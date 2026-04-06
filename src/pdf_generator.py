#!/usr/bin/env python3
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versão:  2.0.0
# Arquivo: pdf_generator.py
# Desc:    Geração do PDF v2 — Executivo, gráficos, comparativo histórico
# =============================================================================

import logging
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.graphics.shapes import (
    Drawing, Rect, String, Circle, Line, Wedge, Group
)
from reportlab.graphics import renderPDF
from models import ClusterReport
from cache import diff_summary

logger = logging.getLogger(__name__)

# ── Paleta OpenLabs ───────────────────────────────────────────────────────────
CP       = colors.HexColor("#0D5C63")   # primary teal
CS       = colors.HexColor("#1A8A94")   # secondary
CA       = colors.HexColor("#3DBAC2")   # accent
CBGH     = colors.HexColor("#0A3E43")   # bg header
CBGL     = colors.HexColor("#F0F7F8")   # bg light
CSUCC    = colors.HexColor("#27AE60")
CWARN    = colors.HexColor("#F39C12")
CDANG    = colors.HexColor("#E74C3C")
CINFO    = colors.HexColor("#2980B9")
CGRAY    = colors.HexColor("#7F8C8D")
CDARK    = colors.HexColor("#1A1A2E")
CTALT    = colors.HexColor("#EAF4F5")   # table alt row
CWHITE   = colors.white
CBLACK   = colors.black

# Paleta gráficos namespace
NS_COLORS = [
    "#0D5C63","#1A8A94","#3DBAC2","#27AE60","#2980B9",
    "#8E44AD","#D35400","#C0392B","#16A085","#2C3E50",
]

W, H = A4
MARGIN = 18 * mm
USABLE = W - 2 * MARGIN


def ST():
    s = {}
    def mk(name, **kw):
        return ParagraphStyle(name, **kw)
    s["title"]    = mk("title",   fontName="Helvetica-Bold", fontSize=20, textColor=CWHITE, leading=26)
    s["sub"]      = mk("sub",     fontName="Helvetica",      fontSize=9,  textColor=CA)
    s["section"]  = mk("section", fontName="Helvetica-Bold", fontSize=12, textColor=CP,
                        spaceBefore=8, spaceAfter=4, leading=16)
    s["normal"]   = mk("normal",  fontName="Helvetica",      fontSize=8,  textColor=CDARK, leading=12)
    s["small"]    = mk("small",   fontName="Helvetica",      fontSize=7,  textColor=CDARK, leading=10)
    s["smallg"]   = mk("smallg",  fontName="Helvetica",      fontSize=7,  textColor=CGRAY, leading=10)
    s["bold"]     = mk("bold",    fontName="Helvetica-Bold", fontSize=8,  textColor=CDARK, leading=12)
    s["bold_s"]   = mk("bold_s",  fontName="Helvetica-Bold", fontSize=7,  textColor=CDARK, leading=10)
    s["center"]   = mk("center",  fontName="Helvetica",      fontSize=8,  alignment=TA_CENTER)
    s["right"]    = mk("right",   fontName="Helvetica",      fontSize=7,  alignment=TA_RIGHT, textColor=CGRAY)
    s["alert_h"]  = mk("alert_h", fontName="Helvetica-Bold", fontSize=10, textColor=CDANG, alignment=TA_CENTER)
    s["exec_val"] = mk("exec_val",fontName="Helvetica-Bold", fontSize=22, textColor=CP,
                        alignment=TA_CENTER, leading=26)
    s["exec_lbl"] = mk("exec_lbl",fontName="Helvetica",      fontSize=7,  textColor=CGRAY, alignment=TA_CENTER)
    s["delta_up"] = mk("delta_up",fontName="Helvetica-Bold", fontSize=8,  textColor=CDANG, alignment=TA_CENTER)
    s["delta_dn"] = mk("delta_dn",fontName="Helvetica-Bold", fontSize=8,  textColor=CSUCC, alignment=TA_CENTER)
    s["delta_eq"] = mk("delta_eq",fontName="Helvetica",      fontSize=8,  textColor=CGRAY, alignment=TA_CENTER)
    return s


def _sc(c: colors.Color) -> str:
    return c.hexval() if hasattr(c, "hexval") else "#888888"


def _status_para(status: str, st: dict) -> Paragraph:
    s = status.upper()
    if s in ("RUNNING","READY","BOUND","ACTIVE","COMPLETE","SUCCEEDED"):
        c = _sc(CSUCC)
    elif s in ("PENDING","TERMINATING","UNKNOWN","PROGRESSING"):
        c = _sc(CWARN)
    elif s in ("FAILED","CRASHLOOPBACKOFF","ERROR","NOTREADY","LOST","OOMKILLED"):
        c = _sc(CDANG)
    else:
        c = _sc(CGRAY)
    return Paragraph(f'<font color="{c}"><b>{status[:22]}</b></font>', st["small"])


def _tbl_style(ncols: int = 1) -> TableStyle:
    return TableStyle([
        ("BACKGROUND",    (0, 0), (-1,  0), CP),
        ("TEXTCOLOR",     (0, 0), (-1,  0), CWHITE),
        ("FONTNAME",      (0, 0), (-1,  0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1,  0), 7),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 7),
        ("TEXTCOLOR",     (0, 1), (-1, -1), CDARK),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [CWHITE, CTALT]),
        ("GRID",          (0, 0), (-1, -1), 0.25, colors.HexColor("#C0D8DA")),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
    ])


