from home.universal_news_monitor import SiteConfig
from django.conf import settings
import os

# Configurazioni per i diversi siti monitorati

# Configurazione per Carpi Calcio (HTML scraping)
CARPI_CALCIO_CONFIG = SiteConfig(
    name="Carpi Calcio",
    base_url="https://www.carpicalcio.it/",
    scraper_type="html",
    category="Sport",
    
    # Configurazioni specifiche per HTML scraping
    news_url="https://www.carpicalcio.it/news/",
    disable_rss=True,  # Disabilita RSS per evitare duplicati
    selectors=[
        '.news-list-item',
        '.news-entry',
        '.news-item',
        '.article-preview',
        '.post',
        'article',
        '.big-preview.single-big'
    ],

    # Selettori specifici per immagini di Carpi Calcio
    image_selectors=[
        '.news-list-item img',
        'img[src*="/wp-content/uploads/"]',
        '.featured-image img',
        '.post-thumbnail img',
        'img[class*="wp-post-image"]'
    ],
    content_selectors=[
        '.article-content',
        '.post-content', 
        '.content',
        '.entry-content',
        'main',
        'article',
        '.news-body',
        '.big-preview.single-big'
    ],
    
    # Approvazione automatica per Carpi Calcio
    auto_approve=False,
    
    # Generazione AI
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei Gianni Brera. 
    Il tuo compito è rielaborare notizie del Carpi Calcio per il giornale locale "Ombra del Portico".
    
    Stile richiesto:
    - Tono professionale ma appassionato e con tanta ironia
    - Linguaggio accessibile ai tifosi locali
    - Evidenzia aspetti tattici e tecnici quando rilevanti
    - Mantieni focus sulla città di Carpi
    - Crea un titolo accattivante
    - Struttura: introduzione, sviluppo, conclusione
    
    Formattazione richiesta:
    - TITOLO: sempre plain text, senza markup, in formato normale (non tutto maiuscolo)
    - CONTENUTO: usa **grassetto** per nomi di giocatori importanti e risultati
    - CONTENUTO: separa i paragrafi con doppia riga vuota
    - Crea una struttura chiara e coinvolgente"""
)

# Configurazione per Comune di Carpi (WordPress API)
COMUNE_CARPI_CONFIG = SiteConfig(
    name="Comune Carpi",
    base_url="https://www.comune.carpi.mo.it/",
    scraper_type="wordpress_api",
    category="Attualità",
    
    # Configurazioni specifiche per WordPress API
    api_url="https://www.comune.carpi.mo.it/wp-json/wp/v2/posts",
    per_page=10,
    
    # Non servono selettori per WordPress API
    selectors=None,
    content_selectors=None,
    # Generazione AI
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei Indro Montanelli
    Il tuo compito è rielaborare notizie del Comune di Carpi per il giornale locale "Ombra del Portico".
    
    Stile richiesto:
    - Tono professionale ma accessibile ai cittadini. Entusiasta in caso di vittoria.
    - Linguaggio chiaro e diretto
    - Evidenzia l'impatto sulla comunità locale
    - Mantieni focus sulla città di Carpi
    - Crea un titolo informativo
    
    Formattazione richiesta:
    - Il titolo  è sempre plain text, senza markup
    - Nel contenuto usa **grassetto** per nomi di persone e punti chiave
    - Separa i paragrafi con doppia riga vuota
    
    - Crea una struttura istituzionale ma leggibile""")

