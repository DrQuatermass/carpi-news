from django.core.management.base import BaseCommand
from django.utils import timezone
from admin_panel.models import PromotionalCode
from datetime import timedelta
import pandas as pd
from pathlib import Path


class Command(BaseCommand):
    help = 'Importa codici promozionali dal file Excel (solo codici, senza creare utenti)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            required=True,
            help='Percorso al file Excel con i codici promozionali'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Esegue senza salvare (solo simulazione)'
        )
        parser.add_argument(
            '--discount',
            type=int,
            default=90,
            help='Percentuale di sconto (default: 90%%)'
        )
        parser.add_argument(
            '--days',
            type=int,
            default=11,
            help='Giorni di validità da oggi (default: 11)'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Numero di codici da salvare per batch (default: 100)'
        )

    def handle(self, *args, **options):
        file_path = options['file']
        dry_run = options['dry_run']
        discount_percentage = options['discount']
        validity_days = options['days']
        batch_size = options['batch_size']

        # Verifica file esiste
        if not Path(file_path).exists():
            self.stdout.write(self.style.ERROR(f'File non trovato: {file_path}'))
            return

        # Leggi Excel
        self.stdout.write(self.style.WARNING('Caricamento file Excel...'))
        try:
            df = pd.read_excel(file_path)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Errore lettura file: {str(e)}'))
            return

        # Verifica colonna "Codice Promozionale"
        if 'Codice Promozionale' not in df.columns:
            self.stdout.write(self.style.ERROR('Colonna "Codice Promozionale" non trovata nel file Excel'))
            return

        # Filtra righe con codice promozionale valido
        df_valid = df[df['Codice Promozionale'].notna() & (df['Codice Promozionale'] != '')]
        total_codes = len(df_valid)

        self.stdout.write(self.style.SUCCESS(f'\nTrovati {total_codes} codici promozionali da importare'))

        if total_codes == 0:
            self.stdout.write(self.style.WARNING('Nessun codice da importare'))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[!] MODALITA DRY-RUN: Nessun dato verra salvato\n'))

        # Date validità
        valid_from = timezone.now()
        valid_until = valid_from + timedelta(days=validity_days)

        self.stdout.write(f'Sconto: {discount_percentage}%')
        self.stdout.write(f'Valido da: {valid_from.strftime("%d/%m/%Y %H:%M")}')
        self.stdout.write(f'Valido fino a: {valid_until.strftime("%d/%m/%Y %H:%M")}')
        self.stdout.write(f'Utilizzi massimi: 1 per codice')
        self.stdout.write(f'Batch size: {batch_size} codici per volta\n')

        # Conferma
        if not dry_run:
            confirm = input(f'\n[!] Stai per importare {total_codes} codici promozionali. Confermi? (yes/no): ')
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.ERROR('Operazione annullata'))
                return

        # Statistiche
        created_codes = 0
        skipped_codes = 0
        errors = 0

        # Importa codici in batch
        self.stdout.write(self.style.WARNING('\nImportazione codici promozionali...\n'))

        codes_to_create = []

        for idx, row in df_valid.iterrows():
            code = str(row['Codice Promozionale']).strip()
            company_name = str(row.get('Azienda', 'N/A')).strip()
            city = str(row.get('Città', 'N/A')).strip()

            try:
                # Verifica se il codice esiste già
                if PromotionalCode.objects.filter(code=code).exists():
                    skipped_codes += 1
                    if skipped_codes <= 10:  # Mostra solo i primi 10
                        self.stdout.write(self.style.WARNING(f'[SKIP] Codice già esistente: {code}'))
                    continue

                description = f"Sconto {discount_percentage}% per {company_name} ({city})"

                # Aggiungi alla lista batch
                codes_to_create.append(PromotionalCode(
                    code=code,
                    description=description,
                    discount_type='percentage',
                    discount_value=discount_percentage,
                    applies_to='pubbliredazionale',
                    valid_from=valid_from,
                    valid_until=valid_until,
                    max_uses=1,
                    current_uses=0,
                    is_active=True,
                ))

                # Salva batch quando raggiungi la dimensione
                if len(codes_to_create) >= batch_size:
                    if not dry_run:
                        PromotionalCode.objects.bulk_create(codes_to_create)
                    created_codes += len(codes_to_create)
                    self.stdout.write(f'[OK] Salvati {created_codes}/{total_codes} codici...')
                    codes_to_create = []

            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f'[ERRORE] {code} ({company_name}): {str(e)}'))

        # Salva l'ultimo batch
        if codes_to_create and not dry_run:
            PromotionalCode.objects.bulk_create(codes_to_create)
            created_codes += len(codes_to_create)

        # Riepilogo finale
        self.stdout.write(self.style.SUCCESS('\n' + '='*60))
        self.stdout.write(self.style.SUCCESS('RIEPILOGO'))
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write(f'Codici nel file: {total_codes}')
        self.stdout.write(self.style.SUCCESS(f'Codici importati: {created_codes}'))
        if skipped_codes > 0:
            self.stdout.write(self.style.WARNING(f'Codici gia esistenti (saltati): {skipped_codes}'))
        if errors > 0:
            self.stdout.write(self.style.ERROR(f'Errori: {errors}'))

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[!] DRY-RUN: Nessun dato salvato'))
            self.stdout.write('\nPer salvare i dati, esegui senza --dry-run')
        else:
            self.stdout.write(self.style.SUCCESS('\n[OK] Codici promozionali importati con successo!'))
            self.stdout.write('\nVisualizza i codici nell\'admin:')
            self.stdout.write('  /admin/admin_panel/promotionalcode/')
