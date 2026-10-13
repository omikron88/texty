"""Measure equalization and exercise decoding, CLI, and plotted evidence."""

from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, freqz, sosfilt

from tools.wav2tap.decoder import (Block, SignalAnalysis, decode_audio,
                                  prepare_extrema_signal, prepare_signal, read_wav, tap_bytes)
from tools.wav2tap.equalizer import EqualizerSettings, apply_equalizer, design_equalizer
from tools.wav2tap.plotting import build_figure
from test_decoder import recording, with_checksum


FIXTURES = Path(__file__).parent / "fixtures"


def difficult_recording(data, fs=48000):
    # Independent tape model: high-frequency loss, DC drift, low-frequency hum
    # and high-frequency interference. EQ should suppress both kinds of noise.
    audio = sosfilt(butter(2, 1500, fs=fs, output="sos"),
                    recording([data], fs=fs, pilot_count=1024))
    time = np.arange(len(audio)) / fs
    return (audio + .35 + .1 * np.sin(2 * np.pi * 4 * time)
            + .5 * np.sin(2 * np.pi * 300 * time)
            + .1 * np.sin(2 * np.pi * 8000 * time))


class EqualizerTests(unittest.TestCase):
    def test_measured_response_at_supported_sample_rates(self):
        settings = EqualizerSettings()
        for fs in (22050, 48000, 96000):
            coefficients = design_equalizer(fs, settings)
            time = np.arange(fs) / fs
            for frequency, expected in ((100, -40), (settings.pilot_hz, 0),
                                        (2047, 8.12), (4500, 15), (6500, -40)):
                with self.subTest(fs=fs, frequency=frequency):
                    tone = np.sin(2 * np.pi * frequency * time)
                    result = apply_equalizer(tone, coefficients)
                    interior = slice(fs // 10, -fs // 10)
                    gain = 20 * np.log10(np.std(result[interior]) / np.std(tone[interior]))
                    self.assertAlmostEqual(expected, gain, delta=.3)

    def test_delay_is_compensated_and_gain_is_not_clipped(self):
        coefficients = design_equalizer(48000, EqualizerSettings())
        impulse = np.zeros(10000)
        impulse[5000] = 1
        result = apply_equalizer(impulse, coefficients)
        self.assertEqual(impulse.shape, result.shape)
        self.assertEqual(5000, np.argmax(result))
        np.testing.assert_allclose(result[4500:5000], result[5500:5000:-1], atol=1e-14)
        time = np.arange(48000) / 48000
        amplified = apply_equalizer(np.sin(2 * np.pi * 4500 * time), coefficients)
        self.assertGreater(np.max(np.abs(amplified[4800:-4800])), 5)
        np.testing.assert_array_equal(np.zeros(100), apply_equalizer(np.zeros(100), coefficients))
        # Constant endpoint extension avoids an artificial step at file edges.
        constant = apply_equalizer(np.ones(10000), coefficients)
        self.assertLess(np.ptp(constant), 1e-12)

    def test_combined_noise_response_matches_filtered_white_noise(self):
        fs = 48000
        original = np.random.default_rng(502).normal(size=fs * 3)
        coefficients = design_equalizer(fs, EqualizerSettings())
        equalized = apply_equalizer(original, coefficients)
        _, response = freqz(coefficients, worN=2048)
        analyses = [prepare_signal(equalized, fs, noise=1, noise_response=response)]
        analyses.extend(prepare_extrema_signal(equalized, fs, cutoff, noise=1,
                                              noise_response=response)
                        for cutoff in (3500, 5000))
        for analysis in analyses:
            measured = np.std(analysis.filtered[fs // 10:-fs // 10])
            self.assertAlmostEqual(measured, analysis.noise, delta=analysis.noise * .04)

    def test_equalization_recovers_attenuated_data_with_interference_and_stereo(self):
        data = with_checksum(b"\xff" + bytes(range(64)))
        audio = difficult_recording(data)
        original, _ = decode_audio(audio, 48000)
        self.assertEqual([], original)
        for source in (audio, -audio, np.column_stack([audio, -audio])):
            with self.subTest(channels=source.ndim):
                before = source.copy()
                blocks, issues = decode_audio(source, 48000, equalizer=EqualizerSettings())
                self.assertEqual([data], [block.data for block in blocks])
                self.assertEqual([], issues)
                self.assertTrue(blocks[0].equalized)
                np.testing.assert_array_equal(before, source)

    def test_original_real_headers_are_preserved_and_dropout_stays_invalid(self):
        for name in ("leonardo_header", "desktop_header", "desktop_new_header",
                     "desktop_new_code_header", "desktop_dropout"):
            with self.subTest(name=name):
                fs, audio = read_wav(FIXTURES / f"{name}.wav")
                original, _ = decode_audio(audio, fs, headerless=True)
                blocks, issues = decode_audio(audio, fs, headerless=True,
                                              equalizer=EqualizerSettings())
                self.assertEqual(tap_bytes(original), tap_bytes(blocks))
                if name == "desktop_dropout":
                    self.assertEqual([], blocks)
                    self.assertTrue(issues)
                else:
                    self.assertEqual([], issues)

    def test_equalization_does_not_repair_bad_checksum(self):
        good = with_checksum(b"\xff" + bytes(range(64)))
        damaged = good[:-1] + bytes([good[-1] ^ 1])
        blocks, issues = decode_audio(difficult_recording(damaged), 48000,
                                      equalizer=EqualizerSettings())
        self.assertEqual([], blocks)
        self.assertTrue(any("XOR" in issue.message for issue in issues))

    def test_conflicting_valid_original_and_equalized_blocks_are_rejected(self):
        first = Block(0, 1, 0, 1, with_checksum(b"\xfforiginal"))
        second = replace(first, data=with_checksum(b"\xffdifferent"), equalized=True)
        analysis = SignalAnalysis(np.zeros(48000), np.zeros(48000), 0)
        with patch("tools.wav2tap.decoder._decode_signal", side_effect=[
                ([first], [], analysis, []), ([second], [], analysis, [])]):
            blocks, issues = decode_audio(np.zeros(48000), 48000,
                                          equalizer=EqualizerSettings())
        self.assertEqual([], blocks)
        self.assertTrue(any("rozdílné" in issue.message for issue in issues))

    def test_invalid_settings_are_rejected(self):
        for settings in (EqualizerSettings(pilot_hz=0), EqualizerSettings(pilot_hz=4500),
                         EqualizerSettings(high_hz=24000), EqualizerSettings(gain_db=-1),
                         EqualizerSettings(gain_db=31), EqualizerSettings(gain_db=float("nan")),
                         EqualizerSettings(high_hz=float("inf"))):
            with self.subTest(settings=settings):
                with self.assertRaises(ValueError):
                    design_equalizer(48000, settings)

    def test_cli_custom_settings_and_report(self):
        data = with_checksum(b"\xff" + bytes(range(64)))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target, report = [root / name for name in ("in.wav", "out.tap", "out.json")]
            wavfile.write(source, 48000, difficult_recording(data).astype(np.float32))
            command = [sys.executable, "-m", "tools.wav2tap", str(source), str(target),
                       "--equalize", "--eq-pilot-hz", "807", "--eq-high-hz", "4000",
                       "--eq-gain-db", "12", "--report", str(report)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(len(data).to_bytes(2, "little") + data, target.read_bytes())
            metadata = json.loads(report.read_text())
            self.assertEqual(12, metadata["equalizer"]["gain_db"])
            self.assertEqual(4000, metadata["equalizer"]["high_hz"])
            self.assertEqual(807, metadata["equalizer"]["pilot_hz"])
            self.assertTrue(metadata["blocks"][0]["equalized"])

    def test_cli_invalid_options_do_not_create_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target, report = [root / name for name in ("in.wav", "out.tap", "out.json")]
            wavfile.write(source, 48000, np.zeros(48000, dtype=np.int16))
            for options in (["--eq-gain-db", "12"], ["--equalize", "--eq-gain-db", "nan"],
                            ["--equalize", "--eq-high-hz", "24000"],
                            ["--equalize", "--eq-pilot-hz", "0"]):
                with self.subTest(options=options):
                    result = subprocess.run([sys.executable, "-m", "tools.wav2tap",
                                             str(source), str(target), "--report", str(report),
                                             *options], capture_output=True, text=True)
                    self.assertNotEqual(0, result.returncode)
                    self.assertFalse(target.exists())
                    self.assertFalse(report.exists())

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Install requirements-plot.txt")
    def test_plot_uses_equalized_trace_and_keeps_original_waveform(self):
        fs = 48000
        data = with_checksum(b"\xff" + bytes(range(64)))
        audio = difficult_recording(data)[:, None]
        diagnostics = []
        settings = EqualizerSettings()
        blocks, issues = decode_audio(audio, fs, equalizer=settings, diagnostics=diagnostics)
        figure = build_figure(audio, fs, blocks, issues, diagnostics, duration=.01)
        self.addCleanup(figure.clear)
        detail = figure.axes[1]
        self.assertIn("EQ", detail.get_title())
        trace = next(trace for trace in diagnostics[0].traces if trace.equalized
                     and trace.detector == blocks[0].detector
                     and trace.threshold_fraction == blocks[0].threshold_fraction
                     and trace.lowpass_hz == blocks[0].lowpass_hz)
        lines = {line.get_label(): line for line in detail.lines}
        times = lines["Filtrovaný signál"].get_xdata()
        samples = np.rint(times * fs).astype(int)
        np.testing.assert_array_equal(lines["Filtrovaný signál"].get_ydata(),
                                      trace.analysis.filtered[samples])
        np.testing.assert_array_equal(lines["Původní WAV"].get_ydata(), audio[samples, 0])
        figure.canvas.draw()


if __name__ == "__main__":
    unittest.main()
