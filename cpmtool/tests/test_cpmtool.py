"""Run with python3 -m unittest discover -s tests -v.

Set CPMTOOLS_DIR to a directory containing cpmcp, cpmls, mkfs.cpm and fsck.cpm
to include independent, bidirectional compatibility checks.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cpmtool import CPMError, DiskImage, Geometry, read_diskdefs, split_name


ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS = read_diskdefs(ROOT / "diskdefs")


def geometry(name="ibm-3740", **changes):
    values = dict(DEFINITIONS[name])
    values.update({k: str(v) for k, v in changes.items()})
    return Geometry.from_definition(name, values)


def blank(g):
    return DiskImage(b"\xe5" * g.image_size, g)


def payload(size):
    # Non-text bytes, including EOF characters, zeroes, and all high bits.
    return (bytes(range(256)) * (size // 256 + 1))[:size]


def edit_entry(disk, index, edit):
    directory = bytearray(disk.directory())
    entry = bytearray(directory[index * 32:(index + 1) * 32])
    edit(entry)
    directory[index * 32:(index + 1) * 32] = entry
    for n in range(disk.geometry.directory_blocks):
        size = disk.geometry.blocksize
        disk._write_block(n, directory[n * size:(n + 1) * size])


class GeometryTests(unittest.TestCase):
    def test_comments_c_numbers_offsets_and_skew(self):
        with tempfile.TemporaryDirectory() as tmp:
            defs = Path(tmp) / "diskdefs"
            defs.write_text("""; test
