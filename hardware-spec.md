# Technická specifikace emulovaného počítače

Stav dokumentu: pracovní specifikace sestavená z popisu skutečného zapojení.

Tento dokument je autoritativním podkladem pro implementaci emulátoru v SDL3. Stroj není kompatibilní s IBM PC. Periferní obvody a zejména diskový řadič je nutné modelovat podle zde popsaného zapojení, nikoli podle obvyklých zkratek používaných v emulátorech osobních počítačů.

## 1. Základní vlastnosti

- CPU: Z80, 4 MHz.
- Periferní obvody pocházejí převážně z rodiny Intel 8080:
  - 3× 8255 PPI,
  - 1× 8253 PIT,
  - 1× 8251 UART,
  - prioritní řadič přerušení 3214.
- Video: černobílé, 512 × 256 bodů, PAL 50 Hz, obraz 4:3.
- Disky: dvě 8palcové mechaniky, jednostranné, jednoduchá hustota, FM.
- Diskový řadič není tvořen jedním FDC. Skládá se ze dvou 8255, jednoho čítače 8253, serializérů/deserializérů a TTL logiky 74xx.

## 2. Společný emulační čas

CPU, video, 8253, disková rotační poloha, datový přenos a periferní události musejí používat jednu deterministickou časovou osu. Časování nesmí být odvozeno od frekvence vykreslování SDL ani přímo od času hostitelského systému.

Doporučená interní časová základna je 12 MHz. Umožní celočíselně vyjádřit hlavní známé intervaly:

| Událost | Doba | Ticků při 12 MHz |
|---|---:|---:|
| takt Z80 | 0,25 µs | 3 |
| takt vstupu 1 MHz | 1 µs | 12 |
| diskový bajt | 32 µs | 384 |
| PAL řádek | 64 µs | 768 |
| PAL snímek | 20 ms | 240 000 |
| otáčka diskety při 360 RPM | 166,666… ms | 2 000 000 |

Jedna otáčka odpovídá 666 666⅔ taktům Z80, proto by pevné zaokrouhlení počtu taktů Z80 na otáčku způsobovalo dlouhodobý drift Indexu.

## 3. Paměť

Z80 má dvě přepínatelné mapy. Rozsah `0x8000–0xFFFF` se nikdy nestránkuje a v obou mapách představuje tutéž fyzickou hlavní RAM.

| Adresy | Mapa po resetu | RAM mapa |
|---|---|---|
| `0x0000–0x3FFF` | 16 KB bootovací a diagnostické ROM | RAM |
| `0x4000–0x7FFF` | 16 KB Video RAM | RAM |
| `0x8000–0xFFFF` | hlavní RAM | tatáž hlavní RAM |

Po resetu je aktivní mapa ROM + Video RAM.

- `IN` z dekódované skupiny `0x30` aktivuje plnou 64KB RAM mapu.
- `IN` z dekódované skupiny `0x50` aktivuje mapu ROM + Video RAM.
- Obě instrukce načtou `0xFF`, protože žádný obvod při tomto čtení neřídí datovou sběrnici.
- Videoobvod stále čte fyzickou Video RAM i tehdy, když ji Z80 po přepnutí na RAM mapu nevidí.

## 4. Dekódování I/O

Při výběru periferní skupiny se dekódují pouze adresové bity `A6–A4`. Bity `A7` a `A15–A8` se ignorují. Vnitřní adresové vstupy periferních IO jsou připojeny na nejnižší adresové bity Z80.

```c
uint8_t io_group = port & 0x70;
```

Neobsazené porty a čtení obvodů, které při dané operaci neřídí datovou sběrnici, vracejí `0xFF` díky pull-up rezistorům datové sběrnice.

### 4.1 Přehled skupin

