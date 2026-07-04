# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Django 5.2.5 news aggregation website for the city of Carpi, Italy ("Ombra del Portico"). It's an automated news portal with AI-powered content generation, multi-source monitoring, and an approval workflow system.

## Architecture

- **Django Project Structure**: Standard Django project with main project folder `carpi_news/`
- **Single App Architecture**: `home` app contains all functionality (models, views, templates, static files)
- **Database**: SQLite (db.sqlite3) for local development
- **Universal Monitoring System**: Multi-source news scraping with configurable scrapers
- **AI Integration**: Content generation and polishing with Anthropic Claude API
- **Content Approval System**: Articles require approval before publication
- **Virtual Environment**: Python 3.12.3 with web scraping and AI/ML dependencies

## Data Model

The `Articolo` model in `home/models.py:4` contains:
- `titolo`: Article title (CharField, max 200)
- `contenuto`: Full article content (TextField)
- `sommario`: Article summary (TextField, max 5000, auto-generated if empty)
- `categoria`: Article category (CharField, default 'Generale')
- `slug`: URL slug (SlugField, auto-generated from title)
- `approvato`: Approval status (BooleanField, default False)
- `fonte`: Source URL (URLField, optional)
- `foto`: Image URL (URLField, optional)
- `richieste_modifica`: Text field for AI regeneration requests (TextField, optional)
- `views`: View count (PositiveIntegerField, default 0)
- `data_creazione`: Creation timestamp
- `data_pubblicazione`: Publication timestamp

## Universal Monitoring System (Database-Driven)

The project features a sophisticated multi-source news monitoring system **managed entirely through the database**:

### Core Components
- **`MonitorConfig` Model** (`home/models.py:109`): Database model for monitor configurations
- **`universal_news_monitor.py`**: Universal scraper class supporting HTML scraping, WordPress API, YouTube, GraphQL, and Email
- **`monitor_manager.py`**: Manages multiple concurrent monitors
- **Admin Interface** (`/admin/home/monitorconfig/`): Web UI for creating, editing, and controlling monitors
- **Management Commands**: CLI tools for importing and managing monitors

### System Architecture
All monitor configurations are stored in the database (`MonitorConfig` model) and loaded dynamically at startup. The old `monitor_configs.py` is only used for initial import and can be considered deprecated.

### Supported Sources
- **Carpi Calcio**: HTML scraping with AI content generation and enhanced image selectors
- **Comune Carpi GraphQL**: GraphQL API with automatic image download to media files
- **Comune Carpi WordPress**: WordPress REST API integration (fallback)
- **Eventi Carpi**: GraphQL API for events with AI content generation
- **La Voce di Carpi**: HTML scraping with URL space encoding support
- **ANSA Emilia-Romagna**: RSS feed with keyword filtering for Carpi-related content
- **TempoNews**: HTML scraping for local news
- **YouTube Channels**: Transcript-based article generation

### Legacy Monitors (Being Replaced)
- `carpi_calcio_monitor.py`: Original Carpi Calcio scraper
- `comune_notizie_monitor.py`: Original Comune scraper
- `youtube_transcript.py`: Original YouTube processor

## Content Processing Pipeline

1. **Monitoring**: Automated scraping of configured news sources with keyword filtering
2. **Content Extraction**: HTML parsing, GraphQL/REST API calls, or transcript processing
3. **Keyword Filtering**: Full-content filtering for ANSA articles (Carpi-related keywords only)
4. **Image Processing**:
   - Automatic image extraction with enhanced selectors
   - Download and local storage for Comune Carpi (GraphQL API images)
   - URL encoding fix for spaces (La Voce images)
   - Smart caching system with validation (30min-1hour TTL)
5. **AI Enhancement**: Content polishing and uniformity via `content_polisher.py`
6. **Approval Workflow**: Articles require manual approval before publication (auto-approval configurable per source)
7. **Logging**: Comprehensive logging via `logger_config.py`

## Pubbliredazionali (Sponsored Articles)

The system includes an AI-powered workflow for creating pubbliredazionali (sponsored articles) with conversational interview:

### Workflow
1. **Company Info Input**: User provides company name, website/social profile, interviewee details
2. **Website/Social Analysis**:
   - For websites: Deep scraping of content (headings, paragraphs, metadata)
   - For social profiles (Instagram, Facebook, LinkedIn): Automatic detection and metadata extraction