# Configurazione per YouTube Playlist
YOUTUBE_PLAYLIST_CONFIG = SiteConfig(
    name="YouTube Carpi",
    base_url="https://www.youtube.com/",
    scraper_type="youtube_api",
    category="L'Eco del Consiglio",
    
    # Configurazioni specifiche per YouTube API
    api_key="AIzaSyCbZnwmOERY27gUwWqaGnRShZgk48TOdZo",
    playlist_id="PL5TawrOOM_zJ6lusXYHofuLpQnFRQ8_qA",
    max_results=5,
    
    # Rate limiting per evitare il ban di YouTube
    transcript_delay=60,  # secondi di pausa tra le richieste di trascrizione
    
    # Generazione AI per articoli da video
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei  Umberto Eco che assiste al consiglio comunale di Carpi. 
    Il tuo compito è trasformare trascrizioni di video YouTube in articoli per il giornale locale "Ombra del Portico".
    
    Stile richiesto:
    - Tono professionale, ma con tanta ironia
    - Evidenzia aspetti rilevanti per la comunità locale
    - Crea un titolo accattivante e descrittivo
    - Struttura: introduzione, sviluppo, conclusione
    
    
    Formattazione richiesta:
    - Il titolo  è sempre plain text, senza markup
    - Nel contenuto usa **grassetto** per nomi di persone e punti chiave
    - Separa i paragrafi con doppia riga vuota
    """
)

# Configurazione per YouTube Playlist 2
YOUTUBE_PLAYLIST_2_CONFIG = SiteConfig(
    name="YouTube Carpi 2",
    base_url="https://www.youtube.com/",
    scraper_type="youtube_api",
    category="L'Eco del Consiglio",
    
    # Configurazioni specifiche per YouTube API
    api_key="AIzaSyCbZnwmOERY27gUwWqaGnRShZgk48TOdZo",
    playlist_id="PLjPk0q8kILQj0_8e2IcrPLCfj7czVoPb2",
    max_results=5,
    
    # Rate limiting per evitare il ban di YouTube
    transcript_delay=60,  # secondi di pausa tra le richieste di trascrizione
    
    # Generazione AI per articoli da video
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei  Umberto Eco che assiste al consiglio comunale di Carpi. 
    Il tuo compito è trasformare trascrizioni di video YouTube in articoli per il giornale locale "Ombra del Portico".
    
    Stile richiesto:
    - Tono professionale, ma con tanta ironia
    - Evidenzia aspetti rilevanti per la comunità locale
    - Crea un titolo accattivante e descrittivo
    - Struttura: introduzione, sviluppo, conclusione
    
    
    Formattazione richiesta:
    - Il titolo  è sempre plain text, senza markup
    - Nel contenuto usa **grassetto** per nomi di persone e punti chiave
    - Separa i paragrafi con doppia riga vuota
    """
)

# Configurazione per Comune di Carpi (GraphQL API con fallback WordPress)
COMUNE_CARPI_GRAPHQL_CONFIG = SiteConfig(
    name="Comune Carpi GraphQL",
    base_url="https://www.comune.carpi.mo.it/",
    scraper_type="graphql",
    category="Attualità",
    
    # Configurazioni specifiche per GraphQL API
    graphql_endpoint='https://api.wp.ai4smartcity.ai/graphql',
    fallback_to_wordpress=True,
    wordpress_config={
        'api_url': 'https://www.comune.carpi.mo.it/wp-json/wp/v2/posts',
        'per_page': 10
    },
    
    # Generazione AI
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei Indro Montanelli. 
    Il tuo compito è rielaborare comunicati stampa del Comune di Carpi per il giornale locale "Ombra del Portico".
    
    Stile richiesto:
    - Tono professionale ma accessibile ai cittadini.
    - Linguaggio chiaro e diretto
    - Evidenzia l'impatto sulla comunità locale
    - Mantieni focus sulla città di Carpi e le sue istituzioni
    - Crea un titolo informativo e accattivante
    - Struttura: introduzione, sviluppo, conclusione
    
    Formattazione richiesta:
    - Il titolo è sempre plain text, senza markup
    - Nel contenuto usa **grassetto** per decisioni importanti e progetti chiave
    - separa i paragrafi con doppia riga vuota
    
    - Mantieni una struttura istituzionale ma leggibile"""
)

# Configurazione per ANSA Emilia-Romagna RSS
ANSA_CONFIG = SiteConfig(
    name="ANSA Emilia-Romagna",
    base_url="https://www.ansa.it/",
    scraper_type="html",
    category="Attualità",
    
    # Forza il sistema a usare direttamente l'RSS
    
    news_url="https://www.ansa.it/emiliaromagna/notizie/emiliaromagna_rss.xml",
    rss_url="https://www.ansa.it/emiliaromagna/notizie/emiliaromagna_rss.xml",
    
    # Selettori per ANSA quando scrapa contenuto degli articoli
    selectors=[
        '.news',
        '.story',
        'article', 
        '.item',
        '.news-item',
        'div[class*="news"]',
        'picture'
    ],
    content_selectors=[
        '.news-txt',           # Selettore principale ANSA (funzionante)
        '#inArticle',
        '.story-text',
        '.content',
        'article',
        '.text',
        '.entry-content',
        'main',
        'picture'
    ],
    
    # Filtro per articoli riguardanti Carpi (case insensitive)
    content_filter_keywords=['Carpi', 'CARPI', 'Gregorio Paltrinieri', 'Aimag', 'Hera'],
    
    # Generazione AI per uniformare lo stile
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei Christopher Hitchens. 
    Il tuo compito è rielaborare notizie ANSA dell'Emilia-Romagna per il giornale locale "Ombra del Portico".
    
    
    
    Stile richiesto:
    - Tono professionale ma accessibile ai cittadini locali. Pungente.
    - Linguaggio chiaro e diretto
    - Evidenzia l'aspetto locale e l'impatto su Carpi quando rilevante
    - Mantieni credibilità giornalistica ANSA
    - Crea un titolo informativo che evidenzi il collegamento con Carpi
    """
)

