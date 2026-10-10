"""Independent ROM pulse generator and end-to-end decoder regression tests."""

from functools import reduce
from operator import xor
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

from tools.wav2tap.decoder import decode_audio, read_wav, tap_bytes


def with_checksum(payload):
    return payload + bytes([reduce(xor, payload, 0)])


def recording(blocks, fs=44100, speed=1.0, degraded=False, pilot_count=512,
              tail_seconds=0.006):
    chunks = [np.zeros(round(fs * 0.1))]
    for block in blocks:
        timings = [2168] * pilot_count + [667, 735]
        for byte in block:
            for shift in range(7, -1, -1):
                length = 1710 if byte & (1 << shift) else 855
                timings.extend([length, length])
        durations = np.array(timings, dtype=float) / 3_500_000 * speed
        if degraded:
            durations *= 1 + 0.03 * np.sin(2 * np.pi * np.cumsum(durations) * 0.8)
        boundaries = np.rint(np.r_[0, np.cumsum(durations)] * fs).astype(int)
        amplitude = np.where(np.array(timings) == 855, 0.22, 0.8) if degraded else 0.7
        levels = (-1.0) ** np.arange(len(timings)) * amplitude
        signal = np.repeat(levels, np.diff(boundaries))
        # A final opposite excursion supplies the last data edge; then pause.
        tail = np.full(round(fs * tail_seconds), -np.sign(levels[-1]) * 0.7)
        chunks.extend([signal, tail, np.zeros(round(fs * 0.15))])
    audio = np.concatenate(chunks)
    if degraded:
        audio = sosfilt(butter(1, 3500, fs=fs, output="sos"), audio)
        time = np.arange(len(audio)) / fs
        audio += 0.35 + 0.25 * np.sin(2 * np.pi * 4 * time)
        audio += np.random.default_rng(17).normal(0, 0.008, len(audio))
    return audio


class DecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = with_checksum(b"\xff" + bytes(range(32)))
        header = (b"\x00\x03" + b"TEST      " + struct.pack("<HHH", 32, 32768, 32768))
        cls.header = with_checksum(header)

    def assert_decoded(self, audio, fs, expected):
        blocks, issues = decode_audio(audio, fs)
        self.assertEqual([], issues)
        self.assertEqual(expected, [block.data for block in blocks])
        return blocks

    def test_header_data_and_tap_layout(self):
        # Full ROM-size pilot, byte order and checksum independently checked.
        blocks = self.assert_decoded(recording([self.header, self.data], pilot_count=8063),
                                     44100, [self.header, self.data])
        expected = b"".join(struct.pack("<H", len(data)) + data
                            for data in [self.header, self.data])
        self.assertEqual(expected, tap_bytes(blocks))

    def test_full_48k_payload(self):
        payload = bytes(range(256)) * 192
        data = with_checksum(b"\xff" + payload)
        header = with_checksum(b"\x00\x03" + b"48K       "
                               + struct.pack("<HHH", len(payload), 16384, 32768))
        blocks = self.assert_decoded(recording([header, data], fs=22050, pilot_count=3223),
                                     22050, [header, data])
        result = tap_bytes(blocks)
        self.assertEqual(struct.pack("<H", len(data)), result[21:23])
        self.assertEqual(data, result[23:])

    def test_drift_weak_short_pulses_noise_speed_and_polarity(self):
        for fs, speed in [(22050, 1.0), (44100, 0.88), (48000, 1.12), (96000, 1.0)]:
            with self.subTest(fs=fs, speed=speed):
                audio = recording([self.header, self.data], fs, speed, degraded=True)
                self.assert_decoded(-audio, fs, [self.header, self.data])

    def test_stereo_opposite_polarity_is_not_averaged(self):
        mono = recording([self.data], degraded=True)
        stereo = np.column_stack([mono, -mono])
        blocks = self.assert_decoded(stereo, 44100, [self.data])
        self.assertEqual(1, len(blocks))

    def test_stereo_uses_other_channel_per_block(self):
        mono = recording([self.header, self.data])
        left, right = mono.copy(), mono.copy()
        # Erase the first pilot/data on the left and the second on the right.
        split = int(0.65 * 44100)
        left[:split] = 0
        right[split:] = 0
        blocks = self.assert_decoded(np.column_stack([left, right]), 44100,
                                     [self.header, self.data])
        self.assertEqual([1, 0], [block.channel for block in blocks])

    def test_bad_checksum_is_rejected(self):
        damaged = self.data[:-1] + bytes([self.data[-1] ^ 1])
        blocks, issues = decode_audio(recording([damaged]), 44100)
        self.assertEqual([], blocks)
        self.assertTrue(any("XOR" in issue.message for issue in issues))

    def test_headerless_flags_and_lengths(self):
        for flag in (0, 1, 128, 255):
            for length in (0, 5, 64):
                with self.subTest(flag=flag, length=length):
                    data = with_checksum(bytes([flag]) + bytes(range(length)))
                    blocks = self.assert_decoded(recording([data]), 44100, [data])
                    self.assertFalse(blocks[0].is_header)
                    self.assertNotIn("name", blocks[0].summary())
                    self.assertEqual(struct.pack("<H", len(data)) + data, tap_bytes(blocks))

    def test_zero_flag_19_bytes_without_header_structure(self):
        data = with_checksum(b"\x00\x42" + bytes(range(16)))
        self.assertEqual(19, len(data))
        blocks = self.assert_decoded(recording([data]), 44100, [data])
        self.assertFalse(blocks[0].is_header)

    def test_headerless_blocks_and_standard_file_in_one_recording(self):
        first = with_checksum(b"\x00" + bytes(range(64)))
        last = with_checksum(b"\x80tail")
        expected = [first, self.header, self.data, last]
        blocks = self.assert_decoded(recording(expected, degraded=True), 44100, expected)
        self.assertEqual([False, True, False, False], [block.is_header for block in blocks])

    def test_headerless_mode_resolves_header_shaped_data(self):
        blocks, issues = decode_audio(recording([self.header]), 44100, headerless=True)
        self.assertEqual([], issues)
        self.assertEqual([self.header], [block.data for block in blocks])
        self.assertFalse(blocks[0].is_header)
        self.assertNotIn("name", blocks[0].summary())

    def test_headerless_mode_still_rejects_bad_checksum(self):
        damaged = self.header[:-1] + bytes([self.header[-1] ^ 1])
        blocks, issues = decode_audio(recording([damaged]), 44100, headerless=True)
        self.assertEqual([], blocks)
        self.assertTrue(any("XOR" in issue.message for issue in issues))

    def test_block_end_not_inferred_from_checksum_or_previous_header(self):
        # The first 34 bytes already have XOR zero, but more data follows.
        longer = with_checksum(self.data + b"\x10\x20")
        blocks, issues = decode_audio(recording([self.header, longer]), 44100)
        self.assertEqual([self.header, longer], [block.data for block in blocks])
        self.assertTrue(any("Délka" in issue.message for issue in issues))
        blocks, issues = decode_audio(recording([self.header, longer]), 44100, headerless=True)
        self.assertEqual([self.header, longer], [block.data for block in blocks])
        self.assertEqual([], issues)

    def test_headerless_short_termination_pulse_before_pause(self):
        data = with_checksum(b"\x00" + bytes(range(64)))
        for tail_seconds in (0.00025, 0.001, 0.006):
            with self.subTest(tail_seconds=tail_seconds):
                audio = recording([data, self.data], tail_seconds=tail_seconds)
                self.assert_decoded(audio, 44100, [data, self.data])

    def test_cli_headerless_mode_writes_header_shaped_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target, report = root / "input.wav", root / "output.tap", root / "report.json"
            wavfile.write(source, 44100, (recording([self.header]) * 32767).astype(np.int16))
            command = [sys.executable, "-m", "tools.wav2tap", str(source), str(target),
                       "--headerless", "--report", str(report)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(struct.pack("<H", len(self.header)) + self.header, target.read_bytes())
            summary = json.loads(report.read_text())
            self.assertTrue(summary["headerless"])
            self.assertFalse(summary["blocks"][0]["is_header"])
            self.assertEqual([], summary["issues"])

    def test_conflicting_valid_stereo_blocks_are_not_selected(self):
        alternative = bytearray(self.data)
        alternative[1], alternative[2] = alternative[2], alternative[1]
        left = recording([self.data])
        right = recording([bytes(alternative)])
        length = max(len(left), len(right))
        stereo = np.column_stack([np.pad(left, (0, length - len(left))),
                                  np.pad(right, (0, length - len(right)))])
        blocks, issues = decode_audio(stereo, 44100)
        self.assertEqual([], blocks)
        self.assertTrue(any("rozdílné" in issue.message for issue in issues))

    def test_missing_data_after_header_is_reported(self):
        blocks, issues = decode_audio(recording([self.header]), 44100)
        self.assertEqual([self.header], [block.data for block in blocks])
        self.assertTrue(any("chybí datový blok" in issue.message for issue in issues))

    def test_truncated_header_is_rejected(self):
        blocks, issues = decode_audio(recording([self.header[:10]]), 44100)
        self.assertEqual([], blocks)
        self.assertTrue(issues)

    def test_silence_and_noise_do_not_create_blocks(self):
        for audio in [np.zeros(44100), np.random.default_rng(1).normal(0, 0.1, 44100)]:
            blocks, _ = decode_audio(audio, 44100)
            self.assertEqual([], blocks)

    def test_unsigned_pcm_and_float_wav(self):
        with tempfile.TemporaryDirectory() as folder:
            for dtype in [np.uint8, np.int16, np.int32, np.float32]:
                with self.subTest(dtype=dtype):
                    audio = recording([self.data])
                    if dtype == np.uint8:
                        encoded = ((audio + 1) * 127.5).astype(dtype)
                    elif np.issubdtype(dtype, np.integer):
                        encoded = (audio * np.iinfo(dtype).max).astype(dtype)
                    else:
                        encoded = audio.astype(dtype)
                    path = Path(folder) / "input.wav"
                    wavfile.write(path, 44100, encoded)
                    fs, decoded = read_wav(path)
                    self.assert_decoded(decoded, fs, [self.data])

    def test_cli_real_wav_report_and_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target, report = root / "input.wav", root / "output.tap", root / "report.json"
            stereo = np.column_stack([recording([self.data]), -recording([self.data])])
            wavfile.write(source, 44100, (stereo * 32767).astype(np.int16))
            command = [sys.executable, "-m", "tools.wav2tap", str(source), str(target),
                       "--report", str(report)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(struct.pack("<H", len(self.data)) + self.data, target.read_bytes())
            self.assertIn('"checksum": "ok"', report.read_text())
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(0, second.returncode)
            self.assertEqual(struct.pack("<H", len(self.data)) + self.data, target.read_bytes())

    def test_cli_partial_output_requires_explicit_option(self):
        damaged = self.data[:-1] + bytes([self.data[-1] ^ 1])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / "input.wav", root / "output.tap"
            audio = recording([self.header, damaged])
            wavfile.write(source, 44100, (audio * 32767).astype(np.int16))
            command = [sys.executable, "-m", "tools.wav2tap", str(source), str(target)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(1, result.returncode)
            self.assertFalse(target.exists())
            partial = subprocess.run(command + ["--allow-partial"], capture_output=True, text=True)
            self.assertEqual(0, partial.returncode, partial.stderr)
            self.assertEqual(struct.pack("<H", len(self.header)) + self.header, target.read_bytes())


if __name__ == "__main__":
    unittest.main()
