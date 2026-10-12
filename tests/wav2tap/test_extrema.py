"""Recovery from offset pulse shapes, with consensus and dropout protection."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import unittest

import numpy as np

from tools.wav2tap.decoder import (Block, ONE, PILOT, SYNC, ZERO, decode_audio,
                                  decode_edges, extrema_consensus, read_wav)
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
        self.assertAlmostEqual(29.608625 - 26.2, failures[0].end, delta=.002)

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
