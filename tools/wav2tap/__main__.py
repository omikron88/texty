"""Run with python -m tools.wav2tap input.wav output.tap."""

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

from .decoder import decode_audio, read_wav, tap_bytes


def main():
    parser = argparse.ArgumentParser(description="WAV → TAP: standardní ZX Spectrum ROM záznam")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--report", type=Path, help="Diagnostický protokol JSON")
    parser.add_argument("--plot", type=Path, help="Diagnostický graf PNG, SVG nebo PDF")
    parser.add_argument("--plot-start", type=float, help="Začátek detailu grafu v sekundách")
    parser.add_argument("--plot-duration", type=float, help="Délka detailu v sekundách (výchozí 0.02)")
    parser.add_argument("--diagnostics-only", action="store_true",
                        help="Uložit pouze graf nebo protokol, bez výstupního TAP")
    parser.add_argument("--headerless", action="store_true",
                        help="Všechny bloky chápat jako data bez hlaviček")
    parser.add_argument("--allow-partial", action="store_true",
                        help="Uložit ověřené bloky i při chybách jinde v nahrávce")
    args = parser.parse_args()
    if args.diagnostics_only:
        if args.output:
            parser.error("V režimu --diagnostics-only vynechte cestu výstupního TAP.")
        if not args.plot and not args.report:
            parser.error("Režim --diagnostics-only vyžaduje --plot nebo --report.")
    elif not args.output:
        parser.error("Zadejte výstupní TAP nebo použijte --diagnostics-only.")
    if not args.plot and (args.plot_start is not None or args.plot_duration is not None):
        parser.error("Volby --plot-start a --plot-duration vyžadují --plot.")
    if args.plot and args.plot.suffix.lower() not in (".png", ".svg", ".pdf"):
        parser.error("Graf musí mít příponu .png, .svg nebo .pdf.")
    if args.plot_start is not None and (not math.isfinite(args.plot_start) or args.plot_start < 0):
        parser.error("Začátek detailu musí být nezáporný a konečný.")
    duration = args.plot_duration if args.plot_duration is not None else 0.02
    if not math.isfinite(duration) or duration <= 0:
        parser.error("Délka detailu musí být kladná a konečná.")
    paths = [path.resolve() for path in (args.input, args.output, args.report, args.plot) if path]
    if len(set(paths)) != len(paths):
        parser.error("Vstup, výstup, protokol a graf musí mít různé cesty.")
    for path in [args.output, args.report, args.plot]:
        if path and path.exists():
            parser.error(f"Soubor již existuje: {path}")
    try:
        if args.plot:
            from .plotting import check_plot_support, plot_window, write_plot
            check_plot_support()
        fs, audio = read_wav(args.input)
        if args.plot:
            plot_window(audio, fs, [], [], args.plot_start, duration)
        diagnostics = [] if args.plot else None
        blocks, issues = decode_audio(audio, fs, headerless=args.headerless, diagnostics=diagnostics)
        report = dict(sample_rate=fs, channels=audio.shape[1], headerless=args.headerless,
                      blocks=[block.summary() for block in blocks],
                      issues=[asdict(issue) for issue in issues])
        if args.report:
            with args.report.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        if args.plot:
            write_plot(args.plot, audio, fs, blocks, issues, diagnostics,
                       start=args.plot_start, duration=duration)
            print(f"Diagnostický graf uložen do {args.plot}")
        for block in blocks:
            print(f"{block.start:.2f} s: {len(block.data)} bajtů, "
                  f"kanál {block.channel + 1}, XOR OK")
        for issue in issues:
            print(f"{issue.start:.2f} s: {issue.message}", file=sys.stderr)
        if args.diagnostics_only:
            print("Diagnostika dokončena; TAP se v tomto režimu neukládá.")
            return 0 if blocks and not issues else 1
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
