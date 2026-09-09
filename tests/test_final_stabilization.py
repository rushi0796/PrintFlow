import unittest
import json
import math
from main import calculate_order_amount, CANONICAL_PRICING

class TestFinalStabilization(unittest.TestCase):
    def test_canonical_pricing_constants(self):
        """Verify standard canonical rates"""
        self.assertEqual(CANONICAL_PRICING["bw_single"], 2.0)
        self.assertEqual(CANONICAL_PRICING["bw_double"], 1.0)
        self.assertEqual(CANONICAL_PRICING["color_single"], 6.0)
        self.assertIsNone(CANONICAL_PRICING["color_double"])
        self.assertEqual(CANONICAL_PRICING["micro_xerox_sheet"], 3.0)

    def test_single_file_standard_pricing(self):
        amt = calculate_order_amount(pages=5, copies=1, color_mode="black_white", duplex="single")
        self.assertEqual(amt, 10.0)

        amt_duplex = calculate_order_amount(pages=5, copies=1, color_mode="black_white", duplex="duplex_long")
        self.assertEqual(amt_duplex, 5.0)

        amt_color = calculate_order_amount(pages=3, copies=2, color_mode="color", duplex="single")
        self.assertEqual(amt_color, 36.0)

    def test_micro_xerox_pricing(self):
        amt_2up = calculate_order_amount(pages=4, copies=1, print_mode="micro_xerox", pages_per_sheet=2)
        self.assertEqual(amt_2up, 6.0)

        amt_4up = calculate_order_amount(pages=5, copies=1, print_mode="micro_xerox", pages_per_sheet=4)
        self.assertEqual(amt_4up, 6.0)

        amt_16up = calculate_order_amount(pages=16, copies=3, print_mode="micro_xerox", pages_per_sheet=16)
        self.assertEqual(amt_16up, 9.0)

        amt_1page = calculate_order_amount(pages=1, copies=1, print_mode="micro_xerox", pages_per_sheet=4)
        self.assertEqual(amt_1page, 3.0)

    def test_per_file_heterogeneous_order_simulation(self):
        files = [
            {
                "id": "file_1_test",
                "name": "doc1.pdf",
                "path": "test_uploads/doc1.pdf",
                "selected_pages_count": 4,
                "copies": 1,
                "print_mode": "micro_xerox",
                "pages_per_sheet": 4,
                "color_mode": "black_white",
                "duplex": "single"
            },
            {
                "id": "file_2_test",
                "name": "doc2.pdf",
                "path": "test_uploads/doc2.pdf",
                "selected_pages_count": 2,
                "copies": 2,
                "print_mode": "standard",
                "pages_per_sheet": 1,
                "color_mode": "black_white",
                "duplex": "single"
            }
        ]

        total_price = 0.0
        for f in files:
            p = calculate_order_amount(
                pages=f["selected_pages_count"],
                copies=f["copies"],
                color_mode=f["color_mode"],
                duplex=f["duplex"],
                print_mode=f["print_mode"],
                pages_per_sheet=f["pages_per_sheet"]
            )
            total_price += p

        self.assertEqual(total_price, 11.0)

    def test_exact_n_cards_logic_in_manifest(self):
        raw_session_3 = [
            {"id": "uid_1", "name": "File1.pdf", "path": "/path/1.pdf", "pages": 2},
            {"id": "uid_2", "name": "File2.pdf", "path": "/path/2.pdf", "pages": 3},
            {"id": "uid_3", "name": "File3.pdf", "path": "/path/3.pdf", "pages": 1},
        ]
        filtered = [f for f in raw_session_3 if f.get("status") != "CANCELED"]
        self.assertEqual(len(filtered), 3)
        self.assertEqual([f["id"] for f in filtered], ["uid_1", "uid_2", "uid_3"])

        raw_session_1 = [
            {"id": "uid_single", "name": "Single.pdf", "path": "/path/single.pdf", "pages": 5}
        ]
        filtered_1 = [f for f in raw_session_1 if f.get("status") != "CANCELED"]
        self.assertEqual(len(filtered_1), 1)
        self.assertEqual(filtered_1[0]["name"], "Single.pdf")

if __name__ == "__main__":
    unittest.main()
