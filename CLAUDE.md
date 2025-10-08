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
- `YOUTUBE_API_KEY` & `YOUTUBE_PLAYLIST_ID`: YouTube integration
- `MONITOR_INTERVAL_*`: Custom intervals for each monitor (seconds)

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