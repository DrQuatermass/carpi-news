"""
Management command per processare pubbliredazionali in attesa
Genera articoli e invia email di notifica agli utenti

Schedulazione consigliata: ogni ora
Cron: 0 */1 * * * cd /path && python manage.py process_pending_pubbliredazionali
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_datetime
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
        parser.add_argument(
            '--status',
            action='store_true',
            help='Mostra lo stato dei pubbliredazionali in coda senza processarli',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostra quali pubbliredazionali verrebbero processati senza generarli',
        )

    def handle(self, *args, **options):
        now = timezone.now()
        dry_run = options.get('dry_run')
        show_status = options.get('status')

        if options.get('pubbliredazionale_id'):
            # Processa pubbliredazionale specifico
            pub_id = options['pubbliredazionale_id']
            try:
                pub = Articolo.objects.get(id=pub_id, is_pubbliredazionale=True)
                if show_status or dry_run:
                    self.write_pub_status(pub, now)
                    return
                self.process_pubbliredazionale(pub)
            except Articolo.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Pubbliredazionale {pub_id} non trovato'))
            return

        pending = list(Articolo.objects.filter(
            is_pubbliredazionale=True,
            contenuto='',
            payment_status='pending',
        ).order_by('data_creazione'))

        if show_status:
            self.stdout.write(f'Pubbliredazionali pending senza contenuto: {len(pending)}')
            for pub in pending:
                self.write_pub_status(pub, now)
            return

        # Filtra per quelli che hanno aspettato abbastanza
        ready_to_process = []
        for pub in pending:
            is_complete, reason = self.is_interview_complete(pub)
            if not is_complete:
                logger.info(f"Pubbliredazionale {pub.id} non pronto: {reason}")
                continue

            # Calcola quando dovrebbe essere pronto basandosi sull'orario reale
            # di completamento intervista. Per record vecchi usa data_modifica,
            # che viene aggiornata quando si salva l'intervista/foto.
            base_time = self.get_interview_completed_at(pub)
            ready_time = self.calculate_ready_time(base_time)

            if now >= ready_time:
                ready_to_process.append(pub)
                logger.info(
                    "Pubbliredazionale %s pronto per elaborazione "
                    "(completed_at: %s, ready: %s)",
                    pub.id,
                    base_time,
                    ready_time,
                )
            else:
                logger.info(
                    "Pubbliredazionale %s in attesa fino a %s "
                    "(completed_at: %s)",
                    pub.id,
                    ready_time,
                    base_time,
                )

        if not ready_to_process:
            self.stdout.write(self.style.SUCCESS('Nessun pubbliredazionale da processare'))
            return

        self.stdout.write(self.style.SUCCESS(f'Trovati {len(ready_to_process)} pubbliredazionali da processare'))

        if dry_run:
            for pub in ready_to_process:
                self.write_pub_status(pub, now)
            return

        # Processa ogni pubbliredazionale
        for pub in ready_to_process:
            self.process_pubbliredazionale(pub)

    def is_interview_complete(self, pub):
        """Ritorna se l'intervista ha materiale sufficiente per generare."""
        interview_data = pub.interview_data or {}
        if not interview_data:
            return False, 'interview_data vuoto'

        conversation = interview_data.get('conversation') or []
        questions_asked = len([
            msg for msg in conversation
            if isinstance(msg, dict) and msg.get('role') == 'agent'
        ])
        user_answers = len([
            msg for msg in conversation
            if isinstance(msg, dict) and msg.get('role') == 'user'
        ])

        if interview_data.get('interview_complete') is True:
            return True, 'intervista marcata completa'

        if questions_asked >= 3 and user_answers >= 2:
            return True, 'intervista completa dedotta dalla conversazione'

        return False, f'intervista incompleta ({questions_asked} domande, {user_answers} risposte)'

    def get_interview_completed_at(self, pub):
        """Timestamp base per il ritardo editoriale."""
        interview_data = pub.interview_data or {}
        completed_at = interview_data.get('interview_completed_at')

        if completed_at:
            parsed = parse_datetime(completed_at)
            if parsed:
                if timezone.is_naive(parsed):
                    return timezone.make_aware(parsed, timezone.get_current_timezone())
                return parsed
            logger.warning(
                "interview_completed_at non valido per pubbliredazionale %s: %r",
                pub.id,
                completed_at,
            )

        return pub.data_modifica or pub.data_creazione

    def write_pub_status(self, pub, now):
        is_complete, reason = self.is_interview_complete(pub)
        base_time = self.get_interview_completed_at(pub)
        ready_time = self.calculate_ready_time(base_time) if is_complete else None
        state = 'READY' if is_complete and now >= ready_time else 'WAIT'
        if not is_complete:
            state = 'SKIP'

        self.stdout.write(
            f'[{state}] id={pub.id} azienda="{pub.nome_azienda}" '
            f'created={timezone.localtime(pub.data_creazione).strftime("%Y-%m-%d %H:%M")} '
            f'modified={timezone.localtime(pub.data_modifica).strftime("%Y-%m-%d %H:%M")} '
            f'completed_at={timezone.localtime(base_time).strftime("%Y-%m-%d %H:%M")} '
            f'ready_at={timezone.localtime(ready_time).strftime("%Y-%m-%d %H:%M") if ready_time else "-"} '
            f'reason="{reason}" foto={bool(pub.foto_upload)}'
        )

    def calculate_ready_time(self, created_at):
        """
        Calcola quando il pubbliredazionale dovrebbe essere pronto

        Logica:
        - Intervista completata 08:00-18:00 → Pronto dopo 107 minuti (1h 47min)
        - Intervista completata 18:00-08:00 → Pronto ore 09:02 giorno dopo
        """
        local_created_at = timezone.localtime(created_at)
        hour = local_created_at.hour

        if 8 <= hour < 18:
            # Orario lavorativo → Pronto dopo 107 minuti
            ready = local_created_at + timedelta(minutes=107)
        else:
            # Sera/Notte → Pronto alle 09:02 del giorno dopo
            next_day = local_created_at + timedelta(days=1)
            ready = next_day.replace(hour=9, minute=2, second=0, microsecond=0)

        return ready

    def process_pubbliredazionale(self, pub):
        """Genera articolo e invia email di notifica"""
        try:
            self.stdout.write(f'Elaborazione pubbliredazionale {pub.id} - {pub.nome_azienda}...')

            # Genera articolo
            agent = PubbliredazioneAgent(pub)
            result = agent._complete_interview_and_generate()

            if not result.get('success'):
                logger.error(f"Errore generazione articolo {pub.id}: {result.get('error')}")
                self.stdout.write(self.style.ERROR(f'❌ Errore: {result.get("error")}'))
                return

            self.stdout.write(self.style.SUCCESS(f'✅ Articolo generato: {pub.titolo}'))

            # Invia email di notifica all'utente
            self.send_notification_email(pub)

            # Invia email di notifica all'admin
            self.send_admin_notification_email(pub)

        except Exception as e:
            logger.error(f"Errore processamento pubbliredazionale {pub.id}: {e}", exc_info=True)
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

    def send_admin_notification_email(self, pub):
        """Invia email all'admin per approvazione pubbliredazionale generato"""
        try:
            from django.contrib.auth.models import User

            admin_emails = User.objects.filter(is_superuser=True).values_list('email', flat=True)
            admin_emails = [email for email in admin_emails if email]

            if not admin_emails:
                logger.warning("Nessun admin con email configurata")
                return

            admin_url = f"{settings.SITE_URL}/admin/home/articolo/{pub.id}/change/"
            preview_url = f"{settings.SITE_URL}/gestionale/pubbliredazionale/{pub.id}/preview/"

            subject = f'🔔 Nuovo pubbliredazionale da approvare: {pub.nome_azienda}'

            # Formatta nome intervistato con ruolo
            intervistato_info = f"{pub.intervistato_nome} {pub.intervistato_cognome}"
            if pub.intervistato_ruolo:
                intervistato_info += f" ({pub.intervistato_ruolo})"

            message = f"""Ciao,

un nuovo pubbliredazionale è stato generato e richiede la tua approvazione prima che l'utente possa procedere al pagamento.

Dettagli:
- Azienda: {pub.nome_azienda}
- Sito web: {pub.sito_web or 'N/A'}
- Utente: {pub.pubbliredazionale_user.username} ({pub.pubbliredazionale_user.email})
- Intervistato: {intervistato_info}
- Titolo articolo: {pub.titolo}

Azioni richieste:
1. Rivedi l'articolo in anteprima: {preview_url}
2. Approva o rifiuta dal pannello admin: {admin_url}

Una volta approvato, l'utente riceverà una email e potrà procedere al pagamento (€200).

---
Ombra del Portico - Sistema di gestione pubbliredazionali
"""

            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=admin_emails,
                fail_silently=False,
            )

            logger.info(f"Email admin inviata per pubbliredazionale {pub.id} a {', '.join(admin_emails)}")
            self.stdout.write(self.style.SUCCESS(f'📧 Email admin inviata a {", ".join(admin_emails)}'))

        except Exception as e:
            logger.error(f"Errore invio email admin per pubbliredazionale {pub.id}: {e}")
            self.stdout.write(self.style.WARNING(f'⚠️ Email admin non inviata: {str(e)}'))
