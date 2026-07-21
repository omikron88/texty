# Implementační návrh emulátoru Texty

Tento návrh je implementačním doplňkem k autoritativní technické specifikaci
stroje. Je jí podřízen: zejména nepopisuje PC kompatibilní stroj a nenahrazuje
složený FM diskový řadič jedním FDC. Neurčené hodnoty zůstávají pojmenovanými
konfiguračními parametry, nikdy se nedoplňují obvyklým chováním PC.

## Pevné parametry stroje

| Vlastnost | Implementovaná hodnota |
| --- | --- |
| CPU | Z80, 4 MHz |
| společný takt | 12 MHz, tedy 3 emulační ticky na takt CPU |
| video | monochromatické 512 × 256, PAL 50 Hz, 4:3 |
| video RAM | 16 KiB, adresace sloupec-bajt × řádek |
| paměť | ROM/VRAM mapa nebo úplná 64KiB RAM mapa |
| periférie | 3 × 8255, 8253, 8251, prioritní řadič 3214 |
| mechaniky | dvě 8palcové jednostranné IBM 3740, single density FM, 77 stop, 26 × 128 B, 360 RPM |

Výměnný raw obraz má přesně **256 256 B** (`1 × 77 × 26 × 128`). Při vložení
se rozvine do 77 interních FM stop po 5 208 bajtech; Z80 nikdy nečte sektor
přímo z raw obrazu.

`Tick` je `uint64_t` a znamená jednu dvanáctimiliontinu sekundy. Všechny
události včetně CPU, PAL, 1MHz vstupu PIT, diskového bajtu a Indexu jsou
plánovány na této ose. Konkrétní periody jsou 3, 12, 384, 768, 240 000 a
2 000 000 ticků. Tím rotační Index nedriftuje vůči ostatnímu hardwaru.
SDL čas rozhoduje pouze o tom, kolik ticků má frontend doběhnout; nemění stav
stroje ani datum žádné události.

## Rozdělení zdrojových souborů

```text
src/
  core/
    machine.{h,cpp}              # plánovač, reset, sběrnice a snapshot
    z80.{h,cpp}                  # instrukce a IM2 acknowledge callback
    memory_map.{h,cpp}           # ROM, VRAM, RAM a obě mapy CPU
    interrupt3214.{h,cpp}        # priority, maska, latched IM2 vektor
    ppi8255.{h,cpp}              # režim 0/1, BSR a handshake piny
    pit8253.{h,cpp}              # tři kanály 8253, ne 8254
    uart8251.{h,cpp}
    video.{h,cpp}                # PAL události, /RAS latch a renderer RAM
    floppy.{h,cpp}               # mechaniky, FM buňky, Index, serializéry
    disk_logic.{h,cpp}           # pomocný registr, mark a format flip-flopy
  platform/
    sdl_frontend.{h,cpp}         # okno, texture, audio a vstup hostitele
  app/main.cpp
  tests/
```

`core` neincludeuje SDL a nečte hostitelský čas. Každé zařízení má metodu
`advance_to(Tick now)` nebo se registruje do prioritní fronty událostí.
Pořadí stejně časovaných událostí je součástí kontraktu: nejprve dokončení
přenosu/handshake, pak změna čítače a jeho `OUT`, potom vyhodnocení 3214.
To zaručí například, že poslední diskový bajt vyvolá I7 před I5.

## Rozhraní a plánovač

```cpp
using Tick = std::uint64_t;
constexpr Tick kCpuCycleTicks = 3;
constexpr Tick kFrameTicks = 240'000;

enum class EventPriority : std::uint8_t {
    DeviceEdge, PitOutput, InterruptSample, CpuBoundary
};

struct Event { Tick at; EventPriority priority; std::uint64_t sequence; };

class Machine {
public:
    void run_until(Tick target);
    std::uint8_t memory_read(std::uint16_t address);
    void memory_write(std::uint16_t address, std::uint8_t value);
    std::uint8_t io_read(std::uint16_t port);
    void io_write(std::uint16_t port, std::uint8_t value);
};
```

Z80 spotřebovává T-stavy v násobcích tří ticků, ale zařízení mohou mít událost
i mezi instrukcemi. `run_until` proto vždy spustí nejbližší událost před dalším
mikrokrokem CPU; přerušení CPU přijme pouze při svém potvrzovacím cyklu.
Prioritní řadič při tomto cyklu zachytí nejvyšší povolený aktivní vstup a vrátí
IM2 vektor `0x00, 0x02, …, 0x0e` pro I7 až I0. Potvrzení nesmí rušit I3/I4
latche; jejich explicitní zrušení probíhá pouze přes skupinu portů `0x70`.

## Paměť a I/O sběrnice

