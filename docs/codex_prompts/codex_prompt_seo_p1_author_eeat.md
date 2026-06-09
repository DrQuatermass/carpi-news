# Codex prompt P1 — Fix attribuzione autore (tutto Redazione, schema ibrido per il futuro)

## Contesto

Codex ha gia' aggiunto il campo `autore` al modello Articolo (migration
0055) ma con default sbagliato `"Sven Rinaldi"`. Questo significa che
TUTTI i 4.900 articoli esistenti sono firmati "Sven Rinaldi" — pattern
penalizzato da Google come "AI farm a singolo autore".

**Nota chiave dall'utente**: la categoria `Editoriale` e' un vecchio test
inattivo, **non vengono piu' pubblicati editoriali**. Quindi non serve
una logica condizionale per attribuire "Sven Rinaldi" agli editoriali —
tutti gli articoli devono diventare "Redazione Ombra del Portico".

Lo schema NewsArticle deve comunque rimanere **condizionale** Person vs
Organization, per supportare in futuro:
- contributi firmati da giornalisti reali (es. assunzioni future)
- pubbliredazionali con firma dell'azienda cliente
- editoriali se la categoria sara' riattivata

Per ora pero' tutti gli articoli mostreranno schema Organization perche'
`autore = "Redazione Ombra del Portico"`.

## Azioni

### 1. Cambia default del campo `autore` e backfill totale

In `home/models.py`, classe `Articolo`, sul campo `autore`:

```python
autore = models.CharField(
    max_length=120,
    default="Redazione Ombra del Portico",
    db_index=True,
    help_text="Autore dell'articolo. Default 'Redazione Ombra del Portico'. "
              "Usa nome persona reale per editoriali firmati o pubbliredazionali "
              "con firma dell'autore."
)
```

Crea migration `0056_alter_articolo_autore_default.py`:

```python
from django.db import migrations, models


def assign_redazione_to_all(apps, schema_editor):
    """
    Ribattezza TUTTI gli articoli a 'Redazione Ombra del Portico'.
    La categoria 'Editoriale' e' un vecchio test inattivo, non serve
    distinguere.
    """
    Articolo = apps.get_model('home', 'Articolo')
    Articolo.objects.all().update(autore='Redazione Ombra del Portico')


def reverse(apps, schema_editor):
    Articolo = apps.get_model('home', 'Articolo')
    Articolo.objects.filter(
        autore='Redazione Ombra del Portico'
    ).update(autore='Sven Rinaldi')


class Migration(migrations.Migration):
    dependencies = [
        ('home', '0055_articolo_autore'),
        # Aggiungi anche dipendenza da migration di ArticoloRedirect se P0 e' gia' applicato
    ]

    operations = [
        migrations.AlterField(
            model_name='articolo',
            name='autore',
            field=models.CharField(
                default='Redazione Ombra del Portico',
                db_index=True,
                help_text="...",
                max_length=120,
            ),
        ),
        migrations.RunPython(assign_redazione_to_all, reverse),
    ]
```

### 2. Schema NewsArticle condizionale (mantiene supporto futuro Person)

In `home/templates/dettaglio_articolo.html`, sostituisci il blocco `author`
dello schema NewsArticle con:

```html
{% if articolo.autore == "Redazione Ombra del Portico" or articolo.autore == "" or not articolo.autore %}
"author": {
  "@type": "Organization",
  "name": "Redazione Ombra del Portico",
  "url": "https://ombradelportico.it/about/",
  "logo": {
    "@type": "ImageObject",
    "url": "https://ombradelportico.it{% static 'home/images/portico_logo_news_60h.png' %}",
    "width": 110,
    "height": 60
  }
}
{% else %}
"author": {
  "@type": "Person",
  "name": "{{ articolo.autore|escapejs }}",
  "url": "https://ombradelportico.it/about/",
  "worksFor": {
    "@type": "Organization",
    "name": "Ombra del Portico",
    "url": "https://ombradelportico.it/"
  }
}
{% endif %}
```

(Niente `sameAs` per ora — quando ci sara' un autore reale assegnato si
aggiungono i suoi link social. Per la "Redazione" come Organization si
mantiene il logo.)

### 3. Byline visibile sotto al titolo

Sotto al titolo articolo (cerca dove appare `{{ articolo.titolo }}` nel
template visibile, non nello schema), aggiungi:

```html
<p class="article-byline">
  di <strong>{{ articolo.autore }}</strong>
  · <time datetime="{{ articolo.data_pubblicazione|date:'c' }}">
    {{ articolo.data_pubblicazione|date:"j F Y" }}
  </time>
  {% if articolo.data_modifica > articolo.data_pubblicazione %}
    · <span class="updated">aggiornato {{ articolo.data_modifica|date:"j F Y" }}</span>
  {% endif %}
</p>
```

Aggiungi al CSS del template (o style.css se preferibile):

