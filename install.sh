#!/bin/bash
# Installation de l'écoute/enregistrement LFOS 119.508 MHz avec un SDRplay RSP1A.
# À lancer dans un terminal normal :   bash ./install.sh
set -e
APP="$(cd "$(dirname "$0")" && pwd)"
SRC=$APP/src
USER_NAME="$(id -un)"
cd "$APP"

# Sources tierces (non incluses dans le dépôt)
mkdir -p "$SRC"
command -v git >/dev/null || { sudo apt-get update && sudo apt-get install -y git; }
[ -d "$SRC/RTLSDR-Airband" ] || git clone --branch v7.0.1 --depth 1 https://github.com/charlie-foxtrot/RTLSDR-Airband.git "$SRC/RTLSDR-Airband"
[ -d "$SRC/SoapySDRPlay3" ] || git clone --depth 1 https://github.com/pothosware/SoapySDRPlay3.git "$SRC/SoapySDRPlay3"
if [ ! -f /usr/local/lib/libsdrplay_api.so.3.15 ] && [ ! -f "$SRC/sdrplay_api/install_lib.sh" ]; then
  echo "Le pilote SDRplay (API 3.15, licence propriétaire) n'est pas fourni :"
  echo "télécharge-le sur https://www.sdrplay.com/api/ puis extrais-le dans $SRC/sdrplay_api"
  echo "(ex. : sh SDRplay_RSP_API-Linux-3.15.2.run --noexec --target $SRC/sdrplay_api)"
  exit 1
fi

# Configuration locale
if [ ! -f "$APP/rtl_airband.conf" ]; then
  sed "s#/home/pi/lfos-radio#$APP#g" "$APP/rtl_airband.conf.example" > "$APP/rtl_airband.conf"
  echo "rtl_airband.conf créé : mets le mot de passe source d'Icecast à la place de CHANGE_MOI, puis relance."
  exit 1
fi


echo "=== 1/5 Paquets nécessaires ==="
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3-venv ffmpeg cmake pkg-config libsoapysdr-dev soapysdr-tools libconfig++-dev \
  libmp3lame-dev libshout-dev libfftw3-dev libusb-1.0-0-dev

echo "=== 2/5 Pilote SDRplay (API 3.15) : accepte la licence quand demandé ==="
if [ ! -f /usr/local/lib/libsdrplay_api.so.3.15 ]; then
  (cd "$SRC/sdrplay_api" && bash ./install_lib.sh)
else
  echo "déjà installé"
fi

echo "=== 3/5 Module SoapySDR pour SDRplay ==="
cmake -S "$SRC/SoapySDRPlay3" -B "$SRC/SoapySDRPlay3/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$SRC/SoapySDRPlay3/build" -j"$(nproc)"
sudo cmake --install "$SRC/SoapySDRPlay3/build"
sudo ldconfig

echo "=== 4/5 RTLSDR-Airband ==="
cd "$SRC/RTLSDR-Airband" && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DPLATFORM=native -DRTLSDR=OFF -DSOAPYSDR=ON -DPULSEAUDIO=OFF -DNFM=OFF
cmake --build build -j"$(nproc)"
sudo cmake --install build && cd "$APP"


echo "=== 5/5 Environnement Python (Whisper) et services de démarrage automatique ==="
# Environnement Python pour la transcription
[ -x "$APP/venv/bin/python" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q -r "$APP/requirements.txt"

sudo tee /etc/systemd/system/lfos-airband.service >/dev/null <<EOF
[Unit]
Description=LFOS 119.508 - reception et enregistrement (RSP1A)
After=network-online.target sdrplay.service icecast2.service
Wants=sdrplay.service

[Service]
User=$USER_NAME
ExecStartPre=/bin/sleep 3
ExecStart=/usr/local/bin/rtl_airband -F -e -c $APP/rtl_airband.conf
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/lfos-web.service >/dev/null <<EOF
[Unit]
Description=LFOS 119.508 - page web des enregistrements
After=network-online.target

[Service]
User=$USER_NAME
ExecStart=/usr/bin/python3 $APP/web/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/lfos-transcribe.service >/dev/null <<EOF
[Unit]
Description=LFOS 119.508 - transcription automatique (Whisper)
After=network-online.target

[Service]
User=$USER_NAME
ExecStart=$APP/venv/bin/python $APP/web/transcribe.py
Nice=10
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now lfos-web.service lfos-transcribe.service
sudo systemctl enable lfos-airband.service
sudo systemctl restart sdrplay 2>/dev/null || true
sleep 3
sudo systemctl restart lfos-airband.service

echo
echo "Installation terminée."
echo "Page web :  http://$(hostname -I | awk '{print $1}'):8080"
echo "État :      systemctl status lfos-airband lfos-web"
