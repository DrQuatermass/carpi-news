import hashlib
import hmac
import json
import logging
import re
import threading
import time
import unicodedata
from datetime import timedelta
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import InstagramAutoDMLog, InstagramOptOut, SocialPublicationLog
from .share_links import build_short_share_url, get_or_create_short_link

logger = logging.getLogger("home.instagram_webhook")

TRANSIENT_GRAPH_ERROR_CODES = {1, 2, 4, 17, 32, 613}


def _log_safe(value) -> str:
    return str(value).encode("unicode_escape").decode("ascii")[:300]


def _log_settings_status() -> None:
    if cache.add("ig_webhook_settings_status_logged", True, 3600):
        logger.info(
            "Instagram webhook: configurazione FACEBOOK_APP_SECRET=%s INSTAGRAM_APP_SECRET=%s PAGE_TOKEN=%s",
            "presente" if getattr(settings, "FACEBOOK_APP_SECRET", "") else "assente",
            "presente" if getattr(settings, "INSTAGRAM_APP_SECRET", "") else "assente",
            "presente" if (
                getattr(settings, "INSTAGRAM_PAGE_ACCESS_TOKEN", "")
                or getattr(settings, "FACEBOOK_ACCESS_TOKEN", "")
            ) else "assente",
        )


def _valid_signature(request) -> bool:
    _log_settings_status()
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

        return bool(getattr(settings, "INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI", False)) and emoji.purely_emoji(cleaned)
    except Exception:
        return bool(getattr(settings, "INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI", False)) and all(
            _is_emoji_char(char) for char in cleaned if ord(char) != 0xFE0F
        )


def _emoji_trigger_attivo() -> bool:
    """Reazioni ed emoji fanno partire il DM solo con INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI."""
    return bool(getattr(settings, "INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI", False))


def _contains_emoji(text: str) -> bool:
    if not getattr(settings, "INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI", False):
        return False
    try:
        import emoji

        return emoji.emoji_count(text or "") > 0
    except Exception:
        return any(_is_emoji_char(char) for char in (text or ""))


def _is_emoji_char(char: str) -> bool:
    code = ord(char)
    return (
        code in (0x2764, 0xFE0F)
        or 0x1F300 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
    )


def _configured_text_triggers() -> list[str]:
    raw_triggers = getattr(settings, "INSTAGRAM_AUTO_DM_TEXT_TRIGGERS", ["LINK", "INFO", "LEGGI"])
    raw_items = raw_triggers.split(",") if isinstance(raw_triggers, str) else raw_triggers

    triggers = []
    for item in raw_items:
        trigger = str(item).strip().upper().strip("[](){}'\" ")
        if trigger:
            triggers.append(trigger)
    return triggers or ["LINK", "INFO", "LEGGI"]


def _text_trigger(text: str) -> bool:
    return _text_trigger_match(text)[0]


def _text_trigger_match(text: str) -> tuple[bool, str]:
    upper = (text or "").strip().upper()
    if upper == "STOP":
        return True, "stop"
    words = set(re.findall(r"[\wÀ-ÿ]+", upper, flags=re.UNICODE))
    for trigger in _configured_text_triggers():
        if trigger in words:
            return True, f"testo:{trigger}"
    if _contains_emoji(text) or _emoji_only(text):
        return True, "emoji"
    return False, "nessuna"


def _sample_payload(kind: str, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=True)[:2000]
    if cache.add(f"ig_webhook_sample_payload:{kind}", True, 86400):
        logger.info("Instagram webhook: campione payload %s=%s", kind, serialized)
    else:
        logger.debug("Instagram webhook: payload %s=%s", kind, serialized)


def _first_attachment_url(message: dict[str, Any]) -> str:
    attachments = message.get("attachments") or []
    if not attachments:
        return ""
    first = attachments[0] or {}
    return first.get("payload", {}).get("url", "")


