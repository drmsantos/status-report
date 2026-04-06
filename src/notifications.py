#!/usr/bin/env python3
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versão:  2.0.0
# Arquivo: notifications.py
# Desc:    Envio de notificações — E-mail (O365), Teams Webhook, Slack Webhook
# =============================================================================

import os
import json
import smtplib
import ssl
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
    # E-mail / Office 365
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

    # Teams
    teams_webhook: str = ""

    # Slack
    slack_webhook: str = ""
    slack_channel: str = ""   # ex: #devops-alerts


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


# ── HTML do e-mail ────────────────────────────────────────────────────────────

def _email_html(report: ClusterReport, delta: dict) -> str:
    s = report.summary
    health = s.get("health_score", 100)
    hc = "#27AE60" if health >= 85 else "#F39C12" if health >= 60 else "#E74C3C"

    has_crit = s.get("nodes_not_ready",0) > 0 or s.get("pods_crashloop",0) > 0 or s.get("pvcs_lost",0) > 0
    has_warn = s.get("pods_pending",0) > 0 or s.get("deployments_degraded",0) > 0
    banner_c = "#E74C3C" if has_crit else ("#F39C12" if has_warn else "#27AE60")
    banner_t = ("⛔ CRÍTICO — Falhas detectadas" if has_crit
                else ("⚠ ATENÇÃO — Verificação necessária" if has_warn
                      else "✅ Cluster Operacional"))

    # Alertas
    alert_items = []
    if s.get("nodes_not_ready",0):     alert_items.append(f"⛔ {s['nodes_not_ready']} Node(s) NOT READY")
    if s.get("pods_crashloop",0):      alert_items.append(f"⛔ {s['pods_crashloop']} Pod(s) CrashLoopBackOff")
    if s.get("pods_oom",0):            alert_items.append(f"⛔ {s['pods_oom']} Pod(s) OOMKilled")
    if s.get("pvcs_lost",0):           alert_items.append(f"⛔ {s['pvcs_lost']} PVC(s) LOST")
    if s.get("pods_failed",0):         alert_items.append(f"⚠ {s['pods_failed']} Pod(s) FAILED")
    if s.get("pods_pending",0):        alert_items.append(f"⚠ {s['pods_pending']} Pod(s) PENDING")
    if s.get("deployments_degraded",0):alert_items.append(f"⚠ {s['deployments_degraded']} Deployment(s) degradado(s)")
    if s.get("pods_high_restarts",0):  alert_items.append(f"⚠ {s['pods_high_restarts']} Pod(s) com ≥5 restarts")

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

    # KPIs
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
          <div style="font-size:34px;font-weight:bold;color:{hc};">{health}%</div>
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
              {kpi(f"{s['pvcs_bound']}/{s['total_pvcs']}", "PVCs Bound", "#27AE60" if s['pvcs_lost']==0 else "#E74C3C")}
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
    hc = "Good" if health >= 85 else ("Warning" if health >= 60 else "Attention")

    facts = [
        {"name": "Health Score", "value": f"{health}%"},
        {"name": "Nodes Ready", "value": f"{s['nodes_ready']}/{s['total_nodes']}"},
        {"name": "Pods Running", "value": str(s['pods_running'])},
        {"name": "Pods Failed",  "value": str(s['pods_failed'])},
        {"name": "Pods Pending", "value": str(s['pods_pending'])},
        {"name": "Deploys Degradados", "value": str(s['deployments_degraded'])},
        {"name": "Warning Events", "value": str(s['warning_events'])},
        {"name": "PVCs Lost", "value": str(s['pvcs_lost'])},
    ]

    has_crit = s.get("nodes_not_ready",0) > 0 or s.get("pods_crashloop",0) > 0
    theme_c  = "attention" if has_crit else ("warning" if health < 85 else "good")

    # Adaptive Card (Teams)
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


def send_teams(report: ClusterReport, webhook_url: str) -> bool:
    if not webhook_url:
        return False
    try:
        payload = _teams_card(report)
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

    fields = [
        {"title": "Nodes Ready",       "value": f"{s['nodes_ready']}/{s['total_nodes']}", "short": True},
        {"title": "Pods Running",       "value": str(s['pods_running']),                   "short": True},
        {"title": "Pods Failed",        "value": str(s['pods_failed']),                    "short": True},
        {"title": "Deploys Degradados", "value": str(s['deployments_degraded']),           "short": True},
        {"title": "Warning Events",     "value": str(s['warning_events']),                 "short": True},
        {"title": "PVCs Lost",          "value": str(s['pvcs_lost']),                      "short": True},
    ]
    payload = {
        "attachments": [{
            "color":  color,
            "pretext": f"{emoji} *K8s Status Report — {report.cluster_name}*",
            "text":   f"Health Score: *{health}%* | Gerado em: {report.collected_at}",
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
    has_crit = s.get("nodes_not_ready",0) > 0 or s.get("pods_crashloop",0) > 0
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
    """Determina se há razão para enviar alerta no modo watch."""
    s = report.summary
    reasons = []

    if s.get("nodes_not_ready",0) > 0:
        reasons.append(f"Node NOT READY ({s['nodes_not_ready']})")
    if s.get("pods_crashloop",0) > 0:
        reasons.append(f"CrashLoopBackOff ({s['pods_crashloop']} pods)")
    if s.get("pods_oom",0) > 0:
        reasons.append(f"OOMKilled ({s['pods_oom']} pods)")
    if s.get("pvcs_lost",0) > 0:
        reasons.append(f"PVC LOST ({s['pvcs_lost']})")
    if s.get("jobs_failed",0) > 0:
        reasons.append(f"Job falhou ({s['jobs_failed']})")

    # Detecta novos problemas comparando com snapshot anterior
    if prev_summary:
        new_failed = s.get("pods_failed",0) - prev_summary.get("pods_failed",0)
        new_pending = s.get("pods_pending",0) - prev_summary.get("pods_pending",0)
        if new_failed > 0:
            reasons.append(f"+{new_failed} pod(s) novos em FAILED")
        if new_pending > 3:
            reasons.append(f"+{new_pending} pod(s) novos em PENDING")

    return len(reasons) > 0, reasons
