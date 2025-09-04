#!/usr/bin/env python
"""
Script per generare una SECRET_KEY sicura per Django.
Esegui questo script e copia la chiave generata nel tuo file .env
"""

import secrets
import string

def generate_secret_key(length=50):
    """Genera una SECRET_KEY sicura per Django"""
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*(-_=+)'
    return ''.join(secrets.choice(alphabet) for _ in range(length))

if __name__ == "__main__":
    key = generate_secret_key()
    print("=" * 60)
    print("NUOVA SECRET_KEY GENERATA:")
    print("=" * 60)
    print(f"SECRET_KEY={key}")
    print("=" * 60)
    print("Copia questa chiave nel tuo file .env")
    print("IMPORTANTE: Non condividere mai questa chiave!")
    print("=" * 60)