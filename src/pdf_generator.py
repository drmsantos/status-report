#!/usr/bin/env python3
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versao:  4.0.0
# Arquivo: pdf_generator.py
# Desc:    K8s Status Report - Design profissional com fonte Carlito
# =============================================================================

import logging, os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak
from reportlab.graphics.shapes import Drawing, Rect, String, Wedge, Line, Circle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from models import ClusterReport
from cache import diff_summary

logger = logging.getLogger(__name__)

# ── Fonte Carlito ─────────────────────────────────────────────────────────────
_FONT_DIR = '/usr/share/fonts/truetype/crosextra'
_FONTS_OK  = False
try:
    pdfmetrics.registerFont(TTFont('C',  f'{_FONT_DIR}/Carlito-Regular.ttf'))
    pdfmetrics.registerFont(TTFont('CB', f'{_FONT_DIR}/Carlito-Bold.ttf'))
    pdfmetrics.registerFont(TTFont('CI', f'{_FONT_DIR}/Carlito-Italic.ttf'))
    _FONTS_OK = True
except Exception as e:
    logger.warning(f'Carlito nao encontrado, usando Helvetica: {e}')

R  = 'CB' if _FONTS_OK else 'Helvetica-Bold'    # Regular-Bold
N  = 'C'  if _FONTS_OK else 'Helvetica'          # Normal
IT = 'CI' if _FONTS_OK else 'Helvetica-Oblique'  # Italic

# ── Paleta ────────────────────────────────────────────────────────────────────
C_HDR   = colors.HexColor("#082E32")
C_P     = colors.HexColor("#0D5C63")
C_S     = colors.HexColor("#1A8A94")
C_A     = colors.HexColor("#3DBAC2")
C_BGL   = colors.HexColor("#F2F9FA")
C_BGL2  = colors.HexColor("#EBF5F7")
C_OK    = colors.HexColor("#1E8449")
C_WARN  = colors.HexColor("#D68910")
C_CRIT  = colors.HexColor("#C0392B")
C_INFO  = colors.HexColor("#1A5276")
C_GRAY  = colors.HexColor("#6C7A7D")
C_DARK  = colors.HexColor("#1A252F")
C_WHITE = colors.white
C_LGRID = colors.HexColor("#C8E6E9")

W, H   = A4
MAR    = 14 * mm
USE    = W - 2 * MAR


# ── Estilos ───────────────────────────────────────────────────────────────────
def _S():
    def p(name, fn=N, fs=8, tc=C_DARK, **kw):
        return ParagraphStyle(name, fontName=fn, fontSize=fs, textColor=tc,
                               leading=kw.pop('leading', fs*1.35), **kw)
    return {
        'title':   p('title',   R,  20, C_WHITE,  leading=26),
        'sub':     p('sub',     N,   9, C_A,      leading=14),
        'sec':     p('sec',     R,  9,  C_P,      spaceBefore=4, spaceAfter=3,
                      leading=12, textTransform='uppercase'),
        'kpi_v':   p('kpi_v',   R,  22, C_P,      leading=26, alignment=TA_CENTER),
        'kpi_l':   p('kpi_l',   N,   8, C_GRAY,   leading=11, alignment=TA_CENTER),
        'kpi2_v':  p('kpi2_v',  R,  14, C_P,      leading=18, alignment=TA_CENTER),
        'kpi2_l':  p('kpi2_l',  N,   7, C_GRAY,   leading=10, alignment=TA_CENTER),
        'th':      p('th',      R,   8, C_WHITE,  leading=11),
        'td':      p('td',      N,   7.5, C_DARK, leading=11),
        'td_g':    p('td_g',    N,   7,   C_GRAY, leading=10),
        'td_c':    p('td_c',    N,   7.5, C_DARK, leading=11, alignment=TA_CENTER),
        'td_r':    p('td_r',    N,   7.5, C_DARK, leading=11, alignment=TA_RIGHT),
        'td_b':    p('td_b',    R,   7.5, C_DARK, leading=11),
        'al_sev':  p('al_sev',  R,   7.5, C_CRIT, leading=11),
        'al_msg':  p('al_msg',  N,   8,   C_DARK, leading=12),
        'note':    p('note',    IT,  6.5, C_GRAY, leading=9),
        'gauge_v': p('gauge_v', R,  28, C_OK,     leading=32, alignment=TA_CENTER),
        'gauge_l': p('gauge_l', N,   8, C_GRAY,   leading=11, alignment=TA_CENTER),
        'hs':      p('hs',      R,   8, C_P,      leading=11),
    }


def _sc(c):
    return c.hexval() if hasattr(c, 'hexval') else '#888'


# ── Componentes gráficos ──────────────────────────────────────────────────────
def _gauge_draw(score, w=150, h=55):
    d = Drawing(w, h)
    c = C_OK if score >= 85 else (C_WARN if score >= 60 else C_CRIT)
    # Track
    d.add(Rect(4, 20, w-8, 12, fillColor=C_BGL2, strokeColor=None, rx=6, ry=6))
    # Fill
    fw = max(12, (score/100)*(w-8))
    d.add(Rect(4, 20, fw, 12, fillColor=c, strokeColor=None, rx=6, ry=6))
    # Score text
    d.add(String(w/2, 2, f'{score}%', textAnchor='middle',
                 fontSize=16, fillColor=_sc(c), fontName=R))
    d.add(String(w/2, 38, 'Health Score', textAnchor='middle',
                 fontSize=7.5, fillColor=_sc(C_GRAY), fontName=N))
    return d


def _pie_draw(data, w=200, h=110, title=''):
    d = Drawing(w, h)
    total = sum(v for _, v, _ in data)
    if not total:
        return d
    cx, cy, r = 46, h/2-4, 34
    angle = 90.0
    for _, val, hx in data:
        sweep = (val/total)*360
        d.add(Wedge(cx, cy, r, angle, angle+sweep,
                    fillColor=colors.HexColor(hx), strokeColor=C_WHITE, strokeWidth=0.8))
        angle += sweep
    # Legend
    lx, ly = 96, h-10
    for i, (lbl, val, hx) in enumerate(data[:7]):
        pct = val/total*100
        d.add(Rect(lx, ly-i*13, 7, 7,
                   fillColor=colors.HexColor(hx), strokeColor=None))
        d.add(String(lx+10, ly-i*13+1, f'{lbl[:14]}  {pct:.0f}%',
                     fontSize=6.5, fillColor=_sc(C_DARK), fontName=N))
    if title:
        d.add(String(cx, 5, title, textAnchor='middle',
                     fontSize=7, fillColor=_sc(C_GRAY), fontName=N))
    return d


