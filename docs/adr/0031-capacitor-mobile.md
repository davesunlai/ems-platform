# 0031 – Mobilní appka přes Capacitor (varianta B: živý web)

## Stav
Přijato (v0.27.0)

## Kontext
Chceme nativní Android + iOS appku. Frontend je React SPA, backend REST/JWT.
Nejlevnější cesta s plným znovupoužitím UI je Capacitor.

## Rozhodnutí
- Samostatná složka `mobile/` (mimo serverový build webu, aby ho Capacitor nezatěžoval).
- Varianta B: capacitor.config `server.url = https://teraems.com` → appka načítá živý
  web, změny webu se projeví bez rebuildu appky. `www/index.html` je offline fallback.
- appId com.teraems.app, appName „TERA EMS". Capacitor 6.
- Native složky android/ ios/ se generují u vývojáře (`npx cap add ...`), nejsou v gitu.

## Důsledky
- Rychlá iterace během vývoje. Pro vydání do obchodů se přejde na variantu A
  (zabalené assety, hash router, Vite base './', CORS, OTA) – popsáno v mobile/README.
- Push (FCM/APNs) + registr device-tokenů je samostatný další krok.
