import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path
import pypdf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main
from print_agent import compose_manifest_to_pdf


class TestPerFilePrintConfiguration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix='pf_per_file_test_'))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_pdf(self, filename: str, page_count: int) -> Path:
        pdf_path = self.temp_dir / filename
        writer = pypdf.PdfWriter()
        for i in range(1, page_count + 1):
            writer.add_blank_page(width=595.28, height=841.89)
        with open(pdf_path, 'wb') as f:
            writer.write(f)
        return pdf_path

    def test_canonical_pricing_per_file_and_sum(self):
        p1 = main.calculate_order_amount(5, 1, color_mode='black_white', duplex='duplex_long')
        self.assertEqual(p1, 5.0)

        p2 = main.calculate_order_amount(3, 2, color_mode='black_white', duplex='single')
        self.assertEqual(p2, 12.0)

        p3 = main.calculate_order_amount(2, 1, color_mode='color', duplex='single')
        self.assertEqual(p3, 12.0)

        p4 = main.calculate_order_amount(8, 1, print_mode='micro_xerox', pages_per_sheet=4)
        self.assertEqual(p4, 6.0)

        total = p1 + p2 + p3 + p4
        self.assertEqual(total, 35.0)

    def test_duplex_boundary_odd_pages_isolation(self):
        f1_path = self._create_sample_pdf('doc1_3pages.pdf', 3)
        f2_path = self._create_sample_pdf('doc2_2pages.pdf', 2)

        order = {
            'order_id': 'TEST_DUPLEX_BOUNDARY_ODD',
            'duplex': 'duplex_long',
            'files': [
                {
                    'name': 'doc1_3pages.pdf',
                    'path': str(f1_path),
                    'pages': 3,
                    'sequence': 0,
                    'duplex': 'duplex_long'
                },
                {
                    'name': 'doc2_2pages.pdf',
                    'path': str(f2_path),
                    'pages': 2,
                    'sequence': 1,
                    'duplex': 'single'
                }
            ]
        }

        composed = compose_manifest_to_pdf(
            order,
            backend_url='http://127.0.0.1:8000',
            agent_token='test_token',
            target_printer='Kyocera ECOSYS M2040dn KX'
        )
        self.assertTrue(composed.exists())

        reader = pypdf.PdfReader(str(composed))
        self.assertEqual(len(reader.pages), 6, f'Expected 6 pages (3 doc1 + 1 blank + 2 doc2), got {len(reader.pages)}')

    def test_duplex_boundary_even_pages_no_unnecessary_padding(self):
        f1_path = self._create_sample_pdf('doc1_4pages.pdf', 4)
        f2_path = self._create_sample_pdf('doc2_2pages.pdf', 2)

        order = {
            'order_id': 'TEST_DUPLEX_BOUNDARY_EVEN',
            'duplex': 'duplex_long',
            'files': [
                {
                    'name': 'doc1_4pages.pdf',
                    'path': str(f1_path),
                    'pages': 4,
                    'sequence': 0,
                    'duplex': 'duplex_long'
                },
                {
                    'name': 'doc2_2pages.pdf',
                    'path': str(f2_path),
                    'pages': 2,
                    'sequence': 1,
                    'duplex': 'duplex_long'
                }
            ]
        }

        composed = compose_manifest_to_pdf(
            order,
            backend_url='http://127.0.0.1:8000',
            agent_token='test_token',
            target_printer='Kyocera ECOSYS M2040dn KX'
        )
        reader = pypdf.PdfReader(str(composed))
        self.assertEqual(len(reader.pages), 6)

    def test_single_file_odd_duplex_padded_for_hardware(self):
        f1_path = self._create_sample_pdf('single_3pages.pdf', 3)
        order = {
            'order_id': 'TEST_SINGLE_ODD_DUPLEX',
            'duplex': 'duplex_long',
            'files': [
                {
                    'name': 'single_3pages.pdf',
                    'path': str(f1_path),
                    'pages': 3,
                    'sequence': 0,
                    'duplex': 'duplex_long'
                }
            ]
        }

        composed = compose_manifest_to_pdf(
            order,
            backend_url='http://127.0.0.1:8000',
            agent_token='test_token',
            target_printer='Kyocera ECOSYS M2040dn KX'
        )
        reader = pypdf.PdfReader(str(composed))
        self.assertEqual(len(reader.pages), 4, f'Single odd duplex file should be padded to 4 pages, got {len(reader.pages)}')

    def test_heterogeneous_segment_detection(self):
        order_hetero = {
            'order_id': 'TEST_HETERO',
            'files': [
                {'name': 'a.pdf', 'duplex': 'duplex_long', 'copies': 1},
                {'name': 'b.pdf', 'duplex': 'single', 'copies': 1}
            ]
        }
        raw_files = order_hetero['files']
        f0 = raw_files[0]
        f0_duplex = f0.get('duplex')
        f0_copies = f0.get('copies')
        is_hetero = any(
            f.get('duplex') != f0_duplex or f.get('copies') != f0_copies
            for f in raw_files[1:]
        )
        self.assertTrue(is_hetero, 'Order with Duplex + Simplex should be detected as heterogeneous')

        order_homo = {
            'order_id': 'TEST_HOMO',
            'files': [
                {'name': 'a.pdf', 'duplex': 'duplex_long', 'copies': 1},
                {'name': 'b.pdf', 'duplex': 'duplex_long', 'copies': 1}
            ]
        }
        raw_files2 = order_homo['files']
        f0 = raw_files2[0]
        f0_duplex = f0.get('duplex')
        f0_copies = f0.get('copies')
        is_hetero2 = any(
            f.get('duplex') != f0_duplex or f.get('copies') != f0_copies
            for f in raw_files2[1:]
        )
        self.assertFalse(is_hetero2, 'Order with identical duplex and copies should not be heterogeneous')


if __name__ == '__main__':
    unittest.main()
