import logging
import re
import unicodedata
from datetime import datetime

import requests
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)


def _strip_accents(text):
    """Rimuove gli accenti per il matching delle date.

    I siti dei cinema scrivono i giorni con l'accento (es. "Mercoledì 15"),
    mentre i pattern usano la forma senza accento ("mercoledi"). Normalizzando
    il testo sorgente il confronto funziona a prescindere dall'accento.
    I nomi dei mesi italiani non hanno accenti, quindi l'operazione e' sicura.
    """
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')

USER_AGENT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def cinema_date_context(now=None):
    today = now or datetime.now()
    today_day = today.day
    today_day_padded = f"{today_day:02d}"
    today_month_it = ['', 'gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
                      'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre'][today.month]
    today_month_num = f"{today.month:02d}"
    weekdays_it = ['lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica']
    today_weekday = weekdays_it[today.weekday()]
    all_months_it = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
                     'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']
    other_months_it = '|'.join(m for m in all_months_it if m != today_month_it)

    today_patterns = [
        f"{today_weekday}\\s+\\b{today_day}\\b(?!\\s+(?:{other_months_it}))",
        f"{today_weekday}\\s+\\b{today_day_padded}\\b(?!\\s+(?:{other_months_it}))",
        f"\\b{today_day}\\b\\s+{today_month_it}",
        f"\\b{today_day_padded}\\b\\s+{today_month_it}",
        f"{today_weekday}\\s+\\b{today_day}\\b\\s+{today_month_it}",
        f"{today_day_padded}/{today_month_num}/",
    ]
    return {
        'today': today,
        'today_day': today_day,
        'today_month_it': today_month_it,
        'today_weekday': today_weekday,
        'today_patterns': today_patterns,
    }


def cinema_payload(name, address, website, films=None):
    return {
        'name': name,
        'address': address,
        'website': website,
        'films': films or [],
    }


def _today_info(date_ctx, showtimes):
    info = f"Oggi {date_ctx['today_weekday']} {date_ctx['today_day']} {date_ctx['today_month_it']}"
    if showtimes:
        info += f" - Orari: {', '.join(showtimes)}"
    return info


def _normalize_showtimes(showtimes):
    """Orari in formato HH:MM, senza duplicati e ordinati.

    I siti dei cinema scrivono gli orari sia come "21:15" sia come "21.15":
    lo ScreeningEvent di schema.org ha bisogno di un orario normalizzato per
    costruire la startDate, che per Google e' obbligatoria.
    """
    normalized = set()
    for raw in showtimes or []:
        match = re.match(r'^(\d{1,2})[:.](\d{2})$', str(raw).strip())
        if not match:
            continue
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            continue
        normalized.add(f"{hour:02d}:{minute:02d}")
    return sorted(normalized)


def _film_entry(date_ctx, title, image, showtimes):
    """Voce film con data e orari strutturati oltre alla stringa leggibile.

    `date` e `showtimes` servono allo schema.org della pagina cinema; `info`
    resta il testo mostrato nel template.
    """
    normalized = _normalize_showtimes(showtimes)
    return {
        'title': title,
        'image': image if image else '',
        'info': _today_info(date_ctx, normalized),
        'date': date_ctx['today'].date().isoformat(),
        'showtimes': normalized,
    }


def _scrape_tmb_cinema(name, address, website, placeholder_default=False):
    date_ctx = cinema_date_context()
    films = []
    response = requests.get(website, timeout=10)
    if response.status_code != 200:
        return cinema_payload(name, address, website, films)

    soup = BeautifulSoup(response.content, 'html.parser')
    for card in soup.find_all('div', class_='tmb'):
        try:
            title_elem = card.find('h2', class_='t-entry-title') or card.find('h3')
            title = title_elem.get_text(strip=True) if title_elem else None
            if not title:
                continue

            text_elem = card.find('div', class_='t-entry-text')
            if not text_elem:
                continue
            info_text = _strip_accents(text_elem.get_text(separator=' ', strip=True).lower())

            today_showtimes = []
            for pattern in date_ctx['today_patterns']:
                match = re.search(pattern, info_text, re.IGNORECASE)
                if match:
                    times = re.findall(r'\b(\d{1,2}[:.]\d{2})\b', info_text[match.end():match.end() + 100])
                    today_showtimes.extend(times[:3])
                    break
            else:
                continue

            img_elem = card.find('img')
            image = ''
            if img_elem:
                image = img_elem.get('data-src') or img_elem.get('src') or img_elem.get('data-lazy-src', '')
                image_lower = image.lower()
                if 'placeholder' in image_lower or (placeholder_default and 'default' in image_lower):
                    image = ''

            films.append(_film_entry(date_ctx, title, image, today_showtimes))
        except Exception as exc:
            logger.error("Errore parsing film %s: %s", name, exc)
    return cinema_payload(name, address, website, films)


def scrape_eden():
    return _scrape_tmb_cinema(
        'Cinema Eden',
        'Via Santa Chiara 22, Carpi',
        'https://www.cinemaedencarpi.it/',
        placeholder_default=True,
    )


def scrape_corso():
    return _scrape_tmb_cinema(
        'Cinema Corso',
        'Corso M. Fanti 91, Carpi',
        'https://www.cinemacorsocarpi.it/',
    )


