# 0026 – HTTPS přes Caddy (Let's Encrypt)

## Stav
Přijato (v0.21.0)

## Kontext
Potřebujeme HTTPS na teraems.com (bezpečnost přihlášení, odkazy v e-mailech,
a hlavně OAuth2 redirect pro eWeLink, který vyžaduje SSL).

## Rozhodnutí
- Do compose přidán kontejner `caddy` (image caddy:2) na portech 80/443,
  reverse_proxy na `web:80`. Caddy si sám obstará a obnovuje Let's Encrypt
  certifikát (HTTP-01, port 80). Konfigurace v infra/Caddyfile.
- Vyžaduje volné porty 80 a 443 na hostu (odstavit Apache) a forward 80+443
  z routeru na frantu. DNS teraems.com → veřejná IP.
- Web (8080) zůstává publikovaný pro přímý přístup z LAN.
- EMS_BASE_URL se přepne na https://teraems.com.

## Důsledky
- HTTPS odemyká OAuth2 pro eWeLink (navazuje další verze) a šifruje provoz.
