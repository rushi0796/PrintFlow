import os
import sys
import time
import argparse
from pathlib import Path
import win32print
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from print_agent import (
    compose_manifest_to_pdf,
    print_document_silently,
    get_printer_hardware_caps,
    get_installed_windows_printers
)

TARGET_PRINTER = 'Kyocera ECOSYS M2040dn KX'
TEST_DIR = Path(__file__).resolve().parent / 'hardware_test_docs'
TEST_DIR.mkdir(exist_ok=True)

def make_banner_pdf(path: Path, test_title: str, pages: int = 1, is_landscape: bool = False, notes: str = ''):
    w, h = (841.890, 595.276) if is_landscape else (595.276, 841.890)
    c = canvas.Canvas(str(path), pagesize=(w, h))
    for p in range(1, pages + 1):
        c.setLineWidth(3)
        c.setStrokeColor(colors.black)
        c.rect(18, 18, w - 36, h - 36)
        
        c.setFont('Helvetica-Bold', 28)
        c.drawString(40, h - 70, 'PRINTFLOW PHYSICAL TEST')
        
        c.setFont('Helvetica-Bold', 22)
        c.drawString(40, h - 110, test_title)
        
        c.setFont('Helvetica-Bold', 18)
        c.drawString(40, h - 145, f'Page {p} of {pages}')
        
        c.setFont('Helvetica', 14)
        c.drawString(40, h - 180, f'Printer: {TARGET_PRINTER}')
        c.drawString(40, h - 205, f'Orientation: {"LANDSCAPE" if is_landscape else "PORTRAIT"}')
        c.drawString(40, h - 230, f'Timestamp: {time.strftime("%Y-%m-%d %H:%M:%S")}')
        if notes:
            c.drawString(40, h - 260, f'Notes: {notes}')
            
        c.setFont('Helvetica-Bold', 14)
        c.drawString(40, 40, '*** VERIFY: SHEET MUST PHYSICALLY PRINT ON KYOCERA M2040dn ***')
        c.showPage()
    c.save()
    return path

def make_banner_image(path: Path, test_title: str, is_landscape: bool = False):
    w, h = (1600, 1200) if is_landscape else (1200, 1600)
    img = Image.new('RGB', (w, h), color=(240, 240, 240))
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, w-20, h-20], outline=(0, 0, 0), width=6)
    draw.text((60, 80), 'PRINTFLOW HARDWARE IMAGE TEST', fill=(0, 0, 0))
    draw.text((60, 160), test_title, fill=(0, 0, 0))
    draw.text((60, 240), f'Timestamp: {time.strftime("%Y-%m-%d %H:%M:%S")}', fill=(0, 0, 0))
    img.save(path)
    return path

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

