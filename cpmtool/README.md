# CP/M tool v Pythonu

Samostatný příkazový nástroj pro **výpis adresáře a zápis souborů do raw obrazů
CP/M disket**. Obsahuje také čtení souborů zpět a vytvoření prázdného obrazu.
Vyžaduje Python 3.10 nebo novější; používá pouze standardní knihovnu.

## Použití

Příkazy spusťte ve složce s `cpmtool.py`. Přepínače `-d` a `-f` patří před příkaz.

```sh
# Formáty v souboru s definicemi geometrie z cpmtools:
python3 cpmtool.py -d /etc/cpmtools/diskdefs formats

# Výpis adresáře obrazu, formát ibm-3740:
python3 cpmtool.py -d /etc/cpmtools/diskdefs -f ibm-3740 ls disk.img

# Zápis souboru do uživatelské oblasti 0, se zálohou disk.img.bak:
python3 cpmtool.py -d /etc/cpmtools/diskdefs -f ibm-3740 put disk.img program.com 0:PROGRAM.COM --backup

# Nahrazení existujícího souboru (zálohu vytvořenou výše ponechá):
python3 cpmtool.py -d /etc/cpmtools/diskdefs -f ibm-3740 put disk.img program.com 0:PROGRAM.COM --force

# Čtení souboru z obrazu do nového hostitelského souboru:
python3 cpmtool.py -d /etc/cpmtools/diskdefs -f ibm-3740 get disk.img 0:PROGRAM.COM export.com
```

Pro rychlé vyzkoušení lze použít přiložený `diskdefs`:

```sh
python3 cpmtool.py -d diskdefs -f ibm-3740 init pokus.img
python3 cpmtool.py -d diskdefs -f ibm-3740 put pokus.img README.md 0:README.TXT
python3 cpmtool.py -d diskdefs -f ibm-3740 dir pokus.img
python3 cpmtool.py -d diskdefs -f ibm-3740 get pokus.img 0:README.TXT export.txt
```

`init` vytváří prázdný obraz vyplněný bajty `E5`, bez bootloaderu a systému CP/M.
Existující obraz nepřepíše. Podrobnosti příkazů zobrazí `--help`, např.
`python3 cpmtool.py put --help`.

## Příkazy

| Příkaz | Význam |
| --- | --- |
| `formats` | Názvy definic v použitém `diskdefs` |
| `ls OBRAZ` nebo `dir OBRAZ` | Výpis všech uživatelských oblastí; `-u N` filtruje jednu |
| `put OBRAZ ZDROJ [N:JMENO.EXT]` | Zápis; bez cílového jména použije jméno zdroje v oblasti 0 |
| `get OBRAZ N:JMENO.EXT CIL` | Export do nového souboru |
| `init OBRAZ` | Vytvoření nového prázdného obrazu |

Jména CP/M se převádějí na velká písmena a musí odpovídat formátu 8.3.
Uživatelské číslo lze vynechat; výchozí je 0. Pro CP/M 2.2, P2DOS a Z-System
jsou přijímány oblasti 0–31 podle konvence cpmtools; CP/M 3 a ISX používají 0–15.
Výpis uvádí velikost v bajtech, počet alokovaných bloků a atributy
`R` (read-only), `S` (system) a `A` (archive).

Data se přenášejí binárně, včetně bajtů `00` a `1A`; nástroj nepřevádí konce
řádků. Neúplný poslední blok při zápisu doplní bajty `1A`. Přesnou délku uloží
do položky S1 podle konvence cpmtools (opačně pro ISX). U starších souborů
bez této informace se velikost určuje po 128bajtových záznamech.

## Soubor diskdefs

