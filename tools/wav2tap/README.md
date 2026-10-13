# WAV → TAP pro ZX Spectrum

První verze převádí mono nebo stereo WAV se standardním ROM časováním na TAP.
Používá pilot 2168 T-stavů, synchronizaci 667/735 a dva pulzy 855 nebo 1710
T-stavů na bit. Rychlost se kalibruje podle pilotu a během dat pomalu sleduje.
Turbo loadery, ochrany a výstup TZX zatím nejsou podporovány.
Podporovány jsou standardní soubory s hlavičkou i samostatné bloky bez hlavičky.

## Instalace a použití

Z kořene repozitáře:

```bash
python3 -m venv /workspace/.wav2tap-venv
/workspace/.wav2tap-venv/bin/python -m pip install -r tools/wav2tap/requirements.txt
/workspace/.wav2tap-venv/bin/python -m tools.wav2tap kazeta.wav program.tap --report program.json
```

V prostředí, které již obsahuje NumPy a SciPy, postačí:

```bash
python3 -m tools.wav2tap kazeta.wav program.tap --report program.json
```

Podporovány jsou běžné nekomprimované celočíselné PCM a IEEE float WAV,
mono nebo stereo, se vzorkovací frekvencí alespoň 22050 Hz. Pro digitalizaci
preferujte 48 nebo 96 kHz. Stereo kanály se nesčítají: každý se dekóduje
samostatně a blok lze získat z kteréhokoli kanálu. Opačná polarita nevadí.

Převodník odstraní pomalý drift středu horní propustí 40 Hz, omezí vysokofrekvenční
šum a potvrdí průchody nulou adaptivní hysterezí. Čas hrany interpoluje mezi
vzorky. Hystereze sleduje místní amplitudu a odhad šumu; zkouší tři nastavení.
Bit klasifikuje podle délky celé dvojice pulzů, s kontrolou jednotlivých pulzů.
Kauzální korekce středu brání tomu, aby následující pauza ovlivnila slabé koncové pulzy.
Krátké zákmity pod přibližně 86 µs se odstraňují jako dvojice hran, od nejkratšího
zákmitu. Zachovává se tím polarita a skutečná hrana vedle zákmitu. Tento filtr
je určen pro podporované standardní časování; velmi krátké pulzy turbo loaderů
vyžadují jiné zpracování.

Na přechodu ze silného pilotu do slabé synchronizace mohou být jednotlivé hrany
posunuté. Synchronizace proto kontroluje obě délky i jejich součet: nejvýše 40 %
odchylky jednotlivého pulzu a 20 % odchylky celé dvojice od délky kalibrované pilotem.
Dvojice datových nul se tak nepovažuje za synchronizaci. Platnost výsledných
bajtů se nadále ověřuje XOR.

Pokud některý blok nezvládne detektor průchodů nulou, automaticky se vyzkouší
záložní detektor střídajících se maxim a minim. Umí najít i kmit, jehož minimum
zůstává nad nulou, nebo maximum pod nulou. Používá dvě dolní propusti,
3500 a 5000 Hz, a lokální požadavek na prominenci extrémů s podlahou podle šumu.
Odhad vstupního šumu přepočítává podle šířky pásma každé dolní propusti,
včetně dvojího průchodu při filtraci bez fázového posunu. Pro každý filtr zkouší
prominenci 8 %, 4 % a 2 % místní obálky s podlahou 3σ. Další citlivý pokus
vyžaduje 0,5 % obálky a 1σ; umožňuje zachytit velmi mělké, ale skutečně přítomné
extrémy. Filtrovaná data se mezi pokusy sdílejí.
Nový blok přijme pouze při shodě všech bajtů mezi oběma filtry, platném XOR
a stejné časové poloze. Ověřené výsledky průchodů nulou mají přednost.

Extrémy přibližně označují středy pulzů, ale kmitočtová závislost záznamu jejich
polohy posouvá. Bit se rozlišuje podle celé dvojice s nejvýše 22% odchylkou
její délky. Kontroluje se přitom běžná geometrie i přechodová délka podle
předchozího bitu. Vnitřní extrém smí být výrazně posunutý: jednotlivé intervaly
musí zůstat v rozmezí 20–180 % své modelové délky. Rychlost se aktualizuje z celé
dvojice, nikoli ze samotného posunutého půlpulzu.
Synchronizace zahrnuje geometrii středů na přechodu z pilotu i rozšířený přechod,
v němž jsou slabé synchronizační kmity slité nebo tvoří jen mělký krátký zákmit.
Krátký zákmit může navazovat na interval, který ještě vypadal jako poslední
pilotní pulz. Tento režim nedoplňuje chybějící datové pulzy ani neopravuje
bajty. Shoda filtrů a XOR zvyšují důvěryhodnost, nejsou silnou kontrolou integrity.
Skutečný výpadek signálu může nadále znemožnit načtení celého bloku.

