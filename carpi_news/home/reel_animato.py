"""
Reel animato: stesso impianto grafico di home.facebook_reels, ma il video si muove.

- la foto non viene ritagliata: se e' larga scorre da sinistra a destra, se e' alta
  dall'alto in basso; se e' quasi quadrata o troppo piccola si avvicina soltanto;
- sotto la foto compaiono il titolo e poi tre punti chiave (testo grigio che l'inchiostro percorre),
  cosi' chi guarda ha la notizia intera senza aprire l'articolo;
- una barra a segmenti sotto la foto mostra a che punto si e'.

I punti li scrive il modello degli articoli (ANTHROPIC_MODEL) (APIUsage operation `reel_punti`); senza
chiave API o se la chiamata fallisce si usano le prime frasi del sommario.

Dal 19/11/2026 e' il video di Storie e Reel di Facebook e Instagram (REEL_ANIMATO=False
per tornare al reel fermo). I punti si salvano in Articolo.reel_punti, correggibili dall'admin.
    python manage.py generate_test_reel --animato [--ultimi 5 | --id N | --slug S]
"""

from __future__ import annotations

import copy
import json
import logging
import re
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.utils.html import strip_tags
from PIL import Image, ImageChops, ImageDraw

from home.facebook_reels import (
    CARD_Y, CARTA, HEIGHT, INCHIOSTRO, LOGO_H, LOGO_Y, VINO, WIDTH, ZONA_COPERTA_BASSO,
    FacebookReelGenerator, _ffmpeg_binary, _reels_output_dir,
)

logger = logging.getLogger(__name__)

# Haiku 4.5 sbagliava i fatti in una frase su sei (minuti inventati, colpevolezza data per certa):
# i punti li scrive il modello degli articoli, settings.ANTHROPIC_MODEL (Sonnet 5)
MAX_CARATTERI_PUNTO = 95

# Impaginazione: il pulsante non sta piu' sotto ogni testo ma solo nella schermata finale,
# quindi la foto torna grande come nel reel fermo e il testo ha tutta la fascia fino alla
# zona coperta dall'interfaccia del social
LATO_FOTO = 820
BARRA_Y = CARD_Y + LATO_FOTO + 16
BARRA_H = 6
BADGE_Y = BARRA_Y + BARRA_H + 22
ZOOM_FINALE = 1.16                # foto quasi quadrata: solo avvicinamento
ZOOM_SCORRENDO = 1.06             # foto larga o alta: scorre tutta, con un filo di zoom
SCORRE_DA = 1.15                  # rapporto tra i lati da cui la foto scorre
LATO_MINIMO_PER_SCORRERE = 400    # px del lato corto: sotto, la foto e' troppo sgranata per scorrerla
CARATTERI_AL_SECONDO = 55         # testo "lettere"
PAROLE_AL_SECONDO = 4             # testo "parole"
FPS_ANIMATO = 30                  # piu' fotogrammi del reel fermo: scorrimento e dissolvenze piu' fluidi
# Modi morbidi: niente compare di colpo
SFUMA_PAROLE_AL_SECONDO = 5       # "sfuma": ogni parola entra in dissolvenza salendo di poco
SFUMA_DURATA = 0.40
RIGHE_INTERVALLO = 0.50           # "righe": una riga alla volta, in dissolvenza
RIGHE_DURATA = 0.55
EVIDENZIA_PAROLE_AL_SECONDO = 3.5 # "evidenzia": testo grigio subito, l'inchiostro lo percorre a ritmo di lettura
EVIDENZIA_PAUSA = 1.5             # secondi a testo tutto evidenziato prima di cambiare schermata
EVIDENZIA_SFUMATURA = 90          # px del bordo morbido dell'inchiostro
GRIGIO_TESTO = (168, 166, 158)
MODI_MORBIDI = ("sfuma", "righe", "evidenzia")
SECONDI_TITOLO = 3.0              # durata minima della scena del titolo
SECONDI_PUNTO = 4.0               # durata minima di ogni punto
SECONDI_FINALE = 2.5              # schermata finale con il pulsante
SECONDI_LETTURA = 1.8             # tempo a testo fermo dopo l'ultima parola scritta
ENTRATA, USCITA = 0.35, 0.50      # secondi di comparsa e scomparsa del testo
BARRA_VUOTA = (221, 217, 207)