3. **Web Research**: AI-powered research on company, market, industry trends
4. **Dynamic Interview**: AI agent conducts 3-8 questions based on collected information
5. **Article Generation**: AI creates journalistic pubbliredazionale (500-700 words)
6. **Preview & Payment**: User reviews article, can request regeneration, then proceeds to payment

### Social Media Profile Support

The system recognizes and handles social media profiles differently from regular websites:

**Supported Platforms:**
- Instagram (`instagram.com`)
- Facebook (`facebook.com`, `fb.com`)
- LinkedIn (`linkedin.com`)
- Twitter/X (`twitter.com`, `x.com`)
- TikTok (`tiktok.com`)

**How it works:**
1. **Auto-detection**: System recognizes social profile URLs automatically
2. **Metadata Extraction**: Attempts to extract public information (username, name, bio)
3. **Fallback Strategy**: If scraping fails (common due to anti-bot protection), relies on:
   - Web research (Google search for public information)
   - Interview conversation (primary source of information)
4. **No errors**: Unlike regular websites, social profiles don't trigger "scraping failed" warnings

**Configuration** (Optional):
```env
# .env file - Social Media API tokens (optional, for enhanced extraction)
INSTAGRAM_ACCESS_TOKEN=your-token-here
FACEBOOK_API_ACCESS_TOKEN=your-token-here
LINKEDIN_ACCESS_TOKEN=your-token-here
```

Without API tokens, the system gracefully falls back to interview+web research only.

**Key Files:**
- `home/publiredazionale_agent.py`: Main AI agent for interview and article generation
- `home/social_media_scraper.py`: Social profile information extraction
- `admin_panel/views.py`: Web interface for pubbliredazionale creation

## Management Commands

The project includes Django management commands in `home/management/commands/`:

### Monitor Management (Database-Driven System)
- **`import_monitors.py`**: Import monitor configurations from `monitor_configs.py` to database
- **`start_monitors.py`**: Start active monitors from database
- **`manage_db_monitors.py`**: Manage monitor status (start/stop/status/restart)

### Legacy Commands
- `monitor_playlist.py`: Monitor specific YouTube playlists
- `manage_monitors.py`: Manage and control universal monitors (legacy)
- `update_editorial_images.py`: Update editorial content images

## Common Commands

**Development Server**:
```bash
cd carpi_news
python manage.py runserver
```

**Monitor Management (NEW - Database-Driven)**:
```bash
# First-time setup: Import monitors from monitor_configs.py
python manage.py import_monitors

# Clean lock files (if monitors fail to start with "lock non acquisibile")
python manage.py clean_locks --force

# View monitor status
python manage.py manage_db_monitors status

# Start all active monitors
python manage.py start_monitors

# Start specific monitor
python manage.py start_monitors --monitor "Monitor Name"

# Manage monitors
python manage.py manage_db_monitors start   # Start all active
python manage.py manage_db_monitors stop    # Stop all
python manage.py manage_db_monitors restart # Restart all
```

**Admin Interface**:
- Access at `/admin/home/monitorconfig/` to manage monitors via web UI
- Create, edit, activate/deactivate monitors
- Control individual monitors with Start/Stop/Test/Logs buttons

**Auto-Start Configuration**:
The system can automatically start monitors when Django loads (e.g., with `runserver` or Gunicorn).
This is controlled by the `AUTO_START_MONITORS` environment variable in `.env`:

```bash
# Development: disable auto-start to avoid lock conflicts on Django reload
AUTO_START_MONITORS=False

# Production: enable auto-start for automatic monitoring
AUTO_START_MONITORS=True
```

When `AUTO_START_MONITORS=False`, start monitors manually with:
```bash
python manage.py start_monitors
```

**Database Operations**:
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

**Testing**:
```bash
python manage.py test
```

**Log Cleanup**:
```bash
python cleanup_old_logs.py
```

**Migration to Universal System**:
```bash
python migrate_to_universal.py
```

## Media Files and Image Management

The project uses Django's media files system for storing downloaded images:

- **Media Directory**: `carpi_news/media/images/downloaded/`
- **Apache Configuration**: Serves `/media/` from filesystem
- **Download System**: Automatic download for Comune Carpi GraphQL API images
- **Image Validation**: Smart caching system validates external image URLs
- **URL Encoding**: Automatic fix for image URLs with spaces (La Voce di Carpi)

**Media files are served by Apache in production:**
```apache
Alias /media /var/www/carpi-news/carpi_news/media
<Directory /var/www/carpi-news/carpi_news/media>
    Require all granted
</Directory>
```

## Monitoring System Status

