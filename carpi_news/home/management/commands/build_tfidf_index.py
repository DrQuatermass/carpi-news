"""
Costruisce l'indice TF-IDF per il gate di rilevanza del linking interno.

Calcola l'IDF sul corpus degli articoli approvati, lo salva su file
(tfidf_data/idf.json) e popola Articolo.tfidf_terms per ogni articolo.

Nessun costo API: solo Python + DB. Da rilanciare periodicamente (es. cron
settimanale) per tenere l'indice aggiornato man mano che crescono gli articoli.
"""
from django.core.management.base import BaseCommand
from home import tfidf_relevance


class Command(BaseCommand):
    help = 'Calcola IDF del corpus e popola Articolo.tfidf_terms (per il linking semantico)'

    def handle(self, *args, **options):
        self.stdout.write('Calcolo indice TF-IDF sugli articoli approvati...')

        def progress(done, total):
            self.stdout.write(f'  {done}/{total} articoli vettorizzati')

        n, vocab, updated = tfidf_relevance.build_index(batch_log=progress)

        if n == 0:
            self.stdout.write(self.style.WARNING('Nessun articolo approvato: indice non creato.'))
            return

        self.stdout.write(self.style.SUCCESS(
            f'\n[OK] Corpus: {n} articoli | vocabolario IDF: {vocab} termini | '
            f'vettori salvati: {updated}'
        ))
        self.stdout.write(f'Indice IDF: {tfidf_relevance._idf_path()}')