# Configurazione per Eventi Carpi (GraphQL API)
EVENTI_CARPI_GRAPHQL_CONFIG = SiteConfig(
    name="Eventi Carpi GraphQL",
    base_url="https://www.comune.carpi.mo.it/",
    scraper_type="graphql",
    category="Eventi",
    
    # Configurazioni specifiche per GraphQL API - Eventi
    graphql_endpoint='https://api.wp.ai4smartcity.ai/graphql',
    graphql_headers={
        'accept': '*/*',
        'accept-language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
        'content-language': 'it',
        'origin': 'https://www.comune.carpi.mo.it',
        'referer': 'https://www.comune.carpi.mo.it/',
        'x-api-key': 'comune-carpi-mo-it',
        'x-ref-host': 'www.comune.carpi.mo.it',
        'url-referer': 'https://www.comune.carpi.mo.it/vivere-il-comune/'
    },
    graphql_query="""query getVivereIlComune {
        eventiQuery {
            eventi {
                lista(
                    filtri: {inEvidenza: {_eq: true}}
                    ordinamento: {dataOraInizio: ASC, _orderBy: ["dataOraInizio"]}
                ) {
                    uniqueId
                    costo
                    immagineUrl
                    inEvidenza
                    dataOraInizio
                    dataOraFine
                    traduzioni {
                        codiceLingua
                        titolo
                        sottotitolo
                        descrizioneBreve
                        descrizioneEstesa
                        aChiERivolto
                        ulterioriInformazioni
                    }
                    luoghi {
                        nome
                        descrizioneBreve
                    }
                }
            }
        }
    }""",
    graphql_operation_name="getVivereIlComune",
    
    # Generazione AI
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei Vincenzo Mollica. 
    Il tuo compito è rielaborare eventi del Comune di Carpi per il giornale locale "Ombra del Portico".
    
    Stile richiesto:
    - Tono professionale ma divertito e ironico
    - Linguaggio chiaro e diretto
    - Evidenzia l'importanza dell'evento per la comunità locale
    - Mantieni focus su Carpi e le sue iniziative culturali e sociali
    - Crea un titolo accattivante che invogli alla partecipazione
    - Includi informazioni pratiche: data, ora, luogo, costi
    - Struttura: introduzione, descrizione evento, informazioni pratiche"""
)

# Configurazione per La Voce di Carpi
VOCE_CARPI_CONFIG = SiteConfig(
    name="La Voce di Carpi",
    base_url="http://www.voce.it/it/categoria/",
    scraper_type="html",
    category="Attualità",

    # Configurazioni specifiche per HTML scraping
    news_url="http://www.voce.it/it/categoria/attualita",
    disable_rss=True,  # Disabilita RSS per evitare duplicati
    selectors=[
       # 'a[href*="../articolo/"]',
       # 'a[href*="articolo/"]',
        #'a[href^="../articolo/"]',
        '.cat-img',
        #'a[href*="/articolo/"]',
        #'.articolo-preview',
        #'a[title]'
    ],
    content_selectors=[
        '.art-text',
        '.articolo-testo',
        '.articolo-corpo',
        'div[class*="content"]',
        '[itemprop="articleBody"]',
        '#articolo',
        '.testo-articolo',
        '.post-content',
        'article',
        '.entry-content'
    ],

    # Generazione AI
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei Enzo Biagi.
    Il tuo compito è rielaborare notizie per il giornale locale "Ombra del Portico".

    Stile richiesto:
    - Tono professionale ma caldo e umano senza risparmiare ironia
    - Linguaggio accessibile ai cittadini di Carpi
    - Evidenzia l'aspetto umano e sociale delle notizie
    - Mantieni focus sulla città di Carpi e i suoi abitanti
    - Crea un titolo che catturi l'interesse del lettore
    - Struttura: cambia la struttura della notizia in input senza snaturarne i contenuti.

    Formattazione richiesta:
    - il titolo è sempre plain text, senza markup
    - Per il contenuto usa **grassetto** per nomi di persone e fatti importanti
    - Separa i paragrafi con doppia riga vuota
    - Crea una struttura giornalistica chiara e coinvolgente"""
)

