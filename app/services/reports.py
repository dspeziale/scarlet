"""Professional PDF report generation (reportlab) — per-tenant security report
with a branded cover, KPI dashboard, sectioned tables, billing summary, and
page numbering. The brand name is configurable."""

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle, NextPageTemplate, PageBreak
)

SCARLET = colors.HexColor("#ff2a5f")
SCARLET_DARK = colors.HexColor("#d11f49")
INK = colors.HexColor("#10131c")
GREY = colors.HexColor("#6b7280")


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(name='Cover', fontName='Helvetica-Bold', fontSize=34,
                         textColor=colors.white, leading=38))
    s.add(ParagraphStyle(name='CoverSub', fontName='Helvetica', fontSize=12,
                         textColor=colors.white, leading=18))
    s.add(ParagraphStyle(name='H2', fontName='Helvetica-Bold', fontSize=14,
                         textColor=INK, spaceBefore=16, spaceAfter=8))
    s.add(ParagraphStyle(name='Body', fontName='Helvetica', fontSize=9.5, textColor=colors.HexColor("#333"), leading=14))
    s.add(ParagraphStyle(name='Small', fontName='Helvetica', fontSize=8, textColor=GREY))
    s.add(ParagraphStyle(name='KpiNum', fontName='Helvetica-Bold', fontSize=20, textColor=SCARLET, alignment=TA_CENTER))
    s.add(ParagraphStyle(name='KpiLbl', fontName='Helvetica', fontSize=7.5, textColor=GREY, alignment=TA_CENTER))
    return s


