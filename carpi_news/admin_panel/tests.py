from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from home.models import Articolo

from .models import Banner, PromotionalCode
from .payments import (
    PayPalError,
    capture_paypal_order,
    create_paypal_order,
    get_paypal_access_token,
    validate_promo_code,
)


class PayPalResponse:
    def __init__(self, status_code, data=None, text=''):
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


@override_settings(PAYPAL_MODE='sandbox', PAYPAL_CLIENT_ID='client', PAYPAL_CLIENT_SECRET='secret')
class PayPalPaymentsTests(TestCase):
    @patch('admin_panel.payments.requests.post')
    def test_get_paypal_access_token_success(self, post):
        post.return_value = PayPalResponse(200, {'access_token': 'token-123'})

        self.assertEqual(get_paypal_access_token(), 'token-123')
        self.assertIn('/v1/oauth2/token', post.call_args.args[0])

    @patch('admin_panel.payments.requests.post')
    def test_get_paypal_access_token_http_error(self, post):
        post.return_value = PayPalResponse(401, text='bad credentials')

        with self.assertRaises(PayPalError) as ctx:
            get_paypal_access_token()

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.response_text, 'bad credentials')

    @patch('admin_panel.payments.requests.post')
    def test_get_paypal_access_token_missing_token(self, post):
        post.return_value = PayPalResponse(200, {})

        with self.assertRaises(PayPalError):
            get_paypal_access_token()

    @patch('admin_panel.payments.requests.post')
    def test_create_paypal_order_payload_and_error(self, post):
        post.side_effect = [
            PayPalResponse(200, {'access_token': 'token-123'}),
            PayPalResponse(201, {'id': 'ORDER-1', 'links': [{'rel': 'approve', 'href': 'https://pay'}]}),
        ]

        order = create_paypal_order(
            amount=Decimal('12.50'),
            currency='EUR',
            reference_id='BANNER-10',
            description='Banner pubblicitario: Test',
            return_url='https://site/success/',
            cancel_url='https://site/cancel/',
        )

        self.assertEqual(order['id'], 'ORDER-1')
        payload = post.call_args_list[1].kwargs['json']
        self.assertEqual(payload['intent'], 'CAPTURE')
        self.assertEqual(payload['purchase_units'][0]['reference_id'], 'BANNER-10')
        self.assertEqual(payload['purchase_units'][0]['amount']['value'], '12.50')
        self.assertEqual(payload['application_context']['return_url'], 'https://site/success/')

        post.reset_mock()
        post.side_effect = [
            PayPalResponse(200, {'access_token': 'token-123'}),
            PayPalResponse(400, text='bad order'),
        ]
        with self.assertRaises(PayPalError) as ctx:
            create_paypal_order(
                amount=Decimal('1.00'),
                currency='EUR',
                description='Bad order',
                return_url='https://site/success/',
                cancel_url='https://site/cancel/',
            )
        self.assertEqual(ctx.exception.response_text, 'bad order')

    @patch('admin_panel.payments.requests.post')
    def test_capture_paypal_order_payload_and_error(self, post):
        post.side_effect = [
            PayPalResponse(200, {'access_token': 'token-123'}),
            PayPalResponse(201, {'status': 'COMPLETED'}),
        ]

        self.assertEqual(capture_paypal_order('ORDER-1')['status'], 'COMPLETED')
        self.assertIn('/v2/checkout/orders/ORDER-1/capture', post.call_args_list[1].args[0])

        post.reset_mock()
        post.side_effect = [
            PayPalResponse(200, {'access_token': 'token-123'}),
            PayPalResponse(422, text='cannot capture'),
        ]
        with self.assertRaises(PayPalError):
            capture_paypal_order('ORDER-1')


