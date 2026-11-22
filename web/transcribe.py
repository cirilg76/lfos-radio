#!/usr/bin/env python3
"""Transcription automatique des enregistrements LFOS (Whisper, local, CPU).

Pour chaque recordings/.../LFOS_AAAAMMJJ_HHMMSS.mp3 sans transcription, écrit
à côté un fichier LFOS_AAAAMMJJ_HHMMSS.json : {"text": "...", "model": "..."}.
Les plus récents sont traités en premier, pour suivre le trafic en direct.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

BASE = Path(__file__).resolve().parent
REC_DIR = Path(os.environ.get("LFOS_REC_DIR", BASE.parent / "recordings")).resolve()
MODEL = os.environ.get("LFOS_WHISPER_MODEL", "medium")
THREADS = int(os.environ.get("LFOS_WHISPER_THREADS", "3"))
PROMPT = "Saint-Valery Vittefleur."
NAME_RE = re.compile(r"^LFOS_\d{8}_\d{6}\.mp3$")
MIN_AGE = 5          # s : on attend que rtl_airband ait fini d'écrire le fichier
MIN_DURATION = 0.6   # s : en dessous, c'est un parasite, pas une phrase

# Phrases que Whisper « invente » sur du bruit ou du silence
HALLUCINATIONS = re.compile(
    r"sous-titr|amara\.org|merci d'avoir regard|abonnez-vous|radio-canada|"
    r"merci de votre attention|^\W*(merci|musique)\W*$", re.I)


def log(msg):
    print(f"{datetime.now():%F %T} {msg}", flush=True)


def load_audio(path: Path):
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
         "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True, check=True, timeout=60).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def clean(text: str) -> str:
    text = " ".join(text.split())
    if HALLUCINATIONS.search(text) or text.strip(" .") == PROMPT.strip(" ."):
        return ""
    return text


def pending():
    now = time.time()
    out = []
    for f in REC_DIR.glob("*/*/*/*.mp3"):
        if not NAME_RE.match(f.name) or f.with_suffix(".json").exists():
            continue
        try:
            if now - f.stat().st_mtime < MIN_AGE:
                continue
        except FileNotFoundError:
            continue
        out.append(f)
    return sorted(out, key=lambda p: p.name, reverse=True)


def write_result(mp3: Path, text: str):
    side = mp3.with_suffix(".json")
    tmp = side.with_suffix(".tmp")
    tmp.write_text(json.dumps({"text": text, "model": MODEL}, ensure_ascii=False))
    tmp.replace(side)


def main():
    try:
        os.nice(10)  # laisse la priorité à la réception radio
    except OSError:
        pass
    log(f"chargement du modèle Whisper « {MODEL} »…")
    model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=THREADS)
    log(f"prêt — surveillance de {REC_DIR}")
    while True:
        todo = pending()
        if not todo:
            time.sleep(10)
            continue
        mp3 = todo[0]
        t0 = time.time()
        try:
            audio = load_audio(mp3)
            if len(audio) < MIN_DURATION * 16000:
                text = ""
            else:
                segs, _ = model.transcribe(
                    audio, language="fr", beam_size=5, vad_filter=True,
                    initial_prompt=PROMPT, condition_on_previous_text=False)
                text = clean(" ".join(s.text.strip() for s in segs))
        except Exception as e:  # fichier abîmé, etc. : on note et on passe
            log(f"erreur sur {mp3.name} : {e}")
            text = ""
        if mp3.exists():
            write_result(mp3, text)
        log(f"{mp3.name} ({time.time() - t0:.0f} s, reste {len(todo) - 1}) : {text or '—'}")


if __name__ == "__main__":
    sys.exit(main())
