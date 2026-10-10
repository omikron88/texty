"""Standard ROM tape decoder. No guessed bits or checksum repairs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import reduce
from operator import xor
import struct

import numpy as np
from scipy.io import wavfile
from scipy.ndimage import maximum_filter1d, uniform_filter1d
from scipy.signal import butter, sosfilt, sosfiltfilt, sosfilt_zi

CLOCK = 3_500_000
PILOT = 2168 / CLOCK
SYNC = np.array([667, 735]) / CLOCK
ZERO = 855 / CLOCK
ONE = 1710 / CLOCK
MIN_PILOT = 256


def is_standard_header(data):
    """Header-like bytes are inherently ambiguous; --headerless overrides this."""
    return len(data) == 19 and data[0] == 0 and data[1] in (0, 1, 2, 3)


@dataclass
class Block:
    start: float
    end: float
    channel: int
    speed: float
    data: bytes
    is_header: bool = False
    data_start: float | None = None
    threshold_fraction: float = 0.06

    def summary(self):
        result = asdict(self)
        result.pop("data")
        result.update(length=len(self.data), flag=self.data[0], checksum="ok")
        if self.is_header:
            result.update(
                name=self.data[2:12].decode("ascii", errors="replace").rstrip(),
                payload_length=int.from_bytes(self.data[12:14], "little"),
            )
        return result


@dataclass
class Issue:
    start: float
    end: float
    channel: int
    message: str
    threshold_fraction: float | None = None


@dataclass
class SignalAnalysis:
    filtered: np.ndarray
    envelope: np.ndarray
    noise: float

    def threshold(self, fraction):
        return np.maximum(fraction * self.envelope, 3 * self.noise)


@dataclass
class DetectionTrace:
    threshold_fraction: float
    edges: np.ndarray


@dataclass
class ChannelDiagnostics:
    channel: int
    analysis: SignalAnalysis
    traces: list[DetectionTrace]


def read_wav(path):
    """Support integer PCM and IEEE float WAV; normalize without channel mixing."""
    fs, audio = wavfile.read(path)
    if fs < 22050:
        raise ValueError("Vzorkovací frekvence musí být alespoň 22050 Hz.")
    if audio.ndim == 1:
        audio = audio[:, None]
    if audio.ndim != 2 or audio.shape[1] not in (1, 2):
        raise ValueError("Podporován je pouze mono nebo stereo WAV.")
    dtype = audio.dtype
    audio = audio.astype(np.float64)
    if np.issubdtype(dtype, np.unsignedinteger):
        midpoint = 2 ** (dtype.itemsize * 8 - 1)
        audio = (audio - midpoint) / midpoint
    elif np.issubdtype(dtype, np.signedinteger):
        audio /= 2 ** (dtype.itemsize * 8 - 1)
    elif not np.issubdtype(dtype, np.floating):
        raise ValueError("Nepodporovaný formát vzorků WAV.")
    if len(audio) < fs // 10 or not np.isfinite(audio).all():
        raise ValueError("WAV je příliš krátký nebo obsahuje neplatné vzorky.")
    return fs, audio


def prepare_signal(audio, fs):
    """Prepare the same filtered signal for all thresholds and optional plots.

    A causal high pass removes slow DC drift without allowing the following
    pause to shift the baseline of weak final data pulses. Hysteresis follows a local
    amplitude envelope and a robust noise floor, so short weak pulses survive.
    """
    audio = np.asarray(audio, dtype=np.float64)
    if not audio.size or np.max(np.abs(audio)) == 0:
        return SignalAnalysis(np.zeros_like(audio), np.zeros_like(audio), 0.0)
    highpass = butter(2, 40, btype="highpass", fs=fs, output="sos")
    signal, _ = sosfilt(highpass, audio, zi=sosfilt_zi(highpass) * audio[0])
    # Estimate noise before low-pass filtering; subsample for long recordings.
    difference = np.diff(audio, n=2)
    difference = difference[::max(1, len(difference) // 200_000)]
    noise = np.median(np.abs(difference - np.median(difference))) / (0.67449 * np.sqrt(6))
    lowpass = butter(2, min(10000, fs * 0.4), fs=fs, output="sos")
    signal = sosfiltfilt(lowpass, signal)
    window = max(3, round(fs * 0.01))
    envelope = uniform_filter1d(maximum_filter1d(np.abs(signal), window), window)
    return SignalAnalysis(signal, envelope, float(noise))


def detect_edges(analysis, fs, threshold_fraction=0.06):
    """Confirm excursions while keeping the interpolated zero-crossing times."""
    signal = analysis.filtered
    threshold = analysis.threshold(threshold_fraction)

    crossings = np.flatnonzero(np.signbit(signal[:-1]) != np.signbit(signal[1:]))
    if not len(crossings):
        return np.empty(0)
    starts = np.r_[0, crossings + 1]
    # An excursion qualifies if at least one sample exceeds its local threshold.
    strength = np.maximum.reduceat(np.abs(signal) - threshold, starts)
    qualified = np.flatnonzero(strength > 0)
    if len(qualified) < 2:
        return np.empty(0)
    signs = np.signbit(signal[starts[qualified]])
    # Same-polarity excursions separated by noise do not create extra edges.
    transitions = qualified[1:][signs[1:] != signs[:-1]]
    indices = crossings[transitions - 1]
    return (indices - signal[indices] / (signal[indices + 1] - signal[indices])) / fs


def edge_times(audio, fs, threshold_fraction=0.06):
    return detect_edges(prepare_signal(audio, fs), fs, threshold_fraction)


def decode_edges(edges, channel=0, *, headerless=False):
    """Decode to the physical block end, independent of flags/header lengths."""
    pulses = np.diff(edges)
    blocks, issues = [], []
    i = 0
    while i < len(pulses):
        if not 0.65 * PILOT <= pulses[i] <= 1.5 * PILOT:
            i += 1
            continue
        begin = i
        reference = pulses[i]
        i += 1
        while i < len(pulses) and abs(pulses[i] / reference - 1) < 0.13:
            reference = 0.98 * reference + 0.02 * float(pulses[i])
            i += 1
        if i - begin < MIN_PILOT:
            continue
        scale = float(np.median(pulses[begin:i]) / PILOT)
        if i + 1 >= len(pulses) or np.any(np.abs(pulses[i:i + 2] / (SYNC * scale) - 1) > 0.25):
            issues.append(Issue(float(edges[begin]), float(edges[i]), channel,
                                "Pilot bez platné synchronizace."))
            continue

        initial_scale = scale
        i += 2
        data_start = float(edges[i])
        data = bytearray()
        byte, bit_count = 0, 0
        error = None
        while i + 1 < len(pulses):
            first, second = float(pulses[i]), float(pulses[i + 1])
            mean = (first + second) * 0.5
            if first > ONE * scale * 1.8:
                break
            # Some recordings finish with one short level-setting pulse before
            # the pause. Accept it only after whole bytes with a valid checksum;
            # an invalid pair inside data must still fail.
            if (second > ONE * scale * 1.8 and bit_count == 0 and len(data) >= 2
                    and reduce(xor, data, 0) == 0):
                break
            # Frequency response and unequal amplitudes shift individual edges.
            # The full bit period cancels displacement of its middle edge.
            distance_zero = abs(mean / (ZERO * scale) - 1)
            distance_one = abs(mean / (ONE * scale) - 1)
            bit = int(distance_one < distance_zero)
            expected = (ONE if bit else ZERO) * scale
            if (min(distance_zero, distance_one) > 0.22
                    or max(abs(first / expected - 1), abs(second / expected - 1)) > 0.4
                    or abs(first - second) / mean > 0.6):
                error = "Neplatná dvojice datových pulzů."
                break
            # Smooth speed updates and limit them to plausible transport drift.
            observed_scale = mean / (ONE if bit else ZERO)
            scale = max(initial_scale * 0.85,
                        min(initial_scale * 1.15, 0.98 * scale + 0.02 * observed_scale))
            byte = (byte << 1) | bit
            bit_count += 1
            i += 2
            if bit_count == 8:
                data.append(byte)
                byte, bit_count = 0, 0
                if len(data) > 65535:
                    error = "Blok je příliš velký pro TAP."
                    break

        if error is None:
            if bit_count:
                error = "Neúplný datový blok."
            elif len(data) < 2:
                error = "Chybí data nebo kontrolní součet."
            elif reduce(xor, data, 0) != 0:
                error = "Nesouhlasí XOR kontrolní součet."
        end = float(edges[min(i, len(edges) - 1)])
        if error:
            issues.append(Issue(float(edges[begin]), end, channel, error))
        else:
            blocks.append(Block(float(edges[begin]), end, channel, initial_scale, bytes(data),
                                not headerless and is_standard_header(data), data_start))
    return blocks, issues


def decode_audio(audio, fs, *, headerless=False, diagnostics=None):
    """Decode normally; optionally append the actual detector traces to a list."""
    if audio.ndim == 1:
        audio = audio[:, None]
    candidates, failures = [], []
    for channel in range(audio.shape[1]):
        analysis = prepare_signal(audio[:, channel], fs)
        traces = []
        for fraction in (0.06, 0.025, 0.12):
            edges = detect_edges(analysis, fs, fraction)
            blocks, issues = decode_edges(edges, channel, headerless=headerless)
            for block in blocks:
                block.threshold_fraction = fraction
            for issue in issues:
                issue.threshold_fraction = fraction
            candidates.extend(blocks)
            failures.extend(issues)
            if diagnostics is not None:
                traces.append(DetectionTrace(fraction, edges))
        if diagnostics is not None:
            diagnostics.append(ChannelDiagnostics(channel, analysis, traces))

    groups = []
    for block in sorted(candidates, key=lambda b: (b.start, b.channel)):
        matching = next((group for group in groups
                         if min(group[0].end, block.end) - max(group[0].start, block.start)
                         > 0.5 * min(group[0].end - group[0].start, block.end - block.start)), None)
        if matching is None:
            groups.append([block])
        else:
            matching.append(block)
    selected, conflicts = [], []
    for group in groups:
        block = group[0]
        if len({candidate.data for candidate in group}) != 1:
            # Even --allow-partial must never choose an ambiguous XOR collision.
            conflicts.append(Issue(block.start, block.end, block.channel,
                                   "Kanály nebo prahy dávají rozdílné bloky s platným XOR."))
        else:
            selected.append(block)

    unresolved = []
    for issue in failures:
        covered = any(min(block.end, issue.end) - max(block.start, issue.start)
                      > 0.5 * (issue.end - issue.start) for block in selected)
        duplicate = any(abs(previous.start - issue.start) < 0.1 for previous in unresolved)
        if not covered and not duplicate:
            unresolved.append(issue)
    unresolved.extend(conflicts)
    # Validate header/data relationships after merging stereo channels.
    for index, block in enumerate(selected):
        if block.is_header:
            following = selected[index + 1] if index + 1 < len(selected) else None
            expected = int.from_bytes(block.data[12:14], "little") + 2
            if following is None or following.data[0] != 255:
                unresolved.append(Issue(block.end, len(audio) / fs, block.channel,
                                        "Za hlavičkou chybí datový blok s příznakem 255."))
            elif len(following.data) != expected:
                unresolved.append(Issue(following.start, following.end, following.channel,
                                        "Délka datového bloku neodpovídá hlavičce."))
    return sorted(selected, key=lambda b: b.start), unresolved


def tap_bytes(blocks):
    output = bytearray()
    for block in blocks:
        if not 2 <= len(block.data) <= 65535 or reduce(xor, block.data, 0):
            raise ValueError("Neplatný TAP blok.")
        output.extend(struct.pack("<H", len(block.data)))
        output.extend(block.data)
    return bytes(output)
