from unittest.mock import Mock, patch
from io import BytesIO, StringIO
import hashlib
import hmac
import requests
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.management import call_command
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.http import Http404
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User
from PIL import Image

from admin_panel.models import Banner
from home.context_processors import categorie_menu
from home.content_polisher import content_polisher
from home.image_variants import ensure_article_image_variants, generate_article_image_variants, get_article_source_image_path
from home.management.commands.process_pending_pubbliredazionali import Command as ProcessPendingPubbliredazionaliCommand
from home.management.commands.retry_failed_social_shares import Command as RetryFailedSocialSharesCommand
from home.models import Articolo, InstagramOptOut, MonitorConfig, ShortLink, SocialPublicationLog
from home.seo_locations import detect_municipality
from home.share_links import build_share_url, build_short_share_url
from home.social_sharing import SocialMediaManager
from home.rielaborazione_ai import rielabora_articolo
from home.universal_news_monitor import SiteConfig, UniversalNewsMonitor, YouTubeAPIScraper, parse_ai_article_json
from home.web_search_tool import WebSearchTool
from home.views import custom_404


class YouTubeScraperExclusionTests(SimpleTestCase):
    def test_fallback_video_ids_skip_excluded_videos(self):
        config = SiteConfig(
            name="YouTube Test",
            base_url="https://www.youtube.com/",
            scraper_type="youtube_api",
            fallback_video_ids=["skipme", "keepme"],
            excluded_video_ids=["skipme"],
        )
        scraper = YouTubeAPIScraper(config, {})

        articles = scraper._scrape_from_fallback_ids()

        self.assertEqual([article["video_id"] for article in articles], ["keepme"])


class TrascrizioniLungheTests(TestCase):
    URL_VIDEO = "https://www.youtube.com/watch?v=abc-123"

    def _genera(self, url, contenuto):
        """Genera con Claude finto e ritorna i parametri della chiamata."""
        config = SiteConfig(name="Test", base_url="https://www.youtube.com/", scraper_type="html",
                            ai_api_key="x", ai_provider="anthropic", enable_web_search=False)
        risposta = Mock(stop_reason="end_turn", usage=Mock(input_tokens=1, output_tokens=1))
        risposta.content = [Mock(type="text", text=json.dumps({
            "titolo": "Titolo", "titolo_seo": "", "sommario": "S", "contenuto": "<p>Testo</p>",
            "tags": ["Carpi"], "spunto_social": "",
        }))]
        with patch("anthropic.Anthropic") as anthropic:
            anthropic.return_value.messages.create.return_value = risposta
            UniversalNewsMonitor(config).generate_ai_article({
                "title": "Seduta", "url": url, "full_content": contenuto,
            })
        return anthropic.return_value.messages.create.call_args.kwargs

    def test_video_arriva_intero_con_le_regole_di_copertura(self):
        parametri = self._genera(self.URL_VIDEO, "x" * 250000 + "FINE SEDUTA")

        self.assertIn("FINE SEDUTA", parametri["messages"][0]["content"])
        self.assertIn("COPERTURA DELLA TRASCRIZIONE", parametri["system"])
        self.assertEqual(parametri["max_tokens"], 16000)

    def test_altre_fonti_restano_al_limite_normale(self):
        parametri = self._genera("https://example.com/notizia", "x" * 25000 + "FINE")

        self.assertNotIn("FINE", parametri["messages"][0]["content"])
        self.assertNotIn("COPERTURA DELLA TRASCRIZIONE", parametri["system"])
        self.assertEqual(parametri["max_tokens"], 8192)

    def test_prompt_comune_prima_della_nota_del_monitor(self):
        from home.prompt_redazione import NOTE_FONTE, PROMPT_BASE

        parametri = self._genera("https://example.com/notizia", "testo")
        system = parametri["system"]

        # Senza ai_system_prompt: prompt comune + nota "altra testata" + regole del codice
        self.assertTrue(system.startswith(PROMPT_BASE))
        self.assertIn(NOTE_FONTE['testata'].strip(), system)
        self.assertLess(system.index(PROMPT_BASE), system.index("FEDELTA' ALLA FONTE"))
        self.assertIn("FORMATO DELLA RISPOSTA", system)
        self.assertNotIn("giudizio pragmatico", system)

    def _rielabora(self, trascrizione, fonte=URL_VIDEO):
        articolo = Articolo.objects.create(titolo="Seduta", contenuto="<p>Articolo gia' scritto</p>", fonte=fonte)
        with patch.object(YouTubeAPIScraper, "get_video_transcript", return_value=trascrizione) as scarica, \
                patch.object(UniversalNewsMonitor, "generate_ai_article", return_value="ok") as genera:
            rielabora_articolo(articolo.id)
        return scarica, genera.call_args.args[0]["full_content"]

    def test_rielaborazione_di_un_video_riparte_dalla_trascrizione(self):
        scarica, testo = self._rielabora("trascrizione completa")

        scarica.assert_called_once_with("abc-123")
        self.assertEqual(testo, "trascrizione completa")

    def test_senza_trascrizione_usa_il_testo_salvato(self):
        _, testo = self._rielabora(None)

        self.assertIn("Articolo gia' scritto", testo)

    def test_altre_fonti_non_scaricano_nulla(self):
        scarica, testo = self._rielabora("mai", fonte="https://example.com/notizia")

        scarica.assert_not_called()
        self.assertIn("Articolo gia' scritto", testo)


class WebSearchToolPdfTests(SimpleTestCase):
    def test_response_looks_like_pdf_with_weak_server_headers(self):
        tool = WebSearchTool()

        response = Mock()
        response.headers = {"Content-Type": "text/html"}
        response.url = "https://example.com/download"
        response.content = b"%PDF-1.7\n..."

        self.assertTrue(tool._response_looks_like_pdf(response, "https://example.com/download"))

    def test_response_looks_like_pdf_from_redirected_pdf_url(self):
        tool = WebSearchTool()

        response = Mock()
        response.headers = {"Content-Type": "application/octet-stream"}
        response.url = "https://example.com/files/document.pdf?download=1"
        response.content = b""

        self.assertTrue(tool._response_looks_like_pdf(response, "https://example.com/download"))


class AIArticleParsingTests(SimpleTestCase):
    def test_parse_loose_json_with_multiline_content_and_quotes(self):
        response = '''{
  "titolo": "Borse di studio ER.GO, copertura totale",
  "sommario": "Tutti gli studenti idonei riceveranno la borsa di studio.",
  "contenuto": "
Tutti gli studenti idonei riceveranno la borsa.

De Lillo: "Una vittoria collettiva, non un caso"

Il risultato arriva dopo mesi di tensione.
",
  "tags": ["Diritto allo studio", "ER.GO"]
}'''

        parsed = parse_ai_article_json(response)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["titolo"], "Borse di studio ER.GO, copertura totale")
        self.assertEqual(parsed["sommario"], "Tutti gli studenti idonei riceveranno la borsa di studio.")
        self.assertIn('De Lillo: "Una vittoria collettiva, non un caso"', parsed["contenuto"])
        self.assertEqual(parsed["tags"], ["Diritto allo studio", "ER.GO"])

    def test_polisher_converts_literal_escaped_newlines(self):
        with patch.object(content_polisher, "add_internal_links", side_effect=lambda content, **kwargs: content):
            polished = content_polisher.polish_article({
                "titolo": "Titolo prova",
                "contenuto": "Primo paragrafo.\\n\\nSottotitolo\\n\\nSecondo paragrafo.",
                "sommario": "Riga uno.\\n\\nRiga due.",
            })

        self.assertIn("<p>Primo paragrafo.</p>", polished["contenuto"])
        self.assertIn("<p>Secondo paragrafo.</p>", polished["contenuto"])
        self.assertNotIn("\\n", polished["contenuto"])
        self.assertNotIn("\\n", polished["sommario"])


