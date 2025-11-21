from django.core.management.base import BaseCommand
import pandas as pd
from pathlib import Path
import re


class Command(BaseCommand):
    help = 'Pulisce il file Excel rimuovendo email malformate e duplicati'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            required=True,
            help='Percorso al file Excel da pulire'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostra le email da rimuovere senza salvare'
        )

    def validate_email(self, email):
        """Valida formato email e rileva problemi comuni"""
        email = email.strip()

        # Problemi comuni da rilevare
        issues = []

        # Email troppo corta o vuota
        if not email or len(email) < 5:
            return False, ['Email vuota o troppo corta']

        # Deve contenere @
        if '@' not in email:
            return False, ['Manca @']

        # Dividi in parte locale e dominio
        parts = email.split('@')
        if len(parts) != 2:
            return False, ['Formato @ non valido']

        local_part, domain = parts

        # Parte locale non può essere vuota
        if not local_part:
            return False, ['Parte locale vuota']

        # Contiene numeri di telefono nel prefisso
        if re.search(r'^\d{5,}', local_part):
            issues.append('Inizia con numero di telefono')

        # Domini malformati comuni - pattern più completi
        bad_patterns = [
            r'\.com[a-z]+',      # .comsiamo, .comazienda
            r'\.it[a-z]+',       # .itservizio, .itsocial, .itdesideri
            r'\.net[a-z]+',      # .netqualcosa
            r'\.org[a-z]+',      # .orgqualcosa
            r'\s',               # Spazi
            r'\.{2,}',           # Doppi punti
            r'[^a-zA-Z0-9@._-]', # Caratteri non permessi
        ]

        for bad_pattern in bad_patterns:
            if re.search(bad_pattern, email):
                issues.append(f'Dominio malformato o caratteri non validi')
                break

        # Estrai TLD (estensione del dominio)
        tld_match = re.search(r'\.([a-zA-Z]{2,6})$', domain)

        # Lista TLD validi più comuni (non esaustiva ma copre la maggior parte)
        valid_tlds = {
            'com', 'it', 'net', 'org', 'edu', 'gov', 'mil', 'int',
            'eu', 'de', 'uk', 'fr', 'es', 'ch', 'nl', 'be', 'at',
            'info', 'biz', 'name', 'pro', 'aero', 'coop', 'museum',
            'io', 'co', 'me', 'tv', 'cc', 'ws', 'mobi', 'asia',
            'cat', 'jobs', 'tel', 'travel', 'xxx', 'tech', 'online',
            'shop', 'store', 'web', 'site', 'email', 'cloud'
        }

        if not tld_match:
            issues.append('TLD (estensione) non valido o mancante')
        else:
            tld = tld_match.group(1).lower()
            if tld not in valid_tlds:
                issues.append(f'TLD non riconosciuto: .{tld}')

        # Domini comuni invalidi o pattern sospetti
        invalid_patterns = [
            'compec', 'itsocialcreated', 'itservizio', 'itp.iva',
            'comsiamo', 'comazienda', 'itrinnai', 'comsi',
            'itquesto', 'commainetti.comitaly.mainetti.com',
            'itdesideri', 'comaziendacasi', 'itazienda', 'eumail'
        ]

        if any(bad_dom in domain.lower() for bad_dom in invalid_patterns):
            issues.append(f'Dominio invalido o malformato: {domain}')

        # Pattern email valido più stringente
        # Permette: lettere, numeri, punto, underscore, %, +, - nella parte locale
        # Permette: lettere, numeri, punto, trattino nel dominio
        # Richiede: almeno un punto nel dominio seguito da 2-6 lettere
        strict_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,6}$'

        if not re.match(strict_pattern, email):
            issues.append('Formato email non valido')

        is_valid = len(issues) == 0
        return is_valid, issues

    def clean_email_string(self, email_string):
        """Pulisce una stringa con più email separate da ; o ,"""
        if pd.isna(email_string) or not email_string:
            return '', [], []

        # Separa email
        emails = re.split(r'[;,]', str(email_string))

        valid_emails = []
        invalid_emails = []
        reasons = []

        for email in emails:
            email = email.strip()
            if not email:
                continue

            is_valid, issues = self.validate_email(email)

            if is_valid:
                valid_emails.append(email)
            else:
                invalid_emails.append(email)
                reasons.extend([f'{email}: {", ".join(issues)}'])

        return '; '.join(valid_emails), invalid_emails, reasons

    def handle(self, *args, **options):
        file_path = options['file']
        dry_run = options['dry_run']

        # Verifica file
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

        # Verifica colonna Email
        if 'Email Estratte' not in df.columns:
            self.stdout.write(self.style.ERROR('Colonna "Email Estratte" non trovata'))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[!] MODALITA DRY-RUN: Analisi senza salvare\n'))

        # Statistiche
        total_companies = 0
        companies_with_changes = 0
        total_emails_before = 0
        total_emails_after = 0
        total_invalid = 0
        invalid_details = []

        # Pulisci email
        self.stdout.write(self.style.WARNING('Pulizia email in corso...\n'))

        for idx, row in df.iterrows():
            if pd.isna(row.get('Email Estratte')):
                continue

            total_companies += 1
            email_string = str(row['Email Estratte'])

            # Conta email originali
            original_emails = [e.strip() for e in re.split(r'[;,]', email_string) if e.strip()]
            total_emails_before += len(original_emails)

            # Pulisci
            cleaned_string, invalid_emails, reasons = self.clean_email_string(email_string)

            # Conta email pulite
            cleaned_emails = [e.strip() for e in re.split(r'[;,]', cleaned_string) if e.strip()] if cleaned_string else []
            total_emails_after += len(cleaned_emails)

            # Se ci sono cambiamenti
            if invalid_emails:
                companies_with_changes += 1
                total_invalid += len(invalid_emails)

                company_name = str(row.get('Azienda', 'N/A'))[:50]

                # Mostra solo primi 20 dettagli
                if len(invalid_details) < 20:
                    self.stdout.write(f'\n[{company_name}]')
                    for reason in reasons:
                        self.stdout.write(f'  ❌ {reason}')
                    if cleaned_emails:
                        self.stdout.write(f'  ✅ Email valide rimaste: {", ".join(cleaned_emails)}')
                    else:
                        self.stdout.write(self.style.WARNING(f'  ⚠️  Nessuna email valida rimasta'))

                invalid_details.extend(reasons)

                # Aggiorna DataFrame
                df.at[idx, 'Email Estratte'] = cleaned_string
                df.at[idx, 'Numero Email'] = len(cleaned_emails)

        # Riepilogo
        self.stdout.write(self.style.SUCCESS('\n' + '='*60))
        self.stdout.write(self.style.SUCCESS('RIEPILOGO PULIZIA'))
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write(f'Aziende processate: {total_companies}')
        self.stdout.write(f'Aziende con modifiche: {companies_with_changes}')
        self.stdout.write(f'Email totali prima: {total_emails_before}')
        self.stdout.write(f'Email totali dopo: {total_emails_after}')
        self.stdout.write(self.style.ERROR(f'Email rimosse: {total_invalid}'))

        removed_percentage = (total_invalid / total_emails_before * 100) if total_emails_before > 0 else 0
        self.stdout.write(f'Percentuale rimossa: {removed_percentage:.1f}%')

        # Salva file pulito
        if not dry_run:
            try:
                path = Path(file_path)
                output_file = path.parent / f"{path.stem}_pulito{path.suffix}"

                df.to_excel(str(output_file), index=False, engine='openpyxl')
                self.stdout.write(self.style.SUCCESS(f'\n[OK] File pulito salvato in: {output_file}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'[ERRORE] Salvataggio file: {str(e)}'))
        else:
            self.stdout.write(self.style.WARNING('\n[!] DRY-RUN: File non salvato'))
            self.stdout.write('\nPer salvare il file pulito, esegui senza --dry-run')

        # Salva report errori
        if invalid_details and not dry_run:
            report_file = Path(file_path).parent / 'email_invalide_report.txt'
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write('REPORT EMAIL INVALIDE\n')
                f.write('='*60 + '\n\n')
                for detail in invalid_details:
                    f.write(f'{detail}\n')

            self.stdout.write(f'\n[FILE] Report email invalide: {report_file}')
