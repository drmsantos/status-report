#!/usr/bin/env python3
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versão:  2.2.0
# Arquivo: notifications.py
# Desc:    Envio de notificações — E-mail (O365), Teams Webhook, Slack Webhook
# Changelog v2.1.0:
#   - PVC Pending alert integrado nos alertas de e-mail/Teams/Slack
#   - Health trend (↑↓→) no e-mail e Teams card
#   - Slack melhorado: campos PVC Pending + trend
#   - should_alert: detecta PVC Pending prolongado
# =============================================================================

import os
import json
import smtplib
import ssl
import base64
import logging
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import formatdate
from dataclasses import dataclass, field
from typing import Optional
from models import ClusterReport

logger = logging.getLogger(__name__)


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class NotificationConfig:
    smtp_host:     str = "smtp.office365.com"
    smtp_port:     int = 587
    smtp_user:     str = ""
    smtp_password: str = ""
    from_name:     str = "OpenLabs DevOps"
    from_email:    str = ""
    to:            list = field(default_factory=list)
    cc:            list = field(default_factory=list)
    bcc:           list = field(default_factory=list)
    reply_to:      str = ""
    teams_webhook: str = ""
    slack_webhook: str = ""
    slack_channel: str = ""


def load_config() -> NotificationConfig:
    cfg = NotificationConfig()
    cfg.smtp_host     = os.getenv("SMTP_HOST", "smtp.office365.com")
    cfg.smtp_port     = int(os.getenv("SMTP_PORT", "587"))
    cfg.smtp_user     = os.getenv("SMTP_USER", "")
    cfg.smtp_password = os.getenv("SMTP_PASSWORD", "")
    cfg.from_name     = os.getenv("SMTP_FROM_NAME", "OpenLabs DevOps")
    cfg.from_email    = os.getenv("SMTP_FROM_EMAIL", cfg.smtp_user)
    cfg.to            = [e.strip() for e in os.getenv("EMAIL_TO", "").split(",") if e.strip()]
    cfg.cc            = [e.strip() for e in os.getenv("EMAIL_CC", "").split(",") if e.strip()]
    cfg.bcc           = [e.strip() for e in os.getenv("EMAIL_BCC", "").split(",") if e.strip()]
    cfg.reply_to      = os.getenv("EMAIL_REPLY_TO", "")
    cfg.teams_webhook = os.getenv("TEAMS_WEBHOOK_URL", "")
    cfg.slack_webhook = os.getenv("SLACK_WEBHOOK_URL", "")
    cfg.slack_channel = os.getenv("SLACK_CHANNEL", "")
    return cfg


# ── Helpers ────────────────────────────────────────────────────────────────────

def _trend_str(summary: dict) -> str:
    """Retorna string de trend ex: '↑ +1.5%', '↓ -2.0%', '→ estável'"""
    trend = summary.get("health_trend")
    delta = summary.get("health_delta")
    if trend is None:
        return ""
    if trend == "up":
        return f"↑ +{delta}%"
    if trend == "down":
        return f"↓ {delta}%"
    return "→ estável"


def _build_alert_items(s: dict) -> list[str]:
    """Constrói lista de alertas unificada incluindo PVC Pending."""
    items = []
    if s.get("nodes_not_ready", 0):
        items.append(f"⛔ {s['nodes_not_ready']} Node(s) NOT READY")
    if s.get("pods_crashloop", 0):
        items.append(f"⛔ {s['pods_crashloop']} Pod(s) CrashLoopBackOff")
    if s.get("pods_oom", 0):
        items.append(f"⛔ {s['pods_oom']} Pod(s) OOMKilled")
    if s.get("pvcs_lost", 0):
        items.append(f"⛔ {s['pvcs_lost']} PVC(s) LOST")
    # PVC Pending prolongado — alerta crítico
    if s.get("pvcs_pending_alert", 0):
        pvc_list = s.get("pvcs_pending_alert_list", [])
        names = ", ".join(f"{p['ns']}/{p['name']}" for p in pvc_list[:3])
        items.append(f"⛔ {s['pvcs_pending_alert']} PVC(s) PENDING prolongado: {names}")
    if s.get("pods_failed", 0):
        items.append(f"⚠ {s['pods_failed']} Pod(s) FAILED")
    if s.get("pods_pending", 0):
        items.append(f"⚠ {s['pods_pending']} Pod(s) PENDING")
    if s.get("deployments_degraded", 0):
        items.append(f"⚠ {s['deployments_degraded']} Deployment(s) degradado(s)")
    if s.get("pods_high_restarts", 0):
        items.append(f"⚠ {s['pods_high_restarts']} Pod(s) com restarts elevados")
    return items