def _bar_h(data, w=None, h=80):
    """Barras horizontais duplas CPU+Mem."""
    if w is None: w = USE
    d = Drawing(w, h)
    if not data: return d
    LM, RM, TM, BM = 140, 12, 6, 14
    cw = w - LM - RM
    ch = h - TM - BM
    bh = min(9, (ch/len(data))-2)
    ma = max((v for _, v, _ in data), default=1) or 1
    mb = max((v for _, _, v in data), default=1) or 1
    for i, (name, va, vb) in enumerate(data):
        y = BM + (len(data)-1-i)*(ch/len(data))
        d.add(String(LM-5, y+bh/2-2, name[:25], textAnchor='end',
                     fontSize=6.5, fillColor=_sc(C_DARK), fontName=N))
        bwa = (va/ma)*cw*0.46
        d.add(Rect(LM, y+bh/2, bwa, bh/2, fillColor=C_P, strokeColor=None))
        bwb = (vb/mb)*cw*0.46
        d.add(Rect(LM+cw*0.54, y+bh/2, bwb, bh/2, fillColor=C_OK, strokeColor=None))
    d.add(Rect(LM, 3, 7, 5, fillColor=C_P,  strokeColor=None))
    d.add(String(LM+10, 3, 'CPU (m)', fontSize=6, fillColor=_sc(C_DARK)))
    d.add(Rect(LM+70, 3, 7, 5, fillColor=C_OK, strokeColor=None))
    d.add(String(LM+80, 3, 'Mem (MiB)', fontSize=6, fillColor=_sc(C_DARK)))
    return d


def _bar_ns(data, w=None, h=100):
    """Barras horizontais para namespaces."""
    if w is None: w = USE/2 - 10
    d = Drawing(w, h)
    if not data: return d
    LM, RM, TM, BM = 90, 30, 4, 4
    cw = w - LM - RM
    ch = h - TM - BM
    bh = min(8, (ch/len(data))-2)
    mx = max((v for _, v, _ in data), default=1) or 1
    NS_C = ['#0D5C63','#117A65','#1A8A94','#2E86C1','#6C3483','#784212','#1B4332']
    for i, (name, val, _) in enumerate(data):
        y = BM + (len(data)-1-i)*(ch/len(data))
        d.add(String(LM-5, y+bh/2-2, name[:16], textAnchor='end',
                     fontSize=6.5, fillColor=_sc(C_DARK), fontName=N))
        bw = max(2, (val/mx)*cw)
        d.add(Rect(LM, y+bh/2, bw, bh/2,
                   fillColor=colors.HexColor(NS_C[i % len(NS_C)]),
                   strokeColor=None))
        d.add(String(LM+bw+4, y+bh/2-1, str(val),
                     fontSize=6, fillColor=_sc(C_GRAY), fontName=N))
    return d


# ── Helpers de tabela ─────────────────────────────────────────────────────────
def _tbl_style():
    return TableStyle([
        ('BACKGROUND',    (0,0), (-1, 0), C_P),
        ('TEXTCOLOR',     (0,0), (-1, 0), C_WHITE),
        ('FONTNAME',      (0,0), (-1, 0), R),
        ('FONTSIZE',      (0,0), (-1, 0), 7.5),
        ('TOPPADDING',    (0,0), (-1, 0), 5),
        ('BOTTOMPADDING', (0,0), (-1, 0), 5),
        ('FONTNAME',      (0,1), (-1,-1), N),
        ('FONTSIZE',      (0,1), (-1,-1), 7),
        ('TEXTCOLOR',     (0,1), (-1,-1), C_DARK),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [C_WHITE, C_BGL]),
        ('LINEBELOW',     (0,0), (-1, 0), 0.5, C_A),
        ('LINEBELOW',     (0,1), (-1,-1), 0.25, C_LGRID),
        ('BOX',           (0,0), (-1,-1), 0.5, C_A),
        ('TOPPADDING',    (0,1), (-1,-1), 3),
        ('BOTTOMPADDING', (0,1), (-1,-1), 3),
        ('LEFTPADDING',   (0,0), (-1,-1), 6),
        ('RIGHTPADDING',  (0,0), (-1,-1), 6),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ])


def _sec(title, st):
    return [
        Paragraph(title, st['sec']),
        HRFlowable(width='100%', thickness=1.5, color=C_A, spaceAfter=5),
    ]


def _status(s, st):
    up = s.upper()
    if up in ('RUNNING','READY','BOUND','ACTIVE','COMPLETE','SUCCEEDED'):
        c = _sc(C_OK)
    elif up in ('PENDING','TERMINATING','UNKNOWN','PROGRESSING'):
        c = _sc(C_WARN)
    elif up in ('FAILED','CRASHLOOPBACKOFF','ERROR','NOTREADY','LOST','OOMKILLED'):
        c = _sc(C_CRIT)
    else:
        c = _sc(C_GRAY)
    return Paragraph(f'<font color="{c}"><b>{s[:18]}</b></font>', st['td'])


def _pct(pct, v, st):
    if not v or v == 'N/A':
        return Paragraph('N/A', st['td_g'])
    c = C_CRIT if pct > 85 else (C_WARN if pct > 65 else C_OK)
    return Paragraph(f'<font color="{_sc(c)}"><b>{pct:.0f}%</b></font>', st['td_c'])


