import hashlib
import hmac
import json
import logging
import unicodedata
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import InstagramAutoDMLog, InstagramOptOut, SocialPublicationLog
from .share_links import build_short_share_url, get_or_create_short_link

logger = logging.getLogger("home.instagram_webhook")


def _log_safe(value) -> str:
    return str(value).encode("unicode_escape").decode("ascii")[:300]


def _valid_signature(request) -> bool:
    secrets = [
        ("FACEBOOK_APP_SECRET", getattr(settings, "FACEBOOK_APP_SECRET", "")),
        ("INSTAGRAM_APP_SECRET", getattr(settings, "INSTAGRAM_APP_SECRET", "")),
    ]
    secrets = [(name, secret) for name, secret in secrets if secret]
    if not secrets:
        logger.warning("Instagram webhook: nessun app secret configurato")
        return False
    header = request.headers.get("X-Hub-Signature-256", "")
    if not header.startswith("sha256="):
        return False
    for name, secret in secrets:
        expected = hmac.new(secret.encode("utf-8"), request.body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(header, f"sha256={expected}"):
            logger.info("Instagram webhook: signature valida con %s", name)
            return True
    return False


def _emoji_only(text: str) -> bool:
    cleaned = "".join(
        char
        for char in (text or "").strip()
        if not unicodedata.category(char).startswith(("P", "Z"))
    )
    if not cleaned:
        return False
    try:
        import emoji

        return bool(getattr(settings, "INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI", True)) and emoji.purely_emoji(cleaned)
    except Exception:
        return bool(getattr(settings, "INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI", True)) and all(
            _is_emoji_char(char) for char in cleaned if ord(char) != 0xFE0F
        )


def _is_emoji_char(char: str) -> bool:
    code = ord(char)
    return (
        code in (0x2764, 0xFE0F)
        or 0x1F300 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
    )


def _configured_text_triggers() -> list[str]:
    raw_triggers = getattr(settings, "INSTAGRAM_AUTO_DM_TEXT_TRIGGERS", ["LINK", "INFO", "LEGGI"])
    if isinstance(raw_triggers, str):
        raw_items = raw_triggers.split(",")
    else:
        raw_items = raw_triggers

    triggers = []
    for item in raw_items:
        trigger = str(item).strip().upper().strip("[](){}'\" ")
        if trigger:
            triggers.append(trigger)
    return triggers or ["LINK", "INFO", "LEGGI"]


def _text_trigger(text: str) -> bool:
    upper = (text or "").strip().upper()
    if upper == "STOP":
        return True
    if any(trigger in upper for trigger in _configured_text_triggers()):
        return True
    return _emoji_only(text)


def _extract_events(payload: dict[str, Any]):
    for entry in payload.get("entry", []):
        for item in entry.get("messaging", []):
            sender_id = item.get("sender", {}).get("id")
            reaction = item.get("reaction", {}) or {}
            message = item.get("message", {}) or {}
            text = message.get("text") or item.get("text") or ""
            media_id = (
                message.get("reply_to", {}).get("story", {}).get("id")
                or message.get("reply_to", {}).get("media", {}).get("id")
                or message.get("reply_to", {}).get("id")
                or item.get("media", {}).get("id")
                or item.get("media_id")
            )
            emoji_value = reaction.get("emoji") or item.get("emoji") or ""

            if emoji_value:
                yield sender_id, media_id, "story_reaction", emoji_value, True
            elif text:
                yield sender_id, media_id, "story_reply", text, _text_trigger(text)

        for change in entry.get("changes", []):
            field = change.get("field")
            if field not in {"messages", "message_reactions", "comments"}:
                continue
            value = change.get("value", {}) or {}

            sender_id = (
                value.get("sender", {}).get("id")
                or value.get("from", {}).get("id")
                or value.get("user", {}).get("id")
            )
            media_id = (
                value.get("media", {}).get("id")
                or value.get("message", {}).get("attachments", [{}])[0].get("payload", {}).get("url", "")
                or value.get("media_id")
            )
            reaction = value.get("reaction", {}) or {}
            message = value.get("message", {}) or {}
            text = value.get("text") or message.get("text") or value.get("comment_text") or ""
            emoji_value = reaction.get("emoji") or value.get("emoji") or ""

            if emoji_value:
                yield sender_id, media_id, "story_reaction", emoji_value, True
            elif text:
                trigger_type = "reel_comment" if field == "comments" else "story_reply"
                yield sender_id, media_id, trigger_type, text, _text_trigger(text)


def _send_dm(sender_id: str, articolo, short_url: str) -> tuple[bool, str]:
    token = getattr(settings, "INSTAGRAM_PAGE_ACCESS_TOKEN", "") or getattr(settings, "FACEBOOK_ACCESS_TOKEN", "")
    if not token:
        return False, "INSTAGRAM_PAGE_ACCESS_TOKEN mancante"

    url = "https://graph.facebook.com/v24.0/me/messages"
    text = (
        "Ciao! 👋 Ecco l'articolo che ti interessava:\n\n"
        f"{articolo.titolo}\n{short_url}\n\n"
        "Grazie per seguirci su Ombra del Portico! 🙏"
    )
    try:
        response = requests.post(
            url,
            params={"access_token": token},
            json={"recipient": {"id": sender_id}, "message": {"text": text}},
            timeout=3,
        )
        if response.status_code == 200:
            return True, response.text[:500]
        return False, f"{response.status_code}: {response.text[:500]}"
    except requests.RequestException as e:
        return False, str(e)


def _handle_event(sender_id: str, media_id: str, trigger_type: str, trigger_value: str, is_trigger: bool) -> None:
    if not sender_id:
        logger.warning("Instagram webhook: evento senza sender_id")
        return

    if (trigger_value or "").strip().upper() == "STOP":
        InstagramOptOut.objects.get_or_create(ig_user_id=sender_id)
        logger.info("Instagram webhook: opt-out registrato per %s", sender_id)
        return

    if not is_trigger:
        logger.info("Instagram webhook: trigger ignorato sender=%s type=%s value=%s", sender_id, trigger_type, trigger_value)
        return
    if InstagramOptOut.objects.filter(ig_user_id=sender_id).exists():
        logger.info("Instagram webhook: utente %s in opt-out, DM saltato", sender_id)
        return
    if not cache.add(f"igdm:{sender_id}", True, 60):
        logger.info("Instagram webhook: rate limit DM per %s", sender_id)
        return

    log = SocialPublicationLog.objects.filter(
        instagram_media_id=media_id,
        platform__in=["instagram_story", "instagram_reel"],
        success=True,
    ).select_related("articolo").order_by("-published_at").first()
    if not log:
        logger.warning("Instagram webhook: media_id non mappato, nessun DM inviato: %s", media_id)
        return

    short_link = get_or_create_short_link(log.articolo, "instagram", "instagram_dm")
    short_url = build_short_share_url(log.articolo, "instagram", "instagram_dm")
    sent, info = _send_dm(sender_id, log.articolo, short_url)
    InstagramAutoDMLog.objects.create(
        articolo=log.articolo,
        ig_user_id=sender_id,
        trigger_type=trigger_type,
        trigger_value=(trigger_value or "")[:255],
        media_id=media_id or "",
        short_link=short_link,
        dm_sent=sent,
        dm_error="" if sent else info,
    )
    if sent:
        logger.info("Instagram webhook: DM inviato a %s per articolo %s", sender_id, log.articolo_id)
    else:
        logger.warning("Instagram webhook: DM fallito per %s: %s", sender_id, info)


@csrf_exempt
def instagram_webhook(request):
    if request.method == "GET":
        expected = getattr(settings, "INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "")
        token = request.GET.get("hub.verify_token", "")
        challenge = request.GET.get("hub.challenge", "")
        if expected and hmac.compare_digest(token, expected):
            return HttpResponse(challenge, content_type="text/plain")
        return HttpResponseForbidden("Verify token non valido")

    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    if not _valid_signature(request):
        logger.warning("Instagram webhook: signature non valida")
        return HttpResponseForbidden("Signature non valida")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning("Instagram webhook: JSON non valido")
        return JsonResponse({"ok": True})

    events = list(_extract_events(payload))
    logger.info(
        "Instagram webhook: POST ricevuto object=%s entries=%s events=%s",
        payload.get("object"),
        len(payload.get("entry", [])),
        len(events),
    )
    if not events:
        logger.info("Instagram webhook: nessun evento estraibile payload=%s", json.dumps(payload)[:1000])

    for event in events:
        try:
            logger.info(
                "Instagram webhook: evento estratto sender=%s media=%s type=%s value=%s trigger=%s",
                event[0],
                event[1],
                event[2],
                _log_safe(event[3]),
                event[4],
            )
            _handle_event(*event)
        except Exception:
            logger.exception("Instagram webhook: errore gestione evento")

    return JsonResponse({"ok": True})
