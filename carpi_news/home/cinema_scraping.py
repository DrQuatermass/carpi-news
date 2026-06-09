import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)

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
            info_text = text_elem.get_text(separator=' ', strip=True).lower()

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

            films.append({
                'title': title,
                'image': image if image else '',
                'info': _today_info(date_ctx, today_showtimes),
            })
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

            excerpt = article.find('div', class_='entry-excerpt')
            if not excerpt:
                continue

            today_showtimes = []
            has_today = False
            for line in excerpt.get_text(separator='\n').split('\n'):
                line_lower = line.strip().lower()
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

            films.append({
                'title': title,
                'image': image if image else '',
                'info': _today_info(date_ctx, sorted(set(today_showtimes))),
            })
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
            schedule_full_text = schedule_section.get_text(separator=' ', strip=True)

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

            films.append({
                'title': title,
                'image': image if image else '',
                'info': _today_info(date_ctx, today_showtimes),
            })
        except Exception as exc:
            logger.error("Errore parsing film Space City: %s", exc)
    return cinema_payload('Space City Multisala', "Viale dell'Industria 9, Carpi", website, films)
