from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import time
import csv
import re


class Command(BaseCommand):
    help = 'Invia email di benvenuto alle aziende con template HTML personalizzato'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            required=True,
            help='Percorso al file Excel con Username, Password e Codice Promozionale'
        )
        parser.add_argument(
            '--template',
            type=str,
            required=True,
            help='Percorso al file HTML template'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Esegue senza inviare email (solo simulazione)'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=10,
            help='Numero di email da inviare per batch (default: 10)'
        )
        parser.add_argument(
            '--delay',
            type=int,
            default=2,
            help='Secondi di pausa tra i batch (default: 2)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limita invio a N email (per test)'
        )
        parser.add_argument(
            '--scadenza-giorni',
            type=int,
            default=11,
            help='Giorni di validità del codice sconto (default: 11)'
        )
        parser.add_argument(
            '--test-email',
            type=str,
            help='Email di test: in dry-run invia email reali a questo indirizzo invece che simulare'
        )
        parser.add_argument(
            '--skip-sent',
            type=str,
            help='Percorso al file CSV report precedente o cartella contenente tutti i report: salta le email già inviate con successo'
        )

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
                # Salta email già esistenti (marcate con "già esistente")
                if 'già esistente' not in email.lower():
                    valid_emails.append(email.lower())

        return valid_emails

    def parse_credentials(self, username_string, password_string, email):
        """Estrae username e password corrispondenti all'email"""
        if pd.isna(username_string) or pd.isna(password_string):
            return None, None

        # Separa per ;
        usernames = [u.strip() for u in str(username_string).split(';')]
        passwords = [p.strip() for p in str(password_string).split(';')]

        # Trova l'indice corrispondente all'email
        for i, username in enumerate(usernames):
            if username.lower() == email.lower() or username.startswith(email.split('@')[0]):
                if i < len(passwords):
                    return username, passwords[i]

        # Fallback: prendi il primo
        if usernames and passwords:
            return usernames[0], passwords[0]

        return None, None

    def load_template(self, template_path):
        """Carica il template HTML"""
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Errore caricamento template: {str(e)}'))
            return None

    def render_template(self, template, company_name, email, password, promo_code, scadenza_data):
        """Sostituisce i placeholder nel template"""
        rendered = template
        rendered = rendered.replace('[NOME_AZIENDA]', company_name)
        rendered = rendered.replace('[EMAIL_AZIENDA]', email)
        rendered = rendered.replace('[PASSWORD_GENERATA]', password)
        rendered = rendered.replace('[CODICE_SCONTO_PERSONALIZZATO]', promo_code)
        rendered = rendered.replace('[DATA_SCADENZA]', scadenza_data)
        return rendered

    def send_email(self, to_email, subject, html_content, from_email):
        """Invia email HTML"""
        try:
            email = EmailMultiAlternatives(
                subject=subject,
                body='Questa email richiede un client che supporta HTML.',
                from_email=from_email,
                to=[to_email]
            )
            email.attach_alternative(html_content, "text/html")
            email.send()
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def is_valid_domain(self, email):
        """Verifica se il dominio dell'email è valido controllando record MX"""
        import socket
        try:
            domain = email.split('@')[1]
            # Prova una semplice risoluzione DNS del dominio
            socket.gethostbyname(domain)
            return True
        except (socket.gaierror, IndexError):
            return False

    def load_sent_emails(self, report_path):
        """Carica le email già inviate con successo dal report CSV o da tutti i CSV in una cartella"""
        sent_emails = set()

        path = Path(report_path)

        # Se è una cartella, leggi tutti i file email_report_*.csv
        if path.is_dir():
            csv_files = list(path.glob('email_report_*.csv'))
            self.stdout.write(f'Trovati {len(csv_files)} file report nella cartella')

            for csv_file in csv_files:
                try:
                    df = pd.read_csv(csv_file)
                    # Include anche i domini invalidi per non riprovarli
                    successful = df[df['Stato'].isin(['SENT', 'TEST-SENT', 'INVALID-DOMAIN'])]
                    emails = set(successful['Email'].str.lower())
                    sent_emails.update(emails)
                    self.stdout.write(f'  - {csv_file.name}: {len(emails)} email processate')
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'  - Errore lettura {csv_file.name}: {str(e)}'))

        # Se è un file, leggi solo quello
        elif path.is_file():
            try:
                df = pd.read_csv(report_path)
                # Include anche i domini invalidi per non riprovarli
                successful = df[df['Stato'].isin(['SENT', 'TEST-SENT', 'INVALID-DOMAIN'])]
                sent_emails = set(successful['Email'].str.lower())
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'Errore lettura report: {str(e)}'))

        return sent_emails

    def handle(self, *args, **options):
        file_path = options['file']
        template_path = options['template']
        dry_run = options['dry_run']
        batch_size = options['batch_size']
        delay = options['delay']
        limit = options['limit']
        scadenza_giorni = options['scadenza_giorni']
        test_email = options.get('test_email')
        skip_sent_file = options.get('skip_sent')

        # Verifica file Excel
        if not Path(file_path).exists():
            self.stdout.write(self.style.ERROR(f'File Excel non trovato: {file_path}'))
            return

        # Verifica template
        if not Path(template_path).exists():
            self.stdout.write(self.style.ERROR(f'Template HTML non trovato: {template_path}'))
            return

        # Carica template
        template = self.load_template(template_path)
        if not template:
            return

        # Leggi Excel
        self.stdout.write(self.style.WARNING('Caricamento file Excel...'))
        try:
            df = pd.read_excel(file_path)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Errore lettura file: {str(e)}'))
            return

        # Verifica colonne necessarie
        required_columns = ['Azienda', 'Email Estratte', 'Username', 'Password', 'Codice Promozionale']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            self.stdout.write(self.style.ERROR(f'Colonne mancanti nel file Excel: {", ".join(missing_columns)}'))
            return

        # Calcola data scadenza
        scadenza_data = (datetime.now() + timedelta(days=scadenza_giorni)).strftime('%d/%m/%Y')

        # Email mittente
        from_email = f'Redazione Ombra del Portico <redazione@ombradelportico.it>'

        # Carica email già inviate (se richiesto)
        already_sent = set()
        if skip_sent_file:
            if Path(skip_sent_file).exists():
                already_sent = self.load_sent_emails(skip_sent_file)
                self.stdout.write(self.style.SUCCESS(f'Caricate {len(already_sent)} email già inviate dal report precedente'))
            else:
                self.stdout.write(self.style.ERROR(f'File report non trovato: {skip_sent_file}'))
                return

        # Statistiche
        total_emails = 0
        sent_emails = 0
        failed_emails = 0
        skipped_emails = 0

        # Report CSV
        report_file = Path(file_path).parent / f'email_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

        # Determina modalità effettiva
        test_mode = dry_run and test_email

        if test_mode:
            self.stdout.write(self.style.WARNING(f'\n[!] MODALITA TEST: Email reali inviate a {test_email}\n'))
        elif dry_run:
            self.stdout.write(self.style.WARNING('\n[!] MODALITA DRY-RUN: Nessuna email verra inviata\n'))
        else:
            self.stdout.write(self.style.WARNING(f'\n[!] Le email verranno inviate da: {from_email}\n'))

        # Info configurazione
        self.stdout.write(f'Batch size: {batch_size} email')
        self.stdout.write(f'Delay tra batch: {delay} secondi')
        self.stdout.write(f'Data scadenza codici: {scadenza_data}')
        if limit:
            self.stdout.write(f'Limite test: {limit} email\n')

        # Conferma
        if not dry_run or test_mode:
            mode_text = f"invio TEST a {test_email}" if test_mode else "invio email"
            confirm = input(f'\n[!] Confermi {mode_text}? (yes/no): ')
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.ERROR('Operazione annullata'))
                return

        self.stdout.write(self.style.WARNING('\nInvio email in corso...\n'))

        # Prepara report CSV
        with open(report_file, 'w', newline='', encoding='utf-8') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow(['Azienda', 'Email', 'Username', 'Codice Promo', 'Stato', 'Messaggio', 'Timestamp'])

            batch_count = 0

            for idx, row in df.iterrows():
                # Salta aziende senza dati completi
                if pd.isna(row.get('Email Estratte')) or pd.isna(row.get('Username')) or pd.isna(row.get('Password')):
                    continue

                company_name = str(row['Azienda']).strip()

                # Salta aziende in liquidazione
                if 'in liquidazione' in company_name.lower():
                    skipped_emails += 1
                    self.stdout.write(self.style.WARNING(f'[LIQUIDAZIONE] Saltata azienda: {company_name}'))
                    continue

                promo_code = str(row.get('Codice Promozionale', 'N/A')).strip()

                # Estrai tutte le email
                emails = self.parse_emails(row['Email Estratte'])

                for email in emails:
                    # Salta email già inviate con successo
                    if email.lower() in already_sent:
                        skipped_emails += 1
                        continue

                    # Limita se richiesto
                    if limit and total_emails >= limit:
                        break

                    total_emails += 1

                    # Verifica dominio valido
                    if not self.is_valid_domain(email):
                        skipped_emails += 1
                        csv_writer.writerow([
                            company_name, email, 'N/A', promo_code,
                            'INVALID-DOMAIN', 'Dominio non valido o inesistente', datetime.now().isoformat()
                        ])
                        self.stdout.write(self.style.WARNING(f'[DOMINIO INVALIDO] {email} ({company_name})'))
                        continue

                    # Estrai credenziali corrispondenti
                    username, password = self.parse_credentials(
                        row['Username'],
                        row['Password'],
                        email
                    )

                    if not username or not password or password == 'N/A':
                        skipped_emails += 1
                        csv_writer.writerow([
                            company_name, email, username or 'N/A', promo_code,
                            'SKIPPED', 'Credenziali mancanti', datetime.now().isoformat()
                        ])
                        continue

                    # Rendering template
                    html_content = self.render_template(
                        template, company_name, username, password, promo_code, scadenza_data
                    )

                    # Subject con indicazione destinatario reale in test mode
                    subject = f"🏛️ {company_name} - Esperimento di giornalismo AI in Emilia-Romagna"
                    if test_mode:
                        subject = f"[TEST per: {email}] {subject}"

                    # Determina destinatario effettivo
                    actual_recipient = test_email if test_mode else email

                    # Invio email (in test_mode o modalità normale)
                    if not dry_run or test_mode:
                        success, message = self.send_email(actual_recipient, subject, html_content, from_email)

                        if success:
                            sent_emails += 1
                            status = 'SENT' if not test_mode else 'TEST-SENT'
                        else:
                            failed_emails += 1
                            status = 'FAILED'

                        csv_writer.writerow([
                            company_name, email, username, promo_code,
                            status, f"Inviato a: {actual_recipient} - {message}", datetime.now().isoformat()
                        ])

                        if success:
                            recipient_info = f" -> {actual_recipient}" if test_mode else ""
                            self.stdout.write(f'[OK] {total_emails}. {email}{recipient_info} ({company_name})')
                        else:
                            self.stdout.write(self.style.ERROR(f'[ERRORE] {email}: {message}'))
                    else:
                        self.stdout.write(f'[DRY-RUN] {total_emails}. {email} ({company_name})')
                        csv_writer.writerow([
                            company_name, email, username, promo_code,
                            'DRY-RUN', 'Simulazione', datetime.now().isoformat()
                        ])

                    batch_count += 1

                    # Pausa tra batch (anche in test mode)
                    if batch_count >= batch_size and (not dry_run or test_mode):
                        self.stdout.write(f'\n[PAUSA] {delay} secondi...\n')
                        time.sleep(delay)
                        batch_count = 0

                # Limita se richiesto
                if limit and total_emails >= limit:
                    break

        # Riepilogo finale
        self.stdout.write(self.style.SUCCESS('\n' + '='*60))
        self.stdout.write(self.style.SUCCESS('RIEPILOGO INVIO EMAIL'))
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write(f'Email processate: {total_emails}')

        if test_mode:
            self.stdout.write(self.style.SUCCESS(f'Email TEST inviate a {test_email}: {sent_emails}'))
            if failed_emails > 0:
                self.stdout.write(self.style.ERROR(f'Email fallite: {failed_emails}'))
            if skipped_emails > 0:
                self.stdout.write(self.style.WARNING(f'Email saltate: {skipped_emails}'))
        elif not dry_run:
            self.stdout.write(self.style.SUCCESS(f'Email inviate: {sent_emails}'))
            if failed_emails > 0:
                self.stdout.write(self.style.ERROR(f'Email fallite: {failed_emails}'))
            if skipped_emails > 0:
                self.stdout.write(self.style.WARNING(f'Email saltate: {skipped_emails}'))
        else:
            self.stdout.write(self.style.WARNING('[!] DRY-RUN: Nessuna email inviata'))

        self.stdout.write(f'\n[FILE] Report salvato in: {report_file}')

        if test_mode:
            self.stdout.write(self.style.SUCCESS(f'\n[OK] Test completato! Tutte le email inviate a {test_email}'))
        elif not dry_run:
            self.stdout.write(self.style.SUCCESS('\n[OK] Invio completato!'))
        else:
            self.stdout.write(self.style.WARNING('\nPer inviare le email, esegui senza --dry-run'))