Do TAP se ukládají původní bajty včetně příznaku a XOR kontrolního součtu,
s dvoubajtovou little-endian délkou každého bloku. Kontrolní součty se neopravují
a neznámé bity se nehádají. Délka bloku se určuje z pulzů až ke konci záznamu
nebo pauze, nikoli z první nalezené shody XOR či délky předchozí hlavičky.
Standardní hlavička má 19 bajtů; kontroluje se také
přítomnost a délka následujícího datového bloku. TAP nezachovává skutečnou
rychlost ani časové rozestupy na kazetě.

## Bloky bez hlavičky

Běžné bloky bez hlavičky se rozpoznávají automaticky. Mohou mít libovolný
příznakový bajt, včetně `0` a `255`, a nemusí jim předcházet hlavička souboru.
Do TAP se ukládají beze změny; název, adresy ani umělá hlavička se nedoplňují.
Stále se vyžaduje standardní pilot a synchronizace, celé bajty a platný XOR.
Rozpoznává se také jeden nebo dva omezené zakončovací pulzy před potvrzenou
pauzou po dokončeném bloku s platným XOR. Zakončení se posuzuje pouze při
neplatné datové dvojici; platná navazující data se podle shody XOR neuseknou.

Za hlavičku se automaticky považuje pouze ověřený blok dlouhý 19 bajtů
s příznakem `0` a typem souboru `0` až `3`. Pokud se bezhlavičková data
náhodou shodují s touto strukturou, nelze je ze samotných bajtů odlišit.
Pro takovou nahrávku použijte:

```bash
python3 -m tools.wav2tap kazeta.wav program.tap --headerless --report program.json
```

Přepínač `--headerless` chápe všechny bloky v nahrávce jako data. Vypíná
interpretaci názvů a kontrolu dvojic hlavička–data, ale zachovává kontrolu pulzů,
celých bajtů i XOR. JSON uvádí tento režim v položce `headerless` a klasifikaci
jednotlivých bloků v položce `is_header`.

## Chyby a protokol

Při rozpoznaném poškozeném bloku se standardně TAP nevytvoří a návratový kód je 1.
Protokol JSON se přesto uloží, byl-li požadován. Obsahuje pozice bloků,
délky, názvy z hlaviček, kanál a rychlostní faktor: hodnota nad 1 znamená
delší pulzy než nominální. Čísla kanálů v JSON jsou od nuly; textový výpis od jedné.
Položka `detector` uvádí `zero_crossing` nebo `extrema`; `lowpass_hz` identifikuje
filtr záložního detektoru. `noise_multiplier` uvádí použitý násobek odhadu šumu
(3, případně 1 v citlivém pokusu). Časy v jeho stopě odpovídají polohám extrémů.
Z více chybových pokusů pro stejný blok se zobrazí ten, který se dostal nejdále.

Pro vědomé uložení pouze dostupných ověřených bloků použijte:

```bash
python3 -m tools.wav2tap kazeta.wav cast.tap --allow-partial --report cast.json
```

Částečný výstup může například obsahovat hlavičku bez odpovídajících dat a nemusí
tedy obsahovat načitatelný program. Pokud kanály nebo nastavení detektoru vytvoří
různé bloky se stejně platným XOR, nejednoznačný blok se neuloží ani v tomto režimu.
Existující výstup nebo protokol se nepřepisují. Bez jediného ověřeného bloku
se TAP nevytvoří a návratový kód je 1.

Rozpoznání neúspěšných bloků vyžaduje detekovatelný pilot. Úplně smazaný nebo
nestandardní záznam nelze odlišit od jiného zvuku; úspěšný převod proto není
zárukou nalezení veškerého obsahu kazety. XOR také není silná kontrola integrity.
První verze načítá WAV do paměti, takže dlouhé nahrávky mají vyšší paměťové nároky.

## Diagnostické grafy

Pro export grafů do PNG, SVG nebo PDF nainstalujte volitelný Matplotlib:

```bash
python3 -m pip install -r tools/wav2tap/requirements-plot.txt
python3 -m tools.wav2tap kazeta.wav program.tap --plot diagnostika.png --report program.json
```

Používáte-li výše vytvořené virtuální prostředí, nahraďte `python3` cestou
`/workspace/.wav2tap-venv/bin/python`. Běžný převod bez `--plot` Matplotlib nevyžaduje.
Export funguje také na serveru bez grafického prostředí.

Každý kanál má čtyři grafy:

1. Přehled původního WAV s ověřenými bloky, chybovými úseky a zvoleným detailem.
2. Detail původního a filtrovaného signálu, obou prahů hystereze a potvrzených hran.
3. Délky jednotlivých pulzů v detailu s referencemi pro synchronizaci, bity a pilot.
4. Histogram délek pulzů v celém kanálu; dlouhé pauzy mimo rozsah se uvádějí počtem.

