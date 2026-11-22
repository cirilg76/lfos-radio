#!/usr/bin/env python3
"""Petit serveur web pour réécouter les enregistrements de la fréquence LFOS.

Les fichiers sont produits par rtl_airband dans
  recordings/AAAA/MM/JJ/LFOS_AAAAMMJJ_HHMMSS.mp3
"""
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import urlopen

BASE = Path(__file__).resolve().parent
REC_DIR = Path(os.environ.get("LFOS_REC_DIR", BASE.parent / "recordings")).resolve()
PORT = int(os.environ.get("LFOS_WEB_PORT", "8080"))
CACHE_FILE = REC_DIR / ".durees.json"
NAME_RE = re.compile(r"_(\d{8})_(\d{6})\.mp3$")

_lock = threading.Lock()
_cache = {}


def load_cache():
    global _cache
    try:
        _cache = json.loads(CACHE_FILE.read_text())
    except Exception:
        _cache = {}


def save_cache():
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_cache))
    tmp.replace(CACHE_FILE)


def duration_of(path: Path) -> float:
    """Durée en secondes (ffprobe), mise en cache par chemin + taille."""
    st = path.stat()
    key = str(path.relative_to(REC_DIR))
    sig = f"{st.st_size}:{int(st.st_mtime)}"
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=10).stdout.strip()
        dur = round(float(out), 1)
    except Exception:
        dur = 0.0
    with _lock:
        _cache[key] = [sig, dur]
    return dur


def transcript_of(path: Path):
    """Texte écrit par transcribe.py, ou None si pas encore transcrit."""
    try:
        return json.loads(path.with_suffix(".json").read_text()).get("text", "")
    except FileNotFoundError:
        return None
    except Exception:
        return ""


ICECAST = os.environ.get("LFOS_ICECAST", "http://127.0.0.1:8000")
STATS_FILE = Path(os.environ.get("LFOS_STATS", BASE.parent / "stats.txt"))
STAT_RE = re.compile(r"^(\w+)\{[^}]*\}\s+(\S+)$", re.M)
_status = {"t": 0, "data": None}


def service_state(name: str) -> str:
    try:
        return subprocess.run(["systemctl", "is-active", name], capture_output=True,
                              text=True, timeout=5).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def receiver_status():
    """État du récepteur, de la diffusion et de la transcription (mis en cache 3 s)."""
    now = time.time()
    if _status["data"] and now - _status["t"] < 3:
        return _status["data"]

    rx = {"service": service_state("lfos-airband"), "stats_age": None}
    try:
        st = STATS_FILE.stat()
        vals = {k: float(v) for k, v in STAT_RE.findall(STATS_FILE.read_text())}
        rx.update({
            "stats_age": round(now - st.st_mtime),
            "noise_dbfs": vals.get("channel_dbfs_noise_level"),
            "signal_dbfs": vals.get("channel_dbfs_signal_level"),
            "squelch_open": vals.get("channel_signal_level", 0) > vals.get("channel_squelch_level", 1e9),
            "openings": int(vals.get("channel_squelch_counter", 0)),
            "overflows": int(vals.get("buffer_overflow_count", 0)),
        })
    except Exception:
        pass

    stream = {"online": False, "listeners": 0}
    try:
        with urlopen(ICECAST + "/status-json.xsl", timeout=2) as r:
            src = json.load(r)["icestats"].get("source", [])
        for s in src if isinstance(src, list) else [src]:
            if s.get("listenurl", "").endswith("/lfos"):
                stream = {"online": True, "listeners": s.get("listeners", 0)}
    except Exception:
        pass

    last = None
    newest = max(REC_DIR.glob("*/*/*/*.mp3"), key=lambda p: p.name, default=None)
    if newest and (m := NAME_RE.search(newest.name)):
        d, t = m.groups()
        last = f"{d[:4]}-{d[4:6]}-{d[6:]}T{t[:2]}:{t[2:4]}:{t[4:]}"
    queue = sum(1 for f in REC_DIR.glob("*/*/*/*.mp3") if not f.with_suffix(".json").exists())

    data = {"receiver": rx, "stream": stream, "last_recording": last,
            "transcription": {"service": service_state("lfos-transcribe"), "queue": queue}}
    _status.update(t=now, data=data)
    return data


def list_days():
    days = {}
    for f in REC_DIR.glob("*/*/*/*.mp3"):
        m = NAME_RE.search(f.name)
        if m:
            d = m.group(1)
            days[d] = days.get(d, 0) + 1
    return [{"day": f"{d[:4]}-{d[4:6]}-{d[6:]}", "count": n}
            for d, n in sorted(days.items(), reverse=True)]


def list_day(day: str):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return []
    y, m, d = day.split("-")
    folder = REC_DIR / y / m / d
    items = []
    for f in sorted(folder.glob("*.mp3")):
        mm = NAME_RE.search(f.name)
        if not mm:
            continue
        t = mm.group(2)
        items.append({
            "time": f"{t[:2]}:{t[2:4]}:{t[4:]}",
            "url": "/rec/" + str(f.relative_to(REC_DIR)),
            "duration": duration_of(f),
            "text": transcript_of(f),
        })
    with _lock:
        save_cache()
    return items


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(BASE / "static"), **kw)

    def log_message(self, *a):
        pass

    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/days":
            return self.send_json(list_days())
        if path == "/api/status":
            return self.send_json(receiver_status())
        if path == "/live":
            return self.relay_live()
        if path.startswith("/api/day/"):
            return self.send_json(list_day(path[len("/api/day/"):]))
        if path.startswith("/rec/"):
            target = (REC_DIR / path[len("/rec/"):]).resolve()
            if REC_DIR not in target.parents or target.suffix != ".mp3" or not target.is_file():
                return self.send_error(404)
            return self.send_file(target)
        return super().do_GET()

    def relay_live(self):
        """Relaie le flux Icecast sur le port de la page (un seul port à ouvrir)."""
        try:
            upstream = urlopen(ICECAST + "/lfos", timeout=10)
        except Exception:
            return self.send_error(503, "Flux direct indisponible")
        with upstream:
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while chunk := upstream.read(2048):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                pass  # l'auditeur a fermé la page ou coupé le direct

    def send_file(self, target: Path):
        size = target.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            else:
                start = max(0, size - int(m.group(2)))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(target, "rb") as fh:
            fh.seek(start)
            self.wfile.write(fh.read(end - start + 1))


if __name__ == "__main__":
    REC_DIR.mkdir(parents=True, exist_ok=True)
    load_cache()
    print(f"{datetime.now():%F %T} LFOS web : http://0.0.0.0:{PORT}  (enregistrements : {REC_DIR})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
