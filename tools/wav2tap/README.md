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
Rozpoznává se také jeden zakončovací pulz před pauzou po dokončeném bloku.

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
