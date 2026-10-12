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

## desktop.zip / desktop.wav

Další mono PCM 16bit/48kHz vzorky pocházejí z uživatelem dodaného archivu:

- `desktop_header.wav`: původní čas 4,3–5,25 s. Synchronizační minimum zůstává
  nad nulou, takže je nutné sledovat střídající se extrémy. Hlavička je BASIC
  `DESKTOP`, délka 2154 bajtů, řádek 10, offset proměnných 90. Očekávané bajty:
  `00004445534b544f502020206a080a005a0040`.
- `desktop_dropout.wav`: původní čas 26,2–29,75 s. Obsahuje pilot a začátek
  hlavního bloku, potom skutečný výpadek signálu kolem 29,61–29,68 s.
  Test vyžaduje odmítnutí neúplného bloku; chybějící bity se nedoplňují.

Oba výřezy zachovávají původní PCM vzorky.
