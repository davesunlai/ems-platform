#!/usr/bin/env bash
# Nasazení EMS pilotu na tento stroj. Spusť z kořene projektu:
#   bash scripts/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."   # kořen projektu

COMPOSE="docker compose -f infra/docker-compose.yml"

# 1) devices.yaml — pokud chybí, vytvoř z mock šablony (běh bez VPN)
if [[ ! -f devices.yaml ]]; then
  echo "==> devices.yaml chybí, vytvářím MOCK konfiguraci (běh bez měničů)."
  cat > devices.yaml << 'YAML'
devices:
  - id: home-fve-hybrid
    type: storage
    adapter: mock
    name: "Goodwe GW10K-ET (hybrid + baterie 52 kWh)"
    site: "Domácnost pilot"
    region: CZ
    params:
      pv_peak_w: 16000
      battery_capacity_kwh: 52
  - id: home-fve-grid
    type: generation
    adapter: mock
    name: "Goodwe GW10K-DT (grid-tie FVE)"
    site: "Domácnost pilot"
    region: CZ
    params:
      pv_peak_w: 10000
      battery_capacity_kwh: 0.001
YAML
  echo "    (až bude VPN: přepni adapter: mock -> goodwe a doplň host)"
fi

# 2) .env s heslem DB — vygeneruj, pokud chybí
if [[ ! -f .env ]]; then
  PW="$(openssl rand -hex 16 2>/dev/null || echo "ems-$(date +%s)")"
  JWT="$(openssl rand -hex 32 2>/dev/null || echo "jwt-$(date +%s)")"
  ADMINPW="$(openssl rand -hex 6 2>/dev/null || echo "admin$(date +%s)")"
  {
    echo "EMS_DB_PASSWORD=${PW}"
    echo "EMS_JWT_SECRET=${JWT}"
    echo "EMS_ADMIN_USER=admin"
    echo "EMS_ADMIN_PASSWORD=${ADMINPW}"
  } > .env
  echo "==> Vytvořen .env (heslo DB, JWT secret, admin)."
  echo "==> PRVNÍ PŘIHLÁŠENÍ:  admin / ${ADMINPW}   (změň po loginu)"
fi
set -a; source .env; set +a

# 3) build + start
echo "==> Build a start kontejnerů…"
$COMPOSE up -d --build

# 4) krátké čekání a stav
echo "==> Čekám na nahození služeb…"
sleep 8
$COMPOSE ps

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "==> Hotovo."
echo "    Web:        http://${IP:-192.168.6.209}:8080"
echo "    API zdraví: http://${IP:-192.168.6.209}:8080/api/health"
echo "    Swagger:    http://${IP:-192.168.6.209}:8000/docs"
echo
echo "Logy kolektoru:  $COMPOSE logs -f collector"
