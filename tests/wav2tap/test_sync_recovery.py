"""Regression for weak sync transitions and clicks in a real cassette header."""

from pathlib import Path
import unittest

import numpy as np

from tools.wav2tap.decoder import (ONE, PILOT, SYNC, ZERO, decode_audio, decode_edges,
                                  matches_sync, read_wav, remove_short_excursions)
from test_decoder import with_checksum


def pulse_edges(data, *, scale=1.0, tail=()):
    widths = [PILOT * scale] * 512 + list(SYNC * scale)
    for byte in data:
        for shift in range(7, -1, -1):
            width = (ONE if byte & (1 << shift) else ZERO) * scale
            widths.extend([width, width])
    widths.extend(tail)
    return np.r_[0, np.cumsum(widths)]


class SyncRecoveryTests(unittest.TestCase):
    def test_real_leonardo_header_with_weak_sync_and_pilot_click(self):
        path = Path(__file__).parent / "fixtures" / "leonardo_header.wav"
        fs, audio = read_wav(path)
        expected = bytes.fromhex("00006c656f6e6172646f2020a5000a00a5001a")
        for polarity in (1, -1):
            with self.subTest(polarity=polarity):
                blocks, issues = decode_audio(audio * polarity, fs)
                self.assertEqual([expected], [block.data for block in blocks])
                self.assertEqual("leonardo", blocks[0].summary()["name"])
                self.assertEqual(165, blocks[0].summary()["payload_length"])
                self.assertAlmostEqual(.78495, blocks[0].data_start, delta=.0001)
                self.assertEqual(1, len(issues))
                self.assertIn("chybí datový blok", issues[0].message)
                # It is a header-only excerpt, not a damaged complete program.
                blocks, issues = decode_audio(audio * polarity, fs, headerless=True)
                self.assertEqual([expected], [block.data for block in blocks])
                self.assertEqual([], issues)

    def test_shortest_excursion_preserves_neighboring_real_edge(self):
        # The 67 µs segment is genuine but shortened by a 65 µs excursion.
        edges = np.array([-659, 0, 67, 132, 626, 1269], dtype=float) * 1e-6
        expected = edges[[0, 1, 4, 5]]
        np.testing.assert_array_equal(expected, remove_short_excursions(edges))

    def test_short_clicks_do_not_split_a_pilot(self):
        data = with_checksum(b"\xffpilot clicks")
        clean = pulse_edges(data)
        noisy = np.sort(np.r_[clean, clean[300] + 67e-6, clean[300] + 132e-6,
                              clean[400] + 171e-6, clean[400] + 209e-6])
        recovered = remove_short_excursions(noisy)
        np.testing.assert_array_equal(clean, recovered)
        blocks, issues = decode_edges(recovered)
        self.assertEqual([data], [block.data for block in blocks])
        self.assertEqual([], issues)

    def test_fast_standard_sync_is_not_removed(self):
        data = with_checksum(b"\xfffast")
        edges = pulse_edges(data, scale=.65)
        np.testing.assert_array_equal(edges, remove_short_excursions(edges))
        blocks, issues = decode_edges(edges)
        self.assertEqual([data], [block.data for block in blocks])
        self.assertEqual([], issues)

    def test_sync_checks_whole_pair_and_rejects_data_zero(self):
        self.assertTrue(matches_sync(np.array([200.8, 146.35]) * 1e-6, 1.0454))
        self.assertFalse(matches_sync(np.array([ZERO, ZERO]), 1.0))
        self.assertFalse(matches_sync(np.array([190, 400]) * 1e-6, 1.0))
        data = with_checksum(b"\xffnot sync")
        edges = pulse_edges(data)
        widths = np.diff(edges)
        widths[512:514] = ZERO
        blocks, issues = decode_edges(np.r_[0, np.cumsum(widths)])
        self.assertEqual([], blocks)
        self.assertTrue(any("synchronizace" in issue.message for issue in issues))

    def test_two_closing_pulses_are_accepted_only_before_pause(self):
        data = with_checksum(b"\xffclosing pulses")
        tail = [406e-6, 858e-6, 1677e-6]
        blocks, issues = decode_edges(pulse_edges(data, scale=1.0454, tail=tail))
        self.assertEqual([data], [block.data for block in blocks])
        self.assertEqual([], issues)
        for tail in ([406e-6, 858e-6, 500e-6], [850e-6, 850e-6, 1677e-6]):
            with self.subTest(tail=tail):
                blocks, issues = decode_edges(pulse_edges(data, scale=1.0454, tail=tail))
                self.assertEqual([], blocks)
                self.assertTrue(issues)

    def test_closing_pulses_cannot_hide_bad_checksum_or_partial_byte(self):
        good = with_checksum(b"\xffbad tail")
        damaged = good[:-1] + bytes([good[-1] ^ 1])
        tail = [406e-6, 858e-6, 1677e-6]
        blocks, issues = decode_edges(pulse_edges(damaged, scale=1.0454, tail=tail))
        self.assertEqual([], blocks)
        self.assertTrue(issues)
        # A valid checksum prefix followed by a truncated bit is not a whole block.
        extra_bit = [ZERO * 1.0454, ZERO * 1.0454] + tail
        blocks, issues = decode_edges(pulse_edges(good, scale=1.0454, tail=extra_bit))
        self.assertEqual([], blocks)
        self.assertTrue(issues)


if __name__ == "__main__":
    unittest.main()