# ── HTML do e-mail ────────────────────────────────────────────────────────────

def _email_html(report: ClusterReport, delta: dict) -> str:
    s = report.summary
    health = s.get("health_score", 100)
    hc = "#27AE60" if health >= 85 else "#F39C12" if health >= 60 else "#E74C3C"

    has_crit = (s.get("nodes_not_ready", 0) > 0 or s.get("pods_crashloop", 0) > 0
                or s.get("pvcs_lost", 0) > 0 or s.get("pvcs_pending_alert", 0) > 0)
    has_warn = s.get("pods_pending", 0) > 0 or s.get("deployments_degraded", 0) > 0
    banner_c = "#E74C3C" if has_crit else ("#F39C12" if has_warn else "#27AE60")
    banner_t = ("⛔ CRÍTICO — Falhas detectadas" if has_crit
                else ("⚠ ATENÇÃO — Verificação necessária" if has_warn
                      else "✅ Cluster Operacional"))

    trend_s = _trend_str(s)
    trend_html = ""
    if trend_s:
        tc = "#27AE60" if "↑" in trend_s else ("#E74C3C" if "↓" in trend_s else "#888")
        trend_html = f' <span style="color:{tc};font-size:13px;">{trend_s}</span>'

    alert_items = _build_alert_items(s)
    alerts_html = ""
    if alert_items:
        items_html = "".join(f"<li style='padding:2px 0;'>{a}</li>" for a in alert_items)
        alerts_html = f"""
        <div style="margin:16px 0;padding:12px 16px;background:#FFF5F5;border-left:4px solid #E74C3C;border-radius:4px;">
          <b style="color:#E74C3C;">Alertas Ativos</b>
          <ul style="margin:6px 0 0;padding-left:18px;color:#333;font-size:13px;">{items_html}</ul>
        </div>"""

    # Comparativo
    comp_html = ""
    if delta and report.previous:
        rows = ""
        keys = [("health_score","Health Score",False),("pods_running","Pods Running",False),
                ("pods_failed","Pods Failed",True),("deployments_degraded","Deploys Degradados",True),
                ("pvcs_pending_alert","PVCs Pending Alert",True),
                ("warning_events","Warning Events",True)]
        for key, label, bad_up in keys:
            d = delta.get(key, {})
            diff = d.get("diff", 0)
            prev = d.get("previous", "?")
            curr = d.get("current", "?")
            if isinstance(diff, (int,float)) and diff != 0:
                is_bad = (diff > 0 and bad_up) or (diff < 0 and not bad_up)
                arrow  = "▲" if diff > 0 else "▼"
                color  = "#E74C3C" if is_bad else "#27AE60"
                delta_s = f'<span style="color:{color};font-weight:bold;">{arrow} {abs(diff)}</span>'
            else:
                delta_s = '<span style="color:#999;">—</span>'
            rows += f"<tr><td style='padding:4px 8px;'>{label}</td><td style='padding:4px 8px;color:#888;'>{prev}</td><td style='padding:4px 8px;font-weight:bold;'>{curr}</td><td style='padding:4px 8px;'>{delta_s}</td></tr>"

        comp_html = f"""
        <h3 style="color:#0D5C63;margin:20px 0 8px;">Comparativo — vs {report.previous.collected_at}</h3>
        <table style="border-collapse:collapse;width:100%;font-size:13px;">
          <thead><tr style="background:#0D5C63;color:white;">
            <th style="padding:5px 8px;text-align:left;">Métrica</th>
            <th style="padding:5px 8px;text-align:left;">Anterior</th>
            <th style="padding:5px 8px;text-align:left;">Atual</th>
            <th style="padding:5px 8px;text-align:left;">Δ</th>
          </tr></thead><tbody>{rows}</tbody></table>"""

    def kpi(val, label, color="#0D5C63"):
        return f"""<td width="16%" style="background:#F0F7F8;border-radius:6px;padding:10px;text-align:center;border:1px solid #C0D8DA;">
            <div style="font-size:22px;font-weight:bold;color:{color};">{val}</div>
            <div style="color:#7F8C8D;font-size:11px;">{label}</div></td>"""

    nready_c = "#27AE60" if s["nodes_not_ready"]==0 else "#E74C3C"
    fail_c   = "#27AE60" if s["pods_failed"]==0 else "#E74C3C"
    deg_c    = "#27AE60" if s["deployments_degraded"]==0 else "#F39C12"

    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F4F7F8;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F7F8;">