Zelená označuje bloky přijaté do výsledku z daného kanálu. Červená označuje
nevyřešené chybové úseky; přerušovaná čára je konec úseku, kde se chyba zjistila.
Při chybě XOR je to konec bloku, nikoli automaticky místo poškozeného bitu.
Ověřený blok získaný z druhého kanálu se do zelených úseků prvního kanálu nepřidává.

Výchozí detail trvá 20 ms a zamíří na první chybu, jinak na začátek dat prvního
ověřeného bloku. Vlastní přiblížení určíte časem v sekundách od začátku WAV:

```bash
python3 -m tools.wav2tap kazeta.wav --diagnostics-only --plot detail.svg --plot-start 12.4 --plot-duration 0.03
```

Režim `--diagnostics-only` nevyžaduje cestu TAP a ukládá pouze požadovaný graf
nebo JSON protokol. Výstup TAP se v tomto režimu nevytváří. Lze ho využít
i k analýze nahrávky, kterou se nepodařilo dekódovat; návratový kód zůstává 1
při chybách nebo při absenci ověřeného bloku. Graf i JSON se uloží také při
neúspěšném běžném převodu. Existující graf se nepřepisuje.

Graf používá uložené stopy z aktuálního dekódování. V detailu ověřeného bloku
se zobrazí právě použité nastavení hystereze, uvedené také v jeho JSON položce
`threshold_fraction`. U detektoru extrémů tato položka určuje relativní požadavek
na prominenci; v grafu se zobrazují fialové body ve skutečných maximech a minimech
příslušného filtrovaného signálu. Tyto body nejsou průchody nulou. Intervaly mezi
extrémy a jejich histogram mají vlastní popisky a referenci pro přechod 0 ↔ 1.
Pokud detail obsahuje chybové místo, má přednost nastavení
tohoto chybového pokusu. Jinde se použije základní práh `0.06`.
Referenční délky se kalibrují podle pilotu ověřeného bloku ve středu detailu;
bez něj jsou nominální pro 3,5 MHz. Histogram pokrývá celý kanál se stejným
nastavením detektoru jako detail, takže může zahrnovat bloky s jinými rychlostmi.

Přehled používá minima a maxima vzorků v časových oknech, aby nezmizely krátké
výpadky. Stejně se zjednodušují dlouhé detaily; u více než 1500 hran se vykreslí
jejich podmnožina a v titulku je zobrazený/celkový počet. Pro jednotlivé pulzy
použijte krátké přiblížení. Diagnostika uchovává filtrované signály a tři sady
hran průchodů nulou a případné stopy záložního detektoru každého kanálu,
proto má vyšší paměťové nároky než samotný převod.

## Ověření

```bash
python3 -m unittest discover -s tests/wav2tap -v
```

Testy používají nezávislý generátor ROM pulzů. Ověřují bajtově přesný TAP včetně 48KB dat,
PCM a float WAV, skutečné spuštění CLI, stereo s opačnou polaritou i výpadkem
kanálu, kolísání rychlosti, drift středu, menší amplitudu krátkých pulzů,
šum a odmítnutí poškozených nebo neúplných bloků. Dále ověřují různé délky
a příznaky bezhlavičkových bloků, smíšené nahrávky, krátký zakončovací pulz,
rozlišení dat podobných hlavičce a zachování všech bajtů za platným XOR prefixem.
Ověření na skutečné historické
kazetě je potřeba provést s konkrétní nahrávkou.

Testy grafů vyžadují `requirements-plot.txt`; bez Matplotlib se přeskočí.
Kontrolují skutečné vzorky, prahy a hrany ve vykresleném detailu, mono/stereo,
ticho, export všech tří formátů, ochranu souborů a diagnostiku neúspěšného převodu.

Regresní vzorek [leonardo_header.wav](../../tests/wav2tap/fixtures/leonardo_header.wav)
obsahuje skutečnou slabou synchronizaci a zákmit v pilotu. Test vyžaduje přesné
bajty hlavičky v obou polaritách. Protože jde o výřez samotné hlavičky, hlášení
o chybějícím navazujícím datovém bloku je očekávané. Podrobnosti jsou v
[popisu vzorku](../../tests/wav2tap/fixtures/README.md).
Vzorky `desktop_header.wav` a `desktop_dropout.wav` navíc ověřují synchronizaci
s minimem nad nulou, shodu záložních filtrů a odmítnutí bloku se skutečným výpadkem.
Výřezy nového načtení `desktop_new_header.wav`, `desktop_new_code_header.wav`
a `desktop_new_weak_zero.wav` ověřují rozšířenou synchronizaci, silně posunutý
vnitřní extrém krátkého pulzu a čtení v obou polaritách. Samostatný test měří
útlum bílého šumu skutečnou filtrací a porovnává jej s odhadem šumové podlahy.
