# Skutečný záznam pro regresní test

`leonardo_header.wav` je mono výřez prvního kanálu uživatelem dodaného `1.wav`:
od 4,4 s do konce původního záznamu (5,3009167 s), PCM 16 bitů, 48 kHz.
Obsahuje závěr pilotu se zákmitem, slabou synchronizaci a úplnou hlavičku.
Původní PCM vzorky jsou zachovány.

Očekávaných 19 bajtů:

```text
00 00 6c 65 6f 6e 61 72 64 6f 20 20 a5 00 0a 00 a5 00 1a
```

Hlavička: BASIC, název `leonardo`, délka programu 165 bajtů, automatický start
na řádku 10, offset proměnných 165, platný XOR. Navazující datový blok
v tomto výřezu není; běžný režim má oznámit chybějící data, nikoli chybu synchronizace.
