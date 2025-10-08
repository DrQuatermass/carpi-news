from django.core.management.base import BaseCommand
from pathlib import Path
import os


class Command(BaseCommand):
    help = 'Rimuove tutti i file di lock dei monitor'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forza la rimozione senza conferma'
        )

    def handle(self, *args, **options):
        force = options.get('force', False)

        locks_dir = Path('locks')

        if not locks_dir.exists():
            self.stdout.write(self.style.WARNING('Directory locks/ non trovata'))
            return

        # Trova tutti i file .lock
        lock_files = list(locks_dir.glob('*.lock'))

        if not lock_files:
            self.stdout.write(self.style.SUCCESS('Nessun file di lock da rimuovere'))
            return

        self.stdout.write(self.style.WARNING(f'\nTrovati {len(lock_files)} file di lock:\n'))
        for lock_file in lock_files:
            self.stdout.write(f'  - {lock_file.name}')

        # Conferma
        if not force:
            confirm = input('\nVuoi rimuovere tutti i lock? (yes/no): ')
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.ERROR('Operazione annullata'))
                return

        # Rimuovi i lock
        removed = 0
        errors = 0

        for lock_file in lock_files:
            try:
                lock_file.unlink()
                removed += 1
                self.stdout.write(self.style.SUCCESS(f'[OK] Rimosso: {lock_file.name}'))
            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f'[ERRORE] {lock_file.name}: {str(e)}'))

        # Riepilogo
        self.stdout.write(self.style.SUCCESS(f'\n=== Riepilogo ==='))
        self.stdout.write(self.style.SUCCESS(f'File rimossi: {removed}'))
        if errors > 0:
            self.stdout.write(self.style.ERROR(f'Errori: {errors}'))
        else:
            self.stdout.write(self.style.SUCCESS('Tutti i lock sono stati rimossi con successo!'))
            self.stdout.write('\nPuoi ora avviare i monitor con:')
            self.stdout.write('  python manage.py start_monitors')
            self.stdout.write('  python manage.py runserver')
