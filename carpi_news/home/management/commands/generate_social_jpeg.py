"""
Genera la variante social JPEG (16x9) per gli articoli che hanno gia' la
variante WebP ma non il JPEG gemello.

Serve perche' Facebook, WhatsApp e LinkedIn non renderizzano in modo affidabile
le anteprime con og:image in formato WebP. Il JPEG viene ri-codificato
direttamente dal WebP 1200x675 gia' esistente (nessun ritaglio: e' gia' nel
formato giusto), quindi e' un'operazione leggera.

IMPORTANTE: il comando scrive SOLO file su disco, non fa save() sul modello,
quindi non innesca i signal post_save (niente rigenerazione immagini / OOM).
"""
from pathlib import Path

from django.core.management.base import BaseCommand
from PIL import Image, UnidentifiedImageError

from home.models import Articolo
from home.image_variants import (
    get_article_social_jpeg_path,
    crop_resize_social_jpeg,
    get_article_source_image_path,
    _to_rgb,
    SOCIAL_JPEG_QUALITY,
)


class Command(BaseCommand):
    help = "Genera la variante social JPEG (16x9) per gli articoli che hanno solo il WebP"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Mostra cosa verrebbe generato senza scrivere file')
        parser.add_argument('--force', action='store_true',
                            help='Rigenera anche se il JPEG esiste gia')
        parser.add_argument('--limit', type=int, default=0,
                            help='Elabora al massimo N articoli (0 = tutti)')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        limit = options['limit']

        if dry_run:
            self.stdout.write(self.style.WARNING('=== MODALITA DRY-RUN ===\n'))

        articoli = (
            Articolo.objects
            .exclude(image_16x9='')
            .filter(image_16x9__isnull=False)
            .order_by('-data_pubblicazione')
        )
        total = articoli.count()
        self.stdout.write(f'Articoli con variante 16x9: {total}\n')
        self.stdout.write('=' * 70)

        generati = saltati = errori = 0

        for articolo in articoli.iterator():
            jpeg_path = get_article_social_jpeg_path(articolo)
            if not jpeg_path:
                continue

            if jpeg_path.exists() and not force:
                saltati += 1
                continue

            # Sorgente: il webp 16x9 gia' esistente (gia' 1200x675 -> nessun crop);
            # in fallback l'immagine sorgente originale.
            source_path = None
            try:
                webp_path = Path(articolo.image_16x9.path)
                if webp_path.exists():
                    source_path = webp_path
            except (ValueError, AttributeError):
                pass
            if source_path is None:
                source_path = get_article_source_image_path(articolo)
            if source_path is None:
                saltati += 1
                continue

            try:
                if not dry_run:
                    if source_path.suffix.lower() == '.webp':
                        # Ri-codifica diretta: il webp e' gia' nel formato 16x9.
                        with Image.open(source_path) as im:
                            jpeg_path.parent.mkdir(parents=True, exist_ok=True)
                            _to_rgb(im).save(
                                jpeg_path, 'JPEG',
                                quality=SOCIAL_JPEG_QUALITY, optimize=True, progressive=True,
                            )
                    else:
                        # Sorgente originale: ritaglia+ridimensiona a 16x9.
                        crop_resize_social_jpeg(source_path, jpeg_path)
                generati += 1
                self.stdout.write(
                    f'{"[DRY-RUN] " if dry_run else ""}[OK] {jpeg_path.name}'
                )
            except (OSError, UnidentifiedImageError) as exc:
                errori += 1
                self.stdout.write(self.style.ERROR(
                    f'[ERRORE] {(articolo.titolo or "")[:45]}... - {exc}'
                ))

            if limit and generati >= limit:
                self.stdout.write(self.style.WARNING(f'\nRaggiunto limite di {limit}.'))
                break

        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.SUCCESS('RIEPILOGO:'))
        self.stdout.write(f'JPEG generati: {generati}')
        self.stdout.write(f'Saltati (gia presenti / senza sorgente): {saltati}')
        self.stdout.write(f'Errori: {errori}')
        self.stdout.write('=' * 70)
