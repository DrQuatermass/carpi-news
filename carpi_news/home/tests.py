from unittest.mock import patch
from io import StringIO
import hashlib
import hmac
import json
from datetime import timedelta

from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from home.content_polisher import content_polisher
from home.management.commands.retry_failed_social_shares import Command as RetryFailedSocialSharesCommand
from home.models import Articolo, InstagramOptOut, ShortLink, SocialPublicationLog
from home.share_links import build_share_url, build_short_share_url
from home.social_sharing import social_manager
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

    def test_facebook_reel_deferred_for_future_event(self):
        self.articolo.data_evento = timezone.localdate() + timedelta(days=3)
        self.assertTrue(social_manager._defer_facebook_reel_until_event_reminder(self.articolo))

    def test_facebook_reel_not_deferred_without_future_event(self):
        self.articolo.data_evento = None
        self.assertFalse(social_manager._defer_facebook_reel_until_event_reminder(self.articolo))


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
