#!/usr/bin/env python
"""
Script per ottenere Facebook Page Access Token usando OAuth manuale
"""

import requests
import sys
import os
from urllib.parse import urlencode
from dotenv import load_dotenv

# Carica variabili d'ambiente
load_dotenv()

APP_ID = os.getenv('FACEBOOK_APP_ID')
APP_SECRET = os.getenv('FACEBOOK_APP_SECRET')
REDIRECT_URI = "https://localhost/"  # Non serve un server reale

if not APP_ID or not APP_SECRET:
    print("ERRORE: Configura FACEBOOK_APP_ID e FACEBOOK_APP_SECRET nel file .env")
    sys.exit(1)

def generate_oauth_url():
    """Genera l'URL per l'autorizzazione OAuth"""
    params = {
        'client_id': APP_ID,
        'redirect_uri': REDIRECT_URI,
        'scope': 'pages_manage_posts,pages_show_list,pages_read_engagement,instagram_basic,instagram_content_publish',
        'response_type': 'code'
    }

    oauth_url = f"https://www.facebook.com/v24.0/dialog/oauth?{urlencode(params)}"
    return oauth_url

def exchange_code_for_token(auth_code):
    """Scambia il codice di autorizzazione con un token di accesso"""
    url = "https://graph.facebook.com/v24.0/oauth/access_token"
    params = {
        'client_id': APP_ID,
        'client_secret': APP_SECRET,
        'redirect_uri': REDIRECT_URI,
        'code': auth_code
    }

    print("\n🔄 Scambio codice con token...")
    response = requests.get(url, params=params)

    if response.status_code != 200:
        print(f"❌ Errore: {response.text}")
        return None

    data = response.json()
    if 'access_token' not in data:
        print(f"❌ Errore: {data}")
        return None

    print("✅ User Access Token ottenuto")
    return data['access_token']

def get_long_lived_token(short_token):
    """Converti in Long-Lived User Access Token"""
    url = "https://graph.facebook.com/v24.0/oauth/access_token"
    params = {
        'grant_type': 'fb_exchange_token',
        'client_id': APP_ID,
        'client_secret': APP_SECRET,
        'fb_exchange_token': short_token
    }

    print("🔄 Conversione in Long-Lived Token...")
    response = requests.get(url, params=params)

    if response.status_code != 200:
        print(f"❌ Errore: {response.text}")
        return None

    data = response.json()
    if 'access_token' not in data:
        print(f"❌ Errore: {data}")
        return None

    print("✅ Long-Lived User Token ottenuto")
    return data['access_token']

def get_page_info(user_token):
    """Ottieni Page Access Token e Page ID"""
    url = "https://graph.facebook.com/v24.0/me/accounts"
    params = {'access_token': user_token}

    print("🔄 Recupero informazioni pagina...")
    response = requests.get(url, params=params)

    if response.status_code != 200:
        print(f"❌ Errore: {response.text}")
        return None, None, None

    data = response.json()

    if 'data' not in data or len(data['data']) == 0:
        print("❌ Nessuna pagina trovata")
        print("⚠️  Assicurati di essere amministratore di una pagina Facebook")
        return None, None, None

    # Mostra le pagine
    print(f"\n📄 Trovate {len(data['data'])} pagine:")
    for i, page in enumerate(data['data']):
        print(f"{i+1}. {page['name']} (ID: {page['id']})")

    if len(data['data']) == 1:
        page = data['data'][0]
        return page['access_token'], page['id'], page['name']

    # Selezione pagina
    while True:
        try:
            choice = input(f"\nScegli la pagina (1-{len(data['data'])}): ")
            index = int(choice) - 1
            if 0 <= index < len(data['data']):
                page = data['data'][index]
                return page['access_token'], page['id'], page['name']
            else:
                print("❌ Scelta non valida")
        except (ValueError, KeyboardInterrupt):
            return None, None, None

def main():
    print("=" * 70)
    print("🔧 Facebook Page Access Token Generator - OAuth Flow")
    print("=" * 70)

    # Step 1: Genera URL OAuth
    oauth_url = generate_oauth_url()

    print("\n📋 ISTRUZIONI:")
    print("=" * 70)
    print("\n1. Apri questo URL nel browser:\n")
    print(f"   {oauth_url}\n")
    print("2. Autorizza l'app per accedere alla tua pagina Facebook")
    print("3. Verrai reindirizzato a un URL tipo:")
    print("   https://localhost/?code=XXXXXX#_=_")
    print("4. COPIA tutto il testo dopo 'code=' e prima di '#' o '&'")
    print("   (Es: se vedi 'code=ABC123#_=_', copia solo 'ABC123')\n")
    print("=" * 70)

    # Step 2: Richiedi il codice all'utente
    auth_code = input("\n📝 Incolla il codice qui: ").strip()

    # Pulisci il codice da eventuali caratteri extra
    if '#' in auth_code:
        auth_code = auth_code.split('#')[0]
    if '&' in auth_code:
        auth_code = auth_code.split('&')[0]

    if not auth_code:
        print("❌ Codice non valido")
        return

    # Step 3: Scambia il codice con un token
    user_token = exchange_code_for_token(auth_code)
    if not user_token:
        return

    # Step 4: Converti in Long-Lived Token
    long_token = get_long_lived_token(user_token)
    if not long_token:
        return

    # Step 5: Ottieni Page Token
    page_token, page_id, page_name = get_page_info(long_token)
    if not page_token:
        return

    # Mostra risultati
    print("\n" + "=" * 70)
    print("CREDENZIALI FACEBOOK OTTENUTE CON SUCCESSO")
    print("=" * 70)
    print(f"\nPagina: {page_name}")
    print(f"Page ID: {page_id}")

    print("\n" + "=" * 70)
    print("IMPORTANTE - DUE TIPI DI TOKEN")
    print("=" * 70)
    print(f"\n1. LONG-LIVED USER TOKEN (dura 60 giorni - USA QUESTO):")
    print(f"{long_token}")
    print(f"\n2. PAGE ACCESS TOKEN (scade presto - NON usare):")
    print(f"{page_token}")

    print("\n" + "=" * 70)
    print("AGGIUNGI QUESTE VARIABILI AL FILE .env:")
    print("=" * 70)
    print(f"\nFACEBOOK_AUTO_SHARE=True")
    print(f"FACEBOOK_PAGE_ID={page_id}")
    print(f"FACEBOOK_ACCESS_TOKEN={long_token}")
    print(f"# ^ USA IL LONG-LIVED USER TOKEN (sopra), NON il Page Token!")
    print(f"FACEBOOK_APP_ID={APP_ID}")
    print(f"FACEBOOK_APP_SECRET={APP_SECRET}")

    print("\n" + "=" * 70)
    print("NOTA IMPORTANTE")
    print("=" * 70)
    print("Il Long-Lived User Token dura 60 giorni.")
    print("Il sistema lo rinnovera automaticamente prima della scadenza.")
    print("Il Page Access Token viene generato automaticamente quando serve.")
    print("\nConfigurazione completata!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Operazione annullata")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Errore: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
