#!/usr/bin/env python3
"""
Script di test per verificare il funzionamento di tutti i monitor
Genera articoli finti per testare auto-approvazione e salvataggio
"""
import sys
import os
import django
from datetime import datetime

# Setup Django
sys.path.append(os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carpi_news.settings')
django.setup()

from home.models import Articolo
from home.monitor_configs import MONITOR_CONFIGS
from home.universal_news_monitor import UniversalNewsMonitor
from django.utils import timezone
import uuid

def create_fake_article_data(monitor_name: str) -> dict:
    """Crea dati articolo finti per testare il monitor"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    unique_id = str(uuid.uuid4())[:8]
    
    fake_articles = {
        'carpi_calcio': {
            'title': f'Test Carpi Calcio {timestamp} - Vittoria in trasferta',
            'url': f'https://carpicalcio.it/test-{unique_id}',
            'preview': 'Ottima prestazione della squadra biancorossa che conquista tre punti importanti.',
            'full_content': '<p>La squadra di Carpi ha disputato un\'ottima partita vincendo per 2-1 contro gli avversari. <strong>Doppietta di Rossi</strong> nel secondo tempo che regala i tre punti ai biancorossi.</p><p>Il mister si dice soddisfatto della prestazione e guarda con ottimismo ai prossimi impegni.</p>',
            'image_url': 'https://example.com/carpi-calcio-test.jpg'
        },
        'comune_carpi': {
            'title': f'Test Comune Carpi {timestamp} - Nuovo servizio per cittadini',
            'url': f'https://comune.carpi.mo.it/test-{unique_id}',
            'preview': 'Il Comune di Carpi annuncia l\'attivazione di un nuovo servizio digitale per i cittadini.',
            'full_content': '<p>Il sindaco di Carpi ha presentato oggi il nuovo <strong>portale digitale</strong> che permetterà ai cittadini di accedere a tutti i servizi comunali online.</p><p>Il servizio sarà attivo dal prossimo lunedì e rappresenta un importante passo verso la digitalizzazione dell\'amministrazione.</p>',
            'image_url': 'https://example.com/comune-carpi-test.jpg'
        },
        'comune_carpi_graphql': {
            'title': f'Test Comune GraphQL {timestamp} - Comunicazione importante',
            'url': f'https://comune.carpi.mo.it/graphql-test-{unique_id}',
            'preview': 'Importante comunicazione dal Comune di Carpi tramite API GraphQL.',
            'full_content': '<p>Tramite il sistema GraphQL, il Comune comunica una <strong>importante decisione</strong> per la cittadinanza.</p><p>Tutti i dettagli sono disponibili sul sito ufficiale del Comune.</p>',
            'image_url': 'https://example.com/comune-graphql-test.jpg'
        },
        'eventi_carpi_graphql': {
            'title': f'Test Eventi Carpi {timestamp} - Festival della Musica',
            'url': f'https://comune.carpi.mo.it/eventi-test-{unique_id}',
            'preview': 'Al via il Festival della Musica 2025 in Piazza Martiri.',
            'full_content': '<p>Si svolgerà dal 15 al 20 marzo il <strong>Festival della Musica 2025</strong> in Piazza Martiri.</p><p>Cinque serate di musica dal vivo con artisti locali e nazionali. Ingresso gratuito per tutti gli eventi.</p>',
            'image_url': 'https://example.com/eventi-test.jpg'
        },
        'voce_carpi': {
            'title': f'Test Voce Carpi {timestamp} - Cronaca cittadina',
            'url': f'https://voce.it/test-{unique_id}',
            'preview': 'Notizie di cronaca dalla città di Carpi tramite La Voce.',
            'full_content': '<p>La Voce di Carpi riporta le principali <strong>notizie di cronaca</strong> dalla città.</p><p>Continua l\'impegno del giornale locale nell\'informazione cittadina.</p>',
            'image_url': 'https://example.com/voce-test.jpg'
        },
        'temponews': {
            'title': f'Test TempoNews {timestamp} - Attualità locale',
            'url': f'https://temponews.it/test-{unique_id}',
            'preview': 'TempoNews riporta le ultime notizie di attualità da Carpi.',
            'full_content': '<p>TempoNews continua a seguire l\'<strong>attualità carpigiana</strong> con articoli approfonditi.</p><p>Focus particolare sugli eventi che coinvolgono la comunità locale.</p>',
            'image_url': 'https://example.com/temponews-test.jpg'
        },
        'ansa_carpi': {
            'title': f'Test ANSA Carpi {timestamp} - Notizia nazionale',
            'url': f'https://ansa.it/emilia-romagna/test-{unique_id}',
            'preview': 'ANSA riporta notizie dall\'Emilia-Romagna con focus su Carpi.',
            'full_content': '<p>L\'agenzia ANSA segnala una <strong>notizia di rilevanza nazionale</strong> che coinvolge anche Carpi.</p><p>I dettagli della vicenda sono ancora in fase di approfondimento.</p>',
            'image_url': 'https://example.com/ansa-test.jpg'
        }
    }
    
    return fake_articles.get(monitor_name, {
        'title': f'Test {monitor_name} {timestamp} - Articolo generico',
        'url': f'https://example.com/test-{unique_id}',
        'preview': f'Articolo di test per il monitor {monitor_name}.',
        'full_content': f'<p>Questo è un <strong>articolo di test</strong> per il monitor {monitor_name}.</p>',
        'image_url': f'https://example.com/{monitor_name}-test.jpg'
    })

def test_monitor(monitor_name: str, config):
    """Testa un singolo monitor"""
    print(f"\n{'='*60}")
    print(f"TESTING: {config.name} ({monitor_name})")
    print(f"{'='*60}")
    
    try:
        # Crea monitor
        monitor = UniversalNewsMonitor(config, check_interval=1)
        print(f"[OK] Monitor creato: {config.name}")
        print(f"   Categoria: {config.category}")
        print(f"   Scraper type: {config.scraper_type}")
        
        # Controlla auto-approvazione
        auto_approve = config.config.get('auto_approve', False)
        should_approve = monitor.should_auto_approve(config.category)
        print(f"   Auto-approve config: {auto_approve}")
        print(f"   Should auto-approve: {should_approve}")
        
        # Crea articolo finto
        fake_data = create_fake_article_data(monitor_name)
        print(f"   Articolo test creato: {fake_data['title'][:50]}...")
        
        # Conta articoli prima del test
        before_count = Articolo.objects.count()
        
        # Testa salvataggio diretto (senza AI)
        print(f"   Testando salvataggio diretto...")
        monitor.save_article_directly(fake_data)
        
        # Conta articoli dopo il test
        after_count = Articolo.objects.count()
        new_articles = after_count - before_count
        
        if new_articles > 0:
            # Trova l'articolo appena salvato
            latest_article = Articolo.objects.filter(fonte=fake_data['url']).first()
            if latest_article:
                print(f"   RISULTATO: Articolo salvato con ID {latest_article.id}")
                print(f"   Titolo: {latest_article.titolo}")
                print(f"   Categoria: {latest_article.categoria}")
                print(f"   Approvato: {latest_article.approvato}")
                print(f"   Foto: {latest_article.foto or 'Nessuna'}")
                print(f"   Slug: {latest_article.slug}")
                
                # Verifica auto-approvazione
                if should_approve and not latest_article.approvato:
                    print(f"   [ERRORE] Doveva essere auto-approvato ma non lo è!")
                elif not should_approve and latest_article.approvato:
                    print(f"   [ATTENZIONE] Non doveva essere auto-approvato ma lo è!")
                else:
                    print(f"   [SUCCESSO] Auto-approvazione corretta!")
        else:
            print(f"   [ERRORE] Nessun articolo salvato!")
            
    except Exception as e:
        print(f"   [ERRORE] {str(e)}")
        import traceback
        print(f"   Traceback: {traceback.format_exc()}")

def main():
    """Testa tutti i monitor"""
    print("MONITOR TESTING SUITE")
    print("Avvio test per tutti i monitor configurati...")
    print(f"Timestamp: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Conta articoli iniziali
    initial_count = Articolo.objects.count()
    print(f"Articoli nel database all'inizio: {initial_count}")
    
    # Testa ogni monitor
    for monitor_name, config in MONITOR_CONFIGS.items():
        try:
            test_monitor(monitor_name, config)
        except Exception as e:
            print(f"\n[ERRORE CRITICO] nel test di {monitor_name}: {e}")
    
    # Statistiche finali
    final_count = Articolo.objects.count()
    new_articles_total = final_count - initial_count
    
    print(f"\n{'='*60}")
    print("STATISTICHE FINALI")
    print(f"{'='*60}")
    print(f"Articoli iniziali: {initial_count}")
    print(f"Articoli finali: {final_count}")
    print(f"Nuovi articoli creati: {new_articles_total}")
    
    # Mostra articoli approvati vs non approvati
    approved = Articolo.objects.filter(approvato=True).count()
    not_approved = Articolo.objects.filter(approvato=False).count()
    print(f"Articoli approvati: {approved}")
    print(f"Articoli in attesa: {not_approved}")
    
    print(f"\nTest completato! Controlla gli articoli in admin per verificare i risultati.")

if __name__ == "__main__":
    main()