**Check active monitors:**
```bash
# View running processes
ps aux | grep -E "(monitor|scheduler)" | grep -v grep

# Check lock files
ls -la locks/

# View monitor logs
tail -20 logs/monitors.log

# Check specific monitor status
python manage.py manage_monitors status
```

**Restart monitors (Database-Driven System):**
```bash
# View status
python manage.py manage_db_monitors status

# Restart all
python manage.py manage_db_monitors restart

# Or via admin interface at /admin/home/monitorconfig/
```

**Legacy method (deprecated):**
```bash
# Stop all
pkill -f "universal_news_monitor"
rm -f locks/*.lock

# Start all
nohup python start_universal_monitors.py &
```

## Key Dependencies

- **Django**: 5.2.5 (web framework)
- **anthropic**: 0.64.0 (AI integration)
- **requests**: 2.31.0 (HTTP requests for web scraping)
- **beautifulsoup4**: 4.12.2 (HTML parsing)
- **youtube-transcript-api**: 0.6.1 (YouTube content processing)
- **python-dotenv**: 1.0.0 (environment variables)
- **gunicorn**: 21.2.0 (WSGI server for production)
- **whitenoise**: 6.6.0 (static file serving)
- **psycopg2-binary**: 2.9.9 (PostgreSQL adapter, optional)
- Dependencies managed via `requirements.txt` in carpi_news/ directory

## Views and URLs

- **Home View** (`/`): Displays first 6 approved articles, ordered by publication date
- **Article Detail** (`/articolo/<slug:slug>/`): Shows full article content for approved articles only
- **Admin Interface** (`/admin/`): Django admin for content management

## Logging and Monitoring

- **Centralized Logging**: `logger_config.py` configures logging across all modules
- **Log Directory**: `logs/` contains rotating log files
- **Lock Files**: Prevent concurrent execution of monitors
- **Email Notifications**: `email_notifications.py` for system alerts

## Templates and Frontend

- **Homepage** (`home/templates/homepage.html`): Responsive grid layout
- **Article Detail** (`home/templates/dettaglio_articolo.html`): Full article view
- **Advanced CSS** (`home/static/home/css/style.css`): Modern styling with animations
- All content in Italian language

## Environment Configuration

The project uses environment variables defined in `.env` file (based on `.env.example`):

**Required Variables**:
- `SECRET_KEY`: Django secret key (generate with `generate_secret_key.py`)
- `ANTHROPIC_API_KEY`: Required for AI content processing
- `DEBUG`: Set to False for production
- `ALLOWED_HOSTS`: Comma-separated list of allowed domains

**Optional Variables**:
- `DATABASE_URL`: PostgreSQL connection string (uses SQLite if not set)
- `EMAIL_*`: SMTP configuration for notifications
- `EMAIL_BACKEND`: Override email backend (e.g. `django.core.mail.backends.console.EmailBackend` in locale per non inviare email reali)
- `YOUTUBE_API_KEY` & `YOUTUBE_PLAYLIST_ID`: YouTube integration
- `MONITOR_INTERVAL_*`: Custom intervals for each monitor (seconds)
- `OPENROUTER_API_KEY`: Chiave OpenRouter (necessaria se si usa DeepSeek)
- `AI_ARTICLE_PROVIDER`: Provider di default per gli articoli — `anthropic` (default) | `openrouter`
- `CHATBOT_PROVIDER`: Provider del chatbot — `anthropic` (default) | `openrouter`
- `OPENROUTER_ARTICLE_MODEL`: Modello articoli (default `deepseek/deepseek-v4-pro`)
- `OPENROUTER_CHATBOT_MODEL`: Modello chatbot (default `deepseek/deepseek-v4-pro`)
- `OPENROUTER_BASE_URL`: Endpoint OpenRouter (default `https://openrouter.ai/api/v1`)

**Virtual Environment**: 
```bash
# Activate virtual environment
cd C:\news
venv\Scripts\activate  # Windows
source venv/bin/activate  # Unix/Linux

# Install dependencies
cd carpi_news
pip install -r requirements.txt
```

## AI Provider (Anthropic / OpenRouter-DeepSeek)

Sia la **generazione articoli** sia il **chatbot** possono usare due provider: **Anthropic** (Claude) o **OpenRouter** (DeepSeek). La selezione è per-componente ed è **guidata da variabili d'ambiente**, senza modifiche al codice.

