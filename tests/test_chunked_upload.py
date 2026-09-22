import os
import io
import asyncio
import unittest
import tempfile
from pathlib import Path
from reportlab.pdfgen import canvas
import pypdf
from fastapi import UploadFile

import storage
from main import (
    upload_pdf,
    upload_chunk_endpoint,
    upload_complete_endpoint,
    download_document,
    get_document_meta_endpoint,
    calculate_document_page_count,
    create_print_order,
    PrintOrder
)
from print_agent import download_file, compose_manifest_to_pdf, optimize_pdf_for_full_page


class TestChunkedUploadAndUnlimitedPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        storage.init_storage()

    def create_sample_pdf(self, page_count: int, target_size_bytes: int = 0) -> bytes:
        """Generates a valid multi-page PDF with exact page count."""
        from PIL import Image
        from reportlab.lib.utils import ImageReader
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(595.28, 841.89))
        for p in range(1, page_count + 1):
            c.setFont("Helvetica-Bold", 24)
            c.drawString(100, 750, f"PrintFlow Document — Page {p} of {page_count}")
            c.setFont("Helvetica", 14)
            c.drawString(100, 700, f"Verification Test: Unlimited Page Architecture")
            c.rect(50, 50, 495, 740, fill=0, stroke=1)
            if target_size_bytes > 1_000_000 and p in (1, 15, 30, 42):
                raw = os.urandom(1250 * 1500)
                img = Image.frombytes('L', (1250, 1500), raw)
                img_buf = io.BytesIO()
                img.save(img_buf, format='JPEG', quality=90)
                c.drawImage(ImageReader(img_buf), 100, 100, width=350, height=450)
            c.showPage()
        c.save()
        return buf.getvalue()

    def test_01_direct_upload_small_pdf(self):
        """Small file (<= 3.5 MB) uploads in a single direct request."""
        pdf_content = self.create_sample_pdf(page_count=3, target_size_bytes=50000)
        upload_file = UploadFile(filename="small_doc.pdf", file=io.BytesIO(pdf_content))

        data = asyncio.run(upload_pdf(upload_file))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["file_name"], "small_doc.pdf")
        self.assertEqual(data["page_count"], 3)
        self.assertTrue(data["file_path"].startswith("/api/documents/"))

    def test_02_chunked_upload_large_51_page_pdf(self):
        """Large 7.1 MB PDF with 51 pages uploaded in 2 MB chunks and assembled without 413 error."""
        target_size = int(7.1 * 1024 * 1024)  # ~7.1 MB
        pdf_content = self.create_sample_pdf(page_count=51, target_size_bytes=target_size)
        self.assertGreaterEqual(len(pdf_content), 7 * 1024 * 1024)

        # Verify raw PDF has 51 pages
        reader = pypdf.PdfReader(io.BytesIO(pdf_content))
        self.assertEqual(len(reader.pages), 51)

        from uuid import uuid4
        upload_id = f"test_up_{uuid4().hex[:8]}"
        chunk_size = 2 * 1024 * 1024  # 2 MB chunks
        total_chunks = (len(pdf_content) + chunk_size - 1) // chunk_size
        self.assertEqual(total_chunks, 4)

        # Upload each chunk
        for i in range(total_chunks):
            start = i * chunk_size
            end = min(len(pdf_content), start + chunk_size)
            chunk_bytes = pdf_content[start:end]

            chunk_upload = UploadFile(filename="large_51p.pdf", file=io.BytesIO(chunk_bytes))
            c_data = asyncio.run(upload_chunk_endpoint(
                upload_id=upload_id,
                chunk_index=i,
                total_chunks=total_chunks,
                file_name="large_51p.pdf",
                file_size=len(pdf_content),
                chunk=chunk_upload
            ))
            self.assertEqual(c_data["status"], "success")
            self.assertEqual(c_data["chunk_index"], i)
            self.assertEqual(c_data["bytes_received"], len(chunk_bytes))

        # Complete assembly
        result = asyncio.run(upload_complete_endpoint(
            upload_id=upload_id,
            file_name="large_51p.pdf",
            total_chunks=total_chunks,
            mime_type="application/pdf"
        ))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["file_name"], "large_51p.pdf")
        self.assertEqual(result["page_count"], 51)
        self.assertEqual(result["pages"], 51)
        self.assertTrue(result["file_path"].startswith("/api/documents/"))

        doc_id = result["file_path"].split("/")[-1]

        # Verify metadata
        meta = get_document_meta_endpoint(doc_id)
        self.assertEqual(meta["file_size"], len(pdf_content))
        self.assertEqual(meta["file_name"], "large_51p.pdf")

        # Verify range request
        range_resp = download_document(doc_id, range="bytes=0-1048575")
        self.assertEqual(range_resp.status_code, 206)
        self.assertEqual(len(range_resp.body), 1048576)
        self.assertEqual(range_resp.body, pdf_content[:1048576])

        # Verify chunk query param
        chunk_param_resp = download_document(doc_id, chunk_index=0, chunk_size=2097152)
        self.assertEqual(chunk_param_resp.status_code, 206)
        self.assertEqual(len(chunk_param_resp.body), 2097152)
        self.assertEqual(chunk_param_resp.body, pdf_content[:2097152])

        # Verify full document retrieval and page count
        full_doc = storage.get_document(doc_id)
        self.assertIsNotNone(full_doc)
        self.assertEqual(len(full_doc["content"]), len(pdf_content))
        self.assertEqual(full_doc["content"], pdf_content)

        # Verify pypdf on stored document has all 51 pages
        stored_reader = pypdf.PdfReader(io.BytesIO(full_doc["content"]))
        self.assertEqual(len(stored_reader.pages), 51)

    def test_03_unlimited_page_count_500_pages(self):
        """Page count detection handles 500 pages with zero truncation."""
        pdf_500 = self.create_sample_pdf(page_count=500)
        detected = calculate_document_page_count("book_500.pdf", pdf_500)
        self.assertEqual(detected, 500)

    def test_04_print_order_creation_with_51_pages(self):
        """Verify order creation and pricing calculation correctly accepts 51 pages without capping."""
        order_obj = PrintOrder(
            file_name="51_page_report.pdf",
            file_path="/api/documents/test_51p_doc",
            pages=51,
            copies=1,
            color_mode="black_white",
            duplex="double",
            orientation="portrait",
            binding="long_edge",
            files=[
                {
                    "id": "file_1",
                    "name": "51_page_report.pdf",
                    "path": "/api/documents/test_51p_doc",
                    "pages": 51,
                    "selected_pages_count": 51,
                    "copies": 1,
                    "color_mode": "black_white",
                    "duplex": "duplex_long",
                    "orientation": "portrait",
                    "sequence": 1
                }
            ]
        )
        res = create_print_order(order_obj)
        self.assertEqual(res["status"], "success")
        order = res["order"]
        self.assertEqual(order["pages"], 51)
        # B&W double sided is ₹1.0 per page * 51 pages = ₹51.0
        self.assertEqual(order["amount"], 51.0)

    def test_05_clean_expired_chunks(self):
        """Verify expired chunks cleanup method executes cleanly without errors."""
        deleted = storage.cleanup_expired_upload_chunks(max_age_hours=0)
        self.assertIsInstance(deleted, int)


if __name__ == "__main__":
    unittest.main()