<tr><td align="center" style="padding:24px 12px;">
<table width="660" cellpadding="0" cellspacing="0" style="background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">
  <tr><td style="background:#0A3E43;padding:22px 32px;">
    <h1 style="margin:0;color:white;font-size:20px;">☸ Kubernetes Status Report v2</h1>
    <p style="margin:6px 0 0;color:#3DBAC2;font-size:12px;">Cluster: <b>{report.cluster_name}</b> &nbsp;|&nbsp; {report.collected_at}</p>
  </td></tr>
  <tr><td style="background:{banner_c};padding:9px 32px;color:white;font-size:13px;font-weight:bold;">{banner_t}</td></tr>
  <tr><td style="padding:22px 32px;">
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:4px;">
      <tr>
        <td width="20%" align="center" style="background:#F0F7F8;border-radius:8px;padding:14px;border:1px solid #C0D8DA;">
          <div style="font-size:34px;font-weight:bold;color:{hc};">{health}%{trend_html}</div>
          <div style="font-size:11px;color:#7F8C8D;">Health Score</div>
        </td>
        <td width="4%"></td>
        <td width="76%">
          <table width="100%" cellpadding="4" cellspacing="4">
            <tr>
              {kpi(f"{s['nodes_ready']}/{s['total_nodes']}", "Nodes Ready", nready_c)}
              {kpi(s['pods_running'], "Running", "#27AE60")}
              {kpi(s['pods_failed'], "Failed", fail_c)}
              {kpi(s['pods_pending'], "Pending", "#F39C12" if s['pods_pending'] else "#27AE60")}
              {kpi(f"{s['deployments_ok']}/{s['total_deployments']}", "Deploys OK", deg_c)}
              {kpi(s['warning_events'], "Warnings", "#E74C3C" if s['warning_events']>5 else "#27AE60")}
            </tr>
            <tr>
              {kpi(s['total_namespaces'], "Namespaces")}
              {kpi(s['total_statefulsets'], "StatefulSets")}
              {kpi(s['total_daemonsets'], "DaemonSets")}
              {kpi(f"{s['pvcs_bound']}/{s['total_pvcs']}", "PVCs Bound",
                   "#E74C3C" if (s['pvcs_lost']>0 or s.get('pvcs_pending_alert',0)>0) else "#27AE60")}
              {kpi(s['total_ingresses'], "Ingresses")}
              {kpi(s['total_hpas'], "HPAs")}
            </tr>
          </table>
        </td>
      </tr>
    </table>
    {alerts_html}
    {comp_html}
    <p style="margin:20px 0 0;font-size:12px;color:#7F8C8D;">📎 Relatório completo em PDF anexado.</p>
  </td></tr>
  <tr><td style="background:#0D5C63;padding:12px 32px;text-align:center;">
    <p style="margin:0;color:#3DBAC2;font-size:11px;">OpenLabs — DevOps | Infra &nbsp;|&nbsp; diego-f-santos@openlabs.com.br</p>
  </td></tr>
