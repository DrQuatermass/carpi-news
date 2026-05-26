from unittest.mock import patch
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
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from home.content_polisher import content_polisher
from home.image_variants import generate_article_image_variants
from home.management.commands.retry_failed_social_shares import Command as RetryFailedSocialSharesCommand
from home.models import Articolo, InstagramOptOut, ShortLink, SocialPublicationLog
from home.seo_locations import detect_municipality
from home.share_links import build_share_url, build_short_share_url
from home.universal_news_monitor import parse_ai_article_json


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

    def test_article_detail_uses_editorial_headline_everywhere(self):
        self.articolo.titolo = "Headline editoriale unica"
        self.articolo.titolo_seo = "Titolo SEO diverso"
        self.articolo.save(update_fields=["titolo", "titolo_seo"])
        cache.delete(f"articolo_ctx_{self.articolo.slug}")

        response = self.client.get(reverse("dettaglio_articolo", kwargs={"slug": self.articolo.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Headline editoriale unica — Ombra del Portico</title>")
        self.assertContains(response, '<meta property="og:title" content="Headline editoriale unica">')
        self.assertContains(response, '<meta name="twitter:title" content="Headline editoriale unica">')
        self.assertContains(response, '<h1 class="article-title">Headline editoriale unica</h1>')
        self.assertContains(response, '"headline": "Headline editoriale unica"')
        self.assertNotContains(response, "Titolo SEO diverso")

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

    def test_newsarticle_image_urls_lazy_generates_missing_variants(self):
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

                self.assertEqual(len(urls), 3)
                self.assertEqual(self.articolo.image_16x9.name, "images/articles/titolo-test-16x9.webp")
                self.assertTrue((media_root / self.articolo.image_4x3.name).exists())

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
class RetryFailedSocialSharesCommandTests(TestCase):
    def setUp(self):
        self.articolo = Articolo.objects.create(
            titolo="Articolo fallito",
            contenuto="Contenuto",
            sommario="Sommario",
            categoria="Cronaca",
            approvato=True,
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
            published_at=timezone.now() - timedelta(minutes=30)
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
            published_at=timezone.now() - timedelta(minutes=30)
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
            published_at=timezone.now() - timedelta(minutes=30)
        )

        old_article = Articolo.objects.create(
            titolo="Articolo vecchio fallito",
            contenuto="Contenuto",
            sommario="Sommario",
            categoria="Cronaca",
            approvato=True,
            data_pubblicazione=timezone.now(),
        )
        old_log = SocialPublicationLog.objects.create(
            articolo=old_article,
            platform="instagram_story",
            success=False,
            error_message="Container non ready",
        )
        SocialPublicationLog.objects.filter(pk=old_log.pk).update(
            published_at=timezone.now() - timedelta(minutes=120)
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
            published_at=timezone.now() - timedelta(minutes=30)
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
            published_at=timezone.now() - timedelta(minutes=30)
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