| `A6–A4` | Skupina | Čtení | Zápis |
|---:|---:|---|---|
| `000` | `0x00` | 8255 tiskárny a klávesnice | totéž |
| `001` | `0x10` | 8253 | 8253 |
| `010` | `0x20` | datová 8255 disku | totéž |
| `011` | `0x30` | aktivace plné RAM, návrat `0xFF` | maska prioritního řadiče |
| `100` | `0x40` | 8251 UART | 8251 UART |
| `101` | `0x50` | aktivace ROM/VRAM mapy, návrat `0xFF` | pomocný diskový registr |
| `110` | `0x60` | řídicí 8255 disku/videa | totéž |
| `111` | `0x70` | myš a zrušení I3 | zrušení video I4 |

U 8255 a 8253 vybírají registr bity `A1–A0`. Bity `A3–A2` jsou zrcadla. Například čtyři registry 8255 se základnou `0x60` jsou `0x60–0x63`, ale zrcadlí se také na `0x64–0x67`, `0x68–0x6B`, `0x6C–0x6F`, `0xE0–0xEF` a se všemi hodnotami horního bajtu I/O adresy.

## 5. Přerušení

### 5.1 Prioritní řadič 3214

Maska se nastavuje zápisem do skupiny `0x30`:

| Hodnota | Povolené vstupy |
|---:|---|
| 0 | žádný |
| 1 | I7 |
| 2 | I7, I6 |
| … | … |
| 8 | I7 až I0 |

I7 má nejvyšší prioritu. Globální povolení přerušení v Z80 pomocí IFF1 je na masce 3214 nezávislé.

Negované výstupy prioritního řadiče `/A2`, `/A1`, `/A0` jsou zachyceny do registru. Při potvrzovacím cyklu Z80 `/IORQ + /M1` se na datovou sběrnici přivede vektor:

```text
D7 D6 D5 D4 D3 D2  D1  D0
 0  0  0  0 /A2 /A1 /A0  0
```

| Vstup | Vektor IM2 | Zdroj |
|---:|---:|---|
| I7 | `0x00` | Disk data |
| I6 | `0x02` | Disk timeout; při formátování také dokončení stopy |
| I5 | `0x04` | End of data |
| I4 | `0x06` | video 50 Hz |
| I3 | `0x08` | změna signálů myši |
| I2 | `0x0A` | UART 8251 (`TXRDY OR RXRDY`) |
| I1 | `0x0C` | klávesnice |
| I0 | `0x0E` | potvrzení tiskárny |

## 6. Video

### 6.1 Formát obrazu

- Aktivní obraz: 512 × 256 logických pixelů.
- Černobílý obraz, jeden bit na pixel.
- V každém bajtu je levý pixel v MSB.
- Celý obraz má poměr stran 4:3; logické pixely proto nejsou čtvercové.
- Vhodné celočíselné zobrazení je například 1024 × 768 s filtrováním nearest-neighbour.

### 6.2 Adresace Video RAM

Video RAM má 16 KB. Čítač sloupce bajtů tvoří horní část adresy a čítač řádku dolní část:

```text
A13–A8 = sloupec bajtu 0–63
A7–A0  = zdrojový řádek 0–255
```

Bez scrollingu:

```c
uint16_t addr = ((uint16_t)(x >> 3) << 8) | y;
uint8_t mask = 0x80 >> (x & 7);
bool pixel = (vram[addr] & mask) != 0;
```

První řádek používá adresy `0x0000`, `0x0100`, …, `0x3F00`. Druhý řádek používá `0x0001`, `0x0101`, …, `0x3F01`.

### 6.3 Vertikální scrolling

Celý Port B řídicí 8255 na skupině `0x60` slouží jako osmibitový jemný vertikální posun. Dvě sčítačky 74283 přičítají zachycenou hodnotu PB k čítači televizních řádků; přenos z nejvyššího bitu se zahodí.

```c
uint8_t source_y = video_line_counter + video_scroll_latched;
uint16_t addr = ((uint16_t)byte_column << 8) | source_y;
```

