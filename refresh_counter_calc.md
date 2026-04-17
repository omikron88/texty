# Výpočet hodnoty refresh čítače pro SDRAM

Pro SDRAM musí být každá řádka (row) obnovena jednou během celého refresh intervalu.

- `f_MHz` = frekvence hodin v MHz
- `ROW_BITS` = počet adresních bitů řádky
- `T_cycle_ms` = délka celého refresh cyklu v ms (např. 64 ms)

Počet řádků:

`ROWS = 2^ROW_BITS`

Interval mezi dvěma AUTO REFRESH příkazy:

`T_ref_ms = T_cycle_ms / ROWS`

Počet taktů mezi refresh příkazy (hodnota čítače):

`REFRESH_INTERVAL = floor(f_MHz * 1000 * T_ref_ms)`

Po dosazení `T_ref_ms`:

`REFRESH_INTERVAL = floor(f_MHz * 1000 * T_cycle_ms / (2^ROW_BITS))`

---

## Příklad (IS42S16320D)

- `f_MHz = 133`
- `ROW_BITS = 12` -> `ROWS = 4096`
- `T_cycle_ms = 64`

Výpočet:

`REFRESH_INTERVAL = floor(133 * 1000 * 64 / 4096) = floor(2078.125) = 2078`

Prakticky se často používá konzervativnější hodnota (menší interval), např. polovina (`~1040`) pro rezervu na arbitráž a latence řadiče.