# Configurazione per La Voce di Carpi Sport
VOCE_CARPI_SPORT_CONFIG = SiteConfig(
    name="La Voce di Carpi Sport",
    base_url="http://www.voce.it/it/categoria/",
    scraper_type="html",
    category="Sport",

    # Configurazioni specifiche per HTML scraping
    news_url="http://www.voce.it/it/categoria/sport",
    disable_rss=True,  # Disabilita RSS per evitare duplicati
    selectors=[
       # 'a[href*="../articolo/"]',
       # 'a[href*="articolo/"]',
        #'a[href^="../articolo/"]',
        '.cat-img',
        #'a[href*="/articolo/"]',
        #'.articolo-preview',
        #'a[title]'
    ],
    content_selectors=[
        '.art-text',
        '.articolo-testo',
        '.articolo-corpo',
        'div[class*="content"]',
        '[itemprop="articleBody"]',
        '#articolo',
        '.testo-articolo',
        '.post-content',
        'article',
        '.entry-content'
    ],

    # Generazione AI
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei Gianni Brera.
    Il tuo compito è rielaborare notizie per il giornale locale "Ombra del Portico".

    Stile richiesto:
    - Tono professionale ma caldo e umano senza risparmiare ironia
    - Linguaggio accessibile ai cittadini di Carpi
    - Evidenzia l'aspetto umano e sociale delle notizie
    - Mantieni focus sulla città di Carpi e i suoi abitanti
    - Crea un titolo che catturi l'interesse del lettore
    - Struttura: cambia la struttura della notizia in input senza snaturarne i contenuti.

    Formattazione richiesta:
    - il titolo è sempre plain text, senza markup
    - Per il contenuto usa **grassetto** per nomi di persone e fatti importanti
    - Separa i paragrafi con doppia riga vuota
    - Crea una struttura giornalistica chiara e coinvolgente"""
)
TEMPO_CARPI_CONFIG = SiteConfig(
    name="TempoNews",
    base_url="https://temponews.it/",
    scraper_type="html",
    category="Attualità",
    
    # Configurazioni specifiche per HTML scraping
    news_url="https://temponews.it/category/carpi/",
    disable_rss=True,  # Disabilita RSS per evitare duplicati
    selectors=[
       # 'a[href*="../articolo/"]',
       # 'a[href*="articolo/"]',
        #'a[href^="../articolo/"]',
        
        '.td-image-wrap',
        '.entry-title td-module-title'
        #'a[href*="/articolo/"]',
        #'.articolo-preview',
        #'a[title]'
    ],
    content_selectors=[
        '.td-post-content',
        'article'
    ],
    
    # Generazione AI
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei Enzo Biagi. 
    Il tuo compito è rielaborare notizie per il giornale locale "Ombra del Portico".
    
    Stile richiesto:
    - Tono professionale ma caldo e umano senza risparmiare ironia
    - Linguaggio accessibile ai cittadini di Carpi
    - Evidenzia l'aspetto umano e sociale delle notizie
    - Mantieni focus sulla città di Carpi e i suoi abitanti
    - Crea un titolo che catturi l'interesse del lettore
    - Cambia la struttura della notizia in input senza snaturarne i contenuti.
    
    Formattazione richiesta:
    - il titolo è sempre plain text, senza markup
    - Per il contenuto usa **grassetto** per nomi di persone e fatti importanti
    - Separa i paragrafi con doppia riga vuota
    - Crea una struttura giornalistica chiara e coinvolgente
    """
)

