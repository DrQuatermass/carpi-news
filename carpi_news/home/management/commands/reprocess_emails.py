from django.core.management.base import BaseCommand
from home.models import MonitorConfig
import imaplib
import email as email_lib


class Command(BaseCommand):
    help = 'Riprocessa le ultime N email (anche se già lette)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=5,
            help='Numero di email da riprocessare (default: 5)'
        )
        parser.add_argument(
            '--mark-unread',
            action='store_true',
            help='Marca le email come NON LETTE per permettere al monitor di riprocessarle'
        )

    def handle(self, *args, **options):
        count = options['count']
        mark_unread = options['mark_unread']

        try:
            monitor = MonitorConfig.objects.get(name='Email Comunicati Stampa')
            config = monitor.config_data

            imap_server = config.get('imap_server')
            imap_port = config.get('imap_port', 993)
            email_addr = config.get('email')
            password = config.get('password')
            mailbox = config.get('mailbox', 'INBOX')

            self.stdout.write(f'Connessione a {imap_server}...')
            mail = imaplib.IMAP4_SSL(imap_server, imap_port)
            mail.login(email_addr, password)
            mail.select(mailbox)

            # Prendi ultime N email
            status, messages = mail.search(None, 'ALL')
            if status == 'OK':
                email_ids = messages[0].split()[-count:]
                self.stdout.write(self.style.SUCCESS(f'Trovate {len(email_ids)} email\n'))

                for i, email_id in enumerate(email_ids, 1):
                    try:
                        # Fetch email
                        status, msg_data = mail.fetch(email_id, '(RFC822 FLAGS)')
                        if status != 'OK':
                            continue

                        # Parse email
                        email_message = email_lib.message_from_bytes(msg_data[0][1])

                        subject = email_message.get('Subject', 'Nessun soggetto')
                        sender = email_message.get('From', 'Mittente sconosciuto')
                        date = email_message.get('Date', 'Data sconosciuta')

                        # Check se è letta
                        flags = msg_data[1].decode() if len(msg_data) > 1 else ''
                        is_seen = '\\Seen' in flags

                        self.stdout.write(f'\n--- Email {i}/{len(email_ids)} (ID: {email_id.decode()}) ---')
                        self.stdout.write(f'Da: {sender}')
                        self.stdout.write(f'Soggetto: {subject}')
                        self.stdout.write(f'Data: {date}')
                        self.stdout.write(f'Stato: {"LETTA" if is_seen else "NON LETTA"}')

                        if mark_unread:
                            mail.store(email_id, '-FLAGS', '\\Seen')
                            self.stdout.write(self.style.SUCCESS('✓ Marcata come NON LETTA'))

                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f'Errore: {e}'))

                mail.close()
                mail.logout()

                if mark_unread:
                    self.stdout.write(self.style.SUCCESS(f'\n✓ {len(email_ids)} email marcate come NON LETTE'))
                    self.stdout.write('Il monitor le riprocesserà al prossimo controllo')
                else:
                    self.stdout.write('\n💡 Usa --mark-unread per marcarle come non lette e riprocessarle')

        except MonitorConfig.DoesNotExist:
            self.stdout.write(self.style.ERROR('Monitor "Email Comunicati Stampa" non trovato'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Errore: {e}'))
            import traceback
            self.stdout.write(traceback.format_exc())
