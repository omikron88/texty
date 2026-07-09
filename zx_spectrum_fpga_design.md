# Návrh FPGA simulátoru ZX Spectra

Tento návrh popisuje syntetizovatelnou architekturu klonu **ZX Spectrum 48K** pro FPGA s hodinami 28 MHz a 133 MHz, SDRAM **Samsung K4S561632E** v x16 zapojení, šestibitovým RGB výstupem na složku a PS/2 klávesnicí. ROM ZX Spectra je uvažována jako synchronní bloková paměť FPGA.

## Cílová konfigurace

- CPU: Z80 kompatibilní soft-core na efektivních 3,5 MHz.
- Hlavní systémová doména: 28 MHz.
- SDRAM doména: 133 MHz.
- Video: RGB `6:6:6`, samostatné synchronizace `hsync` a `vsync`.
- Paměťový model ZX Spectrum 48K:
  - `0x0000-0x3fff`: ROM 16 KiB v blokové RAM, pouze čtení.
  - `0x4000-0xffff`: RAM 48 KiB v SDRAM.
  - `0x4000-0x57ff`: bitmapa obrazu.
  - `0x5800-0x5aff`: atributy barev.
- Klávesnice: PS/2 dekodér mapovaný do osmipolořádkové klávesové matice ZX Spectra.

## Doporučené hodinování

Základní 28MHz hodiny se používají pro CPU, ULA, video a I/O. CPU neběží na samostatném pomalém taktu, ale na hodinovém povolení:

```text
28 MHz / 8 = 3,5 MHz
```

Tak zůstává celý digitální systém synchronní v jedné doméně a Z80 core dostává jen `cpu_ce` jednou za osm taktů. SDRAM řadič zůstává v oddělené 133MHz doméně a komunikuje přes jednoduchou požadavkovou vrstvu s handshake.

## Video časování

Pro běžný monitor je vhodné generovat VGA-kompatibilní signál 640×480 při 60 Hz odvozený z 28 MHz. Protože 28 MHz není standardních 25,175 MHz, návrh používá čítače s mírně upravenou řádkovou frekvencí. Většina monitorů tento režim přijme; pokud konkrétní monitor vyžaduje přesné VGA časování, má se 28 MHz použít jako vstup do PLL a vygenerovat 25,175 MHz nebo 25,2 MHz pixel clock.

Obraz ZX Spectra má 256×192 bodů. Doporučené zobrazení je 2× zvětšené na 512×384 bodů a centrované v aktivní oblasti 640×480:

- levý okraj: 64 pixelů,
- horní okraj: 48 pixelů,
- aktivní obraz: 512×384 pixelů,
- pravý okraj: 64 pixelů,
- dolní okraj: 48 pixelů.

Každý ZX pixel se zobrazí jako blok 2×2 monitorových pixelů. Barvy se převádějí na 6 bitů na složku. Normální jas používá přibližně `0x2a`, zvýšený jas `0x3f`.

## ULA a sdílení paměti

ULA čte obrazovou RAM nezávisle na CPU. Aby CPU nemusel čekat na každý video fetch ze SDRAM, doporučený návrh používá malý řádkový buffer v BRAM:

1. Během vykreslování aktuální zdvojené řádky se z bufferu čtou bitmapové bajty a atributy.
2. V horizontálním blankingu nebo s předstihem se ze SDRAM načte další ZX řádka.
3. CPU port má přednost mimo kritické doplňování line-bufferu.

Minimální line-buffer pro jednu ZX řádku potřebuje:

- 32 bajtů bitmapy,
- 32 bajtů atributů,
- volitelně druhou banku pro double-buffering.

Double-buffering je doporučený, protože odděluje čtení SDRAM od pixelového výstupu.

## SDRAM K4S561632E