PROMPT_PUNTI = """Sei il redattore social di un giornale locale. Da questo articolo ricava 3 punti \
per un video verticale: tre frasi brevi che, lette una dopo l'altra dopo il titolo, danno la notizia \
completa a chi non aprira' l'articolo.

Regole:
- ogni punto e' UNA frase di 8-14 parole, mai oltre {max_car} caratteri spazi compresi: \
si legge in 4 secondi su un telefono. Un solo fatto per punto, senza incisi e subordinate;
- solo fatti scritti nell'articolo, con nomi, luoghi, date e cifre esatti;
- il titolo e' gia' sullo schermo: il primo punto parte da quello che il titolo non dice \
(quando, dove, quanto), poi le conseguenze pratiche per chi legge;
- non aggiungere precisazioni tue (per esempio "del secondo tempo", "in casa") se l'articolo non le scrive;
- cronaca giudiziaria: chi e' indagato o arrestato non e' colpevole. Scrivi "e' accusato di", "e' stato arrestato per", mai che ha commesso il fatto;
- niente emoji, hashtag, domande, inviti a leggere o a scoprire.

Rispondi solo con JSON: {{"punti": ["...", "...", "..."]}}

TITOLO: {titolo}

SOMMARIO: {sommario}

TESTO: {testo}"""


# -----------------------------------------------------------------------------
# PUNTI CHIAVE
# -----------------------------------------------------------------------------
def _pulisci(testo: str) -> str:
    return re.sub(r'\s+', ' ', strip_tags(testo or '')).strip()


def punti_dal_sommario(articolo, quanti: int = 3) -> list[str]:
    """Ripiego senza AI: le prime frasi del sommario (o del testo) che stanno nella misura."""
    testo = _pulisci(articolo.sommario) or _pulisci(articolo.contenuto)
    frasi = [f.strip() for f in re.split(r'(?<=[.!?])\s+', testo) if f.strip()]
    return [f for f in frasi if 25 <= len(f) <= MAX_CARATTERI_PUNTO + 20][:quanti]


def punti_per(articolo) -> list[str]:
    """Punti del reel di un articolo: quelli salvati (scritti a mano o da un reel precedente),
    altrimenti scritti ora dall'AI e salvati, cosi' Facebook e Instagram mostrano le stesse frasi
    e l'AI viene chiamata una volta sola per articolo."""
    salvati = [r.strip() for r in (getattr(articolo, "reel_punti", "") or "").splitlines() if r.strip()]
    if salvati:
        return salvati[:3]
    if not getattr(settings, 'ANTHROPIC_API_KEY', ''):
        return punti_dal_sommario(articolo)
    punti = punti_chiave(articolo, ripiego=False)
    if not punti:
        return punti_dal_sommario(articolo)
    if articolo.pk:
        # update() e non save(): niente segnali di salvataggio (immagini, social) per un campo di servizio
        type(articolo).objects.filter(pk=articolo.pk).update(reel_punti="\n".join(punti))
        articolo.reel_punti = "\n".join(punti)
    return punti


