#!/usr/bin/env python3
# =============================================================================
# Autor:   Diego Regis M. F. dos Santos
# Email:   diego-f-santos@openlabs.com.br
# Time:    OpenLabs - DevOps | Infra
# Versao:  6.0.0
# Arquivo: pdf_generator.py
# Desc:    K8s Status Report - Layout denso estilo dashboard corporativo
# Changelog v6.0.0:
#   - Health Score com trend (↑↓→) e delta vs anterior
#   - Coluna "Último Restart" na tabela Pods com Atenção
#   - PVC Pending prolongado como alerta crítico na pág 1
#   - Página 1 mais limpa: Workloads movidos para pág 2 / Pods Atenção compacto
#   - Rodapé com link do repo
#   - Restart threshold exibido no rodapé da tabela de pods
# =============================================================================

import logging
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, PageBreak)
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from models import ClusterReport
from cache import diff_summary

logger = logging.getLogger(__name__)

# ── Fonte Carlito ──────────────────────────────────────────────────────────────
_FONT_DIR = '/usr/share/fonts/truetype/crosextra'
_FONTS_OK = False
try:
    pdfmetrics.registerFont(TTFont('C',  f'{_FONT_DIR}/Carlito-Regular.ttf'))
    pdfmetrics.registerFont(TTFont('CB', f'{_FONT_DIR}/Carlito-Bold.ttf'))
    pdfmetrics.registerFont(TTFont('CI', f'{_FONT_DIR}/Carlito-Italic.ttf'))
    _FONTS_OK = True
except Exception as e:
    logger.warning(f'Carlito nao encontrado, usando Helvetica: {e}')

B  = 'CB' if _FONTS_OK else 'Helvetica-Bold'
N  = 'C'  if _FONTS_OK else 'Helvetica'
IT = 'CI' if _FONTS_OK else 'Helvetica-Oblique'

# ── Paleta ────────────────────────────────────────────────────────────────────
C_HDR  = colors.HexColor('#0A3D40')
C_P    = colors.HexColor('#0D5C63')
C_S    = colors.HexColor('#1A8A94')
C_A    = colors.HexColor('#3DBAC2')
C_BGL  = colors.HexColor('#F2F9FA')
C_BGL2 = colors.HexColor('#EBF5F7')
C_OK   = colors.HexColor('#1E8449')
C_WARN = colors.HexColor('#D68910')
C_CRIT = colors.HexColor('#C0392B')
C_INFO = colors.HexColor('#1A5276')
C_GRAY = colors.HexColor('#6C7A7D')
C_DARK = colors.HexColor('#1A252F')
C_WHITE= colors.white
C_LGRID= colors.HexColor('#C8E6E9')
C_SEC  = colors.HexColor('#1B6B72')

W, H  = A4
MAR   = 12 * mm
USE   = W - 2 * MAR


# ── Helpers ────────────────────────────────────────────────────────────────────
def _hx(c):
    return c.hexval() if hasattr(c, 'hexval') else '#888888'


def _st():
    def p(name, fn=N, fs=8, tc=C_DARK, **kw):
        return ParagraphStyle(name, fontName=fn, fontSize=fs, textColor=tc,
                              leading=kw.pop('leading', fs * 1.3), **kw)
    return {
        'title':  p('title',  B, 13, C_WHITE, leading=17),
        'sub':    p('sub',    N,  7, C_A,     leading=10),
        'sec':    p('sec',    B,  7, C_WHITE,  leading=10, spaceBefore=0, spaceAfter=0),
        'th':     p('th',     B,  6.5, C_WHITE, leading=9),
        'td':     p('td',     N,  6.5, C_DARK,  leading=9),
        'td_g':   p('td_g',   N,  6,   C_GRAY,  leading=8.5),
        'td_c':   p('td_c',   N,  6.5, C_DARK,  leading=9, alignment=TA_CENTER),
        'td_r':   p('td_r',   N,  6.5, C_DARK,  leading=9, alignment=TA_RIGHT),
        'td_b':   p('td_b',   B,  6.5, C_DARK,  leading=9),
        'note':   p('note',   IT, 5.5, C_GRAY,  leading=7.5),
        'kpi_v':  p('kpi_v',  B, 18, C_P,   leading=20, alignment=TA_CENTER),
        'kpi_l':  p('kpi_l',  N,  6, C_GRAY, leading=8,  alignment=TA_CENTER),
        'kpi2_v': p('kpi2_v', B, 11, C_P,   leading=13, alignment=TA_CENTER),
        'kpi2_l': p('kpi2_l', N,  6, C_GRAY, leading=8,  alignment=TA_CENTER),
        'al_sev': p('al_sev', B,  6.5, C_WHITE, leading=9, alignment=TA_CENTER),
        'al_msg': p('al_msg', N,  7,   C_DARK,  leading=10),
        'hs_v':   p('hs_v',   B, 26, C_P,   leading=30, alignment=TA_CENTER),
        'hs_l':   p('hs_l',   N,  7, C_GRAY, leading=9,  alignment=TA_CENTER),
    }


def _tbl_style(hdr_bg=None):
    bg = hdr_bg or C_P
    return TableStyle([
        ('BACKGROUND',    (0, 0), (-1,  0), bg),
        ('TEXTCOLOR',     (0, 0), (-1,  0), C_WHITE),
        ('FONTNAME',      (0, 0), (-1,  0), B),
        ('FONTSIZE',      (0, 0), (-1,  0), 6.5),
        ('TOPPADDING',    (0, 0), (-1,  0), 4),
        ('BOTTOMPADDING', (0, 0), (-1,  0), 4),
        ('FONTNAME',      (0, 1), (-1, -1), N),
        ('FONTSIZE',      (0, 1), (-1, -1), 6.5),
        ('TEXTCOLOR',     (0, 1), (-1, -1), C_DARK),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [C_WHITE, C_BGL]),
        ('LINEBELOW',     (0, 0), (-1,  0), 0.5, C_A),
        ('LINEBELOW',     (0, 1), (-1, -1), 0.2, C_LGRID),
        ('BOX',           (0, 0), (-1, -1), 0.5, C_A),
        ('TOPPADDING',    (0, 1), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 2),
        ('LEFTPADDING',   (0, 0), (-1, -1), 5),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ])


def _sec_hdr(title, width=None):
    w = width or USE
    return Table(
        [[Paragraph(title.upper(), ParagraphStyle('sh', fontName=B, fontSize=7,
                    textColor=C_WHITE, leading=10))]],
        colWidths=[w],
        style=TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), C_SEC),
            ('TOPPADDING',    (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
            ('RIGHTPADDING',  (0,0), (-1,-1), 8),
        ])
    )