</table></td></tr></table></body></html>"""


# ── Teams ─────────────────────────────────────────────────────────────────────

def _teams_card(report: ClusterReport) -> dict:
    s = report.summary
    health = s.get("health_score", 100)
    trend_s = _trend_str(s)

    has_crit = (s.get("nodes_not_ready", 0) > 0 or s.get("pods_crashloop", 0) > 0
                or s.get("pvcs_pending_alert", 0) > 0)
    theme_c  = "attention" if has_crit else ("warning" if health < 85 else "good")

    health_str = f"{health}%"
    if trend_s:
        health_str += f"  {trend_s}"

    facts = [
        {"name": "Health Score",       "value": health_str},
        {"name": "Nodes Ready",        "value": f"{s['nodes_ready']}/{s['total_nodes']}"},
        {"name": "Pods Running",        "value": str(s['pods_running'])},
        {"name": "Pods Failed",         "value": str(s['pods_failed'])},
        {"name": "Pods Pending",        "value": str(s['pods_pending'])},
        {"name": "Deploys Degradados",  "value": str(s['deployments_degraded'])},
        {"name": "Warning Events",      "value": str(s['warning_events'])},
        {"name": "PVCs Lost",           "value": str(s['pvcs_lost'])},
    ]

    # Adiciona PVC Pending se houver
    if s.get("pvcs_pending_alert", 0):
        pvc_list = s.get("pvcs_pending_alert_list", [])
        names = ", ".join(f"{p['ns']}/{p['name']}" for p in pvc_list[:3])
        facts.append({"name": "⛔ PVCs Pending", "value": f"{s['pvcs_pending_alert']} — {names}"})

    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": f"☸ K8s Status Report — {report.cluster_name}",
                        "weight": "Bolder",
                        "size": "Large",
                        "color": theme_c,
                    },
                    {
                        "type": "TextBlock",
                        "text": f"Gerado em: {report.collected_at}",
                        "isSubtle": True,
                        "size": "Small",
                    },
                    {"type": "FactSet", "facts": facts},
                ],
            },
        }],
    }


def _is_power_automate(url: str) -> bool:
    """Detecta se a URL é do Power Automate (não connector nativo do Teams)."""
    return any(x in url for x in [
        "powerautomate", "powerplatform", "logic.azure.com"
    ])


def _teams_pa_payload(report: ClusterReport, pdf_path: str = "") -> dict:
    """Payload rico para Power Automate — inclui HTML do card + PDF base64."""
    s = report.summary
    health = s.get("health_score", 100)
    trend_s = _trend_str(s)
    has_crit = (s.get("nodes_not_ready", 0) > 0
                or s.get("pods_crashloop", 0) > 0
                or s.get("pvcs_pending_alert", 0) > 0)
    status = "CRITICO" if has_crit else ("ATENCAO" if health < 85 else "OK")
    status_color = "#C0392B" if has_crit else ("#F39C12" if health < 85 else "#27AE60")
    health_color = "#E74C3C" if health < 60 else ("#F39C12" if health < 85 else "#27AE60")

    pvc_list = s.get("pvcs_pending_alert_list", [])
    pvc_names = ", ".join(f"{p['ns']}/{p['name']}" for p in pvc_list[:3])

    # Alertas para o card
    alerts = []
    if s.get("pods_crashloop", 0):
        alerts.append(f"🔴 {s['pods_crashloop']} Pod(s) em CrashLoopBackOff")
    if s.get("pvcs_pending_alert", 0):
        alerts.append(f"🔴 {s['pvcs_pending_alert']} PVC(s) PENDING: {pvc_names}")
    if s.get("pods_failed", 0):
        alerts.append(f"⚠️ {s['pods_failed']} Pod(s) FAILED")
    if s.get("deployments_degraded", 0):
        alerts.append(f"⚠️ {s['deployments_degraded']} Deployment(s) degradado(s)")
    if s.get("pods_high_restarts", 0):
        alerts.append(f"⚠️ {s['pods_high_restarts']} Pod(s) com restarts elevados")
    alerts_html = "".join(f"<li>{a}</li>" for a in alerts) if alerts else "<li>Nenhum alerta</li>"

    # KPIs
    kpis = [
        (f"{s.get('nodes_ready',0)}/{s.get('total_nodes',0)}", "Nodes Ready"),
        (str(s.get("pods_running", 0)),  "Running"),
        (str(s.get("pods_failed", 0)),   "Failed"),
        (str(s.get("pods_pending", 0)),  "Pending"),
        (f"{s.get('deployments_ok',0)}/{s.get('total_deployments',0)}", "Deploys OK"),
        (str(s.get("warning_events", 0)), "Warnings"),
    ]
    kpis_html = "".join(
        f'''<td style="text-align:center;padding:8px 12px;border-right:1px solid #e0e0e0">
            <div style="font-size:18px;font-weight:600;color:#1a1a2e">{v}</div>
            <div style="font-size:11px;color:#666;margin-top:2px">{l}</div>
        </td>''' for v, l in kpis
    )

    html_card = f"""<html><body style="margin:0;padding:0;font-family:Arial,sans-serif;background:#f4f7f8">