def _scrape_ariston_arena(url, date_ctx):
    """Programmazione dell'Arena San Rocco (cinema estivo Ariston).

    In estate l'Ariston non pubblica gli orari nella home ma in un articolo
    dedicato, con un film per sera nel formato:
    "Mercoledi 15 luglio VITA PRIVATA di Rebecca Zlotowski, con ...".
    Il titolo (in maiuscolo) e' compreso tra la data e il connettore " di "
    (minuscolo) del regista. L'orario e' fisso ("INIZIO PROIEZIONE ORE 21:15").
    """
    films = []
    try:
        response = requests.get(url, headers=USER_AGENT_HEADERS, timeout=10)
        if response.status_code != 200:
            return films

        soup = BeautifulSoup(response.content, 'html.parser')
        article = soup.find('article') or soup
        text = _strip_accents(article.get_text(separator=' ', strip=True))

        show_match = re.search(r'inizio proiezione ore\s*(\d{1,2}[:.]\d{2})', text, re.IGNORECASE)
        showtime = show_match.group(1).replace('.', ':') if show_match else '21:15'

        day = date_ctx['today_day']
        month = date_ctx['today_month_it']
        date_match = re.search(rf"\b0?{day}\b\s+{month}\s+", text, re.IGNORECASE)
        if not date_match:
            return films

        rest = text[date_match.end():]
        # Titolo in maiuscolo fino al connettore " di " (minuscolo) del regista.
        title_match = re.match(r"(.+?)\s+di\s", rest)
        title = title_match.group(1).strip() if title_match else rest.split('  ')[0].strip()[:80]
        if title and len(title) >= 3:
            films.append(_film_entry(date_ctx, title, '', [showtime]))
    except Exception as exc:
        logger.error("Errore parsing Arena Ariston: %s", exc)
    return films


def scrape_ariston():
    date_ctx = cinema_date_context()
    films = []
    website = 'https://www.aristoncinemacarpi.it/'
    response = requests.get(website, headers=USER_AGENT_HEADERS, timeout=10)
    if response.status_code != 200:
        return cinema_payload('Cinema Ariston', 'Via Ernesto Boccaletti 3, San Marino di Carpi', website, films)

    soup = BeautifulSoup(response.content, 'html.parser')
    movie_section = soup.find('section', id='movie')
    if not movie_section:
        logger.warning("Cinema Ariston - Sezione #movie non trovata")
        return cinema_payload('Cinema Ariston', 'Via Ernesto Boccaletti 3, San Marino di Carpi', website, films)

    for article in movie_section.find_all('article'):
        try:
            title_elem = article.find('h2', class_='entry-title')
            if not title_elem:
                continue
            title_link = title_elem.find('a')
            title = title_link.get_text(strip=True) if title_link else title_elem.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            # In estate la programmazione e' nell'articolo dedicato "Arena San Rocco".
            if 'arena' in _strip_accents(title.lower()):
                arena_url = title_link.get('href') if title_link else None
                if arena_url:
                    films.extend(_scrape_ariston_arena(arena_url, date_ctx))
                continue

            excerpt = article.find('div', class_='entry-excerpt')
            if not excerpt:
                continue

            today_showtimes = []
            has_today = False
            for line in excerpt.get_text(separator='\n').split('\n'):
                line_lower = _strip_accents(line.strip().lower())
                if not line_lower:
                    continue
                for pattern in date_ctx['today_patterns']:
                    if re.search(pattern, line_lower, re.IGNORECASE):
                        has_today = True
                        time_match = re.search(r'ore\s*(\d{1,2}:\d{2})', line_lower, re.IGNORECASE)
                        if time_match:
                            today_showtimes.append(time_match.group(1))
                        break
            if not has_today:
                continue

            image = ''
            thumb = article.find('div', class_='list-article-thumb')
            if thumb:
                img_elem = thumb.find('img')
                if img_elem:
                    image = img_elem.get('src', '') or img_elem.get('data-src', '')

            films.append(_film_entry(date_ctx, title, image, today_showtimes))
        except Exception as exc:
            logger.error("Errore parsing articolo Ariston: %s", exc)
    return cinema_payload('Cinema Ariston', 'Via Ernesto Boccaletti 3, San Marino di Carpi', website, films)


def scrape_spacecity():
    date_ctx = cinema_date_context()
    films = []
    website = 'https://www.spacecity.it/'
    response = requests.get(website, headers=USER_AGENT_HEADERS, timeout=10)
    if response.status_code != 200:
        return cinema_payload('Space City Multisala', "Viale dell'Industria 9, Carpi", website, films)

    soup = BeautifulSoup(response.content, 'html.parser')
    for movie_div in soup.find_all('div', class_='movie--preview'):
        try:
            title_elem = movie_div.find('a', class_='movie__title')
            if not title_elem:
                continue
            title = title_elem.get_text(strip=True)
            if not title:
                continue

            image = ''
            img_elem = movie_div.find('img', class_='img-fluid')
            if img_elem:
                image = img_elem.get('src', '')

            schedule_section = movie_div.find('div', class_='schedule-section-show')
            if not schedule_section:
                continue
            schedule_full_text = _strip_accents(schedule_section.get_text(separator=' ', strip=True))

            today_showtimes = []
            for pattern in date_ctx['today_patterns']:
                match = re.search(pattern, schedule_full_text, re.IGNORECASE)
                if match:
                    text_after_today = schedule_full_text[match.end():]
                    next_date_pattern = r'(lunedi|martedi|mercoledi|giovedi|venerdi|sabato|domenica)\s+\d{2}/\d{2}/\d{4}'
                    next_date_match = re.search(next_date_pattern, text_after_today, re.IGNORECASE)
                    today_section = text_after_today[:next_date_match.start()] if next_date_match else text_after_today[:200]
                    today_showtimes.extend(re.findall(r'\b(\d{1,2}:\d{2})\b', today_section))
                    break
            else:
                continue

            films.append(_film_entry(date_ctx, title, image, today_showtimes))
        except Exception as exc:
            logger.error("Errore parsing film Space City: %s", exc)
    return cinema_payload('Space City Multisala', "Viale dell'Industria 9, Carpi", website, films)
