
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
from reportlab.graphics.shapes import Drawing, Rect, String, Wedge, Line
from models import ClusterReport
from cache import diff_summary

logger = logging.getLogger(__name__)

CP    = colors.HexColor("#0D5C63")
CS    = colors.HexColor("#1A8A94")
CA    = colors.HexColor("#3DBAC2")
CBGH  = colors.HexColor("#082E32")
CBGL  = colors.HexColor("#F2F9FA")
CSUCC = colors.HexColor("#1E8449")
CWARN = colors.HexColor("#D68910")
CDANG = colors.HexColor("#C0392B")
CINFO = colors.HexColor("#1A5276")
CGRAY = colors.HexColor("#6C7A7D")
CDARK = colors.HexColor("#1A252F")
CTALT = colors.HexColor("#EBF5F7")
CWHITE = colors.white

NS_COLORS = [
    "#0D5C63","#117A65","#1A8A94","#2E86C1","#6C3483",
    "#784212","#1B4332","#922B21","#0B5345","#212F3D",
]

W, H  = A4
MAR   = 16 * mm
USE   = W - 2 * MAR


def _ST():
    def p(name, **kw):
        return ParagraphStyle(name, **kw)
    return {
        "h_title":  p("h_title",  fontName="Helvetica-Bold", fontSize=22, textColor=CWHITE, leading=28),
        "h_sub":    p("h_sub",    fontName="Helvetica",      fontSize=9,  textColor=CA, leading=14),
        "sec":      p("sec",      fontName="Helvetica-Bold", fontSize=11, textColor=CP, spaceBefore=6, spaceAfter=3, leading=15),
        "kpi_lbl":  p("kpi_lbl",  fontName="Helvetica",      fontSize=7,  alignment=TA_CENTER, textColor=CGRAY, leading=10),
        "kpi_d_up": p("kpi_d_up", fontName="Helvetica-Bold", fontSize=7,  alignment=TA_CENTER, textColor=CDANG),
        "kpi_d_dn": p("kpi_d_dn", fontName="Helvetica-Bold", fontSize=7,  alignment=TA_CENTER, textColor=CSUCC),
        "kpi_d_eq": p("kpi_d_eq", fontName="Helvetica",      fontSize=7,  alignment=TA_CENTER, textColor=CGRAY),
        "th":       p("th",  fontName="Helvetica-Bold", fontSize=7.5, textColor=CDARK, leading=11),
        "td":       p("td",  fontName="Helvetica",      fontSize=7,   textColor=CDARK, leading=10),
        "td_g":     p("td_g",fontName="Helvetica",      fontSize=6.5, textColor=CGRAY, leading=10),
        "td_c":     p("td_c",fontName="Helvetica",      fontSize=7,   textColor=CDARK, leading=10, alignment=TA_CENTER),
        "al_msg":   p("al_msg",   fontName="Helvetica", fontSize=8,   textColor=CDARK, leading=12),
        "note":     p("note", fontName="Helvetica-Oblique", fontSize=6.5, textColor=CGRAY, leading=9),
    }


def _sc(c):
    return c.hexval() if hasattr(c, "hexval") else "#888"


def _status_cell(status, st):
    s = status.upper()
    if s in ("RUNNING","READY","BOUND","ACTIVE","COMPLETE","SUCCEEDED"):
        c = _sc(CSUCC)
    elif s in ("PENDING","TERMINATING","UNKNOWN"):
        c = _sc(CWARN)
    elif s in ("FAILED","CRASHLOOPBACKOFF","ERROR","NOTREADY","LOST","OOMKILLED"):
        c = _sc(CDANG)
    else:
        c = _sc(CGRAY)
    return Paragraph(f'<font color="{c}"><b>{status[:20]}</b></font>', st["td"])


def _tbl():
    return TableStyle([
        ("BACKGROUND",    (0, 0), (-1,  0), CP),
        ("TEXTCOLOR",     (0, 0), (-1,  0), CWHITE),
        ("FONTNAME",      (0, 0), (-1,  0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1,  0), 7.5),
        ("BOTTOMPADDING", (0, 0), (-1,  0), 5),
        ("TOPPADDING",    (0, 0), (-1,  0), 5),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 7),
        ("TEXTCOLOR",     (0, 1), (-1, -1), CDARK),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [CWHITE, CTALT]),
        ("LINEBELOW",     (0, 0), (-1,  0), 0.5, CA),
        ("LINEBELOW",     (0, 1), (-1, -1), 0.25, colors.HexColor("#C8E6E9")),
        ("LINEAFTER",     (0, 0), (-1, -1), 0.25, colors.HexColor("#C8E6E9")),
        ("BOX",           (0, 0), (-1, -1), 0.5, CA),
        ("TOPPADDING",    (0, 1), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ])


def _section(title, st):
    return [
        Paragraph(title, st["sec"]),
        HRFlowable(width="100%", thickness=0.6, color=CA, spaceAfter=4),
    ]


