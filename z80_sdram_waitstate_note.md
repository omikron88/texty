# Z80 (3.5 MHz) vs. SDRAM bez wait stavů

## Krátká odpověď

Bez wait stavů to **není garantované** pro všechny případy provozu.

## Proč

- Perioda Z80 při 3.5 MHz je přibližně `T = 285.7 ns`.
- Čtecí cyklus CPU je omezený na několik T-stavů, takže dostupné okno pro validní data je řádově stovky ns.
- SDRAM řadič má proměnlivou latenci (refresh, arbitráž, stav automatu), tedy není čistě fixní synchronní SRAM.

## Co říká aktuální implementace

- Řadič používá `tRCD=3` cykly, `CAS_LATENCY=2`, `tRFC=10` cyklů při 133 MHz (7.5 ns/cyklus).
- Při požadavku se provádí `ACTIVATE -> WAIT(tRCD) -> READ -> WAIT(CL) -> ready`.
- Při refresh se jde do `ST_REFRESH` a čeká se `tRFC` cyklů.
- Správce (`sdram_manager`) dává prioritu video portu před CPU portem.

Z toho plyne:

1. **Typický** read může být rychlý (desítky ns až nízké stovky ns podle přesného zarovnání stavů).
2. **Nejhorší případ** je delší kvůli:
   - probíhajícímu refresh,
   - arbitráži (video priorita),
   - frontě na právě běžící transakci.

Proto bez vložení wait stavů nebo bez mezivrstvy (cache/prefetch/line-buffer) nelze časování Z80 paměťového cyklu robustně zaručit.

## Doporučení

- Pro Z80 bus přidat `WAIT` generátor (vázaný na `cpu_ready`).
- Nebo mezi Z80 a SDRAM dát rychlý buffer (např. BRAM stránku), který se doplňuje na pozadí.
- Pokud je nutný režim bez wait, pak jen pro striktně omezené mapované oblasti s garantovanou lokální RAM.

## Varianta bez `sdram_manager` (CPU je jediný klient)

V tomto případě se situace výrazně zlepší, protože odpadne arbitráž s video portem.

- Přibližná latence read cesty v aktuálním FSM vychází na jednotky až nízké desítky cyklů 133MHz domény (typicky pod ~100 ns, podle zarovnání stavů).
- I s občasným zdržením kvůli refresh (`tRFC=10` => ~75 ns) se součet typicky stále vejde do okna Z80 čtení při 3.5 MHz.

Praktický závěr:

- **Ano, je reálné** jet bez wait stavů, pokud je CPU jediný uživatel SDRAM a je dobře navržené časování rozhraní mezi Z80 a řadičem.
- **Přesto doporučuji** mít možnost wait stav vložit jako pojistku (např. při hraničním PVT, jiném mapování, nebo rozšíření návrhu do budoucna).