def _extract_events(payload: dict[str, Any]):
    for entry in payload.get("entry", []):
        for item in entry.get("messaging", []):
            _sample_payload("messaging", item)
            sender_id = item.get("sender", {}).get("id")
            reaction = item.get("reaction", {}) or {}
            message = item.get("message", {}) or {}
            postback = item.get("postback", {}) or {}
            text = message.get("text") or item.get("text") or ""
            media_id = (
                message.get("reply_to", {}).get("story", {}).get("id")
                or message.get("reply_to", {}).get("media", {}).get("id")
                or message.get("reply_to", {}).get("id")
                or reaction.get("story", {}).get("id")
                or reaction.get("media", {}).get("id")
                or item.get("media", {}).get("id")
                or item.get("media_id")
            )
            emoji_value = reaction.get("emoji") or item.get("emoji") or ""

            if emoji_value:
                if not media_id:
                    logger.info("Instagram webhook: reaction story senza media_id sender=%s", sender_id)
                yield sender_id, media_id, "story_reaction", emoji_value, _emoji_trigger_attivo()
            elif text:
                is_trigger, rule = _text_trigger_match(text)
                logger.info(
                    "Instagram webhook: trigger testo messaging sender=%s media=%s value=%s esito=%s regola=%s",
                    sender_id,
                    media_id,
                    _log_safe(text),
                    is_trigger,
                    rule,
                )
                yield sender_id, media_id, "story_reply", text, is_trigger
            elif postback:
                value = postback.get("payload") or postback.get("title") or ""
                is_trigger, rule = _text_trigger_match(value)
                logger.info(
                    "Instagram webhook: postback sender=%s media=%s value=%s esito=%s regola=%s",
                    sender_id,
                    media_id,
                    _log_safe(value),
                    is_trigger,
                    rule,
                )
                yield sender_id, media_id, "story_reply", value, is_trigger

        for change in entry.get("changes", []):
            field = change.get("field")
            if field not in {"messages", "message_reactions", "comments"}:
                continue
            value = change.get("value", {}) or {}
            _sample_payload(f"change_{field}", value)

            sender_id = (
                value.get("sender", {}).get("id")
                or value.get("from", {}).get("id")
                or value.get("user", {}).get("id")
            )
            message = value.get("message", {}) or {}
            media_id = (
                value.get("media", {}).get("id")
                or value.get("media_id")
                or value.get("parent_id")
                or message.get("reply_to", {}).get("story", {}).get("id")
                or message.get("reply_to", {}).get("media", {}).get("id")
                or message.get("reply_to", {}).get("id")
            )
            reaction = value.get("reaction", {}) or {}
            text = value.get("text") or message.get("text") or value.get("comment_text") or ""
            emoji_value = reaction.get("emoji") or value.get("emoji") or ""

            if emoji_value:
                if not media_id:
                    logger.info("Instagram webhook: reazione senza media_id field=%s sender=%s", field, sender_id)
                yield sender_id, media_id, "story_reaction", emoji_value, _emoji_trigger_attivo()
            elif text:
                trigger_type = "reel_comment" if field == "comments" else "story_reply"
                is_trigger, rule = _text_trigger_match(text)
                logger.info(
                    "Instagram webhook: trigger testo change field=%s sender=%s media=%s attachment_url=%s value=%s esito=%s regola=%s",
                    field,
                    sender_id,
                    media_id,
                    _first_attachment_url(message),
                    _log_safe(text),
                    is_trigger,
                    rule,
                )
                yield sender_id, media_id, trigger_type, text, is_trigger


def _parse_graph_error(response) -> tuple[str, int | None, int | None, str]:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500], None, None, ""
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    code = error.get("code")
    subcode = error.get("error_subcode")
    fbtrace_id = error.get("fbtrace_id", "")
    message = error.get("message") or json.dumps(payload, ensure_ascii=False)
    return message[:500], code, subcode, fbtrace_id


def _send_dm(sender_id: str, articolo, short_url: str) -> tuple[bool, str]:
    token = getattr(settings, "INSTAGRAM_PAGE_ACCESS_TOKEN", "") or getattr(settings, "FACEBOOK_ACCESS_TOKEN", "")
    if not token:
        return False, "INSTAGRAM_PAGE_ACCESS_TOKEN mancante"

    url = "https://graph.facebook.com/v24.0/me/messages"
    text = (
        "Ciao! Ecco l'articolo che ti interessava:\n\n"
        f"{articolo.titolo}\n{short_url}\n\n"
        "Grazie per seguirci su Ombra del Portico!"
    )
    payload = {
        "messaging_type": "RESPONSE",
        "messaging_product": "instagram",
        "recipient": {"id": sender_id},
        "message": {"text": text},
    }
    last_error = ""
    for attempt in range(2):
        try:
            response = requests.post(
                url,
                params={"access_token": token},
                json=payload,
                timeout=(3, 10),
            )
            if response.status_code == 200:
                return True, response.text[:500]
            message, code, subcode, fbtrace_id = _parse_graph_error(response)
            last_error = (
                f"HTTP {response.status_code}: code={code} subcode={subcode} "
                f"fbtrace_id={fbtrace_id} message={message}"
            )
            logger.warning("Instagram webhook: errore Graph DM %s", last_error)
            if response.status_code >= 500 or code in TRANSIENT_GRAPH_ERROR_CODES:
                time.sleep(1)
                continue
            break
        except requests.RequestException as e:
            last_error = f"Errore HTTP: {e}"
            logger.warning("Instagram webhook: eccezione invio DM tentativo %s: %s", attempt + 1, e)
            time.sleep(1)
    return False, last_error


