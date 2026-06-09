import base64
import logging
from decimal import Decimal

import requests
from django.conf import settings

from .models import PromotionalCode

logger = logging.getLogger(__name__)


class PayPalError(Exception):
    """Errore PayPal loggabile e mappabile dalle view sui messaggi esistenti."""

    def __init__(self, message, *, status_code=None, response_text=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


def get_paypal_base_url():
    return 'https://api-m.sandbox.paypal.com' if settings.PAYPAL_MODE == 'sandbox' else 'https://api-m.paypal.com'


def get_paypal_access_token() -> str:
    """Auth client-credentials verso PayPal. Solleva PayPalError su fallimento."""
    auth = base64.b64encode(f"{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_CLIENT_SECRET}".encode()).decode()

    try:
        token_response = requests.post(
            f'{get_paypal_base_url()}/v1/oauth2/token',
            headers={
                'Authorization': f'Basic {auth}',
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            data={'grant_type': 'client_credentials'},
            timeout=15,
        )
    except requests.exceptions.RequestException as exc:
        logger.error(f"PayPal token request failed: {exc}")
        raise PayPalError('PayPal token request failed') from exc

    if token_response.status_code != 200:
        raise PayPalError(
            'PayPal authentication failed',
            status_code=token_response.status_code,
            response_text=token_response.text,
        )

    data = token_response.json()
    access_token = data.get('access_token')
    if not access_token:
        raise PayPalError('PayPal access token missing', status_code=token_response.status_code)

    return access_token


def create_paypal_order(*, amount, currency, description, return_url, cancel_url, reference_id=None) -> dict:
    """Crea l'ordine e restituisce il JSON PayPal (id + approval link)."""
    access_token = get_paypal_access_token()
    purchase_unit = {
        "description": description,
        "amount": {
            "currency_code": currency,
            "value": str(amount),
        },
    }
    if reference_id:
        purchase_unit["reference_id"] = reference_id

    order_data = {
        "intent": "CAPTURE",
        "purchase_units": [purchase_unit],
        "application_context": {
            "return_url": return_url,
            "cancel_url": cancel_url,
            "brand_name": "Ombra del Portico",
            "user_action": "PAY_NOW",
        },
    }

    try:
        order_response = requests.post(
            f'{get_paypal_base_url()}/v2/checkout/orders',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            },
            json=order_data,
            timeout=15,
        )
    except requests.exceptions.RequestException as exc:
        logger.error(f"PayPal order request failed: {exc}")
        raise PayPalError('PayPal order request failed') from exc

    if order_response.status_code != 201:
        raise PayPalError(
            'PayPal order creation failed',
            status_code=order_response.status_code,
            response_text=order_response.text,
        )

    return order_response.json()


def capture_paypal_order(order_id: str) -> dict:
    """Cattura l'ordine approvato e restituisce il JSON PayPal."""
    access_token = get_paypal_access_token()

    try:
        capture_response = requests.post(
            f'{get_paypal_base_url()}/v2/checkout/orders/{order_id}/capture',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            },
            timeout=15,
        )
    except requests.exceptions.RequestException as exc:
        logger.error(f"PayPal capture request failed: {exc}")
        raise PayPalError('PayPal capture request failed') from exc

    if capture_response.status_code != 201:
        raise PayPalError(
            'PayPal capture failed',
            status_code=capture_response.status_code,
            response_text=capture_response.text,
        )

    return capture_response.json()


def validate_promo_code(code: str, *, context: str, original_price=None, enforce_min_amount=True) -> dict | None:
    """Valida un codice promo e restituisce sconto/metadati, None se invalido."""
    code = (code or '').strip()
    if not code:
        return None

    try:
        promo = PromotionalCode.objects.get(code=code)
    except PromotionalCode.DoesNotExist:
        return None

    is_valid, message = promo.is_valid()
    if not is_valid:
        return None

    if not promo.can_apply_to(context):
        return None

    price = Decimal(str(original_price)) if original_price is not None else None
    if enforce_min_amount and price is not None and price < promo.min_amount:
        return None

    discount_amount = promo.calculate_discount(price) if price is not None else Decimal('0')
    final_price = max(Decimal('0'), price - discount_amount) if price is not None else None

    return {
        'promo': promo,
        'code': code,
        'message': message,
        'discount_amount': discount_amount,
        'final_price': final_price,
        'description': promo.get_discount_display(),
    }
