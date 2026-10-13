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

## Nové načtení desktop.wav

Výřezy dalšího uživatelem dodaného mono PCM 16bit/48kHz záznamu
(197,5250625 s) zachovávají původní vzorky:

- `desktop_new_header.wav`: 4,7–5,3 s, závěr pilotu a BASIC hlavička
  `00004445534b544f5020202069080a005a0043`. Tentokrát deklaruje 2153 bajtů;
  odpovídající úplný datový blok má 2155 bajtů včetně příznaku a XOR.
- `desktop_new_code_header.wav`: 25,6–26,2 s, rozšířená synchronizace a hlavička
  CODE `desktopBcd`, 28383 bajtů na adrese 24200. Očekávané bajty:
  `00036465736b746f70426364df6e885e333858`.
- `desktop_new_weak_zero.wav`: 189,75–189,85 s, skutečná velmi mělká nula
  s výrazně posunutým vnitřním extrémem. V původním čase 189,779583 s začíná
  dvojice intervalů přibližně 63/396 µs (3500 Hz) nebo 83/375 µs (5000 Hz).
  Vnitřní minimum je mělké, ale existuje v obou filtrovaných stopách.
  Součet identifikuje nulu; samotný delší interval by mohl připomínat jedničku.

Úplný nový záznam se dekóduje na čtyři bloky o délkách 19, 2155, 19 a 28385
bajtů. Všechny bajty souhlasí při 3500 i 5000 Hz, XOR je platný a délky
odpovídají oběma hlavičkám. SHA-256 hlavního datového bloku včetně příznaku a XOR:
`94f6826127ae1cd11ea73ebb161db882a0623d6081a8b00353384f737e31ef08`.
Celý WAV ani programové soubory nejsou součástí regresních vzorků.
