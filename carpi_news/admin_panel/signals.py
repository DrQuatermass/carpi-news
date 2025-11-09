import logging
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.core.files.base import ContentFile
from .models import Banner
from PIL import Image
import io
from pathlib import Path

logger = logging.getLogger(__name__)


def convert_banner_image_to_webp(image_field, quality=85):
    """
    Converte un'immagine banner in WebP ottimizzato

    Args:
        image_field: Campo ImageField di Django
        quality: Qualità WebP (0-100, default 85 per banner di alta qualità)

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
        logger.info(f"Conversione banner: {width}x{height} {original_format} -> WebP")

        # Converti in RGB se necessario (per PNG con trasparenza)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
            logger.debug("Banner convertito in RGB (rimozione trasparenza)")

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
        logger.error(f"Errore durante conversione WebP del banner: {e}")
        return None


def validate_and_resize_banner_image(banner_instance):
    """
    Valida e ridimensiona l'immagine del banner secondo le dimensioni consigliate

    Strategia di ridimensionamento:
    - Scala alla larghezza massima disponibile mantenendo le proporzioni
    - Per banner orizzontali (leaderboard): altezza max = 3× altezza placeholder
    - Per banner verticali (sidebar): nessun limite di altezza
    - Rifiuta immagini che superano l'altezza massima consentita

    Args:
        banner_instance: Istanza del modello Banner

    Returns:
        Tuple (is_valid, message, resized_image)
    """
    if not banner_instance.image or not banner_instance.position:
        return True, "", None

    try:
        # Ottieni le dimensioni consigliate per la posizione
        recommended_width, recommended_height = Banner.get_recommended_size(banner_instance.position)

        # Apri l'immagine
        banner_instance.image.seek(0)
        img = Image.open(banner_instance.image)
        current_width, current_height = img.size

        # Determina il tipo di banner in base al formato
        is_horizontal_banner = recommended_width > recommended_height  # Es. 728x90 (leaderboard)

        # Calcola l'altezza massima consentita
        if is_horizontal_banner:
            # Banner orizzontali: altezza max = 3× placeholder
            max_allowed_height = recommended_height * 3
        else:
            # Banner verticali (sidebar): nessun limite pratico
            max_allowed_height = float('inf')

        logger.info(f"Validazione banner: {current_width}x{current_height} (larghezza target: {recommended_width}px, altezza max: {max_allowed_height if max_allowed_height != float('inf') else 'illimitata'})")

        # Calcola la tolleranza sulla larghezza
        tolerance = Banner.SIZE_TOLERANCE
        min_width = recommended_width * (1 - tolerance)
        max_width = recommended_width * (1 + tolerance)

        # Verifica se la larghezza è già corretta
        width_ok = min_width <= current_width <= max_width

        # Se la larghezza è già corretta, verifica solo l'altezza
        if width_ok:
            if current_height <= max_allowed_height:
                logger.info(f"Larghezza e altezza banner accettabili: {current_width}x{current_height}")
                return True, f"Dimensioni corrette: {current_width}x{current_height}", None
            else:
                # Immagine con larghezza corretta ma troppo alta
                logger.error(f"Banner troppo alto: {current_height}px > {max_allowed_height}px (max consentito)")
                return False, f"Immagine troppo alta: {current_height}px. Altezza massima consentita: {int(max_allowed_height)}px", None

        # Calcola le nuove dimensioni mantenendo le proporzioni
        aspect_ratio = current_height / current_width
        new_width = recommended_width
        new_height = int(new_width * aspect_ratio)

        # Verifica se l'altezza risultante è accettabile
        if new_height > max_allowed_height:
            logger.error(f"Banner troppo alto dopo ridimensionamento: {new_height}px > {max_allowed_height}px")
            return False, f"Immagine troppo alta: dopo il ridimensionamento raggiungerebbe {new_height}px. Altezza massima consentita: {int(max_allowed_height)}px. Usa un'immagine con proporzioni più orizzontali.", None

        logger.warning(f"Ridimensionamento banner: {current_width}x{current_height} → {new_width}x{new_height} (proporzioni mantenute, larghezza massima)")

        # Ridimensiona mantenendo aspect ratio
        img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Salva in memoria
        output = io.BytesIO()
        format_to_use = img.format if img.format in ['JPEG', 'PNG', 'WebP'] else 'PNG'
        img_resized.save(output, format=format_to_use, quality=95)
        output.seek(0)

        message = f"Immagine ridimensionata da {current_width}x{current_height} a {new_width}x{new_height} (larghezza massima {recommended_width}px, altezza max {int(max_allowed_height)}px, proporzioni mantenute)"
        logger.info(message)

        return True, message, ContentFile(output.getvalue())

    except Exception as e:
        logger.error(f"Errore durante validazione/ridimensionamento banner: {e}")
        return False, f"Errore: {str(e)}", None


@receiver(pre_save, sender=Banner)
def process_banner_image(sender, instance, **kwargs):
    """
    Pre-salvataggio del banner:
    1. Valida e ridimensiona l'immagine se necessario
    2. Converte l'immagine in WebP

    Raises:
        ValidationError: Se l'immagine non rispetta i requisiti di dimensione
    """
    # Verifica se c'è un'immagine
    if not instance.image:
        return

    # Controlla se è un nuovo upload o se l'immagine è cambiata
    if instance.pk:
        try:
            old_instance = Banner.objects.get(pk=instance.pk)
            # Se l'immagine non è cambiata, salta l'elaborazione
            if old_instance.image == instance.image:
                return
        except Banner.DoesNotExist:
            pass

    # Step 1: Valida e ridimensiona se necessario
    is_valid, message, resized_image = validate_and_resize_banner_image(instance)

    # Se la validazione fallisce, lancia un'eccezione
    if not is_valid:
        from django.core.exceptions import ValidationError
        logger.error(f"Validazione banner fallita: {message}")
        raise ValidationError(f"Immagine non valida: {message}")

    if resized_image:
        # Sostituisci l'immagine con quella ridimensionata
        original_name = Path(instance.image.name).stem
        file_ext = Path(instance.image.name).suffix
        resized_name = f"{original_name}_resized{file_ext}"
        instance.image.save(resized_name, resized_image, save=False)
        logger.info(f"Banner ridimensionato: {message}")

    # Step 2: Converti in WebP (se non è già WebP)
    if instance.image.name.lower().endswith('.webp'):
        logger.debug(f"Banner già in formato WebP: {instance.image.name}")
        return

    # Converti solo PNG, JPG, JPEG
    file_ext = Path(instance.image.name).suffix.lower()
    if file_ext not in ['.png', '.jpg', '.jpeg']:
        logger.debug(f"Formato non supportato per conversione WebP: {file_ext}")
        return

    logger.info(f"Conversione banner in WebP: {instance.image.name}")

    # Converti l'immagine
    webp_content = convert_banner_image_to_webp(instance.image)

    if webp_content:
        # Genera nuovo nome file con estensione .webp
        original_name = Path(instance.image.name).stem
        # Rimuovi eventuale suffisso "_resized" dal nome
        if original_name.endswith('_resized'):
            original_name = original_name[:-8]
        webp_name = f"{original_name}.webp"

        # Sostituisci il file con la versione WebP
        instance.image.save(webp_name, webp_content, save=False)
        logger.info(f"Banner convertito e salvato come: {webp_name}")
    else:
        logger.warning(f"Impossibile convertire {instance.image.name} in WebP, mantengo originale")