### Come funziona
- **Articoli** (`home/universal_news_monitor.py` → `generate_ai_article`): il provider di default è `settings.AI_ARTICLE_PROVIDER`. Un singolo monitor può forzare il provider mettendo `"ai_provider": "openrouter"` (o `"anthropic"`) nel suo `config_data` JSON (override per-monitor). Con OpenRouter viene usato `_generate_with_openrouter` (loop Chat Completions con tool `web_search` + finalizzazione forzata, identica al path Anthropic).
- **Chatbot** (`home/chatbot_service.py`): usa `settings.CHATBOT_PROVIDER`.
- **Fallback automatico**: se OpenRouter fallisce o restituisce vuoto, la generazione ricade su **Claude** (nessun blocco della pipeline).
- **Modello per-monitor**: override opzionale con `config_data "ai_openrouter_model"`.

### Attivare DeepSeek (produzione)
Nel `.env` del server:
```env
OPENROUTER_API_KEY=sk-or-...
AI_ARTICLE_PROVIDER=openrouter
CHATBOT_PROVIDER=openrouter
```
Rollback: rimuovere/riportare a `anthropic` queste due variabili + restart gunicorn.

### Tracking costi
Le chiamate OpenRouter sono tracciate in `APIUsage` con `api_type='openrouter'` e compaiono nella dashboard costi (`/admin/home/apiusage/dashboard/`). I prezzi indicativi sono in `home/api_usage_tracker.py` (`OPENROUTER_PRICING`) — verificare/aggiornare su openrouter.ai/models.

### Note
- Il chatbot con OpenRouter è single-shot: `deepseek/deepseek-v4-flash` sarebbe sufficiente e ~5× più economico di V4 Pro.
- `openai` (SDK) è usato come client OpenRouter-compatibile (già dipendenza per il fallback OpenAI).

## Security Considerations

- Environment variables stored in `.env` file (not committed to git)
- API keys should never be hardcoded in source code
- Web scraping includes proper headers and rate limiting
- Content polishing removes potentially harmful characters and symbols
- Production security settings auto-enabled when DEBUG=False
- Image validation system prevents loading malicious external images
- Keyword filtering prevents processing of irrelevant content

## Production Deployment Notes