@override_settings(
    DEBUG=False,
    ALLOWED_HOSTS=["testserver"],
    SECURE_SSL_REDIRECT=False,
    SITE_URL="https://testserver",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class ErrorPageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        Articolo.objects.bulk_create([
            Articolo(
                titolo=f"Articolo recente {index}",
                slug=f"articolo-recente-{index}",
                contenuto="Contenuto",
                sommario="Sommario",
                categoria="Cronaca",
                approvato=True,
                data_pubblicazione=timezone.now() - timedelta(minutes=index),
            )
            for index in range(6)
        ])

    def test_missing_article_uses_custom_404_template(self):
        response = self.client.get("/articolo/slug-inesistente/", secure=True)

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Pagina non trovata", status_code=404)
        self.assertContains(response, '<meta name="robots" content="noindex">', status_code=404)
        self.assertContains(response, "Articoli recenti", status_code=404)

    def test_custom_404_recent_articles_query_budget(self):
        request = self.factory.get("/pagina-inesistente/")

        with self.assertNumQueries(1):
            response = custom_404(request, Http404("Pagina non trovata"))

        self.assertEqual(response.status_code, 404)
        self.assertIn(b"Pagina non trovata", response.content)
        self.assertIn(b"Articolo recente", response.content)

        request = self.factory.get("/altra-pagina-inesistente/")
        with self.assertNumQueries(0):
            response = custom_404(request, Http404("Pagina non trovata"))

        self.assertEqual(response.status_code, 404)
        self.assertIn(b"Pagina non trovata", response.content)

    def test_500_template_is_static_and_does_not_touch_database(self):
        with self.assertNumQueries(0):
            html = render_to_string("500.html")

        self.assertIn("Qualcosa non ha funzionato", html)
        self.assertIn('href="/"', html)


@override_settings(
    DEBUG=True,
    SITE_URL="https://testserver",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class ShareLinkTests(TestCase):
    def setUp(self):
        cache.clear()
        self.articolo = Articolo.objects.create(
            titolo="Titolo test",
            contenuto="Contenuto",
            sommario="Sommario",
            categoria="Cronaca",
            approvato=True,
            data_pubblicazione=timezone.now(),
        )

    def test_build_share_url(self):
        url = build_share_url(self.articolo, "instagram", "reel")
        self.assertIn("/articolo/", url)
        self.assertIn("utm_source=instagram", url)
        self.assertIn("utm_medium=reel", url)
        self.assertIn("utm_campaign=share", url)

    def test_home_response_does_not_vary_on_cookie_or_create_session(self):
        cache.clear()

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Cookie", response.get("Vary", ""))
        self.assertNotIn("sessionid", response.cookies)

    def test_banner_impression_beacon_counts_atomically_and_deduplicates(self):
        user = User.objects.create_user(username="banner-user", password="x")
        banner = Banner.objects.create(
            user=user,
            title="Banner test",
            link_url="https://example.com",
            alt_text="Banner test",
            position="between_articles",
            priority=3,
            duration_days=30,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=30),
            status="active",
            payment_status="completed",
            approved=True,
        )
        url = reverse("banner_impression", kwargs={"banner_id": banner.pk})
        cache.clear()

        response = self.client.post(url, HTTP_USER_AGENT="Mozilla/5.0", REMOTE_ADDR="203.0.113.10")
        self.assertEqual(response.status_code, 204)
        banner.refresh_from_db()
        self.assertEqual(banner.impressions, 1)

        response = self.client.post(url, HTTP_USER_AGENT="Mozilla/5.0", REMOTE_ADDR="203.0.113.10")
        self.assertEqual(response.status_code, 204)
        banner.refresh_from_db()
        self.assertEqual(banner.impressions, 1)

        cache.clear()
        Banner.objects.filter(pk=banner.pk).update(impressions=0)
        response = self.client.post(url, HTTP_USER_AGENT="Googlebot", REMOTE_ADDR="203.0.113.10")
        self.assertEqual(response.status_code, 204)
        banner.refresh_from_db()
        self.assertEqual(banner.impressions, 0)

        response = self.client.post(reverse("banner_impression", kwargs={"banner_id": 999999}))
        self.assertEqual(response.status_code, 204)

    def test_banner_click_counts_only_after_impression_or_from_newsletter(self):
        user = User.objects.create_user(username="banner-click", password="x")
        banner = Banner.objects.create(
            user=user,
            title="Banner clic",
            link_url="https://example.com",
            alt_text="Banner clic",
            position="between_articles",
            priority=3,
            duration_days=30,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=30),
            status="active",
            payment_status="completed",
            approved=True,
        )
        click = reverse("admin_panel:banner_click", kwargs={"banner_id": banner.pk})
        impr = reverse("banner_impression", kwargs={"banner_id": banner.pk})
        persona = {"HTTP_USER_AGENT": "Mozilla/5.0 Chrome/156", "REMOTE_ADDR": "203.0.113.20"}
        cache.clear()

        def clicks():
            banner.refresh_from_db()
            return banner.clicks

        # Bot che apre il link senza aver caricato la pagina: redirect, nessun clic
        response = self.client.get(click, HTTP_USER_AGENT="Mozilla/5.0 Chrome/136", REMOTE_ADDR="198.51.100.7")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://example.com")
        self.assertEqual(clicks(), 0)

        # Visitatore che ha visto il banner: il clic conta, il doppio clic no
        self.client.post(impr, **persona)
        self.client.get(click, **persona)
        self.assertEqual(clicks(), 1)
        self.client.get(click, **persona)
        self.assertEqual(clicks(), 1)

        # Stesso IP ma browser diverso: non ha visto il banner
        self.client.get(click, HTTP_USER_AGENT="Altro browser", REMOTE_ADDR="203.0.113.20")
        self.assertEqual(clicks(), 1)

        # Newsletter: conta una volta per visitatore, mai per i bot
        self.client.get(click + "?src=newsletter", HTTP_USER_AGENT="Mozilla/5.0 Mail", REMOTE_ADDR="192.0.2.5")
        self.client.get(click + "?src=newsletter", HTTP_USER_AGENT="Mozilla/5.0 Mail", REMOTE_ADDR="192.0.2.5")
        self.client.get(click + "?src=newsletter", HTTP_USER_AGENT="Googlebot", REMOTE_ADDR="192.0.2.6")
        self.assertEqual(clicks(), 2)

    def test_categorie_menu_context_processor_uses_cache_and_invalidates_on_article_save(self):
        cache.clear()

        with self.assertNumQueries(1):
            first = categorie_menu(None)["categorie_disponibili"]
        self.assertIn("Cronaca", first)

        with self.assertNumQueries(0):
            second = categorie_menu(None)["categorie_disponibili"]
        self.assertEqual(first, second)

        Articolo.objects.create(
            titolo="Categoria politica",
            contenuto="Contenuto",
            sommario="Sommario",
            categoria="Politica",
            approvato=True,
            data_pubblicazione=timezone.now(),
        )
        self.assertIsNone(cache.get("categorie_menu"))

    def test_home_query_budget_after_menu_cache(self):
        cache.clear()
        categorie_menu(None)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 12)

    def test_pubblicita_ctr_max_matches_python_calculation(self):
        user = User.objects.create_user(username="ctr-user", password="x")
        now = timezone.now()
        for title, impressions, clicks in [
            ("Basso", 100, 5),
            ("Alto", 80, 20),
            ("Zero impressioni", 0, 50),
            ("Zero click", 100, 0),
        ]:
            Banner.objects.create(
                user=user,
                title=title,
                link_url="https://example.com",
                alt_text=title,
                position="header",
                priority=3,
                duration_days=30,
                start_date=now - timedelta(days=1),
                end_date=now + timedelta(days=30),
                status="active",
                payment_status="completed",
                approved=True,
                impressions=impressions,
                clicks=clicks,
            )

        response = self.client.get(reverse("pubblicita"))

        expected = max(round((20 / 80) * 100, 1), round((5 / 100) * 100, 1))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ctr_max"], expected)

    def test_cinema_scraping_parallel_uses_stale_for_failed_cinema(self):
        import time
        from home.views import _scrape_cinema_parallel

        def slow_payload(name):
            time.sleep(0.2)
            return {
                "name": name,
                "address": "Indirizzo",
                "website": "https://example.com",
                "films": [{"title": f"{name} nuovo", "image": "", "info": "Oggi"}],
            }

        def slow_failure():
            time.sleep(0.2)
            raise TimeoutError("timeout")

        stale_ariston = {
            "name": "Cinema Ariston",
            "address": "Via Ernesto Boccaletti 3, San Marino di Carpi",
            "website": "https://www.aristoncinemacarpi.it/",
            "films": [{"title": "Film stale", "image": "", "info": "Oggi"}],
        }

        started = time.perf_counter()
        with patch("home.cinema_scraping.scrape_spacecity", side_effect=lambda: slow_payload("Space City Multisala")), \
             patch("home.cinema_scraping.scrape_eden", side_effect=lambda: slow_payload("Cinema Eden")), \
             patch("home.cinema_scraping.scrape_ariston", side_effect=slow_failure), \
             patch("home.cinema_scraping.scrape_corso", side_effect=lambda: slow_payload("Cinema Corso")):
            cinema_data = _scrape_cinema_parallel(stale_by_name={"Cinema Ariston": stale_ariston})
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.55)
        ariston = next(cinema for cinema in cinema_data if cinema["name"] == "Cinema Ariston")
        self.assertEqual(ariston["films"][0]["title"], "Film stale")

    def test_short_link_and_redirect_tracking(self):
        short_url = build_short_share_url(self.articolo, "instagram", "bio")
        short_link = ShortLink.objects.get(articolo=self.articolo, platform="instagram", medium="bio")
        self.assertIn(f"/s/{short_link.token}/", short_url)

        response = self.client.get(reverse("short_link_redirect", kwargs={"token": short_link.token}))
        self.assertEqual(response.status_code, 302)
        self.assertIn("utm_source=instagram", response["Location"])
        short_link.refresh_from_db()
        self.assertEqual(short_link.clicks_count, 1)

    def test_clean_category_url_has_canonical_and_no_noindex(self):
        self.articolo.categoria = "Sport"
        self.articolo.save(update_fields=["categoria"])

        response = self.client.get(reverse("categoria_articoli", kwargs={"categoria_slug": "sport"}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<link rel="canonical" href="https://testserver/categoria/sport/">')
        self.assertNotContains(response, 'name="robots" content="noindex, follow"')

    def test_clean_category_url_keeps_page_in_canonical(self):
        self.articolo.categoria = "Sport"
        self.articolo.save(update_fields=["categoria"])
        for index in range(9):
            Articolo.objects.create(
                titolo=f"Sport {index}",
                contenuto="Contenuto",
                sommario="Sommario",
                categoria="Sport",
                approvato=True,
                data_pubblicazione=timezone.now() - timedelta(minutes=index + 1),
            )

        response = self.client.get(reverse("categoria_articoli", kwargs={"categoria_slug": "sport"}), {"page": "2"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<link rel="canonical" href="https://testserver/categoria/sport/?page=2">')

    def test_cached_article_detail_revalidates_pubbliredazionale_status(self):
        self.articolo.is_pubbliredazionale = True
        self.articolo.payment_status = "completed"
        self.articolo.save(update_fields=["is_pubbliredazionale", "payment_status"])

        response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(cache.get(f"articolo_ctx_{self.articolo.slug}"))

        Articolo.objects.filter(pk=self.articolo.pk).update(payment_status="pending")
        response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}))

        self.assertEqual(response.status_code, 404)
        self.assertIsNone(cache.get(f"articolo_ctx_{self.articolo.slug}"))

    def test_article_detail_title_tag_uses_seo_title(self):
        """Il <title> usa titolo_seo; H1, social e schema restano sull'headline editoriale."""
        self.articolo.titolo = "Headline editoriale unica"
        self.articolo.titolo_seo = "Titolo SEO diverso"
        self.articolo.save(update_fields=["titolo", "titolo_seo"])
        cache.delete(f"articolo_ctx_{self.articolo.slug}")

        response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Titolo SEO diverso — Ombra del Portico</title>")
        self.assertContains(response, '<meta property="og:title" content="Headline editoriale unica">')
        self.assertContains(response, '<meta name="twitter:title" content="Headline editoriale unica">')
        self.assertContains(response, '<h1 class="article-title">Headline editoriale unica</h1>')
        self.assertContains(response, '"headline": "Headline editoriale unica"')

    def test_article_detail_title_tag_falls_back_to_titolo(self):
        """Senza titolo_seo il <title> usa il titolo editoriale."""
        self.articolo.titolo = "Headline editoriale unica"
        self.articolo.titolo_seo = ""
        self.articolo.save(update_fields=["titolo", "titolo_seo"])
        cache.delete(f"articolo_ctx_{self.articolo.slug}")

        response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Headline editoriale unica — Ombra del Portico</title>")

    def test_audit_headlines_outputs_articles_over_limit(self):
        long_title = "Titolo molto lungo " + ("x" * 90)
        with self.assertWarns(RuntimeWarning):
            article = Articolo.objects.create(
                titolo=long_title,
                contenuto="Contenuto",
                sommario="Sommario",
                categoria="Cronaca",
                approvato=True,
                data_pubblicazione=timezone.now(),
            )

        out = StringIO()
        call_command("audit_headlines", stdout=out)

        output = out.getvalue()
        self.assertIn(article.slug, output)
        self.assertIn(str(len(long_title)), output)
        self.assertIn(long_title, output)

    def test_newsarticle_uses_three_image_variants_when_available(self):
        self.articolo.image_16x9 = "images/articles/titolo-test-16x9.webp"
        self.articolo.image_4x3 = "images/articles/titolo-test-4x3.webp"
        self.articolo.image_1x1 = "images/articles/titolo-test-1x1.webp"
        self.articolo.save(update_fields=["image_16x9", "image_4x3", "image_1x1"])
        cache.delete(f"articolo_ctx_{self.articolo.slug}")

        response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<meta property="og:image" content="https://testserver/media/images/articles/titolo-test-16x9.webp">')
        self.assertContains(response, '<meta name="twitter:image" content="https://testserver/media/images/articles/titolo-test-16x9.webp">')
        self.assertContains(
            response,
            '"image": ["https://testserver/media/images/articles/titolo-test-16x9.webp", "https://testserver/media/images/articles/titolo-test-4x3.webp", "https://testserver/media/images/articles/titolo-test-1x1.webp"]',
        )

    def test_article_detail_renders_minor_social_meta_and_facebook_share_without_quote(self):
        self.articolo.image_16x9 = "images/articles/titolo-test-16x9.webp"
        self.articolo.save(update_fields=["image_16x9"])
        cache.delete(f"articolo_ctx_{self.articolo.slug}")

        with override_settings(FACEBOOK_APP_ID="123456789"):
            response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<html lang="it" prefix="og: https://ogp.me/ns# fb: https://ogp.me/ns/fb#">')
        self.assertContains(response, '<meta name="theme-color" content="#966C42">')
        self.assertContains(
            response,
            '<meta property="og:image:secure_url" content="https://testserver/media/images/articles/titolo-test-16x9.webp">',
        )
        self.assertContains(response, '<meta property="og:image:width" content="1200">')
        self.assertContains(response, '<meta property="og:image:height" content="675">')
        self.assertContains(response, '<meta property="fb:app_id" content="123456789">')
        self.assertContains(response, '<meta name="twitter:creator" content="@ombradelportico">')
        self.assertContains(response, "https://www.facebook.com/sharer/sharer.php?u=")
        self.assertNotContains(response, "&quote=")

    def test_caplet_facebook_share_without_quote(self):
        response = self.client.get(reverse("caplet"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://www.facebook.com/sharer/sharer.php?u=")
        self.assertNotContains(response, "&quote=")

    def test_generate_article_image_variants_creates_expected_sizes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images"
            source_dir.mkdir()
            source_path = source_dir / "source.jpg"
            Image.new("RGB", (1600, 1000), (180, 40, 40)).save(source_path, "JPEG")

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"):
                self.articolo.foto = "/media/images/source.jpg"
                created = generate_article_image_variants(self.articolo, force=True)
                self.articolo.refresh_from_db()

                self.assertEqual(set(created), {"image_16x9", "image_4x3", "image_1x1"})
                expected = {
                    "image_16x9": (1200, 675),
                    "image_4x3": (1200, 900),
                    "image_1x1": (1200, 1200),
                }
                for field_name, size in expected.items():
                    image_path = media_root / getattr(self.articolo, field_name).name
                    self.assertTrue(image_path.exists())
                    with Image.open(image_path) as img:
                        self.assertEqual(img.size, size)

    def test_generate_article_image_variants_keeps_field_paths_within_db_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images"
            source_dir.mkdir()
            source_path = source_dir / "source.jpg"
            Image.new("RGB", (1600, 1000), (180, 40, 40)).save(source_path, "JPEG")

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"):
                self.articolo.slug = "slug-" + ("molto-lungo-" * 10)
                self.articolo.foto = "/media/images/source.jpg"
                created = generate_article_image_variants(self.articolo, force=True)
                self.articolo.refresh_from_db()

                self.assertEqual(set(created), {"image_16x9", "image_4x3", "image_1x1"})
                self.assertLessEqual(len(self.articolo.image_16x9.name), 180)

    def test_regenerate_article_images_command_processes_existing_article(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images"
            source_dir.mkdir()
            source_path = source_dir / "source.jpg"
            Image.new("RGB", (1600, 1000), (40, 120, 180)).save(source_path, "JPEG")

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"):
                Articolo.objects.filter(pk=self.articolo.pk).update(foto="/media/images/source.jpg")
                self.articolo.foto = "/media/images/source.jpg"
                out = StringIO()

                call_command("regenerate_article_images", stdout=out)
                self.articolo.refresh_from_db()

                self.assertIn("Articoli aggiornati: 1", out.getvalue())
                self.assertEqual(self.articolo.image_16x9.name, "images/articles/titolo-test-16x9.webp")

    def test_newsarticle_image_urls_falls_back_without_lazy_generating_variants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images" / "uploaded"
            source_dir.mkdir(parents=True)
            source_path = source_dir / "titolo-test-original.webp"
            Image.new("RGB", (1600, 1000), (80, 120, 160)).save(source_path, "WebP")

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"):
                Articolo.objects.filter(pk=self.articolo.pk).update(
                    foto_upload="images/uploaded/titolo-test-original.webp",
                    image_16x9="",
                    image_4x3="",
                    image_1x1="",
                )
                self.articolo.refresh_from_db()

                urls = self.articolo.get_newsarticle_image_urls()
                self.articolo.refresh_from_db()

                self.assertEqual(urls, ["https://testserver/media/images/uploaded/titolo-test-original.webp"])
                self.assertFalse(self.articolo.image_16x9)
                self.assertFalse((media_root / "images" / "articles").exists())

    def test_social_image_url_uses_upload_without_lazy_generating_variants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images" / "uploaded"
            source_dir.mkdir(parents=True)
            source_path = source_dir / "titolo-test-original.webp"
            Image.new("RGB", (1600, 1000), (80, 120, 160)).save(source_path, "WebP")

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"):
                Articolo.objects.filter(pk=self.articolo.pk).update(
                    foto_upload="images/uploaded/titolo-test-original.webp",
                    image_16x9="",
                    image_4x3="",
                    image_1x1="",
                )
                self.articolo.refresh_from_db()

                image_url = self.articolo.get_social_image_url()
                self.articolo.refresh_from_db()

                self.assertEqual(image_url, "https://testserver/media/images/uploaded/titolo-test-original.webp")
                self.assertFalse(self.articolo.image_16x9)

    def test_image_url_methods_are_pure_string_builders(self):
        cases = [
            (
                Articolo(titolo="Esterna valida", contenuto="x", foto="https://example.com/img//foto con spazio.jpg", foto_valida=True),
                "https://example.com/img/foto%20con%20spazio.jpg",
                "https://example.com/img/foto%20con%20spazio.jpg",
            ),
            (
                Articolo(titolo="Esterna rotta", contenuto="x", foto="https://example.com/broken.jpg", foto_valida=False),
                "/static/home/images/portico_logo_nopayoff.webp",
                "https://testserver/static/home/images/portico_logo_nopayoff.png",
            ),
            (
                Articolo(titolo="Locale", contenuto="x", foto="/media/images/local.jpg", foto_valida=True),
                "https://testserver/media/images/local.jpg",
                "https://testserver/media/images/local.jpg",
            ),
            (
                Articolo(titolo="Senza foto", contenuto="x", foto="", foto_valida=True),
                "/static/home/images/portico_logo_nopayoff.webp",
                "https://testserver/static/home/images/portico_logo_nopayoff.png",
            ),
        ]

        with patch("home.image_validation.requests.head") as head_mock, patch("pathlib.Path.exists") as exists_mock:
            for articolo, expected_image, expected_social in cases:
                self.assertEqual(articolo.get_image_url(), expected_image)
                self.assertEqual(articolo.get_image_url(), expected_image)
                self.assertEqual(articolo.get_social_image_url(), expected_social)
                self.assertEqual(articolo.get_social_image_url(), expected_social)

        head_mock.assert_not_called()
        exists_mock.assert_not_called()

    def test_homepage_and_detail_render_do_not_validate_images(self):
        Articolo.objects.filter(pk=self.articolo.pk).update(
            foto="https://example.com/render//foto con spazio.jpg",
            foto_valida=True,
            image_16x9="",
            image_4x3="",
            image_1x1="",
        )
        cache.clear()

        with patch("home.image_validation.requests.head") as head_mock, patch("pathlib.Path.exists") as exists_mock:
            home_response = self.client.get(reverse("home"))
            detail_response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}))

        self.assertEqual(home_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        head_mock.assert_not_called()
        exists_mock.assert_not_called()

    def test_ensure_article_image_variants_downloads_remote_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            image_buffer = BytesIO()
            Image.new("RGB", (1600, 1000), (80, 120, 160)).save(image_buffer, "JPEG")
            response = Mock()
            response.headers = {"content-type": "image/jpeg"}
            response.content = image_buffer.getvalue()
            response.raise_for_status.return_value = None

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"), patch(
                "home.image_variants.requests.get", return_value=response
            ):
                Articolo.objects.filter(pk=self.articolo.pk).update(
                    foto="https://example.com/source.jpg",
                    image_16x9="",
                    image_4x3="",
                    image_1x1="",
                )
                self.articolo.refresh_from_db()

                created = ensure_article_image_variants(self.articolo)
                self.articolo.refresh_from_db()

                self.assertEqual(set(created), {"image_16x9", "image_4x3", "image_1x1"})
                self.assertEqual(self.articolo.foto, "/media/images/downloaded/titolo-test-original.webp")
                self.assertTrue((media_root / "images" / "downloaded" / "titolo-test-original.webp").exists())
                self.assertTrue((media_root / self.articolo.image_16x9.name).exists())

    def test_ensure_article_image_variants_skips_unapproved_article(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images"
            source_dir.mkdir()
            source_path = source_dir / "source.jpg"
            Image.new("RGB", (1600, 1000), (180, 40, 40)).save(source_path, "JPEG")

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"):
                articolo = Articolo.objects.create(
                    titolo="Bozza con immagine",
                    contenuto="Contenuto",
                    sommario="Sommario",
                    categoria="Cronaca",
                    foto="/media/images/source.jpg",
                    approvato=False,
                    data_pubblicazione=timezone.now(),
                )

                created = ensure_article_image_variants(articolo, force=True)
                articolo.refresh_from_db()

                self.assertEqual(created, {})
                self.assertFalse(articolo.image_16x9)
                self.assertFalse(articolo.image_4x3)
                self.assertFalse(articolo.image_1x1)
                self.assertFalse((media_root / "images" / "articles").exists())

    def test_metadata_access_does_not_generate_variants_for_unapproved_article(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images"
            source_dir.mkdir()
            source_path = source_dir / "source.jpg"
            Image.new("RGB", (1600, 1000), (40, 120, 180)).save(source_path, "JPEG")

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"):
                articolo = Articolo.objects.create(
                    titolo="Bozza metadati",
                    contenuto="Contenuto",
                    sommario="Sommario",
                    categoria="Cronaca",
                    foto="/media/images/source.jpg",
                    approvato=False,
                    data_pubblicazione=timezone.now(),
                )

                newsarticle_urls = articolo.get_newsarticle_image_urls()
                social_url = articolo.get_social_image_url()
                articolo.refresh_from_db()

                self.assertEqual(newsarticle_urls, [social_url])
                self.assertFalse(articolo.image_16x9)
                self.assertFalse(articolo.image_4x3)
                self.assertFalse(articolo.image_1x1)
                self.assertFalse((media_root / "images" / "articles").exists())

    def test_ensure_article_image_variants_uses_static_article_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir) / "media"
            static_dir = Path(tmpdir) / "static"
            source_dir = static_dir / "custom"
            source_dir.mkdir(parents=True)
            source_path = source_dir / "source.png"
            Image.new("RGB", (1600, 1000), (120, 80, 40)).save(source_path, "PNG")

            with override_settings(
                MEDIA_ROOT=str(media_root),
                MEDIA_URL="/media/",
                STATICFILES_DIRS=[str(static_dir)],
            ):
                Articolo.objects.filter(pk=self.articolo.pk).update(
                    foto="/static/custom/source.png",
                    image_16x9="",
                    image_4x3="",
                    image_1x1="",
                )
                self.articolo.refresh_from_db()

                self.assertEqual(get_article_source_image_path(self.articolo), source_path)
                created = ensure_article_image_variants(self.articolo)
                self.articolo.refresh_from_db()

                self.assertEqual(set(created), {"image_16x9", "image_4x3", "image_1x1"})
                self.assertTrue((media_root / self.articolo.image_16x9.name).exists())

    def test_newsarticle_image_urls_uses_single_fallback_without_photo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"):
                Articolo.objects.filter(pk=self.articolo.pk).update(
                    foto="",
                    foto_upload="",
                    image_16x9="",
                    image_4x3="",
                    image_1x1="",
                )
                self.articolo.refresh_from_db()

                urls = self.articolo.get_newsarticle_image_urls()
                self.articolo.refresh_from_db()

                self.assertEqual(urls, ["https://testserver/static/home/images/portico_logo_nopayoff.png"])
                self.assertFalse(self.articolo.image_16x9)
                self.assertFalse((media_root / "images" / "articles").exists())

    def test_approval_generates_variants_before_social_thread(self):
        events = []
        draft = Articolo.objects.create(
            titolo="Da approvare",
            contenuto="Contenuto",
            sommario="Sommario",
            categoria="Cronaca",
            approvato=False,
            data_pubblicazione=timezone.now(),
        )

        def fake_thread(*args, **kwargs):
            events.append("thread")
            thread = Mock()
            thread.start.return_value = None
            return thread

        with patch("home.signals.ensure_article_image_variants", side_effect=lambda articolo: events.append("variants") or {}), patch(
            "home.signals.threading.Thread", side_effect=fake_thread
        ):
            draft.approvato = True
            draft.save(update_fields=["approvato"])

        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[0], "variants")
        self.assertEqual(events[1], "thread")

    def test_check_image_variants_reports_missing_files_without_regenerating(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images" / "uploaded"
            source_dir.mkdir(parents=True)
            source_path = source_dir / "titolo-test-original.webp"
            Image.new("RGB", (1600, 1000), (80, 120, 160)).save(source_path, "WebP")

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"):
                Articolo.objects.filter(pk=self.articolo.pk).update(
                    foto_upload="images/uploaded/titolo-test-original.webp",
                    image_16x9="images/articles/titolo-test-16x9.webp",
                    image_4x3="",
                    image_1x1="",
                )
                out = StringIO()

                call_command("check_image_variants", slug=self.articolo.slug, stdout=out)

                output = out.getvalue()
                self.assertIn("NewsArticle.image=0/3", output)
                self.assertIn("missing=image_16x9,image_4x3,image_1x1", output)
                self.assertFalse((media_root / "images" / "articles" / "titolo-test-16x9.webp").exists())

    def test_uploaded_article_image_uses_slug_based_original_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            image_buffer = BytesIO()
            Image.new("RGB", (1600, 1000), (80, 80, 80)).save(image_buffer, "JPEG")
            image_bytes = image_buffer.getvalue()

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"), patch("home.signals.threading.Thread"):
                articolo = Articolo.objects.create(
                    titolo="Nome immagine articolo",
                    contenuto="Contenuto",
                    sommario="Sommario",
                    categoria="Cronaca",
                    approvato=False,
                    foto_upload=SimpleUploadedFile("facebook_name.jpg", image_bytes, content_type="image/jpeg"),
                    data_pubblicazione=timezone.now(),
                )

                self.assertEqual(articolo.foto_upload.name, "images/uploaded/nome-immagine-articolo-original.webp")

    def test_uploaded_webp_image_is_renamed_to_article_slug_original(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            image_buffer = BytesIO()
            Image.new("RGB", (1600, 1000), (80, 80, 80)).save(image_buffer, "WebP")
            image_bytes = image_buffer.getvalue()

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"), patch("home.signals.threading.Thread"):
                articolo = Articolo.objects.create(
                    titolo="Nome immagine webp",
                    contenuto="Contenuto",
                    sommario="Sommario",
                    categoria="Cronaca",
                    approvato=False,
                    foto_upload=SimpleUploadedFile("nome-vecchio.webp", image_bytes, content_type="image/webp"),
                    data_pubblicazione=timezone.now(),
                )

                self.assertEqual(articolo.foto_upload.name, "images/uploaded/nome-immagine-webp-original.webp")

    def test_regenerate_article_images_can_write_nginx_redirect_map(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images"
            source_dir.mkdir()
            source_path = source_dir / "source.jpg"
            redirect_path = media_root / "image_redirects.conf"
            Image.new("RGB", (1600, 1000), (40, 120, 180)).save(source_path, "JPEG")

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"):
                Articolo.objects.filter(pk=self.articolo.pk).update(foto="/media/images/source.jpg")
                out = StringIO()

                call_command("regenerate_article_images", redirect_map=str(redirect_path), stdout=out)

                redirect_conf = redirect_path.read_text(encoding="utf-8")
                self.assertIn(
                    "location = /media/images/source.jpg { return 301 /media/images/articles/titolo-test-16x9.webp; }",
                    redirect_conf,
                )

    def test_regenerate_article_images_skips_unreadable_source_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images" / "downloaded"
            source_dir.mkdir(parents=True)
            source_path = source_dir / "broken.jpg"
            source_path.write_bytes(b"not an image")

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"):
                Articolo.objects.filter(pk=self.articolo.pk).update(foto="/media/images/downloaded/broken.jpg")
                out = StringIO()
                err = StringIO()

                call_command("regenerate_article_images", stdout=out, stderr=err)

                self.assertIn(f"{self.articolo.slug}: immagine non processabile, salto.", err.getvalue())
                self.assertIn("Falliti: 1", out.getvalue())

    def test_regenerate_article_images_processes_only_published_articles_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images"
            source_dir.mkdir()
            source_path = source_dir / "source.jpg"
            Image.new("RGB", (1600, 1000), (40, 120, 180)).save(source_path, "JPEG")

            draft = Articolo.objects.create(
                titolo="Bozza con immagine",
                contenuto="Contenuto",
                sommario="Sommario",
                categoria="Cronaca",
                approvato=False,
                foto="/media/images/source.jpg",
                data_pubblicazione=timezone.now(),
            )
            future = Articolo.objects.create(
                titolo="Futuro con immagine",
                contenuto="Contenuto",
                sommario="Sommario",
                categoria="Cronaca",
                approvato=True,
                foto="/media/images/source.jpg",
                data_pubblicazione=timezone.now() + timedelta(days=1),
            )

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"):
                Articolo.objects.filter(pk=self.articolo.pk).update(foto="/media/images/source.jpg")
                out = StringIO()

                call_command("regenerate_article_images", stdout=out)
                self.articolo.refresh_from_db()
                draft.refresh_from_db()
                future.refresh_from_db()

                self.assertEqual(self.articolo.image_16x9.name, "images/articles/titolo-test-16x9.webp")
                self.assertFalse(draft.image_16x9)
                self.assertFalse(future.image_16x9)
                self.assertIn("Processati: 1.", out.getvalue())

    def test_regenerate_article_images_can_include_unpublished_articles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images"
            source_dir.mkdir()
            source_path = source_dir / "source.jpg"
            Image.new("RGB", (1600, 1000), (40, 120, 180)).save(source_path, "JPEG")

            draft = Articolo.objects.create(
                titolo="Bozza con immagine",
                contenuto="Contenuto",
                sommario="Sommario",
                categoria="Cronaca",
                approvato=False,
                foto="/media/images/source.jpg",
                data_pubblicazione=timezone.now(),
            )

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"):
                Articolo.objects.filter(pk=self.articolo.pk).update(foto="/media/images/source.jpg")
                out = StringIO()

                call_command("regenerate_article_images", include_unpublished=True, stdout=out)
                draft.refresh_from_db()

                self.assertEqual(draft.image_16x9.name, "images/articles/bozza-con-immagine-16x9.webp")
                self.assertIn("Processati: 2.", out.getvalue())

    def test_detect_municipality_prefers_local_place_over_carpi_fallback(self):
        self.articolo.titolo = "A Soliera apre il nuovo spazio giovani"
        self.articolo.tags = "Carpi, Soliera, giovani"

        location = detect_municipality(self.articolo)

        self.assertEqual(location["name"], "Soliera")
        self.assertEqual(location["cap"], "41019")

    def test_detect_municipality_prefers_slug_before_body_mentions(self):
        examples = [
            "carabinieri-carpi-135-identificati-nei-controlli-del-weekend",
            "aimag-carpi-approvato-il-nuovo-patto-di-sindacato-2026",
            "carpi-kit-larvicidi-anti-zanzara-gratis-dove-ritirarli",
        ]
        for slug in examples:
            with self.subTest(slug=slug):
                self.articolo.slug = slug
                self.articolo.titolo = "Titolo con riferimenti territoriali"
                self.articolo.sommario = "Nel report compaiono anche passaggi da Soliera e Modena."
                self.articolo.contenuto = "<p>Altri dettagli dalla provincia di Modena e da Soliera.</p>"

                location = detect_municipality(self.articolo)

                self.assertEqual(location["name"], "Carpi")
                self.assertEqual(location["addressLocality"], "Carpi")

    def test_detect_municipality_ignores_modena_as_province_when_uncertain(self):
        self.articolo.slug = "kit-larvicidi-anti-zanzara-gratis-dove-ritirarli"
        self.articolo.titolo = "Kit larvicidi anti zanzara gratis"
        self.articolo.sommario = "Iniziativa valida nella provincia di Modena."
        self.articolo.contenuto = "<p>La campagna riguarda il territorio modenese.</p>"

        location = detect_municipality(self.articolo)

        self.assertEqual(location["name"], "Carpi")

    def test_detect_municipality_does_not_match_novi_sad_as_novi_di_modena(self):
        self.articolo.slug = "copilotisopralerighe-modena-parco-novi-sad"
        self.articolo.titolo = "A Modena appuntamento al Parco Novi Sad"
        self.articolo.sommario = "Evento nel parco cittadino di Modena."
        self.articolo.contenuto = "<p>Il Parco Novi Sad ospita l'iniziativa.</p>"

        location = detect_municipality(self.articolo)

        self.assertEqual(location["name"], "Modena")

    def test_detect_municipality_maps_fraction_to_municipality(self):
        self.articolo.slug = "limidi-nuova-area-verde"
        self.articolo.titolo = "Nuova area verde a Limidi"

        location = detect_municipality(self.articolo)

        self.assertEqual(location["name"], "Limidi")
        self.assertEqual(location["addressLocality"], "Soliera")
        self.assertEqual(location["cap"], "41019")

    def test_recheck_locations_command_prints_sample(self):
        out = StringIO()

        call_command("recheck_locations", sample=1, stdout=out)

        output = out.getvalue()
        self.assertIn(self.articolo.slug, output)
        self.assertIn(" | ", output)

    def test_article_detail_renders_dynamic_content_location_and_geo_meta(self):
        self.articolo.titolo = "A Soliera apre il nuovo spazio giovani"
        self.articolo.tags = "Carpi, Soliera, giovani"
        self.articolo.save(update_fields=["titolo", "tags"])
        cache.delete(f"articolo_ctx_{self.articolo.slug}")

        response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<meta name="geo.placename" content="Soliera">')
        self.assertContains(response, '<meta name="geo.position" content="44.7386;10.9212">')
        self.assertContains(response, '<meta name="ICBM" content="44.7386, 10.9212">')
        self.assertContains(response, '"contentLocation": {')
        self.assertContains(response, '"name": "Soliera"')
        self.assertContains(response, '"addressLocality": "Soliera"')
        self.assertContains(response, '"postalCode": "41019"')
        self.assertContains(response, '"latitude": 44.7386')
        self.assertContains(response, '"longitude": 10.9212')

    def test_article_detail_falls_back_to_carpi_content_location(self):
        self.articolo.titolo = "Nuovo progetto per il territorio"
        self.articolo.tags = "Cronaca"
        self.articolo.contenuto = "<p>Una notizia locale senza comune esplicito.</p>"
        self.articolo.save(update_fields=["titolo", "tags", "contenuto"])
        cache.delete(f"articolo_ctx_{self.articolo.slug}")

        response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<meta name="geo.placename" content="Carpi">')
        self.assertContains(response, '"addressLocality": "Carpi"')
        self.assertContains(response, '"postalCode": "41012"')

    def test_article_detail_renders_fraction_name_and_municipality_address(self):
        self.articolo.titolo = "A Limidi arriva il nuovo spazio giovani"
        self.articolo.slug = "limidi-nuovo-spazio-giovani"
        self.articolo.save(update_fields=["titolo", "slug"])
        cache.delete(f"articolo_ctx_{self.articolo.slug}")

        response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<meta name="geo.placename" content="Limidi">')
        self.assertContains(response, '"name": "Limidi"')
        self.assertContains(response, '"addressLocality": "Soliera"')
        self.assertContains(response, '"postalCode": "41019"')

    def test_newsarticle_renders_body_word_count_and_keywords(self):
        self.articolo.tags = "Soliera, Giovani"
        self.articolo.contenuto = (
            "<style>.hidden{display:none}</style><p>Primo testo dell'articolo.</p>"
            "<script>alert('x')</script><p>Secondo testo con &amp; dettagli.</p>"
        )
        self.articolo.save(update_fields=["tags", "contenuto"])
        cache.delete(f"articolo_ctx_{self.articolo.slug}")

        response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"wordCount": 8')
        self.assertContains(response, '"articleBody": "Primo testo dell\\u0027articolo. Secondo testo con \\u0026 dettagli."')
        self.assertContains(response, '"keywords": "Soliera, Giovani, Cronaca, Carpi, Emilia\\u002DRomagna"')
        self.assertNotContains(response, "alert(\\u0027x\\u0027)")


@override_settings(
    DEBUG=True,
    SITE_URL="https://testserver",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class ArticleImageSignalTests(TransactionTestCase):
    def test_post_save_does_not_generate_variants_for_pending_article(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"), patch(
                "home.signals.send_article_approval_notification", return_value=True
            ):
                articolo = Articolo.objects.create(
                    titolo="Articolo in approvazione senza foto",
                    contenuto="Contenuto",
                    sommario="Sommario",
                    categoria="Cronaca",
                    approvato=False,
                    data_pubblicazione=timezone.now(),
                )
                articolo.refresh_from_db()

                self.assertFalse(articolo.image_16x9)
                self.assertFalse(articolo.image_4x3)
                self.assertFalse(articolo.image_1x1)
                self.assertFalse((media_root / "images" / "articles").exists())

    def test_post_save_clears_variants_for_pending_article(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"), patch(
                "home.signals.send_article_approval_notification", return_value=True
            ):
                articolo = Articolo.objects.create(
                    titolo="Bozza con varianti vecchie",
                    contenuto="Contenuto",
                    sommario="Sommario",
                    categoria="Cronaca",
                    approvato=False,
                    image_16x9="images/articles/old-16x9.webp",
                    image_4x3="images/articles/old-4x3.webp",
                    image_1x1="images/articles/old-1x1.webp",
                    data_pubblicazione=timezone.now(),
                )
                articolo.refresh_from_db()

                self.assertFalse(articolo.image_16x9)
                self.assertFalse(articolo.image_4x3)
                self.assertFalse(articolo.image_1x1)

    def test_approval_generates_variants_from_current_photo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images"
            source_dir.mkdir(parents=True)
            first_source = source_dir / "first.jpg"
            second_source = source_dir / "second.jpg"
            Image.new("RGB", (1600, 1000), (200, 20, 20)).save(first_source, "JPEG")
            Image.new("RGB", (1600, 1000), (20, 80, 200)).save(second_source, "JPEG")

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"), patch(
                "home.signals.send_article_approval_notification", return_value=True
            ), patch("home.signals.threading.Thread") as fake_thread, patch(
                "home.signals._notify_search_engines_background"
            ):
                fake_thread.return_value.start.return_value = None
                articolo = Articolo.objects.create(
                    titolo="Articolo approvato con foto corrente",
                    contenuto="Contenuto",
                    sommario="Sommario",
                    categoria="Cronaca",
                    foto="/media/images/first.jpg",
                    approvato=False,
                    data_pubblicazione=timezone.now(),
                )
                articolo.refresh_from_db()
                self.assertFalse(articolo.image_16x9)

                articolo.foto = "/media/images/second.jpg"
                articolo.save(update_fields=["foto"])
                articolo.refresh_from_db()
                self.assertFalse(articolo.image_16x9)

                articolo.approvato = True
                articolo.save(update_fields=["approvato"])
                articolo.refresh_from_db()

                self.assertEqual(
                    articolo.image_16x9.name,
                    "images/articles/articolo-approvato-con-foto-corrente-16x9.webp",
                )
                variant_path = media_root / articolo.image_16x9.name
                self.assertTrue(variant_path.exists())
                with Image.open(variant_path) as img:
                    red, green, blue = img.getpixel((img.width // 2, img.height // 2))
                self.assertGreater(blue, red)

    def test_saving_approved_article_generates_missing_variants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images"
            source_dir.mkdir(parents=True)
            source_path = source_dir / "source.jpg"
            Image.new("RGB", (1600, 1000), (20, 80, 200)).save(source_path, "JPEG")

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"), patch(
                "home.signals.send_article_approval_notification", return_value=True
            ), patch("home.signals.threading.Thread") as fake_thread:
                fake_thread.return_value.start.return_value = None
                articolo = Articolo.objects.create(
                    titolo="Articolo gia approvato senza varianti",
                    contenuto="Contenuto",
                    sommario="Sommario",
                    categoria="Cronaca",
                    foto="/media/images/source.jpg",
                    approvato=False,
                    data_pubblicazione=timezone.now(),
                )
                Articolo.objects.filter(pk=articolo.pk).update(approvato=True)
                articolo.refresh_from_db()
                self.assertFalse(articolo.image_16x9)

                articolo.titolo = "Articolo gia approvato salvato"
                articolo.save(update_fields=["titolo"])
                for call in fake_thread.call_args_list:
                    if call.kwargs.get("name", "").startswith("PrepareArticleImages-"):
                        call.kwargs["target"]()
                articolo.refresh_from_db()

                self.assertEqual(
                    articolo.image_16x9.name,
                    "images/articles/articolo-gia-approvato-senza-varianti-16x9.webp",
                )
                self.assertTrue((media_root / articolo.image_16x9.name).exists())

    def test_saving_approved_article_after_photo_change_regenerates_variants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            source_dir = media_root / "images"
            source_dir.mkdir(parents=True)
            first_source = source_dir / "first.jpg"
            second_source = source_dir / "second.jpg"
            Image.new("RGB", (1600, 1000), (200, 20, 20)).save(first_source, "JPEG")
            Image.new("RGB", (1600, 1000), (20, 80, 200)).save(second_source, "JPEG")

            with override_settings(MEDIA_ROOT=str(media_root), MEDIA_URL="/media/"), patch(
                "home.signals.send_article_approval_notification", return_value=True
            ), patch("home.signals.threading.Thread") as fake_thread, patch(
                "home.signals._notify_search_engines_background"
            ):
                fake_thread.return_value.start.return_value = None
                articolo = Articolo.objects.create(
                    titolo="Articolo approvato cambio foto",
                    contenuto="Contenuto",
                    sommario="Sommario",
                    categoria="Cronaca",
                    foto="/media/images/first.jpg",
                    approvato=False,
                    data_pubblicazione=timezone.now(),
                )
                articolo.approvato = True
                articolo.save(update_fields=["approvato"])
                articolo.refresh_from_db()

                articolo.foto = "/media/images/second.jpg"
                articolo.save(update_fields=["foto"])
                for call in fake_thread.call_args_list:
                    if call.kwargs.get("name", "").startswith("PrepareArticleImages-"):
                        call.kwargs["target"]()
                articolo.refresh_from_db()

                variant_path = media_root / articolo.image_16x9.name
                self.assertTrue(variant_path.exists())
                with Image.open(variant_path) as img:
                    red, green, blue = img.getpixel((img.width // 2, img.height // 2))
                self.assertGreater(blue, red)

    def test_monitor_image_download_skips_unapproved_article(self):
        from home.universal_news_monitor import download_article_image_in_background

        articolo = Articolo.objects.create(
            titolo="Bozza download remoto",
            contenuto="Contenuto",
            sommario="Sommario",
            categoria="Cronaca",
            foto="https://example.com/source.jpg",
            approvato=False,
            data_pubblicazione=timezone.now(),
        )

        def immediate_thread(target=None, **kwargs):
            return Mock(start=lambda: target())

        with patch("home.universal_news_monitor.download_and_save_image") as download_mock, patch(
            "home.universal_news_monitor.threading.Thread", side_effect=immediate_thread
        ):
            download_article_image_in_background(
                articolo.id,
                "https://example.com/source.jpg",
                articolo.slug,
            )

        download_mock.assert_not_called()
        articolo.refresh_from_db()
        self.assertEqual(articolo.foto, "https://example.com/source.jpg")


@override_settings(
    DEBUG=True,
    SITE_URL="https://testserver",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class RetryFailedSocialSharesCommandTests(TestCase):
    def setUp(self):
        self.articolo = Articolo.objects.create(
            titolo="Articolo fallito",
            contenuto="Contenuto",
            sommario="Sommario",
            categoria="Cronaca",
            approvato=True,
            foto="https://example.com/image.jpg",
            data_pubblicazione=timezone.now(),
        )

    def test_retry_items_selects_old_failed_logs(self):
        SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_story",
            success=False,
            error_message="Container non ready",
        )
        SocialPublicationLog.objects.filter(articolo=self.articolo).update(
            published_at=timezone.now() - timedelta(minutes=30),
            updated_at=timezone.now() - timedelta(minutes=30),
        )

        items = RetryFailedSocialSharesCommand()._retry_items({
            "platform": ["instagram_story"],
            "older_than_minutes": 15,
            "newer_than_minutes": 0,
            "limit": 20,
            "article_limit": 0,
            "in_progress_only": False,
        })

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][0], self.articolo)
        self.assertEqual(items[0][1], "instagram_story")

    def test_retry_items_skips_platform_with_success_log(self):
        SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_story",
            success=False,
            error_message="Container non ready",
        )
        SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_story",
            success=True,
        )
        SocialPublicationLog.objects.filter(articolo=self.articolo).update(
            published_at=timezone.now() - timedelta(minutes=30),
            updated_at=timezone.now() - timedelta(minutes=30),
        )

        items = RetryFailedSocialSharesCommand()._retry_items({
            "platform": ["instagram_story"],
            "older_than_minutes": 15,
            "newer_than_minutes": 0,
            "limit": 20,
            "article_limit": 0,
            "in_progress_only": False,
        })

        self.assertEqual(items, [])

    def test_retry_items_can_limit_to_recent_window(self):
        recent_log = SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_story",
            success=False,
            error_message="Container non ready",
        )
        SocialPublicationLog.objects.filter(pk=recent_log.pk).update(
            published_at=timezone.now() - timedelta(minutes=30),
            updated_at=timezone.now() - timedelta(minutes=30),
        )

        old_article = Articolo.objects.create(
            titolo="Articolo vecchio fallito",
            contenuto="Contenuto",
            sommario="Sommario",
            categoria="Cronaca",
            approvato=True,
            foto="https://example.com/image.jpg",
            data_pubblicazione=timezone.now(),
        )
        old_log = SocialPublicationLog.objects.create(
            articolo=old_article,
            platform="instagram_story",
            success=False,
            error_message="Container non ready",
        )
        SocialPublicationLog.objects.filter(pk=old_log.pk).update(
            published_at=timezone.now() - timedelta(minutes=120),
            updated_at=timezone.now() - timedelta(minutes=120),
        )

        items = RetryFailedSocialSharesCommand()._retry_items({
            "platform": ["instagram_story"],
            "older_than_minutes": 15,
            "newer_than_minutes": 60,
            "limit": 20,
            "article_limit": 0,
            "in_progress_only": False,
        })

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][0], self.articolo)

    def test_retry_window_counts_from_first_attempt_not_last_retry(self):
        # Primo tentativo 2 ore fa, ultimo retry 20 minuti fa: fuori dalla finestra di 60
        log = SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_story",
            success=False,
            error_message="Generazione video fallita",
        )
        SocialPublicationLog.objects.filter(pk=log.pk).update(
            published_at=timezone.now() - timedelta(minutes=120),
            updated_at=timezone.now() - timedelta(minutes=20),
        )

        items = RetryFailedSocialSharesCommand()._retry_items({
            "platform": ["instagram_story"],
            "older_than_minutes": 15,
            "newer_than_minutes": 60,
            "limit": 20,
            "article_limit": 0,
            "in_progress_only": False,
        })

        self.assertEqual(items, [])

    @patch("home.management.commands.retry_failed_social_shares.social_manager.retry_failed_platforms_only")
    def test_handle_rechecks_all_platforms_when_no_platform_filter(self, retry_mock):
        retry_mock.return_value = {"telegram": True, "facebook": True, "instagram_story": True}
        SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_story",
            success=False,
            error_message="Container non ready",
        )
        SocialPublicationLog.objects.filter(articolo=self.articolo).update(
            published_at=timezone.now() - timedelta(minutes=30),
            updated_at=timezone.now() - timedelta(minutes=30),
        )

        call_command(
            "retry_failed_social_shares",
            "--execute",
            "--older-than-minutes",
            "15",
            stdout=StringIO(),
        )

        retry_mock.assert_called_once_with(self.articolo, only_platforms=None)

    @patch("home.management.commands.retry_failed_social_shares.social_manager.retry_failed_platforms_only")
    def test_handle_respects_explicit_platform_filter(self, retry_mock):
        retry_mock.return_value = {"instagram_story": True}
        SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_story",
            success=False,
            error_message="Container non ready",
        )
        SocialPublicationLog.objects.filter(articolo=self.articolo).update(
            published_at=timezone.now() - timedelta(minutes=30),
            updated_at=timezone.now() - timedelta(minutes=30),
        )

        call_command(
            "retry_failed_social_shares",
            "--execute",
            "--platform",
            "instagram_story",
            "--older-than-minutes",
            "15",
            stdout=StringIO(),
        )

        retry_mock.assert_called_once_with(self.articolo, only_platforms=["instagram_story"])

    def test_instagram_reel_retry_skips_recent_in_progress_slot(self):
        log = SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_reel",
            success=False,
            error_message="In progress...",
        )
        SocialPublicationLog.objects.filter(pk=log.pk).update(
            published_at=timezone.now() - timedelta(hours=2),
            updated_at=timezone.now() - timedelta(minutes=5),
        )
        manager = SocialMediaManager()
        manager.platforms["instagram_reel"]["enabled"] = True

        with patch.object(manager, "_share_to_instagram_reel") as share_mock:
            results = manager.retry_failed_platforms_only(
                self.articolo,
                only_platforms=["instagram_reel"],
            )

        self.assertEqual(results["instagram_reel"], False)
        share_mock.assert_not_called()

    def test_instagram_reel_retry_uses_publication_slot_and_finalizes(self):
        log = SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_reel",
            success=False,
            error_message="Container non ready",
        )
        SocialPublicationLog.objects.filter(pk=log.pk).update(
            published_at=timezone.now() - timedelta(hours=2),
            updated_at=timezone.now() - timedelta(hours=2),
        )
        manager = SocialMediaManager()
        manager.platforms["instagram_reel"]["enabled"] = True

        with (
            patch.object(manager, "_share_to_instagram_reel", return_value=(True, "ig-media-1")) as share_mock,
            patch.object(manager, "_tracking_link", return_value=("", None)),
        ):
            results = manager.retry_failed_platforms_only(
                self.articolo,
                only_platforms=["instagram_reel"],
            )

        self.assertEqual(results["instagram_reel"], True)
        share_mock.assert_called_once_with(self.articolo)
        log.refresh_from_db()
        self.assertTrue(log.success)
        self.assertEqual(log.instagram_media_id, "ig-media-1")

    def test_instagram_feed_post_saves_media_id(self):
        manager = SocialMediaManager()
        manager.platforms["instagram"]["enabled"] = True

        with patch.object(manager, "_share_to_instagram_with_retry", return_value=(True, "feed-media-1")):
            results = manager.retry_failed_platforms_only(self.articolo, only_platforms=["instagram"])

        self.assertEqual(results["instagram"], True)
        log = SocialPublicationLog.objects.get(articolo=self.articolo, platform="instagram")
        self.assertTrue(log.success)
        self.assertIsNone(log.error_message)
        self.assertEqual(log.instagram_media_id, "feed-media-1")
        self.assertEqual(log.instagram_media_ids, ["feed-media-1"])

    def test_reshare_keeps_previous_instagram_media_ids(self):
        from home.management.commands.reshare_tomorrow_events import Command as ReshareCommand

        old = SocialPublicationLog.objects.create(
            articolo=self.articolo, platform="instagram_reel", success=True,
            instagram_media_id="reel-vecchio", instagram_media_ids=["reel-vecchio"],
        )
        old_story = SocialPublicationLog.objects.create(
            articolo=self.articolo, platform="instagram_story", success=True,
            instagram_media_id="story-vecchia", instagram_media_ids=["story-vecchia"],
        )
        existing = [old, old_story]
        SocialPublicationLog.objects.filter(articolo=self.articolo).delete()
        # Il Reel si ripubblica, la Storia no
        SocialPublicationLog.objects.create(
            articolo=self.articolo, platform="instagram_reel", success=True,
            instagram_media_id="reel-nuovo", instagram_media_ids=["reel-nuovo"],
        )

        ReshareCommand._ripristina_media_ids(self.articolo, existing)

        reel = SocialPublicationLog.objects.get(articolo=self.articolo, platform="instagram_reel")
        self.assertEqual(reel.instagram_media_id, "reel-nuovo")
        self.assertEqual(reel.instagram_media_ids, ["reel-vecchio", "reel-nuovo"])
        story = SocialPublicationLog.objects.get(articolo=self.articolo, platform="instagram_story")
        self.assertEqual(story.instagram_media_ids, ["story-vecchia"])


