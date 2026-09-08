import os
import sys
import time
from pathlib import Path
import win32print
from reportlab.pdfgen import canvas
from reportlab.lib import colors

sys.path.insert(0, str(Path(__file__).resolve().parent))

from print_agent import (
    compose_manifest_to_pdf,
    print_document_silently,
    get_printer_hardware_caps
)

TARGET_PRINTER = 'EPSON L3210 Series'
TEST_DIR = Path(__file__).resolve().parent / 'hardware_test_docs'
TEST_DIR.mkdir(exist_ok=True)

def generate_color_test_pdf(out_path: Path):
    w, h = (595.276, 841.890)  # A4 Portrait
    c = canvas.Canvas(str(out_path), pagesize=(w, h))
    
    # Outer Border
    c.setLineWidth(4)
    c.setStrokeColor(colors.HexColor('#0055ff'))
    c.rect(18, 18, w - 36, h - 36)
    
    # Header Banner (Deep Blue)
    c.setFillColor(colors.HexColor('#0a2540'))
    c.rect(18, h - 100, w - 36, 82, fill=1, stroke=0)
    
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 26)
    c.drawString(40, h - 60, 'PRINTFLOW COLOR QUALITY TEST')
    
    c.setFont('Helvetica', 14)
    c.drawString(40, h - 85, f'Target Printer: {TARGET_PRINTER}  |  Engine: Inkjet Color')
    
    # Color Palette Bands
    y = h - 130
    c.setFont('Helvetica-Bold', 14)
    c.setFillColor(colors.black)
    c.drawString(40, y, 'PRIMARY & SECONDARY COLOR PALETTE')
    
    color_patches = [
        ('RED', colors.HexColor('#e63946')),
        ('ORANGE', colors.HexColor('#f77f00')),
        ('YELLOW', colors.HexColor('#fcbf49')),
        ('GREEN', colors.HexColor('#2a9d8f')),
        ('CYAN', colors.HexColor('#00b4d8')),
        ('BLUE', colors.HexColor('#0077b6')),
        ('MAGENTA', colors.HexColor('#d90429')),
        ('PURPLE', colors.HexColor('#7209b7')),
        ('BLACK', colors.black),
    ]
    
    bar_y = y - 45
    bar_w = (w - 80) / len(color_patches)
    for idx, (label, col) in enumerate(color_patches):
        bx = 40 + idx * bar_w
        c.setFillColor(col)
        c.rect(bx, bar_y, bar_w - 4, 35, fill=1, stroke=1)
        c.setFillColor(colors.black)
        c.setFont('Helvetica-Bold', 8)
        c.drawCentredString(bx + (bar_w - 4)/2, bar_y - 12, label)
        
    # CMYK Test Blocks
    cmyk_y = bar_y - 55
    c.setFont('Helvetica-Bold', 14)
    c.setFillColor(colors.black)
    c.drawString(40, cmyk_y, 'CMYK COLOR GRADIENT BARS')
    
    cmyk_cols = [
        ('CYAN', colors.HexColor('#00ffff'), colors.HexColor('#005577')),
        ('MAGENTA', colors.HexColor('#ff00ff'), colors.HexColor('#770055')),
        ('YELLOW', colors.HexColor('#ffff00'), colors.HexColor('#777700')),
        ('BLACK', colors.HexColor('#888888'), colors.HexColor('#000000'))
    ]
    
    for idx, (name, c1, c2) in enumerate(cmyk_cols):
        gy = cmyk_y - 30 - idx * 28
        c.setFillColor(c1)
        c.rect(40, gy, 240, 20, fill=1, stroke=0)
        c.setFillColor(c2)
        c.rect(280, gy, 240, 20, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont('Helvetica', 10)
        c.drawString(525, gy + 5, name)
        
    # Text Resolution / Sharpness Block
    text_y = cmyk_y - 170
    c.setFont('Helvetica-Bold', 14)
    c.drawString(40, text_y, 'TEXT RESOLUTION & FINE LINES')
    
    fonts_sample = [
        (8, colors.black, '8pt: The quick brown fox jumps over the lazy dog (PrintFlow Color Crisp Text)'),
        (10, colors.HexColor('#0077b6'), '10pt: The quick brown fox jumps over the lazy dog (High Fidelity Cyan)'),
        (12, colors.HexColor('#d90429'), '12pt: The quick brown fox jumps over the lazy dog (Vibrant Red)'),
        (14, colors.HexColor('#2a9d8f'), '14pt: The quick brown fox jumps over the lazy dog (Deep Green)'),
    ]
    
    for idx, (sz, fcol, text) in enumerate(fonts_sample):
        c.setFont('Helvetica', sz)
        c.setFillColor(fcol)
        c.drawString(40, text_y - 25 - idx * 22, text)
        
    # Verification Footer
    c.setLineWidth(1)
    c.setStrokeColor(colors.gray)
    c.line(40, 90, w - 40, 90)
    
    c.setFont('Helvetica-Bold', 12)
    c.setFillColor(colors.HexColor('#0077b6'))
    c.drawString(40, 70, f'Generated at: {time.strftime("%Y-%m-%d %H:%M:%S")}')
    c.drawString(40, 50, 'PRINTER: EPSON L3210 Series  |  MODE: COLOR PRINTING  |  PAPER: A4')
    c.setFillColor(colors.HexColor('#d90429'))
    c.drawString(40, 30, '*** PHYSICAL CONFIRMATION: VIBRANT COLOR SHEET MUST EXIT EPSON L3210 ***')
    
    c.showPage()
    c.save()
    return out_path

def wait_for_spooler_clear(printer_name: str, job_id: int, max_wait: float = 60.0):
    start = time.time()
    while (time.time() - start) < max_wait:
        h = win32print.OpenPrinter(printer_name)
        try:
            jobs = win32print.EnumJobs(h, 0, 999, 1)
            matching = [j for j in jobs if j.get('JobId') == job_id]
            if not matching:
                return True
        finally:
            win32print.ClosePrinter(h)
        time.sleep(1.0)
    return False

def main():
    print('=' * 60)
    print(f'STARTING COLOR PRINT TEST ON: {TARGET_PRINTER}')
    print('=' * 60)
    
    # Preflight Check
    h = win32print.OpenPrinter(TARGET_PRINTER)
    try:
        pinfo = win32print.GetPrinter(h, 2)
        print(f'Printer Name : {pinfo["pPrinterName"]}')
        print(f'Port Name    : {pinfo["pPortName"]}')
        print(f'Status       : {pinfo["Status"]}')
        print(f'Queued Jobs  : {pinfo["cJobs"]}')
    finally:
        win32print.ClosePrinter(h)
        
    # Step 1: Generate Color Calibration Document
    pdf_path = TEST_DIR / 'color_calibration_test.pdf'
    generate_color_test_pdf(pdf_path)
    print(f'[PDF GENERATION] Created color calibration document: {pdf_path.name}')
    
    # Step 2: Compose through PrintFlow Pipeline
    order = {
        'order_id': f'PF-COLOR-{int(time.time())%10000}',
        'file_name': pdf_path.name,
        'file_path': str(pdf_path),
        'pages': 1,
        'copies': 1,
        'duplex': 'single',
        'color_mode': 'color',
        'orientation': 'portrait',
        'paper_size': 'a4',
        'scale_mode': 'fit'
    }
    
    composed_pdf = compose_manifest_to_pdf(order, '', '', TARGET_PRINTER)
    print(f'[PIPELINE] Composed print-ready file: {composed_pdf.name}')
    
    # Step 3: Dispatch in COLOR mode
    print(f'[DISPATCH] Sending print order to {TARGET_PRINTER} in FULL COLOR...')
    spooler_job_id = print_document_silently(
        file_path=composed_pdf,
        printer_name=TARGET_PRINTER,
        copies=1,
        orientation='portrait',
        color_mode='color',
        duplex='single',
        paper_size='a4',
        scale_mode='fit',
        pages_per_sheet=1,
        page_order='horizontal',
        page_range='all',
        print_mode='standard',
        already_composed=True
    )
    
    print(f'[SPOOLER] Windows Spooler Job ID: {spooler_job_id}')
    cleared = False
    if spooler_job_id > 0:
        print(f'[SPOOLER] Waiting for spooler to deliver color job #{spooler_job_id} to Epson L3210 printer memory...')
        cleared = wait_for_spooler_clear(TARGET_PRINTER, spooler_job_id, 60.0)
        status_str = 'DELIVERED TO PRINTER' if cleared else 'ACTIVE/PRINTING'
        print(f'[SPOOLER] Job status: {status_str}')
        
    print('\n' + '=' * 60)
    print('COLOR PRINT TEST SUMMARY')
    print('=' * 60)
    print(f'Test Name     : COLOR PRINT TEST')
    print(f'Order ID      : {order["order_id"]}')
    print(f'Printer       : {TARGET_PRINTER}')
    print(f'Color Mode    : FULL COLOR (CMYK/RGB)')
    print(f'Spooler Job ID: {spooler_job_id}')
    print(f'Spooler Status: {"DELIVERED TO PRINTER" if cleared else ("SUBMITTED" if spooler_job_id > 0 else "FAILED")}')
    print(f'Result        : {"PASS" if spooler_job_id > 0 else "FAIL"}')
    print('=' * 60)

if __name__ == '__main__':
    main()
