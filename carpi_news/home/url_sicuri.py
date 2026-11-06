"""Scaricare pagine da URL trovati nelle fonti (email, schede, link nel testo) senza raggiungere
la rete interna del server.

Un link scritto apposta in una fonte (http://127.0.0.1:8000/..., http://192.168.x.x/, l'indirizzo
dei metadati del provider 169.254.169.254) farebbe leggere al server una sua pagina interna, che poi
finirebbe nel testo dato all'AI. Qui si accettano solo http/https verso indirizzi pubblici, anche
dopo ogni redirect, e si legge al massimo MAX_BYTES.
"""
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests

MAX_REDIRECT = 5
MAX_BYTES = 3 * 1024 * 1024


class UrlNonConsentito(ValueError):
    pass


def indirizzo_pubblico(host):
    """True se tutti gli indirizzi a cui risolve l'host sono pubblici."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split('%')[0])
        except ValueError:
            return False
        if getattr(ip, 'ipv4_mapped', None):
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            return False
    return True


def controlla_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise UrlNonConsentito(f"schema non ammesso: {url}")
    if not indirizzo_pubblico(parsed.hostname):
        raise UrlNonConsentito(f"indirizzo non pubblico: {url}")


def get_pubblico(url, headers=None, timeout=15, max_bytes=MAX_BYTES):
    """requests.get che segue i redirect a mano controllando ogni passaggio. Il contenuto
    oltre max_bytes viene tagliato. Solleva UrlNonConsentito per gli indirizzi interni."""
    for _ in range(MAX_REDIRECT + 1):
        controlla_url(url)
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=False, stream=True)
        if response.is_redirect and response.headers.get('Location'):
            url = urljoin(url, response.headers['Location'])
            response.close()
            continue
        dati = b''
        for blocco in response.iter_content(64 * 1024):
            dati += blocco
            if len(dati) >= max_bytes:
                break
        response.close()
        response._content = dati[:max_bytes]
        response._content_consumed = True
        return response
    raise UrlNonConsentito(f"troppi redirect: {url}")