def _gauge(score, w=160, h=52):
    d = Drawing(w, h)
    c = CSUCC if score >= 85 else (CWARN if score >= 60 else CDANG)
    d.add(Rect(0, 18, w, 14, fillColor=colors.HexColor("#D5EAED"), strokeColor=None, rx=7, ry=7))
    fw = max(14, (score / 100) * w)
    d.add(Rect(0, 18, fw, 14, fillColor=c, strokeColor=None, rx=7, ry=7))
    d.add(String(w/2, 44, "Health Score", textAnchor="middle", fontSize=7, fillColor=CGRAY, fontName="Helvetica"))
    d.add(String(w/2, 2, f"{score}%", textAnchor="middle", fontSize=14, fillColor=_sc(c), fontName="Helvetica-Bold"))
    return d


def _pie(data, w=200, h=120, title=""):
    d = Drawing(w, h)
    total = sum(v for _,v,_ in data)
    if total == 0:
        d.add(String(w/2, h/2, "\u2014", textAnchor="middle", fontSize=9, fillColor=CGRAY))
        return d
    cx, cy, r = 48, h/2 - 6, 36
    angle = 90.0
    for lbl, val, hx in data:
        sweep = (val / total) * 360
        d.add(Wedge(cx, cy, r, angle, angle+sweep, fillColor=colors.HexColor(hx), strokeColor=CWHITE, strokeWidth=0.8))
        angle += sweep
    lx, ly = 98, h - 12
    for i, (lbl, val, hx) in enumerate(data[:7]):
        pct = val / total * 100
        d.add(Rect(lx, ly - i*13, 7, 7, fillColor=colors.HexColor(hx), strokeColor=None))
        d.add(String(lx+10, ly - i*13 + 1, f"{lbl[:13]}  {pct:.0f}%", fontSize=6.5, fillColor=CDARK, fontName="Helvetica"))
    if title:
        d.add(String(cx, 6, title, textAnchor="middle", fontSize=6.5, fillColor=CGRAY, fontName="Helvetica"))
    return d


def _hbar(data, w=None, h=85):
    if w is None:
        w = USE
    d = Drawing(w, h)
    if not data:
        return d
    LM, RM, TM, BM = 145, 15, 8, 16
    cw = w - LM - RM
    ch = h - TM - BM
    bar_h = min(9, (ch / len(data)) - 2)
    max_a = max((v for _,v,_ in data), default=1) or 1
    max_b = max((v for _,_,v in data), default=1) or 1
    for i, (name, va, vb) in enumerate(data):
        y = BM + (len(data)-1-i) * (ch/len(data))
        d.add(String(LM-5, y+bar_h/2-2, name[:26], textAnchor="end", fontSize=6, fillColor=CDARK, fontName="Helvetica"))
        bw = (va/max_a)*cw*0.46
        d.add(Rect(LM, y+bar_h/2, bw, bar_h/2, fillColor=CP, strokeColor=None))
        bw2 = (vb/max_b)*cw*0.46
        d.add(Rect(LM+cw*0.54, y+bar_h/2, bw2, bar_h/2, fillColor=CSUCC, strokeColor=None))
    d.add(Rect(LM, 3, 7, 5, fillColor=CP, strokeColor=None))
    d.add(String(LM+10, 3, "CPU (m)", fontSize=6, fillColor=CDARK))
    d.add(Rect(LM+75, 3, 7, 5, fillColor=CSUCC, strokeColor=None))
    d.add(String(LM+85, 3, "Mem (MiB)", fontSize=6, fillColor=CDARK))
    return d


def _kpi_card(val, label, sub, delta_diff, is_bad_up, col_color, col_w, st):
    hx = _sc(col_color or CP)
    val_p = Paragraph(
        f'<font color="{hx}"><b>{val}</b></font>',
        ParagraphStyle("", fontName="Helvetica-Bold", fontSize=20,
                       alignment=TA_CENTER, leading=24, textColor=col_color or CP)
    )
    inner = [[val_p], [Paragraph(label, st["kpi_lbl"])]]
    if sub:
        inner.append([Paragraph(sub, ParagraphStyle("", fontName="Helvetica", fontSize=7,
                      alignment=TA_CENTER, textColor=CGRAY, leading=10))])
    if delta_diff is not None:
        diff = delta_diff
        if diff == 0:
            dp = Paragraph("\u2014", st["kpi_d_eq"])
        else:
            arrow = "\u25b2" if diff > 0 else "\u25bc"
            is_bad = (diff > 0 and is_bad_up) or (diff < 0 and not is_bad_up)
            ds = st["kpi_d_up"] if is_bad else st["kpi_d_dn"]
            dp = Paragraph(f"{arrow} {abs(diff)}", ds)
        inner.append([dp])
    card = Table(inner, colWidths=[col_w - 10],
                 style=TableStyle([
                     ("BACKGROUND", (0,0),(-1,-1), CBGL),
                     ("BOX",        (0,0),(-1,-1), 0.75, CA),
                     ("LINEABOVE",  (0,0),(-1, 0), 2.5, col_color or CP),
                     ("TOPPADDING", (0,0),(-1,-1), 5),
                     ("BOTTOMPADDING",(0,0),(-1,-1), 5),
                     ("VALIGN",     (0,0),(-1,-1), "MIDDLE"),
                     ("LEFTPADDING",(0,0),(-1,-1), 4),
                     ("RIGHTPADDING",(0,0),(-1,-1), 4),
                 ]))
    return card