IG_PLATFORMS = ["instagram", "instagram_story", "instagram_reel"]
MEDIA_PRODUCT_PLATFORM = {"FEED": "instagram", "REELS": "instagram_reel", "STORY": "instagram_story"}


def _articolo_da_didascalia(media_id: str):
    """Riconosce l'articolo di un contenuto Instagram non collegato leggendone la didascalia.

    Post, Reel e Storie pubblicati dal sito hanno il titolo dell'articolo in prima riga. Serve
    per i contenuti di cui non si e' salvato l'id (i post con foto fino al 23/11/2026, quelli
    pubblicati a mano). Restituisce (articolo, piattaforma), (None, "") se la didascalia non
    corrisponde a nessun articolo, None se Meta non risponde.
    """
    from .models import Articolo

    cache_key = f"igdm_media_articolo:{media_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        articolo_id, platform = cached
        if not articolo_id:
            return None, ""
        articolo = Articolo.objects.filter(pk=articolo_id).first()
        return (articolo, platform) if articolo else (None, "")

    token = getattr(settings, "INSTAGRAM_PAGE_ACCESS_TOKEN", "") or getattr(settings, "FACEBOOK_ACCESS_TOKEN", "")
    if not token:
        return None
    try:
        response = requests.get(
            f"https://graph.facebook.com/v24.0/{media_id}",
            params={"fields": "caption,media_product_type", "access_token": token},
            timeout=(3, 10),
        )
        data = response.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Instagram webhook: lettura didascalia di %s non riuscita: %s", media_id, e)
        return None
    if response.status_code != 200 or not isinstance(data, dict) or "error" in data:
        logger.warning("Instagram webhook: lettura didascalia di %s non riuscita: %s", media_id, str(data)[:300])
        return None

    platform = MEDIA_PRODUCT_PLATFORM.get(str(data.get("media_product_type") or "").upper(), "")
    prima_riga = (data.get("caption") or "").strip().split("\n", 1)[0].strip()
    articolo = None
    if prima_riga:
        qs = Articolo.objects.filter(approvato=True).order_by("-data_pubblicazione")
        articolo = qs.filter(titolo=prima_riga).first() or qs.filter(titolo__iexact=prima_riga).first()
    cache.set(cache_key, (articolo.pk if articolo else 0, platform), 30 * 86400)
    if not articolo:
        logger.warning(
            "Instagram webhook: media %s senza articolo, didascalia=%s", media_id, _log_safe(prima_riga)
        )
        return None, ""

    # Si salva l'id nel log della pubblicazione, cosi' le volte dopo basta il database
    log = (
        SocialPublicationLog.objects.filter(articolo=articolo, platform=platform).first()
        if platform else None
    )
    if log:
        media_ids = list(log.instagram_media_ids or [])
        if media_id not in media_ids:
            log.instagram_media_ids = (media_ids + [media_id])[-50:]
            log.save(update_fields=["instagram_media_ids", "updated_at"])
    logger.info(
        "Instagram webhook: media %s riconosciuto dalla didascalia, articolo %s (%s)",
        media_id, articolo.pk, platform or "tipo sconosciuto",
    )
    return articolo, platform


def _find_articolo(media_id: str, trigger_type: str):
    """L'articolo a cui si riferisce un commento, una risposta o una reazione.

    Prima l'id del contenuto nei log di pubblicazione, poi la didascalia letta da Meta. Il
    ripiego sull'ultimo Reel o sull'ultima Storia pubblicati vale solo quando Meta non manda
    l'id o non risponde: con un id riconosciuto ma senza articolo non parte nessun DM, perche'
    un articolo a caso e' peggio di nessun messaggio.
    """
    if media_id:
        media_id = str(media_id)
        # Niente filtro su success: un contenuto con l'id e' online anche se la
        # ripubblicazione successiva dello stesso articolo e' fallita
        base_qs = SocialPublicationLog.objects.filter(platform__in=IG_PLATFORMS).select_related("articolo")
        log = base_qs.filter(instagram_media_id=media_id).order_by("-updated_at").first()
        if log:
            return log.articolo
        for candidate in base_qs.exclude(instagram_media_ids=[]).order_by("-updated_at")[:500]:
            if media_id in [str(m) for m in (candidate.instagram_media_ids or [])]:
                return candidate.articolo

        trovato = _articolo_da_didascalia(media_id)
        if trovato is not None:
            return trovato[0]

    log = _fallback_publication_log(media_id, trigger_type)
    return log.articolo if log else None