def _status_cell(s, st):
    up = s.upper()
    if up in ('RUNNING','READY','BOUND','ACTIVE','COMPLETE','SUCCEEDED','TRUE'):
        c, bg = C_OK, '#D5F5E3'
    elif up in ('PENDING','TERMINATING','UNKNOWN','PROGRESSING'):
        c, bg = C_WARN, '#FEF3CD'
    elif up in ('FAILED','CRASHLOOPBACKOFF','ERROR','NOTREADY','LOST','OOMKILLED'):
        c, bg = C_CRIT, '#FADBD8'
    else:
        c, bg = C_GRAY, '#F2F3F4'
    return Paragraph(
        f'<font color="{_hx(c)}"><b>{s[:16]}</b></font>',
        ParagraphStyle('sc', fontName=B, fontSize=6.5, textColor=c,
                       leading=9, alignment=TA_CENTER,
                       backColor=colors.HexColor(bg))
    )


def _pct_cell(pct, val, st):
    if not val or val in ('N/A', '', '0', 0):
        return Paragraph('N/A', st['td_g'])
    c = C_CRIT if pct > 85 else (C_WARN if pct > 65 else C_OK)
    return Paragraph(f'<font color="{_hx(c)}"><b>{pct:.0f}%</b></font>', st['td_c'])


# ── Health Score visual com trend ──────────────────────────────────────────────
def _health_gauge(score, trend=None, delta=None, w=110, h=80):
    d = Drawing(w, h)
    c = C_OK if score >= 85 else (C_WARN if score >= 60 else C_CRIT)

    # Barra de progresso
    d.add(Rect(5, 28, w-10, 10, fillColor=C_BGL2, strokeColor=None, rx=5, ry=5))
    fw = max(10, (score/100)*(w-10))
    d.add(Rect(5, 28, fw, 10, fillColor=c, strokeColor=None, rx=5, ry=5))

    # Score
    d.add(String(w/2, 44, f'{score:.1f}%',
                 textAnchor='middle', fontSize=22, fontName=B,
                 fillColor=_hx(c)))

    # Trend
    if trend and delta is not None:
        if trend == 'up':
            t_sym, t_col = f'↑ +{delta}%', _hx(C_OK)
        elif trend == 'down':
            t_sym, t_col = f'↓ {delta}%', _hx(C_CRIT)
        else:
            t_sym, t_col = '→ estável', _hx(C_GRAY)
        d.add(String(w/2, 18, t_sym,
                     textAnchor='middle', fontSize=7, fontName=B,
                     fillColor=t_col))

    d.add(String(w/2, 8, 'Health Score',
                 textAnchor='middle', fontSize=7, fontName=N,
                 fillColor=_hx(C_GRAY)))
    return d


# ── KPI Card ──────────────────────────────────────────────────────────────────
def _kpi(val, lbl, col, w, st, sub=None):
    rows = [
        [Paragraph(f'<font color="{_hx(col)}"><b>{val}</b></font>',
                   ParagraphStyle('', fontName=B, fontSize=16,
                                  alignment=TA_CENTER, leading=20,
                                  textColor=col))],
        [Paragraph(lbl, st['kpi_l'])],
    ]
    if sub:
        rows.append([Paragraph(sub, ParagraphStyle('', fontName=N, fontSize=5.5,
                               alignment=TA_CENTER, textColor=C_GRAY, leading=8))])
    return Table(rows, colWidths=[w-6],
                 style=TableStyle([
                     ('BACKGROUND',    (0,0),(-1,-1), C_BGL),
                     ('BOX',           (0,0),(-1,-1), 0.5, C_A),
                     ('LINEABOVE',     (0,0),(-1, 0), 2.5, col),
                     ('TOPPADDING',    (0,0),(-1,-1), 4),
                     ('BOTTOMPADDING', (0,0),(-1,-1), 4),
                     ('LEFTPADDING',   (0,0),(-1,-1), 3),
                     ('RIGHTPADDING',  (0,0),(-1,-1), 3),
                     ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
                 ]))


def _kpi2(val, lbl, w, st):
    return Table([
        [Paragraph(str(val), st['kpi2_v'])],
        [Paragraph(lbl,      st['kpi2_l'])],
    ], colWidths=[w-6],
       style=TableStyle([
           ('BACKGROUND',    (0,0),(-1,-1), C_WHITE),
           ('BOX',           (0,0),(-1,-1), 0.5, C_LGRID),
           ('TOPPADDING',    (0,0),(-1,-1), 3),
           ('BOTTOMPADDING', (0,0),(-1,-1), 3),
           ('LEFTPADDING',   (0,0),(-1,-1), 3),
           ('RIGHTPADDING',  (0,0),(-1,-1), 3),
           ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
       ]))


def _kpi_row(items, w_each, st):
    cells = [_kpi(v, l, c, w_each, st, s) for v,l,c,s in items]
    return Table([cells], colWidths=[w_each]*len(cells),
                 style=TableStyle([('LEFTPADDING',(0,0),(-1,-1),3),
                                   ('RIGHTPADDING',(0,0),(-1,-1),3),
                                   ('TOPPADDING',(0,0),(-1,-1),2),
                                   ('BOTTOMPADDING',(0,0),(-1,-1),2)]))


def _kpi2_row(items, w_each, st):
    cells = [_kpi2(v, l, w_each, st) for v,l in items]
    return Table([cells], colWidths=[w_each]*len(cells),
                 style=TableStyle([('LEFTPADDING',(0,0),(-1,-1),3),
                                   ('RIGHTPADDING',(0,0),(-1,-1),3),
                                   ('TOPPADDING',(0,0),(-1,-1),2),
                                   ('BOTTOMPADDING',(0,0),(-1,-1),2)]))


# ── Alert badge ───────────────────────────────────────────────────────────────
def _alert_row(sev, msg, col, col2):
    bg = {_hx(C_CRIT): colors.HexColor('#FADBD8'),
          _hx(C_WARN): colors.HexColor('#FEF3CD'),
          _hx(C_INFO): colors.HexColor('#D6EAF8')}.get(_hx(col), C_BGL)
    return Table([[
        Table([[Paragraph(sev, ParagraphStyle('', fontName=B, fontSize=6,
                          textColor=C_WHITE, alignment=TA_CENTER, leading=9))]],
              colWidths=[46],
              style=TableStyle([('BACKGROUND',(0,0),(-1,-1),col),
                                ('TOPPADDING',(0,0),(-1,-1),2),
                                ('BOTTOMPADDING',(0,0),(-1,-1),2),
                                ('LEFTPADDING',(0,0),(-1,-1),3),
                                ('RIGHTPADDING',(0,0),(-1,-1),3)])),
        Paragraph(msg, ParagraphStyle('', fontName=N, fontSize=7,
                  textColor=C_DARK, leading=10)),
    ]], colWidths=[50, col2-50-8],
        style=TableStyle([('BACKGROUND',(0,0),(-1,-1),bg),
                          ('TOPPADDING',(0,0),(-1,-1),2),
                          ('BOTTOMPADDING',(0,0),(-1,-1),2),
                          ('LEFTPADDING',(0,0),(-1,-1),4),
                          ('RIGHTPADDING',(0,0),(-1,-1),4),
                          ('VALIGN',(0,0),(-1,-1),'MIDDLE')]))


