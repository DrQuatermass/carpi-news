"""
Pubblica gli articoli approvati in anticipo con data di pubblicazione futura, quando quella
data arriva: social, Telegram, motori di ricerca, cache della home e feed.

All'approvazione di un articolo programmato il segnale (home/signals.py, handle_article_approval)
localizza e si ferma: prima di questo comando nessuno lo riprendeva, e l'articolo compariva sul
sito alla sua ora senza uscire sui social. Gira dal cron di www-data ogni 5 minuti.

Un articolo e' "da pubblicare" se e' approvato, la sua data di pubblicazione e' arrivata da
meno di --finestra ore e non ha nessuna riga in SocialPublicationLog (mai condiviso). La
condivisione stessa salta le piattaforme gia' riuscite, e il lucchetto in cache evita doppioni
con un'approvazione fatta nello stesso momento dall'admin.
"""
from datetime import timedelta

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from home.models import Articolo, SocialPublicationLog


def articoli_da_pubblicare(finestra_ore=48, adesso=None):
    adesso = adesso or timezone.now()
    gia_condivisi = SocialPublicationLog.objects.filter(articolo_id__isnull=False).values('articolo_id')
    return (Articolo.objects
            .filter(Q(is_pubbliredazionale=False) | Q(payment_status='completed'),
                    approvato=True,
                    data_pubblicazione__lte=adesso,
                    data_pubblicazione__gte=adesso - timedelta(hours=finestra_ore))
            .exclude(id__in=gia_condivisi)
            .order_by('data_pubblicazione'))


class Command(BaseCommand):
    help = "Pubblica sui social gli articoli approvati in anticipo la cui data di pubblicazione e' arrivata"

    def add_arguments(self, parser):
        parser.add_argument('--finestra', type=int, default=48,
                            help="Ore all'indietro dalla data di pubblicazione (default 48): piu' "
                                 "vecchi non si pubblicano, per non ripescare articoli mai condivisi")
        parser.add_argument('--dry-run', action='store_true', help='Elenca senza pubblicare')

    def handle(self, *args, **options):
        articoli = list(articoli_da_pubblicare(options['finestra']))
        if not articoli:
            return
        for a in articoli:
            ora = timezone.localtime(a.data_pubblicazione).strftime('%d/%m %H:%M')
            self.stdout.write(f"{timezone.localtime():%d/%m %H:%M} articolo {a.id} programmato {ora}: {a.titolo}")
        if options['dry_run']:
            return

        from home.signals import (_share_article_background, ensure_publication_images_ready,
                                  generate_responsive_images_for_article, invalidate_rss_feeds)
        from home.indexing_notifier import notifier
        from django.conf import settings

        # Home e liste sono in cache: senza svuotarla l'articolo arriva in home solo a cache scaduta
        invalidate_rss_feeds()
        cache.clear()

        for a in articoli:
            ensure_publication_images_ready(a)
            # Il segnale le genera in un thread, che qui morirebbe con il processo
            generate_responsive_images_for_article(Articolo.objects.get(pk=a.pk))
            # Sincrono: anche i thread della condivisione morirebbero a fine comando
            _share_article_background(a.id, a.titolo)
            if not a.escluso_da_google:
                try:
                    notifier.notify_article_published(f"{settings.SITE_URL}/articolo/{a.slug}/")
                except Exception as e:
                    self.stderr.write(f"Notifica motori di ricerca fallita per {a.id}: {e}")
            n = SocialPublicationLog.objects.filter(articolo=a, success=True).count()
            self.stdout.write(f"  -> articolo {a.id}: {n} pubblicazioni social riuscite")
