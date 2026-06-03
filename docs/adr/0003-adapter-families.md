# ADR 0003: Tři rodiny rozhraní (HW / cloud / trh)

## Kontext
Data tečou z vlastního HW (přímý protokol), z cloud API třetích stran a
z trhů/TSO. Liší se latencí, spolehlivostí a možnostmi řízení.

## Rozhodnutí
Rychlé a bezpečnostně kritické řízení jen přes přímý protokol + edge.
Cloud API = monitoring a pomalé povely. Trh = obchodní rovina + aktivace,
jejíž fyzická realizace běží přes edge. Žádné cizí API není SPOF pro bezpečnost.

## Důsledky
- Goodwe ET/DT (přímý protokol) je vhodný i pro budoucí řízení.
- Adaptér má jednotné rozhraní bez ohledu na rodinu.
