from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.contrib.auth.models import User
from admin_panel.models import PromotionalCode
from datetime import timedelta
import pandas as pd
from pathlib import Path
import re
import secrets
import string


class Command(BaseCommand):
    help = 'Crea codici promozionali per aziende con email e aggiorna il file Excel'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default=r'C:\MoneyScraper\aziende_emilia_romagna.xlsx',
            help='Percorso al file Excel con le aziende'
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
            default=10,
            help='Giorni di validità da domani (default: 10)'
        )

    def generate_promo_code(self, company_name):
        """Genera un codice promozionale dalla ragione sociale"""
        # Rimuovi suffissi legali comuni
        clean_name = re.sub(
            r'\b(S\.?P\.?A\.?|S\.?R\.?L\.?|S\.?N\.?C\.?|S\.?A\.?S\.?|SOCIETA|PER|AZIONI|'
            r'A RESPONSABILITA LIMITATA|SEMPLIFICATA|ESERCIZIO|FABBRICHE)\b',
            '',
            company_name.upper(),
            flags=re.IGNORECASE
        ).strip()

        # Rimuovi caratteri speciali e mantieni solo lettere e numeri
        clean_name = re.sub(r'[^A-Z0-9\s]', '', clean_name)

        # Prendi le prime parole significative
        words = [w for w in clean_name.split() if len(w) > 2][:3]

        if not words:
            # Fallback: usa tutto il nome pulito
            base = clean_name[:15].replace(' ', '')
        else:
            # Unisci le parole
            base = ''.join(words)[:15]

        # Aggiungi suffisso per univocità
        code = f"PUBB90-{base}"

        return code

    def generate_password(self, length=12):
        """Genera una password sicura casuale"""
        alphabet = string.ascii_letters + string.digits + "!@#$%&*"
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def parse_emails(self, email_string):
        """Estrae le email da una stringa separata da ; o ,"""
        if pd.isna(email_string) or not email_string:
            return []

        # Separa per ; o ,
        emails = re.split(r'[;,]', str(email_string))

        # Pulisci e valida
        valid_emails = []
        for email in emails:
            email = email.strip()
            # Validazione base email
            if email and '@' in email and '.' in email.split('@')[1]:
                valid_emails.append(email.lower())

        return valid_emails

    def handle(self, *args, **options):
        file_path = options['file']
        dry_run = options['dry_run']
        discount_percentage = options['discount']
        validity_days = options['days']

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

        # Aggiungi colonne se non esistono
        if 'Codice Promozionale' not in df.columns:
            df['Codice Promozionale'] = ''
        if 'Username' not in df.columns:
            df['Username'] = ''
        if 'Password' not in df.columns:
            df['Password'] = ''

        # Filtra aziende con almeno una email
        companies_with_email = df['Numero Email'] > 0
        total_companies = companies_with_email.sum()

        self.stdout.write(self.style.SUCCESS(f'\nTrovate {total_companies} aziende con email'))

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[!] MODALITA DRY-RUN: Nessun dato verra salvato\n'))

        # Date validità
        valid_from = timezone.now() + timedelta(days=1)  # Da domani
        valid_until = valid_from + timedelta(days=validity_days)

        self.stdout.write(f'Sconto: {discount_percentage}%')
        self.stdout.write(f'Valido da: {valid_from.strftime("%d/%m/%Y %H:%M")}')
        self.stdout.write(f'Valido fino a: {valid_until.strftime("%d/%m/%Y %H:%M")}')
        self.stdout.write(f'Utilizzi massimi: 1 per codice\n')

        # Conferma
        if not dry_run:
            confirm = input(f'\n[!] Stai per creare codici promozionali e utenti per {total_companies} aziende. Confermi? (yes/no): ')
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.ERROR('Operazione annullata'))
                return

        # Statistiche
        created_codes = 0
        created_users = 0
        errors = 0
        used_codes = set()

        # Crea codici promozionali e utenti
        self.stdout.write(self.style.WARNING('\nCreazione codici promozionali e utenti...\n'))

        with transaction.atomic():
            for idx, row in df.iterrows():
                # Salta aziende senza email
                if row['Numero Email'] == 0:
                    continue

                company_name = str(row['Azienda']).strip()
                city = str(row.get('Città', 'N/A')).strip()
                email_string = row.get('Email Estratte', '')

                try:
                    # 1. Genera codice promozionale univoco
                    base_code = self.generate_promo_code(company_name)
                    code = base_code

                    # Assicura univocità nel database E nel file corrente
                    counter = 1
                    while (PromotionalCode.objects.filter(code=code).exists() or
                           code in used_codes):
                        code = f"{base_code}-{counter}"
                        counter += 1

                    used_codes.add(code)
                    description = f"Sconto {discount_percentage}% per {company_name} ({city})"

                    # Salva codice promozionale nel database solo se non è dry-run
                    if not dry_run:
                        PromotionalCode.objects.create(
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
                        )

                    created_codes += 1

                    # 2. Estrai e crea utenti per ogni email
                    emails = self.parse_emails(email_string)
                    usernames_created = []
                    passwords_created = []

                    for email in emails:
                        # Genera username dall'email
                        base_username = email.split('@')[0][:25]  # Max 30 caratteri per Django
                        username = base_username

                        # Assicura univocità username
                        user_counter = 1
                        while User.objects.filter(username=username).exists():
                            username = f"{base_username}{user_counter}"
                            user_counter += 1

                        # Genera password casuale
                        password = self.generate_password()

                        # Crea utente solo se non è dry-run
                        if not dry_run:
                            user = User.objects.create_user(
                                username=username,
                                email=email,
                                password=password,
                                first_name=company_name[:30],  # Max 30 caratteri
                            )

                        usernames_created.append(username)
                        passwords_created.append(password)
                        created_users += 1

                    # 3. Aggiorna il DataFrame
                    df.at[idx, 'Codice Promozionale'] = code
                    df.at[idx, 'Username'] = '; '.join(usernames_created)
                    df.at[idx, 'Password'] = '; '.join(passwords_created)

                    # Mostra progresso ogni 100
                    if created_codes % 100 == 0:
                        self.stdout.write(f'Processate {created_codes}/{total_companies} aziende ({created_users} utenti)...')

                except Exception as e:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f'[ERRORE] {company_name}: {str(e)}'))

            # Se è dry-run, rollback della transazione database
            if dry_run:
                transaction.set_rollback(True)

        # Salva il file Excel aggiornato
        if not dry_run:
            try:
                output_file = file_path.replace('.xlsx', '_con_codici.xlsx')
                df.to_excel(output_file, index=False, engine='openpyxl')
                self.stdout.write(self.style.SUCCESS(f'\n[OK] File Excel aggiornato salvato in: {output_file}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'[ERRORE] Salvataggio file Excel: {str(e)}'))
        else:
            self.stdout.write(self.style.WARNING('\n[!] DRY-RUN: File Excel non salvato'))

        # Riepilogo finale
        self.stdout.write(self.style.SUCCESS('\n' + '='*60))
        self.stdout.write(self.style.SUCCESS('RIEPILOGO'))
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write(f'Aziende processate: {total_companies}')
        self.stdout.write(self.style.SUCCESS(f'Codici promozionali creati: {created_codes}'))
        self.stdout.write(self.style.SUCCESS(f'Utenti creati: {created_users}'))
        if errors > 0:
            self.stdout.write(self.style.ERROR(f'Errori: {errors}'))

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[!] DRY-RUN: Nessun dato e stato salvato'))
            self.stdout.write('\nPer salvare i dati, esegui senza --dry-run:')
            self.stdout.write('  python manage.py create_promo_codes')
        else:
            self.stdout.write(self.style.SUCCESS('\n[OK] Codici promozionali e utenti creati con successo!'))
            self.stdout.write(f'\n[FILE] File Excel aggiornato: {output_file}')
            self.stdout.write('\nVisualizza i codici nell\'admin:')
            self.stdout.write('  /admin/admin_panel/promotionalcode/')
            self.stdout.write('  /admin/auth/user/')