# ── Gráficos ──────────────────────────────────────────────────────────────────

def _pie_chart(data: list[tuple[str,int,str]], w=130, h=120, title="") -> Drawing:
    """Mini gráfico de pizza com legenda."""
    d = Drawing(w, h)
    total = sum(v for _, v, _ in data)
    if total == 0:
        d.add(String(w/2, h/2, "Sem dados", textAnchor="middle", fontSize=8, fillColor=CGRAY))
        return d

    cx, cy, r = 50, h/2 - 8, 38
    start = 90  # começa no topo
    for label, val, hex_c in data:
        angle = (val / total) * 360
        w_shape = Wedge(cx, cy, r, start, start + angle,
                        fillColor=colors.HexColor(hex_c),
                        strokeColor=CWHITE, strokeWidth=1)
        d.add(w_shape)
        start += angle

    # Legenda
    lx, ly = 102, h - 14
    for i, (label, val, hex_c) in enumerate(data[:6]):
        pct = val / total * 100
        d.add(Rect(lx, ly - i*14, 8, 8,
                   fillColor=colors.HexColor(hex_c), strokeColor=None))
        d.add(String(lx + 11, ly - i*14 + 1,
                     f"{label[:12]} {pct:.0f}%",
                     fontSize=6.5, fillColor=CDARK, fontName="Helvetica"))

    if title:
        d.add(String(cx, 8, title, textAnchor="middle",
                     fontSize=7, fillColor=CGRAY, fontName="Helvetica"))
    return d


def _bar_chart(data: list[tuple[str,int,int]], w=USABLE, h=90,
               label_a="CPU (m)", label_b="Mem (MiB)") -> Drawing:
    """Gráfico de barras duplas horizontais para top pods."""
    d = Drawing(w, h)
    if not data:
        return d

    lm, rm, tm, bm = 140, 20, 10, 18
    chart_w = w - lm - rm
    chart_h = h - tm - bm
    bar_h = min(10, (chart_h / len(data)) - 2)

    max_a = max((v for _, v, _ in data), default=1) or 1
    max_b = max((v for _, _, v in data), default=1) or 1

    for i, (name, val_a, val_b) in enumerate(data):
        y = bm + (len(data) - 1 - i) * (chart_h / len(data))
        # Label
        d.add(String(lm - 4, y + bar_h/2 - 2,
                     name[:22], textAnchor="end",
                     fontSize=6, fillColor=CDARK, fontName="Helvetica"))
        # Barra A (CPU)
        bw_a = (val_a / max_a) * chart_w * 0.48
        d.add(Rect(lm, y + bar_h/2, bw_a, bar_h/2,
                   fillColor=CP, strokeColor=None))
        # Barra B (Mem)
        bw_b = (val_b / max_b) * chart_w * 0.48
        d.add(Rect(lm + chart_w * 0.52, y + bar_h/2, bw_b, bar_h/2,
                   fillColor=CSUCC, strokeColor=None))

    # Legenda
    d.add(Rect(lm, 4, 8, 6, fillColor=CP, strokeColor=None))
    d.add(String(lm+10, 4, label_a, fontSize=6, fillColor=CDARK))
    d.add(Rect(lm+80, 4, 8, 6, fillColor=CSUCC, strokeColor=None))
    d.add(String(lm+92, 4, label_b, fontSize=6, fillColor=CDARK))
    return d


def _health_bar(score: float, w=200, h=48) -> Drawing:
    d = Drawing(w, h)
    c = CSUCC if score >= 85 else (CWARN if score >= 60 else CDANG)
    d.add(Rect(0, 20, w, 14, fillColor=colors.HexColor("#D5E8E9"),
               strokeColor=None, rx=7, ry=7))
    d.add(Rect(0, 20, score/100*w, 14, fillColor=c,
               strokeColor=None, rx=7, ry=7))
    d.add(String(w/2, 40, "Health Score", textAnchor="middle",
                 fontSize=7, fillColor=CGRAY, fontName="Helvetica"))
    d.add(String(w/2, 3, f"{score}%", textAnchor="middle",
                 fontSize=13, fillColor=_sc(c), fontName="Helvetica-Bold"))
    return d


def _trend_arrow(diff: float, is_bad_when_up=True) -> str:
    if diff > 0:
        return "▲" if is_bad_when_up else "▼"
    if diff < 0:
        return "▼" if is_bad_when_up else "▲"
    return "—"


# ── Seções ────────────────────────────────────────────────────────────────────

def _section_header(title: str, st: dict) -> list:
    return [
        Paragraph(title, st["section"]),
        HRFlowable(width="100%", thickness=0.75, color=CA, spaceAfter=4),
    ]