Při PB = 1 se nahoře zobrazí řádek 1, následují řádky 2 až 255 a poslední je řádek 0.

PB nejde na sčítačky přímo. Prochází pomocným registrem zachycovaným signálem `/RAS` videopaměti. Zápis PB lze provést kdykoli, ale nová hodnota se pro video použije až na příslušné hraně `/RAS`, aby se adresa nezměnila během paměťového cyklu.

Je nutné rozlišovat:

```c
uint8_t video_scroll_ppi;      // výstupní latch PB 8255
uint8_t video_scroll_latched;  // hodnota zachycená /RAS
```

Změna se může projevit mezi dvěma video-paměťovými cykly i uprostřed obrazového řádku. Časování obrazu, V/H synchronizace a paměťové adresy viděné CPU se scrollingem nemění.

### 6.4 Vertikální impulz a I4

Přerušení vzniká od V impulzu několik televizních řádků před začátkem aktivní oblasti. Frekvence je 50 Hz.

PA2 řídicí 8255 povoluje průchod V impulzu přes AND. Prošlý impulz nastaví klopný obvod, jehož výstup vede na I4. Požadavek proto trvá až do obsluhy.

- PA2 = 0: nové V impulzy jsou pro I4 blokovány.
- PA2 = 1: následující V impulz nastaví latch I4.
- Zápis na skupinu `0x70` latch I4 zruší; zapisovaná data nejsou významná.
- Potvrzení přerušení procesorem latch neruší.
- Vypnutí PA2 již nastavený latch neruší.

V impulz pro čítač 0 obvodu 8253 se odebírá ještě před tímto hradlem, takže čítač běží i při zakázaném I4.

## 7. 8255 na skupině 0x00: tiskárna a klávesnice

### 7.1 Konfigurace

Ve schématu je uvedeno řídicí slovo `CW = 0xAE`:

```text
PA: výstup, handshake režim 1
PB: vstup, handshake režim 1
PC upper: vstup
PC lower: formálně výstup, handshake skupiny B jej přebírá
```

| Registr | Základní adresa |
|---|---:|
| PA | `0x00` |
| PB | `0x01` |
| PC | `0x02` |
| Control | `0x03` |

### 7.2 Tiskárna Centronics

PA posílá datový bajt tiskárně. Používá handshake skupiny A:

| Signál | Funkce |
|---|---|
| PC7 `/OBF_A` | ohlášení připraveného výstupního bajtu / základ Centronics Strobe |
| PC6 `/ACK_A` | ACK z tiskárny |
| PC3 `INTR_A` | přerušení I0 |
| PC5 | ONLINE/SELECT, 1 = tiskárna online, 0 = offline |
| PC4 | PAPER END, 1 = došel papír |

Po zápisu PA zahájí 8255 handshake. Po potvrzení `/ACK_A` vznikne při povoleném interním INTE požadavek I0.

### 7.3 Klávesnice

PB přijímá data klávesnice v handshake režimu skupiny B:

| Signál | Funkce |
|---|---|
| PC2 `/STB_B` | Strobe z klávesnice |
| PC1 `IBF_B` | zachycený bajt čeká |
| PC0 `INTR_B` | přerušení I1 |

Klávesnice:

- při stisku vyšle osmibitový kód a impuls Strobe,
- při uvolnění neposílá nic,
- běžné znaky používají ASCII,
- Backspace posílá `0x7F`,
- kurzorové šipky mají zvláštní dosud neurčené kódy,
- po držení delším než 1 s začne opakovat stejný kód,
- frekvence následného opakování dosud není určena.

Opakování má generovat emulátor, ne autorepeat hostitelského OS.

## 8. Čítač 8253 na skupině 0x10

| Adresa | Registr |
|---:|---|
| `0x10` | čítač 0 |
| `0x11` | čítač 1 |
| `0x12` | čítač 2 |
| `0x13` | řídicí registr |

