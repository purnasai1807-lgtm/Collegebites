import hashlib
import hmac
import secrets
from decimal import Decimal
from typing import Any, Optional

import razorpay
import requests
from fastapi import HTTPException

from app.core.config import settings

_LOCAL_TEST_KEY_ID = "rzp_test_collegebites_local"
_LOCAL_TEST_KEY_SECRET = "rzp_test_secret_collegebites_local"
_LOCAL_TEST_WEBHOOK_SECRET = "rzp_webhook_secret_collegebites_local"


class RazorpayGateway:
    """
    Razorpay Standard Checkout integration powered by the official `razorpay` Python SDK.
    Razorpay is the sole online payment gateway supported by CollegeBites.
    Secrets (`RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`) never leave the backend.
    """

    def __init__(self) -> None:
        self._use_live_api_override: Optional[bool] = None
        self._key_id_override: Optional[str] = None
        self._key_secret_override: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return bool(settings.RAZORPAY_KEY_ID.strip() and settings.RAZORPAY_KEY_SECRET.strip())

    @property
    def use_live_api(self) -> bool:
        if self._use_live_api_override is not None:
            return self._use_live_api_override
        return self.is_configured

    @use_live_api.setter
    def use_live_api(self, value: Optional[bool]) -> None:
        self._use_live_api_override = value

    @property
    def public_key_id(self) -> Optional[str]:
        return settings.RAZORPAY_KEY_ID.strip() or None

    @property
    def key_id(self) -> str:
        if self._key_id_override is not None:
            return self._key_id_override
        configured = settings.RAZORPAY_KEY_ID.strip()
        if configured:
            return configured
        if settings.is_production:
            raise HTTPException(
                status_code=503,
                detail="Razorpay payment gateway (RAZORPAY_KEY_ID) is not configured in production.",
            )
        return _LOCAL_TEST_KEY_ID

    @key_id.setter
    def key_id(self, value: Optional[str]) -> None:
        self._key_id_override = value

    @property
    def key_secret(self) -> str:
        if self._key_secret_override is not None:
            return self._key_secret_override
        configured = settings.RAZORPAY_KEY_SECRET.strip()
        if configured:
            return configured
        if settings.is_production:
            raise HTTPException(
                status_code=503,
                detail="Razorpay payment gateway (RAZORPAY_KEY_SECRET) is not configured in production.",
            )
        return _LOCAL_TEST_KEY_SECRET

    @key_secret.setter
    def key_secret(self, value: Optional[str]) -> None:
        self._key_secret_override = value

    @property
    def webhook_secret(self) -> str:
        configured = settings.RAZORPAY_WEBHOOK_SECRET.strip()
        if configured:
            return configured
        if settings.is_production:
            return ""
        return _LOCAL_TEST_WEBHOOK_SECRET

    def _client(self) -> razorpay.Client:
        return razorpay.Client(auth=(self.key_id, self.key_secret))

    def create_order(
        self,
        *,
        amount_inr: Decimal,
        receipt_ref: str,
        notes: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        amount_paise = int((amount_inr * 100).quantize(Decimal("1")))
        if amount_paise < 100:
            raise HTTPException(
                status_code=400,
                detail="Minimum payment amount for Razorpay is ₹1.00 (100 paise).",
            )
        if self.use_live_api:
            payload = {
                "amount": amount_paise,
                "currency": "INR",
                "receipt": receipt_ref[:40],
                "payment_capture": 1,
                "notes": notes or {},
            }
            try:
                return self._client().order.create(data=payload)
            except razorpay.errors.BadRequestError as exc:
                msg = str(exc) or "Razorpay request error"
                if "auth" in msg.lower():
                    raise HTTPException(
                        status_code=401,
                        detail="Razorpay authentication failed. Verify server RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.",
                    ) from exc
                raise HTTPException(status_code=502, detail=f"Razorpay order creation error: {msg}") from exc
            except (
                razorpay.errors.GatewayError,
                razorpay.errors.ServerError,
                requests.exceptions.RequestException,
            ) as exc:
                raise HTTPException(
                    status_code=502,
                    detail="Razorpay gateway temporarily unreachable while creating order.",
                ) from exc

        if settings.is_production:
            raise HTTPException(
                status_code=503,
                detail="Razorpay payment gateway credentials (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET) are not configured in production.",
            )
        return {
            "id": f"order_test_{secrets.token_hex(8)}",
            "entity": "order",
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt_ref[:40],
            "status": "created",
        }

    def verify_payment_signature(
        self,
        *,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> bool:
        if not (razorpay_order_id and razorpay_payment_id and razorpay_signature):
            return False
        if self.use_live_api:
            try:
                self._client().utility.verify_payment_signature(
                    {
                        "razorpay_order_id": razorpay_order_id.strip(),
                        "razorpay_payment_id": razorpay_payment_id.strip(),
                        "razorpay_signature": razorpay_signature.strip(),
                    }
                )
                return True
            except razorpay.errors.SignatureVerificationError:
                return False
        if settings.is_production and not self.is_configured:
            return False
        secret = self.key_secret
        msg = f"{razorpay_order_id.strip()}|{razorpay_payment_id.strip()}".encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, razorpay_signature.strip())

    def compute_test_payment_signature(self, *, razorpay_order_id: str, razorpay_payment_id: str) -> str:
        if settings.is_production:
            raise RuntimeError("Test signature helper is disabled in production.")
        secret = settings.RAZORPAY_KEY_SECRET.strip() or _LOCAL_TEST_KEY_SECRET
        body = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def verify_webhook_signature(self, *, raw_body: bytes, x_razorpay_signature: str) -> bool:
        if not raw_body or not x_razorpay_signature:
            return False
        secret = self.webhook_secret
        if not secret:
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, x_razorpay_signature.strip())

    def compute_test_webhook_signature(self, *, raw_body: bytes) -> str:
        if settings.is_production:
            raise RuntimeError("Test webhook signature helper is disabled in production.")
        secret = settings.RAZORPAY_WEBHOOK_SECRET.strip() or _LOCAL_TEST_WEBHOOK_SECRET
        return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    def fetch_payment(self, razorpay_payment_id: str) -> Optional[dict[str, Any]]:
        if not self.use_live_api or not razorpay_payment_id:
            return None
        try:
            return self._client().payment.fetch(razorpay_payment_id.strip())
        except (
            razorpay.errors.BadRequestError,
            razorpay.errors.GatewayError,
            razorpay.errors.ServerError,
            requests.exceptions.RequestException,
        ):
            return None

    def capture_payment(self, razorpay_payment_id: str, amount_paise: int, currency: str = "INR") -> Optional[dict[str, Any]]:
        if not self.use_live_api or not razorpay_payment_id:
            return None
        try:
            return self._client().payment.capture(razorpay_payment_id.strip(), amount_paise, {"currency": currency})
        except (
            razorpay.errors.BadRequestError,
            razorpay.errors.GatewayError,
            razorpay.errors.ServerError,
            requests.exceptions.RequestException,
        ):
            return None

    def fetch_order(self, razorpay_order_id: str) -> Optional[dict[str, Any]]:
        if not self.use_live_api or not razorpay_order_id:
            return None
        try:
            return self._client().order.fetch(razorpay_order_id.strip())
        except (
            razorpay.errors.BadRequestError,
            razorpay.errors.GatewayError,
            razorpay.errors.ServerError,
            requests.exceptions.RequestException,
        ):
            return None

    def fetch_order_payments(self, razorpay_order_id: str) -> list[dict[str, Any]]:
        if not self.use_live_api or not razorpay_order_id:
            return []
        try:
            resp = self._client().order.payments(razorpay_order_id.strip())
            if isinstance(resp, dict) and isinstance(resp.get("items"), list):
                return resp["items"]
            return []
        except (
            razorpay.errors.BadRequestError,
            razorpay.errors.GatewayError,
            razorpay.errors.ServerError,
            requests.exceptions.RequestException,
        ):
            return []


razorpay_gateway = RazorpayGateway()