# ── KPI Cards ─────────────────────────────────────────────────────────────────
def _kpi_card(val, lbl, col, col_w, st, delta=None, bad_up=True, sub=None):
    hx = _sc(col)
    vp = Paragraph(f'<font color="{hx}"><b>{val}</b></font>',
                   ParagraphStyle('', fontName=R, fontSize=20,
                                  alignment=TA_CENTER, leading=24, textColor=col))
    rows = [[vp], [Paragraph(lbl, st['kpi_l'])]]
    if sub:
        rows.append([Paragraph(sub, ParagraphStyle('', fontName=N, fontSize=6.5,
                               alignment=TA_CENTER, textColor=C_GRAY, leading=9))])
    if delta is not None:
        if delta == 0:
            dp = Paragraph('—', ParagraphStyle('', fontName=N, fontSize=7,
                           alignment=TA_CENTER, textColor=C_GRAY))
        else:
            is_bad = (delta > 0 and bad_up) or (delta < 0 and not bad_up)
            dc = _sc(C_CRIT) if is_bad else _sc(C_OK)
            arr = '▲' if delta > 0 else '▼'
            dp = Paragraph(f'<font color="{dc}"><b>{arr} {abs(delta)}</b></font>',
                           ParagraphStyle('', fontName=R, fontSize=7,
                                          alignment=TA_CENTER, textColor=C_DARK))
        rows.append([dp])
    return Table(rows, colWidths=[col_w-8],
                 style=TableStyle([
                     ('BACKGROUND', (0,0),(-1,-1), C_BGL),
                     ('BOX',        (0,0),(-1,-1), 0.75, C_A),
                     ('LINEABOVE',  (0,0),(-1, 0), 3, col),
                     ('TOPPADDING', (0,0),(-1,-1), 5),
                     ('BOTTOMPADDING',(0,0),(-1,-1),5),
                     ('VALIGN',     (0,0),(-1,-1), 'MIDDLE'),
                     ('LEFTPADDING',(0,0),(-1,-1), 3),
                     ('RIGHTPADDING',(0,0),(-1,-1),3),
                 ]))


def _kpi_row(items, col_w, st):
    cells = [_kpi_card(v,l,c,col_w,st,dv,bu,sb) for v,l,c,dv,bu,sb in items]
    return Table([cells], colWidths=[col_w]*len(cells),
                 style=TableStyle([('LEFTPADDING',(0,0),(-1,-1),3),
                                   ('RIGHTPADDING',(0,0),(-1,-1),3),
                                   ('TOPPADDING',(0,0),(-1,-1),3),
                                   ('BOTTOMPADDING',(0,0),(-1,-1),3)]))


def _kpi2_card(val, lbl, col_w, st):
    return Table([
        [Paragraph(str(val), st['kpi2_v'])],
        [Paragraph(lbl, st['kpi2_l'])],
    ], colWidths=[col_w-8],
       style=TableStyle([
           ('BACKGROUND',(0,0),(-1,-1), C_WHITE),
           ('BOX',(0,0),(-1,-1), 0.5, C_LGRID),
           ('TOPPADDING',(0,0),(-1,-1),4),
           ('BOTTOMPADDING',(0,0),(-1,-1),4),
           ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
           ('LEFTPADDING',(0,0),(-1,-1),3),
           ('RIGHTPADDING',(0,0),(-1,-1),3),
       ]))


