# TERA EMS – mobilní appka (Capacitor)

Nativní obal pro Android a iOS. V tomto režimu (varianta B) appka **načítá živý web**
`https://teraems.com`, takže každá změna webu se po nasazení projeví i v appce bez rebuildu.
Soubor `www/index.html` je jen offline fallback (zobrazí se, když není připojení).

## Předpoklady
- Node.js 18+
- Android: Android Studio (SDK, emulátor nebo zařízení)
- iOS: macOS + Xcode (na build/podpis), Apple Developer účet (99 $/rok) pro vydání
- Účet Google Play (jednorázově 25 $) pro vydání na Androidu

## První nastavení
```bash
cd mobile
npm install
npx cap add android      # vytvoří složku android/
npx cap add ios          # vytvoří složku ios/  (jen na macOS)
npx cap sync
```

## Spuštění
```bash
npx cap open android     # otevře Android Studio → Run
npx cap open ios         # otevře Xcode → Run
```
Appka naběhne proti živému webu. Po každém nasazení webu stačí v appce pull-to-refresh
nebo restart – nový web se načte sám.

## Ikona a splash (volitelné)
```bash
npm i -D @capacitor/assets
# vlož assets/icon.png (1024x1024) a assets/splash.png (2732x2732)
npx capacitor-assets generate
```

## Později: přechod na „zabalené assety" (varianta A, pro obchody + OTA)
1. V `capacitor.config.json` odeber blok `server.url`.
2. Web build kopíruj do `www`: `cd ../web && npm run build && cp -r dist/* ../mobile/www/`
   (nebo nastav `webDir` na build a uprav skript).
3. Ve webu přepni router na hash režim a Vite `base: "./"`.
4. Na backendu povol CORS pro origin appky (`capacitor://localhost`).
5. Pro aktualizace bez schvalování v obchodě zvaž OTA (Capgo / Appflow).

## Ikona a splash – generování všech rozlišení
Předlohy jsou v `mobile/assets/` (icon-only, icon-foreground, icon-background, splash, splash-dark).
Z nich se jedním příkazem vygenerují všechny velikosti pro Android i iOS:
```bash
cd mobile
npm i -D @capacitor/assets
npx capacitor-assets generate
npx cap sync
```
Pak v Android Studiu znovu Build/Run – appka i launcher budou mít novou ikonu a splash.