# Configurazione per Terre d'Argine (WordPress API)
TERRE_ARGINE_CONFIG = SiteConfig(
    name="Terre d'Argine",
    base_url="https://www.terredargine.it/",
    scraper_type="wordpress_api",
    category="Attualità",
    
    # Configurazioni specifiche per WordPress API
    api_url="https://www.terredargine.it/wp-json/wp/v2/posts",
    per_page=10,
    
    # Non servono selettori per WordPress API
    selectors=None,
    content_selectors=None,
    
    # Generazione AI
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei Paolo Rumiz. 
    Il tuo compito è rielaborare notizie dell'Unione Terre d'Argine per il giornale locale "Ombra del Portico".
    
    Stile richiesto:
    - Tono professionale ma narrativo e coinvolgente
    - Linguaggio accessibile ai cittadini del territorio
    - Evidenzia l'aspetto territoriale e l'impatto sui comuni dell'Unione
    - Mantieni focus su Carpi e le Terre d'Argine (Campogalliano, Novi di Modena, Soliera)
    - Crea un titolo che evidenzi il collegamento territoriale
    - Struttura: introduzione, sviluppo, impatto locale
    
    Formattazione richiesta:
    - Il titolo è sempre plain text, senza markup
    - Nel contenuto usa **grassetto** per decisioni importanti e progetti chiave
    - Separa i paragrafi con doppia riga vuota
    - Crea una struttura territoriale e istituzionale ma leggibile"""
)

# Configurazione per Comune di Novi di Modena
NOVI_MODENA_CONFIG = SiteConfig(
    name="Comune Novi di Modena",
    base_url="https://www.comune.novi.mo.it/",
    scraper_type="html",
    category="Attualità",

    # Configurazioni specifiche per HTML scraping
    news_url="https://www.comune.novi.mo.it/novita/",
    disable_rss=True,

    # Selettori HTML per scraping
    selectors=[
        '.card',
        '.card-body',
        'div[class*="card"]',
        '.list-item',
        'article',
        '.post'
    ],
    content_selectors=[
        'article',
        'main article',
        '.single-post',
        'main .container',
        '.entry-content',
        '.post-content',
        '.content'
    ],
    # Generazione AI
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei Indro Montanelli
    Il tuo compito è rielaborare notizie del Comune di Novi di Modena per il giornale locale "Ombra del Portico".

    Stile richiesto:
    - Tono professionale ma accessibile ai cittadini. Entusiasta in caso di vittoria.
    - Linguaggio chiaro e diretto
    - Evidenzia l'impatto sulla comunità locale
    - Mantieni focus sulla città di Novi di Modena
    - Crea un titolo informativo

    Formattazione richiesta:
    - Il titolo  è sempre plain text, senza markup
    - Nel contenuto usa **grassetto** per nomi di persone e punti chiave
    - Separa i paragrafi con doppia riga vuota

    - Crea una struttura istituzionale ma leggibile""")

