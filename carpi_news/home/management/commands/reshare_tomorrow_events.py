"""
Comando per ricondividere automaticamente sui social gli articoli
con data_evento = domani (per ricordare eventi imminenti)
"""
from django.core.management.base import BaseCommand
from django.db import models
from home.models import Articolo, SocialPublicationLog
from home.social_sharing import social_manager
from datetime import date, timedelta
import logging
import time

from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Ricondivide sui social gli articoli approvati con data_evento = domani'

    def add_arguments(self, parser):
        parser.add_argument(
            '--data',
            type=str,
            help='Data specifica (YYYY-MM-DD). Default: domani',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostra anteprima senza condividere',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Ricondivide anche se già pubblicato oggi',
        )
        parser.add_argument(
            '--entro',
            type=str,
            default='11:50',
            help="Ora (HH:MM) a cui parte l'ultima ricondivisione: gli eventi si distribuiscono a "
                 "intervalli uguali da adesso a quell'ora. Default 11:50",
        )
        parser.add_argument(
            '--subito',
            action='store_true',
            help='Ricondivide tutto di seguito, senza distribuire nel tempo',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']

        # Determina la data target (domani)
        if options['data']:
            try:
                target_date = date.fromisoformat(options['data'])
            except ValueError:
                self.stdout.write(self.style.ERROR(f'Formato data non valido: {options["data"]}. Usa YYYY-MM-DD'))
                return
        else:
            target_date = date.today() + timedelta(days=1)

        self.stdout.write(f'\n{"="*70}')
        self.stdout.write(self.style.WARNING(f'Ricondivisione eventi per {target_date.strftime("%d/%m/%Y")}'))
        reshare_platforms = self._event_reshare_platforms()
        self.stdout.write(
            self.style.NOTICE(
                "\nPiattaforme ricondivisione eventi: "
                + ", ".join(reshare_platforms)
                + " (su Facebook torna il post con il link; il Reel solo se non è mai uscito)"
            )
        )

        if dry_run:
            self.stdout.write(self.style.WARNING('MODALITÀ DRY-RUN: Nessuna condivisione verrà effettuata'))
        if force:
            self.stdout.write(self.style.WARNING('MODALITÀ FORCE: Ricondivide anche se già pubblicato oggi'))
        self.stdout.write(f'{"="*70}\n')

        # Cerca articoli approvati con data_evento = target_date
        # Non ancora usciti (approvati in anticipo con data futura): li pubblica pubblica_programmati
        articoli_query = Articolo.objects.filter(
            data_evento=target_date,
            approvato=True,
            data_pubblicazione__lte=timezone.now(),
        ).order_by('titolo')

        # I piu' letti per primi: escono agli orari migliori (vedi _importanza)
        articoli = sorted(articoli_query, key=self._importanza, reverse=True)

        if not articoli:
            self.stdout.write(self.style.WARNING(f'[X] Nessun articolo trovato con data_evento = {target_date.strftime("%d/%m/%Y")}'))
            self.stdout.write('  Verifica che gli articoli abbiano:')
            self.stdout.write('  - Campo data_evento compilato')
            self.stdout.write('  - Stato approvato=True')
            return

        self.stdout.write(self.style.SUCCESS(f'[OK] Trovati {len(articoli)} articoli da ricondividere:\n'))
        for articolo in articoli:
            self.stdout.write(f'  • {articolo.titolo} ({articolo.categoria})')

        if dry_run:
            self.stdout.write('\n' + '='*70)
            self.stdout.write(self.style.SUCCESS('ANTEPRIMA - Articoli che verrebbero ricondivisi:'))
            self.stdout.write('='*70)
            for articolo in articoli:
                self.stdout.write(f'\n[{articolo.id}] {articolo.titolo}')
                self.stdout.write(f'  Categoria: {articolo.categoria}')
                self.stdout.write(f'  Data evento: {articolo.data_evento.strftime("%d/%m/%Y")}')
                self.stdout.write(f'  URL: /articolo/{articolo.slug}/')
                self.stdout.write(f'  Immagine: {"Sì" if articolo.has_shareable_image else "No"}')
                self.stdout.write(f'  Piattaforme: {", ".join(reshare_platforms)}')
            self.stdout.write('\n' + '='*70)
            self.stdout.write(self.style.WARNING('Esegui senza --dry-run per condividere realmente'))
            return

        # Ricondividi ogni articolo
        total_success = 0
        total_skipped = 0
        total_failed = 0

        # Distribuzione nel tempo (dal 23/11/2026): prima uscivano uno dietro l'altro, a 4-5 minuti,
        # e Facebook ne mostrava pochissimo (21/11: cinque Reel in un quarto d'ora, 20-37
        # visualizzazioni l'uno contro le 270-340 di quelli usciti da soli).
        orari = self._orari(len(articoli), options['entro'], options['subito'])
        if orari:
            self.stdout.write(self.style.NOTICE('\nOrari previsti:'))
            for articolo, quando in zip(articoli, orari):
                self.stdout.write(f'  {quando:%H:%M}  {articolo.titolo}')

        for indice, articolo in enumerate(articoli):
            if orari:
                self._aspetta(orari[indice])
                # Dopo ore di attesa l'articolo puo' essere cambiato o non essere piu' approvato
                articolo = Articolo.objects.filter(pk=articolo.pk, approvato=True).first()
                if articolo is None:
                    total_skipped += 1
                    continue
            self.stdout.write(f'\n{"="*70}')
            self.stdout.write(f'Ricondivisione: {articolo.titolo}')
            self.stdout.write(f'{"="*70}')

            # Se non è force, controlla se già condiviso oggi
            if not force:
                today_publications = SocialPublicationLog.objects.filter(
                    articolo=articolo,
                    published_at__date=date.today(),
                    success=True
                ).count()

                if today_publications > 0:
                    self.stdout.write(self.style.WARNING(f'[SKIP] Già condiviso oggi ({today_publications} piattaforme)'))
                    total_skipped += 1
                    continue

            # Condividi sulle piattaforme abilitate per reminder evento. Su Facebook l'articolo
            # torna come post con il link: il Reel esce gia' all'approvazione e non si ripete.
            # IMPORTANTE: Per la ricondivisione, rimuoviamo temporaneamente i log delle pubblicazioni precedenti
            # per forzare la condivisione anche se l'articolo è già stato pubblicato in passato
            try:
                # Salva i log esistenti per riferimento
                existing_logs = list(SocialPublicationLog.objects.filter(articolo=articolo, success=True))

                # Cancella temporaneamente i log per permettere la ricondivisione
                # (non quello del Reel Facebook: non si ripubblica, e senza il suo log il recupero
                # automatico dei fallimenti lo crederebbe mancante e ne farebbe un altro)
                SocialPublicationLog.objects.filter(articolo=articolo).exclude(platform='facebook_reel').delete()

                # Esegui la condivisione (ora non troverà log e condividerà)
                results = social_manager.retry_failed_platforms_only(
                    articolo,
                    only_platforms=reshare_platforms,
                )
                self._ripristina_media_ids(articolo, existing_logs)

                # Mostra risultati per piattaforma
                for platform, success in results.items():
                    status = "✓" if success else "✗"
                    style = self.style.SUCCESS if success else self.style.ERROR
                    self.stdout.write(style(f'  {status} {platform.capitalize()}: {"OK" if success else "FAILED"}'))

                # Conta successi
                success_count = sum(1 for s in results.values() if s)
                if success_count > 0:
                    total_success += 1
                    self.stdout.write(self.style.SUCCESS(f'[OK] Condiviso su {success_count}/{len(results)} piattaforme'))
                else:
                    total_failed += 1
                    self.stdout.write(self.style.ERROR(f'[FAIL] Nessuna piattaforma riuscita'))

            except Exception as e:
                total_failed += 1
                self.stdout.write(self.style.ERROR(f'[ERROR] Errore condivisione: {str(e)}'))
                logger.error(f"Errore ricondivisione articolo {articolo.id}: {e}")

        # Riepilogo finale
        self.stdout.write(f'\n{"="*70}')
        self.stdout.write(self.style.SUCCESS('RIEPILOGO RICONDIVISIONE'))
        self.stdout.write(f'{"="*70}')
        self.stdout.write(f'  Articoli trovati:     {len(articoli)}')
        self.stdout.write(f'  Condivisi con successo: {total_success}')
        if total_skipped > 0:
            self.stdout.write(f'  Saltati (già pubblicati): {total_skipped}')
        if total_failed > 0:
            self.stdout.write(self.style.ERROR(f'  Falliti:              {total_failed}'))
        self.stdout.write(f'{"="*70}\n')

    @staticmethod
    def _importanza(articolo):
        """Letture sul sito per giorno di vita dell'articolo: l'interesse che l'evento ha gia'
        mostrato. Il contatore comprende anche i robot, che pero' passano su tutti gli articoli
        allo stesso modo: per mettere in ordine basta. A parita', prima chi ha la foto."""
        pubblicato = articolo.data_pubblicazione or articolo.data_creazione
        giorni = max(1.0, (timezone.now() - pubblicato).total_seconds() / 86400) if pubblicato else 1.0
        return ((articolo.views or 0) / giorni, bool(articolo.has_shareable_image))

    @staticmethod
    def _orari(quanti, entro, subito=False):
        """Orari di ricondivisione: il primo adesso, l'ultimo all'ora `entro`, gli altri a
        intervalli uguali in mezzo. Lista vuota se non c'e' da distribuire (un solo evento,
        --subito, ora gia' passata, formato sbagliato): allora escono di seguito come prima."""
        if subito or quanti < 2:
            return []
        adesso = timezone.localtime()
        try:
            ore, minuti = (int(x) for x in entro.split(':'))
            fine = adesso.replace(hour=ore, minute=minuti, second=0, microsecond=0)
        except (ValueError, AttributeError):
            return []
        if fine <= adesso:
            return []
        passo = (fine - adesso) / (quanti - 1)
        return [adesso + passo * i for i in range(quanti)]

    @staticmethod
    def _aspetta(quando):
        """Dorme fino a `quando`. La connessione al database si chiude prima: lasciata aperta
        per ore, alla ripresa sarebbe scaduta."""
        attesa = (quando - timezone.localtime()).total_seconds()
        if attesa <= 0:
            return
        connection.close()
        time.sleep(attesa)

    @staticmethod
    def _ripristina_media_ids(articolo, existing_logs):
        """Rimette nei log nuovi gli id Instagram dei contenuti gia' pubblicati.

        I log si cancellano per poter ripubblicare, ma post, Reel e Storie di prima restano
        online: senza i loro id il webhook dei DM non riconosce piu' l'articolo di chi li
        commenta.
        """
        for old in existing_logs:
            old_ids = [str(m) for m in ([old.instagram_media_id] + list(old.instagram_media_ids or [])) if m]
            if not old_ids:
                continue
            new = SocialPublicationLog.objects.filter(articolo=articolo, platform=old.platform).first()
            if new is None:
                # Ripubblicazione non riuscita (o piattaforma non ricondivisa): si ricrea il log
                # di prima, cosi' resta anche il segno della pubblicazione originale
                old.pk = None
                old.save()
                continue
            media_ids = list(new.instagram_media_ids or [])
            for media_id in old_ids:
                if media_id not in media_ids:
                    media_ids.insert(0, media_id)
            new.instagram_media_ids = media_ids[-50:]
            update_fields = ['instagram_media_ids']
            if not new.instagram_media_id:
                new.instagram_media_id = old_ids[0]
                update_fields.append('instagram_media_id')
            new.save(update_fields=update_fields)

    @staticmethod
    def _event_reshare_platforms():
        """Piattaforme del promemoria evento: tutte quelle accese.

        Fino al 19/11/2026 il post Facebook con il link veniva sostituito dal Reel, forzato
        anche con FACEBOOK_REEL_ENABLED=False. Ora il Reel esce all'approvazione di ogni
        articolo e il promemoria ricondivide il post. Il Reel resta nell'elenco ma il suo log
        non viene cancellato, quindi parte solo per gli eventi che non l'hanno mai avuto
        (quelli approvati prima del cambio)."""
        return [platform for platform, config in social_manager.platforms.items() if config.get('enabled')]
