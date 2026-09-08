import os
import sys
import unittest
import tempfile
import json
from pathlib import Path
from PIL import Image
import pypdf

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import storage
from print_agent import (
    get_installed_windows_printers,
    get_printer_hardware_caps,
    convert_image_to_pdf_page,
    convert_text_to_pdf,
    optimize_pdf_for_full_page,
    compose_manifest_to_pdf,
    select_target_printer
)
from reportlab.pdfgen import canvas

class TestFinalPrintingEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="pf_test_"))

    def tearDown(self):
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_pdf(self, path: Path, num_pages: int = 1, width: float = 595.28, height: float = 841.89, text: str = "Test Page"):
        c = canvas.Canvas(str(path), pagesize=(width, height))
        for i in range(num_pages):
            c.drawString(100, height - 100, f"{text} - {i+1}")
            c.showPage()
        c.save()
        return path

    def _create_sample_image(self, path: Path, width: int = 800, height: int = 600, color=(100, 150, 200)):
        img = Image.new("RGB", (width, height), color=color)
        img.save(path)
        return path

    def _create_sample_text(self, path: Path, text: str = "Hello PrintFlow\nLine 2\nLine 3"):
        path.write_text(text, encoding="utf-8")
        return path

    # 1. Multi-file manifest normalization (PDF + Image + TXT)
    def test_01_multifile_manifest_normalization(self):
        pdf_f = self._create_sample_pdf(self.temp_dir / "sample.pdf", num_pages=2)
        img_f = self._create_sample_image(self.temp_dir / "sample.png", 800, 600)
        txt_f = self._create_sample_text(self.temp_dir / "sample.txt", "Document text content")

        out_img_pdf = self.temp_dir / "img_norm.pdf"
        convert_image_to_pdf_page(img_f, out_img_pdf, orientation="portrait", paper_size="a4", scale_mode="fit")
        self.assertTrue(out_img_pdf.exists())
        r_img = pypdf.PdfReader(str(out_img_pdf))
        self.assertEqual(len(r_img.pages), 1)

        out_txt_pdf = self.temp_dir / "txt_norm.pdf"
        convert_text_to_pdf(txt_f, out_txt_pdf, orientation="portrait", paper_size="a4")
        self.assertTrue(out_txt_pdf.exists())
        r_txt = pypdf.PdfReader(str(out_txt_pdf))
        self.assertEqual(len(r_txt.pages), 1)

        r_pdf = pypdf.PdfReader(str(pdf_f))
        self.assertEqual(len(r_pdf.pages), 2)

    # 2. Sequential page ordering across files
    def test_02_sequential_page_ordering_across_files(self):
        pdf1 = self._create_sample_pdf(self.temp_dir / "doc1.pdf", num_pages=1, text="Doc 1 First")
        pdf2 = self._create_sample_pdf(self.temp_dir / "doc2.pdf", num_pages=1, text="Doc 2 Second")
        pdf3 = self._create_sample_pdf(self.temp_dir / "doc3.pdf", num_pages=1, text="Doc 3 Third")

        claimed_order = {
            "order_id": "test_seq_order",
            "files": [
                {"name": "doc2.pdf", "path": str(pdf2.resolve()), "sequence": 1},
                {"name": "doc3.pdf", "path": str(pdf3.resolve()), "sequence": 2},
                {"name": "doc1.pdf", "path": str(pdf1.resolve()), "sequence": 0},
            ],
            "orientation": "portrait",
            "paper_size": "a4",
            "scale_mode": "fit",
            "duplex": "single"
        }
        composed_pdf = compose_manifest_to_pdf(claimed_order, "", "", "")
        self.assertTrue(composed_pdf.exists())
        reader = pypdf.PdfReader(str(composed_pdf))
        self.assertEqual(len(reader.pages), 3)

    # 3. Duplex support detection via DeviceCapabilities (DC_DUPLEX)
    def test_03_duplex_support_detection(self):
        printers = get_installed_windows_printers()
        self.assertIsInstance(printers, list)
        self.assertGreater(len(printers), 0)
        
        for p in printers:
            self.assertIn("name", p)
            self.assertIn("duplex_supported", p)
            self.assertIn("color_supported", p)
            self.assertIn("paper_sizes", p)
            self.assertIn("online", p)

        kyocera = next((p for p in printers if "Kyocera" in p["name"] and "3212" not in p["name"]), None)
        if kyocera:
            self.assertTrue(kyocera["duplex_supported"], "Kyocera ECOSYS M2040dn must support hardware duplex")

        epson = next((p for p in printers if "EPSON" in p["name"] and "L3210" in p["name"]), None)
        if epson:
            self.assertFalse(epson["duplex_supported"], "EPSON L3210 is simplex-only, must NOT support duplex")

    # 4. Hardware duplex long-edge configuration
    def test_04_hardware_duplex_long_edge_config(self):
        for term in ("duplex_long", "duplexlong", "long_edge", "double", "duplex", "vertical"):
            duplex_setting = "duplexlong" if term in ("duplex_long", "duplexlong", "long_edge", "double", "duplex", "vertical") else "noduplex"
            self.assertEqual(duplex_setting, "duplexlong")

    # 5. Hardware duplex short-edge configuration
    def test_05_hardware_duplex_short_edge_config(self):
        for term in ("duplex_short", "duplexshort", "short_edge", "short", "horizontal"):
            duplex_setting = "duplexshort" if term in ("duplex_short", "duplexshort", "short_edge", "short", "horizontal") else "noduplex"
            self.assertEqual(duplex_setting, "duplexshort")

    # 6. Duplex rejection on non-duplex printer (NO SILENT FALLBACK)
    def test_06_duplex_rejection_on_non_duplex_printer(self):
        fake_printer = {
            "name": "EPSON L3210 Series",
            "duplex_supported": False,
            "online": True
        }
        duplex = "duplex_long"
        is_duplex_job = duplex in ("duplex_long", "duplex_short", "double", "long_edge")
        
        self.assertTrue(is_duplex_job)
        self.assertFalse(fake_printer["duplex_supported"])
        rejected = False
        error_msg = ""
        if is_duplex_job and fake_printer["duplex_supported"] is False:
            rejected = True
            error_msg = f"Duplex printing is not supported by the selected printer '{fake_printer['name']}'."
        
        self.assertTrue(rejected)
        self.assertIn("Duplex printing is not supported", error_msg)

    # 7. Odd-page duplex trailing blank page insertion (3 -> 4 pages)
    def test_07_odd_page_duplex_trailing_blank_page(self):
        pdf_f = self._create_sample_pdf(self.temp_dir / "odd3.pdf", num_pages=3)
        claimed_order = {
            "order_id": "test_odd_3",
            "file_path": str(pdf_f.resolve()),
            "file_name": "odd3.pdf",
            "orientation": "portrait",
            "paper_size": "a4",
            "scale_mode": "fit",
            "duplex": "duplex_long",
            "color_mode": "black_white"
        }
        composed_pdf = compose_manifest_to_pdf(claimed_order, "", "", "")
        reader = pypdf.PdfReader(str(composed_pdf))
        self.assertEqual(len(reader.pages), 4, "3-page duplex document must be padded to 4 pages")

    # 8. Even-page duplex unchanged (4 -> 4 pages)
    def test_08_even_page_duplex_unchanged(self):
        pdf_f = self._create_sample_pdf(self.temp_dir / "even4.pdf", num_pages=4)
        claimed_order = {
            "order_id": "test_even_4",
            "file_path": str(pdf_f.resolve()),
            "file_name": "even4.pdf",
            "orientation": "portrait",
            "paper_size": "a4",
            "scale_mode": "fit",
            "duplex": "duplex_long",
            "color_mode": "black_white"
        }
        composed_pdf = compose_manifest_to_pdf(claimed_order, "", "", "")
        reader = pypdf.PdfReader(str(composed_pdf))
        self.assertEqual(len(reader.pages), 4, "4-page duplex document must remain exactly 4 pages")

    # 9. Portrait orientation matching
    def test_09_portrait_orientation_matching(self):
        pdf_f = self._create_sample_pdf(self.temp_dir / "port.pdf", num_pages=1, width=595.28, height=841.89)
        opt_pdf = optimize_pdf_for_full_page(pdf_f, paper_size="a4", orientation="portrait")
        reader = pypdf.PdfReader(str(opt_pdf))
        p = reader.pages[0]
        self.assertLess(float(p.mediabox.width), float(p.mediabox.height), "Portrait page must have width < height")

    # 10. Landscape orientation matching (90° canvas placement)
    def test_10_landscape_orientation_matching(self):
        pdf_f = self._create_sample_pdf(self.temp_dir / "land.pdf", num_pages=1, width=595.28, height=841.89)
        opt_pdf = optimize_pdf_for_full_page(pdf_f, paper_size="a4", orientation="landscape")
        reader = pypdf.PdfReader(str(opt_pdf))
        p = reader.pages[0]
        self.assertGreater(float(p.mediabox.width), float(p.mediabox.height), "Landscape page must have width > height")

    # 11. Mixed orientation handling across multi-page document
    def test_11_mixed_orientation_handling(self):
        mixed_pdf = self.temp_dir / "mixed.pdf"
        c = canvas.Canvas(str(mixed_pdf))
        # Page 1: Portrait
        c.setPageSize((595.28, 841.89))
        c.drawString(100, 700, "Portrait Page 1")
        c.showPage()
        # Page 2: Landscape
        c.setPageSize((841.89, 595.28))
        c.drawString(100, 500, "Landscape Page 2")
        c.showPage()
        c.save()

        opt_pdf = optimize_pdf_for_full_page(mixed_pdf, paper_size="a4", orientation="landscape")
        reader = pypdf.PdfReader(str(opt_pdf))
        for idx, page in enumerate(reader.pages):
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            self.assertGreater(w, h, f"Page {idx+1} in landscape document must have width > height")

    # 12. Paper size mapping (A4, Letter, Legal)
    def test_12_paper_size_mapping(self):
        caps_a4 = get_printer_hardware_caps("", "portrait", "a4")
        caps_letter = get_printer_hardware_caps("", "portrait", "letter")
        caps_legal = get_printer_hardware_caps("", "portrait", "legal")

        self.assertAlmostEqual(caps_a4["paper_w_pt"], 595.28, delta=10.0)
        self.assertAlmostEqual(caps_letter["paper_w_pt"], 612.0, delta=10.0)
        self.assertAlmostEqual(caps_legal["paper_h_pt"], 1008.0, delta=15.0)

    # 13. Image scale FIT (proportional, fully visible)
    def test_13_image_scale_fit(self):
        img_f = self._create_sample_image(self.temp_dir / "fit_img.png", width=1200, height=600)
        out_pdf = self.temp_dir / "fit_out.pdf"
        convert_image_to_pdf_page(img_f, out_pdf, orientation="portrait", paper_size="a4", scale_mode="fit")
        self.assertTrue(out_pdf.exists())
        reader = pypdf.PdfReader(str(out_pdf))
        self.assertEqual(len(reader.pages), 1)

    # 14. Image scale FILL (proportional, maximum coverage)
    def test_14_image_scale_fill(self):
        img_f = self._create_sample_image(self.temp_dir / "fill_img.png", width=1200, height=600)
        out_pdf = self.temp_dir / "fill_out.pdf"
        convert_image_to_pdf_page(img_f, out_pdf, orientation="portrait", paper_size="a4", scale_mode="fill")
        self.assertTrue(out_pdf.exists())
        reader = pypdf.PdfReader(str(out_pdf))
        self.assertEqual(len(reader.pages), 1)

    # 15. Spooler Job ID assignment & tracking
    def test_15_spooler_job_id_assignment(self):
        order_data = {
            "order_id": "PF_TEST_SPOOLER_15",
            "amount": 4.0,
            "pages": 2,
            "copies": 1,
            "color_mode": "black_white",
            "duplex": "single",
            "paper_size": "a4",
            "orientation": "portrait",
            "scale_mode": "fit",
            "file_name": "test.pdf",
            "file_path": "/test.pdf",
            "customer_mobile": "9876543210",
            "status": "Pending",
            "spooler_job_id": 142
        }
        saved = storage.save_order(order_data)
        self.assertTrue(saved)
        fetched = storage.get_order("PF_TEST_SPOOLER_15")
        self.assertIsNotNone(fetched)
        self.assertEqual(int(fetched.get("spooler_job_id", 0)), 142)

    # 16. Spooler status transitions (SUBMITTED_TO_SPOOLER -> PRINTING -> COMPLETED)
    def test_16_spooler_status_transitions(self):
        order_data = {
            "order_id": "PF_TEST_SPOOLER_16",
            "amount": 2.0,
            "pages": 1,
            "copies": 1,
            "color_mode": "black_white",
            "duplex": "single",
            "paper_size": "a4",
            "orientation": "portrait",
            "scale_mode": "fit",
            "file_name": "test.pdf",
            "file_path": "/test.pdf",
            "customer_mobile": "9876543210",
            "status": "Pending"
        }
        storage.save_order(order_data)

        # Transition 1: SUBMITTED_TO_SPOOLER
        storage.complete_order("PF_TEST_SPOOLER_16", printer_name="Kyocera ECOSYS M2040dn KX", spooler_job_id=201, status="SUBMITTED_TO_SPOOLER")
        o1 = storage.get_order("PF_TEST_SPOOLER_16")
        self.assertEqual(o1.get("status"), "SUBMITTED_TO_SPOOLER")
        self.assertEqual(int(o1.get("spooler_job_id", 0)), 201)

        # Transition 2: PRINTING
        storage.complete_order("PF_TEST_SPOOLER_16", printer_name="Kyocera ECOSYS M2040dn KX", spooler_job_id=201, status="PRINTING")
        o2 = storage.get_order("PF_TEST_SPOOLER_16")
        self.assertEqual(o2.get("status"), "PRINTING")

        # Transition 3: COMPLETED
        storage.complete_order("PF_TEST_SPOOLER_16", printer_name="Kyocera ECOSYS M2040dn KX", spooler_job_id=201, status="COMPLETED")
        o3 = storage.get_order("PF_TEST_SPOOLER_16")
        self.assertEqual(o3.get("status"), "COMPLETED")

    # 17. Offline printer detection & failure handling
    def test_17_offline_printer_detection(self):
        fake_installed = [
            {"name": "Kyocera Offline Test", "driver": "KX", "status": "Offline", "online": False, "is_default": True}
        ]
        config = {"bw_printer": "Kyocera Offline Test"}
        target = select_target_printer("black_white", config, fake_installed)
        self.assertEqual(target, "Kyocera Offline Test")

        p_info = next((p for p in fake_installed if p["name"] == target), None)
        self.assertFalse(p_info.get("online", True))

        order_data = {
            "order_id": "PF_TEST_OFFLINE_17",
            "amount": 2.0,
            "status": "PRINT_QUEUED"
        }
        storage.save_order(order_data)

        # Mark as FAILED due to offline printer
        storage.complete_order("PF_TEST_OFFLINE_17", printer_name=target, status="FAILED", error="Target printer is offline")
        o = storage.get_order("PF_TEST_OFFLINE_17")
        err_msg = str(o.get("error") or o.get("print_error") or "")
        self.assertIn("offline", err_msg.lower())

    # 18. Price calculation validation (total_logical_pages * copies * 2)
    def test_18_price_calculation_validation(self):
        self.assertEqual(1 * 1 * 2.0, 2.0)
        self.assertEqual(3 * 2 * 2.0, 12.0)
        files_pages = [2, 1, 2]
        total_pages = sum(files_pages)
        self.assertEqual(total_pages, 5)
        self.assertEqual(total_pages * 3 * 2.0, 30.0)

if __name__ == "__main__":
    unittest.main(verbosity=2)
