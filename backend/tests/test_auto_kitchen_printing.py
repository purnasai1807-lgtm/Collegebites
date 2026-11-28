import base64
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.razorpay_client import razorpay_gateway
from app.models.payment import Receipt, ReceiptPrintJob
from tests.conftest import login_as


def _checkout_razorpay(client: TestClient, headers: dict, canteen_id: str, dish_id: str, idem_key: str) -> dict:
    res = client.post(
        "/api/v1/orders/checkout",
        headers=headers,
        json={
            "canteen_id": canteen_id,
            "payment_method": "razorpay",
            "idempotency_key": idem_key,
            "use_cart": False,
            "accepted_policy": True,
            "direct_items": [{"food_item_id": dish_id, "quantity": 2}],
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_auto_kitchen_receipt_queue_identical_payload_idempotency_and_paper_resume(
    client: TestClient,
    clean_db_and_seed: Session,
):
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")

    main = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = main["id"]
    dish = client.get(f"/api/v1/menus/canteens/{cid}/items").json()[0]

    # 1. Unpaid checkout order MUST NOT trigger any print jobs
    unpaid = _checkout_razorpay(client, student["headers"], cid, dish["id"], "auto-print-unpaid-1")
    unpaid_jobs = clean_db_and_seed.scalars(
        select(ReceiptPrintJob).where(ReceiptPrintJob.order_id == UUID(unpaid["id"]))
    ).all()
    assert len(unpaid_jobs) == 0

    # Cancelling an unpaid order MUST NOT trigger any print jobs
    assert (
        client.post(
            f"/api/v1/orders/{unpaid['id']}/cancel",
            headers=student["headers"],
            json={"reason": "Abandoned payment"},
        ).status_code
        == 200
    )
    assert (
        len(
            clean_db_and_seed.scalars(
                select(ReceiptPrintJob).where(ReceiptPrintJob.order_id == UUID(unpaid["id"]))
            ).all()
        )
        == 0
    )

    # 2. Verified Razorpay payment triggers EXACTLY ONE kitchen_receipt job + ONE customer_receipt job
    pending = _checkout_razorpay(client, student["headers"], cid, dish["id"], "auto-print-paid-1")
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=pending["razorpay_order_id"],
        razorpay_payment_id="pay_auto_kitchen_001",
    )
    ver_res = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": pending["id"],
            "razorpay_order_id": pending["razorpay_order_id"],
            "razorpay_payment_id": "pay_auto_kitchen_001",
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
    )
    assert ver_res.status_code == 200, ver_res.text
    paid_order = ver_res.json()

    # Repeat verification call (idempotent replay) must NOT create duplicate print jobs
    ver_again = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": pending["id"],
            "razorpay_order_id": pending["razorpay_order_id"],
            "razorpay_payment_id": "pay_auto_kitchen_001",
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
    )
    assert ver_again.status_code == 200

    clean_db_and_seed.expire_all()
    oid_uuid = UUID(paid_order["id"])
    kitchen_jobs = clean_db_and_seed.scalars(
        select(ReceiptPrintJob).where(
            ReceiptPrintJob.order_id == oid_uuid,
            ReceiptPrintJob.job_type == "kitchen_receipt",
        )
    ).all()
    customer_jobs = clean_db_and_seed.scalars(
        select(ReceiptPrintJob).where(
            ReceiptPrintJob.order_id == oid_uuid,
            ReceiptPrintJob.job_type == "customer_receipt",
        )
    ).all()
    assert len(kitchen_jobs) == 1
    assert len(customer_jobs) == 1
    k_job = kitchen_jobs[0]
    c_job = customer_jobs[0]

    # 3. Kitchen print job MUST carry the EXACT SAME canonical receipt document, QR payload, and ESC/POS checksum as Customer
    assert k_job.receipt_id == c_job.receipt_id
    assert k_job.payload_checksum == c_job.payload_checksum
    assert k_job.total_segments > 3

    cust_receipt = client.get(f"/api/v1/tokens/receipts/{paid_order['order_number']}", headers=student["headers"]).json()
    receipt_row = clean_db_and_seed.get(Receipt, k_job.receipt_id)
    assert receipt_row is not None
    snap = receipt_row.receipt_snapshot
    for key in (
        "brand",
        "order_number",
        "pickup_token",
        "customer_name",
        "items",
        "total_paid",
        "payment_status",
        "payment_method",
        "qr_payload",
    ):
        assert snap[key] == cust_receipt[key]
    escpos_res = client.get(f"/api/v1/printing/receipts/{paid_order['order_number']}/escpos", headers=manager["headers"])
    assert escpos_res.status_code == 200, escpos_res.text
    escpos_bytes = base64.b64decode(escpos_res.json()["escpos_base64"])
    assert len(escpos_bytes) == k_job.total_bytes

    # 4. Register kitchen thermal printer device and receive agent credentials
    reg_res = client.post(
        "/api/v1/printing/kitchen/printers/register",
        headers=manager["headers"],
        json={
            "canteen_id": cid,
            "department": "kitchen",
            "device_name": "Kitchen Thermal 80mm",
            "connection_type": "local_usb",
            "paper_width": "80mm",
            "supports_realtime_status": True,
            "supports_resume_offset": True,
        },
    )
    assert reg_res.status_code == 201, reg_res.text
    creds = reg_res.json()
    agent_headers = {
        "X-Print-Agent-Id": creds["agent_id"],
        "X-Print-Agent-Token": creds["agent_token"],
    }

    # Heartbeat reports printer online + paper available
    hb1 = client.post(
        "/api/v1/printing/agent/heartbeat",
        headers=agent_headers,
        json={"is_connected": True, "is_online": True, "paper_status": "available"},
    )
    assert hb1.status_code == 200

    # Agent claims next kitchen receipt job in FIFO order
    claim1 = client.post("/api/v1/printing/agent/jobs/claim", headers=agent_headers)
    assert claim1.status_code == 200, claim1.text
    c1 = claim1.json()
    assert c1["claimed"] is True
    assert c1["job"]["id"] == str(k_job.id)
    assert c1["resume_from_segment_index"] == 0
    assert c1["order_number"] == cust_receipt["order_number"]
    segments = c1["segments"]
    assert b"".join(base64.b64decode(s["base64_bytes"]) for s in segments) == escpos_bytes
    assert len(segments) == k_job.total_segments

    # 5. Simulate checkpointing segment 0..1 then paper roll running out at segment 2!
    seg_pause = 2
    byte_pause = int(segments[seg_pause - 1]["byte_end"])
    prog_res = client.post(
        f"/api/v1/printing/agent/jobs/{k_job.id}/progress",
        headers=agent_headers,
        json={
            "printed_segment_index": seg_pause,
            "printed_byte_offset": byte_pause,
            "supports_resume_offset": True,
        },
    )
    assert prog_res.status_code == 200

    pause_res = client.post(
        f"/api/v1/printing/agent/jobs/{k_job.id}/pause",
        headers=agent_headers,
        json={
            "reason": "Paper roll empty mid-receipt",
            "paper_status": "out_of_paper",
            "printed_segment_index": seg_pause,
            "printed_byte_offset": byte_pause,
            "supports_resume_offset": True,
            "is_connected": True,
            "is_online": False,
        },
    )
    assert pause_res.status_code == 200
    assert pause_res.json()["status"] == "paused"
    assert pause_res.json()["last_printed_segment_index"] == seg_pause

    # Kitchen dashboard accurately shows paused job & out-of-paper printer
    dash_paused = client.get(f"/api/v1/printing/kitchen/dashboard?canteen_id={cid}", headers=kitchen["headers"]).json()
    assert dash_paused["summary"]["paused_count"] == 1
    assert dash_paused["summary"]["out_of_paper_printers"] == 1

    # 6. Staff loads new paper roll -> heartbeat reports paper available -> job auto-restores & resumes at segment 2!
    hb2 = client.post(
        "/api/v1/printing/agent/heartbeat",
        headers=agent_headers,
        json={"is_connected": True, "is_online": True, "paper_status": "available"},
    )
    assert hb2.status_code == 200
    assert hb2.json()["restored_jobs_count"] == 1

    claim2 = client.post("/api/v1/printing/agent/jobs/claim", headers=agent_headers)
    assert claim2.status_code == 200
    c2 = claim2.json()
    assert c2["claimed"] is True
    assert c2["job"]["id"] == str(k_job.id)
    assert c2["resume_from_segment_index"] == seg_pause  # Resumes strictly from exact checkpoint, no duplicate 0..1!
    assert len(c2["segments"]) == len(segments)

    # Complete remaining segments
    total_bytes = int(segments[-1]["byte_end"])
    comp_res = client.post(
        f"/api/v1/printing/agent/jobs/{k_job.id}/complete",
        headers=agent_headers,
        json={"printed_segment_index": len(segments), "printed_byte_offset": total_bytes},
    )
    assert comp_res.status_code == 200
    assert comp_res.json()["status"] == "completed"

    # Controlled manual reprint preserves identical payload & marks is_reprint=True
    reprint_res = client.post(
        f"/api/v1/printing/kitchen/receipts/{paid_order['order_number']}/reprint",
        headers=kitchen["headers"],
    )
    assert reprint_res.status_code == 200, reprint_res.text
    assert reprint_res.json()["is_reprint"] is True
    assert reprint_res.json()["receipt_id"] == str(k_job.receipt_id)
    assert bool(reprint_res.json()["payload_checksum"])
    escpos_reprint = client.get(f"/api/v1/printing/receipts/{paid_order['order_number']}/escpos?reprint=true", headers=kitchen["headers"])
    assert escpos_reprint.status_code == 200
    reprint_bytes = base64.b64decode(escpos_reprint.json()["escpos_base64"])
    assert cust_receipt["order_number"].encode("ascii") in reprint_bytes
    assert cust_receipt["qr_payload"].encode("ascii") in reprint_bytes