K4S561632E je 256Mbit SDRAM s organizací `4M × 16 × 4 banky`. V x16 režimu má 16bitovou datovou sběrnici a byte masky `DQM[1:0]`. Pro 48K RAM a video data je paměť výrazně větší než potřeba ZX Spectra; nejnižších 64 KiB lze mapovat jako pracovní obraz RAM.

Doporučené mapování lineární adresy v řadiči:

```text
byte_addr[0]     -> výběr dolního/horního bajtu na DQ[7:0]/DQ[15:8]
word_addr[8:0]   -> sloupec SDRAM
word_addr[21:9]  -> řádek SDRAM
word_addr[23:22] -> banka SDRAM
```

U K4S561632E je vhodné použít `ROW_BITS=13`, `COL_BITS=9`, `BANK_BITS=2` a `ADDR_WIDTH=25` pro bajtovou adresu. Refresh při 133 MHz a 8192 řádcích v 64 ms vychází přibližně na:

```text
133e6 * 64e-3 / 8192 = 1039 taktů
```

Prakticky tedy `REFRESH_INTERVAL=1030 až 1040` taktů 133MHz domény.

## Paměťová arbitráž

Arbitráž má tři zdroje požadavků:

1. CPU čtení/zápis RAM.
2. Video prefetch do line-bufferu.
3. Refresh uvnitř SDRAM řadiče.

Doporučené priority:

1. Refresh, protože je časově kritický.
2. Video prefetch, pokud hrozí podtečení line-bufferu.
3. CPU.

CPU musí podporovat signál `WAIT`, protože v nejhorším případě může být požadavek zdržen refreshem nebo doplňováním video bufferu. Při 3,5 MHz jsou krátké wait stavy přijatelné a zachovají korektnost návrhu.

## Klávesnice PS/2

PS/2 přijímač dekóduje scan kódy setu 2 na stavovou matici ZX Spectra. Matice je aktivní v nule, stejně jako původní ULA. Čtení portu `0xfe` funguje takto:

- CPU zapíše adresu portu na sběrnici.
- Bity `A15..A8` vybírají řádky klávesnice; řádka je vybraná, pokud je příslušný adresní bit nulový.
- Výsledek je AND všech vybraných řádek.
- Dolních pět bitů datového vstupu obsahuje sloupce kláves, ostatní bity mohou nést stav pásky/borderu podle potřeby.

## Doporučené moduly

| Modul | Úloha |
| --- | --- |
| `zx_spectrum_top` | propojení hodin, CPU, ROM, SDRAM, ULA a klávesnice |
| `zx_clock_enable` | generování `cpu_ce = 28 MHz / 8` |
| `zx_ula_video` | čítače VGA, border, převod bitmapy/atributů na RGB |
| `zx_keyboard_ps2` | PS/2 přijímač a klávesová matice |
| `zx_memory_arbiter` | mapování ROM/RAM/I/O a arbitráž CPU/video požadavků |
| `sdram_controller` | 133MHz SDRAM transakce s refresh logikou |

## Implementační poznámky

- ROM musí mít synchronní čtení, proto CPU při čtení ROM dostane data o takt později nebo přes vložený wait stav.
- Zápisy do ROM oblasti se ignorují.
- Port `0xfe` musí řídit border a číst klávesnici.
- Pro přesnější kompatibilitu lze později doplnit contention ULA, beeper, EAR/MIC a načasování interrupcí po 20 ms.
- První verze může generovat interrupt jednou za snímek při začátku vertikálního blankingu.

## Minimální integrační postup

1. Ověřit 28MHz video výstup se statickým testovacím obrazcem.
2. Připojit ROM a Z80 core, ale RAM zatím nahradit interní BRAM.
3. Přidat PS/2 klávesnici a ověřit čtení portu `0xfe`.
4. Připojit SDRAM řadič a přesunout RAM `0x4000-0xffff` do SDRAM.
5. Přidat line-buffer pro ULA a odstranit vizuální trhání při současném běhu CPU.
6. Doladit wait stavy a případné ULA contention podle požadované kompatibility.
