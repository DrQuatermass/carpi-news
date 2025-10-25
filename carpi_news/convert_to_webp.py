#!/usr/bin/env python3
"""
Script per convertire tutte le immagini PNG/JPG in WebP
Ottimizza dimensioni mantenendo qualità
"""
from PIL import Image
import os
from pathlib import Path

def convert_to_webp(image_path, quality=85, max_width=1200):
    """
    Converte un'immagine in WebP ottimizzato

    Args:
        image_path: Path dell'immagine da convertire
        quality: Qualità WebP (0-100, default 85)
        max_width: Larghezza massima per ridimensionamento (default 1200px)
    """
    try:
        # Apri immagine
        img = Image.open(image_path)

        # Ottieni dimensioni originali
        original_size = os.path.getsize(image_path)
        width, height = img.size

        # Ridimensiona se troppo grande
        if width > max_width:
            ratio = max_width / width
            new_height = int(height * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            print(f"  Ridimensionato: {width}x{height} -> {max_width}x{new_height}")

        # Converti in RGB se necessario (per PNG con trasparenza)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background

        # Crea path WebP
        webp_path = image_path.with_suffix('.webp')

        # Salva come WebP
        img.save(webp_path, 'WebP', quality=quality, method=6)

        # Statistiche
        webp_size = os.path.getsize(webp_path)
        savings = original_size - webp_size
        savings_percent = (savings / original_size) * 100

        print(f"  [OK] Creato: {webp_path.name}")
        print(f"  Dimensione originale: {original_size / 1024:.1f} KB")
        print(f"  Dimensione WebP: {webp_size / 1024:.1f} KB")
        print(f"  Risparmio: {savings / 1024:.1f} KB ({savings_percent:.1f}%)\n")

        return webp_path, savings

    except Exception as e:
        print(f"  [ERROR] Errore: {e}\n")
        return None, 0

def main():
    # Directory da processare
    static_images = Path('home/static/home/images')

    print("=" * 70)
    print("Conversione immagini in WebP")
    print("=" * 70)
    print()

    # Trova tutte le immagini PNG e JPG
    image_extensions = ['*.png', '*.jpg', '*.jpeg', '*.PNG', '*.JPG', '*.JPEG']
    all_images = []

    for ext in image_extensions:
        all_images.extend(static_images.rglob(ext))

    print(f"Trovate {len(all_images)} immagini da convertire\n")

    total_savings = 0
    converted_count = 0

    for img_path in all_images:
        # Salta se esiste già il WebP
        webp_path = img_path.with_suffix('.webp')
        if webp_path.exists():
            print(f"[SKIP] {img_path.name} (WebP già esistente)")
            continue

        print(f"[CONVERTING] {img_path.relative_to(static_images)}")

        # Converti
        result, savings = convert_to_webp(img_path)

        if result:
            total_savings += savings
            converted_count += 1

    print("=" * 70)
    print(f"Conversione completata!")
    print(f"  Immagini convertite: {converted_count}")
    print(f"  Risparmio totale: {total_savings / 1024 / 1024:.2f} MB")
    print("=" * 70)

if __name__ == '__main__':
    main()
