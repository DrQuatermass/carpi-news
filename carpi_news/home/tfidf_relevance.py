# -*- coding: utf-8 -*-
"""
Rilevanza semantica leggera basata su TF-IDF, per il linking interno.

Perche' TF-IDF e non embedding: su questo corpus iperlocale (tutte notizie su
Carpi) gli embedding appiattiscono tutto in un unico grumo (similarita' di base
alta ovunque). L'IDF invece azzera automaticamente le parole comuni a tutti
("Carpi", "biancorosso", i luoghi) e tiene solo i termini distintivi, dando una
discriminazione tematica nettamente migliore. E' inoltre gratis, locale e senza
dipendenze pesanti.

Uso:
  - build_index() calcola l'IDF sul corpus approvato, lo salva su file e
    popola Articolo.tfidf_terms (vettore normalizzato dei termini piu' pesanti).
  - article_vector(art) / vector_from_text(text) costruiscono il vettore di un
    articolo/testo usando l'IDF salvato.
  - cosine(a, b) misura la similarita' tematica tra due vettori.

Tutte le funzioni degradano con grazia: se l'indice IDF non esiste ancora,
vector_from_text restituisce {} e il gate di rilevanza viene semplicemente
disattivato (comportamento come prima).
"""
import os
import re
import json
import math
import threading
from collections import Counter

from django.conf import settings

# Stopword italiane comuni. Le parole ubique del corpus (Carpi, luoghi, ecc.)
# sono gia' neutralizzate dall'IDF, quindi qui basta l'elenco funzionale.
STOPWORDS = set(
    """a ad agli ai al alla alle allo anche ancora avere che chi ci coi col come con
    cui da dai dal dalla dalle dallo degli dei del della delle dello di dopo dove e ed
    era erano essere fa fanno fra gia gli ha hanno i il in io la le lei loro lo lui ma
    me meno mi mia mie miei mio molto ne negli nei nel nella nelle nello no noi non nostra
    nostre nostri nostro o od ogni oltre per piu po poco poi presso qua quale quali quando
    quanta quante quanti quanto quasi quella quelle quelli quello questa queste questi questo
    qui sara sarà se sei senza si sia sono sopra sotto sta stanno stata state stati stato su
    sua sue sui sugli sul sulla sulle sullo suo suoi te ti tra tu tua tue tuo tuoi tutta
    tutte tutti tutto un una uno vi via viene vengono voi vostra vostre vostri vostro
    oggi ieri domani mentre poiche perche cosi ecco proprio senza verso circa""".split()
)

TOP_K = 40          # termini memorizzati per articolo
_TOKEN_RE = re.compile(r'[a-zàèéìòù]{3,}')


def _idf_path():
    base = getattr(settings, 'TFIDF_DATA_DIR', None) or os.path.join(settings.BASE_DIR, 'tfidf_data')
    return os.path.join(base, 'idf.json')


def tokenize(text):
    return [w for w in _TOKEN_RE.findall((text or '').lower()) if w not in STOPWORDS]


# --- cache dell'IDF con invalidazione su mtime del file ---
_cache = {'mtime': None, 'idf': None, 'N': 0}
_lock = threading.Lock()


def load_idf():
    """Ritorna (idf_dict, N) oppure (None, 0) se l'indice non esiste."""
    path = _idf_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None, 0
    with _lock:
        if _cache['mtime'] == mtime and _cache['idf'] is not None:
            return _cache['idf'], _cache['N']
        try:
            with open(path, encoding='utf-8') as f:
                blob = json.load(f)
        except (OSError, ValueError):
            return None, 0
        _cache['idf'] = blob.get('idf') or {}
        _cache['N'] = blob.get('N', 0)
        _cache['mtime'] = mtime
        return _cache['idf'], _cache['N']


def vector_from_text(text, idf=None, top_k=TOP_K):
    """Vettore TF-IDF normalizzato (dict termine->peso) dei top_k termini."""
    if idf is None:
        idf, _ = load_idf()
    if not idf:
        return {}
    toks = tokenize(text)
    if not toks:
        return {}
    tf = Counter(toks)
    length = len(toks)
    raw = {}
    for term, count in tf.items():
        w_idf = idf.get(term)
        if not w_idf:  # termine sconosciuto o ubiquo (idf 0): ignora
            continue
        raw[term] = (count / length) * w_idf
    if not raw:
        return {}
    top = dict(sorted(raw.items(), key=lambda kv: kv[1], reverse=True)[:top_k])
    norm = math.sqrt(sum(v * v for v in top.values())) or 1e-9
    return {t: v / norm for t, v in top.items()}


def article_text(art):
    from home.content_polisher import content_polisher  # import locale per evitare cicli
    somm = content_polisher.clean_content_plain(art.sommario or '') if art.sommario else ''
    cont = re.sub(r'<[^>]+>', ' ', art.contenuto or '')
    return f"{art.titolo or ''}. {somm} {cont}"


def article_vector(art, idf=None):
    """Vettore di un articolo: usa tfidf_terms salvato se presente, altrimenti calcola."""
    stored = getattr(art, 'tfidf_terms', None)
    if stored:
        return stored
    return vector_from_text(article_text(art), idf=idf)


def cosine(a, b):
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(term, 0.0) for term, v in a.items())


def build_index(queryset=None, save_articles=True, batch_log=None):
    """Calcola l'IDF sul corpus approvato, lo salva su file e popola tfidf_terms.

    Ritorna (N, vocab_size, articoli_aggiornati).
    """
    from home.models import Articolo

    if queryset is None:
        queryset = Articolo.objects.filter(approvato=True)
    arts = list(queryset.only('id', 'titolo', 'sommario', 'contenuto'))
    N = len(arts)
    if N == 0:
        return 0, 0, 0

    df = Counter()
    toks_by_id = {}
    for a in arts:
        toks = tokenize(article_text(a))
        toks_by_id[a.id] = toks
        for w in set(toks):
            df[w] += 1

    # idf = log(N/df); i termini presenti in TUTTI i documenti -> 0 e vengono scartati
    idf = {}
    for term, c in df.items():
        val = math.log(N / c)
        if val > 0:
            idf[term] = val

    # salva l'indice IDF su file
    path = _idf_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'N': N, 'idf': idf}, f)
    # invalida cache
    with _lock:
        _cache['mtime'] = None

    updated = 0
    if save_articles:
        for i, a in enumerate(arts):
            tf = Counter(toks_by_id[a.id])
            length = len(toks_by_id[a.id]) or 1
            raw = {}
            for term, count in tf.items():
                w_idf = idf.get(term)
                if not w_idf:
                    continue
                raw[term] = (count / length) * w_idf
            top = dict(sorted(raw.items(), key=lambda kv: kv[1], reverse=True)[:TOP_K])
            norm = math.sqrt(sum(v * v for v in top.values())) or 1e-9
            vec = {t: v / norm for t, v in top.items()}
            a.tfidf_terms = vec
            a.save(update_fields=['tfidf_terms'])
            updated += 1
            if batch_log and updated % 100 == 0:
                batch_log(updated, N)

    return N, len(idf), updated


def update_article_vector(art):
    """Ricalcola e salva il vettore di un singolo articolo (usato alla creazione)."""
    idf, _ = load_idf()
    if not idf:
        return False
    vec = vector_from_text(article_text(art), idf=idf)
    if vec:
        art.tfidf_terms = vec
        art.save(update_fields=['tfidf_terms'])
        return True
    return False