<table width="600" cellpadding="0" cellspacing="0" style="margin:0 auto;background:#fff;border-radius:8px;overflow:hidden">
  <tr><td style="background:#1a1a2e;padding:16px 20px">
    <span style="color:#fff;font-size:16px;font-weight:600">&#9881; Kubernetes Status Report v2</span><br>
    <span style="color:#aab;font-size:12px">Cluster: {report.cluster_name} &nbsp;|&nbsp; {report.collected_at}</span>
  </td></tr>
  <tr><td style="background:{status_color};padding:10px 20px;color:#fff;font-weight:600;font-size:13px">
    — {status} — {"Falhas detectadas" if has_crit else ("Atenção necessária" if health < 85 else "Tudo operacional")}
  </td></tr>
  <tr><td style="padding:16px 20px">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="100" style="vertical-align:middle">
          <div style="font-size:36px;font-weight:700;color:{health_color}">{health}%</div>
          <div style="font-size:11px;color:#666">Health Score {trend_s or "→"}</div>
        </td>
        <td><table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e0e0e0;border-radius:6px;overflow:hidden">
          <tr style="background:#f9f9f9">{kpis_html}</tr>
        </table></td>
      </tr>
    </table>
  </td></tr>
  <tr><td style="padding:0 20px 16px">
    <div style="background:#fff8f8;border-left:4px solid #C0392B;padding:10px 14px;border-radius:4px">
      <div style="font-size:13px;font-weight:600;color:#C0392B;margin-bottom:6px">Alertas Ativos</div>
      <ul style="margin:0;padding-left:18px;font-size:12px;color:#333">{alerts_html}</ul>
    </div>
  </td></tr>
  <tr><td style="padding:10px 20px;border-top:1px solid #eee;font-size:11px;color:#999;text-align:center">
    OpenLabs — DevOps | Infra &nbsp;|&nbsp; Relatório completo em PDF anexado.
  </td></tr>
