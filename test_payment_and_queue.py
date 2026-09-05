#!/usr/bin/env python3
"""
Comprehensive tests for PrintFlow payment verification and queue flow.

Tests:
1. Missing RAZORPAY_KEY_SECRET → configuration error
2. Valid Razorpay TEST signature → success
3. Invalid signature → failure
4. Existing PF-* order → PRINT_QUEUED
5. File path/settings preserved
6. Duplicate callback → idempotent
7. Different payment ID rejected
8. Pending order NOT in agent poll
9. PRINT_QUEUED order in agent poll
10. End-to-end verified payment → queue → poll
"""

import os
import sys
import json
import hmac
import hashlib
import time
import tempfile
from pathlib import Path
from uuid import uuid4

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from main import app
from fastapi.testclient import TestClient

client = TestClient(app)

# Test Configuration
AGENT_TOKEN = "PF_AGENT_SECRET_TOKEN_2026"

# Razorpay TEST credentials (for testing only - do not commit)
RAZORPAY_TEST_KEY_ID = "rzp_test_test_key_id_12345"
RAZORPAY_TEST_SECRET = "rzp_test_secret_12345"


def test_01_missing_razorpay_secret():
    """
    TEST 1: Missing RAZORPAY_KEY_SECRET should produce configuration error.
    """
    print("\n" + "="*70)
    print("TEST 1: Missing RAZORPAY_KEY_SECRET → Configuration Error")
    print("="*70)
    
    # Temporarily remove the secret
    old_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if "RAZORPAY_KEY_SECRET" in os.environ:
        del os.environ["RAZORPAY_KEY_SECRET"]
    
    try:
        resp = client.post("/api/verify-payment", json={
            "razorpay_order_id": "rzp_test_order_123",
            "razorpay_payment_id": "pay_test_123",
            "razorpay_signature": "invalid",
            "print_order_id": "PF-TEST001"
        })
        
        assert resp.status_code == 500, f"Expected 500, got {resp.status_code}"
        assert "not configured" in resp.json().get("detail", "").lower(), \
            f"Expected 'not configured' message, got: {resp.json()}"
        print("✓ PASSED: Missing secret correctly raises 500 error with clear message")
        return True
    finally:
        # Restore the secret
        if old_secret:
            os.environ["RAZORPAY_KEY_SECRET"] = old_secret