def punti_chiave(articolo, ripiego: bool = True) -> list[str]:
    """Tre punti chiave scritti dall'AI; prime frasi del sommario se l'AI non e' disponibile."""
    if not getattr(settings, 'ANTHROPIC_API_KEY', ''):
        return punti_dal_sommario(articolo) if ripiego else []
    try:
        import anthropic
        from home.anthropic_params import anthropic_model, response_text, thinking_params
        from home.api_usage_tracker import APIUsageTracker

        modello = anthropic_model()
        prompt = PROMPT_PUNTI.format(
            max_car=MAX_CARATTERI_PUNTO,
            titolo=articolo.titolo,
            sommario=_pulisci(articolo.sommario)[:800],
            testo=_pulisci(articolo.contenuto)[:5000],
        )
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        messaggi = [{'role': 'user', 'content': prompt}]
        punti = []
        for _ in range(2):          # una seconda richiesta se i punti escono troppo lunghi
            risposta = client.messages.create(model=modello, max_tokens=2000, messages=messaggi,
                                              **thinking_params('low'))
            try:
                APIUsageTracker.track_anthropic('reel_punti', modello, risposta.usage.input_tokens,
                                                risposta.usage.output_tokens,
                                                related_article=articolo if articolo.pk else None)
            except Exception as e:
                logger.warning("Tracking costi reel_punti fallito: %s", e)
            testo_risposta = response_text(risposta)
            m = re.search(r'\{.*\}', testo_risposta, re.DOTALL)
            punti = [str(p).strip() for p in json.loads(m.group(0)).get('punti', []) if str(p).strip()][:3]
            lunghi = [p for p in punti if len(p) > MAX_CARATTERI_PUNTO]
            if punti and not lunghi:
                break
            messaggi += [
                {'role': 'assistant', 'content': testo_risposta},
                {'role': 'user', 'content': (
                    f"Troppo lunghi: {', '.join(str(len(p)) for p in punti)} caratteri. Riscrivi i tre punti "
                    f"sotto i {MAX_CARATTERI_PUNTO} caratteri ciascuno, togliendo i dettagli secondari. Solo JSON.")},
            ]
        if punti:
            return punti
    except Exception as e:
        logger.warning("Reel animato: punti chiave AI non riusciti (%s), uso il sommario", e)
    return punti_dal_sommario(articolo) if ripiego else []