def _kpi_grid(styles, items):
    """items: list of (value, label). Renders a row of KPI cells."""
    cells = [[Paragraph(str(v), styles['KpiNum'])] for v, _ in items]
    labels = [[Paragraph(l, styles['KpiLbl'])] for _, l in items]
    data = [[Paragraph(str(v), styles['KpiNum']) for v, _ in items],
            [Paragraph(l, styles['KpiLbl']) for _, l in items]]
    w = (170 * mm) / len(items)
    t = Table(data, colWidths=[w] * len(items))
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f6f7f9")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.white),
        ('TOPPADDING', (0, 0), (-1, 0), 10), ('BOTTOMPADDING', (0, 1), (-1, 1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def _table(header, rows, widths):
    data = [header] + (rows or [["—"] * len(header)])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), INK),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 8.5),
        ('FONT', (0, 1), (-1, -1), 'Helvetica', 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f7f9")]),
        ('LINEBELOW', (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def build_tenant_report(tenant, probes, devices, alerts, billing=None, brand="SCARLET"):
    """Returns professional PDF bytes for a tenant security report."""
    buf = io.BytesIO()
    gen = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    def _cover_bg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.setFillColor(SCARLET)
        canvas.rect(0, A4[1] - 80 * mm, A4[0], 6, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica-Bold', 9)
        canvas.drawString(20 * mm, 18 * mm, f"{brand} Command Center")
        canvas.setFillColor(GREY)
        canvas.drawRightString(A4[0] - 20 * mm, 18 * mm, "Confidential")
        canvas.restoreState()

    def _page_bg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.rect(0, A4[1] - 14 * mm, A4[0], 14 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica-Bold', 9)
        canvas.drawString(20 * mm, A4[1] - 9.5 * mm, f"{brand}  ·  Security Report")
        canvas.setFillColor(SCARLET)
        canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 9.5 * mm, tenant.name)
        canvas.setFillColor(GREY)
        canvas.setFont('Helvetica', 7.5)
        canvas.drawString(20 * mm, 10 * mm, f"Generated {gen}")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Page {doc.page}")
        canvas.setStrokeColor(colors.HexColor("#e5e7eb"))
        canvas.line(20 * mm, 13 * mm, A4[0] - 20 * mm, 13 * mm)
        canvas.restoreState()

    doc = BaseDocTemplate(buf, pagesize=A4, title=f"{brand} Report - {tenant.name}", author=brand)
    cover_frame = Frame(0, 0, A4[0], A4[1], id='cover')
    body_frame = Frame(20 * mm, 16 * mm, A4[0] - 40 * mm, A4[1] - 16 * mm - 18 * mm, id='body')
    doc.addPageTemplates([
        PageTemplate(id='Cover', frames=[cover_frame], onPage=_cover_bg),
        PageTemplate(id='Body', frames=[body_frame], onPage=_page_bg),
    ])

    s = _styles()
    story = []

    # ---- Cover ----
    story.append(Spacer(1, 90 * mm))
    story.append(Table([[Paragraph("SECURITY REPORT", s['Cover'])]], colWidths=[A4[0]],
                       style=TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 20 * mm), ('TOPPADDING', (0, 0), (-1, -1), 0)])))
    story.append(Table([[Paragraph(f"Tenant: <b>{tenant.name}</b>", s['CoverSub'])],
                        [Paragraph(f"Generated {gen}", s['CoverSub'])]],
                       colWidths=[A4[0]],
                       style=TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 20 * mm), ('TOPPADDING', (0, 0), (-1, -1), 4)])))
    story.append(NextPageTemplate('Body'))
    story.append(PageBreak())

    # ---- Executive summary ----
    vuln = sum(1 for d in devices if d.vulnerabilities)
    services = sum(len(d.services) for d in devices if hasattr(d, 'services'))
    online = sum(1 for p in probes if p.status in ('paired', 'scanning'))
    story.append(Paragraph("Executive Summary", s['H2']))
    story.append(_kpi_grid(s, [
        (len(probes), "PROBES"), (online, "ACTIVE"), (len(devices), "ASSETS"),
        (services, "SERVICES"), (vuln, "VULNERABLE"), (len(alerts), "IDS ALERTS"),
    ]))
    story.append(Spacer(1, 4))

    # ---- Probes ----
    story.append(Paragraph("Probe Fleet", s['H2']))
    prows = [[p.probe_name or 'Unnamed', p.status,
              (p.last_seen.strftime('%Y-%m-%d %H:%M') if p.last_seen else 'Never')] for p in probes[:30]]
    story.append(_table(["Probe", "Status", "Last Seen"], prows, [70 * mm, 40 * mm, 60 * mm]))

    # ---- Assets ----
    story.append(Paragraph("Network Assets", s['H2']))
    drows = [[d.ip_address or '—', (d.os_info or 'Unknown')[:34],
              'Yes' if d.vulnerabilities else 'No'] for d in devices[:45]]
    story.append(_table(["IP Address", "Operating System", "Vulnerable"], drows, [45 * mm, 95 * mm, 30 * mm]))

    # ---- Alerts ----
    if alerts:
        story.append(Paragraph("Recent IDS Alerts", s['H2']))
        arows = [[(a.received_at.strftime('%m-%d %H:%M') if a.received_at else '—'),
                  (a.signature or a.line or '—')[:64], a.src_ip or '—'] for a in alerts[:25]]
        story.append(_table(["Time", "Signature", "Source"], arows, [28 * mm, 102 * mm, 40 * mm]))

    # ---- Billing ----
    if billing:
        story.append(Paragraph("Billing Summary", s['H2']))
        brows = [[item['label'], item['detail'], item['amount']] for item in billing['lines']]
        brows.append(["TOTAL", "", billing['total']])
        bt = _table(["Item", "Detail", "Amount"], brows, [55 * mm, 75 * mm, 40 * mm])
        bt.setStyle(TableStyle([('FONT', (0, -1), (-1, -1), 'Helvetica-Bold', 9),
                                ('TEXTCOLOR', (-1, -1), (-1, -1), SCARLET_DARK),
                                ('LINEABOVE', (0, -1), (-1, -1), 0.8, INK)]))
        story.append(bt)

    story.append(Spacer(1, 12))
    story.append(Paragraph(f"© {datetime.now().year} {brand} — Confidential. Generated automatically.", s['Small']))

    doc.build(story)
    buf.seek(0)
    return buf.read()