def setup_test_order(order_id: str, file_path: str = "/uploads/test_12345_sample.pdf"):
    """Helper: Create a test order in the orders database."""
    from main import orders_db, save_orders, load_orders
    
    orders_db[:] = load_orders()
    
    # Remove any existing order with this ID
    orders_db[:] = [o for o in orders_db if o.get("order_id") != order_id]
    
    new_order = {
        "order_id": order_id,
        "file_name": "sample.pdf",
        "file_path": file_path,
        "copies": 1,
        "pages": 5,
        "color_mode": "black_white",
        "duplex": "double",
        "orientation": "portrait",
        "customer_mobile": "9876543210",
        "amount": 10.0,
        "status": "Pending",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    orders_db.insert(0, new_order)
    save_orders(orders_db)
    print(f"  [SETUP] Created test order: {order_id}")
    return new_order


def generate_razorpay_signature(order_id: str, payment_id: str, secret: str) -> str:
    """Generate valid Razorpay HMAC signature."""
    msg = f"{order_id}|{payment_id}".encode("utf-8")
    return hmac.new(
        secret.encode("utf-8"),
        msg,
        hashlib.sha256
    ).hexdigest()


def test_02_valid_razorpay_signature():
    """
    TEST 2: Valid Razorpay TEST signature should verify successfully.
    """
    print("\n" + "="*70)
    print("TEST 2: Valid Razorpay Signature → Success")
    print("="*70)
    
    # Set TEST credentials
    os.environ["RAZORPAY_KEY_SECRET"] = RAZORPAY_TEST_SECRET
    os.environ["RAZORPAY_KEY_ID"] = RAZORPAY_TEST_KEY_ID
    
    # Create a test order first
    order_id = f"PF-{uuid4().hex[:6].upper()}"
    setup_test_order(order_id)
    
    # Generate valid signature using TEST secret
    razorpay_order_id = f"order_{uuid4().hex[:8]}"
    payment_id = f"pay_{uuid4().hex[:8]}"
    valid_signature = generate_razorpay_signature(razorpay_order_id, payment_id, RAZORPAY_TEST_SECRET)
    
    # Verify payment
    resp = client.post("/api/verify-payment", json={
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": valid_signature,
        "print_order_id": order_id
    })
    
    print(f"  Response status: {resp.status_code}")
    print(f"  Response body: {json.dumps(resp.json(), indent=2)}")
    
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    data = resp.json()
    assert data.get("status") == "success", f"Expected success, got: {data}"
    print("✓ PASSED: Valid signature verified successfully")
    return True


def test_03_invalid_signature():
    """
    TEST 3: Invalid Razorpay signature should fail.
    """
    print("\n" + "="*70)
    print("TEST 3: Invalid Razorpay Signature → Failure")
    print("="*70)
    
    # Set TEST credentials
    os.environ["RAZORPAY_KEY_SECRET"] = RAZORPAY_TEST_SECRET
    os.environ["RAZORPAY_KEY_ID"] = RAZORPAY_TEST_KEY_ID
    
    # Create a test order
    order_id = f"PF-{uuid4().hex[:6].upper()}"
    setup_test_order(order_id)
    
    # Use WRONG signature
    razorpay_order_id = f"order_{uuid4().hex[:8]}"
    payment_id = f"pay_{uuid4().hex[:8]}"
    invalid_signature = "invalid_signature_12345abcde"
    
    resp = client.post("/api/verify-payment", json={
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": invalid_signature,
        "print_order_id": order_id
    })
    
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    assert "Invalid" in resp.json().get("detail", ""), \
        f"Expected 'Invalid' in error, got: {resp.json()}"
    print("✓ PASSED: Invalid signature correctly rejected")
    return True


def test_04_order_becomes_print_queued():
    """
    TEST 4: After verified payment, PF-* order should become PRINT_QUEUED.
    """
    print("\n" + "="*70)
    print("TEST 4: Verified Payment → PF-* Order Becomes PRINT_QUEUED")
    print("="*70)
    
    os.environ["RAZORPAY_KEY_SECRET"] = RAZORPAY_TEST_SECRET
    os.environ["RAZORPAY_KEY_ID"] = RAZORPAY_TEST_KEY_ID
    
    order_id = f"PF-{uuid4().hex[:6].upper()}"
    file_path = "/uploads/test_12345_sample.pdf"
    setup_test_order(order_id, file_path)
    
    # Verify payment
    razorpay_order_id = f"order_{uuid4().hex[:8]}"
    payment_id = f"pay_{uuid4().hex[:8]}"
    valid_signature = generate_razorpay_signature(razorpay_order_id, payment_id, RAZORPAY_TEST_SECRET)
    
    resp = client.post("/api/verify-payment", json={
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": valid_signature,
        "print_order_id": order_id
    })
    
    assert resp.status_code == 200, f"Verification failed: {resp.json()}"
    data = resp.json()
    
    # Check returned order is PRINT_QUEUED
    order = data.get("order", {})
    assert order.get("status") == "PRINT_QUEUED", \
        f"Expected PRINT_QUEUED, got: {order.get('status')}"
    print(f"  Order ID: {order.get('order_id')}")
    print(f"  Status: {order.get('status')}")
    print("✓ PASSED: Order correctly moved to PRINT_QUEUED")
    return True


def test_05_file_path_preserved():
    """
    TEST 5: After payment, file_path and all settings should be preserved.
    """
    print("\n" + "="*70)
    print("TEST 5: File Path and Settings Preserved After Payment")
    print("="*70)
    
    os.environ["RAZORPAY_KEY_SECRET"] = RAZORPAY_TEST_SECRET
    os.environ["RAZORPAY_KEY_ID"] = RAZORPAY_TEST_KEY_ID
    
    order_id = f"PF-{uuid4().hex[:6].upper()}"
    file_path = "/uploads/preserved_file_abc123.pdf"
    
    original_order = setup_test_order(order_id, file_path)
    
    # Verify payment
    razorpay_order_id = f"order_{uuid4().hex[:8]}"
    payment_id = f"pay_{uuid4().hex[:8]}"
    valid_signature = generate_razorpay_signature(razorpay_order_id, payment_id, RAZORPAY_TEST_SECRET)
    
    resp = client.post("/api/verify-payment", json={
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": valid_signature,
        "print_order_id": order_id
    })
    
    order = resp.json().get("order", {})
    
    # Verify all fields preserved
    assert order.get("file_path") == file_path, \
        f"File path mismatch: expected {file_path}, got {order.get('file_path')}"
    assert order.get("pages") == original_order["pages"], \
        f"Pages mismatch: {order.get('pages')} vs {original_order['pages']}"
    assert order.get("copies") == original_order["copies"], \
        f"Copies mismatch: {order.get('copies')} vs {original_order['copies']}"
    assert order.get("color_mode") == original_order["color_mode"], \
        f"Color mode mismatch: {order.get('color_mode')} vs {original_order['color_mode']}"
    assert order.get("duplex") == original_order["duplex"], \
        f"Duplex mismatch: {order.get('duplex')} vs {original_order['duplex']}"
    assert order.get("orientation") == original_order["orientation"], \
        f"Orientation mismatch: {order.get('orientation')} vs {original_order['orientation']}"
    
    print(f"  File path: {order.get('file_path')}")
    print(f"  Pages: {order.get('pages')}, Copies: {order.get('copies')}")
    print(f"  Color: {order.get('color_mode')}, Duplex: {order.get('duplex')}")
    print("✓ PASSED: All settings preserved after payment")
    return True


def test_06_duplicate_callback_idempotent():
    """
    TEST 6: Duplicate payment callback should be idempotent (no duplicate order).
    """
    print("\n" + "="*70)
    print("TEST 6: Duplicate Payment Callback → Idempotent")
    print("="*70)
    
    os.environ["RAZORPAY_KEY_SECRET"] = RAZORPAY_TEST_SECRET
    os.environ["RAZORPAY_KEY_ID"] = RAZORPAY_TEST_KEY_ID
    
    order_id = f"PF-{uuid4().hex[:6].upper()}"
    setup_test_order(order_id)
    
    razorpay_order_id = f"order_{uuid4().hex[:8]}"
    payment_id = f"pay_{uuid4().hex[:8]}"
    valid_signature = generate_razorpay_signature(razorpay_order_id, payment_id, RAZORPAY_TEST_SECRET)
    
    # First callback
    resp1 = client.post("/api/verify-payment", json={
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": valid_signature,
        "print_order_id": order_id
    })
    
    assert resp1.status_code == 200, f"First verification failed: {resp1.json()}"
    
    # Duplicate callback with same payment_id
    resp2 = client.post("/api/verify-payment", json={
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": valid_signature,
        "print_order_id": order_id
    })
    
    assert resp2.status_code == 200, f"Duplicate verification failed: {resp2.json()}"
    
    # Should return same order, not create duplicate
    from main import load_orders
    orders = load_orders()
    matching_orders = [o for o in orders if o.get("order_id") == order_id]
    assert len(matching_orders) == 1, \
        f"Expected 1 order, found {len(matching_orders)}"
    
    print(f"  Order ID: {order_id}")
    print(f"  Status: {matching_orders[0].get('status')}")
    print("✓ PASSED: Duplicate callback is idempotent")
    return True


def test_07_different_payment_rejected():
    """
    TEST 7: Different payment ID for already-paid order must be rejected.
    """
    print("\n" + "="*70)
    print("TEST 7: Different Payment ID → Rejected")
    print("="*70)
    
    os.environ["RAZORPAY_KEY_SECRET"] = RAZORPAY_TEST_SECRET
    os.environ["RAZORPAY_KEY_ID"] = RAZORPAY_TEST_KEY_ID
    
    order_id = f"PF-{uuid4().hex[:6].upper()}"
    setup_test_order(order_id)
    
    # First payment
    razorpay_order_id = f"order_{uuid4().hex[:8]}"
    payment_id_1 = f"pay_{uuid4().hex[:8]}"
    valid_signature_1 = generate_razorpay_signature(razorpay_order_id, payment_id_1, RAZORPAY_TEST_SECRET)
    
    resp1 = client.post("/api/verify-payment", json={
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": payment_id_1,
        "razorpay_signature": valid_signature_1,
        "print_order_id": order_id
    })
    
    assert resp1.status_code == 200, f"First payment failed: {resp1.json()}"
    
    # Try different payment ID
    payment_id_2 = f"pay_{uuid4().hex[:8]}"
    valid_signature_2 = generate_razorpay_signature(razorpay_order_id, payment_id_2, RAZORPAY_TEST_SECRET)
    
    resp2 = client.post("/api/verify-payment", json={
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": payment_id_2,
        "razorpay_signature": valid_signature_2,
        "print_order_id": order_id
    })
    
    assert resp2.status_code == 409, f"Expected 409, got {resp2.status_code}: {resp2.json()}"
    assert "already paid" in resp2.json().get("detail", "").lower(), \
        f"Expected 'already paid', got: {resp2.json()}"
    print(f"  Order ID: {order_id}")
    print(f"  First payment: {payment_id_1} ✓")
    print(f"  Second payment attempt: {payment_id_2} ✗ REJECTED")
    print("✓ PASSED: Different payment correctly rejected")
    return True


def test_08_pending_order_not_in_poll():
    """
    TEST 8: Pending (unpaid) order must NOT be returned by /api/agent/poll.
    """
    print("\n" + "="*70)
    print("TEST 8: Pending Order NOT in Agent Poll")
    print("="*70)
    
    os.environ["RAZORPAY_KEY_SECRET"] = RAZORPAY_TEST_SECRET
    os.environ["RAZORPAY_KEY_ID"] = RAZORPAY_TEST_KEY_ID
    
    # Create a pending order (do NOT verify payment)
    pending_order_id = f"PF-{uuid4().hex[:6].upper()}"
    setup_test_order(pending_order_id)
    
    # Poll agent
    resp = client.post("/api/agent/poll", json={
        "printers": [],
        "status": "ONLINE"
    }, headers={
        "X-Print-Agent-Token": AGENT_TOKEN
    })
    
    assert resp.status_code == 200, f"Poll failed: {resp.json()}"
    jobs = resp.json().get("jobs", [])
    
    # Verify pending order NOT in jobs
    job_ids = [j.get("order_id") for j in jobs]
    assert pending_order_id not in job_ids, \
        f"Pending order {pending_order_id} should NOT be in poll results"
    
    print(f"  Pending order ID: {pending_order_id}")
    print(f"  Jobs returned: {len(jobs)}")
    print(f"  Pending order in poll: NO ✓")
    print("✓ PASSED: Pending order correctly excluded from poll")
    return True


def test_09_print_queued_in_poll():
    """
    TEST 9: PRINT_QUEUED order MUST be returned by /api/agent/poll.
    """
    print("\n" + "="*70)
    print("TEST 9: PRINT_QUEUED Order in Agent Poll")
    print("="*70)
    
    os.environ["RAZORPAY_KEY_SECRET"] = RAZORPAY_TEST_SECRET
    os.environ["RAZORPAY_KEY_ID"] = RAZORPAY_TEST_KEY_ID
    
    # Create and verify payment
    queued_order_id = f"PF-{uuid4().hex[:6].upper()}"
    setup_test_order(queued_order_id)
    
    razorpay_order_id = f"order_{uuid4().hex[:8]}"
    payment_id = f"pay_{uuid4().hex[:8]}"
    valid_signature = generate_razorpay_signature(razorpay_order_id, payment_id, RAZORPAY_TEST_SECRET)
    
    resp_verify = client.post("/api/verify-payment", json={
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": valid_signature,
        "print_order_id": queued_order_id
    })
    
    assert resp_verify.status_code == 200, f"Verification failed: {resp_verify.json()}"
    
    # Poll agent
    resp_poll = client.post("/api/agent/poll", json={
        "printers": [],
        "status": "ONLINE"
    }, headers={
        "X-Print-Agent-Token": AGENT_TOKEN
    })
    
    jobs = resp_poll.json().get("jobs", [])
    job_ids = [j.get("order_id") for j in jobs]
    
    assert queued_order_id in job_ids, \
        f"PRINT_QUEUED order {queued_order_id} should be in poll results"
    
    # Find the job and verify details
    job = next((j for j in jobs if j.get("order_id") == queued_order_id), None)
    assert job is not None, "Job not found"
    assert job.get("status") == "PRINT_QUEUED", f"Expected PRINT_QUEUED, got {job.get('status')}"
    
    print(f"  Queued order ID: {queued_order_id}")
    print(f"  Status: {job.get('status')}")
    print(f"  File path: {job.get('file_path')}")
    print(f"  Queued order in poll: YES ✓")
    print("✓ PASSED: PRINT_QUEUED order correctly included in poll")
    return True


def test_10_end_to_end_flow():
    """
    TEST 10: End-to-end verified payment → PRINT_QUEUED → agent poll.
    """
    print("\n" + "="*70)
    print("TEST 10: End-to-End Flow: Payment → Queue → Agent Poll")
    print("="*70)
    
    os.environ["RAZORPAY_KEY_SECRET"] = RAZORPAY_TEST_SECRET
    os.environ["RAZORPAY_KEY_ID"] = RAZORPAY_TEST_KEY_ID
    
    e2e_order_id = f"PF-{uuid4().hex[:6].upper()}"
    file_path = "/uploads/e2e_test_sample.pdf"
    
    # Step 1: Create order
    setup_test_order(e2e_order_id, file_path)
    print(f"  [1/4] Order created: {e2e_order_id}")
    
    from main import load_orders
    orders = load_orders()
    order = next((o for o in orders if o.get("order_id") == e2e_order_id), None)
    assert order is not None, "Order not found after creation"
    assert order.get("status") == "Pending", f"Expected Pending, got {order.get('status')}"
    
    # Step 2: Verify payment
    razorpay_order_id = f"order_{uuid4().hex[:8]}"
    payment_id = f"pay_{uuid4().hex[:8]}"
    valid_signature = generate_razorpay_signature(razorpay_order_id, payment_id, RAZORPAY_TEST_SECRET)
    
    resp_verify = client.post("/api/verify-payment", json={
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": valid_signature,
        "print_order_id": e2e_order_id
    })
    
    assert resp_verify.status_code == 200, f"Verification failed: {resp_verify.json()}"
    order_data = resp_verify.json().get("order", {})
    assert order_data.get("status") == "PRINT_QUEUED", f"Expected PRINT_QUEUED, got {order_data.get('status')}"
    print(f"  [2/4] Payment verified: {payment_id} → PRINT_QUEUED")
    
    # Step 3: Poll agent (should include the order)
    resp_poll = client.post("/api/agent/poll", json={
        "printers": [],
        "status": "ONLINE"
    }, headers={
        "X-Print-Agent-Token": AGENT_TOKEN
    })
    
    jobs = resp_poll.json().get("jobs", [])
    job = next((j for j in jobs if j.get("order_id") == e2e_order_id), None)
    assert job is not None, "Order not found in agent poll"
    assert job.get("status") == "PRINT_QUEUED", f"Expected PRINT_QUEUED in poll"
    print(f"  [3/4] Agent poll: Found queued order")
    
    # Step 4: Agent claims and completes
    resp_claim = client.post(f"/api/agent/claim/{e2e_order_id}", headers={
        "X-Print-Agent-Token": AGENT_TOKEN
    })
    assert resp_claim.status_code == 200, f"Claim failed: {resp_claim.json()}"
    
    resp_complete = client.post(f"/api/agent/complete/{e2e_order_id}", json={
        "status": "COMPLETED",
        "printed_by_printer": "Test Printer"
    }, headers={
        "X-Print-Agent-Token": AGENT_TOKEN
    })
    assert resp_complete.status_code == 200, f"Complete failed: {resp_complete.json()}"
    print(f"  [4/4] Agent completed: order marked COMPLETED")
    
    # Verify final state
    orders = load_orders()
    final_order = next((o for o in orders if o.get("order_id") == e2e_order_id), None)
    assert final_order.get("status") == "COMPLETED", f"Expected COMPLETED, got {final_order.get('status')}"
    
    print(f"\n✓ PASSED: Complete end-to-end flow successful")
    return True


def run_all_tests():
    """Run all tests and report results."""
    print("\n" + "="*70)
    print("PrintFlow Payment & Queue Flow Test Suite")
    print("="*70)
    
    tests = [
        test_01_missing_razorpay_secret,
        test_02_valid_razorpay_signature,
        test_03_invalid_signature,
        test_04_order_becomes_print_queued,
        test_05_file_path_preserved,
        test_06_duplicate_callback_idempotent,
        test_07_different_payment_rejected,
        test_08_pending_order_not_in_poll,
        test_09_print_queued_in_poll,
        test_10_end_to_end_flow,
    ]
    
    results = []
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            result = test_func()
            if result:
                passed += 1
                results.append((test_func.__name__, "PASSED", None))
            else:
                failed += 1
                results.append((test_func.__name__, "FAILED", "Test returned False"))
        except AssertionError as e:
            failed += 1
            results.append((test_func.__name__, "FAILED", str(e)))
        except Exception as e:
            failed += 1
            results.append((test_func.__name__, "ERROR", str(e)))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    for name, status, error in results:
        symbol = "✓" if status == "PASSED" else "✗"
        print(f"{symbol} {name}: {status}")
        if error:
            print(f"  └─ {error}")
    
    print(f"\nTotal: {len(tests)} | Passed: {passed} | Failed: {failed}")
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n❌ {failed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