Lze přímo použít textový `diskdefs` z [cpmtools](https://www.moria.de/~michael/cpmtools/).
Přiložený soubor obsahuje pouze tři základní geometrie: `ibm-3740`,
`cpm86-720` a `pc1.2m`.

Bez `-d` se soubor hledá v tomto pořadí:

1. `diskdefs` v aktuálním adresáři;
2. cesta v proměnné prostředí `DISKDEFS`;
3. `/usr/local/share/cpmtools/diskdefs`, `/usr/share/cpmtools/diskdefs`,
   `/usr/local/share/diskdefs`, `/usr/share/diskdefs`,
   `/etc/cpmtools/diskdefs`, `/etc/diskdefs`;
4. přiložený `diskdefs` vedle skriptu.

Výchozí formát je `ibm-3740`. Pro skutečnou disketu vždy zvolte odpovídající
definici: CP/M její geometrii obecně neukládá do obrazu a samotná velikost
souboru ji neurčuje jednoznačně.

Podporované parametry:

| Parametr | Význam |
| --- | --- |
| `seclen` | Délka sektoru v bajtech, 128 až 4096, mocnina 2 |
| `tracks` | Počet logických stop v raw obrazu, včetně stran |
| `sectrk` | Počet sektorů na logickou stopu |
| `blocksize` | Alokační blok, 1024 až 16384 B, mocnina 2 a násobek `seclen` |
| `maxdir` | Počet 32bajtových položek adresáře |
| `boottrk` | Počet rezervovaných stop před alokačním blokem 0 |
| `skew` | Generování prokládání sektorů stejně jako v cpmtools; výchozí 1 |
| `skewtab` | Explicitní permutace fyzických sektorů číslovaných od 0, oddělená čárkami |
| `offset` | Začátek diskety/oddílu v obrazu: bajty nebo jednotky `K`, `M`, `S`/`sec`, `T`/`trk` |
| `logicalextents` | Počet logických 16KiB extentů v položce; jinak se odvodí |
| `os` | `2.2` (výchozí), `3`, `isx`, `p2dos`, `zsys` |
| `libdsk:format` | Přijímá se kvůli kompatibilitě souboru; raw přístup ho nepotřebuje |

Podporovány jsou komentáře `#` a `;`, i na konci řádku. Číselné parametry
přijímají také hexadecimální a osmičkový zápis jako cpmtools; `offset` má
desítkovou hodnotu. `skew` a `skewtab` se zadávají alternativně.
Formát vybraný pomocí `-f` se kontroluje před otevřením obrazu.

U oboustranných disket musí pořadí stran a stop v raw souboru odpovídat
definici. Nástroj neprovádí další přeskupování stran.

## Zápis a omezení

- Pracuje s běžnými soubory **raw obrazů**, nikoliv přímo s fyzickou mechanikou.
  Kontejnerové formáty DSK, IMD a HFE je nutné nejprve převést na raw.
- Podporuje 8bitové a 16bitové odkazy na bloky, více extentů, vysoké číslo
  extentu v S2 a čtení řídkých souborů. Speciální varianty s fyzickou kapacitou
  adresářové položky menší než 16 KiB odmítne.
- Před zápisem kontroluje adresář, rozsah a sdílení bloků, volné datové bloky
  a volné položky adresáře. Zjištěná chyba ponechá soubor obrazu beze změny.
- Existující soubor CP/M nahradí pouze s `--force`. Atribut read-only respektuje
  i s tímto přepínačem. Při nahrazení zachová atributové bity jména.
- `--backup` vytvoří přesnou kopii původního obrazu v `OBRAZ.bak`.
  Existující zálohu nikdy nepřepíše a v takovém případě odmítne i požadovaný zápis.
- Výsledek zapisuje do dočasného souboru ve stejném adresáři a poté atomicky
  nahradí obraz. Zachová přístupová práva, rezervované stopy, prefix/offset,
  případný konec obrazu za disketou a data ostatních souborů.
  Současné úpravy obrazu jinými programy nejsou podporovány; nástroj kontroluje
  změny původních bajtů před nahrazením, nepoužívá však sdílený zámek.
- Časové značky CP/M 3/P2DOS, hesla a DateStamper se neaktualizují. Takové
  obrazy lze vypsat a číst, ale zápis je odmítnut. Běžné návěští disku CP/M 3
  bez časových značek zůstává zachováno a zápisu nebrání.
- `get` ani `init` nepřepisují existující hostitelské soubory.

## Testy

```sh
python3 -m unittest discover -s tests -v
```

Testy pokrývají binární přenos, hraniční velikosti záznamů a extentů, obě šířky
odkazů na bloky, S2, geometrii, offset, ochranu ostatních dat, zaplněný disk
i adresář, nahrazení, zálohy, poškozené alokace a příkazové rozhraní.

Volitelně lze spustit nezávislé obousměrné ověření s původními cpmtools:

```sh
CPMTOOLS_DIR=/cesta/k/cpmtools python3 -m unittest discover -s tests -v
```

Adresář musí obsahovat `cpmcp`, `cpmls`, `mkfs.cpm` a `fsck.cpm`.
Ověření exportuje soubory z Pythonu pomocí `cpmcp`, čte soubory zapsané
`cpmcp` zpět Pythonem a kontroluje obraz nástrojem `fsck.cpm`.
Při vývoji ověřeno proti cpmtools 2.23.
