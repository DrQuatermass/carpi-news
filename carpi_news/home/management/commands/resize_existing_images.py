"""
Comando Django per ridimensionare le immagini già salvate in media/images/downloaded/
"""
from django.core.management.base import BaseCommand
from django.conf import settings
import os
import io
from PIL import Image
from pathlib import Path


class Command(BaseCommand):
    help = 'Ridimensiona tutte le immagini già salvate per ridurre spazio su disco'

    def add_arguments(self, parser):
        parser.add_argument(
            '--max-width',
            type=int,
            default=1200,
            help='Larghezza massima in pixel (default: 1200)',
        )
        parser.add_argument(
            '--max-height',
            type=int,
            default=1200,
            help='Altezza massima in pixel (default: 1200)',
        )
        parser.add_argument(
            '--quality',
            type=int,
            default=85,
            help='Qualità JPEG (1-100, default: 85)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula senza modificare i file',
        )
        parser.add_argument(
            '--min-size-kb',
            type=int,
            default=100,
            help='Processa solo immagini più grandi di X KB (default: 100)',
        )

    def handle(self, *args, **options):
        max_width = options['max_width']
        max_height = options['max_height']
        quality = options['quality']
        dry_run = options['dry_run']
        min_size_kb = options['min_size_kb']

        # Directory delle immagini
        images_dir = os.path.join(settings.MEDIA_ROOT, 'images', 'downloaded')

        if not os.path.exists(images_dir):
            self.stdout.write(self.style.ERROR(f'Directory non trovata: {images_dir}'))
            return

        # Trova tutte le immagini
        image_extensions = ['.jpg', '.jpeg', '.png', '.webp']
        image_files = []

        for ext in image_extensions:
            image_files.extend(Path(images_dir).glob(f'*{ext}'))
            image_files.extend(Path(images_dir).glob(f'*{ext.upper()}'))

        if not image_files:
            self.stdout.write(self.style.SUCCESS('Nessuna immagine trovata.'))
            return

        self.stdout.write(f'Trovate {len(image_files)} immagini in {images_dir}')
        self.stdout.write(f'Configurazione: max {max_width}x{max_height}px, qualità {quality}')
        self.stdout.write(f'Minimo dimensione file: {min_size_kb}KB')

        if dry_run:
            self.stdout.write(self.style.WARNING('MODALITÀ DRY-RUN - Nessuna modifica verrà effettuata'))

        self.stdout.write('')

        total_original_size = 0
        total_resized_size = 0
        resized_count = 0
        skipped_count = 0
        error_count = 0

        for i, image_path in enumerate(image_files, 1):
            try:
                # Dimensione file originale
                original_size = os.path.getsize(image_path)
                original_size_kb = original_size / 1024

                # Salta file troppo piccoli
                if original_size_kb < min_size_kb:
                    skipped_count += 1
                    if i % 10 == 0 or i <= 5:
                        self.stdout.write(
                            f'[{i}/{len(image_files)}] SKIP (troppo piccola): {image_path.name} '
                            f'({original_size_kb:.1f}KB)'
                        )
                    continue

                # Apri immagine
                with Image.open(image_path) as img:
                    original_width, original_height = img.size

                    # Controlla se serve ridimensionare
                    if original_width <= max_width and original_height <= max_height:
                        skipped_count += 1
                        if i % 10 == 0 or i <= 5:
                            self.stdout.write(
                                f'[{i}/{len(image_files)}] SKIP (già piccola): {image_path.name} '
                                f'{original_width}x{original_height} ({original_size_kb:.1f}KB)'
                            )
                        continue

                    # Calcola nuove dimensioni
                    ratio = min(max_width / original_width, max_height / original_height)
                    new_width = int(original_width * ratio)
                    new_height = int(original_height * ratio)

                    if not dry_run:
                        # Ridimensiona
                        img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

                        # Converti in RGB se necessario
                        if img_resized.mode in ('RGBA', 'LA', 'P'):
                            background = Image.new('RGB', img_resized.size, (255, 255, 255))
                            if img_resized.mode == 'P':
                                img_resized = img_resized.convert('RGBA')
                            if img_resized.mode == 'RGBA':
                                background.paste(img_resized, mask=img_resized.split()[-1])
                            else:
                                background.paste(img_resized)
                            img_resized = background
                        elif img_resized.mode != 'RGB':
                            img_resized = img_resized.convert('RGB')

                        # Salva in un buffer
                        output_buffer = io.BytesIO()

                        # Determina formato
                        if img.format == 'WEBP':
                            img_resized.save(output_buffer, format='WEBP', quality=quality)
                            output_format = 'WEBP'
                        else:
                            img_resized.save(output_buffer, format='JPEG', quality=quality, optimize=True)
                            output_format = 'JPEG'

                        resized_bytes = output_buffer.getvalue()
                        resized_size = len(resized_bytes)
                        resized_size_kb = resized_size / 1024

                        # Salva solo se c'è risparmio
                        if resized_size < original_size:
                            # Backup del file originale (opzionale)
                            # backup_path = str(image_path) + '.backup'
                            # shutil.copy2(image_path, backup_path)

                            # Sovrascrivi il file
                            with open(image_path, 'wb') as f:
                                f.write(resized_bytes)

                            total_original_size += original_size
                            total_resized_size += resized_size
                            resized_count += 1

                            saving_percent = ((original_size - resized_size) / original_size) * 100

                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'[{i}/{len(image_files)}] RESIZED: {image_path.name}\n'
                                    f'  {original_width}x{original_height} → {new_width}x{new_height}\n'
                                    f'  {original_size_kb:.1f}KB → {resized_size_kb:.1f}KB '
                                    f'(risparmio {saving_percent:.1f}%)'
                                )
                            )
                        else:
                            # Ridimensionamento non conveniente
                            skipped_count += 1
                            self.stdout.write(
                                f'[{i}/{len(image_files)}] SKIP (no risparmio): {image_path.name}'
                            )
                    else:
                        # Dry run - simula
                        estimated_size = original_size * 0.3  # Stima ~70% risparmio
                        estimated_size_kb = estimated_size / 1024
                        saving_percent = 70.0

                        self.stdout.write(
                            f'[{i}/{len(image_files)}] WOULD RESIZE: {image_path.name}\n'
                            f'  {original_width}x{original_height} → {new_width}x{new_height}\n'
                            f'  {original_size_kb:.1f}KB → ~{estimated_size_kb:.1f}KB '
                            f'(~{saving_percent:.1f}% risparmio)'
                        )

                        total_original_size += original_size
                        total_resized_size += estimated_size
                        resized_count += 1

            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f'[{i}/{len(image_files)}] ERROR: {image_path.name} - {str(e)}')
                )

        # Statistiche finali
        self.stdout.write('')
        self.stdout.write('=' * 80)
        self.stdout.write(self.style.SUCCESS('STATISTICHE FINALI'))
        self.stdout.write('=' * 80)
        self.stdout.write(f'Immagini processate: {len(image_files)}')
        self.stdout.write(f'  - Ridimensionate: {resized_count}')
        self.stdout.write(f'  - Saltate: {skipped_count}')
        self.stdout.write(f'  - Errori: {error_count}')

        if resized_count > 0:
            total_original_mb = total_original_size / (1024 * 1024)
            total_resized_mb = total_resized_size / (1024 * 1024)
            total_saving_mb = total_original_mb - total_resized_mb
            total_saving_percent = (total_saving_mb / total_original_mb) * 100

            self.stdout.write('')
            self.stdout.write(f'Spazio originale: {total_original_mb:.2f} MB')
            self.stdout.write(f'Spazio dopo resize: {total_resized_mb:.2f} MB')
            self.stdout.write(
                self.style.SUCCESS(
                    f'Risparmio totale: {total_saving_mb:.2f} MB ({total_saving_percent:.1f}%)'
                )
            )

        if dry_run:
            self.stdout.write('')
            self.stdout.write(
                self.style.WARNING(
                    'Esegui senza --dry-run per applicare le modifiche realmente.'
                )
            )