Je nutné emulovat skutečný 8253 včetně režimů, LSB/MSB sekvencí a latch příkazu. 8253 nemá Read-Back příkaz 8254.

### 8.1 Čítač 0: softwarový čas 50 Hz

- CLK0: V impulzy 50 Hz před hradlem PA2.
- GATE0: trvale 1.
- OUT0: nikam nepřipojen.
- Software jej používá pro měření času.

Každý V impulz provede jeden hodinový krok bez ohledu na povolení I4.

### 8.2 Čítač 1: UART a diskové časování

- CLK1: 1 MHz vzniklý dělením hodin CPU.
- Jeden krok trvá 1 µs = 4 takty Z80.

Když je `disk_timing_enabled` neaktivní, GATE1 je nuceně 1 a čítač funguje jako generátor společných RxC/TxC hodin pro UART 8251.

Když je diskové časování aktivní, GATE1 řídí synchronizační klopný obvod:

```c
gate1 = !disk_timing_enabled || disk_sync_latch;
```

`disk_sync_latch` se nastaví při rozpoznání značky zvolené bitem RDM a nuluje se s koncem diskové operace.

Při dosažení koncového počtu:

- při čtení vznikne I6 Disk timeout,
- při zápisu se aktivuje zápisový signál mechaniky; vypne se s koncem diskové operace.

Během diskové operace čítač 1 neposkytuje normální stabilní baudové hodiny UARTu.

### 8.3 Čítač 2: počet zbývajících bajtů

- CLK2: logický součet `INTR_A OR INTR_B` datové 8255 na skupině `0x20`.
- GATE2: trvale 1.
- Počítají se náběžné hrany součtu, nikoli délka aktivní úrovně.
- OUT2 nuluje pomocný diskový registr a současně vyvolává I5 End of data.

Čítač pracuje při běžném čtení i zápisu. Počet zahrnuje oba CRC bajty. Pro 128bajtové datové pole se tedy nastaví na 130 přenosů.

Při posledním čteném CRC bajtu současně vznikne I7 od handshake a I5 od OUT2. Díky prioritě se nejprve obslouží I7 a přečte se poslední bajt, potom I5.

Při formátování se čítač 2 pro ukončení operace nepoužívá.

## 9. Datová 8255 disku na skupině 0x20

| Registr | Základní adresa | Funkce |
|---|---:|---|
| PA | `0x20` | handshake výstup do zápisového posuvného registru |
| PB | `0x21` | handshake vstup ze čtecího posuvného registru |
| PC | `0x22` | handshake a výběr mechaniky |
| Control | `0x23` | řízení 8255 |

Odvozené řídicí slovo je `0xA6`:

- PA: výstup, režim 1,
- PB: vstup, režim 1,
- horní volná část PC: výstup kvůli PC5.

Přesnou hodnotu řídicího slova je vhodné ještě ověřit podle schématu nebo programu.

| Bit PC | Funkce |
|---:|---|
| PC7 | `/OBF_A` |
| PC6 | `/ACK_A` |
| PC5 | výběr mechaniky: 0 = A, 1 = B |
| PC4 | nepoužitý |
| PC3 | `INTR_A` pro zápis |
| PC2 | `/STB_B` |
| PC1 | `IBF_B` |
| PC0 | `INTR_B` pro čtení |

PC5 má pull-up do 1, aby během resetu a vstupního stavu 8255 neměl nedefinovanou úroveň.

### 9.1 Čtení

Když čtecí posuvný registr sestaví celý bajt, vytvoří `/STB_B`. 8255 bajt zachytí, nastaví IBF a při povoleném INTE vygeneruje `INTR_B`, který vede na I7 a současně taktuje čítač 2. Přečtení PB zruší handshake stav vstupu.

### 9.2 Zápis

CPU zapíše bajt do PA. Je-li zápis povolen, vnější logika jej na hranici zápisu nového diskového bajtu překopíruje do zápisového posuvného registru a následně vytvoří `/ACK_A`. `INTR_A` požádá přes I7 o další bajt a současně taktuje čítač 2.