def _page_executive(report: ClusterReport, st: dict, delta: dict) -> list:
    """Página 1 — Resumo Executivo."""
    story = []
    s = report.summary

    # ── Header ──
    hdr = Table([[
        Paragraph(f"Kubernetes Status Report", st["title"]),
        Paragraph(
            f"Cluster: <b>{report.cluster_name}</b><br/>"
            f"Gerado em: {report.collected_at}<br/>"
            f"OpenLabs — DevOps | Infra", st["sub"]
        ),
    ]], colWidths=[USABLE*0.62, USABLE*0.38],
        style=TableStyle([
            ("BACKGROUND", (0,0),(-1,-1), CBGH),
            ("VALIGN",     (0,0),(-1,-1), "MIDDLE"),
            ("LEFTPADDING",(0,0),(-1,-1), 14),
            ("TOPPADDING", (0,0),(-1,-1), 14),
            ("BOTTOMPADDING",(0,0),(-1,-1), 14),
        ]))
    story.append(hdr)
    story.append(Spacer(1, 8))

    # ── Health + status banner ──
    has_crit = (s.get("nodes_not_ready",0) > 0 or s.get("pods_failed",0) > 0
                or s.get("pvcs_lost",0) > 0 or s.get("pods_crashloop",0) > 0)
    has_warn = (s.get("pods_pending",0) > 0 or s.get("deployments_degraded",0) > 0
                or s.get("warning_events",0) > 5)
    banner_color = CDANG if has_crit else (CWARN if has_warn else CSUCC)
    banner_text  = ("⛔  CRÍTICO — Há falhas que requerem ação imediata" if has_crit
                    else ("⚠  ATENÇÃO — Há itens que requerem monitoramento" if has_warn
                          else "✅  CLUSTER OPERACIONAL"))

    gauge = _health_bar(s.get("health_score", 100), w=180, h=48)

    banner_row = Table([[
        gauge,
        Paragraph(banner_text, ParagraphStyle(
            "", fontName="Helvetica-Bold", fontSize=11,
            textColor=CWHITE, alignment=TA_CENTER
        )),
    ]], colWidths=[200, USABLE-200],
        style=TableStyle([
            ("BACKGROUND", (0,0),(0,0), CBGL),
            ("BACKGROUND", (1,0),(1,0), _sc(banner_color)),
            ("VALIGN",     (0,0),(-1,-1), "MIDDLE"),
            ("ALIGN",      (1,0),(1,0), "CENTER"),
            ("BOX",        (0,0),(0,0), 1, CA),
        ]))
    story.append(banner_row)
    story.append(Spacer(1, 8))

    # ── KPI cards com comparativo ──
    def kpi_card(label, curr, prev_val=None, is_bad_up=True):
        diff_str = ""
        diff_style = st["delta_eq"]
        if prev_val is not None and prev_val != curr:
            diff = curr - prev_val
            arrow = _trend_arrow(diff, is_bad_up)
            diff_str = f"{arrow} {abs(diff)}"
            diff_style = st["delta_up"] if (diff > 0 and is_bad_up) or (diff < 0 and not is_bad_up) else st["delta_dn"]
        cells = [
            [Paragraph(str(curr), st["exec_val"])],
            [Paragraph(label, st["exec_lbl"])],
        ]
        if diff_str:
            cells.append([Paragraph(diff_str, diff_style)])
        return Table(cells, colWidths=[USABLE/6 - 6],
                     style=TableStyle([
                         ("BACKGROUND",(0,0),(-1,-1), CBGL),
                         ("BOX",(0,0),(-1,-1), 1, CA),
                         ("TOPPADDING",(0,0),(-1,-1), 5),
                         ("BOTTOMPADDING",(0,0),(-1,-1), 5),
                         ("VALIGN",(0,0),(-1,-1), "MIDDLE"),
                     ]))

    def _prev(key):
        return delta.get(key, {}).get("previous") if delta else None

    row1 = [
        kpi_card(f"Nodes\n({s['nodes_ready']}/{s['total_nodes']} Ready)",
                 s["nodes_ready"], _prev("nodes_ready"), is_bad_up=False),
        kpi_card("Pods\nTotal", s["total_pods"], _prev("total_pods"), False),
        kpi_card("Running\nPods", s["pods_running"], _prev("pods_running"), False),
        kpi_card("Failed /\nCrashLoop", s["pods_failed"], _prev("pods_failed"), True),
        kpi_card("Deploys\nDegradados", s["deployments_degraded"], _prev("deployments_degraded"), True),
        kpi_card("Warnings\nEvents", s["warning_events"], _prev("warning_events"), True),
    ]
    row2 = [
        kpi_card("Namespaces", s["total_namespaces"], _prev("total_namespaces"), False),
        kpi_card("StatefulSets", s["total_statefulsets"], None, False),
        kpi_card("DaemonSets", s["total_daemonsets"], None, False),
        kpi_card("PVCs Bound\n/ Total", s["pvcs_bound"], _prev("pvcs_bound"), False),
        kpi_card("Ingresses", s["total_ingresses"], None, False),
        kpi_card("HPAs", s["total_hpas"], None, False),
    ]
    col_w = USABLE / 6
    for row in [row1, row2]:
        t = Table([row], colWidths=[col_w]*6,
                  style=TableStyle([
                      ("LEFTPADDING",(0,0),(-1,-1), 3),
                      ("RIGHTPADDING",(0,0),(-1,-1), 3),
                      ("TOPPADDING",(0,0),(-1,-1), 3),
                      ("BOTTOMPADDING",(0,0),(-1,-1), 3),
                  ]))
        story.append(t)
    story.append(Spacer(1, 8))

    # ── Alertas críticos ──
    alerts = []
    if s.get("nodes_not_ready",0):   alerts.append(("CRÍTICO", f"⛔ {s['nodes_not_ready']} Node(s) NOT READY"))
    if s.get("pods_crashloop",0):    alerts.append(("CRÍTICO", f"⛔ {s['pods_crashloop']} Pod(s) em CrashLoopBackOff"))
    if s.get("pods_oom",0):          alerts.append(("CRÍTICO", f"⛔ {s['pods_oom']} Pod(s) OOMKilled"))
    if s.get("pvcs_lost",0):         alerts.append(("CRÍTICO", f"⛔ {s['pvcs_lost']} PVC(s) LOST"))
    if s.get("jobs_failed",0):       alerts.append(("CRÍTICO", f"⛔ {s['jobs_failed']} Job(s) falharam"))
    if s.get("pods_failed",0):       alerts.append(("ATENÇÃO", f"⚠ {s['pods_failed']} Pod(s) FAILED"))
    if s.get("pods_pending",0):      alerts.append(("ATENÇÃO", f"⚠ {s['pods_pending']} Pod(s) PENDING"))
    if s.get("deployments_degraded",0): alerts.append(("ATENÇÃO", f"⚠ {s['deployments_degraded']} Deployment(s) degradado(s)"))
    if s.get("sts_degraded",0):      alerts.append(("ATENÇÃO", f"⚠ {s['sts_degraded']} StatefulSet(s) degradado(s)"))
    if s.get("pods_high_restarts",0): alerts.append(("ATENÇÃO", f"⚠ {s['pods_high_restarts']} Pod(s) com ≥5 restarts"))
    if s.get("warning_events",0) > 5: alerts.append(("INFO", f"ℹ {s['warning_events']} Warning Events recentes"))

    if alerts:
        story.extend(_section_header("Alertas", st))
        alert_rows = [[
            Paragraph(sev, ParagraphStyle("", fontName="Helvetica-Bold", fontSize=7,
                      textColor=CDANG if sev=="CRÍTICO" else (CWARN if sev=="ATENÇÃO" else CINFO))),
            Paragraph(msg, st["normal"]),
        ] for sev, msg in alerts]
        at = Table(alert_rows, colWidths=[60, USABLE-60],
                   style=TableStyle([
                       ("BACKGROUND",(0,0),(-1,-1), colors.HexColor("#FFF8F7")),
                       ("BOX",(0,0),(-1,-1), 1, CDANG),
                       ("GRID",(0,0),(-1,-1), 0.25, colors.HexColor("#F5B7B1")),
                       ("TOPPADDING",(0,0),(-1,-1), 3),
                       ("BOTTOMPADDING",(0,0),(-1,-1), 3),
                       ("LEFTPADDING",(0,0),(-1,-1), 6),
                   ]))
        story.append(at)
        story.append(Spacer(1, 8))

    # ── Comparativo histórico ──
    if delta and report.previous:
        story.extend(_section_header(f"Comparativo — Hoje vs {report.previous.collected_at}", st))
        comp_keys = [
            ("health_score",       "Health Score (%)", False, False),
            ("pods_running",       "Pods Running",     False, False),
            ("pods_failed",        "Pods Failed",      True,  True),
            ("pods_pending",       "Pods Pending",     True,  True),
            ("nodes_not_ready",    "Nodes NotReady",   True,  True),
            ("deployments_degraded","Deploys Degraded",True,  True),
            ("warning_events",     "Warning Events",   True,  True),
        ]
        comp_data = [["Métrica", "Anterior", "Atual", "Δ", "Tendência"]]
        for key, label, higher_is_bad, _ in comp_keys:
            d = delta.get(key, {})
            prev = d.get("previous", "?")
            curr = d.get("current", "?")
            diff = d.get("diff", 0)
            if isinstance(diff, (int, float)):
                if diff == 0:
                    trend = "—"
                    trend_c = _sc(CGRAY)
                elif (diff > 0 and higher_is_bad) or (diff < 0 and not higher_is_bad):
                    trend = f"▲ +{abs(diff)}"
                    trend_c = _sc(CDANG)
                else:
                    trend = f"▼ -{abs(diff)}"
                    trend_c = _sc(CSUCC)
                delta_str = f"{'+' if diff > 0 else ''}{diff}"
            else:
                trend, trend_c, delta_str = "?", _sc(CGRAY), "?"

            comp_data.append([
                Paragraph(label, st["small"]),
                Paragraph(str(prev), st["small"]),
                Paragraph(str(curr), st["bold_s"]),
                Paragraph(delta_str, st["small"]),
                Paragraph(f'<font color="{trend_c}"><b>{trend}</b></font>', st["small"]),
            ])
        ct = Table(comp_data, colWidths=[USABLE*0.38, USABLE*0.15, USABLE*0.15, USABLE*0.15, USABLE*0.17],
                   repeatRows=1)
        ct.setStyle(_tbl_style())
        story.append(ct)
        story.append(Spacer(1, 8))

    # ── Erros de coleta ──
    if report.errors:
        story.append(Paragraph(
            "⚠ Erros de coleta: " + " | ".join(report.errors[:5]),
            ParagraphStyle("", fontName="Helvetica", fontSize=7, textColor=CWARN)
        ))
    return story


