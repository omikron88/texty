"""Recovery from offset pulse shapes, with consensus and dropout protection."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import unittest

import numpy as np

from tools.wav2tap.decoder import (Block, ONE, PILOT, SYNC, ZERO, decode_audio,
                                  classify_extrema_pair, decode_edges, detect_extrema,
                                  extrema_consensus, extrema_sync_start,
                                  prepare_extrema_signal, read_wav)
from tools.wav2tap.plotting import build_figure
from test_decoder import with_checksum


FIXTURES = Path(__file__).parent / "fixtures"
HEADER = bytes.fromhex("00004445534b544f502020206a080a005a0040")


def ideal_centers(data, scale=1.0):
    widths = [PILOT * scale] * 512 + list(SYNC * scale)
    for byte in data:
        for bit in range(7, -1, -1):
            width = (ONE if byte & (1 << bit) else ZERO) * scale
            widths.extend([width, width])
    edges = np.r_[0, np.cumsum(widths)]
    return (edges[:-1] + edges[1:]) / 2


class ExtremaTests(unittest.TestCase):
    def test_real_positive_sync_valley_is_recovered_in_both_polarities(self):
        fs, audio = read_wav(FIXTURES / "desktop_header.wav")
        for sign in (1, -1):
            with self.subTest(sign=sign):
                diagnostics = []
                blocks, issues = decode_audio(sign * audio, fs, diagnostics=diagnostics)
                self.assertEqual([HEADER], [block.data for block in blocks])
                self.assertEqual("extrema", blocks[0].detector)
                self.assertEqual("DESKTOP", blocks[0].summary()["name"])
                self.assertEqual(2154, blocks[0].summary()["payload_length"])
                self.assertEqual(1, len(issues))
                self.assertIn("chybí datový blok", issues[0].message)
                alternatives = [trace for trace in diagnostics[0].traces if trace.detector == "extrema"]
                self.assertEqual({3500, 5000}, {trace.lowpass_hz for trace in alternatives})
                for trace in alternatives:
                    accepted, _ = decode_edges(trace.edges, detector="extrema")
                    self.assertEqual([HEADER], [block.data for block in accepted])

    def test_real_dropout_does_not_create_a_valid_shortened_block(self):
        fs, audio = read_wav(FIXTURES / "desktop_dropout.wav")
        blocks, issues = decode_audio(audio, fs)
        self.assertEqual([], blocks)
        failures = [issue for issue in issues if issue.detector == "extrema"]
        self.assertTrue(failures)
        # Filtering may reject an already fading pulse just before the gap.
        self.assertAlmostEqual(29.608625 - 26.2, failures[0].end, delta=.015)

    def test_new_capture_headers_with_broadened_sync_and_displaced_centers(self):
        cases = [("desktop_new_header.wav", "00004445534b544f5020202069080a005a0043"),
                 ("desktop_new_code_header.wav", "00036465736b746f70426364df6e885e333858")]
        for filename, expected in cases:
            fs, audio = read_wav(FIXTURES / filename)
            for sign in (1, -1):
                with self.subTest(filename=filename, sign=sign):
                    blocks, issues = decode_audio(sign * audio, fs, headerless=True)
                    self.assertEqual([bytes.fromhex(expected)], [block.data for block in blocks])
                    self.assertEqual([], issues)
                    self.assertEqual("extrema", blocks[0].detector)

    def test_noise_floor_matches_measured_filtered_white_noise(self):
        fs = 48000
        audio = np.random.default_rng(714).normal(size=fs * 2)
        for cutoff in (3500, 5000):
            with self.subTest(cutoff=cutoff):
                analysis = prepare_extrema_signal(audio, fs, cutoff, noise=1)
                measured = np.std(analysis.filtered[fs // 10:-fs // 10])
                self.assertAlmostEqual(measured, analysis.noise, delta=.02)

    def test_actual_weak_zero_is_detected_without_inventing_extrema(self):
        fs, audio = read_wav(FIXTURES / "desktop_new_weak_zero.wav")
        for sign in (1, -1):
            for cutoff in (3500, 5000):
                with self.subTest(sign=sign, cutoff=cutoff):
                    analysis = prepare_extrema_signal(sign * audio[:, 0], fs, cutoff,
                                                      noise=.003047774765)
                    trace = detect_extrema(replace(analysis, noise_multiplier=1),
                                           fs, cutoff, fraction=.005)
                    center = 189.779583333 - 189.75
                    index = np.argmin(abs(trace.edges - center))
                    self.assertAlmostEqual(center, trace.edges[index], delta=1 / fs)
                    first, second = np.diff(trace.edges[index:index + 3])
                    self.assertLess(first, 90e-6)
                    choice = classify_extrema_pair(first, second, 1.02, ONE * 1.02)
                    self.assertIsNotNone(choice)
                    self.assertEqual(0, choice[0])
                    for edge in trace.edges[index:index + 3]:
                        sample = round(edge * fs)
                        value = analysis.filtered[sample]
                        neighbors = analysis.filtered[[sample - 1, sample + 1]]
                        self.assertTrue(np.all(value > neighbors) or np.all(value < neighbors))

    def test_full_period_handles_large_middle_center_displacement(self):
        data = with_checksum(b"\xff" + bytes(range(256)))
        centers = ideal_centers(data)
        # Move only each within-bit center, preserving both endpoints of the
        # full bit period. Classification by that single half would fail.
        for index in range(514, len(centers) - 1, 2):
            width = min(centers[index] - centers[index - 1],
                        centers[index + 1] - centers[index])
            centers[index] += .70 * width
        blocks, issues = decode_edges(centers, detector="extrema")
        self.assertEqual([data], [block.data for block in blocks])
        self.assertEqual([], issues)

    def test_sensitive_trials_do_not_supply_consensus_from_one_filter(self):
        data = with_checksum(b"\xfftest")
        block = Block(0, 1, 0, 1, data, detector="extrema", lowpass_hz=3500)
        sensitive = replace(block, threshold_fraction=.005, noise_multiplier=1)
        self.assertEqual([], extrema_consensus([block, sensitive]))

    def test_broadened_sync_accepts_short_ripple_and_pilot_overshoot_only(self):
        pulses = np.r_[[PILOT] * 512, np.array([541, 125, 250]) * 1e-6]
        for index in (512, 513):
            with self.subTest(index=index):
                self.assertEqual(515, extrema_sync_start(pulses, index, 0, 1))
        data_pairs = np.r_[[PILOT] * 512, [ONE, ZERO, ONE]]
        self.assertIsNone(extrema_sync_start(data_pairs, 512, 0, 1))
        too_short_pilot = pulses[300:]
        self.assertIsNone(extrema_sync_start(too_short_pilot, 212, 0, 1))

    def test_center_geometry_handles_mixed_bits(self):
        data = with_checksum(b"\xff" + bytes(range(256)))
        blocks, issues = decode_edges(ideal_centers(data), detector="extrema")
        self.assertEqual([data], [block.data for block in blocks])
        self.assertEqual([], issues)

    def test_center_geometry_still_rejects_bad_checksum(self):
        data = with_checksum(b"\xffmixed bits")
        damaged = data[:-1] + bytes([data[-1] ^ 1])
        blocks, issues = decode_edges(ideal_centers(damaged), detector="extrema")
        self.assertEqual([], blocks)
        self.assertTrue(any("XOR" in issue.message for issue in issues))

    def test_consensus_needs_different_filters_identical_bytes_and_same_position(self):
        data = with_checksum(b"\xfftest")
        first = Block(0, 1, 0, 1, data, detector="extrema", lowpass_hz=3500)
        second = replace(first, lowpass_hz=5000)
        self.assertEqual([first, second], extrema_consensus([first, second]))
        for peer in [first, replace(second, start=2, end=3),
                     replace(second, data=with_checksum(b"\xffother"))]:
            with self.subTest(peer=peer):
                self.assertEqual([], extrema_consensus([first, peer]))

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Install requirements-plot.txt")
    def test_plot_displays_actual_extrema_filter_and_labels_centers(self):
        fs, audio = read_wav(FIXTURES / "desktop_header.wav")
        diagnostics = []
        blocks, _ = decode_audio(audio, fs, diagnostics=diagnostics)
        figure = build_figure(audio, fs, blocks, [], diagnostics, start=.604, duration=.025)
        self.addCleanup(figure.clear)
        detail = figure.axes[1]
        trace = next(trace for trace in diagnostics[0].traces if trace.detector == "extrema"
                     and trace.lowpass_hz == blocks[0].lowpass_hz)
        line = next(line for line in detail.lines if line.get_label() == "Filtrovaný signál")
        left, right = int(.604 * fs), int(np.ceil(.629 * fs))
        np.testing.assert_array_equal(line.get_ydata(), trace.analysis.filtered[left:right])
        points = next(item for item in detail.collections if item.get_label() == "Extrémy / středy pulzů")
        centers = trace.edges[(trace.edges >= .604) & (trace.edges < .629)]
        np.testing.assert_array_equal(points.get_offsets()[:, 0], centers)
        self.assertIn("Extrémy", detail.get_title())
        self.assertEqual("Interval extrémů [µs]", figure.axes[2].get_ylabel())
        figure.canvas.draw()


if __name__ == "__main__":
    unittest.main()