## 10. UART 8251 na skupině 0x40

UART používá pouze A0:

| Operace | Sudá adresa (`0x40`) | Lichá adresa (`0x41`) |
|---|---|---|
| čtení | přijatá data | stav |
| zápis | vysílaná data | mode/command |

A1–A3 jsou zrcadla, například data jsou i na `0x42`, `0x44`, … a stav/řízení na `0x43`, `0x45`, …

- RxC a TxC jsou spojeny s OUT1 čítače 1 obvodu 8253.
- `TXRDY OR RXRDY` vede přímo na I2.
- I2 je úrovňové; samostatný latch zde nebyl popsán.
- Baud rate určuje nastavení čítače 1 a režim ×1/×16/×64 v 8251.

## 11. Pomocný diskový registr na skupině 0x50

Registr je pouze pro zápis. Má čtyři použité klopné obvody, ale nejsou připojené na souvislý dolní nibble:

| Datový bit | Název | Funkce |
|---:|---|---|
| D0 | RE | 1 = povolit čtecí obvody |
| D1 | WRE | 1 = povolit zápisové obvody |
| D2 | RDM | 1 = synchronizace na Data Mark; 0 = na Address Mark |
| D3 | — | nepoužitý |
| D4 | FOR | 1 = formátování stopy |

```c
RE  = (value & 0x01) != 0;
WRE = (value & 0x02) != 0;
RDM = (value & 0x04) != 0;
FOR = (value & 0x10) != 0;
```

Čtením skupiny `0x50` nelze obsah zjistit; čtení místo toho přepne paměťovou mapu na ROM/VRAM a vrátí `0xFF`.

Celý registr se asynchronně nuluje při kterékoli z podmínek:

1. systémový reset,
2. při běžném čtení nebo zápisu dosáhne čítač 2 nuly po přenosu druhého CRC bajtu,
3. při FOR je detekován druhý Index,
4. `disk_timing_enabled` je neaktivní, tedy PA6 = 1.

Reset registru vypne RE, WRE, RDM i FOR a ukončí diskovou operaci.

### 11.1 Synchronizace čtení

Při RE = 1 se posuvný registr spustí až po nalezení zvolené FM značky:

```c
selected_mark = RDM ? data_mark_detected : address_mark_detected;
```

Do té doby běžné bajty mezer ani jiných částí stopy nejsou předávány jako začátek požadovaného pole.

### 11.2 Formátování

Při FOR = 1 se odblokují dva kaskádní klopné obvody:

1. první Index zapne fyzický zápis a začne přenos formátovacích dat,
2. druhý Index nastaví druhý klopný obvod,
3. jeho výstup vynuluje pomocný registr,
4. tím se vypne zápis a ukončí operace,
5. stejný výstup vyvolá I6 Disk timeout.

Při formátování se nepočítají bajty ani čas. Zápis trvá přesně jednu otáčku mezi dvěma po sobě jdoucími Indexy. I6 zde znamená dokončení formátování, nikoli chybu.

## 12. Řídicí 8255 na skupině 0x60

| Registr | Základní adresa | Směr |
|---|---:|---|
| PA | `0x60` | prostý výstup |
| PB | `0x61` | prostý výstup |
| PC | `0x62` | PC0–PC3 výstup, PC4–PC7 vstup |
| Control | `0x63` | řízení 8255 |

Odvozené řídicí slovo je `0x88` (oba porty v režimu 0, PA/PB ven, PC upper dovnitř, PC lower ven). Hodnotu je vhodné ověřit podle inicializačního programu nebo poznámky ve schématu.

### 12.1 Port A