</table></body></html>"""

    # PDF em base64
    pdf_b64 = ""
    pdf_filename = ""
    if pdf_path:
        try:
            import os
            with open(pdf_path, "rb") as f:
                pdf_b64 = base64.b64encode(f.read()).decode("utf-8")
            pdf_filename = os.path.basename(pdf_path)
        except Exception:
            pass

    return {
        "cluster":              report.cluster_name,
        "collected_at":         report.collected_at,
        "health_score":         f"{health}%",
        "health_trend":         trend_s or "→",
        "status":               status,
        "status_color":         status_color,
        "nodes_ready":          f"{s.get('nodes_ready',0)}/{s.get('total_nodes',0)}",
        "pods_running":         s.get("pods_running", 0),
        "pods_failed":          s.get("pods_failed", 0),
        "pods_pending":         s.get("pods_pending", 0),
        "pods_crashloop":       s.get("pods_crashloop", 0),
        "deployments_degraded": s.get("deployments_degraded", 0),
        "warning_events":       s.get("warning_events", 0),
        "pvcs_pending":         s.get("pvcs_pending_alert", 0),
        "pvcs_pending_list":    pvc_names,
        "pvcs_lost":            s.get("pvcs_lost", 0),
        "alerts":               alerts,
        "html_card":            html_card,
        "pdf_base64":           pdf_b64,
        "pdf_filename":         pdf_filename,
    }


def send_teams(report: ClusterReport, webhook_url: str, pdf_path: str = "") -> bool:
    if not webhook_url:
        return False
    try:
        if _is_power_automate(webhook_url):
            payload = _teams_pa_payload(report, pdf_path=pdf_path)
            logger.debug("Teams: usando payload Power Automate")
        else:
            payload = _teams_card(report)
            logger.debug("Teams: usando Adaptive Card (connector nativo)")
        r = requests.post(webhook_url, json=payload, timeout=15)
        if r.status_code in (200, 202):
            logger.info("Teams: notificação enviada")
            return True
        logger.warning(f"Teams: status {r.status_code} — {r.text[:100]}")
        return False
    except Exception as e:
        logger.error(f"Teams: erro — {e}")
        return False


# ── Slack ─────────────────────────────────────────────────────────────────────

def _slack_payload(report: ClusterReport) -> dict:
    s = report.summary
    health = s.get("health_score", 100)
    emoji  = "✅" if health >= 85 else ("⚠️" if health >= 60 else "🚨")
    color  = "#27AE60" if health >= 85 else ("#F39C12" if health >= 60 else "#E74C3C")
    trend_s = _trend_str(s)

    health_text = f"*{health}%*"
    if trend_s:
        health_text += f"  {trend_s}"

    fields = [
        {"title": "Nodes Ready",        "value": f"{s['nodes_ready']}/{s['total_nodes']}", "short": True},
        {"title": "Pods Running",        "value": str(s['pods_running']),                   "short": True},
        {"title": "Pods Failed",         "value": str(s['pods_failed']),                    "short": True},
        {"title": "Deploys Degradados",  "value": str(s['deployments_degraded']),           "short": True},
        {"title": "Warning Events",      "value": str(s['warning_events']),                 "short": True},
        {"title": "PVCs Lost",           "value": str(s['pvcs_lost']),                      "short": True},
    ]

    # PVC Pending alert
    if s.get("pvcs_pending_alert", 0):
        pvc_list = s.get("pvcs_pending_alert_list", [])
        names = ", ".join(f"{p['ns']}/{p['name']}" for p in pvc_list[:2])
        fields.append({
            "title": "⛔ PVCs Pending",
            "value": f"{s['pvcs_pending_alert']} — {names}",
            "short": False,
        })

    # Pods com restart alto — resumo
    if s.get("pods_high_restarts", 0):
        high = s.get("high_restart_pods", [])
        summary_str = ", ".join(
            f"{p['name'][:20]} ({p['restarts']}r, last {p.get('last_restart','?')})"
            for p in high[:3]
        )
        fields.append({
            "title": f"⚠ High Restarts ({s['pods_high_restarts']})",
            "value": summary_str,
            "short": False,
        })

    payload = {
        "attachments": [{
            "color":  color,
            "pretext": f"{emoji} *K8s Status Report — {report.cluster_name}*",
            "text":   f"Health Score: {health_text} | Gerado em: {report.collected_at}",
            "fields": fields,
            "footer": "OpenLabs DevOps | Infra",
            "ts":     int(__import__("time").time()),
        }],
    }
    return payload


def send_slack(report: ClusterReport, webhook_url: str, channel: str = "") -> bool:
    if not webhook_url:
        return False
    try:
        payload = _slack_payload(report)
        if channel:
            payload["channel"] = channel
        r = requests.post(webhook_url, json=payload, timeout=15)
        if r.status_code == 200:
            logger.info("Slack: notificação enviada")
            return True
        logger.warning(f"Slack: status {r.status_code} — {r.text[:100]}")
        return False
    except Exception as e:
        logger.error(f"Slack: erro — {e}")
        return False


# ── E-mail ────────────────────────────────────────────────────────────────────

def send_email(report: ClusterReport, pdf_path: str,
               cfg: NotificationConfig, delta: dict = None) -> bool:
    if not cfg.smtp_user or not cfg.to:
        logger.error("E-mail: SMTP_USER ou EMAIL_TO não configurados")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"]    = f"{cfg.from_name} <{cfg.from_email or cfg.smtp_user}>"
    msg["To"]      = ", ".join(cfg.to)
    msg["Date"]    = formatdate(localtime=True)
    msg["Subject"] = f"[K8s] Status Report — {report.cluster_name} — {report.collected_at}"

    s = report.summary
    has_crit = (s.get("nodes_not_ready", 0) > 0 or s.get("pods_crashloop", 0) > 0
                or s.get("pvcs_pending_alert", 0) > 0)
    if has_crit:
        msg["X-Priority"] = "1"
        msg["X-MSMail-Priority"] = "High"

    if cfg.cc:
        msg["Cc"] = ", ".join(cfg.cc)
    if cfg.reply_to:
        msg["Reply-To"] = cfg.reply_to

    msg.attach(MIMEText(_email_html(report, delta or {}), "html", "utf-8"))

    try:
        with open(pdf_path, "rb") as f:
            att = MIMEApplication(f.read(), _subtype="pdf")
        att.add_header("Content-Disposition", "attachment",
                        filename=__import__("os").path.basename(pdf_path))
        msg.attach(att)
    except Exception as e:
        logger.error(f"E-mail: erro ao anexar PDF — {e}")
        return False

    all_rcpt = cfg.to + cfg.cc + cfg.bcc
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as srv:
            srv.ehlo()
            srv.starttls(context=ctx)
            srv.ehlo()
            srv.login(cfg.smtp_user, cfg.smtp_password)
            srv.sendmail(cfg.smtp_user, all_rcpt, msg.as_string())
        logger.info(f"E-mail: enviado para {', '.join(cfg.to)}")
        return True
    except Exception as e:
        logger.error(f"E-mail: falha — {e}")
        return False


# ── Watch mode helpers ────────────────────────────────────────────────────────

def should_alert(report: ClusterReport, prev_summary: dict = None) -> tuple[bool, list[str]]:
    s = report.summary
    reasons = []

    if s.get("nodes_not_ready", 0) > 0:
        reasons.append(f"Node NOT READY ({s['nodes_not_ready']})")
    if s.get("pods_crashloop", 0) > 0:
        reasons.append(f"CrashLoopBackOff ({s['pods_crashloop']} pods)")
    if s.get("pods_oom", 0) > 0:
        reasons.append(f"OOMKilled ({s['pods_oom']} pods)")
    if s.get("pvcs_lost", 0) > 0:
        reasons.append(f"PVC LOST ({s['pvcs_lost']})")
    if s.get("pvcs_pending_alert", 0) > 0:
        reasons.append(f"PVC PENDING prolongado ({s['pvcs_pending_alert']})")
    if s.get("jobs_failed", 0) > 0:
        reasons.append(f"Job falhou ({s['jobs_failed']})")

    if prev_summary:
        new_failed = s.get("pods_failed", 0) - prev_summary.get("pods_failed", 0)
        new_pending = s.get("pods_pending", 0) - prev_summary.get("pods_pending", 0)
        if new_failed > 0:
            reasons.append(f"+{new_failed} pod(s) novos em FAILED")
        if new_pending > 3:
            reasons.append(f"+{new_pending} pod(s) novos em PENDING")
        # Health degradou muito
        prev_score = prev_summary.get("health_score", 100)
        curr_score = s.get("health_score", 100)
        if prev_score - curr_score >= 5:
            reasons.append(f"Health degradou {prev_score - curr_score:.1f}% ({prev_score}% → {curr_score}%)")

    return len(reasons) > 0, reasons
