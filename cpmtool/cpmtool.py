#!/usr/bin/env python3
"""Directory listing and file transfer for raw CP/M disk images (Python 3.10+)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


class CPMError(Exception):
    """An invalid format, image, filename, or requested operation."""


def number(value: str) -> int:
    """Accept C-style integers, as diskdefs does, including octal."""
    if re.fullmatch(r"0[0-7]+", value):
        return int(value, 8)
    return int(value, 0) if value.lower().startswith(("0x", "0o")) else int(value)


def read_diskdefs(path: Path) -> dict[str, dict[str, str]]:
    """Read definitions without validating unrelated formats in a vendor file."""
    definitions: dict[str, dict[str, str]] = {}
    current = None
    for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = re.split(r"[#;]", line, maxsplit=1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 1)
        key = parts[0].lower()
        if key == "diskdef" and len(parts) == 2:
            if current is not None:
                current["__error__"] = f"{path}:{lineno}: chybí end před dalším diskdef"
            name = parts[1].strip()
            if name in definitions:
                raise CPMError(f"{path}:{lineno}: duplicitní diskdef {name}")
            current = definitions[name] = {}
        elif key == "end" and len(parts) == 1 and current is not None:
            current = None
        elif current is not None and len(parts) == 2 and key not in ("diskdef", "end"):
            if key in current:
                raise CPMError(f"{path}:{lineno}: duplicitní parametr {key}")
            current[key] = parts[1].strip()
        else:
            raise CPMError(f"{path}:{lineno}: neplatný řádek diskdefs")
    if current is not None:
        current["__error__"] = f"{path}: chybí end"
    return definitions


@dataclass(frozen=True)
class Geometry:
    name: str
    seclen: int
    tracks: int
    sectrk: int
    blocksize: int
    maxdir: int
    boottrk: int
    skewtab: tuple[int, ...]
    offset: int = 0
    logicalextents: int = 1
    os_type: str = "2.2"

    @property
    def block_count(self) -> int:
        return (self.tracks - self.boottrk) * self.sectrk * self.seclen // self.blocksize

    @property
    def directory_blocks(self) -> int:
        return math.ceil(self.maxdir * 32 / self.blocksize)

    @property
    def pointer_size(self) -> int:
        return 1 if self.block_count < 256 else 2

    @property
    def extent_capacity(self) -> int:
        return self.logicalextents * 16384

    @property
    def image_size(self) -> int:
        return self.offset + self.tracks * self.sectrk * self.seclen

    @property
    def max_user(self) -> int:
        # CP/M 3 uses status 16..31 for password records, not user files.
        return 15 if self.os_type in ("3", "isx") else 31

    @classmethod
    def from_definition(cls, name: str, values: dict[str, str]) -> Geometry:
        if "__error__" in values:
            raise CPMError(values["__error__"])
        required = {"seclen", "tracks", "sectrk", "blocksize", "maxdir", "boottrk"}
        allowed = required | {"skew", "skewtab", "offset", "logicalextents", "os", "libdsk:format"}
        if required - values.keys():
            raise CPMError(f"{name}: chybí {', '.join(sorted(required - values.keys()))}")
        if values.keys() - allowed:
            raise CPMError(f"{name}: nepodporované parametry: {', '.join(sorted(values.keys() - allowed))}")
        try:
            args = {key: number(values[key]) for key in required}
            seclen, sectrk = args["seclen"], args["sectrk"]
            if seclen not in (128, 256, 512, 1024, 2048, 4096):
                raise CPMError(f"{name}: nepodporovaná délka sektoru")
            if sectrk <= 0 or args["tracks"] <= 0 or not 0 <= args["boottrk"] < args["tracks"]:
                raise CPMError(f"{name}: neplatné stopy nebo sektory")
            blocksize = args["blocksize"]
            if blocksize < 1024 or blocksize > 16384 or blocksize & (blocksize - 1) or blocksize % seclen:
                raise CPMError(f"{name}: blocksize musí být mocnina 2, 1024..16384, násobek seclen")
            if args["maxdir"] <= 0:
                raise CPMError(f"{name}: maxdir musí být kladné")
            if "skew" in values and "skewtab" in values:
                raise CPMError(f"{name}: použijte buď skew, nebo skewtab")
            if "skewtab" in values:
                table = tuple(number(x.strip()) for x in values["skewtab"].split(","))
            else:
                skew = number(values.get("skew", "1"))
                if skew < 0:
                    raise CPMError(f"{name}: skew nesmí být záporné")
                generated: list[int] = []
                used: set[int] = set()
                sector = 0
                for _ in range(sectrk):
                    while sector in used:
                        sector = (sector + 1) % sectrk
                    generated.append(sector)
                    used.add(sector)
                    sector = (sector + skew) % sectrk
                table = tuple(generated)
            if len(table) != sectrk or set(table) != set(range(sectrk)):
                raise CPMError(f"{name}: skewtab musí být permutace sektorů 0..{sectrk - 1}")
            offset_match = re.fullmatch(r"(\d+)\s*([A-Za-z]*)", values.get("offset", "0"))
            if not offset_match:
                raise CPMError(f"{name}: neplatný offset")
            units = {"": 1, "k": 1024, "m": 1024**2, "s": seclen, "sec": seclen,
                     "t": seclen * sectrk, "trk": seclen * sectrk}
            unit = offset_match[2].lower()
            if unit not in units:
                raise CPMError(f"{name}: neznámá jednotka offsetu {unit}")
            offset = int(offset_match[1]) * units[unit]
            count = (args["tracks"] - args["boottrk"]) * seclen * sectrk // blocksize
            pointer_count = 16 if count < 256 else 8
            extents = number(values.get("logicalextents", "0"))
            if extents == 0:
                extents = max(1, pointer_count * blocksize // 16384)
            if extents < 1 or extents & (extents - 1) or extents * 16384 > pointer_count * blocksize:
                raise CPMError(f"{name}: nepodporované logicalextents nebo malý blocksize")
            os_type = values.get("os", "2.2").lower()
            if os_type not in ("2.2", "3", "isx", "p2dos", "zsys"):
                raise CPMError(f"{name}: nepodporovaný OS {os_type}")
            result = cls(name=name, **args, skewtab=table, offset=offset,
                         logicalextents=extents, os_type=os_type)
        except ValueError as exc:
            raise CPMError(f"{name}: neplatná číselná hodnota: {exc}") from exc
        if not 1 < result.block_count <= 65536:
            raise CPMError(f"{name}: počet bloků je mimo rozsah CP/M")
        if not 1 <= result.directory_blocks < result.block_count or result.directory_blocks > 16:
            raise CPMError(f"{name}: adresář se nevejde do vyhrazených bloků CP/M")
        return result


def split_name(spec: str, max_user: int = 31) -> tuple[int, bytes]:
    match = re.fullmatch(r"(?:(\d{1,2}):)?([^:]+)", spec)
    if not match:
        raise CPMError("jméno musí mít tvar [uživatel:]JMENO.EXT")
    user = int(match[1] or "0")
    if not 0 <= user <= max_user:
        raise CPMError(f"uživatel musí být v rozsahu 0..{max_user}")
    name = match[2].upper()
    parts = name.split(".")
    base, ext = parts[0], parts[1] if len(parts) == 2 else ""
    forbidden = set(' <>.,;:=?*[]/\\|"')
    if (len(parts) > 2 or not 1 <= len(base) <= 8 or len(ext) > 3
            or any(ord(c) < 33 or ord(c) > 126 or c in forbidden for c in base + ext)):
        raise CPMError(f"neplatné jméno CP/M 8.3: {name}")
    return user, (base.ljust(8) + ext.ljust(3)).encode("ascii")


@dataclass(frozen=True)
class Entry:
    index: int
    raw: bytes
    geometry: Geometry

    @property
    def key(self) -> tuple[int, bytes]:
        return self.raw[0], bytes(c & 0x7f for c in self.raw[1:12])

    @property
    def name(self) -> str:
        name = self.key[1][:8].decode("ascii").rstrip()
        ext = self.key[1][8:].decode("ascii").rstrip()
        return name + ("." + ext if ext else "")

    @property
    def extent(self) -> int:
        return (self.raw[12] & 31) | ((self.raw[14] & 63) << 5)

    @property
    def group(self) -> int:
        return self.extent // self.geometry.logicalextents

    @property
    def size(self) -> int:
        size = self.extent * 16384 + self.raw[15] * 128
        if self.raw[15]:
            if self.geometry.os_type == "isx":
                size -= self.raw[13]
            elif self.raw[13]:
                size -= 128 - self.raw[13]
        return size

    @property
    def local_size(self) -> int:
        return self.size - self.group * self.geometry.extent_capacity

    @property
    def blocks(self) -> tuple[int, ...]:
        step = self.geometry.pointer_size
        return tuple(int.from_bytes(self.raw[pos:pos + step], "little") for pos in range(16, 32, step))

    @property
    def attributes(self) -> str:
        return "".join(letter if self.raw[pos] & 0x80 else "-"
                       for pos, letter in ((9, "R"), (10, "S"), (11, "A")))


class DiskImage:
    """In-memory changes; save() atomically replaces a regular image file."""

    def __init__(self, data: bytes, geometry: Geometry):
        self.geometry = geometry
        if data.startswith((b"MV - CPCEMU", b"EXTENDED CPC DSK", b"IMD ", b"HXCPICFE")):
            raise CPMError("kontejnerový obraz není podporován; převeďte jej na raw")
        if len(data) < geometry.image_size:
            raise CPMError(f"obraz je příliš krátký: {len(data)} B, geometrie vyžaduje {geometry.image_size} B")
        self.original = bytes(data)
        self.data = bytearray(data)

    def _sector_offset(self, logical_sector: int) -> int:
        g = self.geometry
        track, sector = divmod(logical_sector, g.sectrk)
        return g.offset + (track * g.sectrk + g.skewtab[sector]) * g.seclen

    def read_block(self, block: int) -> bytes:
        g = self.geometry
        if not 0 <= block < g.block_count:
            raise CPMError(f"blok {block} je mimo obraz")
        start = g.boottrk * g.sectrk + block * (g.blocksize // g.seclen)
        return b"".join(self.data[pos:pos + g.seclen]
                        for pos in (self._sector_offset(start + n) for n in range(g.blocksize // g.seclen)))

    def _write_block(self, block: int, data: bytes) -> None:
        g = self.geometry
        if not 0 <= block < g.block_count or len(data) != g.blocksize:
            raise CPMError("neplatný zápis bloku")
        start = g.boottrk * g.sectrk + block * (g.blocksize // g.seclen)
        for n in range(g.blocksize // g.seclen):
            pos = self._sector_offset(start + n)
            self.data[pos:pos + g.seclen] = data[n * g.seclen:(n + 1) * g.seclen]

    def directory(self) -> bytes:
        return b"".join(self.read_block(n) for n in range(self.geometry.directory_blocks))

    def entries(self) -> list[Entry]:
        directory = self.directory()
        g = self.geometry
        return [Entry(n, directory[n * 32:(n + 1) * 32], g) for n in range(g.maxdir)
                if directory[n * 32] <= g.max_user]

    def files(self) -> dict[tuple[int, bytes], list[Entry]]:
        files: dict[tuple[int, bytes], list[Entry]] = {}
        for entry in self.entries():
            files.setdefault(entry.key, []).append(entry)
        return files

    def validate(self, *, writing: bool = False) -> set[int]:
        """Refuse unsafe allocations, cross-links, and inconsistent extents."""
        g = self.geometry
        used = set(range(g.directory_blocks))
        directory = self.directory()
        statuses = {directory[n * 32] for n in range(g.maxdir)}
        special = statuses - set(range(g.max_user + 1)) - {0xe5}
        allowed_metadata = {0x20, 0x21} if g.os_type in ("3", "p2dos") else set()
        if g.os_type == "3":
            allowed_metadata |= set(range(16, 32))
        if special - allowed_metadata:
            raise CPMError("neznámé položky adresáře; zkontrolujte formát, skew a stav obrazu")
        if writing and (special - {0x20} or any(
                directory[n * 32] == 0x20 and directory[n * 32 + 12] & 0x70
                for n in range(g.maxdir))):
            raise CPMError("zápis do adresáře s časovými značkami nebo hesly není podporován")
        files = self.files()
        if writing and any(key[1] == b"!!!TIME&DAT" for key in files):
            raise CPMError("zápis na disk s DateStamperem není podporován")
        for key, entries in files.items():
            groups: set[int] = set()
            for entry in entries:
                try:
                    if split_name(f"{key[0]}:{entry.name}", g.max_user) != key:
                        raise CPMError("nekanonické jméno")
                except (CPMError, UnicodeError) as exc:
                    raise CPMError(f"neplatné jméno v položce {entry.index}; chybný formát nebo poškozený adresář") from exc
                if entry.group in groups:
                    raise CPMError(f"{entry.name}: duplicitní extent")
                groups.add(entry.group)
                if entry.raw[15] > 128 or entry.raw[13] > 127 or not 0 <= entry.local_size <= g.extent_capacity:
                    raise CPMError(f"{entry.name}: neplatná délka extentu")
                if entry.raw[15] == 0 and (entry.raw[13] or entry.extent % g.logicalextents):
                    raise CPMError(f"{entry.name}: neplatný prázdný extent")
                needed = math.ceil(entry.local_size / g.blocksize)
                if any(entry.blocks[needed:]):
                    raise CPMError(f"{entry.name}: bloky za koncem extentu")
                for block in entry.blocks:
                    if block == 0:  # Sparse files are legal in CP/M; read as zeroes.
                        continue
                    if block in used or block >= g.block_count:
                        raise CPMError(f"{entry.name}: sdílený, rezervovaný nebo neplatný blok {block}")
                    used.add(block)
        return used

    def get(self, spec: str) -> bytes:
        self.validate()
        key = split_name(spec, self.geometry.max_user)
        entries = self.files().get(key)
        if entries is None:
            raise CPMError(f"soubor {spec} neexistuje")
        result = bytearray(max(entry.size for entry in entries))
        g = self.geometry
        for entry in entries:
            content = b"".join(self.read_block(n) if n else bytes(g.blocksize) for n in entry.blocks)
            start = entry.group * g.extent_capacity
            result[start:start + entry.local_size] = content[:entry.local_size]
        return bytes(result)

    def put(self, spec: str, content: bytes, *, force: bool = False) -> None:
        used = self.validate(writing=True)
        g = self.geometry
        key = split_name(spec, g.max_user)
        if key[1] == b"!!!TIME&DAT":
            raise CPMError("jméno !!!TIME&.DAT je vyhrazeno pro DateStamper")
        old = self.files().get(key, [])
        if old and not force:
            raise CPMError(f"soubor {spec} již existuje; pro nahrazení použijte --force")
        if any(entry.raw[9] & 0x80 for entry in old):
            raise CPMError(f"soubor {spec} má atribut read-only")
        if len(content) > 2048 * 16384:
            raise CPMError("soubor překračuje rozsah čísel extentů CP/M (32 MiB)")
        # Complete allocation before mutating even the in-memory image.
        directory = bytearray(self.directory())
        for entry in old:
            used.difference_update(n for n in entry.blocks if n)
            directory[entry.index * 32] = 0xe5
        free_blocks = [n for n in range(g.directory_blocks, g.block_count) if n not in used]
        free_entries = [n for n in range(g.maxdir) if directory[n * 32] == 0xe5]
        block_total = math.ceil(len(content) / g.blocksize)
        entry_total = max(1, math.ceil(len(content) / g.extent_capacity))
        if block_total > len(free_blocks):
            raise CPMError("na disku není dost volných bloků")
        if entry_total > len(free_entries):
            raise CPMError("adresář nemá dost volných položek")
        selected = free_blocks[:block_total]
        block_position = 0
        for group in range(entry_total):
            start = group * g.extent_capacity
            part = content[start:start + g.extent_capacity]
            extent = group * g.logicalextents + (len(part) - 1) // 16384 if part else 0
            record_count = (len(part) - 1) % 16384 // 128 + 1 if part else 0
            entry = bytearray(32)
            entry[0] = key[0]
            entry[1:12] = key[1]
            if old:
                for pos in range(1, 12):
                    entry[pos] |= old[0].raw[pos] & 0x80
            entry[12] = extent & 31
            entry[14] = (extent >> 5) & 63
            entry[15] = record_count
            # S1: exact byte count convention used by cpmtools (reversed for ISX).
            entry[13] = (-len(part) if g.os_type == "isx" else len(part)) % 128
            part_blocks = math.ceil(len(part) / g.blocksize)
            for n in range(part_blocks):
                block = selected[block_position]
                block_position += 1
                pointer = 16 + n * g.pointer_size
                entry[pointer:pointer + g.pointer_size] = block.to_bytes(g.pointer_size, "little")
            index = free_entries[group] * 32
            directory[index:index + 32] = entry
        for n, block in enumerate(selected):
            part = content[n * g.blocksize:(n + 1) * g.blocksize]
            self._write_block(block, part.ljust(g.blocksize, b"\x1a"))
        for n in range(g.directory_blocks):
            self._write_block(n, directory[n * g.blocksize:(n + 1) * g.blocksize])

    def save(self, path: Path, *, backup: bool = False) -> None:
        """Replace only if the original image still has the bytes we opened."""
        path = path.resolve(strict=True)
        if not path.is_file():
            raise CPMError("zapisovat lze pouze do běžného souboru s obrazem")
        if path.read_bytes() != self.original:
            raise CPMError("obraz se od načtení změnil; zápis zrušen")
        if backup:
            backup_path = path.with_name(path.name + ".bak")
            write_new(backup_path, self.original)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(self.data)
                stream.flush()
                os.fsync(stream.fileno())
                os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
            if path.read_bytes() != self.original:
                raise CPMError("obraz se během přípravy změnil; zápis zrušen")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.original = bytes(self.data)


def write_new(path: Path, data: bytes) -> None:
    """Create exclusively, never truncate an existing output or backup."""
    try:
        stream = path.open("xb")
    except FileExistsError as exc:
        raise CPMError(f"{path} již existuje") from exc
    try:
        with stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def find_diskdefs(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    candidates = [Path("diskdefs")]
    if os.environ.get("DISKDEFS"):
        candidates.append(Path(os.environ["DISKDEFS"]))
    candidates += [Path("/usr/local/share/cpmtools/diskdefs"), Path("/usr/share/cpmtools/diskdefs"),
                   Path("/usr/local/share/diskdefs"), Path("/usr/share/diskdefs"),
                   Path("/etc/cpmtools/diskdefs"), Path("/etc/diskdefs"),
                   Path(__file__).resolve().with_name("diskdefs")]
    for path in candidates:
        if path.is_file():
            return path
    raise CPMError("soubor diskdefs nenalezen; zadejte --diskdefs CESTA")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-d", "--diskdefs", type=Path, help="soubor diskdefs z cpmtools")
    parser.add_argument("-f", "--format", default="ibm-3740", help="název diskdef (výchozí: ibm-3740)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("formats", help="vypíše názvy definic v diskdefs")
    ls = sub.add_parser("ls", aliases=["dir"], help="vypíše adresář")
    ls.add_argument("image", type=Path)
    ls.add_argument("-u", "--user", type=int, help="zobrazí jen zadanou uživatelskou oblast")
    put = sub.add_parser("put", help="zapíše hostitelský soubor do obrazu")
    put.add_argument("image", type=Path)
    put.add_argument("source", type=Path)
    put.add_argument("destination", nargs="?", help="[uživatel:]JMENO.EXT; výchozí je jméno zdroje")
    put.add_argument("--force", action="store_true", help="nahradí existující soubor CP/M")
    put.add_argument("--backup", action="store_true", help="před zápisem vytvoří obraz.bak (nesmí existovat)")
    get = sub.add_parser("get", help="přečte soubor z obrazu")
    get.add_argument("image", type=Path)
    get.add_argument("source", help="[uživatel:]JMENO.EXT")
    get.add_argument("destination", type=Path, help="nový hostitelský soubor")
    init = sub.add_parser("init", help="vytvoří nový prázdný raw obraz bez zaváděcího systému")
    init.add_argument("image", type=Path)
    args = parser.parse_args(argv)
    try:
        definitions = read_diskdefs(find_diskdefs(args.diskdefs))
        if args.command == "formats":
            print("\n".join(sorted(definitions)))
            return 0
        if args.format not in definitions:
            raise CPMError(f"neznámý formát {args.format}; použijte příkaz formats")
        geometry = Geometry.from_definition(args.format, definitions[args.format])
        if args.command == "init":
            write_new(args.image, b"\xe5" * geometry.image_size)
            print(f"Vytvořen {args.image}: {geometry.image_size} B ({geometry.name}).")
            return 0
        if not args.image.is_file():
            raise CPMError("obraz musí být běžný soubor")
        disk = DiskImage(args.image.read_bytes(), geometry)
        if args.command in ("ls", "dir"):
            used = disk.validate()
            if args.user is not None and not 0 <= args.user <= geometry.max_user:
                raise CPMError(f"uživatel musí být v rozsahu 0..{geometry.max_user}")
            print("USR JMENO         BAJTU   BLOKU RSA")
            for (user, _), entries in sorted(disk.files().items()):
                if args.user is not None and args.user != user:
                    continue
                blocks = sum(bool(n) for entry in entries for n in entry.blocks)
                print(f"{user:3} {entries[0].name:12} {max(e.size for e in entries):8} {blocks:6} {entries[0].attributes}")
            print(f"Volno: {(geometry.block_count - len(used)) * geometry.blocksize} B; "
                  f"položek adresáře: {sum(disk.directory()[n * 32] == 0xe5 for n in range(geometry.maxdir))}.")
        elif args.command == "put":
            if args.source.resolve() == args.image.resolve():
                raise CPMError("zdrojový soubor nesmí být současně obrazem")
            spec = args.destination or args.source.name
            content = args.source.read_bytes()
            disk.put(spec, content, force=args.force)
            disk.save(args.image, backup=args.backup)
            print(f"Zapsán {spec.upper()}: {len(content)} B.")
        elif args.command == "get":
            content = disk.get(args.source)
            write_new(args.destination, content)
            print(f"Přečten {args.source.upper()}: {len(content)} B.")
        return 0
    except (CPMError, OSError, UnicodeError) as exc:
        print(f"Chyba: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
