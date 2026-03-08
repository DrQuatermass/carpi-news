import logging
from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.conf import settings

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Invia la newsletter giornaliera agli iscritti attivi'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula invio senza spedire email reali',
        )
        parser.add_argument(
            '--preview-only',
            action='store_true',
            help='Mostra solo quanti articoli verrebbe inclusi, poi esce',
        )

    def handle(self, *args, **options):
        from home.views import _get_newsletter_context
        from home.models import NewsletterSubscriber, NewsletterLog

        dry_run = options['dry_run']
        preview_only = options['preview_only']

        # Recupera contenuto newsletter
        ctx = _get_newsletter_context()
        articoli_oggi = ctx['articoli_oggi']   # dict {categoria: [articoli]}
        articoli_ieri = ctx['articoli_ieri']   # dict {categoria: [articoli]}
        eventi_domani = ctx['eventi_domani']   # list

        num_oggi = sum(len(v) for v in articoli_oggi.values())
        num_ieri = sum(len(v) for v in articoli_ieri.values())
        num_eventi = len(eventi_domani)
        num_totale = num_oggi + num_ieri + num_eventi

        self.stdout.write(
            f"Articoli oggi: {num_oggi} | Articoli ieri: {num_ieri} | "
            f"Eventi domani: {num_eventi} | Totale: {num_totale}"
        )

        if preview_only:
            return

        if num_totale == 0:
            self.stdout.write(self.style.WARNING("Nessun contenuto da inviare. Newsletter saltata."))
            NewsletterLog.objects.create(
                oggetto='Newsletter giornaliera',
                num_destinatari=0,
                num_articoli=0,
                stato='skipped',
                note='Nessun articolo disponibile',
            )
            return

        # Iscritti attivi
        subscribers = list(NewsletterSubscriber.objects.filter(attivo=True))
        if not subscribers:
            self.stdout.write(self.style.WARNING("Nessun iscritto attivo. Newsletter saltata."))
            NewsletterLog.objects.create(
                oggetto='Newsletter giornaliera',
                num_destinatari=0,
                num_articoli=num_totale,
                stato='skipped',
                note='Nessun iscritto attivo',
            )
            return

        site_url = getattr(settings, 'SITE_URL', 'https://ombradelportico.it')
        oggetto = f"Ombra del Portico Newsletter — {ctx['data_oggi'].strftime('%d/%m/%Y')}"
        from_email = settings.DEFAULT_FROM_EMAIL

        inviati = 0
        errori = 0

        # Apre una singola connessione SMTP per tutti gli invii (più efficiente con molti iscritti)
        connection = get_connection() if not dry_run else None
        try:
            if connection:
                connection.open()

            for subscriber in subscribers:
                email_ctx = {
                    **ctx,
                    'subscriber': subscriber,
                    'site_url': site_url,
                }
                try:
                    html_body = render_to_string('newsletter/email_template.html', email_ctx)
                    text_body = (
                        f"{oggetto}\n\n"
                        f"Leggi le notizie su {site_url}\n\n"
                        f"Disiscrivi: {site_url}/newsletter/disiscrivi/{subscriber.token_disiscrizione}/"
                    )

                    if dry_run:
                        self.stdout.write(f"  [DRY-RUN] Invio a {subscriber.email}")
                        inviati += 1
                        continue

                    msg = EmailMultiAlternatives(
                        subject=oggetto,
                        body=text_body,
                        from_email=from_email,
                        to=[subscriber.email],
                        connection=connection,
                    )
                    msg.attach_alternative(html_body, 'text/html')
                    msg.send()
                    inviati += 1

                except Exception as e:
                    errori += 1
                    logger.error(f"Errore invio newsletter a {subscriber.email}: {e}")
                    self.stdout.write(self.style.ERROR(f"  Errore per {subscriber.email}: {e}"))
        finally:
            if connection:
                connection.close()

        # Log risultato
        if errori == 0:
            stato = 'success'
        elif inviati > 0:
            stato = 'partial'
        else:
            stato = 'failed'

        prefix = "[DRY-RUN] " if dry_run else ""
        note = f"{prefix}Inviati: {inviati}, Errori: {errori}"
        if dry_run:
            note += " — Nessuna email reale spedita"

        NewsletterLog.objects.create(
            oggetto=oggetto,
            num_destinatari=inviati,
            num_articoli=num_totale,
            stato=stato,
            note=note,
        )

        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Newsletter inviata: {inviati}/{len(subscribers)} destinatari, {num_totale} articoli, stato={stato}"
        ))