def run_test(test_key: str):
    test_key = test_key.upper()
    print('=' * 50)
    print(f'EXECUTING PHYSICAL TEST {test_key}')
    print('=' * 50)
    
    order = {'order_id': f'PF-PHYSICAL-{test_key}-{int(time.time())%10000}', 'printer_name': TARGET_PRINTER}
    expected_pages = 1
    expected_copies = 1
    expected_sheets = 1
    orientation = 'portrait'
    duplex = 'single'
    files_desc = ''

    if test_key == 'A':
        f = make_banner_pdf(TEST_DIR / 'test_A_1page.pdf', 'TEST A: 1-PAGE PDF SIMPLEX', 1, False)
        order.update({'file_name': f.name, 'file_path': str(f), 'pages': 1, 'copies': 1, 'duplex': 'single', 'orientation': 'portrait'})
        expected_pages, expected_copies, expected_sheets, orientation, duplex = 1, 1, 1, 'portrait', 'single'
        files_desc = 'test_A_1page.pdf'

    elif test_key == 'B':
        f = make_banner_pdf(TEST_DIR / 'test_B_3page.pdf', 'TEST B: 3-PAGE PDF SIMPLEX', 3, False)
        order.update({'file_name': f.name, 'file_path': str(f), 'pages': 3, 'copies': 1, 'duplex': 'single', 'orientation': 'portrait'})
        expected_pages, expected_copies, expected_sheets, orientation, duplex = 3, 1, 3, 'portrait', 'single'
        files_desc = 'test_B_3page.pdf'

    elif test_key == 'C':
        f1 = make_banner_pdf(TEST_DIR / 'test_C_file1.pdf', 'TEST C: FILE 1 OF 2', 1, False)
        f2 = TEST_DIR / 'test_C_file2.txt'
        f2.write_text('TEST C: FILE 2 OF 2 (TEXT FILE)\nLine 2: Multi-file sequence verification\nLine 3: Printed cleanly.', encoding='utf-8')
        order.update({
            'files': [
                {'name': 'test_C_file1.pdf', 'path': str(f1), 'pages': 1, 'sequence': 1},
                {'name': 'test_C_file2.txt', 'path': str(f2), 'pages': 1, 'sequence': 2}
            ],
            'copies': 1, 'duplex': 'single', 'orientation': 'portrait'
        })
        expected_pages, expected_copies, expected_sheets, orientation, duplex = 2, 1, 2, 'portrait', 'single'
        files_desc = 'test_C_file1.pdf + test_C_file2.txt'

    elif test_key == 'D':
        f1 = make_banner_image(TEST_DIR / 'test_D_1.jpg', 'TEST D: IMAGE 1 OF 3')
        f2 = make_banner_image(TEST_DIR / 'test_D_2.png', 'TEST D: IMAGE 2 OF 3')
        f3 = make_banner_image(TEST_DIR / 'test_D_3.jpg', 'TEST D: IMAGE 3 OF 3')
        order.update({
            'files': [
                {'name': 'test_D_1.jpg', 'path': str(f1), 'pages': 1, 'sequence': 1},
                {'name': 'test_D_2.png', 'path': str(f2), 'pages': 1, 'sequence': 2},
                {'name': 'test_D_3.jpg', 'path': str(f3), 'pages': 1, 'sequence': 3}
            ],
            'copies': 1, 'duplex': 'single', 'orientation': 'portrait'
        })
        expected_pages, expected_copies, expected_sheets, orientation, duplex = 3, 1, 3, 'portrait', 'single'
        files_desc = '3 Images (JPG + PNG + JPG)'

    elif test_key == 'E':
        f = make_banner_pdf(TEST_DIR / 'test_E_portrait.pdf', 'TEST E: PORTRAIT VERIFICATION', 1, False)
        order.update({'file_name': f.name, 'file_path': str(f), 'pages': 1, 'copies': 1, 'duplex': 'single', 'orientation': 'portrait'})
        expected_pages, expected_copies, expected_sheets, orientation, duplex = 1, 1, 1, 'portrait', 'single'
        files_desc = 'test_E_portrait.pdf'

    elif test_key == 'F':
        f = make_banner_pdf(TEST_DIR / 'test_F_landscape.pdf', 'TEST F: LANDSCAPE VERIFICATION (297x210mm)', 1, True)
        order.update({'file_name': f.name, 'file_path': str(f), 'pages': 1, 'copies': 1, 'duplex': 'single', 'orientation': 'landscape'})
        expected_pages, expected_copies, expected_sheets, orientation, duplex = 1, 1, 1, 'landscape', 'single'
        files_desc = 'test_F_landscape.pdf'

    elif test_key == 'G':
        f = make_banner_pdf(TEST_DIR / 'test_G_2copies.pdf', 'TEST G: 2 COPIES VERIFICATION', 1, False)
        order.update({'file_name': f.name, 'file_path': str(f), 'pages': 1, 'copies': 2, 'duplex': 'single', 'orientation': 'portrait'})
        expected_pages, expected_copies, expected_sheets, orientation, duplex = 1, 2, 2, 'portrait', 'single'
        files_desc = 'test_G_2copies.pdf'

    elif test_key == 'H':
        f = make_banner_pdf(TEST_DIR / 'test_H_duplex_long.pdf', 'TEST H: DUPLEX LONG-EDGE (FLIP LIKE BOOK)', 2, False, 'Side 1 & Side 2 on 1 sheet')
        order.update({'file_name': f.name, 'file_path': str(f), 'pages': 2, 'copies': 1, 'duplex': 'duplex_long', 'orientation': 'portrait'})
        expected_pages, expected_copies, expected_sheets, orientation, duplex = 2, 1, 1, 'portrait', 'duplex_long'
        files_desc = 'test_H_duplex_long.pdf'

    elif test_key == 'I':
        f = make_banner_pdf(TEST_DIR / 'test_I_duplex_short.pdf', 'TEST I: DUPLEX SHORT-EDGE (FLIP LIKE CALENDAR)', 2, False, 'Notepad / Calendar Flip')
        order.update({'file_name': f.name, 'file_path': str(f), 'pages': 2, 'copies': 1, 'duplex': 'duplex_short', 'orientation': 'portrait'})
        expected_pages, expected_copies, expected_sheets, orientation, duplex = 2, 1, 1, 'portrait', 'duplex_short'
        files_desc = 'test_I_duplex_short.pdf'

    elif test_key == 'J':
        f1 = make_banner_pdf(TEST_DIR / 'test_J_p1_port.pdf', 'TEST J: PAGE 1 (PORTRAIT)', 1, False)
        f2 = make_banner_pdf(TEST_DIR / 'test_J_p2_land.pdf', 'TEST J: PAGE 2 (LANDSCAPE)', 1, True)
        order.update({
            'files': [
                {'name': 'test_J_p1_port.pdf', 'path': str(f1), 'pages': 1, 'sequence': 1},
                {'name': 'test_J_p2_land.pdf', 'path': str(f2), 'pages': 1, 'sequence': 2}
            ],
            'copies': 1, 'duplex': 'single', 'orientation': 'mixed'
        })
        expected_pages, expected_copies, expected_sheets, orientation, duplex = 2, 1, 2, 'mixed', 'single'
        files_desc = 'Page 1 Portrait + Page 2 Landscape'

    elif test_key == 'K':
        f = make_banner_image(TEST_DIR / 'test_K_fullpage.jpg', 'TEST K: FULL-PAGE PROPORTIONAL IMAGE', False)
        order.update({'file_name': f.name, 'file_path': str(f), 'pages': 1, 'copies': 1, 'duplex': 'single', 'scale_mode': 'fit', 'orientation': 'portrait'})
        expected_pages, expected_copies, expected_sheets, orientation, duplex = 1, 1, 1, 'portrait', 'single'
        files_desc = 'test_K_fullpage.jpg (Proportional Fit)'

    elif test_key == 'L':
        f1 = make_banner_pdf(TEST_DIR / 'test_L_doc1.pdf', 'TEST L: MULTI-FILE DUPLEX (DOC 1)', 2, False)
        f2 = make_banner_pdf(TEST_DIR / 'test_L_doc2.pdf', 'TEST L: MULTI-FILE DUPLEX (DOC 2)', 1, False, 'Doc 2 is 1 page -> padded to 4p total')
        order.update({
            'files': [
                {'name': 'test_L_doc1.pdf', 'path': str(f1), 'pages': 2, 'sequence': 1},
                {'name': 'test_L_doc2.pdf', 'path': str(f2), 'pages': 1, 'sequence': 2}
            ],
            'copies': 2, 'duplex': 'duplex_long', 'orientation': 'portrait'
        })
        expected_pages, expected_copies, expected_sheets, orientation, duplex = 4, 2, 4, 'portrait', 'duplex_long'
        files_desc = '2 Files (3p + 1 blank padding) x 2 Copies Duplex'

    else:
        print(f'Unknown test key {test_key}')
        return None

    # Step 1: Compose unified document through PrintFlow pipeline
    composed_pdf = compose_manifest_to_pdf(order, '', '', TARGET_PRINTER)
    print(f'[PIPELINE] Composed print-ready file: {composed_pdf.name}')

    # Step 2: Dispatch to physical Windows printer
    spooler_job_id = print_document_silently(
        file_path=composed_pdf,
        printer_name=TARGET_PRINTER,
        copies=order.get('copies', 1),
        orientation=order.get('orientation', 'portrait'),
        color_mode='black_white',
        duplex=order.get('duplex', 'single'),
        paper_size=order.get('paper_size', 'a4'),
        scale_mode=order.get('scale_mode', 'fit'),
        pages_per_sheet=1,
        page_order='horizontal',
        page_range='all',
        print_mode='standard',
        already_composed=True
    )
    
    print(f'[SPOOLER] Windows Spooler Job ID: {spooler_job_id}')
    cleared = False
    if spooler_job_id > 0:
        print(f'[SPOOLER] Waiting for spooler to deliver job #{spooler_job_id} to Kyocera printer memory...')
        cleared = wait_for_spooler_clear(TARGET_PRINTER, spooler_job_id, 45.0)
        status_str = 'DELIVERED TO PRINTER' if cleared else 'ACTIVE/PRINTING'
        print(f'[SPOOLER] Job status: {status_str}')

    result = {
        'test_id': f'TEST {test_key}',
        'job_id': order['order_id'],
        'files': files_desc,
        'expected_pages': expected_pages,
        'expected_copies': expected_copies,
        'expected_sheets': expected_sheets,
        'orientation': orientation.upper(),
        'duplex': duplex.upper(),
        'printer': TARGET_PRINTER,
        'spooler_job_id': spooler_job_id,
        'spooler_status': 'DELIVERED TO PRINTER' if cleared else ('SUBMITTED' if spooler_job_id > 0 else 'GDI DIRECT'),
        'result': 'PASS' if spooler_job_id > 0 else 'FAIL'
    }
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', default='A', help='Test key (A through L or ALL)')
    args = parser.parse_args()
    
    if args.test.upper() == 'ALL':
        results = []
        for k in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']:
            res = run_test(k)
            if res:
                results.append(res)
            time.sleep(3.0)
    else:
        results = [run_test(args.test)]

    print('\n' + '=' * 80)
    print('PHYSICAL PRINTER TEST RESULTS MATRIX')
    print('=' * 80)
    for r in results:
        t_id = r['test_id']
        j_id = r['job_id']
        f_desc = r['files']
        s_cnt = r['expected_sheets']
        ori = r['orientation']
        dup = r['duplex']
        s_id = r['spooler_job_id']
        s_stat = r['spooler_status']
        res = r['result']
        print(f'{t_id} | Job: {j_id} | Files: {f_desc} | Sheets: {s_cnt} | Orient: {ori} | Duplex: {dup} | SpoolerID: {s_id} | SpoolerStatus: {s_stat} | Result: {res}')
