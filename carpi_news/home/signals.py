import logging
import threading
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.cache import cache
from django.core.cache.utils import make_template_fragment_key
from django.core.files.base import ContentFile
from .models import Articolo
from .email_notifications import send_article_approval_notification
from .social_sharing import social_manager
from .indexing_notifier import notifier
from PIL import Image
import io
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_responsive_versions(image_path, widths=[400, 600, 800], quality=65):
    """
    Genera versioni responsive di un'immagine

    Args:
        image_path: Path assoluto dell'immagine
        widths: Lista di larghezze per le versioni responsive
        quality: Qualità WebP (0-100)

    Returns:
        List di path creati
    """
    from django.conf import settings

    created_files = []

    try:
        source_path = Path(image_path)

        # Apri immagine originale
        with Image.open(source_path) as img:
            original_width, original_height = img.size

            for width in widths:
                # Salta se l'immagine è già più piccola
                if original_width <= width:
                    continue

                # Nome file output
                output_stem = f"{source_path.stem}-{width}w"
                output_path = source_path.parent / f"{output_stem}.webp"

                # Salta se esiste già
                if output_path.exists():
                    logger.info(f"Versione {width}w già esistente: {output_path.name}")
                    continue

                # Ridimensiona
                ratio = width / original_width
                new_height = int(original_height * ratio)
                img_resized = img.resize((width, new_height), Image.Resampling.LANCZOS)

                # Converti in RGB se necessario
                if img_resized.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img_resized.size, (255, 255, 255))
                    if img_resized.mode == 'P':
                        img_resized = img_resized.convert('RGBA')
                    if img_resized.mode in ('RGBA', 'LA'):
                        background.paste(img_resized, mask=img_resized.split()[-1])
                    else:
                        background.paste(img_resized)
                    img_resized = background

                # Salva come WebP
                img_resized.save(output_path, 'WebP', quality=quality, method=6)

                created_files.append(str(output_path))
                logger.info(f"Versione responsive creata: {output_path.name} ({width}x{new_height})")

        return created_files

    except Exception as e:
        logger.error(f"Errore generazione versioni responsive: {e}")
        return []