class ProcessPendingPubbliredazionaliCommandTests(TestCase):
    def make_pubbliredazionale(self, interview_data=None):
        return Articolo.objects.create(
            titolo="Pubbliredazionale Test",
            contenuto="",
            categoria="Attualita",
            is_pubbliredazionale=True,
            nome_azienda="Azienda Test",
            payment_status="pending",
            interview_data=interview_data or {},
        )

    def test_interview_without_enough_answers_is_not_complete(self):
        pub = self.make_pubbliredazionale({
            "conversation": [
                {"role": "agent", "message": "Domanda iniziale"},
                {"role": "user", "message": "Risposta"},
            ],
        })

        complete, reason = ProcessPendingPubbliredazionaliCommand().is_interview_complete(pub)

        self.assertFalse(complete)
        self.assertIn("incompleta", reason)

    def test_interview_completion_timestamp_drives_ready_time(self):
        completed_at = timezone.now() - timedelta(hours=3)
        pub = self.make_pubbliredazionale({
            "interview_complete": True,
            "interview_completed_at": completed_at.isoformat(),
            "conversation": [
                {"role": "agent", "message": "D1"},
                {"role": "user", "message": "R1"},
                {"role": "agent", "message": "D2"},
                {"role": "user", "message": "R2"},
                {"role": "agent", "message": "D3"},
            ],
        })

        command = ProcessPendingPubbliredazionaliCommand()

        self.assertEqual(command.get_interview_completed_at(pub), completed_at)
        self.assertLessEqual(command.calculate_ready_time(completed_at), timezone.now())


