"""
Test del contatore letture via beacon (settembre 2026): niente conteggio lato server,
beacon cookieless con dedup in cache e filtro crawler, comando di ricalibrazione,
banner cookie e Consent Mode.
"""
import csv
import tempfile
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from home.models import Articolo


@override_settings(
    DEBUG=True,
    ALLOWED_HOSTS=["testserver"],
    SITE_URL="https://testserver",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class ArticleViewBeaconTests(TestCase):
    def setUp(self):
        cache.clear()
        with patch("home.signals.threading.Thread") as fake_thread, patch(
            "home.signals._notify_search_engines_background"
        ), patch("home.signals.send_article_approval_notification", return_value=True):
            fake_thread.return_value.start.return_value = None
            self.articolo = Articolo.objects.create(
                titolo="Articolo beacon",
                slug="articolo-beacon",
                contenuto="<p>Contenuto</p>",
                sommario="Sommario",
                categoria="Cronaca",
                approvato=True,
                data_pubblicazione=timezone.now() - timedelta(minutes=1),
            )
        self.url = reverse("article_view_beacon", kwargs={"articolo_id": self.articolo.id})
        self.human_ua = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36"

    def _views(self):
        self.articolo.refresh_from_db()
        return self.articolo.views

    def test_page_render_does_not_increment_views_nor_create_session(self):
        response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}), HTTP_USER_AGENT=self.human_ua)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._views(), 0)
        self.assertNotIn("sessionid", response.cookies)
        # il beacon e' nella pagina
        self.assertContains(response, self.url)
        self.assertContains(response, "navigator.sendBeacon")

    def test_beacon_counts_once_per_visitor_within_window(self):
        for _ in range(3):
            response = self.client.post(self.url, HTTP_USER_AGENT=self.human_ua, REMOTE_ADDR="10.0.0.1")
            self.assertEqual(response.status_code, 204)
        self.assertEqual(self._views(), 1)

        # un altro visitatore (altro IP) conta
        self.client.post(self.url, HTTP_USER_AGENT=self.human_ua, REMOTE_ADDR="10.0.0.2")
        self.assertEqual(self._views(), 2)

    def test_beacon_uses_forwarded_ip_behind_proxy(self):
        self.client.post(self.url, HTTP_USER_AGENT=self.human_ua, REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="93.1.1.1, 127.0.0.1")
        self.client.post(self.url, HTTP_USER_AGENT=self.human_ua, REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="93.1.1.2, 127.0.0.1")
        self.client.post(self.url, HTTP_USER_AGENT=self.human_ua, REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="93.1.1.2, 127.0.0.1")
        self.assertEqual(self._views(), 2)

    def test_beacon_ignores_crawlers_including_facebook(self):
        for ua in (
            "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
            "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            "WhatsApp/2.23.20.0",
            "",
        ):
            response = self.client.post(self.url, HTTP_USER_AGENT=ua, REMOTE_ADDR="10.0.0.9")
            self.assertEqual(response.status_code, 204)
        self.assertEqual(self._views(), 0)

    def test_beacon_requires_post_and_ignores_unapproved(self):
        self.assertEqual(self.client.get(self.url, HTTP_USER_AGENT=self.human_ua).status_code, 405)
        Articolo.objects.filter(pk=self.articolo.pk).update(approvato=False)
        self.client.post(self.url, HTTP_USER_AGENT=self.human_ua, REMOTE_ADDR="10.0.0.3")
        self.assertEqual(self._views(), 0)

    def test_beacon_and_impression_endpoints_are_blocked_in_robots(self):
        body = self.client.get("/robots.txt").content.decode()
        self.assertIn("Disallow: /beacon/", body)
        self.assertIn("Disallow: /banner/impression/", body)

    def test_ricalibra_views_uses_log_csv_and_divisor(self):
        with patch("home.signals.threading.Thread") as fake_thread, patch(
            "home.signals._notify_search_engines_background"
        ), patch("home.signals.send_article_approval_notification", return_value=True):
            fake_thread.return_value.start.return_value = None
            vecchio = Articolo.objects.create(
                titolo="Articolo vecchio", slug="articolo-vecchio", contenuto="<p>x</p>", sommario="s",
                categoria="Cronaca", approvato=True, data_pubblicazione=timezone.now() - timedelta(days=200),
            )
        Articolo.objects.filter(pk=self.articolo.pk).update(views=1370)
        Articolo.objects.filter(pk=vecchio.pk).update(views=1370)
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/views_umane.csv"
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["slug", "views_umane"])
                w.writerow([self.articolo.slug, 42])
            out = StringIO()
            call_command("ricalibra_views", csv=path, divisore=13.7, dry_run=True, stdout=out)
            self.assertEqual(Articolo.objects.get(pk=self.articolo.pk).views, 1370)  # dry-run non tocca
            call_command("ricalibra_views", csv=path, divisore=13.7, stdout=out)
            self.assertEqual(Articolo.objects.get(pk=self.articolo.pk).views, 42)
            self.assertEqual(Articolo.objects.get(pk=vecchio.pk).views, 100)
            with open(f"{tmp}/views_precedente.csv", encoding="utf-8") as f:
                backup = list(csv.DictReader(f))
            self.assertEqual({r["slug"]: r["views_prima"] for r in backup}[vecchio.slug], "1370")

    def test_cookie_banner_text_and_consent_mode(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Continuando la navigazione accetti")
        self.assertContains(response, 'id="cookie-preferences"')
        self.assertContains(response, "gtag('consent', 'default'")
        self.assertContains(response, "analytics_storage: 'denied'")
        self.assertContains(response, "window.grantGoogleConsent")
