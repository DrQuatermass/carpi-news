"""
Test di igiene SEO (settembre 2026): redirect www dietro proxy, robots.txt,
canonical dei filtri categoria, link "fonti" nofollow, JSON-LD homepage.
"""
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from home.middleware.security import SEOMiddleware
from home.models import Articolo


@override_settings(
    DEBUG=False,
    ALLOWED_HOSTS=["ombradelportico.it", "www.ombradelportico.it", "testserver"],
    USE_X_FORWARDED_HOST=True,
)
class SEOMiddlewareForwardedHostTests(SimpleTestCase):
    """Dietro Apache l'host reale arriva in X-Forwarded-Host: il redirect www deve scattare."""

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = SEOMiddleware(lambda request: HttpResponse("ok"))

    def test_www_in_forwarded_host_redirects_permanently_to_bare_domain(self):
        request = self.factory.get(
            "/articolo/esempio/?page=2",
            secure=True,
            HTTP_HOST="ombradelportico.it",
            HTTP_X_FORWARDED_HOST="www.ombradelportico.it",
        )

        response = self.middleware(request)

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://ombradelportico.it/articolo/esempio/?page=2")

    def test_bare_domain_passes_through(self):
        request = self.factory.get(
            "/articolo/esempio/",
            secure=True,
            HTTP_HOST="ombradelportico.it",
            HTTP_X_FORWARDED_HOST="ombradelportico.it",
        )

        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_www_in_host_header_still_redirects(self):
        request = self.factory.get("/", secure=True, HTTP_HOST="www.ombradelportico.it")

        response = self.middleware(request)

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://ombradelportico.it/")


@override_settings(
    DEBUG=True,  # il client di test usa http: con DEBUG=False il SEOMiddleware farebbe redirect a https
    ALLOWED_HOSTS=["testserver"],
    SITE_URL="https://testserver",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class CrawlHygieneTests(TestCase):
    def setUp(self):
        cache.clear()
        # niente thread in background (condivisione social, notifiche, IndexNow) durante i test
        with patch("home.signals.threading.Thread") as fake_thread, patch(
            "home.signals._notify_search_engines_background"
        ), patch("home.signals.send_article_approval_notification", return_value=True):
            fake_thread.return_value.start.return_value = None
            self.articolo = Articolo.objects.create(
                titolo="Articolo con fonte",
                slug="articolo-con-fonte",
                contenuto="<p>Contenuto</p>",
                sommario="Sommario",
                categoria="Cronaca",
                approvato=True,
                fonte="https://www.example.com/notizia",
                data_pubblicazione=timezone.now() - timedelta(minutes=1),
            )

    def test_robots_blocks_short_links_and_fonti_pages(self):
        response = self.client.get("/robots.txt")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Disallow: /s/", body)
        self.assertIn("Disallow: /articolo/*/fonti/", body)
        self.assertNotIn("Crawl-delay", body)
        # le regole valgono anche per il gruppo Googlebot-News
        news_group = body.split("User-agent: Googlebot-News", 1)[1]
        self.assertIn("Disallow: /s/", news_group)
        self.assertIn("Disallow: /articolo/*/fonti/", news_group)
        # le pagine pubbliche restano permesse
        self.assertIn("Allow: /articolo/", body)
        self.assertIn("Sitemap: https://ombradelportico.it/sitemap_index.xml", body)

    def test_category_query_filter_canonical_points_to_clean_category_url(self):
        response = self.client.get(reverse("home"), {"categoria": "Cronaca"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<link rel="canonical" href="https://testserver/categoria/cronaca/">')
        # resta noindex: e' la versione non canonica della pagina
        self.assertContains(response, 'name="robots" content="noindex, follow"')

    def test_unknown_category_query_filter_falls_back_to_homepage_canonical(self):
        response = self.client.get(reverse("home"), {"categoria": "NonEsiste"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<link rel="canonical" href="https://testserver/">')

    def test_fonti_link_is_nofollow(self):
        response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}))

        self.assertEqual(response.status_code, 200)
        fonti_url = reverse("fonti_articolo", kwargs={"slug": self.articolo.slug})
        self.assertContains(response, f'href="{fonti_url}" class="sources-button" rel="nofollow"')

    def test_homepage_json_ld_has_no_search_action(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "SearchAction")
        self.assertNotContains(response, "search_term_string")
        self.assertContains(response, '"@type": "WebSite"')
