"""Validate plotted detector evidence, real exports, and failure diagnostics."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile

from tools.wav2tap.decoder import Issue, decode_audio, edge_times, tap_bytes
from tools.wav2tap.plotting import build_figure, check_plot_support, plot_window, write_plot
from test_decoder import recording, with_checksum


class TraceTests(unittest.TestCase):
    def test_basic_conversion_does_not_require_matplotlib(self):
        original_import = __import__

        def without_matplotlib(name, *args, **kwargs):
            if name.startswith("matplotlib"):
                raise ModuleNotFoundError("matplotlib is not installed")
            return original_import(name, *args, **kwargs)

        data = with_checksum(b"\xfftest")
        with patch("builtins.__import__", side_effect=without_matplotlib):
            blocks, issues = decode_audio(recording([data]), 44100)
            self.assertEqual([], issues)
            self.assertEqual([data], [block.data for block in blocks])
            with self.assertRaisesRegex(ValueError, "requirements-plot.txt"):
                check_plot_support()

    def test_collecting_diagnostics_preserves_decoded_bytes_and_edge_times(self):
        data = with_checksum(b"\xff" + bytes(range(32)))
        mono = recording([data], degraded=True)
        stereo = np.column_stack([mono, -mono])
        original, original_issues = decode_audio(stereo, 44100)
        diagnostics = []
        blocks, issues = decode_audio(stereo, 44100, diagnostics=diagnostics)
        self.assertEqual(tap_bytes(original), tap_bytes(blocks))
        self.assertEqual(original_issues, issues)
        self.assertEqual([0, 1], [item.channel for item in diagnostics])
        self.assertTrue(blocks[0].start < blocks[0].data_start < blocks[0].end)
        for item in diagnostics:
            self.assertEqual([0.06, 0.025, 0.12], [trace.threshold_fraction for trace in item.traces])
            for trace in item.traces:
                np.testing.assert_array_equal(trace.edges,
                                              edge_times(stereo[:, item.channel], 44100,
                                                         trace.threshold_fraction))

    def test_automatic_window_targets_error_or_data_and_validates_range(self):
        data = with_checksum(b"\xfftest")
        audio = recording([data])
        blocks, issues = decode_audio(audio, 44100)
        start, end = plot_window(audio, 44100, blocks, issues)
        self.assertTrue(start < blocks[0].data_start < end)
        damaged = data[:-1] + bytes([data[-1] ^ 1])
        broken = recording([damaged])
        failed, issues = decode_audio(broken, 44100)
        start, end = plot_window(broken, 44100, failed, issues)
        self.assertTrue(start <= issues[0].end <= end)
        # Aggregated stereo errors need not arrive in chronological order.
        unordered = [Issue(.4, .5, 0, "later"), Issue(.1, .2, 1, "earlier")]
        start, end = plot_window(np.zeros((44100, 2)), 44100, [], unordered)
        self.assertTrue(start < .2 < end)
        for start, duration in [(float("nan"), .02), (-1, .02), (99, .02), (0, 0),
                                (0, float("inf"))]:
            with self.subTest(start=start, duration=duration):
                with self.assertRaises(ValueError):
                    plot_window(audio, 44100, blocks, [], start, duration)


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Install requirements-plot.txt for plot tests")
class PlotTests(unittest.TestCase):
    def setUp(self):
        self.data = with_checksum(b"\xff" + bytes(range(32)))
        self.audio = recording([self.data], degraded=True)[:, None]
        self.diagnostics = []
        self.blocks, self.issues = decode_audio(self.audio, 44100, diagnostics=self.diagnostics)

    def test_figure_shows_filtered_samples_thresholds_and_selected_edges(self):
        # Plot an alternative recorded detector setting, not a fresh approximation.
        block = replace(self.blocks[0], threshold_fraction=0.025)
        start, end = plot_window(self.audio, 44100, [block], [], duration=.01)
        figure = build_figure(self.audio, 44100, [block], [], self.diagnostics, duration=.01)
        self.addCleanup(figure.clear)
        self.assertEqual(4, len(figure.axes))
        detail = figure.axes[1]
        lines = {line.get_label(): line for line in detail.lines}
        left, right = int(start * 44100), int(np.ceil(end * 44100))
        np.testing.assert_array_equal(lines["Filtrovaný signál"].get_ydata(),
                                      self.diagnostics[0].analysis.filtered[left:right])
        np.testing.assert_array_equal(lines["Prahy hystereze"].get_ydata(),
                                      self.diagnostics[0].analysis.threshold(.025)[left:right])
        trace = self.diagnostics[0].traces[1]
        expected = trace.edges[(trace.edges >= start) & (trace.edges < end)]
        drawn = next(collection for collection in detail.collections
                     if collection.get_label() == "Potvrzené hrany")
        np.testing.assert_array_equal([segment[0, 0] for segment in drawn.get_segments()], expected)
        self.assertIn("0.025", detail.get_title())
        self.assertIn("kalibrace", figure.axes[2].get_title())

    def test_stereo_axes_and_silence(self):
        for audio in [np.column_stack([self.audio[:, 0], -self.audio[:, 0]]), np.zeros((44100, 2))]:
            diagnostics = []
            blocks, issues = decode_audio(audio, 44100, diagnostics=diagnostics)
            figure = build_figure(audio, 44100, blocks, issues, diagnostics)
            self.addCleanup(figure.clear)
            self.assertEqual(8, len(figure.axes))
            self.assertIn("Kanál 1", figure.axes[0].get_title())
            self.assertIn("Kanál 2", figure.axes[1].get_title())
            figure.canvas.draw()

    def test_real_png_svg_pdf_exports_and_no_overwrite(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            for extension in ("png", "svg", "pdf"):
                path = Path(folder) / f"plot.{extension}"
                write_plot(path, self.audio, 44100, self.blocks, self.issues, self.diagnostics)
                self.assertGreater(path.stat().st_size, 5000)
                original = path.read_bytes()
                if extension == "png":
                    with Image.open(path) as image:
                        self.assertGreater(image.width, 1000)
                        self.assertNotEqual(image.convert("RGB").getextrema(), ((255, 255),) * 3)
                elif extension == "svg":
                    self.assertIn("<svg", original.decode())
                else:
                    self.assertTrue(original.startswith(b"%PDF"))
                with self.assertRaises(FileExistsError):
                    write_plot(path, self.audio, 44100, self.blocks, self.issues, self.diagnostics)
                self.assertEqual(original, path.read_bytes())

    def test_cli_failure_still_saves_plot_and_report_without_tap(self):
        damaged = self.data[:-1] + bytes([self.data[-1] ^ 1])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target, plot, report = [root / name for name in
                                             ("input.wav", "output.tap", "plot.png", "report.json")]
            wavfile.write(source, 44100, (recording([damaged]) * 32767).astype(np.int16))
            result = subprocess.run([sys.executable, "-m", "tools.wav2tap", str(source), str(target),
                                     "--plot", str(plot), "--report", str(report)],
                                    capture_output=True, text=True)
            self.assertEqual(1, result.returncode, result.stderr)
            self.assertIn("XOR", result.stderr)
            self.assertFalse(target.exists())
            self.assertTrue(plot.read_bytes().startswith(b"\x89PNG"))
            self.assertIn("XOR", report.read_text())

    def test_cli_zoom_export_preserves_tap_and_existing_plot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target, plot = root / "input.wav", root / "output.tap", root / "plot.png"
            pcm = (self.audio / np.max(np.abs(self.audio)) * 30000).astype(np.int16)
            wavfile.write(source, 44100, pcm)
            command = [sys.executable, "-m", "tools.wav2tap", str(source), str(target),
                       "--plot", str(plot), "--plot-start", ".42", "--plot-duration", ".015"]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(struct.pack("<H", len(self.data)) + self.data, target.read_bytes())
            target.unlink()
            before = plot.read_bytes()
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(0, second.returncode)
            self.assertFalse(target.exists())
            self.assertEqual(before, plot.read_bytes())

    def test_cli_diagnostics_only_does_not_require_or_write_tap(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, plot, report = root / "input.wav", root / "plot.png", root / "report.json"
            wavfile.write(source, 44100, (recording([self.data]) * 32767).astype(np.int16))
            result = subprocess.run([sys.executable, "-m", "tools.wav2tap", str(source),
                                     "--diagnostics-only", "--plot", str(plot), "--report", str(report)],
                                    capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(plot.exists())
            self.assertTrue(report.exists())
            self.assertEqual([], list(root.glob("*.tap")))

    def test_cli_diagnostics_only_keeps_failure_exit_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, report = root / "silence.wav", root / "report.json"
            wavfile.write(source, 44100, np.zeros(44100, dtype=np.int16))
            result = subprocess.run([sys.executable, "-m", "tools.wav2tap", str(source),
                                     "--diagnostics-only", "--report", str(report)],
                                    capture_output=True, text=True)
            self.assertEqual(1, result.returncode)
            self.assertTrue(report.exists())
            self.assertEqual([], list(root.glob("*.tap")))

    def test_cli_rejects_collisions_formats_and_invalid_zoom(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / "input.wav", root / "output.tap"
            wavfile.write(source, 44100, (self.audio * 32767).astype(np.int16))
            command = [sys.executable, "-m", "tools.wav2tap", str(source), str(target)]
            cases = [["--plot-start", "0"], ["--plot", str(target)],
                     ["--diagnostics-only", "--plot", str(root / "plot.png")],
                     ["--plot", str(root / "plot.html")],
                     ["--plot", str(root / "plot.png"), "--report", str(root / "plot.png")],
                     ["--plot", str(root / "plot.png"), "--plot-duration", "nan"],
                     ["--plot", str(root / "plot.png"), "--plot-start", "99"]]
            for options in cases:
                with self.subTest(options=options):
                    result = subprocess.run(command + options, capture_output=True, text=True)
                    self.assertNotEqual(0, result.returncode)
                    self.assertFalse(target.exists())
                    self.assertFalse((root / "plot.png").exists())


if __name__ == "__main__":
    unittest.main()