def _page_resources(report: ClusterReport, st: dict) -> list:
    """Página 2 — Gráficos de distribuição por namespace + Top pods."""
    story = [PageBreak()]
    s = report.summary

    story.extend(_section_header("Distribuição por Namespace", st))

    # Pie: pods por namespace
    ns_sorted = sorted(report.namespaces, key=lambda n: n.pod_count, reverse=True)
    # Oculta namespaces sem pods para não poluir o relatório
    ns_with_pods = [n for n in ns_sorted if n.pod_count > 0]
    ns_empty     = [n for n in ns_sorted if n.pod_count == 0]
    pie_data = [
        (n.name[:14], n.pod_count, NS_COLORS[i % len(NS_COLORS)])
        for i, n in enumerate(ns_with_pods[:8]) if n.pod_count > 0
    ]
    other = sum(n.pod_count for n in ns_with_pods[8:])
    if other > 0:
        pie_data.append(("outros", other, "#95A5A6"))

    # Pie: status dos pods
    pie_status = []
    if s["pods_running"]:  pie_status.append(("Running", s["pods_running"], "#27AE60"))
    if s["pods_pending"]:  pie_status.append(("Pending", s["pods_pending"], "#F39C12"))
    if s["pods_failed"]:   pie_status.append(("Failed",  s["pods_failed"],  "#E74C3C"))
    succ = s["total_pods"] - s["pods_running"] - s["pods_pending"] - s["pods_failed"]
    if succ > 0:           pie_status.append(("Succeeded",succ,             "#2980B9"))

    pie1 = _pie_chart(pie_data,   w=220, h=130, title="Pods por Namespace")
    pie2 = _pie_chart(pie_status, w=200, h=130, title="Status dos Pods")

    pie_row = Table([[pie1, pie2]], colWidths=[USABLE*0.55, USABLE*0.45],
                    style=TableStyle([
                        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                        ("BACKGROUND",(0,0),(-1,-1),CBGL),
                        ("BOX",(0,0),(-1,-1),1,CA),
                    ]))
    story.append(pie_row)
    story.append(Spacer(1, 10))

    # ── Tabela namespaces com métricas ──
    story.extend(_section_header("Namespaces — Detalhado", st))
    headers = ["Namespace","Status","Pods","Running","Pending","Failed","CPU (m)","Mem (MiB)","Idade"]
    data = [headers]
    for ns in ns_with_pods:
        cpu = str(ns.cpu_usage_m) if ns.cpu_usage_m else "N/A"
        mem = str(ns.mem_usage_mib) if ns.mem_usage_mib else "N/A"
        data.append([
            Paragraph(ns.name, st["small"]),
            _status_para(ns.status, st),
            Paragraph(str(ns.pod_count), st["small"]),
            Paragraph(str(ns.running), st["small"]),
            Paragraph(str(ns.pending), st["small"]),
            Paragraph(str(ns.failed), st["small"]),
            Paragraph(cpu, st["small"]),
            Paragraph(mem, st["small"]),
            Paragraph(ns.age, st["small"]),
        ])
    if ns_empty:
        data.append([
            Paragraph(f"+ {len(ns_empty)} namespaces sem pods omitidos", st["smallg"]),
            *[Paragraph("", st["small"]) for _ in range(8)]
        ])
    widths = [r*USABLE for r in [0.24,0.09,0.07,0.08,0.08,0.07,0.09,0.10,0.07]]
    nt = Table(data, colWidths=widths, repeatRows=1)
    nt.setStyle(_tbl_style())
    story.append(nt)
    story.append(Spacer(1, 10))

    # ── Top pods por recurso ──
    story.extend(_section_header("Top Pods por Consumo de Recurso", st))

    top_cpu = s.get("top_cpu_pods", [])
    top_mem = s.get("top_mem_pods", [])

    if top_cpu or top_mem:
        bar_data = []
        names = list({p["name"] for p in top_cpu[:8]})
        for p in top_cpu[:8]:
            cpu_m = p.get("cpu_m", 0)
            mem_mib = next((x["mem_mib"] for x in top_mem if x["name"]==p["name"]), 0)
            bar_data.append((f"{p['ns']}/{p['name'][:20]}", cpu_m, mem_mib))

        if bar_data:
            bar = _bar_chart(bar_data, w=USABLE, h=100, label_a="CPU (millicores)", label_b="Mem (MiB)")
            story.append(bar)
            story.append(Spacer(1, 6))

    # Tabela top CPU
    if top_cpu:
        story.append(Paragraph("Top 10 — CPU", st["bold"]))
        story.append(Spacer(1,3))
        cpu_data = [["Pod","Namespace","CPU","Millicores"]]
        for p in top_cpu:
            cpu_data.append([
                Paragraph(p["name"][:40], st["small"]),
                Paragraph(p["ns"], st["small"]),
                Paragraph(p["cpu"], st["small"]),
                Paragraph(str(p["cpu_m"]), st["small"]),
            ])
        ct = Table(cpu_data, colWidths=[USABLE*0.45, USABLE*0.25, USABLE*0.15, USABLE*0.15], repeatRows=1)
        ct.setStyle(_tbl_style())
        story.append(ct)
        story.append(Spacer(1, 6))

    # Tabela top Mem
    if top_mem:
        story.append(Paragraph("Top 10 — Memória", st["bold"]))
        story.append(Spacer(1,3))
        mem_data = [["Pod","Namespace","Memória","MiB"]]
        for p in top_mem:
            mem_data.append([
                Paragraph(p["name"][:40], st["small"]),
                Paragraph(p["ns"], st["small"]),
                Paragraph(p["mem"], st["small"]),
                Paragraph(str(p["mem_mib"]), st["small"]),
            ])
        mt = Table(mem_data, colWidths=[USABLE*0.45, USABLE*0.25, USABLE*0.15, USABLE*0.15], repeatRows=1)
        mt.setStyle(_tbl_style())
        story.append(mt)
    return story


