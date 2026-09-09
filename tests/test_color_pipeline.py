import unittest
from pathlib import Path
from print_agent import select_target_printer, convert_image_to_pdf_page
from PIL import Image

class TestColorPipeline(unittest.TestCase):
    def setUp(self):
        self.dummy_installed_printers = [
            {
                "name": "EPSON L3110 Series",
                "online": False,
                "color_supported": True,
                "is_default": False
            },
            {
                "name": "Kyocera ECOSYS M2040dn KX",
                "online": True,
                "color_supported": False,
                "is_default": True
            },
            {
                "name": "EPSON L3210 Series",
                "online": True,
                "color_supported": True,
                "is_default": False
            }
        ]

    def test_select_target_printer_color_prefers_online(self):
        config = {"color_printer": "EPSON L3110 Series", "bw_printer": "Kyocera ECOSYS M2040dn KX"}
        # EPSON L3110 is offline, so it must route to online EPSON L3210
        target = select_target_printer("color", config, self.dummy_installed_printers)
        self.assertEqual(target, "EPSON L3210 Series")

    def test_select_target_printer_color_explicit_online(self):
        config = {"color_printer": "EPSON L3210 Series", "bw_printer": "Kyocera ECOSYS M2040dn KX"}
        target = select_target_printer("color", config, self.dummy_installed_printers)
        self.assertEqual(target, "EPSON L3210 Series")

    def test_select_target_printer_bw_routes_to_kyocera(self):
        config = {"color_printer": "EPSON L3210 Series", "bw_printer": "Kyocera ECOSYS M2040dn KX"}
        target = select_target_printer("black_white", config, self.dummy_installed_printers)
        self.assertEqual(target, "Kyocera ECOSYS M2040dn KX")

    def test_convert_image_fallback_to_pil(self):
        test_dir = Path(__file__).resolve().parent / "temp_test_img"
        test_dir.mkdir(exist_ok=True)
        img_path = test_dir / "sample_rgb.png"
        img = Image.new("RGB", (200, 200), color=(255, 0, 0))
        img.save(img_path)

        out_pdf = test_dir / "sample_rgb.pdf"
        if out_pdf.exists():
            out_pdf.unlink()

        res_pdf = convert_image_to_pdf_page(
            image_path=img_path,
            out_pdf_path=out_pdf,
            orientation="portrait",
            paper_size="a4",
            scale_mode="fit",
            printer_name="EPSON L3210 Series"
        )
        self.assertTrue(res_pdf.exists())
        self.assertGreater(res_pdf.stat().st_size, 500)

        try:
            img_path.unlink()
            out_pdf.unlink()
            test_dir.rmdir()
        except Exception:
            pass

if __name__ == "__main__":
    unittest.main()
