#!/bin/bash
# ============================================================================
# EMSBOX provision.sh — inicializace čerstvého Raspberry Pi (OS Lite 64-bit)
# na EMSBOX. Spouštět jako root PŘES SSH na čistém Pi:
#   curl -fsSL https://raw.githubusercontent.com/davesunlai/ems-platform/main/emsbox/provision.sh | bash
# nebo: scp provision.sh pi:/tmp/ && ssh pi 'sudo bash /tmp/provision.sh'
# Idempotentní — lze pouštět opakovaně.
# ============================================================================
set -euo pipefail
REPO="${EMSBOX_REPO:-https://github.com/davesunlai/ems-platform.git}"
echo "== EMSBOX provisioning =="
[ "$(id -u)" = "0" ] || { echo "Spusť jako root"; exit 1; }

# 1) hostname (emsbox-XXXX z konce sériáku CPU) — jen pokud ještě default
if hostname | grep -qE '^raspberrypi$'; then
  SUF=$(awk '/Serial/{print substr($3, length($3)-3)}' /proc/cpuinfo)
  hostnamectl set-hostname "emsbox-${SUF:-0000}"
  sed -i "s/raspberrypi/emsbox-${SUF:-0000}/g" /etc/hosts
fi

# 2) NetworkManager (Bookworm/Trixie ho má; jistota) + tovární Wi-Fi profil
apt-get update -qq
apt-get install -y -qq network-manager git curl >/dev/null
systemctl enable --now NetworkManager
if ! nmcli -t -g NAME con show emsbox-default >/dev/null 2>&1; then
  nmcli con add type wifi ifname "*" con-name emsbox-default ssid emsbox \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk emsbox123 \
    connection.autoconnect yes connection.autoconnect-priority -10
  echo "Tovární Wi-Fi profil emsbox/emsbox123 založen."
fi

# 3) Docker
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

# 4) Repo + build agenta
mkdir -p /opt && cd /opt
if [ ! -d /opt/emsbox/.git ]; then git clone "$REPO" /opt/emsbox; fi
cd /opt/emsbox && git pull
docker build -f emsbox/Dockerfile -t teraems/emsbox-agent .

# 5) Start/restart agenta (stejné argumenty jako produkce; RS485 by-id se mapuje
#    až po připojení převodníku — bez něj poběží localui a párování)
docker rm -f emsbox 2>/dev/null || true
DEV_ARG=""
BYID=$(ls /dev/serial/by-id/ 2>/dev/null | head -1 || true)
[ -n "$BYID" ] && DEV_ARG="--device /dev/serial/by-id/$BYID:/dev/ttyUSB0"
docker run -d --name emsbox --restart unless-stopped --network host --pid host \
  --cap-add SYS_ADMIN --cap-add SYS_PTRACE \
  -e TZ=Europe/Prague $DEV_ARG \
  -v /etc:/host/etc:ro \
  -v /etc/resolv.conf:/etc/resolv.conf:ro \
  -v /run/dbus/system_bus_socket:/run/dbus/system_bus_socket \
  -v emsbox-data:/data teraems/emsbox-agent

# 6) update skript pro dálkovou aktualizaci (zatím přes SSH: emsbox-update)
cat > /usr/local/bin/emsbox-update << 'UPD'
#!/bin/bash
set -e
cd /opt/emsbox && git pull
docker build -f emsbox/Dockerfile -t teraems/emsbox-agent .
docker rm -f emsbox 2>/dev/null || true
DEV_ARG=""
BYID=$(ls /dev/serial/by-id/ 2>/dev/null | head -1 || true)
[ -n "$BYID" ] && DEV_ARG="--device /dev/serial/by-id/$BYID:/dev/ttyUSB0"
docker run -d --name emsbox --restart unless-stopped --network host --pid host \
  --cap-add SYS_ADMIN --cap-add SYS_PTRACE \
  -e TZ=Europe/Prague $DEV_ARG \
  -v /etc:/host/etc:ro \
  -v /etc/resolv.conf:/etc/resolv.conf:ro \
  -v /run/dbus/system_bus_socket:/run/dbus/system_bus_socket \
  -v emsbox-data:/data teraems/emsbox-agent
echo "EMSBOX aktualizován: $(cd /opt/emsbox && git log --oneline -1)"
UPD
chmod +x /usr/local/bin/emsbox-update

# 7) dálkový update z teraems: path unit hlídá /data/update_request (zapisuje agent na povel)
VOL=/var/lib/docker/volumes/emsbox-data/_data
cat > /etc/systemd/system/emsbox-update.service << 'SVC'
[Unit]
Description=EMSBOX agent update (vyzadano z teraems)
[Service]
Type=oneshot
ExecStartPre=/bin/rm -f /var/lib/docker/volumes/emsbox-data/_data/update_request
ExecStart=/usr/local/bin/emsbox-update
SVC
cat > /etc/systemd/system/emsbox-update.path << 'PTH'
[Unit]
Description=Hlidac pozadavku na update EMSBOX agenta
[Path]
PathExists=/var/lib/docker/volumes/emsbox-data/_data/update_request
[Install]
WantedBy=multi-user.target
PTH
systemctl daemon-reload
systemctl enable --now emsbox-update.path

echo "== HOTOVO =="
echo "Lokální UI:  http://$(hostname -I | awk '{print $1}')/  (port 80)"
echo "Update:      emsbox-update (přes SSH)"
echo "Tovární WiFi: SSID emsbox / heslo emsbox123 (hotspot na mobilu)"