diskdef custom # comment
seclen 0x80
tracks 0115
sectrk 26
blocksize 1024
maxdir 64
boottrk 2
offset 2trk ; comment
skew 6
end
""", encoding="utf-8")
            g = Geometry.from_definition("custom", read_diskdefs(defs)["custom"])
            self.assertEqual(g.tracks, 77)
            self.assertEqual(g.offset, 6656)
            self.assertEqual(g.skewtab, (0, 6, 12, 18, 24, 4, 10, 16, 22, 2, 8, 14,
                                         20, 1, 7, 13, 19, 25, 5, 11, 17, 23, 3, 9, 15, 21))

    def test_zero_skew_and_explicit_table(self):
        g = geometry(skew=0)
        self.assertEqual(g.skewtab, tuple(range(26)))
        values = dict(DEFINITIONS["ibm-3740"])
        del values["skew"]
        values["skewtab"] = ",".join(str(n) for n in reversed(range(26)))
        self.assertEqual(Geometry.from_definition("reverse", values).skewtab, tuple(reversed(range(26))))

    def test_invalid_geometry(self):
        for changes in ({"blocksize": 3000}, {"skewtab": "0,1"}, {"sectrk": 0},
                        {"logicalextents": 3}, {"offset": "-1"}, {"os": "unknown"},
                        {"boottrk": 77}, {"skew": -1}, {"maxdir": 99999}):
            with self.subTest(changes=changes), self.assertRaises(CPMError):
                geometry(**changes)

    def test_missing_end_in_unrelated_vendor_definition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "diskdefs"
            path.write_text("diskdef broken\nseclen 128\ndiskdef good\n" +
                            "\n".join(f"{k} {v}" for k, v in DEFINITIONS["ibm-3740"].items()) + "\nend\n")
            definitions = read_diskdefs(path)
            self.assertEqual(Geometry.from_definition("good", definitions["good"]).seclen, 128)
            with self.assertRaisesRegex(CPMError, "chybí end"):
                Geometry.from_definition("broken", definitions["broken"])

    def test_names(self):
        self.assertEqual(split_name("12:hello.txt"), (12, b"HELLO   TXT"))
        for name in ("bad name", "longfilename.txt", "a.b.c", "../test", "a*", "32:a", "ě.txt", ":a"):
            with self.subTest(name=name), self.assertRaises(CPMError):
                split_name(name)


class ImageTests(unittest.TestCase):
    def test_binary_roundtrip_boundaries_and_extent_sizes(self):
        for name in DEFINITIONS:
            g = geometry(name)
            for size in (0, 1, 127, 128, 129, 1023, 1024, 1025, 16383, 16384, 16385,
                         32767, 32768, 32769, 65536, 100003):
                with self.subTest(format=name, size=size):
                    disk = blank(g)
                    disk.put("3:binary.bin", payload(size))
                    loaded = DiskImage(bytes(disk.data), g)
                    self.assertEqual(loaded.get("3:BINARY.BIN"), payload(size))
                    self.assertEqual(sum(bool(n) for e in loaded.entries() for n in e.blocks),
                                     (size + g.blocksize - 1) // g.blocksize)

    def test_high_extent_number_and_two_byte_pointers(self):
        g = geometry("cpm86-720")
        disk = blank(g)
        data = payload(600003)
        disk.put("BIG.BIN", data)
        self.assertTrue(any(e.extent >= 32 for e in disk.entries()))
        self.assertTrue(any(n > 255 for e in disk.entries() for n in e.blocks))
        self.assertEqual(disk.get("BIG.BIN"), data)

    def test_override_logicalextents(self):
        g = geometry(blocksize=4096, logicalextents=1)
        disk = blank(g)
        disk.put("ONE.BIN", payload(40001))
        self.assertEqual(len(disk.entries()), 3)
        self.assertEqual(disk.get("ONE.BIN"), payload(40001))

    def test_isx_reverse_exact_size(self):
        disk = blank(geometry(os="isx"))
        disk.put("A.BIN", payload(129))
        self.assertEqual(disk.entries()[0].raw[13], 127)
        self.assertEqual(disk.get("A.BIN"), payload(129))

    def test_offset_boot_tracks_suffix_and_other_files_unchanged(self):
        g = geometry(offset="1K")
        disk = DiskImage(b"P" * g.offset + b"B" * (g.image_size - g.offset) + b"SUFFIX", g)
        for n in range(g.directory_blocks):
            disk._write_block(n, b"\xe5" * g.blocksize)
        disk.put("OTHER.BIN", payload(6007))
        before = bytes(disk.data)
        disk.put("NEW.BIN", payload(22007))
        self.assertEqual(disk.get("OTHER.BIN"), payload(6007))
        boot_end = g.offset + g.boottrk * g.sectrk * g.seclen
        self.assertEqual(disk.data[:boot_end], before[:boot_end])
        self.assertEqual(disk.data[g.image_size:], b"SUFFIX")
        changed = {i for i, (a, b) in enumerate(zip(before, disk.data)) if a != b}
        allowed = set()
        blocks = set(range(g.directory_blocks)) | {n for e in disk.files()[split_name("NEW.BIN")] for n in e.blocks if n}
        for block in blocks:
            for n in range(g.blocksize // g.seclen):
                pos = disk._sector_offset(g.boottrk * g.sectrk + block * (g.blocksize // g.seclen) + n)
                allowed.update(range(pos, pos + g.seclen))
        self.assertTrue(changed <= allowed)

    def test_duplicate_force_reuses_blocks_and_preserves_other_user(self):
        disk = blank(geometry())
        disk.put("0:A.BIN", payload(30000))
        disk.put("1:A.BIN", b"other user")
        before = bytes(disk.data)
        with self.assertRaises(CPMError):
            disk.put("A.BIN", b"new")
        self.assertEqual(disk.data, before)
        disk.put("A.BIN", b"new", force=True)
        self.assertEqual(disk.get("A.BIN"), b"new")
        self.assertEqual(disk.get("1:A.BIN"), b"other user")
        self.assertEqual(len(disk.entries()), 2)

    def test_full_disk_and_directory_leave_image_unchanged(self):
        disk = blank(geometry())
        disk.put("A.BIN", b"old")
        before = bytes(disk.data)
        with self.assertRaisesRegex(CPMError, "volných bloků"):
            disk.put("A.BIN", bytes(256000), force=True)
        self.assertEqual(disk.data, before)
        for n in range(1, 64):
            disk.put(f"F{n}", b"")
        before = bytes(disk.data)
        with self.assertRaisesRegex(CPMError, "volných položek"):
            disk.put("ANOTHER", b"")
        self.assertEqual(disk.data, before)

    def test_read_only(self):
        disk = blank(geometry())
        disk.put("A.BIN", b"old")
        edit_entry(disk, 0, lambda e: e.__setitem__(9, e[9] | 0x80))
        before = bytes(disk.data)
        with self.assertRaisesRegex(CPMError, "read-only"):
            disk.put("A.BIN", b"new", force=True)
        self.assertEqual(disk.data, before)

    def test_corrupt_allocations_are_rejected(self):
        for pointer in (1, 255):
            disk = blank(geometry())
            disk.put("A.BIN", b"x")
            edit_entry(disk, 0, lambda e: e.__setitem__(16, pointer))
            with self.subTest(pointer=pointer), self.assertRaises(CPMError):
                disk.put("B.BIN", b"y")
        disk = blank(geometry())
        disk.put("A.BIN", b"x")
        disk.put("B.BIN", b"y")
        pointer = disk.entries()[0].blocks[0]
        edit_entry(disk, 1, lambda e: e.__setitem__(16, pointer))
        with self.assertRaises(CPMError):
            disk.validate()

    def test_cpm3_metadata_preserved_and_stamped_writes_rejected(self):
        disk = blank(geometry("cpm86-720"))
        label = bytes([0x20]) + b"LABEL      " + bytes(20)
        edit_entry(disk, 0, lambda e: e.__setitem__(slice(None), label))
        disk.put("A.BIN", b"ok")
        self.assertEqual(disk.directory()[:32], label)
        edit_entry(disk, 3, lambda e: e.__setitem__(slice(None), bytes([0x21]) + bytes(31)))
        self.assertEqual(disk.get("A.BIN"), b"ok")
        with self.assertRaisesRegex(CPMError, "časovými značkami"):
            disk.put("B.BIN", b"no")

    def test_sparse_file_and_unordered_extents(self):
        disk = blank(geometry())
        disk.put("A.BIN", payload(40001))
        edit_entry(disk, 0, lambda e: e.__setitem__(16, 0))
        # Swap directory positions, which need not follow extent numbers.
        first, last = disk.directory()[:32], disk.directory()[64:96]
        edit_entry(disk, 0, lambda e: e.__setitem__(slice(None), last))
        edit_entry(disk, 2, lambda e: e.__setitem__(slice(None), first[:16] + b"\x00" + first[17:]))
        self.assertEqual(disk.get("A.BIN"), bytes(1024) + payload(40001)[1024:])

    def test_truncated_container_and_unformatted_images(self):
        g = geometry()
        for data in (bytes(g.image_size - 1), b"IMD " + bytes(g.image_size), bytes(g.image_size)):
            with self.subTest(prefix=data[:4]), self.assertRaises(CPMError):
                DiskImage(data, g).validate()

    def test_save_backup_and_changed_image(self):
        disk = blank(geometry())
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "disk.img"
            image.write_bytes(disk.original)
            image.chmod(0o640)
            original = disk.original
            disk.put("A.BIN", b"hello")
            disk.save(image, backup=True)
            self.assertEqual(Path(str(image) + ".bak").read_bytes(), original)
            self.assertEqual(image.stat().st_mode & 0o777, 0o640)
            self.assertEqual(DiskImage(image.read_bytes(), disk.geometry).get("A.BIN"), b"hello")
            disk.put("B.BIN", b"world")
            before = image.read_bytes()
            with self.assertRaises(CPMError):
                disk.save(image, backup=True)
            self.assertEqual(image.read_bytes(), before)
            image.write_bytes(b"changed")
            with self.assertRaisesRegex(CPMError, "změnil"):
                disk.save(image)
            self.assertEqual(image.read_bytes(), b"changed")


class CLITests(unittest.TestCase):
    def run_cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(ROOT / "cpmtool.py"), "-d", str(ROOT / "diskdefs"), *map(str, args)],
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
        return result

    def test_cli_workflow_and_no_clobber(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            image, source, output = tmp / "disk.img", tmp / "hello.txt", tmp / "output.txt"
            source.write_bytes(b"Hello CP/M!\r\n")
            self.run_cli("init", image)
            self.run_cli("put", image, source, "2:HELLO.TXT", "--backup")
            listing = self.run_cli("ls", image, "--user", "2")
            self.assertIn("HELLO.TXT", listing.stdout)
            self.run_cli("get", image, "2:hello.txt", output)
            self.assertEqual(source.read_bytes(), output.read_bytes())
            before = image.read_bytes()
            self.run_cli("init", image, success=False)
            self.run_cli("get", image, "2:HELLO.TXT", output, success=False)
            self.run_cli("put", image, source, "2:HELLO.TXT", success=False)
            self.assertEqual(image.read_bytes(), before)
            self.assertEqual(output.read_bytes(), source.read_bytes())


@unittest.skipUnless(os.environ.get("CPMTOOLS_DIR"), "CPMTOOLS_DIR není nastaveno")
class CpmtoolsCompatibilityTests(unittest.TestCase):
    def test_cpmtools_formatted_images_and_metadata(self):
        tools = Path(os.environ["CPMTOOLS_DIR"]).resolve()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "diskdefs").write_bytes((ROOT / "diskdefs").read_bytes())
            source = tmp / "source.bin"
            source.write_bytes(payload(20003))
            for name in DEFINITIONS:
                g = geometry(name)
                for stamped in (False, True):
                    with self.subTest(format=name, timestamps=stamped):
                        image = tmp / f"{name}-{stamped}.img"
                        subprocess.run([str(tools / "mkfs.cpm"), "-f", name,
                                        *(["-t"] if stamped else []), str(image)],
                                       cwd=tmp, check=True, capture_output=True, timeout=15)
                        # mkfs.cpm initially writes only the boot/directory area.
                        # Pad to the full physical size expected of a raw floppy image.
                        with image.open("ab") as stream:
                            stream.write(b"\xe5" * (g.image_size - image.stat().st_size))
                        subprocess.run([str(tools / "cpmcp"), "-f", name, str(image),
                                        str(source), "0:SOURCE.BIN"],
                                       cwd=tmp, check=True, capture_output=True, timeout=15)
                        disk = DiskImage(image.read_bytes(), g)
                        self.assertEqual(disk.get("SOURCE.BIN"), source.read_bytes())
                        if stamped:
                            with self.assertRaises(CPMError):
                                disk.put("NEW.BIN", b"new")
                        else:
                            disk.put("NEW.BIN", b"new")
                            disk.save(image)
                            target = tmp / f"{name}-new.bin"
                            subprocess.run([str(tools / "cpmcp"), "-f", name, str(image),
                                            "0:NEW.BIN", str(target)],
                                           cwd=tmp, check=True, capture_output=True, timeout=15)
                            self.assertEqual(target.read_bytes(), b"new")

    def test_bidirectional_binary_compatibility(self):
        tools = Path(os.environ["CPMTOOLS_DIR"]).resolve()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "diskdefs").write_bytes((ROOT / "diskdefs").read_bytes())
            for name in DEFINITIONS:
                g = geometry(name)
                image = tmp / f"{name}.img"
                disk = blank(g)
                for i, size in enumerate((0, 1, 127, 128, 129, 16383, 16384, 16385, 32768, 40003)):
                    disk.put(f"2:F{i}.BIN", payload(size))
                image.write_bytes(disk.data)

                def call(tool, *args):
                    return subprocess.run([str(tools / tool), "-f", name, *map(str, args)], cwd=tmp,
                                          check=True, text=True, capture_output=True, timeout=15)

                with self.subTest(format=name, direction="Python -> cpmtools"):
                    listing = call("cpmls", "-l", image).stdout.upper()
                    self.assertIn("F9.BIN", listing)
                    for i, size in enumerate((0, 1, 127, 128, 129, 16383, 16384, 16385, 32768, 40003)):
                        output = tmp / f"{name}-{i}.bin"
                        call("cpmcp", image, f"2:F{i}.BIN", output)
                        self.assertEqual(output.read_bytes(), payload(size))
                    # fsck checks directory/allocation validity independently.
                    call("fsck.cpm", "-n", image)

                with self.subTest(format=name, direction="cpmtools -> Python"):
                    for i, size in enumerate((0, 1, 129, 16384, 32769)):
                        source = tmp / "source.bin"
                        source.write_bytes(payload(size))
                        call("cpmcp", image, source, f"3:C{i}.BIN")
                        loaded = DiskImage(image.read_bytes(), g)
                        self.assertEqual(loaded.get(f"3:C{i}.BIN"), payload(size))
                    # Replace a cpmtools-created file with our writer.
                    loaded.put("3:C0.BIN", b"replacement", force=True)
                    loaded.save(image)
                    output = tmp / f"{name}-replaced.bin"
                    call("cpmcp", image, "3:C0.BIN", output)
                    self.assertEqual(output.read_bytes(), b"replacement")


if __name__ == "__main__":
    unittest.main()
