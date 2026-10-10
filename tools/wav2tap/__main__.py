"""Run with python -m tools.wav2tap input.wav output.tap."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .decoder import decode_audio, read_wav, tap_bytes


def main():
    parser = argparse.ArgumentParser(description="WAV → TAP: standardní ZX Spectrum ROM záznam")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, help="Diagnostický protokol JSON")
    parser.add_argument("--headerless", action="store_true",
                        help="Všechny bloky chápat jako data bez hlaviček")
    parser.add_argument("--allow-partial", action="store_true",
                        help="Uložit ověřené bloky i při chybách jinde v nahrávce")
    args = parser.parse_args()
    paths = [args.input.resolve(), args.output.resolve()]
    if args.report:
        paths.append(args.report.resolve())
    if len(set(paths)) != len(paths):
        parser.error("Vstup, výstup a protokol musí mít různé cesty.")
    for path in [args.output, args.report]:
        if path and path.exists():
            parser.error(f"Soubor již existuje: {path}")
    try:
        fs, audio = read_wav(args.input)
        blocks, issues = decode_audio(audio, fs, headerless=args.headerless)
        report = dict(sample_rate=fs, channels=audio.shape[1], headerless=args.headerless,
                      blocks=[block.summary() for block in blocks],
                      issues=[asdict(issue) for issue in issues])
        if args.report:
            with args.report.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        for block in blocks:
            print(f"{block.start:.2f} s: {len(block.data)} bajtů, "
                  f"kanál {block.channel + 1}, XOR OK")
        for issue in issues:
            print(f"{issue.start:.2f} s: {issue.message}", file=sys.stderr)
        if not blocks:
            print("Nenalezen žádný platný standardní blok; TAP nebyl vytvořen.", file=sys.stderr)
            return 1
        if issues and not args.allow_partial:
            print("Nahrávka obsahuje chyby; TAP nebyl vytvořen. "
                  "Pro částečný výstup použijte --allow-partial.", file=sys.stderr)
            return 1
        with args.output.open("xb") as stream:
            stream.write(tap_bytes(blocks))
        print(f"Uloženo {len(blocks)} bloků do {args.output}")
        return 0
    except (OSError, ValueError) as error:
        print(f"Chyba: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