`MemoryMap` vlastní tři fyzická úložiště: 16KiB ROM, 16KiB VRAM a 64KiB
hlavní RAM. Po resetu CPU čte/zapisuje `0000–3fff` ROM (zápisy ignoruje),
`4000–7fff` VRAM a `8000–ffff` hlavní RAM. Čtení skupiny I/O `0x30` přepne
mapu na celou 64KiB RAM; čtení `0x50` obnoví ROM/VRAM. Obě vracejí `0xff`.
Video čte VRAM vždy, bez ohledu na aktuální mapu CPU.

Dekodér používá výhradně `port & 0x70`; horní bajt a A7 se ignorují. Pro
8255/8253 je registr `port & 0x03`, pro UART `port & 0x01`. Každé zrcadlo má
stejné vedlejší účinky jako základní port. Nedržená data sběrnice vracejí
`0xff`.

| skupina | čtení | zápis |
| --- | --- | --- |
| `0x00` | PPI tiskárny/klávesnice | totéž |
| `0x10` | 8253 | 8253 |
| `0x20` | datová PPI disku | totéž |
| `0x30` | RAM mapa, `ff` | maska 3214 |
| `0x40` | 8251 | 8251 |
| `0x50` | ROM/VRAM mapa, `ff` | pomocný diskový registr |
| `0x60` | řídicí PPI disku/videa | totéž |
| `0x70` | myš, clear I3 | clear I4 |

## Video

PAL generátor plánuje řádkové události po 768 tickách a snímkovou událost po
240 000 tickách. Přesný počet řádků, poloha aktivní oblasti a V pulzu musí
zůstat parametry, protože jejich kombinaci specifikace zatím neurčuje.
Aktivních 256 zdrojových řádků se převádí na
512 × 256 ARGB8888 framebuffer. Pixel `x,y` bere bit `0x80 >> (x & 7)` z
`vram[((x >> 3) << 8) | source_y]`; jednička je bílá, nula černá.

Port B řídicí PPI (`0x61`) je nutné držet ve dvou registrech:
`video_scroll_ppi` a `video_scroll_latched`. První se mění zápisem PPI,
druhý přesně na modelované hraně `/RAS`; `source_y` je osmibitový součet
televizního řádku a latched hodnoty. PPI PA2 povolí zachycení následujícího
V pulzu do latche I4. V pulz současně a nezávisle taktuje kanál 0 PIT.

Frontend vytvoří SDL3 streaming texture v ARGB8888 a zobrazuje ji nearest
neighbour v poměru 4:3 (např. 1024 × 768). Nesmí vytvářet video přerušení ani
časovat řádky podle renderování.

## Periférie a vstup

Obecný `Ppi8255` implementuje mode-set, BSR, portové latche a mode 0/1.
Konkrétní zapojení jej propojí následovně:

- PPI `0x00`: PA/PC7 tiskárna; PC6 je ACK, PC3 vede na I0. PB/PC2 přijímá
  jednobajtovou klávesnici; PC0 vede na I1.
- PPI `0x20`: handshake PA/PB nese bajty mezi CPU a diskovým serializérem;
  obě `INTR` vedou na I7 a jejich logický součet hranově taktuje PIT2. PC5
  vybírá mechaniku A/B.
- PPI `0x60`: PA0/PA1 volí FM masku `ff/f7/ef/e7`; PA2 a PA3 hradlují I4 a
  I3; PA6 je aktivně nízké povolení diskového časování. PB řídí scrolling.
  PC0–PC3 jsou invertované výstupy STEP, DIR, TG43 a HEAD LOAD; PC4–PC7
  poskytují Track 00, Write Protect, pevnou jedničku a Index.

Klávesové stisky SDL se převádějí na ASCII (Backspace `0x7f`) a vkládají jako
impuls STB do PPI, nikdy ne jako autorepeat OS. Po 1 sekundě emulovaného času
spouští opakování parametr `keyboard_repeat_period_ticks`, dokud nebude jeho
skutečná hodnota potvrzena. Neznámé kódy šipek a bity myši jsou explicitní
konfigurace s bezpečným výchozím `0xff` pro čtení myši.

`Pit8253` neimplementuje Read-Back. CLK0 přichází z V pulzu, CLK1 každých 12
ticků a CLK2 pouze na náběžné hraně `INTR_A || INTR_B` diskové PPI. Při aktivní
časovací části disku je GATE1 `disk_sync_latch`, jinak jednička. OUT2 zruší
pomocný diskový registr a nastaví I5; OUT1 hodinově pohání obě strany 8251.
UART I2 je úrovňový signál `TXRDY || RXRDY`.

## Disková časová cesta

`FloppyDrive` udržuje pro každou mechaniku nezávislou fázi modulo 2 000 000
ticků a polohu hlavy 0–76. Fáze se rozbíhá pouze s připojeným obrazem; výběr
mechaniky ji neresetuje. Index je aktivní po konfigurovatelnou
`index_pulse_width_ticks`, protože šířka není potvrzena. Stav Track 00 platí
i bez média, Write Protect je aktivní pro read-only obraz.