- **Gunicorn**: Serves Django via Unix socket (`carpi_news.sock`)
- **Apache**: Reverse proxy with SSL termination (Let's Encrypt)
- **Media Files**: Served directly by Apache for performance
- **Static Files**: Collected via `collectstatic` and served by Apache
- **Monitor Processes**: Auto-start on Django startup, managed via database
- **Monitor Configuration**: All monitors configured via `/admin/home/monitorconfig/`
- **Editorial Scheduler**: Automated daily articles at 8:00 AM
- **Cache System**: Redis/Database caching for image validation (30min-1hour TTL)

## Database-Driven Monitor System (NEW)

The monitoring system is now **fully database-driven**, replacing the old `monitor_configs.py` approach:

### Key Features
- ✅ **Admin Interface**: Manage all monitors via `/admin/home/monitorconfig/`
- ✅ **Dynamic Configuration**: Add/edit monitors without code changes
- ✅ **Individual Control**: Start/Stop/Test each monitor independently
- ✅ **Live Monitoring**: View logs and status in real-time
- ✅ **Auto-Start**: Monitors auto-start when Django loads (configurable via `is_active` flag)

### MonitorConfig Model
All monitor configurations stored in `home_monitorconfig` table with fields:
- Basic: `name`, `base_url`, `scraper_type`, `category`
- Control: `is_active`, `auto_approve`, `last_run`
- AI: `use_ai_generation`, `enable_web_search`, `ai_system_prompt`
- Config: `config_data` (JSON field for type-specific settings)

### Migration from Old System
```bash
# One-time: Import existing monitors from monitor_configs.py
python manage.py import_monitors

# Update existing monitors
python manage.py import_monitors --update

# After import, manage everything via admin interface
```

### Commands Reference
```bash
# Import monitors from monitor_configs.py (first time only)
python manage.py import_monitors [--update] [--delete-existing]

# Start monitors from database
python manage.py start_monitors [--monitor "Name"] [--daemon]

# Manage monitor status
python manage.py manage_db_monitors status|start|stop|restart [--monitor "Name"]
```

## Project Documentation

Additional guides available:
- **`MONITOR_DB_SYSTEM.md`**: Complete guide to database-driven monitor system (NEW)
- `UNIVERSAL_MONITOR_GUIDE.md`: Comprehensive guide to the monitoring system (legacy)
- `YOUTUBE_SETUP_GUIDE.md`: YouTube integration setup
- `POLISHING_SYSTEM_GUIDE.md`: Content polishing system documentation

## Social sharing & link tracking

Nuovi modelli:
- `ShortLink`: collega `Articolo`, `platform`, `medium` e token `/s/<token>/`, con `clicks_count` e ultimo referer.
- `SocialPublicationLog`: conserva `shared_url`, `short_link`, `instagram_media_id`, storico `instagram_media_ids` e `updated_at` per mappare Story/Reel IG all'articolo corretto anche dopo retry/ripubblicazioni.
- `InstagramAutoDMLog`: traccia trigger IG e invio DM.
- `InstagramOptOut`: utenti IG che hanno risposto `STOP`.

Endpoint:
- `/s/<token>/`: incrementa i click con rate limit cache-based e reindirizza all'articolo con UTM.
- `/instagram/`: smart link in bio, ultimi 7 giorni di contenuti Instagram.
- `/instagram/search/`: ricerca AJAX per titolo/categoria.
- `/webhooks/instagram/`: webhook Meta per reazioni, risposte e commenti.

Convention UTM:
- `utm_source=<platform>`
- `utm_medium=<medium>`
- `utm_campaign=share`

Limiti Meta:
- Instagram Story: Link Sticker non disponibile via Graph API.
- Instagram Reel: link in caption non cliccabile; il link viene messo nel primo commento e in bio.
- Facebook Reel/Story pubblicati via `/video_stories`: si prova a inviare `description`/`text`; se Meta rifiuta, la pubblicazione viene ritentata senza descrizione per non bloccare la pipeline.

Variabili ambiente:
- `SITE_URL`
- `INSTAGRAM_WEBHOOK_VERIFY_TOKEN`
- `INSTAGRAM_PAGE_ACCESS_TOKEN`
- `INSTAGRAM_AUTO_DM_ACCEPT_ANY_EMOJI`
- `INSTAGRAM_AUTO_DM_TEXT_TRIGGERS`
- `INSTAGRAM_AUTO_DM_STORY_FALLBACK_MINUTES` default `1440` (24 ore)
- `INSTAGRAM_AUTO_DM_REEL_FALLBACK_MINUTES` default `4320` (72 ore)
- `INSTAGRAM_WEBHOOK_HANDLE_SYNC` default `False`; usare `True` solo nei test/manual debug.

## Diagnostica DM IG

Comandi utili:
- `python manage.py test_instagram_dm --fixture story_reaction`: parse fixture senza inviare DM.
- `python manage.py test_instagram_dm --fixture story_reply --handle-fixture`: gestisce fixture con invio DM mockato.
- `python manage.py test_instagram_dm --media-id <ig_media_id> --sender-id <ig_sender_id> --send`: invia davvero un DM di test.
- `python manage.py check_ig_dm_token`: controlla `/debug_token`, validità, scadenza e scope del token DM.
- `python manage.py check_ig_subscriptions`: legge `/{page-id}/subscribed_apps` e stampa i campi webhook sottoscritti.

Note operative:
- Il webhook risponde subito `200` e gestisce gli eventi in background, salvo `INSTAGRAM_WEBHOOK_HANDLE_SYNC=True`.
- Eventi duplicati Meta vengono deduplicati in cache per 24 ore.
- Il rate limit per utente dura 60 secondi ma viene liberato se l'invio DM fallisce.
- Trigger testuali sono matchati per parola intera: `LINK` matcha, `LINKEDIN` non matcha.

## Instagram Webhook Setup

1. App configurata su flusso Instagram API + Facebook Login, use case "Manage Pages" + Instagram Graph. Verificare che `instagram_manage_messages` e `pages_messaging` siano "Ready for testing".
2. Meta Developer dashboard -> app -> Webhooks -> Instagram: subscribe ai campi `messages`, `message_reactions`, `comments`.
3. Callback URL: `https://ombradelportico.it/webhooks/instagram/`.
4. Verify token: valore di `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` in `.env`.
5. Sottoscrivere anche la Pagina Facebook collegata all'account IG: `POST /{page-id}/subscribed_apps?subscribed_fields=messages,message_reactions,messaging_postbacks&access_token=<page_token>`.
6. Permission da richiedere in App Review: `instagram_manage_messages`, `instagram_manage_comments`, `pages_messaging`, `pages_show_list`, `pages_read_engagement`.
7. Durante sviluppo aggiungere utenti come Tester / Instagram Tester in App Roles.
8. Token per inviare DM: Page Access Token dell'IG Business Account in `INSTAGRAM_PAGE_ACCESS_TOKEN`.