# ════════════════════════════════════════════════════════════════════════════════
# PÁGINA 1 — EXECUTIVO (layout limpo: sem workloads, pods atenção compacto)
# ════════════════════════════════════════════════════════════════════════════════
def _pg_exec(report, st, delta):
    story = []
    s = report.summary

    # ── Header ────────────────────────────────────────────────────────────────
    hdr = Table([[
        Table([
            [Paragraph('Kubernetes Status Report', st['title'])],
            [Paragraph('OpenLabs — DevOps | Infra', st['sub'])],
        ], colWidths=[USE*0.55],
           style=TableStyle([('BACKGROUND',(0,0),(-1,-1),C_HDR),
                             ('LEFTPADDING',(0,0),(-1,-1),12),
                             ('TOPPADDING',(0,0),(-1,-1),10),
                             ('BOTTOMPADDING',(0,0),(-1,-1),10)])),
        Table([
            [Paragraph(f'Cluster: <b>{report.cluster_name}</b>', st['sub'])],
            [Paragraph(f'{report.collected_at}', st['sub'])],
        ], colWidths=[USE*0.45],
           style=TableStyle([('BACKGROUND',(0,0),(-1,-1),C_HDR),
                             ('ALIGN',(0,0),(-1,-1),'RIGHT'),
                             ('RIGHTPADDING',(0,0),(-1,-1),12),
                             ('TOPPADDING',(0,0),(-1,-1),10),
                             ('BOTTOMPADDING',(0,0),(-1,-1),10)])),
    ]], colWidths=[USE*0.55, USE*0.45],
        style=TableStyle([('BACKGROUND',(0,0),(-1,-1),C_HDR),
                          ('LEFTPADDING',(0,0),(-1,-1),0),
                          ('RIGHTPADDING',(0,0),(-1,-1),0),
                          ('TOPPADDING',(0,0),(-1,-1),0),
                          ('BOTTOMPADDING',(0,0),(-1,-1),0),
                          ('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    story.append(hdr)

    # ── Status strip ──────────────────────────────────────────────────────────
    has_c = (s.get('nodes_not_ready',0)>0 or s.get('pods_crashloop',0)>0
             or s.get('pvcs_lost',0)>0 or s.get('pvcs_pending_alert',0)>0)
    has_w = (s.get('pods_failed',0)>0 or s.get('deployments_degraded',0)>0
             or s.get('pods_high_restarts',0)>0 or s.get('pods_pending',0)>0)
    sc = C_CRIT if has_c else (C_WARN if has_w else C_OK)
    txt = ('■ CRITICO — Falhas detectadas' if has_c
           else ('■ ATENCAO — Itens que requerem monitoramento' if has_w
                 else '■ CLUSTER OPERACIONAL — Todos os servicos saudaveis'))
    story.append(Table([[Paragraph(txt, ParagraphStyle('',fontName=B,fontSize=7.5,
                         textColor=C_WHITE,alignment=TA_LEFT))]],
                       colWidths=[USE],
                       style=TableStyle([('BACKGROUND',(0,0),(-1,-1),sc),
                                         ('TOPPADDING',(0,0),(-1,-1),4),
                                         ('BOTTOMPADDING',(0,0),(-1,-1),4),
                                         ('LEFTPADDING',(0,0),(-1,-1),10)])))
    story.append(Spacer(1, 5))

    # ── Seção: Resumo Executivo ────────────────────────────────────────────────
    story.append(_sec_hdr('Resumo Executivo'))
    story.append(Spacer(1, 4))

    # Gauge com trend + KPIs primários
    gauge_w = 118
    col6 = (USE - gauge_w - 18) / 6
    kpi_items = [
        (f"{s['nodes_ready']}/{s['total_nodes']}", 'Nodes Ready',
         C_OK if s['nodes_not_ready']==0 else C_CRIT, None),
        (str(s['total_pods']),     'Pods Total',    C_P,   None),
        (str(s['pods_running']),   'Running',       C_OK,  'pods OK'),
        (str(s['pods_failed']),    'Failed / Crash',
         C_CRIT if s['pods_failed']>0 else C_OK, None),
        (str(s['deployments_degraded']), 'Deploys Deg.',
         C_CRIT if s['deployments_degraded']>0 else C_OK, None),
        (str(s['warning_events']), 'Warnings',
         C_CRIT if s['warning_events']>10 else (C_WARN if s['warning_events']>0 else C_OK), None),
    ]
    gauge_tbl = Table(
        [[_health_gauge(s.get('health_score',100),
                        trend=s.get('health_trend'),
                        delta=s.get('health_delta'),
                        w=gauge_w-8, h=75)]],
        colWidths=[gauge_w],
        style=TableStyle([('BACKGROUND',(0,0),(-1,-1),C_BGL),
                          ('BOX',(0,0),(-1,-1),0.5,C_A),
                          ('TOPPADDING',(0,0),(-1,-1),4),
                          ('BOTTOMPADDING',(0,0),(-1,-1),4),
                          ('LEFTPADDING',(0,0),(-1,-1),4)]))
    kpi_tbl = _kpi_row(kpi_items, col6, st)
    story.append(Table([[gauge_tbl, kpi_tbl]],
                       colWidths=[gauge_w+8, USE-gauge_w-8],
                       style=TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                                         ('LEFTPADDING',(0,0),(-1,-1),0),
                                         ('RIGHTPADDING',(0,0),(0,0),8),
                                         ('TOPPADDING',(0,0),(-1,-1),0),
                                         ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
    story.append(Spacer(1, 4))

    # KPI secundários
    pvc_label = 'PVCs Bound'
    pvc_color = C_P
    if s.get('pvcs_pending_alert', 0) > 0:
        pvc_label = f"PVCs ⚠{s['pvcs_pending_alert']}Pend"
        pvc_color = C_CRIT
    elif s.get('pvcs_lost', 0) > 0:
        pvc_color = C_CRIT

    col7 = USE / 7
    kpi2_items = [
        (s['total_namespaces'],   'Namespaces'),
        (s['total_statefulsets'], 'StatefulSets'),
        (s['total_daemonsets'],   'DaemonSets'),
        (f"{s['pvcs_bound']}/{s['total_pvcs']}", pvc_label),
        (s['total_ingresses'],    'Ingresses'),
        (s['total_hpas'],         'HPAs'),
        (s.get('total_cronjobs','-'), 'CronJobs'),
    ]
    story.append(_kpi2_row(kpi2_items, col7, st))
    story.append(Spacer(1, 6))

    # ── 2 colunas: Alertas | Nodes ────────────────────────────────────────────
    col2 = USE / 2 - 6

    # Alertas — inclui PVC Pending
    alerts = []
    if s.get('pods_crashloop',0):
        alerts.append((C_CRIT,'CRITICO', f"{s['pods_crashloop']} Pod(s) em CrashLoopBackOff"))
    if s.get('nodes_not_ready',0):
        alerts.append((C_CRIT,'CRITICO', f"{s['nodes_not_ready']} Node(s) NOT READY"))
    if s.get('pvcs_lost',0):
        alerts.append((C_CRIT,'CRITICO', f"{s['pvcs_lost']} PVC(s) LOST"))
    if s.get('pvcs_pending_alert',0):
        pvc_list = s.get('pvcs_pending_alert_list', [])
        names = ', '.join(f"{p['ns']}/{p['name']}" for p in pvc_list[:2])
        alerts.append((C_CRIT,'CRITICO',
                       f"{s['pvcs_pending_alert']} PVC(s) PENDING: {names}"))
    if s.get('deployments_degraded',0):
        alerts.append((C_WARN,'ATENCAO', f"{s['deployments_degraded']} Deployment(s) degradado(s)"))
    if s.get('pods_high_restarts',0):
        alerts.append((C_WARN,'ATENCAO', f"{s['pods_high_restarts']} Pod(s) com restarts elevados"))
    if s.get('pods_failed',0):
        alerts.append((C_WARN,'ATENCAO', f"{s['pods_failed']} Pod(s) FAILED"))
    if s.get('pods_pending',0):
        alerts.append((C_WARN,'ATENCAO', f"{s['pods_pending']} Pod(s) PENDING"))
    if s.get('warning_events',0)>0:
        alerts.append((C_INFO,'INFO', f"{s['warning_events']} Warning Events recentes no cluster"))

    al_block = [_sec_hdr('Alertas Ativos', col2)]
    al_block.append(Spacer(1, 3))
    if alerts:
        for col, sev, msg in alerts[:7]:
            al_block.append(_alert_row(sev, msg, col, col2))
            al_block.append(Spacer(1, 2))
    else:
        al_block.append(Paragraph('Nenhum alerta ativo — cluster saudavel',
                                  ParagraphStyle('', fontName=N, fontSize=7,
                                                textColor=C_OK, leading=10)))

    # Nodes resumo
    nd_block = [_sec_hdr('Nodes do Cluster', col2)]
    nd_block.append(Spacer(1, 3))
    nd_hd = ['Node', 'Status', 'CPU%', 'Mem%']
    nd_data = [nd_hd]
    for n in report.nodes:
        nd_data.append([
            Paragraph(n.name[:20], st['td_b']),
            _status_cell(n.status, st),
            _pct_cell(n.cpu_pct, n.cpu_usage, st),
            _pct_cell(n.mem_pct, n.mem_usage, st),
        ])
    nd_ws = [r*col2 for r in [0.46, 0.20, 0.17, 0.17]]
    nd_t = Table(nd_data, colWidths=nd_ws, repeatRows=1)
    nd_t.setStyle(_tbl_style())
    nd_block.append(nd_t)

    story.append(Table([[al_block, nd_block]], colWidths=[col2, col2],
                       style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                         ('LEFTPADDING',(0,0),(-1,-1),0),
                                         ('RIGHTPADDING',(0,0),(0,0),12),
                                         ('TOPPADDING',(0,0),(-1,-1),0),
                                         ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
    story.append(Spacer(1, 6))

    # ── 2 colunas: Top Namespaces | Status Pods ───────────────────────────────
    ns_sorted = sorted(report.namespaces, key=lambda n: n.pod_count, reverse=True)
    ns_active = [n for n in ns_sorted if n.pod_count > 0]
    NS_COLORS = ['#0D5C63','#117A65','#1A8A94','#2E86C1','#6C3483','#784212','#1B4332']

    ns_block = [_sec_hdr('Top Namespaces por Pods', col2)]
    ns_block.append(Spacer(1, 3))
    max_pods = ns_active[0].pod_count if ns_active else 1
    bar_w = col2 - 95
    for i, ns in enumerate(ns_active[:8]):
        c = colors.HexColor(NS_COLORS[i % len(NS_COLORS)])
        bw = max(2, (ns.pod_count / max_pods) * bar_w)
        row_d = Drawing(col2, 11)
        row_d.add(String(0, 2, ns.name[:18], fontSize=6.5, fontName=N,
                         fillColor=_hx(C_DARK)))
        row_d.add(Rect(75, 2, bar_w, 7, fillColor=C_BGL2, strokeColor=None, rx=2))
        row_d.add(Rect(75, 2, bw, 7, fillColor=c, strokeColor=None, rx=2))
        row_d.add(String(75 + bar_w + 5, 2, str(ns.pod_count),
                         fontSize=6.5, fontName=B, fillColor=_hx(C_DARK)))
        ns_block.append(row_d)

    # Status pods
    total = s['total_pods'] or 1
    succ = total - s['pods_running'] - s['pods_pending'] - s['pods_failed']
    pod_bars = [
        ('Running',   s['pods_running'],   '#1E8449'),
        ('Succeeded', max(0, succ),         '#1A5276'),
        ('Failed',    s['pods_failed'],    '#C0392B'),
        ('Pending',   s['pods_pending'],   '#D68910'),
    ]
    ps_block = [_sec_hdr('Status dos Pods', col2)]
    ps_block.append(Spacer(1, 3))
    bw2 = col2 - 70
    for lbl, val, hx in pod_bars:
        fw = max(0, (val/total)*bw2)
        row_d2 = Drawing(col2, 11)
        row_d2.add(String(0, 2, lbl, fontSize=6.5, fontName=N, fillColor=_hx(C_DARK)))
        row_d2.add(Rect(62, 2, bw2, 7, fillColor=C_BGL2, strokeColor=None, rx=2))
        if fw > 0:
            row_d2.add(Rect(62, 2, fw, 7, fillColor=colors.HexColor(hx),
                            strokeColor=None, rx=2))
        row_d2.add(String(62+bw2+5, 2, str(val), fontSize=6.5, fontName=B,
                          fillColor=_hx(C_DARK)))
        ps_block.append(row_d2)

    story.append(Table([[ns_block, ps_block]], colWidths=[col2, col2],
                       style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                         ('LEFTPADDING',(0,0),(-1,-1),0),
                                         ('RIGHTPADDING',(0,0),(0,0),12),
                                         ('TOPPADDING',(0,0),(-1,-1),0),
                                         ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
    story.append(Spacer(1, 6))

    # ── Pods com Atenção compacto (inline pág 1) — com coluna Último Restart ──
    SYS = {'kube-system','kube-node-lease','kube-public','cattle-system',
           'cattle-fleet-system','cattle-fleet-local-system','cattle-capi-system',
           'cattle-turtles-system','fleet-default','fleet-local','local-path-storage'}
    thr_app = s.get('restart_threshold_app', 5)
    thr_sys = s.get('restart_threshold_sys', 20)
    problem_pods = [p for p in report.pods if (
        p.status not in ('Running','Succeeded') or
        (p.namespace in SYS and p.restarts >= thr_sys) or
        (p.namespace not in SYS and p.restarts >= thr_app))]

    story.append(_sec_hdr(f'Pods com Atencao ({len(problem_pods)})'))
    story.append(Spacer(1, 3))
    if problem_pods:
        ph = ['Pod', 'Status', 'Restarts', 'Último Restart']
        pd_data = [ph]
        for p in problem_pods[:6]:
            last_r = getattr(p, 'last_restart_ago', 'N/A')
            pd_data.append([
                Paragraph(p.name[:38], st['td_b']),
                _status_cell(p.status, st),
                Paragraph(str(p.restarts), st['td_c']),
                Paragraph(last_r, st['td_g']),
            ])
        pw = [r*USE for r in [0.58, 0.18, 0.10, 0.14]]
        pt = Table(pd_data, colWidths=pw, repeatRows=1)
        pt.setStyle(_tbl_style())
        story.append(pt)
        story.append(Paragraph(
            f'* Threshold: app ≥{thr_app} restarts | system ≥{thr_sys} restarts',
            ParagraphStyle('', fontName=IT, fontSize=5.5, textColor=C_GRAY, leading=8)
        ))
    else:
        story.append(Paragraph('Nenhum pod com problemas.', st['td']))

    return story


# ════════════════════════════════════════════════════════════════════════════════
# PÁGINA 2 — WORKLOADS VISÃO GERAL + RECURSOS
# ════════════════════════════════════════════════════════════════════════════════
def _pg_resources(report, st):
    story = [PageBreak()]
    s = report.summary

    # ── Workloads — Visão Geral (3 colunas) ──────────────────────────────────
    story.append(_sec_hdr('Workloads — Visao Geral'))
    story.append(Spacer(1, 4))

    col3 = USE / 3 - 4

    dep_ok   = [d for d in report.deployments if d.ready == d.desired and d.desired > 0]
    dep_bad  = [d for d in report.deployments if d.ready != d.desired or d.desired == 0]
    dep_hd   = ['Deployment', 'NS', 'Status']
    dep_data = [dep_hd]
    for d in dep_bad[:4]:
        rc = _hx(C_CRIT) if d.ready == 0 else _hx(C_WARN)
        dep_data.append([
            Paragraph(d.name[:20], st['td_b']),
            Paragraph(d.namespace[:8], st['td_g']),
            Paragraph(f'<font color="{rc}"><b>{d.ready}/{d.desired}</b></font>', st['td_c']),
        ])
    dep_data.append([
        Paragraph(f'+ {len(dep_ok)} deployments OK',
                  ParagraphStyle('', fontName=IT, fontSize=6, textColor=C_GRAY, leading=8)),
        Paragraph('', st['td']), Paragraph('', st['td']),
    ])
    dep_ws = [r*col3 for r in [0.52, 0.26, 0.22]]
    dep_t = Table(dep_data, colWidths=dep_ws, repeatRows=1)
    dep_t.setStyle(_tbl_style())
    dep_block = [Paragraph(f'Deployments ({s["total_deployments"]} total)',
                           ParagraphStyle('', fontName=B, fontSize=7, textColor=C_P, leading=10)),
                 Spacer(1,2), dep_t]

    # PVCs — com destaque para Pending alert
    pvc_hd   = ['PVC', 'Cap.', 'Status']
    pvc_data = [pvc_hd]
    for p in report.pvcs[:7]:
        pvc_data.append([
            Paragraph(p.name[:18], st['td_b']),
            Paragraph(p.capacity,  st['td_c']),
            _status_cell(p.status, st),
        ])
    bound = sum(1 for p in report.pvcs if p.status.upper()=='BOUND')
    pend_alert = s.get('pvcs_pending_alert', 0)
    pvc_note = f'+ {bound} PVCs Bound'
    if pend_alert:
        pvc_note += f'  ⚠ {pend_alert} Pending'
    pvc_data.append([
        Paragraph(pvc_note, ParagraphStyle('', fontName=IT, fontSize=6, textColor=C_GRAY, leading=8)),
        Paragraph('', st['td']), Paragraph('', st['td']),
    ])
    pvc_ws = [r*col3 for r in [0.52, 0.22, 0.26]]
    pvc_t = Table(pvc_data, colWidths=pvc_ws, repeatRows=1)
    pvc_t.setStyle(_tbl_style())
    pvc_block = [Paragraph('Storage (PVCs)', ParagraphStyle('', fontName=B, fontSize=7,
                 textColor=C_P, leading=10)), Spacer(1,2), pvc_t]

    # Top CPU/Mem
    top_cpu = s.get('top_cpu_pods', [])
    top_mem = s.get('top_mem_pods', [])
    tm_hd   = ['Pod', 'CPU', 'Mem']
    tm_data = [tm_hd]
    for p in top_cpu[:5]:
        mem_v = next((x['mem'] for x in top_mem if x['name']==p['name']), 'N/A')
        tm_data.append([
            Paragraph(p['name'][:18], st['td_b']),
            Paragraph(p['cpu'], st['td_c']),
            Paragraph(mem_v,    st['td_c']),
        ])
    tm_ws = [r*col3 for r in [0.56, 0.22, 0.22]]
    tm_t = Table(tm_data, colWidths=tm_ws, repeatRows=1)
    tm_t.setStyle(_tbl_style())
    tm_block = [Paragraph('Top CPU / Mem', ParagraphStyle('', fontName=B, fontSize=7,
                textColor=C_P, leading=10)), Spacer(1,2), tm_t]

    story.append(Table([[dep_block, pvc_block, tm_block]],
                       colWidths=[col3, col3, col3],
                       style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                         ('LEFTPADDING',(0,0),(-1,-1),0),
                                         ('RIGHTPADDING',(0,0),(0,1),8),
                                         ('RIGHTPADDING',(0,0),(1,0),8),
                                         ('TOPPADDING',(0,0),(-1,-1),0),
                                         ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
    story.append(Spacer(1, 8))

    # ── Namespaces Detalhado ───────────────────────────────────────────────────
    ns_sorted = sorted(report.namespaces, key=lambda n: n.pod_count, reverse=True)
    ns_active = [n for n in ns_sorted if n.pod_count > 0]
    ns_empty  = [n for n in ns_sorted if n.pod_count == 0]

    story.append(_sec_hdr('Namespaces — Detalhado'))
    story.append(Spacer(1, 4))

    hd = ['Namespace','Status','Pods','Running','Pending','Failed','CPU (m)','Mem (MiB)','Idade']
    data = [hd]
    for ns in ns_active:
        data.append([
            Paragraph(ns.name, st['td_b']),
            _status_cell(ns.status, st),
            Paragraph(str(ns.pod_count),   st['td_c']),
            Paragraph(str(ns.running),     st['td_c']),
            Paragraph(str(ns.pending),     st['td_c']),
            Paragraph(str(ns.failed),      st['td_c']),
            Paragraph(str(ns.cpu_usage_m)  if ns.cpu_usage_m  else 'N/A', st['td_c']),
            Paragraph(str(ns.mem_usage_mib)if ns.mem_usage_mib else 'N/A', st['td_c']),
            Paragraph(ns.age, st['td_g']),
        ])
    if ns_empty:
        data.append([Paragraph(f'+ {len(ns_empty)} namespaces sem pods omitidos', st['note'])]
                    + [Paragraph('', st['td'])]*8)
    ws = [r*USE for r in [0.22, 0.09, 0.06, 0.08, 0.07, 0.07, 0.09, 0.10, 0.07]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    story.append(Spacer(1, 8))

    # ── Top Pods por Recurso ───────────────────────────────────────────────────
    story.append(_sec_hdr('Top Pods por Consumo de Recurso'))
    story.append(Spacer(1, 4))
    top_cpu = s.get('top_cpu_pods', [])
    top_mem = s.get('top_mem_pods', [])
    col2 = USE / 2 - 4

    cpu_hd = ['Pod', 'Namespace', 'CPU', 'm']
    cpu_data = [cpu_hd]
    for p in top_cpu:
        cpu_data.append([Paragraph(p['name'][:34], st['td']),
                         Paragraph(p['ns'], st['td_g']),
                         Paragraph(p['cpu'], st['td_c']),
                         Paragraph(str(p['cpu_m']), st['td_c'])])
    mem_hd = ['Pod', 'Namespace', 'Mem', 'MiB']
    mem_data = [mem_hd]
    for p in top_mem:
        mem_data.append([Paragraph(p['name'][:34], st['td']),
                         Paragraph(p['ns'], st['td_g']),
                         Paragraph(p['mem'], st['td_c']),
                         Paragraph(str(p['mem_mib']), st['td_c'])])

    ws2 = [r*col2 for r in [0.44, 0.24, 0.18, 0.14]]
    tc = Table(cpu_data, colWidths=ws2, repeatRows=1); tc.setStyle(_tbl_style())
    tm = Table(mem_data, colWidths=ws2, repeatRows=1); tm.setStyle(_tbl_style())

    story.append(Table([[
        [Paragraph('Top 10 — CPU', ParagraphStyle('', fontName=B, fontSize=7, textColor=C_P, leading=10)),
         Spacer(1,2), tc],
        [Paragraph('Top 10 — Memoria', ParagraphStyle('', fontName=B, fontSize=7, textColor=C_P, leading=10)),
         Spacer(1,2), tm],
    ]], colWidths=[col2, col2],
        style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                          ('LEFTPADDING',(0,0),(-1,-1),0),
                          ('RIGHTPADDING',(0,0),(0,0),8),
                          ('TOPPADDING',(0,0),(-1,-1),0),
                          ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
    return story


# ════════════════════════════════════════════════════════════════════════════════
# PÁGINA 3 — NODES DETALHADO
# ════════════════════════════════════════════════════════════════════════════════
def _pg_nodes(report, st):
    story = [PageBreak()]
    story.append(_sec_hdr('Nodes do Cluster — Detalhado'))
    story.append(Spacer(1, 4))
    hd = ['Node','Status','Roles','Versao','CPU Cap.','CPU Uso','CPU%',
          'Mem Cap.','Mem Uso','Mem%','Idade']
    data = [hd]
    for n in report.nodes:
        data.append([
            Paragraph(n.name, st['td_b']),
            _status_cell(n.status, st),
            Paragraph(n.roles[:12], st['td_g']),
            Paragraph(n.version,    st['td_g']),
            Paragraph(n.cpu_capacity, st['td_c']),
            Paragraph(n.cpu_usage,    st['td_c']),
            _pct_cell(n.cpu_pct, n.cpu_usage, st),
            Paragraph(n.mem_capacity, st['td_c']),
            Paragraph(n.mem_usage,    st['td_c']),
            _pct_cell(n.mem_pct, n.mem_usage, st),
            Paragraph(n.age, st['td_g']),
        ])
    ws = [r*USE for r in [0.18,0.08,0.09,0.09,0.07,0.07,0.06,0.09,0.08,0.06,0.06]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    return story


# ════════════════════════════════════════════════════════════════════════════════
# PÁGINA 4 — WORKLOADS DETALHADO
# ════════════════════════════════════════════════════════════════════════════════
def _pg_workloads(report, st):
    story = [PageBreak()]
    col2 = USE / 2 - 4

    story.append(_sec_hdr('Deployments'))
    story.append(Spacer(1, 4))
    hd = ['Deployment','Namespace','Desejado','Pronto','Disponivel','Atualizado','Idade']
    data = [hd]
    for d in report.deployments:
        ok = d.ready == d.desired and d.desired > 0
        rc = _hx(C_OK) if ok else _hx(C_CRIT if d.ready==0 and d.desired>0 else C_WARN)
        data.append([
            Paragraph(d.name, st['td_b']),
            Paragraph(d.namespace, st['td_g']),
            Paragraph(str(d.desired),   st['td_c']),
            Paragraph(f'<font color="{rc}"><b>{d.ready}</b></font>', st['td_c']),
            Paragraph(str(d.available), st['td_c']),
            Paragraph(str(d.up_to_date),st['td_c']),
            Paragraph(d.age, st['td_g']),
        ])
    ws = [r*USE for r in [0.30, 0.22, 0.10, 0.10, 0.10, 0.10, 0.08]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    story.append(Spacer(1, 8))

    left, right = [], []
    if report.statefulsets:
        left.append(_sec_hdr('StatefulSets', col2))
        left.append(Spacer(1, 3))
        hd2 = ['StatefulSet','Namespace','Desejado','Pronto','Idade']
        d2 = [hd2]
        for s2 in report.statefulsets:
            rc = _hx(C_OK) if s2.ready==s2.desired else _hx(C_CRIT)
            d2.append([Paragraph(s2.name, st['td_b']),Paragraph(s2.namespace, st['td_g']),
                       Paragraph(str(s2.desired), st['td_c']),
                       Paragraph(f'<font color="{rc}"><b>{s2.ready}</b></font>', st['td_c']),
                       Paragraph(s2.age, st['td_g'])])
        ws2 = [r*col2 for r in [0.36,0.28,0.13,0.13,0.10]]
        t2 = Table(d2, colWidths=ws2, repeatRows=1); t2.setStyle(_tbl_style())
        left.append(t2)

    if report.daemonsets:
        right.append(_sec_hdr('DaemonSets', col2))
        right.append(Spacer(1, 3))
        hd3 = ['DaemonSet','Namespace','Desejado','Pronto','Idade']
        d3 = [hd3]
        for ds in report.daemonsets:
            rc = _hx(C_OK) if ds.ready==ds.desired else _hx(C_WARN)
            d3.append([Paragraph(ds.name, st['td_b']),Paragraph(ds.namespace, st['td_g']),
                       Paragraph(str(ds.desired), st['td_c']),
                       Paragraph(f'<font color="{rc}"><b>{ds.ready}</b></font>', st['td_c']),
                       Paragraph(ds.age, st['td_g'])])
        ws3 = [r*col2 for r in [0.36,0.28,0.12,0.12,0.12]]
        t3 = Table(d3, colWidths=ws3, repeatRows=1); t3.setStyle(_tbl_style())
        right.append(t3)

    if left or right:
        story.append(Table([[left or [Spacer(1,1)], right or [Spacer(1,1)]]],
                           colWidths=[col2, col2],
                           style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                             ('LEFTPADDING',(0,0),(-1,-1),0),
                                             ('RIGHTPADDING',(0,0),(0,0),8),
                                             ('TOPPADDING',(0,0),(-1,-1),0),
                                             ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
        story.append(Spacer(1, 8))

    cj_s, job_s = [], []
    if report.cronjobs:
        cj_s.append(_sec_hdr('CronJobs', col2))
        cj_s.append(Spacer(1, 3))
        hc = ['CronJob','Namespace','Schedule','Ultimo','Idade']
        dc = [hc]
        for cj in report.cronjobs:
            dc.append([Paragraph(cj.name[:24], st['td_b']),
                       Paragraph(cj.namespace[:14], st['td_g']),
                       Paragraph(cj.schedule, st['td_g']),
                       Paragraph(cj.last_schedule, st['td_g']),
                       Paragraph(cj.age, st['td_g'])])
        wc = [r*col2 for r in [0.36,0.20,0.22,0.14,0.08]]
        tc2 = Table(dc, colWidths=wc, repeatRows=1); tc2.setStyle(_tbl_style())
        cj_s.append(tc2)

    if report.jobs:
        job_s.append(_sec_hdr('Jobs', col2))
        job_s.append(Spacer(1, 3))
        hj = ['Job','Namespace','Status','Duracao','Idade']
        dj = [hj]
        for j in report.jobs:
            if j.namespace == 'status-report': continue
            dj.append([Paragraph(j.name[:26], st['td_b']),
                       Paragraph(j.namespace[:16], st['td_g']),
                       _status_cell(j.status, st),
                       Paragraph(j.duration, st['td_g']),
                       Paragraph(j.age, st['td_g'])])
        wj = [r*col2 for r in [0.36,0.22,0.16,0.16,0.10]]
        tj = Table(dj, colWidths=wj, repeatRows=1); tj.setStyle(_tbl_style())
        job_s.append(tj)

    if cj_s or job_s:
        story.append(Table([[cj_s or [Spacer(1,1)], job_s or [Spacer(1,1)]]],
                           colWidths=[col2, col2],
                           style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                             ('LEFTPADDING',(0,0),(-1,-1),0),
                                             ('RIGHTPADDING',(0,0),(0,0),8),
                                             ('TOPPADDING',(0,0),(-1,-1),0),
                                             ('BOTTOMPADDING',(0,0),(-1,-1),0)])))
    return story


# ════════════════════════════════════════════════════════════════════════════════
# PÁGINA 5 — PODS — com coluna Último Restart
# ════════════════════════════════════════════════════════════════════════════════
def _pg_pods(report, st):
    story = [PageBreak()]
    s = report.summary
    thr_app = s.get('restart_threshold_app', 5)
    thr_sys = s.get('restart_threshold_sys', 20)
    SYS = {'kube-system','kube-node-lease','kube-public','cattle-system',
           'cattle-fleet-system','cattle-fleet-local-system','cattle-capi-system',
           'cattle-turtles-system','fleet-default','fleet-local','local-path-storage'}
    problem = [p for p in report.pods if (
        p.status not in ('Running','Succeeded') or
        (p.namespace in SYS     and p.restarts >= thr_sys) or
        (p.namespace not in SYS and p.restarts >= thr_app))]
    normal = [p for p in report.pods if p not in problem]

    story.append(_sec_hdr(f'Pods — Atencao ({len(problem)})'))
    story.append(Spacer(1, 4))
    hd = ['Pod','Namespace','Status','Ready','Restarts','Últ.Restart','CPU','Mem','Node','Idade']
    data = [hd]
    for p in problem:
        last_r = getattr(p, 'last_restart_ago', 'N/A')
        data.append([Paragraph(p.name[:24], st['td_b']),
                     Paragraph(p.namespace[:10], st['td_g']),
                     _status_cell(p.status, st),
                     Paragraph(p.ready, st['td_c']),
                     Paragraph(str(p.restarts), st['td_c']),
                     Paragraph(last_r, st['td_g']),
                     Paragraph(p.cpu_usage, st['td_c']),
                     Paragraph(p.mem_usage, st['td_c']),
                     Paragraph(p.node[:12] if p.node else '?', st['td_g']),
                     Paragraph(p.age, st['td_g'])])
    ws = [r*USE for r in [0.18,0.10,0.13,0.05,0.07,0.09,0.06,0.07,0.12,0.05]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    story.append(Paragraph(
        f'* Threshold: app ≥{thr_app} restarts | system ≥{thr_sys} restarts  '
        f'(configurável via RESTART_THRESHOLD_APP / RESTART_THRESHOLD_SYS)',
        ParagraphStyle('', fontName=IT, fontSize=5.5, textColor=C_GRAY, leading=8)
    ))
    story.append(Spacer(1, 8))

    story.append(_sec_hdr(f'Pods — Saudaveis ({min(50,len(normal))} de {len(normal)})'))
    story.append(Spacer(1, 4))
    hd2 = ['Pod','Namespace','Status','Ready','Restarts','CPU','Mem','Idade']
    data2 = [hd2]
    for p in normal[:50]:
        data2.append([Paragraph(p.name[:34], st['td_b']),
                      Paragraph(p.namespace, st['td_g']),
                      _status_cell(p.status, st),
                      Paragraph(p.ready, st['td_c']),
                      Paragraph(str(p.restarts), st['td_c']),
                      Paragraph(p.cpu_usage, st['td_c']),
                      Paragraph(p.mem_usage, st['td_c']),
                      Paragraph(p.age, st['td_g'])])
    ws2 = [r*USE for r in [0.27,0.15,0.10,0.07,0.07,0.08,0.08,0.08]]
    t2 = Table(data2, colWidths=ws2, repeatRows=1)
    t2.setStyle(_tbl_style())
    story.append(t2)
    return story


# ════════════════════════════════════════════════════════════════════════════════
# PÁGINA 6 — REDE + STORAGE
# ════════════════════════════════════════════════════════════════════════════════
def _pg_net_stor(report, st):
    story = [PageBreak()]

    story.append(_sec_hdr('PersistentVolumeClaims'))
    story.append(Spacer(1, 4))
    hd = ['PVC','Namespace','Status','Volume','Cap.','StorageClass','Modo','Idade']
    data = [hd]
    for p in report.pvcs:
        # Destaca Pending prolongado
        age_days = getattr(p, 'age_days', 0)
        from collector import PVC_PENDING_ALERT_DAYS
        is_pend_alert = p.status == 'Pending' and age_days >= PVC_PENDING_ALERT_DAYS
        name_para = (
            Paragraph(f'<font color="{_hx(C_CRIT)}"><b>{p.name[:22]}</b></font>', st['td_b'])
            if is_pend_alert else Paragraph(p.name[:22], st['td_b'])
        )
        data.append([name_para,
                     Paragraph(p.namespace, st['td_g']),
                     _status_cell(p.status, st),
                     Paragraph(p.volume[:16], st['td_g']),
                     Paragraph(p.capacity, st['td_c']),
                     Paragraph(p.storage_class[:12], st['td_g']),
                     Paragraph(p.access_modes[:12], st['td_g']),
                     Paragraph(p.age, st['td_g'])])
    ws = [r*USE for r in [0.20,0.13,0.09,0.18,0.08,0.13,0.12,0.07]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    story.append(Spacer(1, 8))

    left, right = [], []
    if report.ingresses:
        left.append(_sec_hdr('Ingresses', USE))
        left.append(Spacer(1, 3))
        hi = ['Ingress','Namespace','Hosts','Ports','Idade']
        di = [hi]
        for i in report.ingresses:
            di.append([Paragraph(i.name[:20], st['td_b']),
                       Paragraph(i.namespace[:12], st['td_g']),
                       Paragraph(i.hosts[:38], st['td_g']),
                       Paragraph(i.ports[:16], st['td_c']),
                       Paragraph(i.age, st['td_g'])])
        wi = [r*USE for r in [0.16,0.13,0.48,0.14,0.09]]
        ti = Table(di, colWidths=wi, repeatRows=1); ti.setStyle(_tbl_style())
        left.append(ti)
        left.append(Spacer(1, 8))

    if report.services:
        left.append(_sec_hdr('Services Expostos', USE))
        left.append(Spacer(1, 3))
        hs2 = ['Service','Namespace','Tipo','External IP','Ports','Idade']
        ds = [hs2]
        for sv in report.services:
            ds.append([Paragraph(sv.name[:20], st['td_b']),
                       Paragraph(sv.namespace[:8], st['td_g']),
                       Paragraph(sv.type, st['td_g']),
                       Paragraph(sv.external_ip[:12], st['td_g']),
                       Paragraph(sv.ports[:24], st['td_g']),
                       Paragraph(sv.age, st['td_g'])])
        ws2 = [r*USE for r in [0.16,0.11,0.12,0.14,0.37,0.10]]
        ts = Table(ds, colWidths=ws2, repeatRows=1); ts.setStyle(_tbl_style())
        left.append(ts)
        left.append(Spacer(1, 8))

    for item in left:
        story.append(item)

    if report.hpas:
        story.append(_sec_hdr('Horizontal Pod Autoscalers'))
        story.append(Spacer(1, 4))
        hh = ['HPA','Namespace','Target','Min','Max','Atual','CPU Target','CPU Atual','Idade']
        dh = [hh]
        for h in report.hpas:
            rc = _hx(C_WARN) if h.current_replicas >= h.max_replicas else _hx(C_OK)
            dh.append([Paragraph(h.name[:18], st['td_b']),
                       Paragraph(h.namespace[:12], st['td_g']),
                       Paragraph(h.target[:20], st['td_g']),
                       Paragraph(str(h.min_replicas), st['td_c']),
                       Paragraph(str(h.max_replicas), st['td_c']),
                       Paragraph(f'<font color="{rc}"><b>{h.current_replicas}</b></font>', st['td_c']),
                       Paragraph(h.cpu_target_pct, st['td_c']),
                       Paragraph(h.cpu_current_pct, st['td_c']),
                       Paragraph(h.age, st['td_g'])])
        wh = [r*USE for r in [0.14,0.12,0.20,0.06,0.06,0.07,0.12,0.12,0.08]]
        th = Table(dh, colWidths=wh, repeatRows=1); th.setStyle(_tbl_style())
        story.append(th)
    return story


# ════════════════════════════════════════════════════════════════════════════════
# PÁGINA 7 — EVENTS
# ════════════════════════════════════════════════════════════════════════════════
def _pg_events(report, st):
    story = [PageBreak()]
    story.append(_sec_hdr(f'Warning Events ({len(report.events)} eventos)'))
    story.append(Spacer(1, 4))
    if not report.events:
        story.append(Paragraph('Nenhum Warning Event encontrado.', st['td']))
        return story
    hd = ['Namespace','Razao','Objeto','Mensagem','Count','Ha']
    data = [hd]
    for e in report.events[:60]:
        data.append([Paragraph(e.namespace[:14], st['td_g']),
                     Paragraph(e.reason[:14], st['td_b']),
                     Paragraph(e.object[:28], st['td_g']),
                     Paragraph(e.message[:75], st['td_g']),
                     Paragraph(str(e.count), st['td_c']),
                     Paragraph(e.last_seen, st['td_g'])])
    ws = [r*USE for r in [0.12,0.12,0.22,0.42,0.06,0.06]]
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(_tbl_style())
    story.append(t)
    return story


# ════════════════════════════════════════════════════════════════════════════════
# RODAPÉ com link do repo
# ════════════════════════════════════════════════════════════════════════════════
class _Doc(SimpleDocTemplate):
    def __init__(self, fn, report, **kw):
        self.report = report
        super().__init__(fn, **kw)

    def afterPage(self):
        c = self.canv
        r = self.report
        c.saveState()
        c.setFillColor(C_P)
        c.rect(0, 0, W, 8*mm, fill=1, stroke=0)
        c.setFillColor(C_A)
        c.rect(0, 8*mm-1, W, 1, fill=1, stroke=0)
        fn = B if _FONTS_OK else 'Helvetica-Bold'
        c.setFont(fn, 6)
        c.setFillColor(C_WHITE)
        c.drawString(MAR, 3*mm,
            f'OpenLabs  |  K8s Status Report  |  {r.cluster_name}  |  {r.collected_at}  |  Confidencial')
        c.drawRightString(W-MAR, 3*mm,
            f'github.com/drmsantos/status-report  |  Pagina {c.getPageNumber()}')
        c.restoreState()


# ════════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════════
def generate_pdf(report, output_path, delta=None):
    st = _st()
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
               topMargin=MAR, bottomMargin=11*mm)
    doc.build(story)
    logger.info(f'PDF gerado: {output_path}')
    return output_path
