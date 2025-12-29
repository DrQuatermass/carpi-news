"""
Management command per processare pubbliredazionali in attesa
Genera articoli e invia email di notifica agli utenti

Schedulazione consigliata: ogni ora
Cron: 0 */1 * * * cd /path && python manage.py process_pending_pubbliredazionali
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from home.models import Articolo
from home.publiredazionale_agent import PubbliredazioneAgent
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Processa pubbliredazionali con intervista completata e genera articoli'

    def add_arguments(self, parser):
        parser.add_argument(
            '--pubbliredazionale-id',
            type=int,
            help='Processa solo un pubbliredazionale specifico',
        )

    def handle(self, *args, **options):
        now = timezone.now()

        if options.get('pubbliredazionale_id'):
            # Processa pubbliredazionale specifico
            pub_id = options['pubbliredazionale_id']
            try:
                pub = Articolo.objects.get(id=pub_id, is_pubbliredazionale=True)
                self.process_pubbliredazionale(pub)
            except Articolo.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Pubbliredazionale {pub_id} non trovato'))
            return

        # Trova pubbliredazionali pronti per essere processati
        pending = Articolo.objects.filter(
            is_pubbliredazionale=True,
            status='interview_completed',  # Intervista completata
            contenuto='',  # Articolo non ancora generato
            payment_status='pending'  # Non ancora pagato
        )

        # Filtra per quelli che hanno aspettato abbastanza
        ready_to_process = []
        for pub in pending:
            # Calcola quando dovrebbe essere pronto basandosi sull'orario intervista
            ready_time = self.calculate_ready_time(pub.data_creazione)

            if now >= ready_time:
                ready_to_process.append(pub)
                logger.info(f"Pubbliredazionale {pub.id} pronto per elaborazione (creato: {pub.data_creazione}, ready: {ready_time})")

        if not ready_to_process:
            self.stdout.write(self.style.SUCCESS('Nessun pubbliredazionale da processare'))
            return

        self.stdout.write(self.style.SUCCESS(f'Trovati {len(ready_to_process)} pubbliredazionali da processare'))

        # Processa ogni pubbliredazionale
        for pub in ready_to_process:
            self.process_pubbliredazionale(pub)

    def calculate_ready_time(self, created_at):
        """
        Calcola quando il pubbliredazionale dovrebbe essere pronto

        Logica:
        - Intervista completata 08:00-18:00 → Pronto dopo 107 minuti (1h 47min)
        - Intervista completata 18:00-08:00 → Pronto ore 09:02 giorno dopo
        """
        hour = created_at.hour

        if 8 <= hour < 18:
            # Orario lavorativo → Pronto dopo 107 minuti
            ready = created_at + timedelta(minutes=107)
        else:
            # Sera/Notte → Pronto alle 09:02 del giorno dopo
            next_day = created_at + timedelta(days=1)
            ready = next_day.replace(hour=9, minute=2, second=0, microsecond=0)

        return ready

    def process_pubbliredazionale(self, pub):
        """Genera articolo e invia email di notifica"""
        try:
            self.stdout.write(f'Elaborazione pubbliredazionale {pub.id} - {pub.nome_azienda}...')

            # Marca come "in elaborazione"
            pub.status = 'article_generating'
            pub.save()

            # Genera articolo
            agent = PubbliredazioneAgent(pub)
            result = agent._complete_interview_and_generate()

            if not result.get('success'):
                logger.error(f"Errore generazione articolo {pub.id}: {result.get('error')}")
                pub.status = 'article_generation_failed'
                pub.save()
                self.stdout.write(self.style.ERROR(f'❌ Errore: {result.get("error")}'))
                return

            # Aggiorna status
            pub.status = 'article_ready'
            pub.save()

            self.stdout.write(self.style.SUCCESS(f'✅ Articolo generato: {pub.titolo}'))

            # Invia email di notifica
            self.send_notification_email(pub)

        except Exception as e:
            logger.error(f"Errore processamento pubbliredazionale {pub.id}: {e}", exc_info=True)
            pub.status = 'article_generation_failed'
            pub.save()
            self.stdout.write(self.style.ERROR(f'❌ Eccezione: {str(e)}'))

    def send_notification_email(self, pub):
        """Invia email all'utente con link anteprima articolo"""
        try:
            user_email = pub.pubbliredazionale_user.email
            preview_url = f"{settings.SITE_URL}/gestionale/pubbliredazionale/{pub.id}/preview/"

            subject = f'Il tuo pubbliredazionale è pronto - {pub.nome_azienda}'

            message = f"""Gentile {pub.pubbliredazionale_user.first_name or 'Cliente'},

la redazione di Ombra del Portico ha completato l'elaborazione del suo pubbliredazionale per {pub.nome_azienda}.

L'articolo è ora disponibile in anteprima al seguente link:
{preview_url}

Potrà:
- Visualizzare l'anteprima completa dell'articolo
- Richiedere eventuali modifiche
- Procedere con il pagamento per la pubblicazione

Il pubbliredazionale rimarrà disponibile per 30 giorni prima della pubblicazione.

Cordiali saluti,
La Redazione di Ombra del Portico

---
Questo è un messaggio automatico. Per assistenza, risponda a questa email.
"""

            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user_email],
                fail_silently=False,
            )

            logger.info(f"Email inviata a {user_email} per pubbliredazionale {pub.id}")
            self.stdout.write(self.style.SUCCESS(f'📧 Email inviata a {user_email}'))

        except Exception as e:
            logger.error(f"Errore invio email per pubbliredazionale {pub.id}: {e}")
            self.stdout.write(self.style.WARNING(f'⚠️ Email non inviata: {str(e)}'))
