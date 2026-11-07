from unittest.mock import Mock, patch
from io import BytesIO, StringIO
import hashlib
import hmac
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
    """Condivisione a mano nei gruppi: gruppi proposti, testo, link tracciato, pagina admin."""

    def setUp(self):
        from home.models import GruppoFacebook
        self.articolo = Articolo.objects.create(
            titolo='Festa della zucca a Fossoli', contenuto='<p>T</p>',
            sommario='Domenica in piazza a Fossoli torna la festa. Stand, musica e giochi per tutta la giornata.',
            categoria='Cultura & Eventi', comune='Carpi', approvato=True, data_pubblicazione=timezone.now())
        self.fossoli = GruppoFacebook.objects.create(nome='Sei di Fossoli se', url='https://www.facebook.com/groups/1',
                                                     comune='Carpi', parole_chiave='Fossoli, Budrione')
        self.carpi = GruppoFacebook.objects.create(nome='Carpi Notizie', url='https://www.facebook.com/groups/2',
                                                   comune='Carpi', come_pagina=False)
        self.zona = GruppoFacebook.objects.create(nome='Terre d Argine', url='https://www.facebook.com/groups/3')
        self.soliera = GruppoFacebook.objects.create(nome='Soliera', url='https://www.facebook.com/groups/4',
                                                     comune='Soliera')

    def test_ordine_parola_chiave_comune_zona(self):
        from home.gruppi_facebook import gruppi_ordinati
        righe = gruppi_ordinati(self.articolo, [self.soliera, self.zona, self.carpi, self.fossoli])
        self.assertEqual([r[0] for r in righe], [self.fossoli, self.carpi, self.zona, self.soliera])
        self.assertEqual(righe[0][2], 'parla di Fossoli')
        self.assertEqual(righe[3][1], 0)

    def test_slug_unico_dal_nome(self):
        from home.models import GruppoFacebook
        doppio = GruppoFacebook.objects.create(nome='Sei di Fossoli se', url='https://www.facebook.com/groups/9')
        self.assertEqual(self.fossoli.slug, 'sei-di-fossoli-se')
        self.assertEqual(doppio.slug, 'sei-di-fossoli-se-2')

    def test_testo_e_link_tracciato_per_gruppo(self):
        from home.gruppi_facebook import testo_condivisione
        testo = testo_condivisione(self.articolo, self.fossoli)
        link = ShortLink.objects.get(articolo=self.articolo, platform='facebook_gruppo', medium='sei-di-fossoli-se')
        self.assertTrue(testo.startswith('Festa della zucca a Fossoli'))
        self.assertTrue(testo.endswith(f'/s/{link.token}/'))
        r = self.client.get(f'/s/{link.token}/')
        self.assertIn('utm_source=facebook_gruppo&utm_medium=sei-di-fossoli-se', r['Location'])

    def test_dal_profilo_riga_di_presentazione(self):
        from home.gruppi_facebook import testo_condivisione
        self.assertTrue(testo_condivisione(self.articolo, self.carpi, 'L').startswith('Dal sito di notizie locali che curo, @Ombra del Portico'))
        self.assertFalse(testo_condivisione(self.articolo, self.fossoli, 'L').startswith('Dal sito di notizie locali che curo, @Ombra del Portico'))

    def test_pagina_admin_e_segna_fatto(self):
        from home.models import CondivisioneGruppo
        self.client.force_login(User.objects.create_superuser('admin', 'a@example.it', 'x'))
        url = reverse('admin:gruppi_condividi')
        html = self.client.get(url).content.decode()
        self.assertIn('Festa della zucca a Fossoli', html)
        self.assertLess(html.index('Sei di Fossoli se'), html.index('Altri gruppi'))
        self.assertLess(html.index('Altri gruppi'), html.index('>Soliera<'))
        r = self.client.post(url + '?giorni=2', {'articolo': self.articolo.pk, 'gruppo': self.fossoli.pk, 'azione': 'fatto'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(CondivisioneGruppo.objects.filter(articolo=self.articolo, gruppo=self.fossoli).exists())
        self.assertIn('Condiviso il', self.client.get(url).content.decode())
        self.client.post(url, {'articolo': self.articolo.pk, 'gruppo': self.fossoli.pk, 'azione': 'annulla'})
        self.assertFalse(CondivisioneGruppo.objects.exists())

    def test_gruppo_di_frazione_solo_se_nominata(self):
        from home.gruppi_facebook import punteggio
        altro = Articolo.objects.create(
            titolo='Lavori in via Roma a Carpi', contenuto='<p>T</p>', sommario='Cantiere in centro.',
            categoria='Attualità', comune='Carpi', approvato=True, data_pubblicazione=timezone.now())
        self.assertEqual(punteggio(altro, self.fossoli)[0], 0)
        self.assertEqual(punteggio(altro, self.carpi)[0], 2)

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

    def _contenuto(self, dimensione='135 KiB', pdf=b'%PDF-1.4 atto', testo_pdf='x' * 300, **config):
        """get_full_content dell'ordinanza con scheda e PDF finti; ritorna (testo, url chiesti)."""
        from datetime import datetime
        oggi = datetime.now().strftime('%d/%m/%Y')
        scraper = self._scraper(**config)
        with patch.object(scraper, '_get_request', return_value=self._risposta(ALBO_HTML.format(oggi=oggi))):
            url = scraper.scrape_articles()[0]['url']
        dettaglio = self._risposta(ALBO_DETTAGLIO_HTML.format(dimensione=dimensione))
        file_pdf = Mock(content=pdf, raise_for_status=Mock())
        with patch.object(scraper, '_get_request', side_effect=[dettaglio, file_pdf]) as get, \
                patch.object(scraper, '_testo_pdf', return_value=testo_pdf):
            testo = scraper.get_full_content(url)
        return testo, [c.args[0] for c in get.call_args_list]

    def test_dettaglio_aggiunge_solo_i_campi_nuovi(self):
        testo, _ = self._contenuto(leggi_pdf=False)
        self.assertIn('Protocollo: 72505/2026', testo)
        self.assertIn('Documenti allegati: ordinanza.pdf.p7m; planimetria.pdf', testo)
        self.assertNotIn('U.O.R.', testo)
        self.assertNotIn("gia' nell'elenco", testo)

    def test_testo_dell_atto_dal_pdf_gia_estratto(self):
        testo, chiesti = self._contenuto(testo_pdf='ORDINA il senso unico alternato ' * 20)
        # Il documento ATTO, link al PDF senza firma (non il .p7m, non l'allegato)
        self.assertEqual(chiesti, ['https://albo.test/?pub_token=b', 'https://albo.test/?pub_token=pdf'])
        self.assertIn("TESTO DELL'ATTO", testo)
        self.assertIn('ORDINA il senso unico alternato', testo)

    def test_pdf_troppo_grande_o_scansione_saltati(self):
        testo, chiesti = self._contenuto(dimensione='10.57 MiB')
        self.assertEqual(len(chiesti), 1)  # solo la scheda, il PDF non si scarica
        self.assertNotIn("TESTO DELL'ATTO", testo)

        testo, _ = self._contenuto(testo_pdf='Firmato digitalmente')  # scansione: solo il timbro
        self.assertNotIn("TESTO DELL'ATTO", testo)
        self.assertIn('Protocollo: 72505/2026', testo)

    def test_accenti_codificati_due_volte(self):
        from home.universal_news_monitor import AlboItalsoftScraper
        self.assertEqual(AlboItalsoftScraper._testo('festivitÃ   natalizie'), 'festività natalizie')
        self.assertEqual(AlboItalsoftScraper._testo('MOBILITÃ\u0080-VIABILITÃ\u0080'), 'MOBILITÀ-VIABILITÀ')
        self.assertEqual(AlboItalsoftScraper._testo(' città  già\n giusta '), 'città già giusta')

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
