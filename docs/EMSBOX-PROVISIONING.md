# EMSBOX — výroba, provisioning a aktualizace firmwaru

## Přehled cest k hotovému boxu

| Fáze | Metoda | Pro koho |
|---|---|---|
| teď (pilot, kusovka) | **SSH + provision.sh** | David vyrábí SD karty ručně |
| malosérie | **Golden image** (předpřipravená SD/dd) | technik jen vloží kartu |
| produkce | Golden image + first-boot personalizace | výroba |

## 1. SSH + provision.sh (aktuální workflow)

1. Vypal **Raspberry Pi OS Lite 64-bit** (Raspberry Pi Imager: nastav SSH on, user root/heslo nebo klíč, volitelně dočasnou Wi-Fi pro instalaci).
2. Přihlas se přes SSH a spusť:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/davesunlai/ems-platform/main/emsbox/provision.sh | bash
   ```
3. Skript (idempotentní): hostname `emsbox-XXXX` (ze sériáku CPU) → NetworkManager → **tovární Wi-Fi profil `emsbox`/`emsbox123`** (autoconnect, priorita −10) → Docker → clone/pull repa → build + start agenta → nainstaluje `emsbox-update`.
4. Konec: vypíše IP lokálního UI (port 80). Box je připraven k párování z mobilu.

Skryté servisní heslo lokálního UI (topadmin) zůstává beze změny — env `EMSBOX_TOPADMIN`, default dle interní dokumentace; ve výrobě NEMĚNIT na kartě, drží se v image.

## 2. Tovární Wi-Fi `emsbox`/`emsbox123` — servisní záchrana

Profil je v NM s nízkou prioritou: nikdy nepřebije nakonfigurovanou síť klienta, ale když box
„zmizí" (klient změnil router apod.), stačí komukoli na místě zapnout **hotspot na mobilu se
jménem `emsbox` a heslem `emsbox123`** → box se do minuty připojí → heartbeat donese privátní IP
na `teraems.com/emsboxes` → servis se dostane na lokální UI. Profil zakládá provision.sh
i agent sám při startu (ensure_factory_wifi — pokrývá i staré instalace po updatu).

## 3. Golden image (malosérie) — postup výroby

1. Vyrob vzorový box přes provision.sh, NEPÁRUJ ho (žádné credentials v /data — párování je per-kus).
2. `docker rm -f emsbox && docker volume rm emsbox-data` (čistý stav), vypni Pi.
3. Na PC: `dd if=/dev/sdX bs=4M | gzip > emsbox-golden-vX.Y.Z.img.gz` (příp. PiShrink pro zmenšení).
4. Výroba: Imager → image na kartu → hotovo. Hostname se dopočítá z CPU sériáku při prvním bootu
   (unikátní per kus), tovární Wi-Fi je uvnitř, agent startuje sám a čeká na párování.

## 4. Aktualizace firmwaru

- **Dnes (přes SSH):** `ssh root@box 'emsbox-update'` — git pull + rebuild + restart kontejneru, ~3 min.
- **Dálkově z teraems (od v0.79.0):** fleet /emsboxy → tlačítko „⬆ update" u verze → akce
  `update_agent` heartbeatem → agent zapíše `/data/update_request` → hostový
  `emsbox-update.path` (systemd, instaluje provision.sh) spustí `emsbox-update`. Starší boxy:
  jednorázově doinstalovat jednotky (blok v README/chatu).
  Alternativa pro větší flotily: publikovat hotový multi-arch image do registru
  (ghcr.io) → update = `docker pull` + restart, bez buildů na Pi (rychlejší, deterministické).
  Doporučený cíl pro produkci.

## 5. Bezpečnostní poznámky

- Wi-Fi heslo klientovy sítě se od v0.77.0 posílá v heartbeatu a ukazuje ve fleetu (rozhodnutí
  Davida — servisní přístup). Přenos jde přes HTTPS na teraems; ve fleet UI je za „okem".
- Tovární síť `emsbox`/`emsbox123` je vědomě slabá (servisní kanál; WPA-PSK vyžaduje min. 8 znaků, proto ne jen 'emsbox') — box na ní pouze *klientsky
  visí*; lokální UI dál chrání heslo uživatele/topadmina.


## 6. Síťové lekce z pilotu (9. 9. 2026)

- **Netplan backend:** Raspberry Pi OS/Ubuntu image mohou mít NM řízený netplanem (profily
  `netplan-*`). nmcli změny z lokálního UI se v tom režimu persistují přes netplan YAML
  (`/etc/netplan/90-NM-*.yaml`) — statická IP i Wi-Fi PŘEŽÍVAJÍ reboot. Po přegenerování
  profilů může NM při aktivaci chtít znovu vtisknout PSK (`nmcli con mod <p> wifi-sec.psk …`).
- **DNS kontejneru:** agent MUSÍ mít mount `-v /etc/resolv.conf:/etc/resolv.conf:ro`, jinak si
  po přepnutí sítě (Wi-Fi↔LAN) nese zatuchlé DNS a heartbeat umírá na name resolution,
  i když host je online. provision.sh i emsbox-update mount obsahují.
- **Tovární profil:** ensure_factory_wifi testuje existenci výpisem všech jmen (con show
  <name> není spolehlivé) a duplicity sám uklízí.


## 7. Servisní konzole (od v0.82.x)

Fleet → „🖥 konzole" u boxu otevře terminál v prohlížeči (admin-only, auditováno). Shell běží
NA HOSTU (Raspberry) přes `nsenter` do PID 1 — technik má ps/top/dmesg/journalctl/systemctl/
nmcli/df celého Pi, ne jen kontejneru. Vyžaduje `docker run … --pid host --cap-add SYS_ADMIN
--cap-add SYS_PTRACE` a `util-linux` v image (nsenter); provision.sh i emsbox-update to nastavují.
Když prostředí nsenter nedovolí, konzole spadne do shellu kontejneru (fallback). Tunel je odchozí
z boxu (WS na server), takže nepotřebuje otevřené porty u klienta.
