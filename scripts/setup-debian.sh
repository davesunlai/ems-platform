#!/usr/bin/env bash
# Instalace Docker Engine + Compose pluginu na Debianu (oficiální apt repo).
# Spuštění:  sudo bash scripts/setup-debian.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Spusť přes sudo:  sudo bash scripts/setup-debian.sh" >&2
  exit 1
fi

echo "==> Odstraňuji konfliktní staré balíčky (pokud jsou)"
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  apt-get remove -y "$pkg" 2>/dev/null || true
done

echo "==> Základní balíčky"
apt-get update
apt-get install -y ca-certificates curl gnupg

echo "==> Docker GPG klíč"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "==> Docker apt repozitář"
CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian ${CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list

echo "==> Instalace Docker Engine + Compose pluginu"
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "==> Povolení a start služby"
systemctl enable --now docker

# Přidat běžného uživatele do skupiny docker (běh bez sudo)
REAL_USER="${SUDO_USER:-}"
if [[ -n "$REAL_USER" && "$REAL_USER" != "root" ]]; then
  usermod -aG docker "$REAL_USER"
  echo "==> Uživatel '$REAL_USER' přidán do skupiny docker (odhlas/přihlas se, ať se projeví)."
fi

echo "==> Hotovo. Ověření:"
docker --version
docker compose version
echo
echo "Dál pokračuj:  bash scripts/deploy.sh"
