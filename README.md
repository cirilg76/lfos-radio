# LFOS 119.508 — écoute, enregistrement et transcription

Écoute de la fréquence de l'aérodrome de **Saint-Valery – Vittefleur (LFOS)**, 119.508 MHz (canal 8.33 kHz « 119.510 »), avec un **SDRplay RSP1A** sur un petit serveur Linux.

- **Enregistrement** de chaque transmission en MP3 (squelch automatique) par [RTLSDR-Airband](https://github.com/charlie-foxtrot/RTLSDR-Airband) ;
- **Écoute en direct** via Icecast, relayée par la page web ;
- **Transcription automatique** en français avec [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (local, sur le processeur) ;
- **Page web** (port 8080) : réécoute jour par jour, texte de chaque transmission, état du récepteur (bruit, signal, squelch), du direct et de la transcription.

## Organisation

| Fichier | Rôle |
|---|---|
| `rtl_airband.conf.example` | Configuration du récepteur (fréquence, gain, sorties MP3 + Icecast) |
| `web/server.py` | Serveur web (Python standard, sans dépendance) |
| `web/static/index.html` | Page de réécoute |
| `web/transcribe.py` | Service de transcription Whisper |
| `install.sh` | Compilation des pilotes, installation des services systemd |

Les enregistrements sont écrits dans `recordings/AAAA/MM/JJ/LFOS_AAAAMMJJ_HHMMSS.mp3`, avec la transcription à côté (`.json`).

## Installation

Prérequis : Debian/Ubuntu, un RSP1A, un serveur Icecast2 qui tourne (`sudo apt install icecast2`).

1. Télécharge le pilote **SDRplay API 3.15** sur <https://www.sdrplay.com/api/> (licence propriétaire, non fourni ici) et extrais-le :
   ```bash
   sh SDRplay_RSP_API-Linux-3.15.2.run --noexec --target src/sdrplay_api
   ```
2. Lance `bash install.sh` une première fois : il crée `rtl_airband.conf` à partir de l'exemple.
3. Mets le mot de passe *source* de ton Icecast à la place de `CHANGE_MOI` dans `rtl_airband.conf`.
4. Relance `bash install.sh` : il télécharge et compile SoapySDRPlay3 et RTLSDR-Airband, crée l'environnement Python et installe les services `lfos-airband`, `lfos-web` et `lfos-transcribe`.

La page est ensuite sur `http://<serveur>:8080`.

## Réglages utiles

- **Gain** : `gain = "IFGR=40,RFGR=2"` dans `rtl_airband.conf` (plus petit = plus de gain).
- **Sensibilité du squelch** : `squelch_snr_threshold` dans `rtl_airband.conf`.
- **Modèle Whisper** : variable d'environnement `LFOS_WHISPER_MODEL` (défaut `medium`), `LFOS_WHISPER_THREADS` (défaut 3).
- **Port web** : `LFOS_WEB_PORT` (défaut 8080).

## Remarque

Les communications aéronautiques ne doivent pas être rediffusées publiquement. Ce dépôt ne contient aucun enregistrement ; garde la page web et le flux Icecast sur ton réseau local.

## Licence

MIT (voir `LICENSE`). RTLSDR-Airband, SoapySDRPlay3 et l'API SDRplay gardent leurs propres licences.
