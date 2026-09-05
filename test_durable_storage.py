from datetime import datetime
from uuid import uuid4

from storage import (
    claim_order,
    complete_order,
    delete_document,
    get_document,
    get_order,
    queue_paid_order,
    save_document,
    save_order,
)


def new_order(order_id):
    return {
        "order_id": order_id,
        "file_name": "durable-test.txt",
        "file_path": "",
        "pages": 1,
        "copies": 1,
        "color_mode": "black_white",
        "duplex": "single",
        "orientation": "portrait",
        "amount": 2.0,
        "paid": False,
        "status": "Pending",
        "document_status": "UPLOADED",
        "timestamp": datetime.utcnow().isoformat(),
    }


def main():
    order_id = f"TEST-DURABLE-{uuid4().hex[:8].upper()}"
    document_id = save_document("durable-test.txt", "text/plain", b"durable print test")
    order = new_order(order_id)
    order["file_path"] = f"/api/documents/{document_id}"
    save_order(order)

    assert get_order(order_id)["status"] == "Pending"
    assert get_document(document_id)["content"] == b"durable print test"
    assert claim_order(order_id) is None
    assert queue_paid_order(order_id, "order_durable", "pay_durable")["status"] == "PRINT_QUEUED"
    assert claim_order(order_id)["status"] == "PRINTING"
    assert complete_order(order_id, "FAILED", "controlled failure", "Test Printer")["status"] == "FAILED"
    assert get_order(order_id)["print_error"] == "controlled failure"
    assert complete_order(order_id, "COMPLETED", "", "Test Printer")["status"] == "COMPLETED"
    delete_document(document_id)
    assert get_document(document_id) is None
    print("durable storage tests passed")


if __name__ == "__main__":
    main()