def _kpi_row(items, col_w, st):
    cells = [_kpi_card(v, lbl, sub, dv, bad, col, col_w, st) for v,lbl,sub,dv,bad,col in items]
    n = len(cells)
    return Table([cells], colWidths=[col_w]*n,
                 style=TableStyle([
                     ("LEFTPADDING",(0,0),(-1,-1),3),
                     ("RIGHTPADDING",(0,0),(-1,-1),3),
                     ("TOPPADDING",(0,0),(-1,-1),3),
                     ("BOTTOMPADDING",(0,0),(-1,-1),3),
                 ]))


def _page_executive(report, st, delta):
    story = []
    s = report.summary

    # Header
    hdr = Table([[
        Paragraph("Kubernetes Status Report", st["h_title"]),
        Table([
            [Paragraph(f"Cluster: <b>{report.cluster_name}</b>", st["h_sub"])],
            [Paragraph(f"Gerado em: {report.collected_at}", st["h_sub"])],
        ], colWidths=[USE*0.42],
           style=TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#082E32")),
                             ("ALIGN",(0,0),(-1,-1),"RIGHT"),
                             ("RIGHTPADDING",(0,0),(-1,-1),16),
                             ("TOPPADDING",(0,0),(-1,-1),4),
                             ("BOTTOMPADDING",(0,0),(-1,-1),4)])),
    ]], colWidths=[USE*0.58, USE*0.42],
        style=TableStyle([
            ("BACKGROUND",(0,0),(-1,-1), colors.HexColor("#082E32")),
            ("LEFTPADDING",(0,0),(-1,-1), 16),
            ("TOPPADDING",(0,0),(-1,-1), 14),
            ("BOTTOMPADDING",(0,0),(-1,-1), 14),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ]))
    story.append(hdr)

    # Status strip
    has_crit = s.get("nodes_not_ready",0)>0 or s.get("pods_crashloop",0)>0 or s.get("pvcs_lost",0)>0
    has_warn = s.get("pods_failed",0)>0 or s.get("pods_pending",0)>0 or s.get("deployments_degraded",0)>0 or s.get("pods_high_restarts",0)>0
    sc = CDANG if has_crit else (CWARN if has_warn else CSUCC)
    st_txt = ("\u26d4  CRITICO \u2014 Falhas detectadas, acao imediata necessaria" if has_crit
              else ("\u26a0  ATENCAO \u2014 Itens que requerem monitoramento" if has_warn
                    else "\u2705  CLUSTER OPERACIONAL \u2014 Todos os servicos saudaveis"))
    strip = Table([[Paragraph(st_txt, ParagraphStyle("",fontName="Helvetica-Bold",fontSize=10,textColor=CWHITE,alignment=TA_CENTER))]],
                  colWidths=[USE],
                  style=TableStyle([("BACKGROUND",(0,0),(-1,-1),sc),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7)]))
    story.append(strip)
    story.append(Spacer(1, 7))

    # Gauge + KPI row 1
    gauge = _gauge(s.get("health_score",100), w=155, h=50)
    gauge_tbl = Table([[gauge]], colWidths=[165],
                      style=TableStyle([("BACKGROUND",(0,0),(-1,-1),CBGL),("BOX",(0,0),(-1,-1),0.75,CA),
                                        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),("LEFTPADDING",(0,0),(-1,-1),5)]))

    def _dv(key):
        if not delta: return None
        return delta.get(key,{}).get("diff")

    col6 = (USE - 165 - 15) / 6
    kpi1 = _kpi_row([
        (f"{s['nodes_ready']}/{s['total_nodes']}", "Nodes Ready", "control+workers", _dv("nodes_ready"), False, CSUCC if s["nodes_not_ready"]==0 else CDANG),
        (str(s["total_pods"]), "Pods Total", None, _dv("total_pods"), False, CP),
        (str(s["pods_running"]), "Running", "pods OK", _dv("pods_running"), False, CSUCC),
        (str(s["pods_failed"]), "Failed/CrashLoop", None, _dv("pods_failed"), True, CDANG if s["pods_failed"]>0 else CSUCC),
        (str(s["deployments_degraded"]), "Deploys Degradados", None, _dv("deployments_degraded"), True, CDANG if s["deployments_degraded"]>0 else CSUCC),
        (str(s["warning_events"]), "Warning Events", None, _dv("warning_events"), True, CDANG if s["warning_events"]>10 else (CWARN if s["warning_events"]>5 else CSUCC)),
    ], col6, st)

    top = Table([[gauge_tbl, kpi1]], colWidths=[165, USE-165],
                style=TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(0,0),8),("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
    story.append(top)
    story.append(Spacer(1, 5))

    # KPI row 2
    col6b = USE / 6
    kpi2 = _kpi_row([
        (str(s["total_namespaces"]), "Namespaces", None, None, False, CS),
        (str(s["total_statefulsets"]), "StatefulSets", None, None, False, CS),
        (str(s["total_daemonsets"]), "DaemonSets", None, None, False, CS),
        (f"{s['pvcs_bound']}/{s['total_pvcs']}", "PVCs Bound", None, None, False, CDANG if s["pvcs_lost"]>0 else CSUCC),
        (str(s["total_ingresses"]), "Ingresses", None, None, False, CS),
        (str(s["total_hpas"]), "HPAs", None, None, False, CS),
    ], col6b, st)
    story.append(kpi2)
    story.append(Spacer(1, 8))

    # Alertas
    alerts = []
    if s.get("nodes_not_ready",0):      alerts.append(("CRITICO", CDANG, f"  {s['nodes_not_ready']} Node(s) NOT READY"))
    if s.get("pods_crashloop",0):       alerts.append(("CRITICO", CDANG, f"  {s['pods_crashloop']} Pod(s) em CrashLoopBackOff"))
    if s.get("pods_oom",0):             alerts.append(("CRITICO", CDANG, f"  {s['pods_oom']} Pod(s) OOMKilled"))
    if s.get("pvcs_lost",0):            alerts.append(("CRITICO", CDANG, f"  {s['pvcs_lost']} PVC(s) LOST"))
    if s.get("jobs_failed",0):          alerts.append(("CRITICO", CDANG, f"  {s['jobs_failed']} Job(s) falharam"))
    if s.get("pods_failed",0):          alerts.append(("ATENCAO", CWARN, f"  {s['pods_failed']} Pod(s) FAILED"))
    if s.get("pods_pending",0):         alerts.append(("ATENCAO", CWARN, f"  {s['pods_pending']} Pod(s) PENDING"))
    if s.get("deployments_degraded",0): alerts.append(("ATENCAO", CWARN, f"  {s['deployments_degraded']} Deployment(s) degradado(s)"))
    if s.get("pods_high_restarts",0):   alerts.append(("ATENCAO", CWARN, f"  {s['pods_high_restarts']} Pod(s) com restarts elevados"))
    if s.get("warning_events",0)>5:     alerts.append(("INFO",    CINFO, f"  {s['warning_events']} Warning Events recentes"))

    if alerts:
        story.extend(_section("Alertas Ativos", st))
        crits = [(sv,c,m) for sv,c,m in alerts if sv=="CRITICO"]
        warns = [(sv,c,m) for sv,c,m in alerts if sv!="CRITICO"]

        def alert_block(items, bg, border):
            if not items: return Spacer(1,1)
            rows = [[Paragraph(sv, ParagraphStyle("",fontName="Helvetica-Bold",fontSize=7,textColor=c)),
                     Paragraph(m, st["al_msg"])] for sv,c,m in items]
            t = Table(rows, colWidths=[55, USE/2-55-8],
                      style=TableStyle([("BACKGROUND",(0,0),(-1,-1),bg),("BOX",(0,0),(-1,-1),1,border),
                                        ("LINEAFTER",(0,0),(0,-1),0.5,border),("TOPPADDING",(0,0),(-1,-1),4),
                                        ("BOTTOMPADDING",(0,0),(-1,-1),4),("LEFTPADDING",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
            return t

        al_row = Table([[
            alert_block(crits, colors.HexColor("#FDF2F1"), CDANG),
            alert_block(warns, colors.HexColor("#FDFAF0"), CWARN),
        ]], colWidths=[USE/2, USE/2],
            style=TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
        story.append(al_row)
        story.append(Spacer(1, 8))

    # Comparativo
    if delta and report.previous:
        story.extend(_section(f"Comparativo \u2014 Hoje vs {report.previous.collected_at}", st))
        keys = [("health_score","Health Score",False),("pods_running","Pods Running",False),
                ("pods_failed","Pods Failed",True),("nodes_not_ready","Nodes NotReady",True),
                ("deployments_degraded","Deploys Degradados",True),("warning_events","Warning Events",True)]
        hdr_row = [Paragraph(h, ParagraphStyle("",fontName="Helvetica-Bold",fontSize=7.5,textColor=CWHITE)) for h in ["Metrica","Anterior","Atual","Delta","Tendencia"]]
        rows = [hdr_row]
        for key, label, bad_up in keys:
            d = delta.get(key,{})
            prev_v = d.get("previous","?")
            curr_v = d.get("current","?")
            diff   = d.get("diff",0)
            if isinstance(diff,(int,float)) and diff != 0:
                is_bad = (diff>0 and bad_up) or (diff<0 and not bad_up)
                c_hex  = _sc(CDANG) if is_bad else _sc(CSUCC)
                arrow  = "+" if diff>0 else ""
                trend  = f'<font color="{c_hex}"><b>{"Up" if diff>0 else "Dn"} {abs(diff)}</b></font>'
                ds     = f'<font color="{c_hex}">{arrow}{diff}</font>'
            else:
                trend, ds = '<font color="#999">&#8212;</font>', '<font color="#999">0</font>'
            rows.append([Paragraph(label,st["td"]),Paragraph(str(prev_v),st["td_g"]),Paragraph(str(curr_v),st["th"]),Paragraph(ds,st["td_c"]),Paragraph(trend,st["td_c"])])
        cw = [USE*r for r in [0.36,0.15,0.15,0.14,0.18]]
        ct = Table(rows, colWidths=cw, repeatRows=1)
        ct.setStyle(_tbl())
        story.append(ct)

    if report.errors:
        story.append(Spacer(1,4))
        story.append(Paragraph("Coleta parcial: " + " | ".join(report.errors[:4]),
                     ParagraphStyle("",fontName="Helvetica",fontSize=6.5,textColor=CWARN)))
    return story


def _page_resources(report, st):
    story = [PageBreak()]
    ns_sorted = sorted(report.namespaces, key=lambda n: n.pod_count, reverse=True)
    ns_active = [n for n in ns_sorted if n.pod_count > 0]
    ns_empty  = [n for n in ns_sorted if n.pod_count == 0]
    s = report.summary

    story.extend(_section("Distribuicao por Namespace", st))
    pie_ns = [(n.name[:14], n.pod_count, NS_COLORS[i%len(NS_COLORS)]) for i,n in enumerate(ns_active[:8])]
    other = sum(n.pod_count for n in ns_active[8:])
    if other: pie_ns.append(("outros", other, "#95A5A6"))
    pie_st = []
    if s["pods_running"]:  pie_st.append(("Running",   s["pods_running"],  "#1E8449"))
    if s["pods_pending"]:  pie_st.append(("Pending",   s["pods_pending"],  "#D68910"))
    if s["pods_failed"]:   pie_st.append(("Failed",    s["pods_failed"],   "#C0392B"))
    succ = s["total_pods"] - s["pods_running"] - s["pods_pending"] - s["pods_failed"]
    if succ > 0: pie_st.append(("Succeeded", succ, "#1A5276"))
    p1 = _pie(pie_ns, w=230, h=125, title="Pods por Namespace")
    p2 = _pie(pie_st, w=180, h=125, title="Status dos Pods")
    pie_row = Table([[p1,p2]], colWidths=[USE*0.56,USE*0.44],
                    style=TableStyle([("BACKGROUND",(0,0),(-1,-1),CBGL),("BOX",(0,0),(-1,-1),0.5,CA),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    story.append(pie_row)
    story.append(Spacer(1, 8))

    story.extend(_section("Namespaces \u2014 Detalhado", st))
    hd = ["Namespace","Status","Pods","Running","Pending","Failed","CPU (m)","Mem (MiB)","Idade"]
    data = [hd]
    for ns in ns_active:
        data.append([Paragraph(ns.name,st["td"]),_status_cell(ns.status,st),Paragraph(str(ns.pod_count),st["td_c"]),
                     Paragraph(str(ns.running),st["td_c"]),Paragraph(str(ns.pending),st["td_c"]),Paragraph(str(ns.failed),st["td_c"]),
                     Paragraph(str(ns.cpu_usage_m) if ns.cpu_usage_m else "N/A",st["td_c"]),
                     Paragraph(str(ns.mem_usage_mib) if ns.mem_usage_mib else "N/A",st["td_c"]),
                     Paragraph(ns.age,st["td_g"])])
    if ns_empty:
        data.append([Paragraph(f"+ {len(ns_empty)} namespaces sem pods omitidos",st["note"])] + [Paragraph("",st["td"]) for _ in range(8)])
    ws = [r*USE for r in [0.22,0.09,0.07,0.08,0.08,0.07,0.09,0.10,0.07]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl())
    story.append(t)
    story.append(Spacer(1, 8))

    story.extend(_section("Top Pods por Consumo de Recurso", st))
    top_cpu = s.get("top_cpu_pods",[])
    top_mem = s.get("top_mem_pods",[])
    bar_data = [(f"{p['ns'][:10]}/{p['name'][:18]}", p.get("cpu_m",0), next((x["mem_mib"] for x in top_mem if x["name"]==p["name"]),0)) for p in top_cpu[:8]]
    if bar_data:
        story.append(_hbar(bar_data, w=USE, h=90))
        story.append(Spacer(1, 6))

    col2 = USE/2 - 4
    def top_tbl(title, rows_data, cols):
        d = [cols] + rows_data
        ws2 = [col2*r for r in [0.44,0.24,0.18,0.14]]
        t2 = Table(d, colWidths=ws2, repeatRows=1)
        t2.setStyle(_tbl())
        return t2

    cpu_rows = [[Paragraph(p["name"][:38],st["td"]),Paragraph(p["ns"],st["td_g"]),Paragraph(p["cpu"],st["td_c"]),Paragraph(str(p["cpu_m"]),st["td_c"])] for p in top_cpu]
    mem_rows = [[Paragraph(p["name"][:38],st["td"]),Paragraph(p["ns"],st["td_g"]),Paragraph(p["mem"],st["td_c"]),Paragraph(str(p["mem_mib"]),st["td_c"])] for p in top_mem]
    row = Table([[
        [Paragraph("Top 10 \u2014 CPU",st["sec"]),HRFlowable(width="100%",thickness=0.6,color=CA,spaceAfter=3),top_tbl("",cpu_rows,["Pod","Namespace","CPU","m"])],
        [Paragraph("Top 10 \u2014 Memoria",st["sec"]),HRFlowable(width="100%",thickness=0.6,color=CA,spaceAfter=3),top_tbl("",mem_rows,["Pod","Namespace","Mem","MiB"])],
    ]], colWidths=[col2,col2],
        style=TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(0,0),8),("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
    story.append(row)
    return story


def _page_nodes(report, st):
    story = [PageBreak()]
    story.extend(_section("Nodes do Cluster", st))
    hd = ["Node","Status","Roles","Versao","CPU Cap.","CPU Uso","CPU%","Mem Cap.","Mem Uso","Mem%","Idade"]
    data = [hd]
    for n in report.nodes:
        def pct_cell(pct, v):
            if not v or v == "N/A": return Paragraph("N/A",st["td_g"])
            c = CDANG if pct>85 else (CWARN if pct>65 else CSUCC)
            return Paragraph(f'<font color="{_sc(c)}"><b>{pct:.0f}%</b></font>',st["td_c"])
        data.append([Paragraph(n.name,st["td"]),_status_cell(n.status,st),Paragraph(n.roles[:14],st["td_g"]),
                     Paragraph(n.version,st["td_g"]),Paragraph(n.cpu_capacity,st["td_c"]),Paragraph(n.cpu_usage,st["td_c"]),
                     pct_cell(n.cpu_pct,n.cpu_usage),Paragraph(n.mem_capacity,st["td_c"]),Paragraph(n.mem_usage,st["td_c"]),
                     pct_cell(n.mem_pct,n.mem_usage),Paragraph(n.age,st["td_g"])])
    ws = [r*USE for r in [0.18,0.08,0.09,0.09,0.07,0.07,0.06,0.08,0.07,0.06,0.05]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl())
    story.append(t)
    return story


def _page_workloads(report, st):
    story = [PageBreak()]
    story.extend(_section("Deployments", st))
    hd = ["Deployment","Namespace","Desejado","Pronto","Disponivel","Atualizado","Idade"]
    data = [hd]
    for d in report.deployments:
        ok = d.ready == d.desired and d.desired > 0
        rc = _sc(CSUCC) if ok else _sc(CDANG if d.ready==0 and d.desired>0 else CWARN)
        data.append([Paragraph(d.name,st["td"]),Paragraph(d.namespace,st["td_g"]),Paragraph(str(d.desired),st["td_c"]),
                     Paragraph(f'<font color="{rc}"><b>{d.ready}</b></font>',st["td_c"]),Paragraph(str(d.available),st["td_c"]),Paragraph(str(d.up_to_date),st["td_c"]),Paragraph(d.age,st["td_g"])])
    ws = [r*USE for r in [0.30,0.22,0.10,0.10,0.10,0.10,0.08]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl())
    story.append(t)
    story.append(Spacer(1,8))

    if report.statefulsets:
        story.extend(_section("StatefulSets", st))
        hd2 = ["StatefulSet","Namespace","Desejado","Pronto","Idade"]
        d2 = [hd2]
        for s2 in report.statefulsets:
            ok = s2.ready == s2.desired
            rc = _sc(CSUCC) if ok else _sc(CDANG)
            d2.append([Paragraph(s2.name,st["td"]),Paragraph(s2.namespace,st["td_g"]),Paragraph(str(s2.desired),st["td_c"]),
                       Paragraph(f'<font color="{rc}"><b>{s2.ready}</b></font>',st["td_c"]),Paragraph(s2.age,st["td_g"])])
        ws2 = [r*USE for r in [0.35,0.28,0.13,0.13,0.11]]
        t2 = Table(d2, colWidths=ws2, repeatRows=1)
        t2.setStyle(_tbl())
        story.append(t2)
        story.append(Spacer(1,8))

    if report.daemonsets:
        story.extend(_section("DaemonSets", st))
        hd3 = ["DaemonSet","Namespace","Desejado","Pronto","Disponivel","Idade"]
        d3 = [hd3]
        for ds in report.daemonsets:
            ok = ds.ready == ds.desired
            rc = _sc(CSUCC) if ok else _sc(CWARN)
            d3.append([Paragraph(ds.name,st["td"]),Paragraph(ds.namespace,st["td_g"]),Paragraph(str(ds.desired),st["td_c"]),
                       Paragraph(f'<font color="{rc}"><b>{ds.ready}</b></font>',st["td_c"]),Paragraph(str(ds.available),st["td_c"]),Paragraph(ds.age,st["td_g"])])
        ws3 = [r*USE for r in [0.32,0.26,0.12,0.12,0.12,0.10]]
        t3 = Table(d3, colWidths=ws3, repeatRows=1)
        t3.setStyle(_tbl())
        story.append(t3)
        story.append(Spacer(1,8))

    col2 = USE/2 - 4
    left_s, right_s = [], []
    if report.cronjobs:
        left_s.extend(_section("CronJobs", st))
        hc = ["CronJob","Namespace","Schedule","Ultimo","Idade"]
        dc = [hc]
        for cj in report.cronjobs:
            dc.append([Paragraph(cj.name[:28],st["td"]),Paragraph(cj.namespace[:18],st["td_g"]),
                       Paragraph(cj.schedule,st["td_g"]),Paragraph(cj.last_schedule,st["td_g"]),Paragraph(cj.age,st["td_g"])])
        wc = [r*col2 for r in [0.32,0.24,0.22,0.14,0.08]]
        tc = Table(dc, colWidths=wc, repeatRows=1)
        tc.setStyle(_tbl())
        left_s.append(tc)
    if report.jobs:
        right_s.extend(_section("Jobs", st))
        hj = ["Job","Namespace","Status","Duracao","Idade"]
        dj = [hj]
        for j in report.jobs:
            if "status-report-test" in j.name or "status-report-fix" in j.name: continue
            dj.append([Paragraph(j.name[:26],st["td"]),Paragraph(j.namespace[:16],st["td_g"]),_status_cell(j.status,st),Paragraph(j.duration,st["td_g"]),Paragraph(j.age,st["td_g"])])
        wj = [r*col2 for r in [0.32,0.22,0.16,0.18,0.10]]
        tj = Table(dj, colWidths=wj, repeatRows=1)
        tj.setStyle(_tbl())
        right_s.append(tj)
    if left_s or right_s:
        story.append(Table([[left_s or [Spacer(1,1)],right_s or [Spacer(1,1)]]],colWidths=[col2,col2],
                           style=TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(0,0),8),("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)])))
    return story


def _page_pods(report, st):
    story = [PageBreak()]
    SYSTEM_NS = {"kube-system","kube-node-lease","kube-public","cattle-system","cattle-fleet-system",
                 "cattle-fleet-local-system","cattle-capi-system","cattle-turtles-system","fleet-default","fleet-local","local","local-path-storage"}
    problem = [p for p in report.pods if (p.status not in ("Running","Succeeded") or
               (p.namespace in SYSTEM_NS and p.restarts >= 20) or (p.namespace not in SYSTEM_NS and p.restarts >= 5))]
    normal  = [p for p in report.pods if p.status in ("Running","Succeeded") and
               not ((p.namespace in SYSTEM_NS and p.restarts>=20) or (p.namespace not in SYSTEM_NS and p.restarts>=5))]
    story.extend(_section(f"Pods \u2014 Atencao ({len(problem)} pods)", st))
    if not problem:
        story.append(Paragraph("Nenhum pod com problemas detectado.", st["td"]))
    else:
        hd = ["Pod","Namespace","Status","Ready","Restarts","CPU","Mem","Node","Idade"]
        data = [hd]
        for p in problem:
            data.append([Paragraph(p.name[:36],st["td"]),Paragraph(p.namespace,st["td_g"]),_status_cell(p.status,st),
                         Paragraph(p.ready,st["td_c"]),Paragraph(str(p.restarts),st["td_c"]),Paragraph(p.cpu_usage,st["td_c"]),
                         Paragraph(p.mem_usage,st["td_c"]),Paragraph(p.node[:18] if p.node else "?",st["td_g"]),Paragraph(p.age,st["td_g"])])
        ws = [r*USE for r in [0.24,0.13,0.10,0.07,0.07,0.07,0.07,0.17,0.06]]
        t = Table(data, colWidths=ws, repeatRows=1)
        t.setStyle(_tbl())
        story.append(t)
    story.append(Spacer(1,10))
    story.extend(_section(f"Pods \u2014 Saudaveis ({min(50,len(normal))} de {len(normal)})", st))
    hd2 = ["Pod","Namespace","Status","Ready","Restarts","CPU","Mem","Idade"]
    data2 = [hd2]
    for p in normal[:50]:
        data2.append([Paragraph(p.name[:38],st["td"]),Paragraph(p.namespace,st["td_g"]),_status_cell(p.status,st),
                      Paragraph(p.ready,st["td_c"]),Paragraph(str(p.restarts),st["td_c"]),Paragraph(p.cpu_usage,st["td_c"]),Paragraph(p.mem_usage,st["td_c"]),Paragraph(p.age,st["td_g"])])
    ws2 = [r*USE for r in [0.28,0.15,0.10,0.07,0.07,0.08,0.08,0.07]]
    t2 = Table(data2, colWidths=ws2, repeatRows=1)
    t2.setStyle(_tbl())
    story.append(t2)
    return story


def _page_network_storage(report, st):
    story = [PageBreak()]
    story.extend(_section("PersistentVolumeClaims", st))
    hd = ["PVC","Namespace","Status","Volume","Capacidade","StorageClass","Modo","Idade"]
    data = [hd]
    for p in report.pvcs:
        data.append([Paragraph(p.name[:26],st["td"]),Paragraph(p.namespace,st["td_g"]),_status_cell(p.status,st),
                     Paragraph(p.volume[:18],st["td_g"]),Paragraph(p.capacity,st["td_c"]),
                     Paragraph(p.storage_class[:16],st["td_g"]),Paragraph(p.access_modes[:14],st["td_g"]),Paragraph(p.age,st["td_g"])])
    ws = [r*USE for r in [0.22,0.14,0.08,0.18,0.09,0.14,0.10,0.06]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl())
    story.append(t)
    story.append(Spacer(1,8))

    col2 = USE/2 - 4
    left_s, right_s = [], []
    if report.ingresses:
        left_s.extend(_section("Ingresses", st))
        hi = ["Ingress","Namespace","Hosts","Address","Ports","Idade"]
        di = [hi]
        for i in report.ingresses:
            di.append([Paragraph(i.name[:22],st["td"]),Paragraph(i.namespace[:16],st["td_g"]),
                       Paragraph(i.hosts[:28],st["td_g"]),Paragraph(i.address[:16],st["td_g"]),Paragraph(i.ports,st["td_c"]),Paragraph(i.age,st["td_g"])])
        wi = [r*col2 for r in [0.22,0.18,0.28,0.16,0.10,0.06]]
        ti = Table(di, colWidths=wi, repeatRows=1)
        ti.setStyle(_tbl())
        left_s.append(ti)
    if report.services:
        right_s.extend(_section("Services Expostos", st))
        hs = ["Service","Namespace","Tipo","External IP","Ports","Idade"]
        ds = [hs]
        for sv in report.services:
            ds.append([Paragraph(sv.name[:22],st["td"]),Paragraph(sv.namespace[:14],st["td_g"]),Paragraph(sv.type,st["td_g"]),
                       Paragraph(sv.external_ip[:16],st["td_g"]),Paragraph(sv.ports[:18],st["td_g"]),Paragraph(sv.age,st["td_g"])])
        ws2 = [r*col2 for r in [0.22,0.18,0.12,0.18,0.22,0.08]]
        ts = Table(ds, colWidths=ws2, repeatRows=1)
        ts.setStyle(_tbl())
        right_s.append(ts)
    if left_s or right_s:
        story.append(Table([[left_s or [Spacer(1,1)],right_s or [Spacer(1,1)]]],colWidths=[col2,col2],
                           style=TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(0,0),8),("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)])))
        story.append(Spacer(1,8))

    if report.hpas:
        story.extend(_section("Horizontal Pod Autoscalers", st))
        hh = ["HPA","Namespace","Target","Min","Max","Atual","CPU Target","CPU Atual","Idade"]
        dh = [hh]
        for h in report.hpas:
            at_max = h.current_replicas >= h.max_replicas
            rc = _sc(CWARN) if at_max else _sc(CSUCC)
            dh.append([Paragraph(h.name[:22],st["td"]),Paragraph(h.namespace[:16],st["td_g"]),Paragraph(h.target[:24],st["td_g"]),
                       Paragraph(str(h.min_replicas),st["td_c"]),Paragraph(str(h.max_replicas),st["td_c"]),
                       Paragraph(f'<font color="{rc}"><b>{h.current_replicas}</b></font>',st["td_c"]),
                       Paragraph(h.cpu_target_pct,st["td_c"]),Paragraph(h.cpu_current_pct,st["td_c"]),Paragraph(h.age,st["td_g"])])
        wh = [r*USE for r in [0.14,0.13,0.20,0.06,0.06,0.07,0.10,0.10,0.07]]
        th = Table(dh, colWidths=wh, repeatRows=1)
        th.setStyle(_tbl())
        story.append(th)
    return story


def _page_events(report, st):
    story = [PageBreak()]
    story.extend(_section(f"Warning Events Recentes ({len(report.events)} eventos)", st))
    if not report.events:
        story.append(Paragraph("Nenhum Warning Event encontrado.", st["td"]))
        return story
    hd = ["Namespace","Razao","Objeto","Mensagem","Count","Ha"]
    data = [hd]
    for e in report.events[:60]:
        data.append([Paragraph(e.namespace[:16],st["td_g"]),Paragraph(e.reason[:18],st["td"]),
                     Paragraph(e.object[:32],st["td_g"]),Paragraph(e.message[:80],st["td_g"]),
                     Paragraph(str(e.count),st["td_c"]),Paragraph(e.last_seen,st["td_g"])])
    ws = [r*USE for r in [0.13,0.12,0.22,0.40,0.07,0.07]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl())
    story.append(t)
    return story


class _DocTpl(SimpleDocTemplate):
    def __init__(self, filename, report, **kwargs):
        self.report = report
        super().__init__(filename, **kwargs)

    def afterPage(self):
        c = self.canv
        r = self.report
        c.saveState()
        c.setFillColor(CP)
        c.rect(0, 0, W, 10*mm, fill=1, stroke=0)
        c.setFillColor(CA)
        c.rect(0, 10*mm - 1.5, W, 1.5, fill=1, stroke=0)
        c.setFont("Helvetica", 6.5)
        c.setFillColor(CWHITE)
        c.drawString(MAR, 3.8*mm, f"OpenLabs | K8s Status Report | Cluster: {r.cluster_name} | {r.collected_at} | Confidencial")
        c.drawRightString(W - MAR, 3.8*mm, f"Pagina {c.getPageNumber()}")
        c.restoreState()


def generate_pdf(report, output_path, delta=None):
    st = _ST()
    story = []
    story.extend(_page_executive(report, st, delta or {}))
    story.extend(_page_resources(report, st))
    story.extend(_page_nodes(report, st))
    story.extend(_page_workloads(report, st))
    story.extend(_page_pods(report, st))
    story.extend(_page_network_storage(report, st))
    story.extend(_page_events(report, st))
    doc = _DocTpl(output_path, report, pagesize=A4,
                  leftMargin=MAR, rightMargin=MAR, topMargin=MAR, bottomMargin=14*mm)
    doc.build(story)
    logger.info(f"PDF gerado: {output_path}")
    return output_path