```css
.article-byline {
  color: #666;
  font-size: 0.9rem;
  margin: 0 0 1.5rem 0;
  font-style: italic;
  border-left: 3px solid #b32b1a;
  padding-left: 12px;
}
.article-byline strong {
  color: #222;
  font-weight: 600;
  font-style: normal;
}
.article-byline .updated {
  color: #888;
}
```

### 4. Pagina /about/ — aggiungi schema NewsMediaOrganization completo

`home/templates/about.html` ha gia' 4 menzioni di "Sven Rinaldi" come
Fondatore — quelle vanno bene, sono nel contesto della pagina "chi
siamo".

All'inizio del file `about.html`, dentro `{% block extra_css %}` o
`{% block extra_head %}` se disponibile, aggiungi un singolo blocco
JSON-LD con un `@graph` che dichiara sia l'Organization sia la Person
Sven (cosi' che il link `/about/` usato dallo schema NewsArticle sia
sempre coerente):

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "NewsMediaOrganization",
      "@id": "https://ombradelportico.it/about/#organization",
      "name": "Ombra del Portico",
      "alternateName": "Redazione Ombra del Portico",
      "url": "https://ombradelportico.it/",
      "logo": "https://ombradelportico.it{% static 'home/images/portico_logo_news_60h.png' %}",
      "sameAs": [
        "https://www.facebook.com/ombradelportico/",
        "https://www.instagram.com/ombradelportico/"
      ],
      "founder": {"@id": "https://ombradelportico.it/about/#sven"},
      "areaServed": {
        "@type": "City",
        "name": "Carpi",
        "containedInPlace": {
          "@type": "AdministrativeArea",
          "name": "Emilia-Romagna"
        }
      },
      "diversityPolicy": "https://ombradelportico.it/about/",
      "ethicsPolicy": "https://ombradelportico.it/about/",
      "ownershipFundingInfo": "https://ombradelportico.it/about/",
      "actionableFeedbackPolicy": "https://ombradelportico.it/about/",
      "correctionsPolicy": "https://ombradelportico.it/about/"
    },
    {
      "@type": "Person",
      "@id": "https://ombradelportico.it/about/#sven",
      "name": "Sven Rinaldi",
      "jobTitle": "Fondatore",
      "url": "https://ombradelportico.it/about/",
      "worksFor": {"@id": "https://ombradelportico.it/about/#organization"}
    }
  ]
}
</script>
```

(Se ci sono URL LinkedIn/Twitter di Sven che vuoi includere come
`sameAs` nella Person, l'utente li puo' fornire dopo.)

### 5. Sezioni testuali da aggiungere ad about.html

Nel `<body>` di about.html (o nel template equivalente), assicurati che
esistano queste sezioni (con questi titoli H2 — Google li cerca per
attribuire i campi `*Policy` dello schema):

#### Politica editoriale
> Selezioniamo le notizie monitorando fonti ufficiali (Comune di Carpi,
> ANSA, La Voce di Carpi, SulPanaro, TempoNews) e attivita' locali.
> Alcuni articoli sono redatti con assistenza di sistemi di
> intelligenza artificiale a partire dalle fonti citate, sotto
> supervisione editoriale della Redazione. Ogni articolo riporta sempre
> la fonte originale quando disponibile.

#### Correzioni
> Per segnalare errori o richiedere rettifiche scrivere a
> redazione@ombradelportico.it. Le correzioni sostanziali vengono
> riportate in fondo all'articolo con data e descrizione della modifica.

#### Trasparenza e finanziamento
> Ombra del Portico e' una pubblicazione indipendente. Le entrate
> derivano da pubblicita' display, pubbliredazionali (segnalati come
> tali) e contributi volontari dei lettori. Il sito non riceve
> finanziamenti pubblici ne' contributi politici.

Non serve creare URL separati — basta che le sezioni esistano dentro
/about/ con questi H2.

### 6. Pulizia campi admin

In `home/admin.py` mantieni `autore` in `list_display` ma valuta di
aggiungerlo a `list_filter`:

```python
list_filter = [
    'approvato', 'spotlight', 'categoria', 'autore',
    'escludi_newsletter', IsPubbliredazionaleFilter,
    'payment_status', HasWebSourcesFilter
]
```

## Cosa NON toccare

- Campo `titolo_seo` — gestione separata in P0
- Logica di polishing AI — gestione in P2 (validatore titoli)
- Schema NewsArticle base — solo il blocco `author` cambia
- Robots, sitemap, indexing notifier
- La menzione di "Sven Rinaldi" come Fondatore nel testo visibile di about.html

## Output atteso

- Diff completo
- Migration 0056 generata
- Conteggio articoli aggiornati a "Redazione Ombra del Portico"
- Render di prova del JSON-LD per un articolo (sara' Organization perche'
  tutti i record ora hanno "Redazione...")
- Verifica con https://search.google.com/test/rich-results su un articolo
  pubblicato (rich result deve riconoscere NewsArticle + Organization)
