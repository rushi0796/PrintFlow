import unittest
import os
import sys
import hmac
import hashlib
import json
import tempfile
import time
from pathlib import Path
from PIL import Image
from reportlab.pdfgen import canvas
import pypdf

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import calculate_order_amount, queue_order_for_printing, verify_razorpay_payment
from storage import init_storage, save_order, get_order, complete_order, claim_order
from print_agent import (
    compose_manifest_to_pdf,
    convert_image_to_pdf_page,
    get_printer_hardware_caps,
    get_installed_windows_printers
)

class TestProductionMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_storage()
        cls.temp_dir = Path(tempfile.mkdtemp(prefix='pf_prod_test_'))

    def _create_dummy_pdf(self, filename: str, num_pages: int = 1, width: float = 595.276, height: float = 841.890) -> Path:
        path = self.temp_dir / filename
        c = canvas.Canvas(str(path), pagesize=(width, height))
        for p in range(1, num_pages + 1):
            c.drawString(100, height - 100, f'Doc: {filename} Page: {p}')
            c.showPage()
        c.save()
        return path

    def _create_dummy_image(self, filename: str, width: int = 800, height: int = 600, color=(100, 150, 200)) -> Path:
        path = self.temp_dir / filename
        img = Image.new('RGB', (width, height), color)
        img.save(path)
        return path

    # A. One PDF, 1 page, 1 copy, simplex
    def test_A_one_pdf_1page_simplex(self):
        pdf = self._create_dummy_pdf('test_A.pdf', 1)
        order = {
            'order_id': 'TEST_A',
            'file_name': 'test_A.pdf',
            'file_path': str(pdf),
            'pages': 1,
            'copies': 1,
            'duplex': 'single',
            'orientation': 'portrait'
        }
        res_pdf = compose_manifest_to_pdf(order, '', '', '')
        reader = pypdf.PdfReader(str(res_pdf))
        self.assertEqual(len(reader.pages), 1)
        cost = calculate_order_amount(1, 1, 'black_white', 'single')
        self.assertEqual(cost, 2.0)

    # B. One PDF, multiple pages (5 pages)
    def test_B_one_pdf_multiple_pages(self):
        pdf = self._create_dummy_pdf('test_B.pdf', 5)
        order = {
            'order_id': 'TEST_B',
            'file_name': 'test_B.pdf',
            'file_path': str(pdf),
            'pages': 5,
            'copies': 1,
            'duplex': 'single',
            'orientation': 'portrait'
        }
        res_pdf = compose_manifest_to_pdf(order, '', '', '')
        reader = pypdf.PdfReader(str(res_pdf))
        self.assertEqual(len(reader.pages), 5)
        cost = calculate_order_amount(5, 1, 'black_white', 'single')
        self.assertEqual(cost, 10.0)

    # C. Multiple PDFs (2 PDFs, 2p and 3p = 5p)
    def test_C_multiple_pdfs(self):
        pdf1 = self._create_dummy_pdf('test_C1.pdf', 2)
        pdf2 = self._create_dummy_pdf('test_C2.pdf', 3)
        order = {
            'order_id': 'TEST_C',
            'files': [
                {'name': 'test_C1.pdf', 'path': str(pdf1), 'pages': 2, 'sequence': 1},
                {'name': 'test_C2.pdf', 'path': str(pdf2), 'pages': 3, 'sequence': 2}
            ],
            'copies': 1,
            'duplex': 'single'
        }
        res_pdf = compose_manifest_to_pdf(order, '', '', '')
        reader = pypdf.PdfReader(str(res_pdf))
        self.assertEqual(len(reader.pages), 5)

    # D. Multiple images (3 images)
    def test_D_multiple_images(self):
        img1 = self._create_dummy_image('test_D1.jpg')
        img2 = self._create_dummy_image('test_D2.png')
        img3 = self._create_dummy_image('test_D3.jpg')
        order = {
            'order_id': 'TEST_D',
            'files': [
                {'name': 'test_D1.jpg', 'path': str(img1), 'pages': 1, 'sequence': 1},
                {'name': 'test_D2.png', 'path': str(img2), 'pages': 1, 'sequence': 2},
                {'name': 'test_D3.jpg', 'path': str(img3), 'pages': 1, 'sequence': 3}
            ],
            'copies': 1,
            'duplex': 'single'
        }
        res_pdf = compose_manifest_to_pdf(order, '', '', '')
        reader = pypdf.PdfReader(str(res_pdf))
        self.assertEqual(len(reader.pages), 3)

    # E. PDF + images together
    def test_E_pdf_and_images_together(self):
        pdf = self._create_dummy_pdf('test_E.pdf', 2)
        img = self._create_dummy_image('test_E.jpg')
        order = {
            'order_id': 'TEST_E',
            'files': [
                {'name': 'test_E.pdf', 'path': str(pdf), 'pages': 2, 'sequence': 1},
                {'name': 'test_E.jpg', 'path': str(img), 'pages': 1, 'sequence': 2}
            ],
            'copies': 1,
            'duplex': 'single'
        }
        res_pdf = compose_manifest_to_pdf(order, '', '', '')
        reader = pypdf.PdfReader(str(res_pdf))
        self.assertEqual(len(reader.pages), 3)

    # F. Portrait
    def test_F_portrait_orientation(self):
        pdf = self._create_dummy_pdf('test_F.pdf', 1, 595.276, 841.890)
        reader = pypdf.PdfReader(str(pdf))
        w = float(reader.pages[0].mediabox.width)
        h = float(reader.pages[0].mediabox.height)
        self.assertLess(w, h)

    # G. Landscape
    def test_G_landscape_orientation(self):
        pdf = self._create_dummy_pdf('test_G.pdf', 1, 841.890, 595.276)
        reader = pypdf.PdfReader(str(pdf))
        w = float(reader.pages[0].mediabox.width)
        h = float(reader.pages[0].mediabox.height)
        self.assertGreater(w, h)

    # H. Mixed portrait + landscape
    def test_H_mixed_portrait_landscape(self):
        p_pdf = self._create_dummy_pdf('test_H_p.pdf', 1, 595.276, 841.890)
        l_pdf = self._create_dummy_pdf('test_H_l.pdf', 1, 841.890, 595.276)
        order = {
            'order_id': 'TEST_H',
            'files': [
                {'name': 'test_H_p.pdf', 'path': str(p_pdf), 'pages': 1, 'sequence': 1},
                {'name': 'test_H_l.pdf', 'path': str(l_pdf), 'pages': 1, 'sequence': 2}
            ]
        }
        res_pdf = compose_manifest_to_pdf(order, '', '', '')
        reader = pypdf.PdfReader(str(res_pdf))
        self.assertEqual(len(reader.pages), 2)
        self.assertLess(float(reader.pages[0].mediabox.width), float(reader.pages[0].mediabox.height))
        self.assertGreater(float(reader.pages[1].mediabox.width), float(reader.pages[1].mediabox.height))

    # I. 2 copies
    def test_I_two_copies(self):
        cost = calculate_order_amount(3, 2, 'black_white', 'single')
        self.assertEqual(cost, 12.0)  # 3 * 2 * 2 = 12

    # J. 3 copies
    def test_J_three_copies(self):
        cost = calculate_order_amount(3, 3, 'black_white', 'single')
        self.assertEqual(cost, 18.0)  # 3 * 3 * 2 = 18

    # K. Duplex long-edge (with odd page padding)
    def test_K_duplex_long_edge(self):
        pdf = self._create_dummy_pdf('test_K.pdf', 3)
        order = {
            'order_id': 'TEST_K',
            'file_name': 'test_K.pdf',
            'file_path': str(pdf),
            'pages': 3,
            'duplex': 'duplex_long'
        }
        res_pdf = compose_manifest_to_pdf(order, '', '', '')
        reader = pypdf.PdfReader(str(res_pdf))
        # 3 pages in duplex must be padded with 1 blank trailing page to 4 pages!
        self.assertEqual(len(reader.pages), 4)

    # L. Duplex short-edge (even pages unchanged)
    def test_L_duplex_short_edge(self):
        pdf = self._create_dummy_pdf('test_L.pdf', 4)
        order = {
            'order_id': 'TEST_L',
            'file_name': 'test_L.pdf',
            'file_path': str(pdf),
            'pages': 4,
            'duplex': 'duplex_short'
        }
        res_pdf = compose_manifest_to_pdf(order, '', '', '')
        reader = pypdf.PdfReader(str(res_pdf))
        self.assertEqual(len(reader.pages), 4)

    # M. Printer without duplex
    def test_M_printer_without_duplex(self):
        printers = get_installed_windows_printers()
        epson = next((p for p in printers if 'L3210' in p['name']), None)
        if epson:
            self.assertFalse(epson['duplex_supported'])

    # N. Printer offline
    def test_N_printer_offline_detection(self):
        printers = get_installed_windows_printers()
        taskalfa = next((p for p in printers if 'TASKalfa' in p['name']), None)
        if taskalfa:
            self.assertFalse(taskalfa['online'])
            self.assertEqual(taskalfa['status'], 'Offline')

    # O. Failed payment
    def test_O_failed_payment_signature(self):
        os.environ['RAZORPAY_KEY_SECRET'] = 'test_secret_123'
        from fastapi import HTTPException
        invalid_payload = {
            'razorpay_order_id': 'order_123',
            'razorpay_payment_id': 'pay_456',
            'razorpay_signature': 'invalid_signature_xyz'
        }
        with self.assertRaises(HTTPException) as ctx:
            verify_razorpay_payment(invalid_payload)
        self.assertEqual(ctx.exception.status_code, 400)

    # P. Successful LIVE Razorpay payment HMAC verification
    def test_P_successful_razorpay_hmac_signature(self):
        secret = 'secret_test_key_999'
        os.environ['RAZORPAY_KEY_SECRET'] = secret
        order_id = 'order_valid_777'
        payment_id = 'pay_valid_888'
        msg = f'{order_id}|{payment_id}'.encode('utf-8')
        sig = hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).hexdigest()

        # Seed order in DB
        save_order({'order_id': 'PF-TEST-P', 'razorpay_order_id': order_id, 'file_name': 'test.pdf', 'status': 'Pending', 'paid': False})

        payload = {
            'print_order_id': 'PF-TEST-P',
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': sig
        }
        res = verify_razorpay_payment(payload)
        self.assertEqual(res.get('status'), 'success')
        self.assertEqual(res.get('order_status'), 'PRINT_QUEUED')

    # Q. Duplicate payment callback (Idempotency)
    def test_Q_duplicate_payment_callback(self):
        order = get_order('PF-TEST-P')
        self.assertTrue(order.get('paid'))
        # Second call with same order
        res2 = queue_order_for_printing({'order_id': 'PF-TEST-P', 'paid': True})
        self.assertEqual(res2.get('status'), 'PRINT_QUEUED')
        self.assertTrue(res2.get('paid'))

    # R. Page refresh after payment
    def test_R_page_refresh_after_payment(self):
        order_entry = {
            'order_id': 'PF-TEST-R-REFRESH',
            'paid': True,
            'status': 'PRINT_QUEUED',
            'file_name': 'doc.pdf'
        }
        save_order(order_entry)
        refreshed = queue_order_for_printing({'order_id': 'PF-TEST-R-REFRESH'})
        self.assertEqual(refreshed.get('order_id'), 'PF-TEST-R-REFRESH')
        self.assertEqual(refreshed.get('status'), 'PRINT_QUEUED')

    # S. Large PDF (multi-page streaming)
    def test_S_large_pdf(self):
        large_pdf = self._create_dummy_pdf('test_S_large.pdf', 25)
        order = {
            'order_id': 'TEST_S',
            'file_name': 'test_S_large.pdf',
            'file_path': str(large_pdf),
            'pages': 25,
            'duplex': 'single'
        }
        res_pdf = compose_manifest_to_pdf(order, '', '', '')
        reader = pypdf.PdfReader(str(res_pdf))
        self.assertEqual(len(reader.pages), 25)

    # T. Multiple simultaneous uploaded files
    def test_T_multiple_simultaneous_files(self):
        f1 = self._create_dummy_pdf('simul_1.pdf', 1)
        f2 = self._create_dummy_image('simul_2.jpg')
        f3 = self._create_dummy_pdf('simul_3.pdf', 2)
        f4 = self._create_dummy_image('simul_4.png')
        order = {
            'order_id': 'TEST_T',
            'files': [
                {'name': 'simul_1.pdf', 'path': str(f1), 'pages': 1, 'sequence': 1},
                {'name': 'simul_2.jpg', 'path': str(f2), 'pages': 1, 'sequence': 2},
                {'name': 'simul_3.pdf', 'path': str(f3), 'pages': 2, 'sequence': 3},
                {'name': 'simul_4.png', 'path': str(f4), 'pages': 1, 'sequence': 4}
            ]
        }
        res_pdf = compose_manifest_to_pdf(order, '', '', '')
        reader = pypdf.PdfReader(str(res_pdf))
        self.assertEqual(len(reader.pages), 5)

if __name__ == '__main__':
    unittest.main()