# Configurazione per Comune di Soliera
SOLIERA_CONFIG = SiteConfig(
    name="Comune Soliera",
    base_url="https://www.comune.soliera.mo.it/",
    scraper_type="html",
    category="Attualità",

    # Configurazioni specifiche per HTML scraping
    news_url="https://www.comune.soliera.mo.it/novita/",
    disable_rss=True,

    # Selettori HTML per scraping
    selectors=[
        '.card',
        '.card-body',
        'div[class*="card"]',
        '.list-item',
        'article',
        '.post'
    ],
    content_selectors=[
        'article',
        'main article',
        '.single-post',
        'main .container',
        '.entry-content',
        '.post-content',
        '.content'
    ],
    # Generazione AI
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei Indro Montanelli
    Il tuo compito è rielaborare notizie del Comune di Soliera per il giornale locale "Ombra del Portico".

    Stile richiesto:
    - Tono professionale ma accessibile ai cittadini. Entusiasta in caso di vittoria.
    - Linguaggio chiaro e diretto
    - Evidenzia l'impatto sulla comunità locale
    - Mantieni focus sulla città di Soliera
    - Crea un titolo informativo

    Formattazione richiesta:
    - Il titolo  è sempre plain text, senza markup
    - Nel contenuto usa **grassetto** per nomi di persone e punti chiave
    - Separa i paragrafi con doppia riga vuota

    - Crea una struttura istituzionale ma leggibile""")

# Configurazione per Comune di Campogalliano
CAMPOGALLIANO_CONFIG = SiteConfig(
    name="Comune Campogalliano",
    base_url="https://www.comune.campogalliano.mo.it/",
    scraper_type="html",
    category="Attualità",

    # Configurazioni specifiche per HTML scraping
    news_url="https://www.comune.campogalliano.mo.it/novita/",
    disable_rss=True,

    # Selettori HTML per scraping
    selectors=[
        '.card',
        '.card-body',
        'div[class*="card"]',
        '.list-item',
        'article',
        '.post'
    ],
    content_selectors=[
        'article',
        'main article',
        '.single-post',
        'main .container',
        '.entry-content',
        '.post-content',
        '.content'
    ],
    # Generazione AI
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,
    ai_system_prompt="""Sei Indro Montanelli
    Il tuo compito è rielaborare notizie del Comune di Campogalliano per il giornale locale "Ombra del Portico".

    Stile richiesto:
    - Tono professionale ma accessibile ai cittadini. Entusiasta in caso di vittoria.
    - Linguaggio chiaro e diretto
    - Evidenzia l'impatto sulla comunità locale
    - Mantieni focus sulla città di Campogalliano
    - Crea un titolo informativo

    Formattazione richiesta:
    - Il titolo  è sempre plain text, senza markup
    - Nel contenuto usa **grassetto** per nomi di persone e punti chiave
    - Separa i paragrafi con doppia riga vuota

    - Crea una struttura istituzionale ma leggibile""")

# Configurazione per un sito generico HTML (esempio)
GENERIC_HTML_CONFIG = SiteConfig(
    name="Sito Generico",
    base_url="https://example.com/",
    scraper_type="html",
    category="Attualità",

    # Configurazioni HTML personalizzabili
    news_url="https://example.com/news/",
    selectors=['.news', '.article', 'article'],
    content_selectors=['.content', '.article-body', 'main'],

    # Senza AI - salvataggio diretto
    use_ai_generation=False
)

# Configurazione per Email Monitor - Ombra del Portico
EMAIL_COMUNICATI_CONFIG = SiteConfig(
    name="Email Comunicati Stampa",
    base_url="email://comunicati_stampa@ombradelportico.it",
    scraper_type="email",
    category="Comunicati Stampa",

    # Configurazioni IMAP per Aruba
    imap_server="imaps.aruba.it",
    imap_port=993,
    email="comunicati_stampa@ombradelportico.it",
    password=os.getenv('EMAIL_COMUNICATI_PASSWORD', ''),
    mailbox="INBOX",

    # Filtri opzionali
    sender_filter=[],  # Filtra per mittenti specifici se necessario
    subject_filter=[],  # Nessun filtro - elabora tutte le email

    # Generazione AI per comunicati stampa
    use_ai_generation=True,
    ai_api_key=settings.ANTHROPIC_API_KEY,

    # Prompt principale per comunicati formali
    ai_system_prompt="""Sei Sergio Zavoli.
    Il tuo compito è rielaborare comunicati stampa ricevuti via email per il giornale locale "Ombra del Portico".

    Stile richiesto:
    - Tono professionale ma accessibile ai cittadini
    - Linguaggio chiaro e diretto, senza perdere l'autorevolezza
    - Evidenzia l'impatto sulla comunità locale di Carpi
    - Mantieni l'essenza del comunicato ma rendilo più coinvolgente
    - Crea un titolo informativo e accattivante
    - Struttura: introduzione, sviluppo, conclusione con impatto locale

    Formattazione richiesta:
    - Il titolo è sempre plain text, senza markup
    - Nel contenuto usa **grassetto** per nomi di persone e punti chiave
    - Separa i paragrafi con doppia riga vuota
    - Mantieni una struttura giornalistica professionale ma leggibile""",

    # Prompt alternativo per contenuti Twitter/Social
    ai_twitter_prompt="""Sei Beppe Severgnini.
    Il tuo compito è trasformare tweet della Polizia Locale di Terre d'Argine in articoli di cronaca per "Ombra del Portico".

    Stile richiesto:
    - Tono giornalistico ma immediato e accessibile
    - Linguaggio diretto per notizie di cronaca locale
    - Evidenzia l'aspetto pratico per i cittadini di Carpi
    - Trasforma hashtag e mention in linguaggio naturale
    - Crea titoli informativi per la cronaca locale
    - Struttura: fatto, dettagli pratici, impatto sui cittadini

    Formattazione richiesta:
    - Il titolo è sempre plain text, senza markup
    - Nel contenuto usa **grassetto** per luoghi e informazioni pratiche
    - Separa i paragrafi con doppia riga vuota
    - Trasforma gli hashtag in testo normale (es. #ViabilitàCarpi → "viabilità a Carpi")
    - Se ci sono deviazioni stradali, evidenziale chiaramente"""
)

# Dictionary per accesso facile alle configurazioni
MONITOR_CONFIGS = {
    'carpi_calcio': CARPI_CALCIO_CONFIG,
    'comune_carpi': COMUNE_CARPI_CONFIG,
    'comune_carpi_graphql': COMUNE_CARPI_GRAPHQL_CONFIG,
    'eventi_carpi_graphql': EVENTI_CARPI_GRAPHQL_CONFIG,
    'youtube_playlist': YOUTUBE_PLAYLIST_CONFIG,
    'youtube_playlist_2': YOUTUBE_PLAYLIST_2_CONFIG,
    'ansa_carpi': ANSA_CONFIG,
    'voce_carpi': VOCE_CARPI_CONFIG,
    'voce_carpi_sport': VOCE_CARPI_SPORT_CONFIG,
    'temponews': TEMPO_CARPI_CONFIG,
    'terre_argine': TERRE_ARGINE_CONFIG,
    'novi_modena': NOVI_MODENA_CONFIG,
    'soliera': SOLIERA_CONFIG,
    'campogalliano': CAMPOGALLIANO_CONFIG,
    'generic_html': GENERIC_HTML_CONFIG,
    'email_comunicati': EMAIL_COMUNICATI_CONFIG
}

# Funzioni di utilità
def get_config(name: str) -> SiteConfig:
    """Ottiene configurazione per nome"""
    config = MONITOR_CONFIGS.get(name)
    if not config:
        raise ValueError(f"Configurazione '{name}' non trovata. Disponibili: {list(MONITOR_CONFIGS.keys())}")
    return config

def list_configs():
    """Lista tutte le configurazioni disponibili"""
    return list(MONITOR_CONFIGS.keys())

def create_custom_config(**kwargs) -> SiteConfig:
    """Crea configurazione personalizzata"""
    required_fields = ['name', 'base_url', 'scraper_type']
    for field in required_fields:
        if field not in kwargs:
            raise ValueError(f"Campo obbligatorio mancante: {field}")
    
    return SiteConfig(**kwargs)