def _fallback_publication_log(media_id: str, trigger_type: str):
    if trigger_type == "reel_comment":
        fallback_minutes = int(getattr(settings, "INSTAGRAM_AUTO_DM_REEL_FALLBACK_MINUTES", 4320))
        platform = "instagram_reel"
        label = "reel"
    else:
        fallback_minutes = int(getattr(settings, "INSTAGRAM_AUTO_DM_STORY_FALLBACK_MINUTES", 1440))
        platform = "instagram_story"
        label = "story"

    if fallback_minutes <= 0:
        return None

    since = timezone.now() - timedelta(minutes=fallback_minutes)
    fallback_log = SocialPublicationLog.objects.filter(
        platform=platform,
        success=True,
        updated_at__gte=since,
    ).select_related("articolo").order_by("-updated_at").first()
    if fallback_log:
        logger.warning(
            "Instagram webhook: media_id %s non mappato, fallback %s recente %s per articolo %s",
            media_id,
            label,
            fallback_log.instagram_media_id,
            fallback_log.articolo_id,
        )
    return fallback_log


def _dedup_key(sender_id: str, media_id: str, trigger_type: str, trigger_value: str) -> str:
    minute = timezone.now().strftime("%Y%m%d%H%M")
    raw = "|".join([sender_id or "", media_id or "", trigger_type or "", trigger_value or "", minute])
    return f"igdm_event:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _handle_event(sender_id: str, media_id: str, trigger_type: str, trigger_value: str, is_trigger: bool) -> None:
    if not sender_id:
        logger.warning("Instagram webhook: evento senza sender_id")
        return

    own_ids = {
        str(value)
        for value in (
            getattr(settings, "INSTAGRAM_ACCOUNT_ID", ""),
            getattr(settings, "FACEBOOK_PAGE_ID", ""),
        )
        if value
    }
    if sender_id in own_ids:
        logger.info("Instagram webhook: evento generato dall'account business ignorato sender=%s", sender_id)
        return

    if (trigger_value or "").strip().upper() == "STOP":
        InstagramOptOut.objects.get_or_create(ig_user_id=sender_id)
        logger.info("Instagram webhook: opt-out registrato per %s", sender_id)
        return

    if not is_trigger:
        logger.info(
            "Instagram webhook: trigger ignorato sender=%s type=%s value=%s",
            sender_id,
            trigger_type,
            _log_safe(trigger_value),
        )
        return
    if not cache.add(_dedup_key(sender_id, media_id, trigger_type, trigger_value), True, 86400):
        logger.info("Instagram webhook: evento duplicato ignorato sender=%s media=%s type=%s", sender_id, media_id, trigger_type)
        return
    if InstagramOptOut.objects.filter(ig_user_id=sender_id).exists():
        logger.info("Instagram webhook: utente %s in opt-out, DM saltato", sender_id)
        return

    articolo = _find_articolo(media_id, trigger_type)
    if not articolo:
        logger.warning("Instagram webhook: media_id non mappato, nessun DM inviato: %s", media_id)
        return

    # Un DM per persona e articolo al minuto: chi commenta due contenuti diversi riceve
    # entrambi i link
    rate_key = f"igdm:{sender_id}:{articolo.pk}"
    if not cache.add(rate_key, True, 60):
        logger.info("Instagram webhook: rate limit DM per %s articolo %s", sender_id, articolo.pk)
        return

    short_link = get_or_create_short_link(articolo, "instagram", "instagram_dm")
    short_url = build_short_share_url(articolo, "instagram", "instagram_dm")
    sent, info = _send_dm(sender_id, articolo, short_url)
    if not sent:
        cache.delete(rate_key)
    InstagramAutoDMLog.objects.create(
        articolo=articolo,
        ig_user_id=sender_id,
        trigger_type=trigger_type,
        trigger_value=(trigger_value or "")[:255],
        media_id=media_id or "",
        short_link=short_link,
        dm_sent=sent,
        dm_error="" if sent else info,
    )
    if sent:
        logger.info("Instagram webhook: DM inviato a %s per articolo %s", sender_id, articolo.pk)
    else:
        logger.warning("Instagram webhook: DM fallito per %s: %s", sender_id, info)


def _handle_events_background(events) -> None:
    close_old_connections()
    try:
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
    finally:
        close_old_connections()


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
    elif getattr(settings, "INSTAGRAM_WEBHOOK_HANDLE_SYNC", False):
        _handle_events_background(events)
    else:
        threading.Thread(target=_handle_events_background, args=(events,), daemon=True).start()

    return JsonResponse({"ok": True})
