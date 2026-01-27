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
        if dry_run:
            self.stdout.write(self.style.WARNING('MODALITÀ DRY-RUN: Nessuna condivisione verrà effettuata'))
        if force:
            self.stdout.write(self.style.WARNING('MODALITÀ FORCE: Ricondivide anche se già pubblicato oggi'))
        self.stdout.write(f'{"="*70}\n')

        # Cerca articoli approvati con data_evento = target_date
        articoli_query = Articolo.objects.filter(
            data_evento=target_date,
            approvato=True
        ).order_by('titolo')

        articoli = list(articoli_query)

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
                self.stdout.write(f'  Immagine: {"Sì" if articolo.foto else "No"}')
            self.stdout.write('\n' + '='*70)
            self.stdout.write(self.style.WARNING('Esegui senza --dry-run per condividere realmente'))
            return

        # Ricondividi ogni articolo
        total_success = 0
        total_skipped = 0
        total_failed = 0

        for articolo in articoli:
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

            # Condividi su tutte le piattaforme abilitate
            # IMPORTANTE: Per la ricondivisione, rimuoviamo temporaneamente i log delle pubblicazioni precedenti
            # per forzare la condivisione anche se l'articolo è già stato pubblicato in passato
            try:
                # Salva i log esistenti per riferimento
                existing_logs = list(SocialPublicationLog.objects.filter(articolo=articolo, success=True))

                # Cancella temporaneamente i log per permettere la ricondivisione
                SocialPublicationLog.objects.filter(articolo=articolo).delete()

                # Esegui la condivisione (ora share_article_on_approval non troverà log e condividerà)
                results = social_manager.share_article_on_approval(articolo)

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