| Bit | Funkce | Aktivní stav |
|---:|---|---:|
| PA0 | potlačení FM hodinového pulzu C3 | 1 |
| PA1 | potlačení FM hodinového pulzu C4 | 1 |
| PA2 | povolení zachycení V impulzu do I4 | 1 |
| PA3 | povolení zachycení změny myši do I3 | 1 |
| PA4 | nepoužitý | — |
| PA5 | nepoužitý | — |
| PA6 | povolení diskových časovacích obvodů | 0 |
| PA7 | nepoužitý | — |

PA6 prochází jako aktivně nízké povolení diskového podsystému. Má pull-up do 1, aby při resetu, kdy je PA vysokoodporový vstup, zůstaly čtecí/zápisové časovací obvody bezpečně vypnuté.

```c
bool disk_timing_enabled = (ppi60_pa & 0x40) == 0;
```

PA6 neřídí mechanickou rotační fázi diskety; řídí datovou a časovací část řadiče.

### 12.2 FM hodinové masky při zápisu

PA0 a PA1 procházejí před serializérem invertory. Při PA1:PA0 = 00 jsou přítomny všechny hodinové pulzy. Jednička na příslušném bitu hodinový pulz potlačí.

| PA1 | PA0 | C4 | C3 | Hodinová maska |
|---:|---:|---:|---:|---:|
| 0 | 0 | 1 | 1 | `0xFF` |
| 0 | 1 | 1 | 0 | `0xF7` |
| 1 | 0 | 0 | 1 | `0xEF` |
| 1 | 1 | 0 | 0 | `0xE7` |

Hodinové pulzy na všech ostatních pozicích jsou pevně zapojeny na 1. Tyto kombinace slouží k zápisu indexových, adresních a datových FM značek.

Interní reprezentace stopy proto musí rozlišovat alespoň datový bajt a hodinovou masku; zvláštní značka nesmí splynout se stejným datovým bajtem zapsaným s normálními hodinami.

```c
struct FMByte {
    uint8_t data;
    uint8_t clocks; // FF, F7, EF nebo E7
};
```

### 12.3 Port B

Viz vertikální scrolling v části Video. Celých osm bitů PB se přes `/RAS`-synchronizovaný registr přičítá k čítači televizních řádků.

### 12.4 Port C: výstupy mechanik

PC0–PC3 vedou přes výkonové invertory na společný kabel mechanik. Z pohledu CPU jsou proto opačné než na mechanice:

| Bit CPU | Signál kabelu | Rovnice |
|---:|---|---|
| PC0 | `/STEP` | `/STEP = !PC0` |
| PC1 | `DIR` | `DIR = !PC1` |
| PC2 | `/TG43` | `/TG43 = !PC2` |
| PC3 | `/HEAD LOAD` | `/HEAD_LOAD = !PC3` |

Pohyb hlavy a hledání stopy 0 jsou čistě softwarové. Řadič nemá registr čísla stopy ani příkaz Seek/Restore. Emulátor drží polohu hlavy každé mechaniky v rozsahu 0–76, reaguje na platné impulzy `/STEP` a poskytuje stav Track 00. Pokus o krok pod stopu 0 polohu nezmění.

Konkrétní význam úrovně DIR pro pohyb k nule nebo k vyšší stopě je ještě třeba potvrdit.

### 12.5 Port C: vstupy mechaniky

Vstupy z mechaniky procházejí invertory. CPU proto vidí aktivní stav jako 1:

| Bit | Signál mechaniky | Hodnota čtená CPU |
|---:|---|---|
| PC4 | `/TRACK 00` | 1 = hlava na stopě 0 |
| PC5 | `/WRITE PROTECT` | 1 = médium chráněné |
| PC6 | pevná úroveň | vždy 1 |
| PC7 | `/INDEX` | 1 během indexového impulzu |

`/INDEX` vede současně do řadiče pro formátovací logiku. Samostatný signál `/READY` se nepoužívá. Software poznává připravenost podle přítomnosti periodických impulzů Index.

## 13. Portová skupina 0x70: video a myš

### 13.1 Zápis

Libovolný `OUT` do skupiny `0x70` zruší latch přerušení I4 od videa. Data nejsou významná.