Stopa je 5 208 `FMByte`, kde položka obsahuje `data` a `clocks`; mezi
datovými bajty je 384 ticků. Formát importeru IBM 3740 je přesně: 40×`ff`,
6×`00`, Index Mark (`d7/fc`), 26×`ff`, pro každý z 26 sektorů 6×`00`, Address
Mark (`c7/fe`), CHRN (`track`, `0`, `1..26`, `0`), CRC, 11×`ff`, 6×`00`, Data
Mark (`c7/fb`), 128 datových bajtů, CRC a 27×`ff`; stopu uzavírá 247×`ff`.
Ostatní bajty mají hodinovou masku `ff`. Posledních 128 ticků do Indexu není
datový bajt, takže rotační perioda zůstane přesně 2 000 000 ticků.

CRC je CRC-16/CCITT (`poly=0x1021`, `init=0xffff`), MSB-first. Počítá se od
Address/Data Mark včetně až po poslední datový bajt a zapisuje se high byte,
potom low byte.

Pomocný registr z `OUT 0x50` interpretuje jen D0 RE, D1 WRE, D2 RDM a D4 FOR.
Jeho reset nastane při resetu, OUT2, deaktivaci PA6 nebo druhém Indexu při FOR.
RE čeká na Address Mark nebo Data Mark podle RDM, než začne strobovat čtená
data. FOR zapisuje přesně mezi prvním a druhým Indexem; druhý Index resetuje
registr a vyvolá I6. Běžný přenos nikdy nesmí být nahrazen okamžitým čtením
sektoru: musí postupovat po FM bajtech, handshaku PPI a čase 384 ticků.

## Snapshoty, reset a neuzavřené parametry

Snapshot obsahuje `Tick`, frontu událostí včetně pořadí, celý stav Z80,
mapu paměti, latche PPI/PIT/UART/3214, VRAM, oba stavy mechanik i jejich FM
stopy. Načtení ověřuje magic, verzi, délky a hranice alokací. Reset nastaví
ROM/VRAM mapu, všechny PPI do vstupu, diskový registr na nulu, diskové
časování vypnuté pull-upem PA6 a bezpečnou masku 3214 `0`.

Následující položky jsou parametry/TODO, nikoli vymyšlené konstanty: směr DIR,
šířka a hrana Indexu, inicializace PIT,
modemové piny 8251, mechanické prodlevy a souběh RE/WRE. Každá hodnota musí
být dohledatelná ve schématu nebo v testovaném softwaru předtím, než se stane
výchozím chováním.

## Boot EPROM jako spustitelný důkaz

Dodaná Intel HEX boot EPROM musí být uložena jako binární ROM o velikosti
16 KiB a použita v integračních testech; kontrolní součet jednotlivých HEX
záznamů se před převodem ověří. Její inicializace potvrzuje řídicí slova PPI:

| zápis ROM | význam |
| --- | --- |
| `LD A,0xae; OUT (0x03),A` | PPI tiskárny/klávesnice (`0x00`) |
| `LD A,0xa6; OUT (0x23),A` | datová PPI disku (`0x20`) |
| `LD A,0x88; OUT (0x63),A` | řídicí PPI disku/videa (`0x60`) |

ROM dále bezprostředně čte skupinu `0x30` a skáče do RAM na `0x8000`, což je
regresní test vedlejšího účinku přepnutí paměťové mapy. Před zavedením CP/M
programuje PPI/PIT a diskové porty, proto nestačí testovat jednotlivé porty
izolovaně: headless test musí nechat ROM dosáhnout prvního požadavku na data
disku. Trace tohoto běhu se uloží jako referenční posloupnost I/O operací;
změna trace vyžaduje vysvětlení v testu, nikoli pouze aktualizaci golden souboru.

## Testovací milníky

1. Unit testy paměťových map a všech I/O zrcadel ověří `port & 0x70`, návrat
   `ff` i vedlejší účinky každého IN/OUT.
2. Test 3214 ověří masku, priority I7→I0 a IM2 vektory; test I3/I4 ověří
   set i explicitní clear bez clear při acknowledge.
3. Video test ověří adresaci prvních dvou řádků, MSB pixelu a změnu scrollu
   právě na `/RAS`.
4. Testy 8255/8253 ověří handshake, BSR, LSB/MSB, latch a hranu OR pro PIT2.
5. Diskový test běží více otáček, ověří stabilní Index bez driftu, nezávislé
   fáze mechanik, výběr PC5, FM masky, mark synchronizaci, OUT2 a druhý Index
   při formátování.
6. Headless test přehraje stejný záznam vstupu dvakrát a porovná hash stavu po
   každém PAL snímku. SDL test pouze ověří upload hotového framebufferu.
7. Boot-EPROM test ověří Intel HEX kontrolní součty, PPI inicializace `ae`,
   `a6`, `88`, přepnutí čtením `0x30` a deterministickou I/O trace až k prvnímu
   diskovému přenosu.
