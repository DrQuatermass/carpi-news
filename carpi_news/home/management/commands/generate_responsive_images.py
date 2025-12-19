"""
Comando per generare versioni responsive delle immagini esistenti
Crea versioni a 400w, 600w, 800w per tutte le immagini in /media/
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from pathlib import Path
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Genera versioni responsive delle immagini esistenti'

    def add_arguments(self, parser):
        parser.add_argument(
            '--quality',
            type=int,
            default=85,
            help='Qualità WebP (0-100, default 85)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Rigenera anche se le versioni esistono già'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostra cosa verrebbe fatto senza eseguire'
        )

    def handle(self, *args, **options):
        quality = options['quality']
        force = options['force']
        dry_run = options['dry_run']

        self.stdout.write(f"Generazione immagini responsive (qualità: {quality})")

        # Directory media
        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.exists():
            self.stdout.write(self.style.ERROR(f"MEDIA_ROOT non trovato: {media_root}"))
            return

        # Dimensioni responsive (incluso 1200w per spotlight)
        widths = [400, 600, 800, 1200]

        # Trova tutte le immagini
        image_extensions = ['.jpg', '.jpeg', '.png', '.webp']
        total_processed = 0
        total_created = 0
        total_skipped = 0

        for ext in image_extensions:
            for image_path in media_root.rglob(f'*{ext}'):
                # Salta immagini già responsive (con -400w, -600w, -800w nel nome)
                if any(f'-{w}w' in image_path.stem for w in widths):
                    continue

                total_processed += 1
                self.stdout.write(f"\nProcessando: {image_path.relative_to(media_root)}")

                # Genera versioni responsive
                for width in widths:
                    created = self.generate_responsive_version(
                        image_path, width, quality, force, dry_run
                    )
                    if created:
                        total_created += 1
                    else:
                        total_skipped += 1

        # Riepilogo
        self.stdout.write(self.style.SUCCESS(f"\n{'=' * 60}"))
        self.stdout.write(self.style.SUCCESS(f"Completato!"))
        self.stdout.write(f"Immagini originali processate: {total_processed}")
        self.stdout.write(f"Versioni responsive create: {total_created}")
        self.stdout.write(f"Versioni saltate (già esistono): {total_skipped}")

    def generate_responsive_version(self, source_path, width, quality, force, dry_run):
        """
        Genera una versione responsive di un'immagine

        Returns:
            bool: True se creata, False se saltata
        """
        # Nome file output
        output_stem = f"{source_path.stem}-{width}w"
        output_path = source_path.parent / f"{output_stem}.webp"

        # Controlla se esiste già
        if output_path.exists() and not force:
            self.stdout.write(f"  > {width}w: gia' esistente (skip)")
            return False

        if dry_run:
            self.stdout.write(f"  > {width}w: verrebbe creato {output_path.name}")
            return True

        try:
            # Apri immagine
            img = Image.open(source_path)
            original_width, original_height = img.size

            # Salta se l'immagine e' gia' piu' piccola della dimensione target
            if original_width <= width:
                self.stdout.write(f"  > {width}w: skip (originale gia' piccolo: {original_width}px)")
                return False

            # Ridimensiona mantenendo aspect ratio
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

            # Calcola statistiche
            original_size = source_path.stat().st_size
            new_size = output_path.stat().st_size
            savings = ((original_size - new_size) / original_size) * 100

            self.stdout.write(
                self.style.SUCCESS(
                    f"  OK {width}w: {original_width}x{original_height} -> {width}x{new_height} "
                    f"({original_size/1024:.1f}KB -> {new_size/1024:.1f}KB, -{savings:.0f}%)"
                )
            )
            return True

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ERR {width}w: Errore - {e}"))
            return False
