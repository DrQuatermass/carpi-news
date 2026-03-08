#!/usr/bin/env python
"""
Genera portico_logo_email.png (bianco, landscape) dal SVG originale.
Richiede: pip install cairosvg pillow
Eseguire sul server Linux: python generate_email_logo.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

import cairosvg
from PIL import Image
import numpy as np

svg_path = 'carpi_news/home/static/home/images/portico_logo.svg'
out_path = 'carpi_news/home/static/home/images/portico_logo_email.png'

# Converti SVG in PNG (scale=2 per qualità sufficiente, output ~3214x338 px)
cairosvg.svg2png(url=svg_path, write_to=out_path, scale=2)

# Rendi tutti i pixel visibili bianchi (inverte il logo scuro)
img = Image.open(out_path).convert('RGBA')
data = np.array(img)
mask = data[:,:,3] > 10
data[mask, 0] = 255
data[mask, 1] = 255
data[mask, 2] = 255
Image.fromarray(data).save(out_path)

print(f'OK: {Image.open(out_path).size}')
print(f'Salvato in: {out_path}')
print('Ora esegui: python carpi_news/manage.py collectstatic --noinput')