def _page_nodes(report: ClusterReport, st: dict) -> list:
    story = [PageBreak()]
    story.extend(_section_header("Nodes do Cluster", st))
    headers = ["Node","Status","Roles","Versão","CPU Cap.","CPU Uso","CPU%","Mem Cap.","Mem Uso","Mem%","Idade"]
    data = [headers]
    for n in report.nodes:
        cp_c = CDANG if n.cpu_pct > 85 else (CWARN if n.cpu_pct > 65 else CSUCC)
        mp_c = CDANG if n.mem_pct > 85 else (CWARN if n.mem_pct > 65 else CSUCC)
        data.append([
            Paragraph(n.name, st["small"]),
            _status_para(n.status, st),
            Paragraph(n.roles, st["smallg"]),
            Paragraph(n.version, st["small"]),
            Paragraph(n.cpu_capacity, st["small"]),
            Paragraph(n.cpu_usage, st["small"]),
            Paragraph(f'<font color="{_sc(cp_c)}"><b>{n.cpu_pct:.0f}%</b></font>', st["small"]) if n.cpu_pct else Paragraph("N/A", st["smallg"]),
            Paragraph(n.mem_capacity, st["small"]),
            Paragraph(n.mem_usage, st["small"]),
            Paragraph(f'<font color="{_sc(mp_c)}"><b>{n.mem_pct:.0f}%</b></font>', st["small"]) if n.mem_pct else Paragraph("N/A", st["smallg"]),
            Paragraph(n.age, st["smallg"]),
        ])
    ws = [r*USABLE for r in [0.17,0.08,0.09,0.10,0.07,0.07,0.06,0.08,0.07,0.06,0.05]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    story.append(Spacer(1, 10))
    return story


def _page_workloads(report: ClusterReport, st: dict) -> list:
    story = [PageBreak()]

    # Deployments
    story.extend(_section_header("Deployments", st))
    dh = ["Deployment","Namespace","Desejado","Pronto","Disponível","Atualizado","Idade"]
    dd = [dh]
    for d in report.deployments:
        ok = d.ready == d.desired and d.desired > 0
        rc = _sc(CSUCC) if ok else _sc(CDANG if d.ready == 0 and d.desired > 0 else CWARN)
        dd.append([
            Paragraph(d.name, st["small"]),
            Paragraph(d.namespace, st["small"]),
            Paragraph(str(d.desired), st["small"]),
            Paragraph(f'<font color="{rc}"><b>{d.ready}</b></font>', st["small"]),
            Paragraph(str(d.available), st["small"]),
            Paragraph(str(d.up_to_date), st["small"]),
            Paragraph(d.age, st["smallg"]),
        ])
    ws = [r*USABLE for r in [0.30,0.20,0.10,0.10,0.10,0.10,0.08]]
    t = Table(dd, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    story.append(Spacer(1, 10))

    # StatefulSets
    if report.statefulsets:
        story.extend(_section_header("StatefulSets", st))
        sh = ["StatefulSet","Namespace","Desejado","Pronto","Idade"]
        sd = [sh]
        for s2 in report.statefulsets:
            ok = s2.ready == s2.desired
            rc = _sc(CSUCC) if ok else _sc(CDANG)
            sd.append([
                Paragraph(s2.name, st["small"]),
                Paragraph(s2.namespace, st["small"]),
                Paragraph(str(s2.desired), st["small"]),
                Paragraph(f'<font color="{rc}"><b>{s2.ready}</b></font>', st["small"]),
                Paragraph(s2.age, st["smallg"]),
            ])
        ws2 = [r*USABLE for r in [0.35,0.25,0.12,0.12,0.10]]
        t2 = Table(sd, colWidths=ws2, repeatRows=1)
        t2.setStyle(_tbl_style())
        story.append(t2)
        story.append(Spacer(1, 10))

    # DaemonSets
    if report.daemonsets:
        story.extend(_section_header("DaemonSets", st))
        dsh = ["DaemonSet","Namespace","Desejado","Pronto","Disponível","Idade"]
        dsd = [dsh]
        for ds in report.daemonsets:
            ok = ds.ready == ds.desired
            rc = _sc(CSUCC) if ok else _sc(CWARN)
            dsd.append([
                Paragraph(ds.name, st["small"]),
                Paragraph(ds.namespace, st["small"]),
                Paragraph(str(ds.desired), st["small"]),
                Paragraph(f'<font color="{rc}"><b>{ds.ready}</b></font>', st["small"]),
                Paragraph(str(ds.available), st["small"]),
                Paragraph(ds.age, st["smallg"]),
            ])
        ws3 = [r*USABLE for r in [0.30,0.22,0.12,0.12,0.12,0.10]]
        t3 = Table(dsd, colWidths=ws3, repeatRows=1)
        t3.setStyle(_tbl_style())
        story.append(t3)
        story.append(Spacer(1, 10))

    # CronJobs + Jobs
    col2 = USABLE / 2 - 4
    row_left, row_right = [], []

    if report.cronjobs:
        row_left.extend(_section_header("CronJobs", st))
        cjh = ["CronJob","Namespace","Schedule","Último","Idade"]
        cjd = [cjh]
        for cj in report.cronjobs:
            cjd.append([
                Paragraph(cj.name[:30], st["small"]),
                Paragraph(cj.namespace[:20], st["small"]),
                Paragraph(cj.schedule, st["smallg"]),
                Paragraph(cj.last_schedule, st["smallg"]),
                Paragraph(cj.age, st["smallg"]),
            ])
        wsc = [r*col2 for r in [0.32,0.26,0.20,0.14,0.08]]
        tc = Table(cjd, colWidths=wsc, repeatRows=1)
        tc.setStyle(_tbl_style())
        row_left.append(tc)

    if report.jobs:
        row_right.extend(_section_header("Jobs", st))
        jh = ["Job","Namespace","Status","Duração","Idade"]
        jd = [jh]
        for j in report.jobs:
            # Filtra jobs de teste do status-report
            if "status-report-test" in j.name:
                continue
            jd.append([
                Paragraph(j.name[:28], st["small"]),
                Paragraph(j.namespace[:18], st["small"]),
                _status_para(j.status, st),
                Paragraph(j.duration, st["smallg"]),
                Paragraph(j.age, st["smallg"]),
            ])
        wsj = [r*col2 for r in [0.32,0.24,0.16,0.16,0.08]]
        tj = Table(jd, colWidths=wsj, repeatRows=1)
        tj.setStyle(_tbl_style())
        row_right.append(tj)

    if row_left or row_right:
        from reportlab.platypus import KeepTogether
        combined = Table([[row_left or [Spacer(1,1)], row_right or [Spacer(1,1)]]],
                         colWidths=[col2, col2],
                         style=TableStyle([
                             ("VALIGN",(0,0),(-1,-1),"TOP"),
                             ("LEFTPADDING",(0,0),(-1,-1),0),
                             ("RIGHTPADDING",(0,0),(-1,-1),0),
                         ]))
        story.append(combined)
    return story


def _page_pods(report: ClusterReport, st: dict) -> list:
    story = [PageBreak()]
    story.extend(_section_header("Pods — Atenção (Falhas / Pending / High Restarts)", st))

    SYSTEM_NS = {"kube-system","kube-node-lease","kube-public","cattle-system",
                 "cattle-fleet-system","cattle-fleet-local-system","cattle-capi-system",
                 "cattle-turtles-system","fleet-default","fleet-local","local","local-path-storage"}

    problem = [p for p in report.pods if (
        p.status not in ("Running", "Succeeded") or
        (p.namespace in SYSTEM_NS and p.restarts >= 20) or
        (p.namespace not in SYSTEM_NS and p.restarts >= 5)
    )]
    if not problem:
        story.append(Paragraph("✅ Nenhum pod com problemas detectado.", st["normal"]))
    else:
        ph = ["Pod","Namespace","Status","Ready","Restarts","CPU","Mem","Node","Idade"]
        pd2 = [ph]
        for p in problem:
            pd2.append([
                Paragraph(p.name[:38], st["small"]),
                Paragraph(p.namespace, st["small"]),
                _status_para(p.status, st),
                Paragraph(p.ready, st["small"]),
                Paragraph(str(p.restarts), st["small"]),
                Paragraph(p.cpu_usage, st["small"]),
                Paragraph(p.mem_usage, st["small"]),
                Paragraph(p.node[:20] if p.node else "?", st["small"]),
                Paragraph(p.age, st["smallg"]),
            ])
        ws = [r*USABLE for r in [0.24,0.13,0.11,0.07,0.07,0.07,0.07,0.16,0.06]]
        t = Table(pd2, colWidths=ws, repeatRows=1)
        t.setStyle(_tbl_style())
        story.append(t)

    story.append(Spacer(1, 10))
    story.extend(_section_header("Pods — Todos (Running / Succeeded)", st))
    normal = [p for p in report.pods if p.status in ("Running","Succeeded") and p.restarts < 5]
    story.append(Paragraph(f"{len(normal)} pods saudáveis (exibindo até 50)", st["smallg"]))
    story.append(Spacer(1, 4))
    ph2 = ["Pod","Namespace","Status","Ready","Restarts","CPU","Mem","Idade"]
    pd3 = [ph2]
    for p in normal[:50]:
        pd3.append([
            Paragraph(p.name[:38], st["small"]),
            Paragraph(p.namespace, st["small"]),
            _status_para(p.status, st),
            Paragraph(p.ready, st["small"]),
            Paragraph(str(p.restarts), st["small"]),
            Paragraph(p.cpu_usage, st["small"]),
            Paragraph(p.mem_usage, st["small"]),
            Paragraph(p.age, st["smallg"]),
        ])
    ws2 = [r*USABLE for r in [0.28,0.15,0.11,0.07,0.07,0.08,0.08,0.07]]
    t2 = Table(pd3, colWidths=ws2, repeatRows=1)
    t2.setStyle(_tbl_style())
    story.append(t2)
    return story


def _page_network_storage(report: ClusterReport, st: dict) -> list:
    story = [PageBreak()]

    # PVCs
    story.extend(_section_header("PersistentVolumeClaims", st))
    pvch = ["PVC","Namespace","Status","Volume","Capacidade","StorageClass","Modo","Idade"]
    pvcd = [pvch]
    for p in report.pvcs:
        pvcd.append([
            Paragraph(p.name, st["small"]),
            Paragraph(p.namespace, st["small"]),
            _status_para(p.status, st),
            Paragraph(p.volume[:28], st["small"]),
            Paragraph(p.capacity, st["small"]),
            Paragraph(p.storage_class, st["small"]),
            Paragraph(p.access_modes[:14], st["smallg"]),
            Paragraph(p.age, st["smallg"]),
        ])
    ws = [r*USABLE for r in [0.20,0.14,0.08,0.20,0.09,0.13,0.10,0.06]]
    t = Table(pvcd, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    story.append(Spacer(1, 10))

    # Ingresses
    if report.ingresses:
        story.extend(_section_header("Ingresses", st))
        ih = ["Ingress","Namespace","Class","Hosts","Address","Ports","Idade"]
        id2 = [ih]
        for i in report.ingresses:
            id2.append([
                Paragraph(i.name, st["small"]),
                Paragraph(i.namespace, st["small"]),
                Paragraph(i.class_name, st["small"]),
                Paragraph(i.hosts[:40], st["small"]),
                Paragraph(i.address[:20], st["small"]),
                Paragraph(i.ports, st["small"]),
                Paragraph(i.age, st["smallg"]),
            ])
        wsi = [r*USABLE for r in [0.18,0.14,0.10,0.28,0.14,0.08,0.07]]
        ti = Table(id2, colWidths=wsi, repeatRows=1)
        ti.setStyle(_tbl_style())
        story.append(ti)
        story.append(Spacer(1, 10))

    # Services (LoadBalancer/NodePort)
    if report.services:
        story.extend(_section_header("Services Expostos (LoadBalancer / NodePort)", st))
        svch = ["Service","Namespace","Tipo","ClusterIP","External IP","Ports","Idade"]
        svcd = [svch]
        for s2 in report.services:
            svcd.append([
                Paragraph(s2.name, st["small"]),
                Paragraph(s2.namespace, st["small"]),
                Paragraph(s2.type, st["small"]),
                Paragraph(s2.cluster_ip, st["small"]),
                Paragraph(s2.external_ip[:22], st["small"]),
                Paragraph(s2.ports[:22], st["small"]),
                Paragraph(s2.age, st["smallg"]),
            ])
        wss = [r*USABLE for r in [0.20,0.14,0.12,0.12,0.16,0.16,0.07]]
        ts = Table(svcd, colWidths=wss, repeatRows=1)
        ts.setStyle(_tbl_style())
        story.append(ts)
        story.append(Spacer(1, 10))

    # HPAs
    if report.hpas:
        story.extend(_section_header("Horizontal Pod Autoscalers", st))
        hh = ["HPA","Namespace","Target","Min","Max","Atual","CPU Target","CPU Atual","Idade"]
        hd = [hh]
        for h in report.hpas:
            at_max = h.current_replicas >= h.max_replicas
            rc = _sc(CWARN) if at_max else _sc(CSUCC)
            hd.append([
                Paragraph(h.name, st["small"]),
                Paragraph(h.namespace, st["small"]),
                Paragraph(h.target[:24], st["small"]),
                Paragraph(str(h.min_replicas), st["small"]),
                Paragraph(str(h.max_replicas), st["small"]),
                Paragraph(f'<font color="{rc}"><b>{h.current_replicas}</b></font>', st["small"]),
                Paragraph(h.cpu_target_pct, st["small"]),
                Paragraph(h.cpu_current_pct, st["small"]),
                Paragraph(h.age, st["smallg"]),
            ])
        wsh = [r*USABLE for r in [0.14,0.12,0.18,0.06,0.06,0.07,0.09,0.09,0.07]]
        th = Table(hd, colWidths=wsh, repeatRows=1)
        th.setStyle(_tbl_style())
        story.append(th)
    return story


def _page_events(report: ClusterReport, st: dict) -> list:
    story = [PageBreak()]
    story.extend(_section_header(f"Warning Events Recentes ({len(report.events)} total)", st))

    if not report.events:
        story.append(Paragraph("✅ Nenhum Warning Event encontrado.", st["normal"]))
        return story

    eh = ["Namespace","Razão","Objeto","Mensagem","Contagem","Visto há"]
    ed = [eh]
    for e in report.events[:60]:
        ed.append([
            Paragraph(e.namespace, st["small"]),
            Paragraph(e.reason[:18], st["small"]),
            Paragraph(e.object[:30], st["small"]),
            Paragraph(e.message[:70], st["small"]),
            Paragraph(str(e.count), st["small"]),
            Paragraph(e.last_seen, st["smallg"]),
        ])
    we = [r*USABLE for r in [0.13,0.12,0.20,0.38,0.08,0.08]]
    t = Table(ed, colWidths=we, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    return story


# ── Template com header/footer ────────────────────────────────────────────────

class _DocTpl(SimpleDocTemplate):
    def __init__(self, filename, report: ClusterReport, **kwargs):
        self.report = report
        super().__init__(filename, **kwargs)

    def afterPage(self):
        c = self.canv
        r = self.report
        # Rodapé
        c.saveState()
        c.setFillColor(CP)
        c.rect(0, 0, W, 11*mm, fill=1, stroke=0)
        c.setFont("Helvetica", 6.5)
        c.setFillColor(CWHITE)
        c.drawString(MARGIN, 4*mm,
            f"OpenLabs — K8s Status Report v2 | Cluster: {r.cluster_name} | {r.collected_at} | Confidencial")
        c.drawRightString(W - MARGIN, 4*mm, f"Página {c.getPageNumber()}")
        c.restoreState()


# ── Entry point ───────────────────────────────────────────────────────────────

def generate_pdf(report: ClusterReport, output_path: str,
                 delta: dict = None) -> str:
    st = ST()
    story = []

    story.extend(_page_executive(report, st, delta or {}))
    story.extend(_page_resources(report, st))
    story.extend(_page_nodes(report, st))
    story.extend(_page_workloads(report, st))
    story.extend(_page_pods(report, st))
    story.extend(_page_network_storage(report, st))
    story.extend(_page_events(report, st))

    doc = _DocTpl(
        output_path, report,
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=16*mm,
    )
    doc.build(story)
    logger.info(f"PDF gerado: {output_path}")
    return output_path