def convert_uploaded_image_to_webp(image_field, quality=65, max_width=800):
    """
    Converte un'immagine caricata in WebP ottimizzato

    Args:
        image_field: Campo ImageField di Django
        quality: Qualità WebP (0-100, default 75 per bilanciare qualità/dimensione)
        max_width: Larghezza massima per ridimensionamento (default 1200px)

    Returns:
        ContentFile con l'immagine WebP convertita, o None se errore
    """
    try:
        # Apri l'immagine dal campo
        image_field.seek(0)
        img = Image.open(image_field)

        # Log dimensioni originali
        original_format = img.format
        width, height = img.size
        logger.info(f"Conversione immagine: {width}x{height} {original_format} -> WebP")

        # Ridimensiona se troppo grande (ottimizzazione performance web)
        if width > max_width:
            ratio = max_width / width
            new_height = int(height * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            logger.info(f"Immagine ridimensionata: {width}x{height} -> {max_width}x{new_height}")

        # Converti in RGB se necessario (per PNG con trasparenza)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
            logger.debug("Immagine convertita in RGB (rimozione trasparenza)")

        # Salva come WebP in memoria
        webp_io = io.BytesIO()
        img.save(webp_io, 'WebP', quality=quality, method=6)
        webp_io.seek(0)

        # Calcola risparmio
        image_field.seek(0)
        original_size = len(image_field.read())
        webp_size = len(webp_io.getvalue())
        savings = original_size - webp_size
        savings_percent = (savings / original_size) * 100 if original_size > 0 else 0

        logger.info(f"Conversione WebP completata: {original_size/1024:.1f}KB -> {webp_size/1024:.1f}KB (risparmio: {savings_percent:.1f}%)")

        # Ritorna il ContentFile con i dati WebP
        return ContentFile(webp_io.getvalue())

    except Exception as e:
        logger.error(f"Errore durante conversione WebP: {e}")
        return None


@receiver(pre_save, sender=Articolo)
def convert_foto_upload_to_webp(sender, instance, **kwargs):
    """
    Converte automaticamente le immagini caricate in WebP prima del salvataggio
    """
    # Verifica se c'è un'immagine caricata
    if not instance.foto_upload:
        return

    # Controlla se è un nuovo upload o se l'immagine è cambiata
    if instance.pk:
        try:
            old_instance = Articolo.objects.get(pk=instance.pk)
            # Se l'immagine non è cambiata, salta la conversione
            if old_instance.foto_upload == instance.foto_upload:
                return
        except Articolo.DoesNotExist:
            pass

    # Verifica se è già WebP
    if instance.foto_upload.name.lower().endswith('.webp'):
        logger.debug(f"Immagine già in formato WebP: {instance.foto_upload.name}")
        return

    # Converti solo PNG, JPG, JPEG
    file_ext = Path(instance.foto_upload.name).suffix.lower()
    if file_ext not in ['.png', '.jpg', '.jpeg']:
        logger.debug(f"Formato non supportato per conversione WebP: {file_ext}")
        return

    logger.info(f"Conversione immagine caricata in WebP: {instance.foto_upload.name}")

    # Converti l'immagine
    webp_content = convert_uploaded_image_to_webp(instance.foto_upload)

    if webp_content:
        # Genera nuovo nome file con estensione .webp
        original_name = Path(instance.foto_upload.name).stem
        webp_name = f"{original_name}.webp"

        # Sostituisci il file con la versione WebP
        instance.foto_upload.save(webp_name, webp_content, save=False)
        logger.info(f"Immagine convertita e salvata come: {webp_name}")
    else:
        logger.warning(f"Impossibile convertire {instance.foto_upload.name} in WebP, mantengo originale")


@receiver(post_save, sender=Articolo)
def generate_responsive_images_on_save(sender, instance, created, **kwargs):
    """
    Genera automaticamente versioni responsive dopo il salvataggio dell'articolo.
    Supporta sia foto_upload (upload manuale) che foto (URL da monitor).
    """
    from django.conf import settings
    import threading

    image_path = None

    # Priorità 1: foto_upload (upload manuale)
    if instance.foto_upload:
        image_path = instance.foto_upload.path
    # Priorità 2: foto che punta a /media/images/ (scaricata dai monitor)
    elif instance.foto and instance.foto.startswith('/media/images/'):
        # Converti URL relativo in path assoluto
        relative_path = instance.foto.replace('/media/', '')
        image_path = str(Path(settings.MEDIA_ROOT) / relative_path)

    # Se non c'è immagine locale, esci
    if not image_path:
        return

    # Verifica che il file esista
    if not Path(image_path).exists():
        logger.warning(f"Immagine non trovata per generazione responsive: {image_path}")
        return

    # Esegui in background per non bloccare il salvataggio
    def generate_in_background():
        try:
            logger.info(f"Generazione versioni responsive per: {image_path}")
            created_files = generate_responsive_versions(image_path, widths=[400, 600, 800], quality=65)
            if created_files:
                logger.info(f"Generate {len(created_files)} versioni responsive per {instance.titolo}")
            else:
                logger.warning(f"Nessuna versione responsive creata per: {instance.titolo} (possibile immagine troppo piccola o versioni già esistenti)")
        except Exception as e:
            logger.error(f"Errore generazione responsive in background per {instance.titolo}: {e}", exc_info=True)

    # Avvia thread in background
    thread = threading.Thread(target=generate_in_background)
    thread.daemon = True
    thread.start()


def invalidate_rss_feeds():
    """
    Invalida la cache dei feed RSS per forzare l'aggiornamento immediato
    """
    try:
        # Django syndication framework usa cache interno per i feed
        # Invalidiamo le chiavi di cache comuni per i feed RSS
        cache_keys_to_invalidate = [
            'syndication:rss-feed',
            'syndication:atom-feed', 
            'syndication:recenti-feed',
            'feeds:ArticoliFeedRSS',
            'feeds:ArticoliFeedAtom',
            'feeds:ArticoliRecentiFeed',
        ]
        
        for key in cache_keys_to_invalidate:
            cache.delete(key)
        
        # Invalida anche eventuali cache con timestamp
        from datetime import datetime
        today = datetime.now().strftime('%Y%m%d')
        cache.delete(f'rss_feed_{today}')
        cache.delete(f'rss_recenti_{today}')
        
        logger.info("Cache dei feed RSS invalidata per aggiornamento immediato")
        
    except Exception as e:
        logger.error(f"Errore nell'invalidazione cache RSS: {e}")


@receiver(pre_save, sender=Articolo)
def track_approval_change(sender, instance, **kwargs):
    """Traccia i cambiamenti dello stato di approvazione prima del salvataggio"""
    if instance.pk:
        try:
            # Ottieni lo stato precedente dall'oggetto esistente
            old_instance = Articolo.objects.get(pk=instance.pk)
            # Salva lo stato precedente in cache per il post_save
            cache.set(f'article_approval_state_{instance.pk}', {
                'was_approved': old_instance.approvato,
                'is_approved': instance.approvato
            }, 60)  # Cache per 1 minuto

            # Per pubbliredazionali, traccia anche il payment_status
            if instance.is_pubbliredazionale:
                cache.set(f'pubbliredazionale_payment_state_{instance.pk}', {
                    'was_paid': old_instance.payment_status == 'completed',
                    'is_paid': instance.payment_status == 'completed',
                }, 60)
        except Articolo.DoesNotExist:
            # Caso edge: pk esiste ma oggetto non trovato
            cache.set(f'article_approval_state_{instance.pk}', {
                'was_approved': False,
                'is_approved': instance.approvato
            }, 60)
    else:
        # Nuovo articolo (pk è None) - usa l'id dell'oggetto Python temporaneamente
        cache.set(f'article_approval_state_new_{id(instance)}', {
            'was_approved': False,
            'is_approved': instance.approvato
        }, 60)


@receiver(post_save, sender=Articolo)
def article_created_notification(sender, instance, created, **kwargs):
    """
    Invia notifica email quando viene creato un nuovo articolo non approvato
    ESCLUSI i pubbliredazionali (che hanno il proprio flusso di notifica al pagamento)
    """
    # Skip pubbliredazionali - hanno il loro flusso di notifica
    if instance.is_pubbliredazionale:
        return

    if created and not instance.approvato:
        logger.info(f"Nuovo articolo creato (ID: {instance.id}) - Invio notifica email")

        # Invia email di notifica in modo asincrono per non bloccare il salvataggio
        try:
            success = send_article_approval_notification(instance)
            if success:
                logger.info(f"Notifica email inviata per articolo ID {instance.id}")
            else:
                logger.warning(f"Impossibile inviare notifica email per articolo ID {instance.id}")
        except Exception as e:
            logger.error(f"Errore nell'invio notifica per articolo ID {instance.id}: {e}")


@receiver(post_save, sender=Articolo)
def handle_article_approval(sender, instance, created, **kwargs):
    """
    Gestisce la condivisione automatica quando un articolo viene approvato
    E invia email al cliente se è un pubbliredazionale
    """
    # Recupera lo stato di approvazione dalla cache
    approval_state = cache.get(f'article_approval_state_{instance.pk}')

    # Per articoli nuovi, controlla anche la cache temporanea
    if not approval_state and created:
        approval_state = cache.get(f'article_approval_state_new_{id(instance)}')
        if approval_state:
            cache.delete(f'article_approval_state_new_{id(instance)}')

    if not approval_state:
        # Se non c'è cache, assumiamo sia un nuovo articolo
        was_approved = False
        is_approved = instance.approvato
    else:
        was_approved = approval_state['was_approved']
        is_approved = approval_state['is_approved']
        # Pulizia cache
        if instance.pk:
            cache.delete(f'article_approval_state_{instance.pk}')

    # Condividi se:
    # 1. L'articolo è passato da non approvato ad approvato (approvazione manuale)
    # 2. L'articolo è nuovo e già approvato (auto-approvazione)
    # 3. Per pubbliredazionali: condividi SOLO se anche pagato (payment_status='completed')
    if (not was_approved and is_approved) or (created and is_approved):
        # Per pubbliredazionali, verifica anche che siano pagati
        if instance.is_pubbliredazionale:
            if instance.payment_status != 'completed':
                logger.info(f"Pubbliredazionale '{instance.titolo}' approvato ma non ancora pagato. Condivisione rimandata al pagamento.")
                # Invia email al cliente per approvazione (ma non condivide)
                from .email_notifications import send_pubbliredazionale_approved_notification
                try:
                    send_pubbliredazionale_approved_notification(instance)
                except Exception as e:
                    logger.error(f"Errore invio email approvazione pubbliredazionale ID {instance.id}: {e}")
                return  # NON condividere ancora
            else:
                logger.info(f"Pubbliredazionale '{instance.titolo}' approvato E pagato. Procedo con condivisione.")

        logger.info(f"Articolo '{instance.titolo}' appena approvato, aggiorno feed RSS e avvio condivisione automatica")

        # I link interni sono già stati aggiunti durante la generazione (polish_article)
        # Non è necessario riaggiungerli qui

        # Invalida immediatamente la cache RSS per IFTTT (veloce, sincrono)
        invalidate_rss_feeds()
        # Invalida cache homepage (tutte le varianti categoria)
        cache.clear()

        # Condivisione automatica in background thread per evitare timeout
        # Instagram con retry può impiegare fino a 90 secondi
        import threading
        thread = threading.Thread(
            target=_share_article_background,
            args=(instance.id, instance.titolo),
            name=f"ShareArticle-{instance.id}"
        )
        thread.daemon = True  # Thread termina quando il main process termina
        thread.start()

        logger.info(f"Condivisione social avviata in background per: {instance.titolo}")

        # Notifica motori di ricerca dell'articolo pubblicato (già in background)
        _notify_search_engines_background(instance)

        logger.info(f"Feed RSS aggiornato per articolo: {instance.titolo}")


@receiver(post_save, sender=Articolo)
def handle_pubbliredazionale_payment(sender, instance, created, **kwargs):
    """
    Gestisce la condivisione automatica quando un pubbliredazionale viene pagato.
    Se il pubbliredazionale è già approvato E il pagamento è appena stato completato,
    triggera la condivisione social.
    """
    if not instance.is_pubbliredazionale:
        return

    # Recupera lo stato del pagamento dalla cache
    payment_state = cache.get(f'pubbliredazionale_payment_state_{instance.pk}')

    if not payment_state:
        return  # Nessun cambiamento di payment_status

    was_paid = payment_state['was_paid']
    is_paid = payment_state['is_paid']

    # Pulizia cache
    cache.delete(f'pubbliredazionale_payment_state_{instance.pk}')

    # Condividi se:
    # 1. Il pagamento è passato da non completato a completato
    # 2. L'articolo è già approvato (approvato=True)
    if not was_paid and is_paid:
        if instance.approvato:
            logger.info(f"Pubbliredazionale '{instance.titolo}' pagato e già approvato. Avvio condivisione automatica.")

            # I link interni sono già stati aggiunti durante la generazione
            # Invalida cache RSS
            invalidate_rss_feeds()

            # Condivisione automatica in background
            import threading
            thread = threading.Thread(
                target=_share_article_background,
                args=(instance.id, instance.titolo),
                name=f"SharePubbliredazionale-{instance.id}"
            )
            thread.daemon = True
            thread.start()

            logger.info(f"Condivisione social avviata per pubbliredazionale pagato: {instance.titolo}")

            # Notifica motori di ricerca
            _notify_search_engines_background(instance)

            logger.info(f"Feed RSS aggiornato per pubbliredazionale: {instance.titolo}")
        else:
            logger.info(f"Pubbliredazionale '{instance.titolo}' pagato ma non ancora approvato. Condivisione rimandata all'approvazione.")


def _notify_search_engines_background(instance):
    """
    Notifica i motori di ricerca (Google, Bing, Yandex) della pubblicazione dell'articolo.
    Eseguito in background per non bloccare il salvataggio.
    """
    logger.warning(f"[SIGNAL] Avvio notifica indicizzazione per: {instance.titolo}")

    def _notify():
        try:
            from django.conf import settings
            import sys
            article_url = f"{settings.SITE_URL}/articolo/{instance.slug}/"

            logger.warning(f"[SIGNAL] Chiamata API per: {article_url}")
            sys.stdout.flush()

            results = notifier.notify_article_published(article_url)

            # Log risultati con WARNING per visibilità
            if results['indexnow']['success']:
                logger.warning(f"[SIGNAL INDEXING] IndexNow OK: {instance.titolo}")
            else:
                logger.warning(f"[SIGNAL INDEXING] IndexNow FAIL: {instance.titolo} - {results['indexnow']['message'][:100]}")

            if results['google']['success']:
                logger.warning(f"[SIGNAL INDEXING] Google OK: {instance.titolo}")
            else:
                logger.warning(f"[SIGNAL INDEXING] Google FAIL: {instance.titolo} - {results['google']['message'][:100]}")

            sys.stdout.flush()

        except Exception as e:
            logger.error(f"[SIGNAL] Errore notifica motori ricerca: {instance.titolo} - {e}")
            import traceback
            logger.error(traceback.format_exc())
            sys.stdout.flush()

    # Avvia thread
    thread = threading.Thread(target=_notify)
    thread.daemon = True
    thread.start()


def _share_article_background(article_id, article_title):
    """
    Esegue la condivisione sui social in background thread.
    Utilizzato per evitare timeout HTTP quando Instagram impiega molto tempo (retry con delay fino a 90s).

    Args:
        article_id: ID dell'articolo da condividere
        article_title: Titolo dell'articolo (per logging)
    """
    try:
        # Piccolo ritardo per evitare race conditions con la transazione di approvazione
        import time
        time.sleep(1)

        # Lock distribuito per evitare che più worker Gunicorn eseguano la condivisione contemporaneamente
        from django.core.cache import cache
        from .models import SocialPublicationLog
        lock_key = f'share_article_lock_{article_id}'
        lock_timeout = 180  # 3 minuti (tempo massimo stimato per condivisione completa)

        # Tenta di acquisire il lock (atomic operation)
        if not cache.add(lock_key, 'locked', lock_timeout):
            logger.info(f"[Background Thread] Condivisione già in corso per articolo {article_id} (altro worker), skip")
            return

        try:
            logger.info(f"[Background Thread] Lock acquisito, inizio condivisione social per: {article_title}")

            # Ricarica l'articolo dal database per sicurezza
            from .models import Articolo
            from .social_sharing import social_manager

            articolo = Articolo.objects.get(pk=article_id)

            # Verifica che sia ancora approvato (doppio controllo)
            if not articolo.approvato:
                logger.warning(f"[Background Thread] Articolo '{article_title}' non più approvato, annullo condivisione")
                return

            # Per pubbliredazionali, verifica anche che siano pagati
            if articolo.is_pubbliredazionale and articolo.payment_status != 'completed':
                logger.warning(f"[Background Thread] Pubbliredazionale '{article_title}' non ancora pagato, annullo condivisione")
                return

            # Doppio controllo: verifica se è già stato condiviso su TUTTE le piattaforme
            # Questo previene duplicati anche se il lock scade prematuramente.
            # facebook_story e instagram richiedono foto: ignorati se manca.
            # facebook_reel non parte all'approvazione degli eventi futuri:
            # viene creato dal reminder del giorno prima dell'evento.
            platforms = ['telegram', 'facebook', 'facebook_story', 'instagram',
                         'instagram_story', 'instagram_reel']
            requires_photo = {'facebook_story', 'instagram', 'instagram_story', 'instagram_reel'}
            already_shared_all = all(
                SocialPublicationLog.objects.filter(
                    articolo=articolo,
                    platform=platform,
                    success=True
                ).exists()
                for platform in platforms if articolo.has_shareable_image or platform not in requires_photo
            )

            if already_shared_all:
                logger.info(f"[Background Thread] Articolo '{article_title}' già condiviso su tutte le piattaforme, skip completo")
                return

            # Esegui la condivisione (con retry automatico Instagram e protezione duplicati interna)
            results = social_manager.share_article_on_approval(articolo)
        finally:
            # Rilascia il lock
            cache.delete(lock_key)
            logger.info(f"[Background Thread] Lock rilasciato per articolo {article_id}")

        # Log dei risultati
        successful_platforms = [platform for platform, success in results.items() if success]
        failed_platforms = [platform for platform, success in results.items() if not success]

        success_count = len(successful_platforms)
        total_count = len(results)

        if success_count == total_count:
            logger.info(f"[Background Thread] ✓ Condivisione completata: {success_count}/{total_count} piattaforme per '{article_title}'")
            logger.info(f"[Background Thread] Piattaforme: {', '.join(successful_platforms)}")
        elif success_count > 0:
            logger.warning(f"[Background Thread] ⚠ Condivisione parziale: {success_count}/{total_count} piattaforme per '{article_title}'")
            logger.info(f"[Background Thread] Successo: {', '.join(successful_platforms)}")
            logger.warning(f"[Background Thread] Fallito: {', '.join(failed_platforms)}")
        else:
            logger.error(f"[Background Thread] ✗ Condivisione fallita su tutte le piattaforme per '{article_title}'")
            logger.error(f"[Background Thread] Piattaforme fallite: {', '.join(failed_platforms)}")

    except Articolo.DoesNotExist:
        logger.error(f"[Background Thread] Articolo ID {article_id} non trovato durante condivisione")
    except Exception as e:
        logger.error(f"[Background Thread] Errore durante condivisione per '{article_title}': {str(e)}")
        import traceback
        logger.error(f"[Background Thread] Traceback: {traceback.format_exc()}")