# ── Página 1 — Executivo ──────────────────────────────────────────────────────
def _pg_exec(report, st, delta):
    story = []
    s = report.summary

    # Header
    hdr = Table([[
        Table([
            [Paragraph('Kubernetes Status Report', st['title'])],
            [Paragraph('OpenLabs &mdash; DevOps | Infra', st['sub'])],
        ], colWidths=[USE*0.58],
           style=TableStyle([('BACKGROUND',(0,0),(-1,-1),C_HDR),
                              ('LEFTPADDING',(0,0),(-1,-1),16),
                              ('TOPPADDING',(0,0),(-1,-1),14),
                              ('BOTTOMPADDING',(0,0),(-1,-1),14)])),
        Table([
            [Paragraph(f'Cluster: <b>{report.cluster_name}</b>', st['sub'])],
            [Paragraph(f'Gerado em: {report.collected_at}', st['sub'])],
            [Paragraph('Confidencial', ParagraphStyle('',fontName=N,fontSize=8,
                        textColor=colors.HexColor('#3DBAC2'),leading=12))],
        ], colWidths=[USE*0.42],
           style=TableStyle([('BACKGROUND',(0,0),(-1,-1),C_HDR),
                              ('ALIGN',(0,0),(-1,-1),'RIGHT'),
                              ('RIGHTPADDING',(0,0),(-1,-1),16),
                              ('TOPPADDING',(0,0),(-1,-1),14),
                              ('BOTTOMPADDING',(0,0),(-1,-1),14)])),
    ]], colWidths=[USE*0.58, USE*0.42],
        style=TableStyle([('BACKGROUND',(0,0),(-1,-1),C_HDR),
                           ('LEFTPADDING',(0,0),(-1,-1),0),
                           ('RIGHTPADDING',(0,0),(-1,-1),0),
                           ('TOPPADDING',(0,0),(-1,-1),0),
                           ('BOTTOMPADDING',(0,0),(-1,-1),0),
                           ('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    story.append(hdr)

    # Status strip
    has_c = s.get('nodes_not_ready',0)>0 or s.get('pods_crashloop',0)>0 or s.get('pvcs_lost',0)>0
    has_w = s.get('pods_failed',0)>0 or s.get('pods_pending',0)>0 or s.get('deployments_degraded',0)>0 or s.get('pods_high_restarts',0)>0
    sc = C_CRIT if has_c else (C_WARN if has_w else C_OK)
    txt = ('CRITICO — Falhas detectadas, acao imediata necessaria' if has_c
           else ('ATENCAO — Itens que requerem monitoramento' if has_w
                 else 'CLUSTER OPERACIONAL — Todos os servicos saudaveis'))
    story.append(Table([[Paragraph(txt, ParagraphStyle('',fontName=R,fontSize=10,
                         textColor=C_WHITE,alignment=TA_CENTER))]],
                       colWidths=[USE],
                       style=TableStyle([('BACKGROUND',(0,0),(-1,-1),sc),
                                          ('TOPPADDING',(0,0),(-1,-1),6),
                                          ('BOTTOMPADDING',(0,0),(-1,-1),6)])))
    story.append(Spacer(1, 7))

    def _dv(k):
        if not delta: return None
        return delta.get(k,{}).get('diff')

    # Gauge + KPI row 1
    gauge_tbl = Table([[_gauge_draw(s.get('health_score',100), w=150, h=55)]],
                      colWidths=[162],
                      style=TableStyle([('BACKGROUND',(0,0),(-1,-1),C_BGL),
                                         ('BOX',(0,0),(-1,-1),0.75,C_A),
                                         ('TOPPADDING',(0,0),(-1,-1),4),
                                         ('BOTTOMPADDING',(0,0),(-1,-1),4),
                                         ('LEFTPADDING',(0,0),(-1,-1),6)]))
    col6 = (USE-162-12)/6
    kpi1 = _kpi_row([
        (f"{s['nodes_ready']}/{s['total_nodes']}", 'Nodes Ready',
         C_OK if s['nodes_not_ready']==0 else C_CRIT, _dv('nodes_ready'), False, None),
        (str(s['total_pods']),         'Pods Total',        C_P,    _dv('total_pods'),    False, None),
        (str(s['pods_running']),       'Running',           C_OK,   _dv('pods_running'),  False, 'pods OK'),
        (str(s['pods_failed']),        'Failed/Crash',      C_CRIT if s['pods_failed']>0 else C_OK,
         _dv('pods_failed'), True, None),
        (str(s['deployments_degraded']),'Deploys Deg.',     C_CRIT if s['deployments_degraded']>0 else C_OK,
         _dv('deployments_degraded'), True, None),
        (str(s['warning_events']),     'Warnings',          C_CRIT if s['warning_events']>10 else (C_WARN if s['warning_events']>5 else C_OK),
         _dv('warning_events'), True, None),
    ], col6, st)
    story.append(Table([[gauge_tbl, kpi1]], colWidths=[162, USE-162],
                       style=TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                                          ('LEFTPADDING',(0,0),(-1,-1),0),
                                          ('RIGHTPADDING',(0,0),(0,0),8),
                                          ('TOPPADDING',(0,0),(-1,-1),0),
                                          ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
    story.append(Spacer(1, 5))

    # KPI row 2
    col6b = USE/6
    kpi2_cells = [
        _kpi2_card(s['total_namespaces'],    'Namespaces',    col6b, st),
        _kpi2_card(s['total_statefulsets'],  'StatefulSets',  col6b, st),
        _kpi2_card(s['total_daemonsets'],    'DaemonSets',    col6b, st),
        _kpi2_card(f"{s['pvcs_bound']}/{s['total_pvcs']}", 'PVCs Bound', col6b, st),
        _kpi2_card(s['total_ingresses'],     'Ingresses',     col6b, st),
        _kpi2_card(s['total_hpas'],          'HPAs',          col6b, st),
    ]
    story.append(Table([kpi2_cells], colWidths=[col6b]*6,
                       style=TableStyle([('LEFTPADDING',(0,0),(-1,-1),3),
                                          ('RIGHTPADDING',(0,0),(-1,-1),3),
                                          ('TOPPADDING',(0,0),(-1,-1),2),
                                          ('BOTTOMPADDING',(0,0),(-1,-1),2)])))
    story.append(Spacer(1, 8))

    # Alertas + Nodes (2 colunas)
    alerts = []
    if s.get('nodes_not_ready',0):      alerts.append((C_CRIT,'CRITICO',f"{s['nodes_not_ready']} Node(s) NOT READY"))
    if s.get('pods_crashloop',0):       alerts.append((C_CRIT,'CRITICO',f"{s['pods_crashloop']} Pod(s) CrashLoopBackOff"))
    if s.get('pods_oom',0):             alerts.append((C_CRIT,'CRITICO',f"{s['pods_oom']} Pod(s) OOMKilled"))
    if s.get('pvcs_lost',0):            alerts.append((C_CRIT,'CRITICO',f"{s['pvcs_lost']} PVC(s) LOST"))
    if s.get('jobs_failed',0):          alerts.append((C_CRIT,'CRITICO',f"{s['jobs_failed']} Job(s) falharam"))
    if s.get('pods_failed',0):          alerts.append((C_WARN,'ATENCAO',f"{s['pods_failed']} Pod(s) FAILED"))
    if s.get('pods_pending',0):         alerts.append((C_WARN,'ATENCAO',f"{s['pods_pending']} Pod(s) PENDING"))
    if s.get('deployments_degraded',0): alerts.append((C_WARN,'ATENCAO',f"{s['deployments_degraded']} Deployment(s) degradado(s)"))
    if s.get('pods_high_restarts',0):   alerts.append((C_WARN,'ATENCAO',f"{s['pods_high_restarts']} Pod(s) com restarts elevados"))
    if s.get('warning_events',0)>5:     alerts.append((C_INFO,'INFO',   f"{s['warning_events']} Warning Events recentes"))

    col2 = USE/2 - 6

    # Bloco alertas
    al_content = _sec('Alertas Ativos', st)
    if alerts:
        for col, sev, msg in alerts:
            bg = {_sc(C_CRIT): colors.HexColor('#FADBD8'),
                  _sc(C_WARN): colors.HexColor('#FEF3CD'),
                  _sc(C_INFO): colors.HexColor('#D6EAF8')}.get(_sc(col), C_BGL)
            bc = col
            row = Table([[
                Paragraph(sev, ParagraphStyle('',fontName=R,fontSize=7,textColor=col)),
                Paragraph(msg, st['al_msg']),
            ]], colWidths=[54, col2-54-10],
                style=TableStyle([('BACKGROUND',(0,0),(-1,-1),bg),
                                   ('LEFTBORDER',(0,0),(0,-1),3,bc),
                                   ('TOPPADDING',(0,0),(-1,-1),3),
                                   ('BOTTOMPADDING',(0,0),(-1,-1),3),
                                   ('LEFTPADDING',(0,0),(-1,-1),7),
                                   ('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
            al_content.append(row)
            al_content.append(Spacer(1, 3))
    else:
        al_content.append(Paragraph('Nenhum alerta ativo — cluster saudavel', st['td']))

    # Bloco nodes
    nd_content = _sec('Nodes do Cluster', st)
    nd_hd = ['Node','Status','Versao','CPU%','Mem%','Idade']
    nd_data = [nd_hd]
    for n in report.nodes:
        nd_data.append([
            Paragraph(n.name[:22], st['td_b']),
            _status(n.status, st),
            Paragraph(n.version[:10], st['td_g']),
            _pct(n.cpu_pct, n.cpu_usage, st),
            _pct(n.mem_pct, n.mem_usage, st),
            Paragraph(n.age, st['td_g']),
        ])
    nd_ws = [r*col2 for r in [0.34,0.13,0.17,0.12,0.12,0.10]]
    nd_t = Table(nd_data, colWidths=nd_ws, repeatRows=1)
    nd_t.setStyle(_tbl_style())
    nd_content.append(nd_t)

    story.append(Table([[al_content, nd_content]], colWidths=[col2, col2],
                       style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                          ('LEFTPADDING',(0,0),(-1,-1),0),
                                          ('RIGHTPADDING',(0,0),(0,0),12),
                                          ('TOPPADDING',(0,0),(-1,-1),0),
                                          ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
    story.append(Spacer(1, 8))

    # Namespace bars + Pod status bars (2 colunas)
    ns_sorted = sorted(report.namespaces, key=lambda n: n.pod_count, reverse=True)
    ns_active = [n for n in ns_sorted if n.pod_count > 0]
    ns_bar_data = [(n.name, n.pod_count, '') for n in ns_active[:8]]

    ns_content = _sec('Top Namespaces por Pods', st)
    ns_content.append(_bar_ns(ns_bar_data, w=col2, h=max(80, len(ns_bar_data)*14+20)))

    # Pod status bars
    ps_content = _sec('Distribuicao de Status dos Pods', st)
    total = s['total_pods'] or 1
    pod_bars = [
        ('Running',   s['pods_running'],  '#1E8449'),
        ('Succeeded', total-s['pods_running']-s['pods_pending']-s['pods_failed'], '#1A5276'),
        ('Pending',   s['pods_pending'],  '#D68910'),
        ('Failed',    s['pods_failed'],   '#C0392B'),
    ]
    bar_d = Drawing(col2, 80)
    bx, by, bw, bh = 70, 8, col2-90, 12
    for i, (lbl, val, hx) in enumerate(pod_bars):
        y = by + i*(bh+6)
        bar_d.add(Rect(bx, y, bw, bh, fillColor=C_BGL2, strokeColor=None, rx=4, ry=4))
        fw = max(0, (val/total)*bw)
        if fw > 0:
            bar_d.add(Rect(bx, y, fw, bh, fillColor=colors.HexColor(hx), strokeColor=None, rx=4, ry=4))
        bar_d.add(String(bx-5, y+2, lbl, textAnchor='end', fontSize=7,
                         fillColor=_sc(C_DARK), fontName=N))
        bar_d.add(String(bx+bw+5, y+2, str(val), textAnchor='start', fontSize=7,
                         fillColor=_sc(C_GRAY), fontName=N))
    ps_content.append(bar_d)

    story.append(Table([[ns_content, ps_content]], colWidths=[col2, col2],
                       style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                          ('LEFTPADDING',(0,0),(-1,-1),0),
                                          ('RIGHTPADDING',(0,0),(0,0),12),
                                          ('TOPPADDING',(0,0),(-1,-1),0),
                                          ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
    story.append(Spacer(1, 8))

    # Comparativo histórico
    if delta and report.previous:
        story.extend(_sec(f'Comparativo — Hoje vs {report.previous.collected_at}', st))
        keys = [('health_score','Health Score',False),('pods_running','Pods Running',False),
                ('pods_failed','Pods Failed',True),('nodes_not_ready','Nodes NotReady',True),
                ('deployments_degraded','Deploys Degradados',True),('warning_events','Warning Events',True)]
        ch_data = [[Paragraph(h, ParagraphStyle('',fontName=R,fontSize=7.5,textColor=C_WHITE))
                    for h in ['Metrica','Anterior','Atual','Delta','Tendencia']]]
        for key, label, bad_up in keys:
            d = delta.get(key,{})
            prev_v, curr_v, diff = d.get('previous','?'), d.get('current','?'), d.get('diff',0)
            if isinstance(diff,(int,float)) and diff != 0:
                is_bad = (diff>0 and bad_up) or (diff<0 and not bad_up)
                chx = _sc(C_CRIT) if is_bad else _sc(C_OK)
                arr = '+' if diff>0 else ''
                trend = f'<font color="{chx}"><b>{"Up" if diff>0 else "Dn"} {abs(diff)}</b></font>'
                ds = f'<font color="{chx}">{arr}{diff}</font>'
            else:
                trend = '<font color="#999">—</font>'
                ds    = '<font color="#999">0</font>'
            ch_data.append([Paragraph(label,st['td']),Paragraph(str(prev_v),st['td_g']),
                             Paragraph(str(curr_v),st['td_b']),Paragraph(ds,st['td_c']),
                             Paragraph(trend,st['td_c'])])
        cmp_t = Table(ch_data, colWidths=[USE*r for r in [0.36,0.15,0.15,0.14,0.18]], repeatRows=1)
        cmp_t.setStyle(_tbl_style())
        story.append(cmp_t)

    if report.errors:
        story.append(Spacer(1,4))
        story.append(Paragraph('Coleta parcial: '+' | '.join(report.errors[:4]),
                     ParagraphStyle('',fontName=N,fontSize=6.5,textColor=C_WARN)))
    return story


# ── Página 2 — Recursos ───────────────────────────────────────────────────────
def _pg_resources(report, st):
    story = [PageBreak()]
    s = report.summary
    ns_sorted = sorted(report.namespaces, key=lambda n: n.pod_count, reverse=True)
    ns_active = [n for n in ns_sorted if n.pod_count > 0]
    ns_empty  = [n for n in ns_sorted if n.pod_count == 0]

    # Dois pies lado a lado
    story.extend(_sec('Distribuicao por Namespace e Status', st))
    NS_C = ['#0D5C63','#117A65','#1A8A94','#2E86C1','#6C3483','#784212','#1B4332','#922B21']
    pie_ns = [(n.name[:14], n.pod_count, NS_C[i%len(NS_C)]) for i,n in enumerate(ns_active[:8])]
    other = sum(n.pod_count for n in ns_active[8:])
    if other: pie_ns.append(('outros', other, '#95A5A6'))
    pie_st = []
    if s['pods_running']: pie_st.append(('Running',   s['pods_running'],  '#1E8449'))
    succ = s['total_pods']-s['pods_running']-s['pods_pending']-s['pods_failed']
    if succ>0:            pie_st.append(('Succeeded', succ,               '#1A5276'))
    if s['pods_pending']: pie_st.append(('Pending',   s['pods_pending'],  '#D68910'))
    if s['pods_failed']:  pie_st.append(('Failed',    s['pods_failed'],   '#C0392B'))

    p1 = _pie_draw(pie_ns, w=230, h=120, title='Pods por Namespace')
    p2 = _pie_draw(pie_st, w=180, h=120, title='Status dos Pods')
    story.append(Table([[p1,p2]], colWidths=[USE*0.56, USE*0.44],
                       style=TableStyle([('BACKGROUND',(0,0),(-1,-1),C_BGL),
                                          ('BOX',(0,0),(-1,-1),0.5,C_A),
                                          ('VALIGN',(0,0),(-1,-1),'MIDDLE')])))
    story.append(Spacer(1, 8))

    # Tabela namespaces
    story.extend(_sec('Namespaces — Detalhado', st))
    hd = ['Namespace','Status','Pods','Running','Pending','Failed','CPU (m)','Mem (MiB)','Idade']
    data = [hd]
    for ns in ns_active:
        data.append([Paragraph(ns.name,st['td_b']),_status(ns.status,st),
                     Paragraph(str(ns.pod_count),st['td_c']),Paragraph(str(ns.running),st['td_c']),
                     Paragraph(str(ns.pending),st['td_c']),Paragraph(str(ns.failed),st['td_c']),
                     Paragraph(str(ns.cpu_usage_m) if ns.cpu_usage_m else 'N/A',st['td_c']),
                     Paragraph(str(ns.mem_usage_mib) if ns.mem_usage_mib else 'N/A',st['td_c']),
                     Paragraph(ns.age,st['td_g'])])
    if ns_empty:
        data.append([Paragraph(f'+ {len(ns_empty)} namespaces sem pods omitidos',st['note'])]
                    +[Paragraph('',st['td']) for _ in range(8)])
    ws = [r*USE for r in [0.22,0.09,0.07,0.08,0.08,0.07,0.09,0.10,0.07]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    story.append(Spacer(1, 8))

    # Top pods
    story.extend(_sec('Top Pods por Consumo de Recurso', st))
    top_cpu = s.get('top_cpu_pods', [])
    top_mem = s.get('top_mem_pods', [])
    bar_data = [(f"{p['ns'][:8]}/{p['name'][:15]}", p.get('cpu_m',0),
                 next((x['mem_mib'] for x in top_mem if x['name']==p['name']),0))
                for p in top_cpu[:8]]
    if bar_data:
        story.append(_bar_h(bar_data, w=USE, h=88))
        story.append(Spacer(1, 6))

    col2 = USE/2 - 4
    def _top_t(title, rows, cols):
        d = [cols]+rows
        ws2 = [col2*r for r in [0.44,0.24,0.18,0.14]]
        t2 = Table(d, colWidths=ws2, repeatRows=1)
        t2.setStyle(_tbl_style())
        return t2

    cpu_r = [[Paragraph(p['name'][:36],st['td']),Paragraph(p['ns'],st['td_g']),
               Paragraph(p['cpu'],st['td_c']),Paragraph(str(p['cpu_m']),st['td_c'])]
              for p in top_cpu]
    mem_r = [[Paragraph(p['name'][:36],st['td']),Paragraph(p['ns'],st['td_g']),
               Paragraph(p['mem'],st['td_c']),Paragraph(str(p['mem_mib']),st['td_c'])]
              for p in top_mem]

    story.append(Table([[
        [Paragraph('Top 10 — CPU', st['sec']),
         HRFlowable(width='100%',thickness=1.5,color=C_A,spaceAfter=4),
         _top_t('',cpu_r,['Pod','Namespace','CPU','m'])],
        [Paragraph('Top 10 — Memoria', st['sec']),
         HRFlowable(width='100%',thickness=1.5,color=C_A,spaceAfter=4),
         _top_t('',mem_r,['Pod','Namespace','Mem','MiB'])],
    ]], colWidths=[col2,col2],
        style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                           ('LEFTPADDING',(0,0),(-1,-1),0),
                           ('RIGHTPADDING',(0,0),(0,0),8),
                           ('TOPPADDING',(0,0),(-1,-1),0),
                           ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
    return story


# ── Página 3 — Nodes ──────────────────────────────────────────────────────────
def _pg_nodes(report, st):
    story = [PageBreak()]
    story.extend(_sec('Nodes do Cluster — Detalhado', st))
    hd = ['Node','Status','Roles','Versao','CPU Cap.','CPU Uso','CPU%','Mem Cap.','Mem Uso','Mem%','Idade']
    data = [hd]
    for n in report.nodes:
        data.append([Paragraph(n.name,st['td_b']),_status(n.status,st),
                     Paragraph(n.roles[:14],st['td_g']),Paragraph(n.version,st['td_g']),
                     Paragraph(n.cpu_capacity,st['td_c']),Paragraph(n.cpu_usage,st['td_c']),
                     _pct(n.cpu_pct,n.cpu_usage,st),
                     Paragraph(n.mem_capacity,st['td_c']),Paragraph(n.mem_usage,st['td_c']),
                     _pct(n.mem_pct,n.mem_usage,st),
                     Paragraph(n.age,st['td_g'])])
    ws = [r*USE for r in [0.19,0.08,0.10,0.09,0.07,0.07,0.06,0.09,0.08,0.06,0.05]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    return story


# ── Página 4 — Workloads ─────────────────────────────────────────────────────
def _pg_workloads(report, st):
    story = [PageBreak()]

    story.extend(_sec('Deployments', st))
    hd = ['Deployment','Namespace','Desejado','Pronto','Disponivel','Atualizado','Idade']
    data = [hd]
    for d in report.deployments:
        ok = d.ready==d.desired and d.desired>0
        rc = _sc(C_OK) if ok else _sc(C_CRIT if d.ready==0 and d.desired>0 else C_WARN)
        data.append([Paragraph(d.name,st['td_b']),Paragraph(d.namespace,st['td_g']),
                     Paragraph(str(d.desired),st['td_c']),
                     Paragraph(f'<font color="{rc}"><b>{d.ready}</b></font>',st['td_c']),
                     Paragraph(str(d.available),st['td_c']),Paragraph(str(d.up_to_date),st['td_c']),
                     Paragraph(d.age,st['td_g'])])
    ws = [r*USE for r in [0.30,0.22,0.10,0.10,0.10,0.10,0.08]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    story.append(Spacer(1,8))

    col2 = USE/2-4
    left_s, right_s = [], []

    if report.statefulsets:
        left_s.extend(_sec('StatefulSets', st))
        hd2 = ['StatefulSet','Namespace','Desejado','Pronto','Idade']
        d2 = [hd2]
        for s2 in report.statefulsets:
            rc = _sc(C_OK) if s2.ready==s2.desired else _sc(C_CRIT)
            d2.append([Paragraph(s2.name,st['td_b']),Paragraph(s2.namespace,st['td_g']),
                       Paragraph(str(s2.desired),st['td_c']),
                       Paragraph(f'<font color="{rc}"><b>{s2.ready}</b></font>',st['td_c']),
                       Paragraph(s2.age,st['td_g'])])
        ws2 = [r*col2 for r in [0.35,0.28,0.13,0.13,0.11]]
        t2 = Table(d2, colWidths=ws2, repeatRows=1)
        t2.setStyle(_tbl_style())
        left_s.append(t2)

    if report.daemonsets:
        right_s.extend(_sec('DaemonSets', st))
        hd3 = ['DaemonSet','Namespace','Desejado','Pronto','Idade']
        d3 = [hd3]
        for ds in report.daemonsets:
            rc = _sc(C_OK) if ds.ready==ds.desired else _sc(C_WARN)
            d3.append([Paragraph(ds.name,st['td_b']),Paragraph(ds.namespace,st['td_g']),
                       Paragraph(str(ds.desired),st['td_c']),
                       Paragraph(f'<font color="{rc}"><b>{ds.ready}</b></font>',st['td_c']),
                       Paragraph(ds.age,st['td_g'])])
        ws3 = [r*col2 for r in [0.35,0.28,0.12,0.12,0.10]]
        t3 = Table(d3, colWidths=ws3, repeatRows=1)
        t3.setStyle(_tbl_style())
        right_s.append(t3)

    if left_s or right_s:
        story.append(Table([[left_s or [Spacer(1,1)],right_s or [Spacer(1,1)]]],
                           colWidths=[col2,col2],
                           style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                              ('LEFTPADDING',(0,0),(-1,-1),0),
                                              ('RIGHTPADDING',(0,0),(0,0),8),
                                              ('TOPPADDING',(0,0),(-1,-1),0),
                                              ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
        story.append(Spacer(1,8))

    cj_s, job_s = [], []
    if report.cronjobs:
        cj_s.extend(_sec('CronJobs', st))
        hc = ['CronJob','Namespace','Schedule','Ultimo','Idade']
        dc = [hc]
        for cj in report.cronjobs:
            dc.append([Paragraph(cj.name[:30],st['td_b']),Paragraph(cj.namespace[:20],st['td_g']),
                       Paragraph(cj.schedule,st['td_g']),Paragraph(cj.last_schedule,st['td_g']),
                       Paragraph(cj.age,st['td_g'])])
        wc = [r*col2 for r in [0.36,0.22,0.22,0.12,0.08]]
        tc = Table(dc, colWidths=wc, repeatRows=1)
        tc.setStyle(_tbl_style())
        cj_s.append(tc)

    if report.jobs:
        job_s.extend(_sec('Jobs', st))
        hj = ['Job','Namespace','Status','Duracao','Idade']
        dj = [hj]
        for j in report.jobs:
            if j.namespace == 'status-report': continue
            dj.append([Paragraph(j.name[:28],st['td_b']),Paragraph(j.namespace[:18],st['td_g']),
                       _status(j.status,st),Paragraph(j.duration,st['td_g']),Paragraph(j.age,st['td_g'])])
        wj = [r*col2 for r in [0.36,0.22,0.14,0.16,0.12]]
        tj = Table(dj, colWidths=wj, repeatRows=1)
        tj.setStyle(_tbl_style())
        job_s.append(tj)

    if cj_s or job_s:
        story.append(Table([[cj_s or [Spacer(1,1)],job_s or [Spacer(1,1)]]],
                           colWidths=[col2,col2],
                           style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                              ('LEFTPADDING',(0,0),(-1,-1),0),
                                              ('RIGHTPADDING',(0,0),(0,0),8),
                                              ('TOPPADDING',(0,0),(-1,-1),0),
                                              ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
    return story


# ── Página 5 — Pods ──────────────────────────────────────────────────────────
def _pg_pods(report, st):
    story = [PageBreak()]
    SYS = {'kube-system','kube-node-lease','kube-public','cattle-system',
           'cattle-fleet-system','cattle-fleet-local-system','cattle-capi-system',
           'cattle-turtles-system','fleet-default','fleet-local','local','local-path-storage'}

    problem = [p for p in report.pods if (
        p.status not in ('Running','Succeeded') or
        (p.namespace in SYS and p.restarts>=20) or
        (p.namespace not in SYS and p.restarts>=5))]
    normal = [p for p in report.pods if p not in problem]

    story.extend(_sec(f'Pods — Atencao ({len(problem)})', st))
    if not problem:
        story.append(Paragraph('Nenhum pod com problemas detectado.', st['td']))
    else:
        hd = ['Pod','Namespace','Status','Ready','Restarts','CPU','Mem','Node','Idade']
        data = [hd]
        for p in problem:
            data.append([Paragraph(p.name[:34],st['td_b']),Paragraph(p.namespace,st['td_g']),
                         _status(p.status,st),Paragraph(p.ready,st['td_c']),
                         Paragraph(str(p.restarts),st['td_c']),Paragraph(p.cpu_usage,st['td_c']),
                         Paragraph(p.mem_usage,st['td_c']),Paragraph(p.node[:16] if p.node else '?',st['td_g']),
                         Paragraph(p.age,st['td_g'])])
        ws = [r*USE for r in [0.24,0.13,0.10,0.07,0.07,0.07,0.07,0.17,0.06]]
        t = Table(data, colWidths=ws, repeatRows=1)
        t.setStyle(_tbl_style())
        story.append(t)

    story.append(Spacer(1,10))
    story.extend(_sec(f'Pods — Saudaveis ({min(50,len(normal))} de {len(normal)})', st))
    hd2 = ['Pod','Namespace','Status','Ready','Restarts','CPU','Mem','Idade']
    data2 = [hd2]
    for p in normal[:50]:
        data2.append([Paragraph(p.name[:36],st['td_b']),Paragraph(p.namespace,st['td_g']),
                      _status(p.status,st),Paragraph(p.ready,st['td_c']),
                      Paragraph(str(p.restarts),st['td_c']),Paragraph(p.cpu_usage,st['td_c']),
                      Paragraph(p.mem_usage,st['td_c']),Paragraph(p.age,st['td_g'])])
    ws2 = [r*USE for r in [0.28,0.15,0.10,0.07,0.07,0.08,0.08,0.07]]
    t2 = Table(data2, colWidths=ws2, repeatRows=1)
    t2.setStyle(_tbl_style())
    story.append(t2)
    return story


# ── Página 6 — Rede + Storage ─────────────────────────────────────────────────
def _pg_net_stor(report, st):
    story = [PageBreak()]

    story.extend(_sec('PersistentVolumeClaims', st))
    hd = ['PVC','Namespace','Status','Volume','Cap.','StorageClass','Modo','Idade']
    data = [hd]
    for p in report.pvcs:
        data.append([Paragraph(p.name[:24],st['td_b']),Paragraph(p.namespace,st['td_g']),
                     _status(p.status,st),Paragraph(p.volume[:18],st['td_g']),
                     Paragraph(p.capacity,st['td_c']),Paragraph(p.storage_class[:14],st['td_g']),
                     Paragraph(p.access_modes[:14],st['td_g']),Paragraph(p.age,st['td_g'])])
    ws = [r*USE for r in [0.22,0.14,0.08,0.18,0.08,0.14,0.10,0.06]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    story.append(Spacer(1,8))

    col2 = USE/2-4
    left_s, right_s = [], []

    if report.ingresses:
        left_s.extend(_sec('Ingresses', st))
        hi = ['Ingress','Namespace','Hosts','Address','Ports','Idade']
        di = [hi]
        for i in report.ingresses:
            di.append([Paragraph(i.name[:20],st['td_b']),Paragraph(i.namespace[:14],st['td_g']),
                       Paragraph(i.hosts[:28],st['td_g']),Paragraph(i.address[:16],st['td_g']),
                       Paragraph(i.ports,st['td_c']),Paragraph(i.age,st['td_g'])])
        wi = [r*col2 for r in [0.20,0.16,0.26,0.16,0.14,0.08]]
        ti = Table(di, colWidths=wi, repeatRows=1)
        ti.setStyle(_tbl_style())
        left_s.append(ti)

    if report.services:
        right_s.extend(_sec('Services Expostos', st))
        hs = ['Service','Namespace','Tipo','External IP','Ports','Idade']
        ds = [hs]
        for sv in report.services:
            ds.append([Paragraph(sv.name[:20],st['td_b']),Paragraph(sv.namespace[:14],st['td_g']),
                       Paragraph(sv.type,st['td_g']),Paragraph(sv.external_ip[:14],st['td_g']),
                       Paragraph(sv.ports[:26],st['td_g']),Paragraph(sv.age,st['td_g'])])
        ws2 = [r*col2 for r in [0.20,0.16,0.12,0.14,0.28,0.10]]
        ts = Table(ds, colWidths=ws2, repeatRows=1)
        ts.setStyle(_tbl_style())
        right_s.append(ts)

    if left_s or right_s:
        story.append(Table([[left_s or [Spacer(1,1)],right_s or [Spacer(1,1)]]],
                           colWidths=[col2,col2],
                           style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                              ('LEFTPADDING',(0,0),(-1,-1),0),
                                              ('RIGHTPADDING',(0,0),(0,0),8),
                                              ('TOPPADDING',(0,0),(-1,-1),0),
                                              ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
        story.append(Spacer(1,8))

    if report.hpas:
        story.extend(_sec('Horizontal Pod Autoscalers', st))
        hh = ['HPA','Namespace','Target','Min','Max','Atual','CPU Target','CPU Atual','Idade']
        dh = [hh]
        for h in report.hpas:
            rc = _sc(C_WARN) if h.current_replicas>=h.max_replicas else _sc(C_OK)
            dh.append([Paragraph(h.name[:20],st['td_b']),Paragraph(h.namespace[:14],st['td_g']),
                       Paragraph(h.target[:22],st['td_g']),Paragraph(str(h.min_replicas),st['td_c']),
                       Paragraph(str(h.max_replicas),st['td_c']),
                       Paragraph(f'<font color="{rc}"><b>{h.current_replicas}</b></font>',st['td_c']),
                       Paragraph(h.cpu_target_pct,st['td_c']),Paragraph(h.cpu_current_pct,st['td_c']),
                       Paragraph(h.age,st['td_g'])])
        wh = [r*USE for r in [0.14,0.13,0.20,0.06,0.06,0.07,0.10,0.10,0.07]]
        th = Table(dh, colWidths=wh, repeatRows=1)
        th.setStyle(_tbl_style())
        story.append(th)
    return story


# ── Página 7 — Events ─────────────────────────────────────────────────────────
def _pg_events(report, st):
    story = [PageBreak()]
    story.extend(_sec(f'Warning Events ({len(report.events)} eventos)', st))
    if not report.events:
        story.append(Paragraph('Nenhum Warning Event encontrado.', st['td']))
        return story
    hd = ['Namespace','Razao','Objeto','Mensagem','Count','Ha']
    data = [hd]
    for e in report.events[:60]:
        data.append([Paragraph(e.namespace[:16],st['td_g']),Paragraph(e.reason[:16],st['td_b']),
                     Paragraph(e.object[:30],st['td_g']),Paragraph(e.message[:80],st['td_g']),
                     Paragraph(str(e.count),st['td_c']),Paragraph(e.last_seen,st['td_g'])])
    ws = [r*USE for r in [0.13,0.12,0.22,0.40,0.07,0.07]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    return story


# ── Template com rodapé ───────────────────────────────────────────────────────
class _Doc(SimpleDocTemplate):
    def __init__(self, fn, report, **kw):
        self.report = report
        super().__init__(fn, **kw)

    def afterPage(self):
        c = self.canv
        r = self.report
        c.saveState()
        # Rodapé teal
        c.setFillColor(C_P)
        c.rect(0, 0, W, 9*mm, fill=1, stroke=0)
        # Linha acento
        c.setFillColor(C_A)
        c.rect(0, 9*mm-1.5, W, 1.5, fill=1, stroke=0)
        c.setFont(R if _FONTS_OK else 'Helvetica-Bold', 6.5)
        c.setFillColor(C_WHITE)
        c.drawString(MAR, 3.5*mm,
            f'OpenLabs  |  K8s Status Report  |  {r.cluster_name}  |  {r.collected_at}  |  Confidencial')
        c.drawRightString(W-MAR, 3.5*mm, f'Pagina {c.getPageNumber()}')
        c.restoreState()


# ── Entry point ───────────────────────────────────────────────────────────────
def generate_pdf(report, output_path, delta=None):
    st = _S()
    story = []
    story.extend(_pg_exec(report, st, delta or {}))
    story.extend(_pg_resources(report, st))
    story.extend(_pg_nodes(report, st))
    story.extend(_pg_workloads(report, st))
    story.extend(_pg_pods(report, st))
    story.extend(_pg_net_stor(report, st))
    story.extend(_pg_events(report, st))

    doc = _Doc(output_path, report, pagesize=A4,
               leftMargin=MAR, rightMargin=MAR,
               topMargin=MAR, bottomMargin=13*mm)
    doc.build(story)
    logger.info(f'PDF gerado: {output_path}')
    return output_path