### 13.2 Čtení

Libovolný `IN` ze skupiny `0x70`:

1. přečte aktuální signály myši,
2. zruší latch přerušení I3.

Jednotlivé signály myši vedou přes detektory obou hran, jsou sloučeny a přes AND řízený PA3 nastavují latch I3. Více změn před přečtením se sloučí do jediného požadavku; software přečte aktuální stav a porovná jej s dřívějším.

Čtení `0x70` neruší I4 a zápis `0x70` neruší I3.

Při PA3 = 0 nové hrany latch nenastaví. Vypnutí PA3 již zachycený požadavek neruší.

Přiřazení jednotlivých signálů myši na datové bity portu zatím není určeno.

## 14. Diskové mechaniky a médium

### 14.1 Geometrie

| Parametr | Hodnota |
|---|---:|
| mechaniky | 2 |
| průměr | 8 palců |
| strany | 1 |
| hustota | single density |
| kódování | FM |
| stopy | 77, číslované 0–76 |
| sektory na stopu | 26 |
| dat v sektoru | 128 bajtů |
| logická kapacita | 256 256 bajtů |
| otáčky | 360 RPM |
| doba otáčky | 166,666… ms |
| datová rychlost | 250 kbit/s |
| čas datového bajtu | 32 µs |

Formát odpovídá geometrii standardního osmipalcového IBM FM média. Přesné hodnoty gapů, bajty značek a jejich hodinové masky je nutné převzít ze schématu, formátovacího programu nebo referenční diskety.

### 14.2 Rotační fáze a Index

Každá mechanika má vlastní nezávislou rotační fázi. Výběr mechaniky fázi neresetuje. Index, data a formátovací logika musejí být odvozeny od stejné fáze.

- Pokud mechanika nemá otevřený obraz disku, virtuální médium se netočí a negeneruje Index.
- Obraz otevřený pouze pro čtení se otáčí a aktivuje Write Protect.
- Obraz otevřený pro čtení i zápis se otáčí a Write Protect je neaktivní.
- Track 00 je vlastnost polohy hlavy, proto může být platný i bez obrazu média.
- Na společnou sběrnici se promítá stav mechaniky zvolené PC5 datové 8255.

Přesná šířka indexového impulzu dosud není určena. Musí být konfigurovatelná a později doplněna podle konkrétní mechaniky nebo schématu. Formátovací a testovací programy měří Index vůči CPU a 8253, takže jeho perioda a fáze musí být cyklově stabilní.

### 14.3 Reprezentace stopy

Pouhý sektorový obraz nestačí pro věrné formátování a detekci značek, protože neuchová:

- rotační polohu polí,
- mezery,
- zvláštní FM hodinové vzory,
- případné přepsání části stopy,
- přesný vztah dat k Indexu.

Interní emulační formát má uchovávat celou časovanou stopu jako FM buňky, dvojice data/hodinová maska nebo přesnější tok magnetických přechodů. Běžný sektorový obraz lze podporovat jako import/export, ale při připojení je třeba jej rozvinout do úplného obrazu stopy.

### 14.4 CRC

CRC není počítáno hardwarem. Program v Z80:

- při čtení průběžně počítá CRC a porovná je se dvěma bajty ze stopy,
- při zápisu vypočítá a odešle oba CRC bajty přes datovou 8255.

Hardware zajišťuje pouze FM serializaci/deserializaci, synchronizaci na Address Mark/Data Mark, handshake, počet bajtů, časování a ukončení operace.

Přesný CRC polynom, počáteční hodnota a pořadí výsledných bajtů zatím nejsou v této specifikaci potvrzeny.

## 15. Reset

Při systémovém resetu minimálně:

- Z80 aktivuje mapu ROM + Video RAM,
- všechny 8255 přejdou do vstupního stavu,
- pull-up PA6 drží diskové časování vypnuté,
- pull-up PC5 datové 8255 dává definovanou volbu mechaniky B,
- pomocný diskový registr se vynuluje,
- RE, WRE, RDM a FOR jsou 0,
- probíhající disková operace a formátovací klopné obvody se zruší,
- prioritní maska po resetu musí odpovídat hardwarovému stavu; předpokládaná bezpečná hodnota je 0, ale je vhodné ji ověřit.

Po mode-set zápisu mohou výstupní latche 8255 přejít na nulu podle skutečného chování 8255. Emulátor nemá přeskakovat krátké nebo zdánlivě nevhodné mezistavy, pokud je testovací software může pozorovat.

## 16. Doporučené členění emulátoru

Toto je implementační doporučení, nikoli další popis hardwaru:

```text
Machine
├── Z80
├── MemoryMap
├── InterruptController3214
├── VideoTiming + VideoAddressGenerator
├── PPI8255 printer_keyboard
├── PIT8253
├── PPI8255 disk_data
├── UART8251
├── DiskAuxControl
├── PPI8255 machine_control
├── MouseEdgeLatch
└── FloppySubsystem
    ├── Drive A
    ├── Drive B
    ├── FM reader/writer
    ├── mark detectors
    ├── read/write shift registers
    └── format flip-flops
```

Periferní události se mají plánovat na společné časové ose. SDL má pouze zobrazovat dokončený nebo průběžně sestavený obraz a předávat hostitelské vstupy; nesmí být zdrojem emulovaného hardwarového času.

## 17. Dosud neurčené nebo neověřené detaily

Codex se na tyto hodnoty nemá snažit odpovědět běžnými PC konvencemi. Mají zůstat pojmenovanými parametry nebo TODO, dokud nebudou doplněny ze schématu či software:

1. Přesné speciální kódy kurzorových šipek.
2. Frekvence opakování klávesy po počáteční 1s prodlevě.
3. Datové bity jednotlivých signálů myši na čtení skupiny `0x70`.
4. Směr DIR: která kabelová úroveň znamená pohyb ke stopě 0.
5. Přesná šířka a aktivní hrana Indexu konkrétní mechaniky.
6. Přesné rozložení FM stopy: gapy, hodnoty značek a hodinové masky.
7. Přesný CRC algoritmus a pořadí CRC bajtů používané softwarem.
8. Přesné programované režimy a počáteční hodnoty jednotlivých kanálů 8253.
9. Způsob zrušení/obnovení požadavku I6 mimo ukončení formátování a nový program čítače.
10. Potvrzení řídicích slov `0xA6` pro datovou 8255 a `0x88` pro řídicí 8255 podle originálního programu nebo schématu.
11. Zapojení a výchozí úrovně ostatních modemových signálů 8251 (`CTS`, `DSR`, `RTS`, `DTR`).
12. Mechanická časování kroku, ustálení hlavy a případné prodlevy Head Load.
13. Přesné chování při současném RE a WRE; software by tuto kombinaci neměl používat, pokud není ve schématu vzájemně blokována.

## 18. Pokyn pro Codex

Při implementaci:

1. Považuj tento dokument za autoritativní popis stroje.
2. Nejprve navrhni stavové automaty a společnou časovou osu; teprve potom propojuj SDL.
3. Zachovej zrcadlení I/O přesně podle `port & 0x70`.
4. Zachovej vedlejší účinky IN/OUT i v zrcadlených adresách.
5. Nezjednodušuj disk na okamžité sektorové operace.
6. Neměň latche na krátké jednorázové události; požadavky I3 a I4 musejí trvat do explicitního zrušení.
7. U nejasných míst použij pojmenovaný parametr nebo TODO a vyžádej si doplnění, místo abys dosadil obvyklé chování PC.
8. Přidej testy alespoň pro paměťové mapy, I/O zrcadla, vektory IM2, video adresaci/scroll, 8255 handshake, 8253, rotační drift, Index a ukončení diskových operací.