class PromoCodeTests(TestCase):
    def test_validate_promo_code_valid(self):
        promo = PromotionalCode.objects.create(
            code='SAVE10',
            description='Sconto',
            discount_type='fixed',
            discount_value=Decimal('10.00'),
            applies_to='banner',
        )

        result = validate_promo_code('SAVE10', context='banner', original_price=Decimal('30.00'))

        self.assertEqual(result['promo'], promo)
        self.assertEqual(result['discount_amount'], Decimal('10.00'))
        self.assertEqual(result['final_price'], Decimal('20.00'))

    def test_validate_promo_code_expired_missing_and_wrong_context(self):
        PromotionalCode.objects.create(
            code='OLD',
            description='Scaduto',
            discount_type='percentage',
            discount_value=Decimal('50.00'),
            applies_to='both',
            valid_until=timezone.now() - timedelta(days=1),
        )
        PromotionalCode.objects.create(
            code='PUB',
            description='Solo pubbliredazionale',
            discount_type='fixed',
            discount_value=Decimal('5.00'),
            applies_to='pubbliredazionale',
        )

        self.assertIsNone(validate_promo_code('OLD', context='banner', original_price=Decimal('30.00')))
        self.assertIsNone(validate_promo_code('MISSING', context='banner', original_price=Decimal('30.00')))
        self.assertIsNone(validate_promo_code('PUB', context='banner', original_price=Decimal('30.00')))


@override_settings(
    PAYPAL_CLIENT_ID='client',
    PAYPAL_CLIENT_SECRET='secret',
    SECURE_SSL_REDIRECT=False,
    DEBUG=True,
    ALLOWED_HOSTS=['testserver', 'localhost'],
    DEFAULT_FROM_EMAIL='noreply@example.com',
    ADMINS=(('Admin', 'admin@example.com'),),
    ADMIN_EMAIL='admin@example.com',
    SITE_URL='https://example.com',
)
class PaymentViewSmokeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mario', 'mario@example.com', 'password')
        self.client.force_login(self.user)

    def make_banner(self):
        return Banner.objects.create(
            user=self.user,
            title='Banner Test',
            link_url='https://example.com',
            alt_text='Alt',
            position='header',
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=7),
            duration_days=7,
            price_per_day=Decimal('2.00'),
        )

    def make_pubbliredazionale(self):
        return Articolo.objects.create(
            titolo='Pub Test',
            contenuto='Contenuto',
            categoria='Attualità',
            is_pubbliredazionale=True,
            pubbliredazionale_user=self.user,
            nome_azienda='Azienda',
            sito_web='https://azienda.example.com',
            interview_data={'done': True},
            payment_status='pending',
            total_price=Decimal('200.00'),
        )

    @patch('admin_panel.views.create_paypal_order')
    def test_banner_payment_calls_extracted_order_function_and_redirects(self, create_order):
        banner = self.make_banner()
        create_order.return_value = {
            'id': 'ORDER-BANNER',
            'links': [{'rel': 'approve', 'href': 'https://paypal.example/approve'}],
        }

        response = self.client.post(reverse('admin_panel:banner_payment', args=[banner.id]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://paypal.example/approve')
        create_order.assert_called_once()
        kwargs = create_order.call_args.kwargs
        self.assertEqual(kwargs['amount'], banner.total_price)
        self.assertEqual(kwargs['currency'], 'EUR')
        self.assertEqual(kwargs['reference_id'], f'BANNER-{banner.id}')
        self.assertEqual(kwargs['description'], f'Banner pubblicitario: {banner.title}')

    @patch('admin_panel.views.create_paypal_order')
    def test_pubbliredazionale_payment_calls_extracted_order_function_and_redirects(self, create_order):
        pub = self.make_pubbliredazionale()
        create_order.return_value = {
            'id': 'ORDER-PUB',
            'links': [{'rel': 'approve', 'href': 'https://paypal.example/pub-approve'}],
        }

        response = self.client.post(reverse('admin_panel:pubbliredazionale_payment', args=[pub.id]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://paypal.example/pub-approve')
        create_order.assert_called_once()
        kwargs = create_order.call_args.kwargs
        self.assertEqual(kwargs['amount'], pub.total_price)
        self.assertEqual(kwargs['currency'], 'EUR')
        self.assertEqual(kwargs['reference_id'], f'PUBBLIREDAZIONALE-{pub.id}')
        self.assertEqual(kwargs['description'], f'Articolo pubbliredazionale: {pub.nome_azienda}')
