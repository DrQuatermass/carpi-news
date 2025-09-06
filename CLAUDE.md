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

## Universal Monitoring System

The project features a sophisticated multi-source news monitoring system:

### Core Components
- **`universal_news_monitor.py`**: Universal scraper class supporting HTML scraping, WordPress API, and YouTube
- **`monitor_configs.py`**: Centralized configurations for all news sources
- **`monitor_manager.py`**: Manages multiple concurrent monitors
- **`start_universal_monitors.py`**: Main entry point for starting all monitors

### Supported Sources
- **Carpi Calcio**: HTML scraping with AI content generation
- **Comune Carpi**: WordPress REST API integration
- **YouTube Channels**: Transcript-based article generation

### Legacy Monitors (Being Replaced)
- `carpi_calcio_monitor.py`: Original Carpi Calcio scraper
- `comune_notizie_monitor.py`: Original Comune scraper
- `youtube_transcript.py`: Original YouTube processor

## Content Processing Pipeline

1. **Monitoring**: Automated scraping of configured news sources
2. **Content Extraction**: HTML parsing, API calls, or transcript processing
3. **AI Enhancement**: Content polishing and uniformity via `content_polisher.py`
4. **Image Processing**: Automatic image extraction and URL management
5. **Approval Workflow**: Articles require manual approval before publication
6. **Logging**: Comprehensive logging via `logger_config.py`

## Management Commands

The project includes Django management commands in `home/management/commands/`:
- `monitor_playlist.py`: Monitor specific YouTube playlists
- `manage_monitors.py`: Manage and control universal monitors
- `update_editorial_images.py`: Update editorial content images

## Common Commands

**Development Server**:
```bash
cd carpi_news
python manage.py runserver
```

**Start Universal Monitoring System**:
```bash
cd carpi_news
python start_universal_monitors.py
```

**Database Operations**:
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

**Management Commands**:
```bash
python manage.py monitor_playlist
python manage.py manage_monitors
python manage.py update_editorial_images
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

## Project Documentation

Additional guides available:
- `UNIVERSAL_MONITOR_GUIDE.md`: Comprehensive guide to the monitoring system
- `YOUTUBE_SETUP_GUIDE.md`: YouTube integration setup
- `POLISHING_SYSTEM_GUIDE.md`: Content polishing system documentation