# -----------------------------------------------------------------------------
# GENERATORE
# -----------------------------------------------------------------------------
class ReelAnimatoGenerator(FacebookReelGenerator):
    """MP4 verticale 1080x1920 con foto in movimento, titolo e punti chiave in sequenza."""

    # "sfuma" | "righe" | "evidenzia" (morbidi) | "parole" | "lettere" (a scatti) | "dissolvenza"
    testo = "evidenzia"         # scelta del 19/11/2026 dopo il confronto sui video di prova

    def generate(self, articolo, punti: Optional[list[str]] = None, riusa: bool = True) -> Optional[str]:
        """Reel animato dell'articolo. Con REEL_ANIMATO=False, o se qualcosa va storto, il reel
        fermo di FacebookReelGenerator: la pubblicazione non si ferma per un video.

        `riusa`: come il reel fermo, un file dello stesso articolo generato da meno di
        GENERATED_REUSE_TTL_SECONDS non si rifa' (Storia e Reel Instagram usano lo stesso MP4)."""
        if not getattr(settings, "REEL_ANIMATO", True):
            return super().generate(articolo)
        try:
            output_mp4 = _reels_output_dir(self.config.output_dir_name) / f"{articolo.slug}.mp4"
            if riusa and output_mp4.exists():
                if time.time() - output_mp4.stat().st_mtime <= self.GENERATED_REUSE_TTL_SECONDS:
                    logger.info(f"Reel animato: riuso {output_mp4.name}")
                    return str(output_mp4)

            image_path = self._resolve_image_path(articolo)
            if not image_path:
                logger.warning(f"Reel animato: nessuna immagine valida per '{articolo.titolo}'")
                return None
            if punti is None:
                punti = punti_per(articolo)
            if not punti:
                logger.warning(f"Reel animato: nessun punto chiave per '{articolo.titolo}', uso il reel fermo")
                return super().generate(articolo)

            # I gestori (reel_manager, ig_reel_manager...) tengono un solo generatore per tutti gli
            # articoli e le pubblicazioni girano in thread: durata e fotogrammi stanno su una copia
            copia = copy.copy(self)
            copia._durate = [copia._durata_scena(articolo.titolo, SECONDI_TITOLO)]
            copia._durate += [copia._durata_scena(p, SECONDI_PUNTO) for p in punti]
            copia._durate.append(SECONDI_FINALE)
            copia.config = replace(self.config, duration_seconds=sum(copia._durate), fps=FPS_ANIMATO)

            inizio = time.time()
            with tempfile.TemporaryDirectory(prefix="reel_") as tmpdir:
                audio_path = copia._prepare_audio(out_dir=Path(tmpdir))
                copia._render(image_path, articolo.titolo, articolo.categoria or "Notizie",
                              punti, audio_path, output_mp4, Path(tmpdir))
            logger.info(f"Reel animato generato: {output_mp4} ({output_mp4.stat().st_size // 1024} KB, "
                        f"{copia.config.duration_seconds:.0f}s di video in {time.time() - inizio:.0f}s)")
            return str(output_mp4)
        except Exception as e:
            logger.error(f"Reel animato: errore per '{articolo.titolo}': {e}. Uso il reel fermo", exc_info=True)
            return super().generate(articolo)

    def _durata_scena(self, testo: str, minimo: float) -> float:
        """Il tempo di scrivere il testo piu' quello di rileggerlo fermo, mai sotto `minimo`."""
        parole = len(testo.split())
        if self.testo == "sfuma":
            scrittura = parole / SFUMA_PAROLE_AL_SECONDO + SFUMA_DURATA
        elif self.testo == "righe":
            scrittura = max(1, -(-len(testo) // 30)) * RIGHE_INTERVALLO + RIGHE_DURATA
        elif self.testo == "evidenzia":
            # finito di evidenziare il testo resta fermo EVIDENZIA_PAUSA, poi sfuma in USCITA
            return round(max(minimo, parole / EVIDENZIA_PAROLE_AL_SECONDO + 0.5 + EVIDENZIA_PAUSA + USCITA), 2)
        elif self.testo == "parole":
            scrittura = parole / PAROLE_AL_SECONDO
        elif self.testo == "lettere":
            scrittura = len(testo) / CARATTERI_AL_SECONDO
        else:
            return minimo
        return round(max(minimo, scrittura + SECONDI_LETTURA), 2)

    # --- pezzi fermi ---------------------------------------------------------
    def _fondo(self, category: str) -> tuple[Image.Image, int, int]:
        """Fondo con logo ed etichetta. Restituisce anche i limiti della zona del testo."""
        layer = Image.new("RGBA", (WIDTH, HEIGHT), CARTA + (255,))
        draw = ImageDraw.Draw(layer)
        logo = self._make_logo(target_height=LOGO_H)
        layer.alpha_composite(logo, ((WIDTH - logo.size[0]) // 2, LOGO_Y))
        bh = self._draw_badge(draw, category, BADGE_Y)
        zona_su = BADGE_Y + bh + 30
        zona_giu = HEIGHT - ZONA_COPERTA_BASSO - 20
        return layer.convert("RGB"), zona_su, zona_giu

    def _scena_finale(self, zona_su: int, altezza: int) -> dict:
        """Ultima schermata: solo il pulsante, al centro della zona del testo."""
        layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        n_righe = len([r for r in self.config.cta_text.splitlines() if r.strip()]) or 1
        alto_pulsante = n_righe * 54 + 40
        # _draw_cta mette il pulsante 30 px sotto la quota che riceve
        self._draw_cta(layer, draw, zona_su + (altezza - alto_pulsante) // 2 - 30)
        return {"finale": True, "layer": layer.crop((0, zona_su, WIDTH, zona_su + altezza))}

    def _foto(self, image_path: Path) -> tuple[Image.Image, bool]:
        """Foto intera (nessun ritaglio), con il lato corto un po' piu' grande del riquadro,
        e se e' abbastanza grande da poterla scorrere."""
        img = Image.open(image_path).convert("RGB")
        iw, ih = img.size
        scala = LATO_FOTO * 1.25 / min(iw, ih)
        foto = img.resize((max(1, round(iw * scala)), max(1, round(ih * scala))), Image.LANCZOS)
        return foto, min(iw, ih) >= LATO_MINIMO_PER_SCORRERE

    @staticmethod
    def _finestra(foto: Image.Image, p: float, grande: bool = True) -> tuple:
        """Coefficienti della finestra quadrata sulla foto al punto `p` (0-1) del video.

        Foto larga (o alta): la finestra scorre da sinistra a destra (o dall'alto in basso),
        cosi' si vede tutta. Foto quasi quadrata: non c'e' niente da scorrere, ci si avvicina.
        Foto piccola: ingrandita e' sgranata, quindi resta il quadrato centrale quasi fermo."""
        fw, fh = foto.size
        corto, lungo = min(fw, fh), max(fw, fh)
        scorre = grande and lungo / corto >= SCORRE_DA
        zoom = ZOOM_SCORRENDO if (scorre or not grande) else ZOOM_FINALE
        lato = corto / (1 + (zoom - 1) * p)
        centro_lungo = lato / 2 + (lungo - lato) * p if scorre else lungo / 2
        cx, cy = (centro_lungo, fh / 2) if fw >= fh else (fw / 2, centro_lungo)
        a = lato / LATO_FOTO
        return (a, 0, cx - lato / 2, 0, a, cy - lato / 2)

    def _scena(self, testo: str, altezza: int, misure: tuple, max_righe: int) -> dict:
        """Testo centrato nella zona, nel corpo piu' grande che sta in `max_righe` righe."""
        for size in misure:
            font = self._load_font(size)
            righe = self._wrap(testo, font, max_width=WIDTH - 120)
            if len(righe) <= max_righe and int(size * 1.27) * len(righe) <= altezza:
                break
        if len(righe) > max_righe:
            righe = righe[:max_righe]
            righe[-1] = righe[-1].rstrip(".,;:") + "..."
        interlinea = int(size * 1.27)
        misura = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        y = max(0, (altezza - interlinea * len(righe)) // 2)
        posizioni = []
        for riga in righe:
            bbox = misura.textbbox((0, 0), riga, font=font)
            posizioni.append((riga, (WIDTH - (bbox[2] - bbox[0])) // 2, y))
            y += interlinea
        # dove finisce ogni parola, contando i caratteri come li conta _testo (riga dopo riga)
        fine_parole, base = [], 0
        for riga in righe:
            pos = 0
            for parola in riga.split(" "):
                pos += len(parola)
                fine_parole.append(base + pos)
                pos += 1
            base += len(riga)
        scena = {"righe": posizioni, "font": font, "altezza": altezza, "interlinea": interlinea,
                 "caratteri": sum(len(r) for r in righe), "fine_parole": fine_parole}
        scena["layer"] = self._testo(scena, scena["caratteri"])
        # per i modi morbidi: posto di ogni parola, larghezza di ogni riga
        scena["parole"] = []
        scena["larghezze"] = []
        for n_riga, (riga, x, y) in enumerate(posizioni):
            scena["larghezze"].append(font.getlength(riga))
            pos = 0
            for parola in riga.split(" "):
                scena["parole"].append((parola, x + font.getlength(riga[:pos]), y, n_riga))
                pos += len(parola) + 1
        return scena

    @staticmethod
    def _morbido(x: float) -> float:
        """0-1 con partenza e arrivo dolci."""
        x = min(1.0, max(0.0, x))
        return x * x * (3 - 2 * x)

    def _strati_morbidi(self, scena: dict, tau: float) -> list:
        """Strati (colore, maschera) del testo al secondo `tau` della scena, per i modi morbidi."""
        dim = (WIDTH, scena["altezza"])
        font = scena["font"]
        if self.testo == "evidenzia":
            pieno = scena["layer"].getchannel("A")
            entrata = self._morbido(tau / 0.45)
            grigio = pieno if entrata >= 1 else pieno.point(lambda v, f=entrata: int(v * f))
            # l'inchiostro avanza in modo continuo lungo le righe, con il bordo sfumato
            totale = sum(scena["larghezze"])
            velocita = totale / max(0.5, len(scena["parole"]) / EVIDENZIA_PAROLE_AL_SECONDO)
            fatto = max(0.0, tau - 0.3) * velocita
            tenda = Image.new("L", dim, 0)
            draw = ImageDraw.Draw(tenda)
            for (riga, x, y), larghezza in zip(scena["righe"], scena["larghezze"]):
                r = min(fatto, larghezza + EVIDENZIA_SFUMATURA)
                fatto -= larghezza
                if r <= 0:
                    break
                y1 = y + scena["interlinea"]
                pieno_fino = x + r - EVIDENZIA_SFUMATURA
                if pieno_fino > x - 20:
                    draw.rectangle([(x - 20, y), (pieno_fino, y1)], fill=255)
                for i in range(0, EVIDENZIA_SFUMATURA, 3):
                    xs = pieno_fino + i
                    if xs >= x - 20:
                        draw.rectangle([(xs, y), (xs + 3, y1)],
                                       fill=int(255 * (1 - self._morbido(i / EVIDENZIA_SFUMATURA))))
            return [(GRIGIO_TESTO, grigio), (INCHIOSTRO, ImageChops.multiply(pieno, tenda))]

        maschera = Image.new("L", dim, 0)
        draw = ImageDraw.Draw(maschera)
        if self.testo == "righe":
            for n, (riga, x, y) in enumerate(scena["righe"]):
                a = self._morbido((tau - n * RIGHE_INTERVALLO) / RIGHE_DURATA)
                if a > 0:
                    draw.text((x, y + (1 - a) * 22), riga, font=font, fill=int(255 * a))
        else:   # sfuma
            for n, (parola, x, y, _) in enumerate(scena["parole"]):
                a = self._morbido((tau - n / SFUMA_PAROLE_AL_SECONDO) / SFUMA_DURATA)
                if a > 0:
                    draw.text((x, y + (1 - a) * 12), parola, font=font, fill=int(255 * a))
        return [(INCHIOSTRO, maschera)]

    @staticmethod
    def _testo(scena: dict, quanti: int) -> Image.Image:
        """I primi `quanti` caratteri della scena. Ogni riga parte gia' dal suo posto
        definitivo, quindi le lettere scritte non si spostano mentre arrivano le altre."""
        layer = Image.new("RGBA", (WIDTH, scena["altezza"]), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for riga, x, y in scena["righe"]:
            if quanti <= 0:
                break
            draw.text((x, y), riga[:quanti], font=scena["font"], fill=INCHIOSTRO + (255,))
            quanti -= len(riga)
        return layer

    # --- video ---------------------------------------------------------------
    def _render(self, image_path: Path, title: str, category: str, punti: list[str],
                audio_path: Path, output_path: Path, tmp: Path) -> None:
        cfg = self.config
        durata = float(cfg.duration_seconds)
        n_frame = int(durata * cfg.fps)

        fondo, zona_su, zona_giu = self._fondo(category)
        altezza = zona_giu - zona_su
        foto, grande = self._foto(image_path)
        maschera = Image.new("L", (LATO_FOTO, LATO_FOTO), 0)
        ImageDraw.Draw(maschera).rounded_rectangle([(0, 0), (LATO_FOTO, LATO_FOTO)], radius=8, fill=255)
        foto_x = (WIDTH - LATO_FOTO) // 2

        # scene: titolo, poi i punti che si dividono il tempo rimasto
        scene = [(self._scena(title, altezza, (68, 62, 58, 54, 50), 4), self._durate[0] if punti else durata)]
        for p, d in zip(punti, self._durate[1:]):
            scene.append((self._scena(p, altezza, (62, 58, 54, 50, 46), 4), d))
        if punti:
            scene.append((self._scena_finale(zona_su, altezza), self._durate[-1]))
        inizi, t0 = [], 0.0
        for _, d in scene:
            inizi.append(t0)
            t0 += d

        # barra a segmenti, larga quanto la foto
        vuoto = 10
        seg_w = (LATO_FOTO - vuoto * (len(scene) - 1)) / len(scene)

        log_ffmpeg = open(tmp / "ffmpeg.log", "w+", encoding="utf-8", errors="replace")
        cmd = [
            _ffmpeg_binary(), "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(cfg.fps), "-i", "-",
            "-i", str(audio_path),
            "-t", str(durata),
            "-af", f"afade=t=in:st=0:d=0.5,afade=t=out:st={max(0, durata - 2)}:d=2",
            "-c:v", "libx264", "-preset", cfg.preset, "-crf", str(cfg.crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", cfg.audio_bitrate,
            "-movflags", "+faststart", "-shortest",
            str(output_path),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log_ffmpeg, stderr=log_ffmpeg)
        try:
            for i in range(n_frame):
                t = i / cfg.fps
                frame = fondo.copy()

                # foto: scorre da un capo all'altro (o si avvicina, se e' quasi quadrata)
                riquadro = foto.transform((LATO_FOTO, LATO_FOTO), Image.AFFINE,
                                          self._finestra(foto, i / max(1, n_frame - 1), grande),
                                          resample=Image.BICUBIC)
                frame.paste(riquadro, (foto_x, CARD_Y), maschera)

                # scena in corso
                k = max(j for j, s in enumerate(inizi) if t >= s)
                scena, dur = scene[k]
                layer = scena["layer"]
                tau = t - inizi[k]
                alpha, dy = 1.0, 0
                if k < len(scene) - 1 and dur - tau < USCITA:
                    alpha = max(0.0, (dur - tau) / USCITA)
                if scena.get("finale"):
                    alpha = self._morbido(tau / 0.6)
                elif self.testo in MODI_MORBIDI:
                    for colore, maschera_testo in self._strati_morbidi(scena, tau):
                        if alpha < 1:
                            maschera_testo = maschera_testo.point(lambda v, f=alpha: int(v * f))
                        frame.paste(colore, (0, zona_su, WIDTH, zona_su + altezza), maschera_testo)
                    layer = None
                elif self.testo == "parole":
                    n = int(tau * PAROLE_AL_SECONDO) + 1
                    if n < len(scena["fine_parole"]):
                        layer = self._testo(scena, scena["fine_parole"][n - 1])
                elif self.testo == "lettere":
                    scritti = int(tau * CARATTERI_AL_SECONDO) + 1
                    if scritti < scena["caratteri"]:
                        layer = self._testo(scena, scritti)
                elif k > 0 and tau < ENTRATA:
                    e = 1 - (1 - tau / ENTRATA) ** 3          # rallenta arrivando
                    alpha, dy = e, int((1 - e) * 36)
                if layer is not None:
                    trasparenza = layer.getchannel("A")
                    if alpha < 1:
                        trasparenza = trasparenza.point(lambda v, f=alpha: int(v * f))
                    frame.paste(layer.convert("RGB"), (0, zona_su + dy), trasparenza)

                # barra di avanzamento
                draw = ImageDraw.Draw(frame)
                for j, (_, d) in enumerate(scene):
                    x0 = foto_x + j * (seg_w + vuoto)
                    draw.rectangle([(x0, BARRA_Y), (x0 + seg_w, BARRA_Y + BARRA_H)], fill=BARRA_VUOTA)
                    pieno = min(1.0, max(0.0, (t - inizi[j]) / d))
                    if pieno > 0:
                        draw.rectangle([(x0, BARRA_Y), (x0 + seg_w * pieno, BARRA_Y + BARRA_H)], fill=VINO)

                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            codice = proc.wait(timeout=180)
        except Exception:
            proc.kill()
            raise
        finally:
            log_ffmpeg.seek(0)
            coda = log_ffmpeg.read()[-2000:]
            log_ffmpeg.close()
        if codice != 0:
            logger.error(f"Reel animato: ffmpeg failed:\n{coda}")
            raise RuntimeError(f"ffmpeg encoding fallito (exit {codice})")
