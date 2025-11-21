from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
import pandas as pd
from pathlib import Path
import re
import secrets
import string


class Command(BaseCommand):
    help = 'Genera utenti per ogni email nel file Excel e scrive username/password nel file'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            required=True,
            help='Percorso al file Excel con le aziende'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Esegue senza salvare (solo simulazione)'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Numero di utenti da salvare per batch (default: 100)'
        )

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

        # Aggiungi colonne se non esistono
        if 'Username' not in df.columns:
            df['Username'] = ''
        if 'Password' not in df.columns:
            df['Password'] = ''

        # Filtra aziende con almeno una email
        companies_with_email = df['Numero Email'] > 0
        total_companies = companies_with_email.sum()

        self.stdout.write(self.style.SUCCESS(f'\nTrovate {total_companies} aziende con email'))

        if total_companies == 0:
            self.stdout.write(self.style.WARNING('Nessuna azienda con email da processare'))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[!] MODALITA DRY-RUN: Nessun dato verra salvato\n'))

        # Conferma
        if not dry_run:
            confirm = input(f'\n[!] Stai per creare utenti per {total_companies} aziende. Confermi? (yes/no): ')
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.ERROR('Operazione annullata'))
                return

        # Statistiche
        created_users = 0
        skipped_users = 0
        errors = 0

        # Lista per batch creation
        users_to_create = []
        user_data_map = {}  # Per tenere traccia dei dati utente
        processed_emails = set()  # Traccia email già processate nel file

        # Crea utenti
        self.stdout.write(self.style.WARNING('\nCreazione utenti...\n'))

        for idx, row in df.iterrows():
            # Salta aziende senza email
            if row['Numero Email'] == 0:
                continue

            company_name = str(row['Azienda']).strip()
            email_string = row.get('Email Estratte', '')

            try:
                # Estrai email
                emails = self.parse_emails(email_string)
                usernames_created = []
                passwords_created = []

                for email in emails:
                    # Salta email già processate nel file
                    if email in processed_emails:
                        skipped_users += 1
                        continue

                    # Verifica se esiste già un utente con questa email nel DB
                    if User.objects.filter(email=email).exists():
                        skipped_users += 1
                        existing_user = User.objects.get(email=email)
                        usernames_created.append(f"{existing_user.username} (già esistente)")
                        passwords_created.append("N/A")
                        processed_emails.add(email)
                        continue

                    # Usa l'email come username (Django supporta fino a 150 caratteri)
                    username = email
                    processed_emails.add(email)

                    # Genera password casuale
                    password = self.generate_password()

                    # Prepara per creazione batch
                    if not dry_run:
                        users_to_create.append({
                            'username': username,
                            'email': email,
                            'password': password,
                            'first_name': company_name[:30],
                        })
                        user_data_map[username] = password

                    usernames_created.append(username)
                    passwords_created.append(password)
                    created_users += 1

                    # Salva batch quando raggiungi la dimensione
                    if len(users_to_create) >= batch_size:
                        if not dry_run:
                            for user_data in users_to_create:
                                User.objects.create_user(
                                    username=user_data['username'],
                                    email=user_data['email'],
                                    password=user_data['password'],
                                    first_name=user_data['first_name'],
                                )
                        self.stdout.write(f'[OK] Creati {created_users} utenti...')
                        users_to_create = []

                # Aggiorna il DataFrame
                df.at[idx, 'Username'] = '; '.join(usernames_created)
                df.at[idx, 'Password'] = '; '.join(passwords_created)

            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f'[ERRORE] {company_name}: {str(e)}'))

        # Salva l'ultimo batch
        if users_to_create and not dry_run:
            for user_data in users_to_create:
                User.objects.create_user(
                    username=user_data['username'],
                    email=user_data['email'],
                    password=user_data['password'],
                    first_name=user_data['first_name'],
                )

        # Salva il file Excel aggiornato
        if not dry_run:
            try:
                # Determina il nome del file di output
                path = Path(file_path)
                output_file = path.parent / f"{path.stem}_con_utenti{path.suffix}"

                df.to_excel(str(output_file), index=False, engine='openpyxl')
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
        self.stdout.write(self.style.SUCCESS(f'Utenti creati: {created_users}'))
        if skipped_users > 0:
            self.stdout.write(self.style.WARNING(f'Utenti già esistenti (saltati): {skipped_users}'))
        if errors > 0:
            self.stdout.write(self.style.ERROR(f'Errori: {errors}'))

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[!] DRY-RUN: Nessun dato salvato'))
            self.stdout.write('\nPer salvare i dati, esegui senza --dry-run')
        else:
            self.stdout.write(self.style.SUCCESS('\n[OK] Utenti creati con successo!'))
            self.stdout.write(f'\n[FILE] Scarica il file Excel aggiornato dal server')
            self.stdout.write('\nVisualizza gli utenti nell\'admin:')
            self.stdout.write('  /admin/auth/user/')