@override_settings(
    DEBUG=True,
    SITE_URL="https://testserver",
    INSTAGRAM_WEBHOOK_VERIFY_TOKEN="verify-token",
    FACEBOOK_APP_SECRET="secret",
    INSTAGRAM_PAGE_ACCESS_TOKEN="page-token",
    INSTAGRAM_ACCOUNT_ID="ig-business",
    INSTAGRAM_WEBHOOK_HANDLE_SYNC=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class InstagramWebhookTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.articolo = Articolo.objects.create(
            titolo="Articolo IG",
            contenuto="Contenuto",
            sommario="Sommario",
            categoria="Cronaca",
            approvato=True,
            data_pubblicazione=timezone.now(),
        )
        self.short_link = ShortLink.objects.create(
            articolo=self.articolo,
            platform="instagram",
            medium="story",
            token="abc123",
        )
        SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_story",
            success=True,
            instagram_media_id="media-1",
            instagram_media_ids=["media-1"],
        )
        cache.clear()
        # Lettura delle didascalie da Meta: di default Meta non risponde (si ripiega come prima)
        get_patcher = patch("home.views_webhooks.requests.get", side_effect=requests.RequestException("offline"))
        self.mock_get = get_patcher.start()
        self.addCleanup(get_patcher.stop)

    @staticmethod
    def _dm_calls(mock_post):
        return [c for c in mock_post.call_args_list if c.args and "me/messages" in str(c.args[0])]

    def _dm_count(self, mock_post):
        return len(self._dm_calls(mock_post))

    def _graph_media(self, caption, media_product_type="FEED"):
        self.mock_get.side_effect = None
        self.mock_get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={"caption": caption, "media_product_type": media_product_type, "id": "x"}),
        )

    def _comment_payload(self, sender, media_id, text="LINK"):
        return {
            "object": "instagram",
            "entry": [{
                "changes": [{
                    "field": "comments",
                    "value": {"from": {"id": sender}, "media": {"id": media_id}, "text": text},
                }]
            }],
        }

    @patch("home.views_webhooks.requests.post")
    def test_feed_post_comment_matches_article(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        SocialPublicationLog.objects.create(
            articolo=self.articolo, platform="instagram", success=True,
            instagram_media_id="feed-1", instagram_media_ids=["feed-1"],
        )

        self._signed_post(self._comment_payload("feed-user", "feed-1"))

        self.assertEqual(self._dm_count(mock_post), 1)
        self.assertIn("Articolo IG", self._dm_calls(mock_post)[-1].kwargs["json"]["message"]["text"])
        self.mock_get.assert_not_called()

    @patch("home.views_webhooks.requests.post")
    def test_unmapped_media_recognized_from_caption_not_recent_reel(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        altro = Articolo.objects.create(
            titolo="Altro articolo", contenuto="c", sommario="s", categoria="Cronaca",
            approvato=True, data_pubblicazione=timezone.now(),
        )
        SocialPublicationLog.objects.create(
            articolo=altro, platform="instagram_reel", success=True, instagram_media_id="recent-reel",
        )
        feed_log = SocialPublicationLog.objects.create(articolo=self.articolo, platform="instagram", success=True)
        self._graph_media("Articolo IG\n\nSommario\n\nLeggi nel link in bio")

        self._signed_post(self._comment_payload("caption-user", "feed-vecchio"))

        self.assertEqual(self._dm_count(mock_post), 1)
        self.assertIn("Articolo IG", self._dm_calls(mock_post)[-1].kwargs["json"]["message"]["text"])
        feed_log.refresh_from_db()
        self.assertEqual(feed_log.instagram_media_ids, ["feed-vecchio"])

        # La seconda volta basta il database
        self.mock_get.reset_mock()
        self._signed_post(self._comment_payload("caption-user-2", "feed-vecchio"))
        self.assertEqual(self._dm_count(mock_post), 2)
        self.mock_get.assert_not_called()

    @patch("home.views_webhooks.requests.post")
    def test_unknown_caption_sends_no_dm(self, mock_post):
        SocialPublicationLog.objects.create(
            articolo=self.articolo, platform="instagram_reel", success=True, instagram_media_id="recent-reel",
        )
        self._graph_media("Un post fatto a mano dalla redazione")

        self._signed_post(self._comment_payload("manual-user", "post-a-mano"))

        self.assertEqual(self._dm_count(mock_post), 0)

    @patch("home.views_webhooks.requests.post")
    def test_same_user_two_articles_gets_two_dms(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        altro = Articolo.objects.create(
            titolo="Altro articolo", contenuto="c", sommario="s", categoria="Cronaca",
            approvato=True, data_pubblicazione=timezone.now(),
        )
        SocialPublicationLog.objects.create(
            articolo=altro, platform="instagram_reel", success=True, instagram_media_id="reel-altro",
        )

        self._signed_post(self._comment_payload("same-user", "media-1"))
        self._signed_post(self._comment_payload("same-user", "reel-altro"))

        self.assertEqual(self._dm_count(mock_post), 2)

    @patch("home.views_webhooks.requests.post")
    def test_emoji_and_reactions_do_not_trigger_by_default(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        self._signed_post(self._comment_payload("emoji-user", "media-1", text="Che vergogna 🤬🔥"))
        self._signed_post({
            "entry": [{"changes": [{"field": "message_reactions", "value": {
                "sender": {"id": "reaction-user"}, "media": {"id": "media-1"}, "reaction": {"emoji": "❤️"},
            }}]}]
        })
        self.assertEqual(self._dm_count(mock_post), 0)

        self._signed_post(self._comment_payload("link-user", "media-1", text="link per favore 🙏"))
        self.assertEqual(self._dm_count(mock_post), 1)

    def _signed_post(self, payload):
        body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        return self.client.post(
            reverse("instagram_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=f"sha256={signature}",
        )

    def test_get_challenge_ok_and_ko(self):
        ok = self.client.get(reverse("instagram_webhook"), {
            "hub.verify_token": "verify-token",
            "hub.challenge": "123",
        })
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.content, b"123")

        ko = self.client.get(reverse("instagram_webhook"), {
            "hub.verify_token": "wrong",
            "hub.challenge": "123",
        })
        self.assertEqual(ko.status_code, 403)

    def test_invalid_signature(self):
        response = self.client.post(
            reverse("instagram_webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=bad",
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI=True)
    @patch("home.views_webhooks.requests.post")
    def test_valid_reaction_sends_dm_and_rate_limits(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        payload = {
            "entry": [{
                "changes": [{
                    "field": "message_reactions",
                    "value": {
                        "sender": {"id": "ig-user"},
                        "media": {"id": "media-1"},
                        "reaction": {"emoji": "❤️"},
                    },
                }]
            }]
        }

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_post.call_count, 1)

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_post.call_count, 1)

    @patch("home.views_webhooks.requests.post")
    def test_media_history_matches_old_instagram_media_id(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        SocialPublicationLog.objects.filter(articolo=self.articolo, platform="instagram_story").update(
            instagram_media_id="new-media",
            instagram_media_ids=["media-1", "old-media", "new-media"],
        )
        payload = {
            "entry": [{
                "changes": [{
                    "field": "messages",
                    "value": {
                        "sender": {"id": "history-user"},
                        "media": {"id": "old-media"},
                        "message": {"text": "LINK"},
                    },
                }]
            }]
        }

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_post.call_count, 1)

    @patch("home.views_webhooks.requests.post")
    def test_linkedin_does_not_match_link_trigger(self, mock_post):
        payload = {
            "entry": [{
                "changes": [{
                    "field": "messages",
                    "value": {
                        "sender": {"id": "linkedin-user"},
                        "media": {"id": "media-1"},
                        "message": {"text": "LINKEDIN"},
                    },
                }]
            }]
        }

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        mock_post.assert_not_called()

    @patch("home.views_webhooks.requests.post")
    def test_rate_limit_released_on_dm_failure(self, mock_post):
        fail_response = type("Resp", (), {})()
        fail_response.status_code = 400
        fail_response.text = '{"error":{"message":"fail","code":10,"fbtrace_id":"trace"}}'
        fail_response.json = lambda: {"error": {"message": "fail", "code": 10, "fbtrace_id": "trace"}}
        ok_response = type("Resp", (), {})()
        ok_response.status_code = 200
        ok_response.text = "{}"
        ok_response.json = lambda: {}
        mock_post.side_effect = [fail_response, ok_response]
        first_payload = {
            "entry": [{
                "changes": [{
                    "field": "messages",
                    "value": {
                        "sender": {"id": "retry-user"},
                        "media": {"id": "media-1"},
                        "message": {"text": "LINK"},
                    },
                }]
            }]
        }
        second_payload = {
            "entry": [{
                "changes": [{
                    "field": "messages",
                    "value": {
                        "sender": {"id": "retry-user"},
                        "media": {"id": "media-1"},
                        "message": {"text": "INFO"},
                    },
                }]
            }]
        }

        self.assertEqual(self._signed_post(first_payload).status_code, 200)
        self.assertEqual(self._signed_post(second_payload).status_code, 200)
        self.assertEqual(mock_post.call_count, 2)

    @patch("home.views_webhooks.requests.post")
    def test_stop_opt_out(self, mock_post):
        payload = {
            "entry": [{
                "changes": [{
                    "field": "messages",
                    "value": {
                        "sender": {"id": "ig-stop"},
                        "media": {"id": "media-1"},
                        "message": {"text": "STOP"},
                    },
                }]
            }]
        }
        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(InstagramOptOut.objects.filter(ig_user_id="ig-stop").exists())
        mock_post.assert_not_called()

    @override_settings(INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI=True)
    @patch("home.views_webhooks.requests.post")
    def test_text_emoji_reply_sends_dm(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        payload = {
            "entry": [{
                "changes": [{
                    "field": "messages",
                    "value": {
                        "sender": {"id": "ig-user-text-heart"},
                        "media": {"id": "media-1"},
                        "message": {"text": "❤️"},
                    },
                }]
            }]
        }

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_post.call_count, 1)

    @patch("home.views_webhooks.requests.post")
    def test_messaging_payload_story_reply_sends_dm(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        payload = {
            "object": "instagram",
            "entry": [{
                "id": "ig-business",
                "messaging": [{
                    "sender": {"id": "real-sender-id"},
                    "recipient": {"id": "ig-business"},
                    "message": {
                        "mid": "message-id",
                        "text": "LINK",
                        "reply_to": {"story": {"id": "media-1"}},
                    },
                }],
            }],
        }

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_post.call_count, 1)

    @override_settings(INSTAGRAM_AUTO_DM_TEXT_TRIGGERS=["['LINK'", "'INFO'", "'LEGGI']"])
    @patch("home.views_webhooks.requests.post")
    def test_reel_comment_link_triggers_with_malformed_env_tokens(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_reel",
            success=True,
            instagram_media_id="reel-1",
        )
        payload = {
            "object": "instagram",
            "entry": [{
                "changes": [{
                    "field": "comments",
                    "value": {
                        "from": {"id": "commenter-id"},
                        "media": {"id": "reel-1"},
                        "text": "LINK",
                    },
                }]
            }],
        }

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_post.call_count, 1)

    @override_settings(INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI=True)
    @patch("home.views_webhooks.requests.post")
    def test_reel_comment_with_emoji_triggers_dm(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_reel",
            success=True,
            instagram_media_id="reel-emoji",
        )
        payload = {
            "object": "instagram",
            "entry": [{
                "changes": [{
                    "field": "comments",
                    "value": {
                        "from": {"id": "emoji-commenter-id"},
                        "media": {"id": "reel-emoji"},
                        "text": "Grande \U0001f525",
                    },
                }]
            }],
        }

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_post.call_count, 1)

    @patch("home.views_webhooks.requests.post")
    def test_reel_comment_unmapped_media_falls_back_to_recent_reel(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_reel",
            success=True,
            instagram_media_id="recent-reel",
        )
        payload = {
            "object": "instagram",
            "entry": [{
                "changes": [{
                    "field": "comments",
                    "value": {
                        "from": {"id": "commenter-id"},
                        "media": {"id": "missing-reel"},
                        "text": "LINK",
                    },
                }]
            }],
        }

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_post.call_count, 1)

    @override_settings(INSTAGRAM_AUTO_DM_REEL_FALLBACK_MINUTES=0)
    @patch("home.views_webhooks.requests.post")
    def test_reel_fallback_can_be_disabled(self, mock_post):
        SocialPublicationLog.objects.create(
            articolo=self.articolo,
            platform="instagram_reel",
            success=True,
            instagram_media_id="recent-reel",
        )
        payload = {
            "object": "instagram",
            "entry": [{
                "changes": [{
                    "field": "comments",
                    "value": {
                        "from": {"id": "commenter-id"},
                        "media": {"id": "missing-reel"},
                        "text": "LINK",
                    },
                }]
            }],
        }

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        mock_post.assert_not_called()

    @patch("home.views_webhooks.requests.post")
    def test_unmapped_media_does_not_consume_rate_limit(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        unmapped_payload = {
            "object": "instagram",
            "entry": [{
                "changes": [{
                    "field": "messages",
                    "value": {
                        "sender": {"id": "same-user"},
                        "media": {"id": "missing-media"},
                        "message": {"text": "LINK"},
                    },
                }]
            }],
        }
        mapped_payload = {
            "object": "instagram",
            "entry": [{
                "changes": [{
                    "field": "messages",
                    "value": {
                        "sender": {"id": "same-user"},
                        "media": {"id": "media-1"},
                        "message": {"text": "LINK"},
                    },
                }]
            }],
        }

        self.assertEqual(self._signed_post(unmapped_payload).status_code, 200)
        self.assertEqual(self._signed_post(mapped_payload).status_code, 200)
        self.assertEqual(mock_post.call_count, 1)

    @override_settings(INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI=True)
    @patch("home.views_webhooks.requests.post")
    def test_story_reaction_unmapped_media_falls_back_to_recent_story(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        payload = {
            "object": "instagram",
            "entry": [{
                "changes": [{
                    "field": "message_reactions",
                    "value": {
                        "sender": {"id": "story-emoji-user"},
                        "media": {"id": "meta-story-id-not-saved"},
                        "reaction": {"emoji": "\u2764\ufe0f"},
                    },
                }]
            }],
        }

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_post.call_count, 1)

    @override_settings(INSTAGRAM_AUTO_DM_STORY_FALLBACK_MINUTES=0)
    @override_settings(INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI=True)
    @patch("home.views_webhooks.requests.post")
    def test_story_fallback_can_be_disabled(self, mock_post):
        payload = {
            "object": "instagram",
            "entry": [{
                "changes": [{
                    "field": "message_reactions",
                    "value": {
                        "sender": {"id": "story-emoji-user"},
                        "media": {"id": "meta-story-id-not-saved"},
                        "reaction": {"emoji": "\u2764\ufe0f"},
                    },
                }]
            }],
        }

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        mock_post.assert_not_called()

    @override_settings(INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI=True)
    @patch("home.views_webhooks.requests.post")
    def test_messaging_payload_reaction_without_media_falls_back_to_recent_story(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        payload = {
            "object": "instagram",
            "entry": [{
                "id": "ig-business",
                "messaging": [{
                    "sender": {"id": "real-sender-id"},
                    "recipient": {"id": "ig-business"},
                    "reaction": {"mid": "message-id", "emoji": "❤"},
                }],
            }],
        }

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_post.call_count, 1)

    @patch("home.views_webhooks.requests.post")
    def test_own_business_message_is_ignored(self, mock_post):
        payload = {
            "object": "instagram",
            "entry": [{
                "id": "ig-business",
                "messaging": [{
                    "sender": {"id": "ig-business"},
                    "recipient": {"id": "real-sender-id"},
                    "message": {"text": "LINK"},
                }],
            }],
        }

        response = self._signed_post(payload)
        self.assertEqual(response.status_code, 200)
        mock_post.assert_not_called()


@override_settings(
    DEBUG=True,
    SITE_URL="https://testserver",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class LinkInBioTests(TestCase):
    def _article(self, title, days=0, category="Cronaca"):
        return Articolo.objects.create(
            titolo=title,
            contenuto="Contenuto",
            sommario="Sommario",
            categoria=category,
            approvato=True,
            data_pubblicazione=timezone.now() - timedelta(days=days),
        )

    def test_filters_last_7_days_and_highlights_story(self):
        recent = self._article("Recente")
        old = self._article("Vecchio", days=10)
        SocialPublicationLog.objects.create(articolo=recent, platform="instagram_story", success=True)
        old_log = SocialPublicationLog.objects.create(articolo=old, platform="instagram", success=True)
        SocialPublicationLog.objects.filter(pk=old_log.pk).update(published_at=timezone.now() - timedelta(days=10))

        response = self.client.get(reverse("link_in_bio"))
        self.assertContains(response, "Recente")
        self.assertNotContains(response, "Vecchio")
        self.assertContains(response, "Appena pubblicato su Story")

    def test_search_filters_title_and_category(self):
        wanted = self._article("Cultura in piazza", category="Cultura & Eventi")
        other = self._article("Cronaca locale")
        SocialPublicationLog.objects.create(articolo=wanted, platform="instagram", success=True)
        SocialPublicationLog.objects.create(articolo=other, platform="instagram", success=True)

        response = self.client.get(reverse("link_in_bio_search"), {"q": "Cultura"})
        self.assertContains(response, "Cultura in piazza")
        self.assertNotContains(response, "Cronaca locale")


class NewsletterIndirizzoInesistenteTests(SimpleTestCase):
    def test_dominio_inesistente_disattiva(self):
        import smtplib
        from home.management.commands.send_newsletter import indirizzo_inesistente
        exc = smtplib.SMTPRecipientsRefused({'x@immenseignite.info': (556, b'5.1.10 abc dominio non valido')})
        self.assertTrue(indirizzo_inesistente(exc))

    def test_rifiuti_non_di_indirizzo_non_disattivano(self):
        import smtplib
        from home.management.commands.send_newsletter import indirizzo_inesistente
        self.assertFalse(indirizzo_inesistente(smtplib.SMTPRecipientsRefused({'a@b.it': (550, b'5.7.1 rate limit')})))
        self.assertFalse(indirizzo_inesistente(smtplib.SMTPRecipientsRefused({'a@b.it': (450, b'4.1.1 try later')})))
        self.assertFalse(indirizzo_inesistente(smtplib.SMTPServerDisconnected('please run connect() first')))


class ReelImmagineLocaleTests(TestCase):
    def test_usa_versione_locale_se_la_foto_remota_non_risponde(self):
        import tempfile
        from pathlib import Path
        from django.test import override_settings
        from home.facebook_reels import FacebookReelGenerator

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            Path(media, 'images', 'articles').mkdir(parents=True)
            Path(media, 'images', 'articles', 'x-16x9.webp').write_bytes(b'x')
            articolo = Articolo(titolo='T', contenuto='c', foto='https://example.com/sparita.jpg',
                                image_16x9='images/articles/x-16x9.webp')
            generator = FacebookReelGenerator.__new__(FacebookReelGenerator)
            with patch.object(FacebookReelGenerator, '_download_image', return_value=None):
                path = generator._resolve_image_path(articolo)
            self.assertEqual(path, Path(media, 'images', 'articles', 'x-16x9.webp'))


@override_settings(
    DEBUG=True,
    SITE_URL="https://testserver",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class MonitorNoindexTests(TestCase):
    def setUp(self):
        cache.clear()
        self.testata = MonitorConfig.objects.create(name='Testata', base_url='https://www.testata.it/',
                                                    scraper_type='html', noindex=True)
        self.comune = MonitorConfig.objects.create(name='Comune', base_url='https://www.comune.it/',
                                                   scraper_type='html')
        common = dict(contenuto='<p>Testo</p>', sommario='S', categoria='Attualità', approvato=True,
                      data_pubblicazione=timezone.now() - timedelta(hours=1))
        self.riscritto = Articolo.objects.create(titolo='Riscritto da testata', monitor_origine=self.testata, **common)
        self.originale = Articolo.objects.create(titolo='Notizia del comune', monitor_origine=self.comune, **common)
        self.vecchio = Articolo.objects.create(titolo='Vecchio senza monitor', fonte='https://www.testata.it/a/',
                                               **common)

    def test_meta_robots_segue_il_monitor(self):
        r = self.client.get(f'/articolo/{self.riscritto.slug}/')
        self.assertContains(r, '<meta name="robots" content="noindex, follow">')
        r = self.client.get(f'/articolo/{self.originale.slug}/')
        self.assertContains(r, 'content="index, follow, max-image-preview:large"')

    def test_sitemap_esclude_i_monitor_noindex(self):
        for url in ('/sitemap.xml', '/sitemap-news.xml'):
            r = self.client.get(url)
            self.assertNotContains(r, self.riscritto.slug)
            self.assertContains(r, self.originale.slug)

    def test_selettore_vale_subito_anche_con_articolo_in_cache(self):
        self.client.get(f'/articolo/{self.originale.slug}/')  # mette in cache il contesto
        MonitorConfig.objects.filter(pk=self.comune.pk).update(noindex=True)
        r = self.client.get(f'/articolo/{self.originale.slug}/')
        self.assertContains(r, '<meta name="robots" content="noindex, follow">')

    def test_evento_scaduto_esce_dall_indice(self):
        from datetime import date
        from home.models import soglia_evento_scaduto
        scaduto = Articolo.objects.create(titolo='Mostra scaduta', contenuto='<p>T</p>', sommario='S',
                                          categoria='Cultura & Eventi', approvato=True,
                                          data_pubblicazione=timezone.now() - timedelta(hours=2),
                                          data_evento=soglia_evento_scaduto() - timedelta(days=1))
        vicino = Articolo.objects.create(titolo='Mostra appena finita', contenuto='<p>T</p>', sommario='S',
                                         categoria='Cultura & Eventi', approvato=True,
                                         data_pubblicazione=timezone.now() - timedelta(hours=2),
                                         data_evento=soglia_evento_scaduto())
        r = self.client.get(f'/articolo/{scaduto.slug}/')
        self.assertContains(r, '<meta name="robots" content="noindex, follow">')
        r = self.client.get(f'/articolo/{vicino.slug}/')
        self.assertContains(r, 'content="index, follow, max-image-preview:large"')
        r = self.client.get('/sitemap.xml')
        self.assertNotContains(r, scaduto.slug)
        self.assertContains(r, vicino.slug)

    def test_collega_monitor_origine_dal_dominio(self):
        call_command('collega_monitor_origine', stdout=StringIO())
        self.vecchio.refresh_from_db()
        self.assertIsNone(self.vecchio.monitor_origine_id)  # prova a vuoto
        call_command('collega_monitor_origine', '--esegui', stdout=StringIO())
        self.vecchio.refresh_from_db()
        self.assertEqual(self.vecchio.monitor_origine_id, self.testata.pk)
        self.assertTrue(self.vecchio.escluso_da_google)


@override_settings(
    DEBUG=True,
    SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class NewsletterIscrizioneTests(TestCase):
    AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def test_salva_l_origine_del_modulo(self):
        from home.models import NewsletterSubscriber
        r = self.client.post("/newsletter/", {"email": "Lettore@Example.it", "origine": "barra"}, **self.AJAX)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(NewsletterSubscriber.objects.get().origine, "barra")
        self.assertEqual(NewsletterSubscriber.objects.get().email, "lettore@example.it")

    def test_origine_sconosciuta_non_salvata(self):
        from home.models import NewsletterSubscriber
        self.client.post("/newsletter/", {"email": "a@example.it", "origine": "<script>"}, **self.AJAX)
        self.assertEqual(NewsletterSubscriber.objects.get().origine, "")

    def test_honeypot_compilato_finge_successo_e_non_salva(self):
        from home.models import NewsletterSubscriber
        r = self.client.post("/newsletter/", {"email": "bot@example.it", "sito_web": "http://spam"}, **self.AJAX)
        self.assertTrue(r.json()["ok"])
        self.assertFalse(NewsletterSubscriber.objects.exists())

    def test_email_non_valida_rifiutata(self):
        from home.models import NewsletterSubscriber
        r = self.client.post("/newsletter/", {"email": "non-una-email"}, **self.AJAX)
        self.assertFalse(r.json()["ok"])
        self.assertFalse(NewsletterSubscriber.objects.exists())

    def test_gia_iscritto_messaggio_leggibile(self):
        self.client.post("/newsletter/", {"email": "a@example.it"}, **self.AJAX)
        r = self.client.post("/newsletter/", {"email": "a@example.it"}, **self.AJAX)
        self.assertEqual(r.json()["message"], "Sei già iscritto alla newsletter.")


@override_settings(
    DEBUG=True,
    SECURE_SSL_REDIRECT=False,
    SITE_URL="https://testserver",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class NewsletterModuliPagineTests(TestCase):
    """Barra/riquadro newsletter: articoli e liste (homepage in cache_page, quindi niente CSRF)."""

    def setUp(self):
        cache.clear()
        self.articolo = Articolo.objects.create(
            titolo='Notizia di prova newsletter', contenuto='<p>Testo</p>', sommario='S',
            categoria='Attualità', approvato=True, data_pubblicazione=timezone.now() - timedelta(hours=1))

    def test_iscrizione_senza_token_csrf(self):
        from django.test import Client
        from home.models import NewsletterSubscriber
        client = Client(enforce_csrf_checks=True)
        r = client.post("/newsletter/", {"email": "home@example.it", "origine": "barra_home"},
                        HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(NewsletterSubscriber.objects.get().origine, "barra_home")

    def test_homepage_ha_la_barra_senza_csrf(self):
        html = self.client.get("/").content.decode()
        self.assertIn('id="nl-bar"', html)
        self.assertIn('value="barra_home"', html)
        self.assertIn('data-origine-pc="barra_home_pc"', html)
        self.assertNotIn('csrfmiddlewaretoken', html)

    def test_articolo_riquadro_prima_del_banner_finale(self):
        html = self.client.get(f"/articolo/{self.articolo.slug}/").content.decode()
        self.assertIn('value="barra"', html)
        self.assertIn('data-origine-pc="barra_pc"', html)
        self.assertEqual(html.count('id="nl-bar"'), 1)
        self.assertLess(html.index('id="nl-cta-box"'), html.index('<!-- Banner fine articolo -->'))


@override_settings(SITE_URL="https://testserver")
class ReelCommentoLinkTests(TestCase):
    """Primo commento con il link sotto il Reel Facebook (nella descrizione non e' cliccabile)."""

    def setUp(self):
        self.articolo = Articolo.objects.create(
            titolo='Reel con commento', contenuto='<p>T</p>', sommario='S', categoria='Attualità',
            approvato=True, data_pubblicazione=timezone.now())

    def _risposta(self, status, body):
        r = Mock(status_code=status, text=json.dumps(body))
        r.json.return_value = body
        return r

    def test_commento_con_link_tracciato(self):
        from home.facebook_reels import FacebookPageReelManager
        with patch('home.facebook_reels.requests.post', return_value=self._risposta(200, {'id': '1_2'})) as post:
            ok, info = FacebookPageReelManager().commenta_link(self.articolo, '999', 'tok', attesa=0)
        self.assertTrue(ok)
        self.assertEqual(info, '1_2')
        url, kwargs = post.call_args[0][0], post.call_args[1]
        self.assertTrue(url.endswith('/999/comments'))
        link = ShortLink.objects.get(articolo=self.articolo, platform='facebook', medium='reel_commento')
        self.assertIn(f'/s/{link.token}/', kwargs['data']['message'])

    def test_riprova_se_il_video_e_ancora_in_elaborazione(self):
        from home.facebook_reels import FacebookPageReelManager
        risposte = [self._risposta(400, {'error': {'code': 100, 'message': 'processing'}}),
                    self._risposta(200, {'id': '1_3'})]
        with patch('home.facebook_reels.requests.post', side_effect=risposte) as post:
            ok, _ = FacebookPageReelManager().commenta_link(self.articolo, '999', 'tok', attesa=0)
        self.assertTrue(ok)
        self.assertEqual(post.call_count, 2)

    def test_permesso_mancante_non_riprova(self):
        from home.facebook_reels import FacebookPageReelManager
        with patch('home.facebook_reels.requests.post',
                   return_value=self._risposta(403, {'error': {'code': 200, 'message': 'permission'}})) as post:
            ok, _ = FacebookPageReelManager().commenta_link(self.articolo, '999', 'tok', attesa=0)
        self.assertFalse(ok)
        self.assertEqual(post.call_count, 1)

    def test_pubblicazione_avvia_il_commento(self):
        from home import facebook_reels
        manager = facebook_reels.FacebookPageReelManager()

        def finto_publish(publisher, video_path, description=''):
            publisher.last_video_id = '777'
            return True, 'post_1'

        with override_settings(FACEBOOK_PAGE_ID='123'), \
             patch.object(manager, 'generate', return_value='/tmp/finto.mp4'), \
             patch.object(manager, '_cleanup_local_file'), \
             patch.object(facebook_reels.FacebookPageReelPublisher, 'publish', finto_publish), \
             patch.object(facebook_reels.threading, 'Thread') as thread:
            ok, _ = manager.publish(self.articolo, 'tok')
        self.assertTrue(ok)
        self.assertEqual(thread.call_args[1]['args'][1], '777')
        thread.return_value.start.assert_called_once()


@override_settings(SITE_URL="https://testserver", DEBUG=True, SECURE_SSL_REDIRECT=False)
class GruppiFacebookTests(TestCase):
    """Condivisione a mano nei gruppi: testo, link tracciato, pulsanti dei gruppi di partenza."""

    def setUp(self):
        from home.models import GruppoFacebook
        self.articolo = Articolo.objects.create(
            titolo='Festa della zucca a Fossoli', contenuto='<p>T</p>',
            sommario='Domenica in piazza a Fossoli torna la festa. Stand, musica e giochi per tutta la giornata.',
            categoria='Cultura & Eventi', comune='Carpi', approvato=True, data_pubblicazione=timezone.now())
        self.secondo = GruppoFacebook.objects.create(nome='Sei di Carpi se', ordine=2,
                                                     url='https://www.facebook.com/groups/2/')
        self.primo = GruppoFacebook.objects.create(nome='ViVi Carpi', ordine=1,
                                                   url='https://www.facebook.com/groups/1')
        self.spento = GruppoFacebook.objects.create(nome='Gruppo spento', url='https://www.facebook.com/groups/3/',
                                                    attivo=False)

    def test_indirizzo_che_apre_la_finestra_del_post(self):
        self.assertEqual(self.primo.url_nuovo_post, 'https://www.facebook.com/groups/1/?should_open_composer=true')
        self.assertEqual(self.secondo.url_nuovo_post, 'https://www.facebook.com/groups/2/?should_open_composer=true')

    def test_un_testo_per_articolo_con_link_tracciato(self):
        from home.gruppi_facebook import testo_condivisione
        testo = testo_condivisione(self.articolo)
        link = ShortLink.objects.get(articolo=self.articolo, platform='facebook_gruppo', medium='gruppi')
        # apre con il riassunto, non con il titolo: quello lo mostra la scheda del link
        self.assertTrue(testo.startswith('Domenica in piazza a Fossoli torna la festa.'))
        self.assertNotIn('Festa della zucca a Fossoli', testo)
        self.assertTrue(testo.endswith(f'/s/{link.token}/'))
        self.assertEqual(testo_condivisione(self.articolo), testo)
        r = self.client.get(f'/s/{link.token}/')
        self.assertIn('utm_source=facebook_gruppo&utm_medium=gruppi', r['Location'])

    def test_pagina_con_un_pulsante_per_gruppo_attivo(self):
        self.client.force_login(User.objects.create_superuser('admin', 'a@example.it', 'x'))
        html = self.client.get(reverse('admin:gruppi_condividi')).content.decode()
        self.assertIn('Festa della zucca a Fossoli', html)
        self.assertEqual(html.count('class="cg-testo"'), 1)
        self.assertEqual(html.count('class="button cg-apri"'), 2)
        self.assertLess(html.index('Copia e apri: ViVi Carpi'), html.index('Copia e apri: Sei di Carpi se'))
        self.assertNotIn('Gruppo spento', html)
        self.assertIn('data-url="https://www.facebook.com/groups/1/?should_open_composer=true"', html)

    def test_segna_fatto_senza_ricaricare_e_annulla(self):
        from home.models import CondivisioneGruppo
        self.client.force_login(User.objects.create_superuser('admin', 'a@example.it', 'x'))
        url = reverse('admin:gruppi_condividi')
        dati = {'articolo': self.articolo.pk, 'gruppo': self.primo.pk, 'azione': 'fatto'}
        r = self.client.post(url, dati, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(r.json()['ok'])
        self.assertRegex(r.json()['ora'], r'^\d\d/\d\d \d\d:\d\d$')
        self.client.post(url, dati, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(CondivisioneGruppo.objects.filter(articolo=self.articolo, gruppo=self.primo).count(), 1)
        self.assertIn('cg-partenza fatto', self.client.get(url).content.decode())
        r = self.client.post(url + '?giorni=2', {**dati, 'azione': 'annulla'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(CondivisioneGruppo.objects.exists())

    def test_elenco_gruppi_nell_admin(self):
        self.client.force_login(User.objects.create_superuser('admin', 'a@example.it', 'x'))
        r = self.client.get(reverse('admin:home_gruppofacebook_changelist'))
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse('admin:home_gruppofacebook_change', args=[self.primo.pk]))
        self.assertEqual(r.status_code, 200)

    def test_link_dei_gruppi_fatto_leggere_a_facebook(self):
        from home.social_sharing import social_manager
        with patch('home.social_sharing.requests.post') as post:
            post.return_value = Mock(status_code=200, text='{}')
            social_manager._prepara_anteprima_gruppi(self.articolo, 'chiave')
        dati = post.call_args.kwargs['data']
        link = ShortLink.objects.get(articolo=self.articolo, platform='facebook_gruppo', medium='gruppi')
        self.assertTrue(dati['id'].endswith(f'/s/{link.token}/'))
        self.assertEqual(dati['scrape'], 'true')

    def test_errore_di_facebook_non_ferma_la_condivisione(self):
        from home.social_sharing import social_manager
        with patch('home.social_sharing.requests.post', side_effect=requests.ConnectionError('giu')):
            social_manager._prepara_anteprima_gruppi(self.articolo, 'chiave')

    def test_riassunto_senza_stili_e_html(self):
        from home.gruppi_facebook import _riassunto
        self.assertEqual(_riassunto('<style>p{color:red}</style><p>Ciao &amp; benvenuti</p>'), 'Ciao & benvenuti')


ALBO_HTML = """<html><body><table id="tabella_risultati"><tbody>
<tr><td>2078/2026</td><td>Comune di Carpi</td><td>Pubblicazioni di matrimonio</td><td>224</td><td>{oggi}</td>
<td><div>PUBBLICAZIONI DI MATRIMONIO ROSSI - BIANCHI</div></td><td>{oggi}</td><td>15/11/2026</td><td><a href="https://albo.test/?pub_token=a">x</a></td></tr>
<tr><td>2073/2026</td><td>Comune di Carpi</td><td>Ordinanza</td><td>31</td><td>{oggi}</td>
<td><div>ORDINANZA UFFICIO MOBILITÃ\x80-VIABILITÃ\x80 N.31/2026: POSA DISSUASORE IN VIA PAGANINI</div></td><td>{oggi}</td><td>21/11/2026</td><td><a href="https://albo.test/?pub_token=b">x</a></td></tr>
<tr><td>1500/2026</td><td>Comune di Carpi</td><td>Delibera di Giunta</td><td>10</td><td>01/01/2026</td>
<td><div>DELIBERA VECCHIA</div></td><td>01/01/2026</td><td>15/01/2026</td><td></td></tr>
</tbody></table></body></html>"""

ALBO_DETTAGLIO_HTML = """<html><body><table class="tablesorter"><tbody>
<tr><td>U.O.R. Mittente</td><td>Comune di Carpi</td></tr>
<tr><td>Protocollo</td><td>72505/2026</td></tr>
<tr><td>Oggetto</td><td>gia' nell'elenco</td></tr>
</tbody></table>
<table class="tablesorter"><thead><tr><th>Elenco Documenti [2]</th></tr></thead>
<tbody><tr><td>- ordinanza.pdf.p7m<br /><span>( Impronta MD5 )</span></td><td>{dimensione}</td><td>- ATTO</td>
<td><a href="https://albo.test/?pub_token=p7m"><img src="https://albo.test/icons/file-p7m.png"></a></td>
<td><a href="https://albo.test/?pub_token=pdf"><img src="https://albo.test/icons/file-pdf.png"></a></td></tr>
<tr><td>- planimetria.pdf<br /></td><td>1 MiB</td><td>- ALLEGATO</td>
<td><a href="https://albo.test/?pub_token=allegato"><img src="https://albo.test/icons/file-pdf.png"></a></td></tr>
<tr><td>- P_2026_PARERE_3.pdf.p7m<br /></td><td>100 KiB</td><td>- ALLEGATO</td>
<td><a href="https://albo.test/?pub_token=parere"><img src="https://albo.test/icons/file-pdf.png"></a></td></tr>
</tbody></table></body></html>"""


class AlboItalsoftScraperTests(SimpleTestCase):
    def _scraper(self, **config):
        from home.universal_news_monitor import AlboItalsoftScraper, SiteConfig
        sc = SiteConfig('Albo Pretorio Comune di Carpi', 'https://albo.test/carpi/?page_id=740',
                        'albo_italsoft', 'Attualità', **config)
        return AlboItalsoftScraper(sc, {})

    def _risposta(self, html):
        r = Mock()
        r.content = html.encode('utf-8')
        r.raise_for_status = Mock()
        return r

    def test_atti_recenti_con_url_fisso_e_tipi_esclusi(self):
        from datetime import datetime
        oggi = datetime.now().strftime('%d/%m/%Y')
        scraper = self._scraper()
        with patch.object(scraper, '_get_request', return_value=self._risposta(ALBO_HTML.format(oggi=oggi))):
            atti = scraper.scrape_articles()

        # Matrimonio escluso (dati di privati), delibera di gennaio troppo vecchia
        self.assertEqual(len(atti), 1)
        atto = atti[0]
        self.assertEqual(atto['url'], 'https://albo.test/carpi/?page_id=740#reg-2073-2026')
        # Accenti codificati due volte dal gestionale ripresi
        self.assertIn('MOBILITÀ-VIABILITÀ', atto['title'])
        self.assertTrue(atto['title'].startswith('Ordinanza n. 31: '))
        self.assertIn('N. registro albo: 2073/2026', atto['content'])

    def _contenuto(self, dimensione='135 KiB', testo_atto='x' * 300, testo_allegato='y' * 300, **config):
        """get_full_content dell'ordinanza con scheda e PDF finti; ritorna (testo, url chiesti)."""
        from datetime import datetime
        oggi = datetime.now().strftime('%d/%m/%Y')
        scraper = self._scraper(**config)
        with patch.object(scraper, '_get_request', return_value=self._risposta(ALBO_HTML.format(oggi=oggi))):
            url = scraper.scrape_articles()[0]['url']
        risposte = {
            'https://albo.test/?pub_token=b': self._risposta(ALBO_DETTAGLIO_HTML.format(dimensione=dimensione)),
            'https://albo.test/?pub_token=pdf': Mock(content=b'%PDF atto', raise_for_status=Mock()),
            'https://albo.test/?pub_token=allegato': Mock(content=b'%PDF allegato', raise_for_status=Mock()),
        }
        testi = {b'%PDF atto': testo_atto, b'%PDF allegato': testo_allegato}
        with patch.object(scraper, '_get_request', side_effect=lambda u, **kw: risposte[u]) as get, \
                patch.object(scraper, '_testo_pdf', side_effect=lambda dati, _max: testi[dati]):
            testo = scraper.get_full_content(url)
        return testo, [c.args[0] for c in get.call_args_list]

    def test_dettaglio_aggiunge_solo_i_campi_nuovi(self):
        testo, _ = self._contenuto(leggi_pdf=False)
        self.assertIn('Protocollo: 72505/2026', testo)
        self.assertIn('Documenti allegati: ordinanza.pdf.p7m; planimetria.pdf; P_2026_PARERE_3.pdf.p7m', testo)
        self.assertNotIn('U.O.R.', testo)
        self.assertNotIn("gia' nell'elenco", testo)

    def test_testo_dell_atto_e_degli_allegati_utili(self):
        testo, chiesti = self._contenuto(testo_atto='ORDINA il senso unico alternato ' * 20,
                                         testo_allegato='Via Mazzini: chiusura dal 10 al 20 novembre ' * 10)
        # Atto dal link al PDF senza firma (non il .p7m); allegato letto, parere no
        self.assertEqual(sorted(chiesti), ['https://albo.test/?pub_token=allegato',
                                           'https://albo.test/?pub_token=b',
                                           'https://albo.test/?pub_token=pdf'])
        self.assertIn("TESTO DELL'ATTO", testo)
        self.assertIn('ORDINA il senso unico alternato', testo)
        self.assertNotIn('ATTO NON LETTO', testo)
        self.assertIn('ALLEGATO "planimetria.pdf"', testo)
        self.assertIn('Via Mazzini: chiusura dal 10 al 20 novembre', testo)
        self.assertLess(testo.index("TESTO DELL'ATTO"), testo.index('ALLEGATO "planimetria.pdf"'))

    def test_allegati_nella_meta_dello_spazio(self):
        testo, _ = self._contenuto(testo_atto='Premessa lunga. ' * 2000, testo_allegato='Opera da 150.000 euro. ' * 2000,
                                   pdf_max_caratteri=10000)
        atto = testo.split("TESTO DELL'ATTO")[1].split('ALLEGATO "')[0]
        allegato = testo.split('ALLEGATO "planimetria.pdf"')[1]
        self.assertLessEqual(len(allegato), 5200)
        self.assertLessEqual(len(atto), 5300)
        self.assertGreater(len(atto), 4000)  # all'atto lo spazio lasciato dall'allegato

    def test_pdf_troppo_grande_o_scansione_saltati(self):
        testo, chiesti = self._contenuto(dimensione='10.57 MiB', leggi_allegati=False)
        self.assertEqual(len(chiesti), 1)  # solo la scheda, il PDF non si scarica
        self.assertNotIn("TESTO DELL'ATTO", testo)
        self.assertTrue(testo.startswith('ATTO NON LETTO:'))   # avviso per chi sceglie e per l'AI

        testo, _ = self._contenuto(testo_atto='Firmato digitalmente', testo_allegato='')  # scansioni
        self.assertNotIn("TESTO DELL'ATTO", testo)
        self.assertTrue(testo.startswith('ATTO NON LETTO:'))
        self.assertNotIn('ALLEGATO "', testo)
        self.assertIn('Protocollo: 72505/2026', testo)

    def test_atto_pubblicato_due_volte_resta_quello_con_il_file(self):
        # 9/11/2026: ordinanza 800 dell'Unione ai registri 2205 (senza file) e 2206 (con il PDF)
        def riga(registro, numero='800', oggetto='ORDINANZA POTATURE'):
            return {'registro': registro, 'ente': 'UNIONE', 'tipo': 'Ordinanza', 'numero': numero,
                    'data_atto': '07/11/2026', 'oggetto': oggetto, 'dal': '09/11/2026', 'al': '',
                    'dettaglio': f'https://albo.test/?d={registro}'}
        righe = [riga('2204/2026', '804', 'DIVIETO DI SOSTA'), riga('2205/2026'), riga('2206/2026')]
        scraper = self._scraper()
        con_file = {'https://albo.test/?d=2205/2026': [{'nome': 'atto.pdf'}]}
        with patch.object(scraper, '_leggi_dettaglio', side_effect=lambda link, ente: ([], con_file.get(link, []))):
            tenute, doppi = scraper._senza_doppioni(righe)
        self.assertEqual(doppi, 1)
        self.assertEqual(sorted(r['registro'] for r in tenute), ['2204/2026', '2205/2026'])

        # Nessuna delle due ha il file: resta l'ultima registrata
        with patch.object(scraper, '_leggi_dettaglio', return_value=([], [])):
            tenute, _ = scraper._senza_doppioni(righe)
        self.assertEqual(sorted(r['registro'] for r in tenute), ['2204/2026', '2206/2026'])

    def test_atto_senza_documenti_lo_dice(self):
        from datetime import datetime
        oggi = datetime.now().strftime('%d/%m/%Y')
        scraper = self._scraper()
        with patch.object(scraper, '_get_request', return_value=self._risposta(ALBO_HTML.format(oggi=oggi))):
            url = scraper.scrape_articles()[0]['url']
        with patch.object(scraper, '_leggi_dettaglio', return_value=(['Protocollo: 84101/2026'], [])):
            testo = scraper.get_full_content(url)
        self.assertIn("L'albo non ha pubblicato il testo dell'atto", testo)

    def test_limite_fonte_piu_alto_per_gli_atti_dell_albo(self):
        from home.universal_news_monitor import (MAX_ALBO_SOURCE_CHARS, MAX_SOURCE_CHARS,
                                                 source_char_limit)
        albo = 'https://trasparenza.terredargine.it/campogalliano/?page_id=740#reg-811-2026'
        self.assertEqual(source_char_limit({'url': albo}), MAX_ALBO_SOURCE_CHARS)
        self.assertEqual(source_char_limit({'url': 'https://www.comune.carpi.mo.it/notizia'}), MAX_SOURCE_CHARS)
        self.assertEqual(source_char_limit({}), MAX_SOURCE_CHARS)

    def test_accenti_codificati_due_volte(self):
        from home.universal_news_monitor import AlboItalsoftScraper
        self.assertEqual(AlboItalsoftScraper._testo('festivitÃ   natalizie'), 'festività natalizie')
        self.assertEqual(AlboItalsoftScraper._testo('MOBILITÃ\u0080-VIABILITÃ\u0080'), 'MOBILITÀ-VIABILITÀ')
        self.assertEqual(AlboItalsoftScraper._testo(' città  già\n giusta '), 'città già giusta')

    def test_numero_atto_senza_zeri(self):
        from home.universal_news_monitor import AlboItalsoftScraper
        self.assertEqual(AlboItalsoftScraper._numero(' 000000000141 '), '141')
        self.assertEqual(AlboItalsoftScraper._numero('961'), '961')
        self.assertEqual(AlboItalsoftScraper._numero('0'), '0')
        self.assertEqual(AlboItalsoftScraper._numero('SUAP/0012'), 'SUAP/0012')
        self.assertEqual(AlboItalsoftScraper._numero(''), '')

    def test_busta_p7m_aperta(self):
        from home.universal_news_monitor import AlboItalsoftScraper
        busta = b'0\x82\x10\x00firma' + b'%PDF-1.4 contenuto %%EOF\n' + b'certificati'
        self.assertEqual(AlboItalsoftScraper._pdf_da_p7m(busta), b'%PDF-1.4 contenuto %%EOF')
        self.assertEqual(AlboItalsoftScraper._pdf_da_p7m(b'nessun pdf'), b'')
        self.assertEqual(AlboItalsoftScraper._byte('10.57 MiB'), int(10.57 * 1024 ** 2))

    def test_atto_lungo_tiene_la_parte_dispositiva(self):
        from home.universal_news_monitor import AlboItalsoftScraper
        testo = 'OGGETTO: affidamento sgombero neve. ' + 'Richiamata la delibera. ' * 400 + \
                'DETERMINA di affidare alla ditta Rossi per euro 38.975,81. Il Dirigente'
        corto = AlboItalsoftScraper._accorcia_atto(testo, 2000)
        self.assertLessEqual(len(corto), 2100)
        self.assertTrue(corto.startswith('OGGETTO: affidamento sgombero neve.'))
        self.assertIn('[... premesse omesse ...]', corto)
        self.assertTrue(corto.endswith('DETERMINA di affidare alla ditta Rossi per euro 38.975,81. Il Dirigente'))
        self.assertEqual(AlboItalsoftScraper._accorcia_atto('breve', 2000), 'breve')

    def test_nota_albo_prima_di_quella_del_comune(self):
        from home.prompt_redazione import NOTE_FONTE, nota_per_monitor
        self.assertEqual(nota_per_monitor('Albo Pretorio Comune di Carpi'), NOTE_FONTE['albo'])


class PolisherElenchiHtmlTests(SimpleTestCase):
    """Elenchi HTML scritti dall'AI: prima uscivano come <p><ul>.</p> e <p></ul>...</p>."""

    def _pulisci(self, html):
        return content_polisher.polish_article({'titolo': 't', 'contenuto': html})['contenuto']

    def test_elenco_con_a_capo_singoli_resta_intatto(self):
        out = self._pulisci('<p>Gli interventi sono questi:</p>\n<ul>\n<li>Casa della salute, 5,5 milioni;</li>\n'
                            '<li>strade, 150.000 euro.</li>\n</ul>\n<p>Fine.</p>')
        self.assertIn('<ul> <li>Casa della salute, 5,5 milioni;</li> <li>strade, 150.000 euro.</li> </ul>', out)
        self.assertNotIn('<p><ul>', out)
        self.assertNotIn('<ul>.', out)
        self.assertNotIn('<p></ul>', out)
        self.assertNotIn('<p><p>', out)

    def test_righe_vuote_tra_le_voci_non_perdono_i_li(self):
        out = self._pulisci('<p>Prima.</p>\n\n<ul>\n\n<li>uno</li>\n\n<li>due</li>\n\n</ul>\n\n<h2>Titolo</h2>\n\n<p>Dopo</p>')
        self.assertIn('<li>uno</li> <li>due</li>', out)
        self.assertIn('<h2>Titolo</h2>', out)
        self.assertTrue(out.endswith('<p>Dopo.</p>'))

    def test_punto_dentro_il_paragrafo(self):
        self.assertEqual(self._pulisci('<p>Testo con <strong>nome</strong></p>'),
                         '<p>Testo con <strong>nome</strong>.</p>')
        self.assertEqual(self._pulisci('Primo paragrafo\n\nSecondo paragrafo.'),
                         '<p>Primo paragrafo.</p>\n\n<p>Secondo paragrafo.</p>')


class AttoLettoAllaRielaborazioneTests(TestCase):
    """Notizia grezza dell'albo con l'avviso "ATTO NON LETTO": alla rielaborazione si legge l'atto."""

    def _grezza(self):
        return Articolo.objects.create(
            titolo='Ordinanza n. 34: ciclabile', categoria='Attualità', approvato=False,
            fonte='https://albo.test/carpi/?page_id=740#reg-2173-2026',
            contenuto='ATTO NON LETTO: i documenti pubblicati sono scansioni.\n\nN. registro albo: 2173/2026')

    def test_il_testo_letto_sostituisce_l_avviso(self):
        from home.rielaborazione_ai import _con_testo_dell_atto
        a = self._grezza()
        with patch('home.albo_scansioni.leggi_atto', return_value="TESTO DELL'ATTO (trascritto):\n\nORDINA la creazione") as letto:
            testo = _con_testo_dell_atto(a, Mock(), a.contenuto)
        letto.assert_called_once()
        self.assertNotIn('ATTO NON LETTO', testo)
        self.assertTrue(testo.startswith('N. registro albo: 2173/2026'))
        self.assertIn('ORDINA la creazione', testo)
        a.refresh_from_db()
        self.assertIn('ORDINA la creazione', a.contenuto)      # salvato sulla grezza
        self.assertNotIn('ATTO NON LETTO', a.contenuto)

    def test_senza_avviso_o_senza_testo_non_cambia_nulla(self):
        from home.rielaborazione_ai import _con_testo_dell_atto
        a = self._grezza()
        with patch('home.albo_scansioni.leggi_atto') as letto:
            self.assertEqual(_con_testo_dell_atto(a, Mock(), 'N. registro albo: 1/2026'), 'N. registro albo: 1/2026')
        letto.assert_not_called()
        with patch('home.albo_scansioni.leggi_atto', return_value=''):
            self.assertEqual(_con_testo_dell_atto(a, Mock(), a.contenuto), a.contenuto)
        with patch('home.albo_scansioni.leggi_atto', side_effect=RuntimeError('albo irraggiungibile')):
            self.assertEqual(_con_testo_dell_atto(a, Mock(), a.contenuto), a.contenuto)

    def test_registro_dalla_fonte(self):
        from home.albo_scansioni import _registro_da_fonte
        self.assertEqual(_registro_da_fonte('https://albo.test/carpi/?page_id=740#reg-2173-2026'),
                         ('https://albo.test/carpi/?page_id=740', '2173/2026'))
        self.assertEqual(_registro_da_fonte('https://temponews.it/articolo/'), (None, None))


class VideoInstagramSeparatoTests(SimpleTestCase):
    """Dal 23/11/2026 Facebook e Instagram hanno video diversi: solo Instagram spiega il DM."""

    def test_cartelle_e_scritte_diverse(self):
        from home.instagram_story import InstagramReelGenerator, InstagramStoryGenerator
        from home.instagram_templates import IG_CTA_INVITO
        from home.reel_animato import ReelAnimatoGenerator

        fb = ReelAnimatoGenerator()
        self.assertEqual(fb.config.output_dir_name, "reels")
        self.assertEqual(fb.config.cta_text, "Leggi su ombradelportico.it")
        self.assertEqual(fb.invito_testi, "")
        for gen in (InstagramStoryGenerator(), InstagramReelGenerator()):
            self.assertEqual(gen.config.output_dir_name, "ig_video")
            # alla fine il sito come su Facebook, l'invito sta sotto i testi
            self.assertEqual(gen.config.cta_text, "Leggi su ombradelportico.it")
            self.assertEqual(gen.invito_testi, IG_CTA_INVITO)


class PromemoriaEventiDistribuitoTests(TestCase):
    """Il promemoria del mattino distribuisce gli eventi fino alle 11:50, i piu' letti per primi."""

    def _cmd(self):
        from home.management.commands.reshare_tomorrow_events import Command
        return Command

    def test_orari_a_intervalli_uguali_fino_all_ora_indicata(self):
        inizio = timezone.localtime().replace(hour=7, minute=50, second=0, microsecond=0)
        with patch('home.management.commands.reshare_tomorrow_events.timezone.localtime', return_value=inizio):
            orari = self._cmd()._orari(5, '11:50')
            self.assertEqual([o.strftime('%H:%M') for o in orari], ['07:50', '08:50', '09:50', '10:50', '11:50'])
            self.assertEqual([o.strftime('%H:%M') for o in self._cmd()._orari(2, '11:50')], ['07:50', '11:50'])
            self.assertEqual(self._cmd()._orari(1, '11:50'), [])          # un solo evento: subito
            self.assertEqual(self._cmd()._orari(5, '11:50', subito=True), [])
            self.assertEqual(self._cmd()._orari(5, '07:00'), [])          # ora gia' passata
            self.assertEqual(self._cmd()._orari(5, 'mezzogiorno'), [])

    def test_i_piu_letti_per_giorno_escono_per_primi(self):
        adesso = timezone.now()
        vecchio = Articolo(titolo='Vecchio', views=300, data_pubblicazione=adesso - timedelta(days=30))
        nuovo = Articolo(titolo='Nuovo', views=60, data_pubblicazione=adesso - timedelta(days=2))
        fermo = Articolo(titolo='Fermo', views=0, data_pubblicazione=adesso - timedelta(days=2))
        ordinati = sorted([vecchio, fermo, nuovo], key=self._cmd()._importanza, reverse=True)
        self.assertEqual([a.titolo for a in ordinati], ['Nuovo', 'Vecchio', 'Fermo'])   # 30, 10 e 0 al giorno

    def test_il_comando_aspetta_ogni_orario_e_condivide_in_ordine(self):
        domani = timezone.localdate() + timedelta(days=1)
        adesso = timezone.now()
        # bulk_create: niente segnali di approvazione, che in un test farebbero partire la condivisione
        Articolo.objects.bulk_create([
            Articolo(titolo=titolo, slug=slug, contenuto='x', sommario='x', categoria='Cultura & Eventi',
                     approvato=True, data_evento=domani, views=views,
                     data_pubblicazione=adesso - timedelta(days=1))
            for titolo, slug, views in (('Evento poco letto', 'evento-poco-letto', 5),
                                        ('Evento molto letto', 'evento-molto-letto', 500))])
        condivisi, attese = [], []
        inizio = timezone.localtime().replace(hour=7, minute=50, second=0, microsecond=0)
        base = 'home.management.commands.reshare_tomorrow_events'
        with patch(f'{base}.timezone.localtime', return_value=inizio), \
             patch(f'{base}.Command._aspetta', side_effect=lambda q: attese.append(q.strftime('%H:%M'))), \
             patch(f'{base}.social_manager.retry_failed_platforms_only',
                   side_effect=lambda a, only_platforms=None: condivisi.append(a.titolo) or {'facebook': True}):
            call_command('reshare_tomorrow_events', stdout=StringIO())
        self.assertEqual(condivisi, ['Evento molto letto', 'Evento poco letto'])
        self.assertEqual(attese, ['07:50', '11:50'])


class PubblicaProgrammatiTests(TestCase):
    """Articoli approvati in anticipo: escono sui social quando arriva la data di pubblicazione."""

    def _crea(self, slug, ore, **extra):
        # bulk_create: niente segnali di approvazione
        return Articolo.objects.bulk_create([Articolo(
            titolo=slug, slug=slug, contenuto='x', sommario='x', categoria='Cultura & Eventi',
            approvato=True, data_pubblicazione=timezone.now() + timedelta(hours=ore), **extra)])[0]

    def test_sceglie_solo_quelli_arrivati_e_mai_condivisi(self):
        from home.management.commands.pubblica_programmati import articoli_da_pubblicare
        from home.models import SocialPublicationLog
        arrivato = self._crea('arrivato', -1)
        self._crea('futuro', 5)
        self._crea('troppo-vecchio', -24 * 5)
        condiviso = self._crea('gia-condiviso', -1)
        SocialPublicationLog.objects.create(articolo=condiviso, platform='telegram', success=True)
        Articolo.objects.bulk_create([Articolo(titolo='non approvato', slug='non-approvato', contenuto='x',
                                               sommario='x', approvato=False,
                                               data_pubblicazione=timezone.now() - timedelta(hours=1))])
        self.assertEqual([a.slug for a in articoli_da_pubblicare()], [arrivato.slug])

    def test_il_comando_condivide_e_svuota_la_cache(self):
        a = self._crea('evento-programmato', -1)
        base = 'home.signals'
        with patch(f'{base}._share_article_background') as share, \
             patch(f'{base}.ensure_publication_images_ready'), \
             patch(f'{base}.generate_responsive_images_for_article'), \
             patch('home.indexing_notifier.notifier.notify_article_published') as notify, \
             patch('home.management.commands.pubblica_programmati.cache.clear') as clear:
            call_command('pubblica_programmati', stdout=StringIO())
        share.assert_called_once_with(a.id, a.titolo)
        clear.assert_called_once()
        self.assertEqual(notify.call_count, 0 if a.escluso_da_google else 1)

    def test_il_promemoria_salta_gli_articoli_non_ancora_usciti(self):
        domani = timezone.localdate() + timedelta(days=1)
        self._crea('non-ancora-uscito', 24 * 3, data_evento=domani)
        out = StringIO()
        call_command('reshare_tomorrow_events', '--dry-run', stdout=out)
        self.assertIn('Nessun articolo trovato', out.getvalue())


class RotazioneBraniReelTests(TestCase):
    """I brani di un tono ruotano: nessuno torna prima che siano usciti tutti gli altri."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.cartella = Path(tempfile.mkdtemp())
        self.sobri = ['Taccuino di Vetro.mp3', 'eliveta-corporate-491206.mp3',
                      'penguinmusic-inspiring-minimal-434823.mp3']
        for nome in self.sobri + ['alec_koff-carnaval-484622.mp3']:
            (self.cartella / nome).write_bytes(b'x')

    def _articolo(self, n, tono='sobrio'):
        a = Articolo(titolo=f'Notizia {n}', slug=f'notizia-{n}', contenuto='<p>T</p>', categoria='Cronaca',
                     reel_tono=tono)
        Articolo.objects.bulk_create([a])
        return Articolo.objects.get(slug=f'notizia-{n}')

    def test_tutti_i_brani_del_tono_prima_di_ripeterne_uno(self):
        from home.reel_musica import scegli_brano
        usciti = [scegli_brano(self._articolo(n), self.cartella).name for n in range(7)]
        self.assertEqual(sorted(usciti[:3]), sorted(self.sobri))
        self.assertEqual(usciti[3:6], usciti[:3])
        self.assertEqual(usciti[6], usciti[0])

    def test_stesso_brano_per_lo_stesso_articolo(self):
        from home.reel_musica import scegli_brano
        a = self._articolo(1)
        primo = scegli_brano(a, self.cartella)
        self._articolo(2)
        self.assertEqual(scegli_brano(Articolo.objects.get(pk=a.pk), self.cartella), primo)
        self.assertEqual(Articolo.objects.get(pk=a.pk).reel_brano, primo.name)

    def test_tono_cambiato_a_mano_cambia_brano(self):
        from home.reel_musica import scegli_brano
        a = self._articolo(1)
        scegli_brano(a, self.cartella)
        Articolo.objects.filter(pk=a.pk).update(reel_tono='vivace')
        nuovo = scegli_brano(Articolo.objects.get(pk=a.pk), self.cartella)
        self.assertEqual(nuovo.name, 'alec_koff-carnaval-484622.mp3')

    def test_articolo_non_salvato_non_rompe(self):
        from types import SimpleNamespace
        from home.reel_musica import scegli_brano
        finto = SimpleNamespace(titolo='Prova', slug='prova', categoria='Cronaca', reel_tono='')
        self.assertIn(scegli_brano(finto, self.cartella).name, self.sobri)


class DescrizioneReelFacebookTests(SimpleTestCase):
    """La descrizione del Reel Facebook porta titolo, link, sommario e pochi hashtag."""

    def test_link_subito_sotto_il_titolo_poi_sommario_e_hashtag(self):
        from home.facebook_reels import descrizione_reel
        a = Articolo(titolo='Bilancio 2027, Carpi alza Imu', comune='Carpi', tags='bilancio, Imu, asfalti, giunta',
                     sommario='La giunta ha approvato lo schema. ' * 30)
        righe = descrizione_reel(a, 'https://ombradelportico.it/s/AbC/').split('\n\n')
        self.assertEqual(righe[0], 'Bilancio 2027, Carpi alza Imu')
        self.assertEqual(righe[1], 'Leggi tutto: https://ombradelportico.it/s/AbC/')
        self.assertLessEqual(len(righe[2]), 400)
        self.assertTrue(righe[2].endswith('.'))              # tagliato a fine frase
        self.assertEqual(righe[3], '#Carpi #bilancio #Imu')  # il comune e due parole chiave

    def test_senza_sommario_e_senza_tag(self):
        from home.facebook_reels import descrizione_reel
        a = Articolo(titolo='Festa a Novi', comune='Novi di Modena', sommario='', tags='')
        self.assertEqual(descrizione_reel(a, 'https://x/s/1/'),
                         'Festa a Novi\n\nLeggi tutto: https://x/s/1/\n\n#NoviDiModena')


class HashtagInstagramTests(SimpleTestCase):
    """Al massimo cinque hashtag: il comune, le parole chiave dell'articolo, la categoria."""

    def test_comune_parole_chiave_e_categoria_entro_cinque(self):
        a = Articolo(titolo='x', comune='Soliera', categoria='Cronaca', tags='api, sciami, Pettirosso, volontari, miele')
        tags = SocialMediaManager()._get_instagram_hashtags(a).split()
        self.assertEqual(tags, ['#Soliera', '#api', '#sciami', '#Pettirosso', '#Cronaca'])

    def test_senza_parole_chiave_si_riempie_dalla_categoria_ma_mai_oltre_cinque(self):
        a = Articolo(titolo='x', comune='', categoria='Sport', tags='')
        tags = SocialMediaManager()._get_instagram_hashtags(a).split()
        self.assertEqual(tags[:2], ['#Carpi', '#Sport'])
        self.assertLessEqual(len(tags), 5)
        self.assertNotIn('#OmbraDelPortico', tags)


class TestoAlternativoInstagramTests(SimpleTestCase):
    """Il post con foto di Instagram porta come testo alternativo titolo e punti del video."""

    def test_titolo_e_punti_del_video(self):
        a = Articolo(titolo='Un bastone che conta i passi', sommario='Sommario.',
                     reel_punti='Pesa meno di 80 grammi\nSupera il 90% di accuratezza.')
        self.assertEqual(
            SocialMediaManager._testo_alternativo(a),
            "Foto dell'articolo con il titolo: Un bastone che conta i passi. "
            "Pesa meno di 80 grammi. Supera il 90% di accuratezza.")

    def test_senza_punti_usa_il_sommario_e_non_supera_mille_caratteri(self):
        a = Articolo(titolo='Titolo', sommario='Parola ' * 400, reel_punti='')
        testo = SocialMediaManager._testo_alternativo(a)
        self.assertTrue(testo.startswith("Foto dell'articolo con il titolo: Titolo. Parola"))
        self.assertLessEqual(len(testo), 1000)


class CaroselloInstagramTests(SimpleTestCase):
    """Su Instagram, al posto della foto singola, un carosello: foto, punti chiave, invito."""

    PUNTI = ['Tre tirocini partono a gennaio', 'Domande entro il 31 dicembre', 'Moduli sul sito del Comune']

    def _articolo(self, punti=None):
        return Articolo(titolo='Il Comune cerca tirocinanti', slug='tirocini', categoria='Attualità',
                        sommario='Sommario.', reel_punti='\n'.join(self.PUNTI if punti is None else punti))

    def _risposta(self, status=200, ident='1'):
        r = Mock(status_code=status, text='{}')
        r.json.return_value = {'id': ident}
        return r

    def test_schede_copertina_punti_e_invito(self):
        from home.instagram_templates import render_instagram_carousel
        with tempfile.TemporaryDirectory() as cartella:
            foto = Path(cartella) / 'foto.jpg'
            Image.new('RGB', (600, 900), (120, 80, 40)).save(foto)
            schede = render_instagram_carousel(foto, 'tirocini', 'Titolo', 'Attualità', self.PUNTI,
                                               output_dir=Path(cartella))
            self.assertEqual([p.name for p in schede],
                             [f'tirocini_ig_c{i}.jpg' for i in range(1, 6)])
            for p in schede:
                with Image.open(p) as img:
                    self.assertEqual(img.size, (1080, 1350))
            # con un solo punto niente carosello
            self.assertEqual(render_instagram_carousel(foto, 'x', 'Titolo', 'Attualità', ['Uno'],
                                                       output_dir=Path(cartella)), [])

    def _pubblica(self, risposte, punti=None):
        manager = SocialMediaManager()
        schede = [f'https://ombradelportico.it/media/images/instagram_temp/tirocini_ig_c{i}.jpg'
                  for i in range(1, 6)]
        with patch.object(manager, '_prepare_instagram_carousel', return_value=schede), \
                patch('home.social_sharing.requests.post', side_effect=risposte) as post, \
                patch('home.social_sharing.time.sleep'), \
                patch('home.luoghi_meta.place_id_per', return_value=''):
            esito = manager._pubblica_carosello_instagram(
                self._articolo(punti), '123', 'token', 'Didascalia', 'https://ombradelportico.it/foto.jpg')
        return esito, post

    def test_cinque_schede_un_contenitore_e_la_pubblicazione(self):
        risposte = [self._risposta(ident=f'f{i}') for i in range(5)]
        risposte += [self._risposta(ident='contenitore'), self._risposta(ident='post99')]
        esito, post = self._pubblica(risposte)
        self.assertEqual(esito, 'post99')
        chiamate = [c.kwargs['data'] for c in post.call_args_list]
        self.assertTrue(all(d['is_carousel_item'] == 'true' for d in chiamate[:5]))
        self.assertEqual(chiamate[1]['alt_text'], self.PUNTI[0])
        self.assertEqual(chiamate[5]['media_type'], 'CAROUSEL')
        self.assertEqual(chiamate[5]['children'], 'f0,f1,f2,f3,f4')
        self.assertEqual(chiamate[5]['caption'], 'Didascalia')
        self.assertEqual(chiamate[6]['creation_id'], 'contenitore')

    def test_testo_alternativo_rifiutato_si_riprova_senza(self):
        risposte = [self._risposta(status=400), self._risposta(ident='f0')]
        risposte += [self._risposta(ident=f'f{i}') for i in range(1, 5)]
        risposte += [self._risposta(ident='contenitore'), self._risposta(ident='post1')]
        esito, post = self._pubblica(risposte)
        self.assertEqual(esito, 'post1')
        self.assertNotIn('alt_text', post.call_args_list[1].kwargs['data'])

    def test_senza_punti_o_con_rifiuto_di_meta_esce_la_foto_singola(self):
        esito, post = self._pubblica([], punti=['Uno solo'])
        self.assertEqual(esito, '')
        post.assert_not_called()
        esito, _ = self._pubblica([self._risposta(status=400), self._risposta(status=400)])
        self.assertEqual(esito, '')

    @override_settings(INSTAGRAM_CAROSELLO=False)
    def test_spento_dal_env(self):
        esito, post = self._pubblica([])
        self.assertEqual(esito, '')
        post.assert_not_called()


class ReelFacebookRimandatoTests(TestCase):
    """Storia e Reel Facebook escono qualche ora dopo il post con il link, non insieme."""

    def setUp(self):
        self.articolo = Articolo.objects.create(
            titolo='Nuova piazza a Limidi', contenuto='<p>T</p>', sommario='Sommario.',
            categoria='Attualità', approvato=False, data_pubblicazione=timezone.now())
        # approvato con update(): niente segnali di approvazione (social, motori di ricerca)
        Articolo.objects.filter(pk=self.articolo.pk).update(approvato=True)
        self.articolo.refresh_from_db()
        self.manager = SocialMediaManager()

    def _ora(self, ore, minuti=0):
        return timezone.make_aware(timezone.datetime(2026, 11, 26, ore, minuti))

    def test_tre_ore_dopo_ma_non_di_notte(self):
        uscita = SocialMediaManager.uscita_reel_rimandato
        self.assertEqual(uscita(self._ora(10), 3), self._ora(13))
        self.assertEqual(uscita(self._ora(20, 30), 3),
                         timezone.make_aware(timezone.datetime(2026, 11, 27, 7, 0)))
        self.assertEqual(uscita(self._ora(2), 3), self._ora(7))

    @override_settings(FACEBOOK_REEL_RITARDO_ORE=3)
    def test_all_approvazione_si_segna_l_attesa_e_nessuno_la_scavalca(self):
        self.assertTrue(self.manager._rimanda_reel_facebook(self.articolo, 'facebook_reel'))
        log = SocialPublicationLog.objects.get(articolo=self.articolo, platform='facebook_reel')
        self.assertFalse(log.success)
        self.assertTrue(log.error_message.startswith('Rimandato'))
        # un secondo salvataggio dell'articolo e i tentativi di recupero non lo fanno uscire prima
        self.assertTrue(self.manager._rimanda_reel_facebook(self.articolo, 'facebook_reel'))
        self.assertEqual(self.manager._prepare_publication_slot(self.articolo, 'facebook_reel'), (False, False))
        cmd = RetryFailedSocialSharesCommand()
        voci = cmd._retry_items({'older_than_minutes': 0, 'platform': None, 'newer_than_minutes': 0,
                                 'in_progress_only': False, 'limit': 10, 'article_limit': 10})
        self.assertEqual(list(voci), [])

    @override_settings(FACEBOOK_REEL_RITARDO_ORE=0)
    def test_con_zero_ore_esce_insieme_come_prima(self):
        self.assertFalse(self.manager._rimanda_reel_facebook(self.articolo, 'facebook_reel'))
        self.assertFalse(SocialPublicationLog.objects.filter(articolo=self.articolo).exists())

    @override_settings(FACEBOOK_REEL_RITARDO_ORE=3)
    def test_escono_quando_arriva_l_ora(self):
        from django.core.cache import cache
        cache.delete('reel_rimandati_ultima_uscita')
        for platform in ('facebook_story', 'facebook_reel'):
            self.manager._rimanda_reel_facebook(self.articolo, platform)
            self.manager.platforms[platform]['enabled'] = True
        SocialPublicationLog.objects.update(published_at=self._ora(9))
        creato =SocialPublicationLog.objects.filter(articolo=self.articolo).first().published_at
        dopo = SocialMediaManager.uscita_reel_rimandato(creato, 3) + timedelta(minutes=1)
        with patch.object(SocialMediaManager, '_share_to_facebook_story', return_value=(True, '')) as storia, \
                patch.object(SocialMediaManager, '_share_to_facebook_reel', return_value=(True, '')) as reel, \
                patch.object(Articolo, 'has_shareable_image', True):
            self.assertEqual(self.manager.pubblica_reel_rimandati(adesso=creato + timedelta(minutes=30)), 0)
            storia.assert_not_called()
            self.assertEqual(self.manager.pubblica_reel_rimandati(adesso=dopo), 2)
            self.assertEqual(self.manager.pubblica_reel_rimandati(adesso=dopo), 0)
        storia.assert_called_once()
        reel.assert_called_once()
        self.assertEqual(
            SocialPublicationLog.objects.filter(articolo=self.articolo, success=True).count(), 2)

    @override_settings(FACEBOOK_REEL_RITARDO_ORE=3, FACEBOOK_REEL_DISTANZA_MINUTI=30)
    def test_articoli_approvati_insieme_escono_a_distanza(self):
        from django.core.cache import cache
        from home.social_sharing import REEL_RIMANDATI_ULTIMA_USCITA
        cache.delete(REEL_RIMANDATI_ULTIMA_USCITA)
        secondo = Articolo.objects.create(
            titolo='Mostra al museo', contenuto='<p>T</p>', sommario='Sommario.',
            categoria='Attualità', approvato=False, data_pubblicazione=timezone.now())
        Articolo.objects.filter(pk=secondo.pk).update(approvato=True)
        self.manager.platforms['facebook_reel']['enabled'] = True
        for articolo in (self.articolo, secondo):
            self.manager._rimanda_reel_facebook(articolo, 'facebook_reel')
        SocialPublicationLog.objects.update(published_at=self._ora(9))
        with patch.object(SocialMediaManager, '_share_to_facebook_reel', return_value=(True, '')) as reel, \
                patch.object(Articolo, 'has_shareable_image', True):
            self.assertEqual(self.manager.pubblica_reel_rimandati(adesso=self._ora(12, 5)), 1)
            self.assertEqual(self.manager.pubblica_reel_rimandati(adesso=self._ora(12, 20)), 0)
            self.assertEqual(self.manager.pubblica_reel_rimandati(adesso=self._ora(12, 36)), 1)
        self.assertEqual(reel.call_count, 2)
        cache.delete(REEL_RIMANDATI_ULTIMA_USCITA)

    @override_settings(FACEBOOK_REEL_RITARDO_ORE=3, FACEBOOK_REEL_DISTANZA_MINUTI=30)
    def test_la_coda_non_esce_di_notte(self):
        from django.core.cache import cache
        from home.social_sharing import REEL_RIMANDATI_ULTIMA_USCITA
        cache.delete(REEL_RIMANDATI_ULTIMA_USCITA)
        self.manager.platforms['facebook_reel']['enabled'] = True
        self.manager._rimanda_reel_facebook(self.articolo, 'facebook_reel')
        SocialPublicationLog.objects.update(published_at=self._ora(9))
        with patch.object(SocialMediaManager, '_share_to_facebook_reel', return_value=(True, '')) as reel, \
                patch.object(Articolo, 'has_shareable_image', True):
            self.assertEqual(self.manager.pubblica_reel_rimandati(adesso=self._ora(22, 30)), 0)
        reel.assert_not_called()


class TestoPostFacebookTests(SimpleTestCase):
    """Il post della Pagina apre con il sommario: il titolo lo mostra gia' la scheda del link."""

    def _messaggio(self, articolo):
        manager = SocialMediaManager()
        manager.platforms['facebook'].update(access_token='t', page_id='1')
        risposta = Mock(status_code=200, text='{}')
        risposta.json.return_value = {'id': '1_2'}
        with patch.object(manager, '_get_page_access_token', return_value='pt'), \
                patch.object(manager, '_refresh_facebook_link_preview'), \
                patch.object(manager, '_prepara_anteprima_gruppi'), \
                patch('home.luoghi_meta.place_id_per', return_value=''), \
                patch('home.social_sharing.requests.post', return_value=risposta) as post:
            self.assertTrue(manager._share_to_facebook(articolo, 'https://ombradelportico.it/articolo/x/'))
        return post.call_args.kwargs['data']['message']

    def test_sommario_poi_domanda_senza_titolo(self):
        a = Articolo(titolo='Nuova piazza a Limidi', sommario='Via Papotti diventa una piazza.',
                     spunto_social='Voi come la vorreste?')
        self.assertEqual(self._messaggio(a), 'Via Papotti diventa una piazza.\n\nVoi come la vorreste?')

    def test_senza_sommario_resta_il_titolo(self):
        a = Articolo(titolo='Nuova piazza a Limidi', sommario='', spunto_social='')
        self.assertEqual(self._messaggio(a), 'Nuova piazza a Limidi')
