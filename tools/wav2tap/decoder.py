"""Standard ROM tape decoder. No guessed bits or checksum repairs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import reduce
import heapq
from operator import xor
import struct

import numpy as np
from scipy.io import wavfile
from scipy.ndimage import maximum_filter1d, uniform_filter1d
from scipy.signal import butter, find_peaks, sosfilt, sosfiltfilt, sosfilt_zi

CLOCK = 3_500_000
PILOT = 2168 / CLOCK
SYNC = np.array([667, 735]) / CLOCK
ZERO = 855 / CLOCK
ONE = 1710 / CLOCK
MIN_PILOT = 256
MIN_EXCURSION = float(SYNC[0] * 0.45)


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
    detector: str = "zero_crossing"
    lowpass_hz: float | None = None

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
    detector: str = "zero_crossing"
    lowpass_hz: float | None = None


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
    detector: str = "zero_crossing"
    lowpass_hz: float | None = None
    analysis: SignalAnalysis | None = None


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
    edges = (indices - signal[indices] / (signal[indices + 1] - signal[indices])) / fs
    return remove_short_excursions(edges)


def remove_short_excursions(edges, minimum=MIN_EXCURSION):
    """Cancel pairs of edges around very short glitches, shortest first.

    Removing both boundaries preserves polarity. Adjacent short excursions must
    not all be discarded: one may be the genuine edge next to a glitch. A heap
    and linked indices avoid repeatedly copying a long recording's edge array.
    """
    widths = np.diff(edges)
    short = np.flatnonzero(widths < minimum)
    if not len(short):
        return edges
    previous = np.arange(len(edges)) - 1
    following = np.arange(len(edges)) + 1
    following[-1] = -1
    active = np.ones(len(edges), dtype=bool)
    pending = [(float(widths[index]), int(index), int(index + 1)) for index in short]
    heapq.heapify(pending)
    while pending:
        _, left, right = heapq.heappop(pending)
        if not active[left] or not active[right] or following[left] != right:
            continue
        before, after = int(previous[left]), int(following[right])
        active[left] = active[right] = False
        if before >= 0:
            following[before] = after
        if after >= 0:
            previous[after] = before
        if before >= 0 and after >= 0 and edges[after] - edges[before] < minimum:
            heapq.heappush(pending, (float(edges[after] - edges[before]), before, after))
    return edges[active]


def matches_sync(pair, scale, *, centers=False):
    """Constrain each sync pulse and the whole pair when transition edges shift."""
    expected = SYNC * scale
    standard = (np.all(np.abs(pair / expected - 1) <= 0.4)
                and abs(np.sum(pair) / np.sum(expected) - 1) <= 0.20)
    if standard or not centers:
        return standard
    # Ideal pulse centers straddle the final pilot/sync boundary. The second
    # interval must stay below a data-zero interval; do not treat bits as sync.
    geometric = np.array([(PILOT + SYNC[0]) / 2, np.mean(SYNC)]) * scale
    return (np.all(np.abs(pair / geometric - 1) <= np.array([.20, .15]))
            and abs(np.sum(pair) / np.sum(geometric) - 1) <= .15)


def is_termination_tail(pulses, index, scale, data, bit_count):
    """Recognize up to two closing pulses followed by a confirmed long pause.

    Called only for an invalid data pair. Neither a checksum match alone nor a
    header length may truncate valid subsequent data pulses.
    """
    if bit_count or len(data) < 2 or reduce(xor, data, 0):
        return False
    first, second = pulses[index:index + 2]
    gap = ONE * scale * 1.8
    if first < gap and second > gap:
        return True
    return (index + 2 < len(pulses) and pulses[index + 2] > gap
            and max(first, second) < gap and first + second <= ONE * scale * 3)


def edge_times(audio, fs, threshold_fraction=0.06):
    return detect_edges(prepare_signal(audio, fs), fs, threshold_fraction)


def extrema_trace(audio, fs, cutoff, noise, fraction=0.08):
    """Locate alternating maxima/minima even when excursions never cross zero."""
    highpass = butter(2, 40, btype="highpass", fs=fs, output="sos")
    filtered, _ = sosfilt(highpass, audio, zi=sosfilt_zi(highpass) * audio[0])
    filtered = sosfiltfilt(butter(4, cutoff, fs=fs, output="sos"), filtered)
    envelope = maximum_filter1d(np.abs(filtered), round(fs * .002))
    analysis = SignalAnalysis(filtered, envelope, noise)
    prominence = np.maximum(envelope * fraction, 3 * noise)
    kwargs = dict(prominence=prominence, wlen=round(fs * .003),
                  distance=max(1, round(fs * MIN_EXCURSION)))
    high, _ = find_peaks(filtered, **kwargs)
    low, _ = find_peaks(-filtered, **kwargs)
    indices = np.sort(np.r_[high, low])
    positive = np.isin(indices, high)
    kept = []
    for index, sign in zip(indices, positive):
        if kept and sign == kept[-1][1]:
            if (filtered[index] - filtered[kept[-1][0]]) * (1 if sign else -1) > 0:
                kept[-1] = (index, sign)
        else:
            kept.append((index, sign))
    centers = np.array([index / fs for index, _ in kept])
    return DetectionTrace(fraction, centers, "extrema", cutoff, analysis)


def decode_edges(edges, channel=0, *, headerless=False, detector="zero_crossing"):
    """Decode measured edge or center intervals, independent of header lengths."""
    if detector not in ("zero_crossing", "extrema"):
        raise ValueError("Neznámý detektor pulzů.")
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
        if i + 1 >= len(pulses) or not matches_sync(pulses[i:i + 2], scale,
                                                   centers=detector == "extrema"):
            issues.append(Issue(float(edges[begin]), float(edges[i]), channel,
                                "Pilot bez platné synchronizace."))
            continue

        initial_scale = scale
        i += 2
        data_start = float(edges[i])
        data = bytearray()
        byte, bit_count = 0, 0
        error = None
        previous_width = None
        while i + 1 < len(pulses):
            first, second = float(pulses[i]), float(pulses[i + 1])
            mean = (first + second) * 0.5
            if first > ONE * scale * 1.8:
                break
            # Frequency response and unequal amplitudes shift individual edges.
            # The full bit period cancels displacement of its middle edge.
            # Extrema mark pulse centers. The within-bit interval (second) is
            # less sensitive to the preceding bit's different pulse length.
            measured = second if detector == "extrema" else mean
            distance_zero = abs(measured / (ZERO * scale) - 1)
            distance_one = abs(measured / (ONE * scale) - 1)
            bit = int(distance_one < distance_zero)
            expected = (ONE if bit else ZERO) * scale
            if detector == "extrema":
                transition = expected if previous_width is None else (previous_width + expected) / 2
                invalid = (min(distance_zero, distance_one) > .35
                           or min(abs(first / expected - 1), abs(first / transition - 1)) > .4)
            else:
                invalid = (min(distance_zero, distance_one) > 0.22
                           or max(abs(first / expected - 1), abs(second / expected - 1)) > 0.4
                           or abs(first - second) / mean > 0.65)
            if invalid:
                if is_termination_tail(pulses, i, scale, data, bit_count):
                    break
                error = "Neplatná dvojice datových pulzů."
                break
            # Smooth speed updates and limit them to plausible transport drift.
            previous_width = expected
            observed_scale = measured / (ONE if bit else ZERO)
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
                                not headerless and is_standard_header(data), data_start,
                                detector=detector))
    return blocks, issues


def same_recording_block(first, second):
    return (min(first.end, second.end) - max(first.start, second.start)
            > .5 * min(first.end - first.start, second.end - second.start))


def issue_covered(issue, blocks):
    return any(min(block.end, issue.end) - max(block.start, issue.start)
               > .5 * (issue.end - issue.start) for block in blocks)


def extrema_consensus(candidates):
    """Admit a fallback block only if two independent cutoff settings agree."""
    return [block for block in candidates if any(
        peer.lowpass_hz != block.lowpass_hz and peer.data == block.data
        and same_recording_block(peer, block) for peer in candidates)]


def decode_audio(audio, fs, *, headerless=False, diagnostics=None):
    """Decode normally; optionally append the actual detector traces to a list."""
    if audio.ndim == 1:
        audio = audio[:, None]
    candidates, failures = [], []
    for channel in range(audio.shape[1]):
        analysis = prepare_signal(audio[:, channel], fs)
        traces = []
        channel_blocks, channel_issues = [], []
        for fraction in (0.06, 0.025, 0.12):
            edges = detect_edges(analysis, fs, fraction)
            blocks, issues = decode_edges(edges, channel, headerless=headerless)
            for block in blocks:
                block.threshold_fraction = fraction
            for issue in issues:
                issue.threshold_fraction = fraction
            channel_blocks.extend(blocks)
            channel_issues.extend(issues)
            if diagnostics is not None:
                traces.append(DetectionTrace(fraction, edges))
        if any(not issue_covered(issue, channel_blocks) for issue in channel_issues):
            alternative_blocks = []
            for cutoff in (3500, 5000):
                trace = extrema_trace(audio[:, channel], fs, cutoff, analysis.noise)
                blocks, issues = decode_edges(trace.edges, channel, headerless=headerless,
                                              detector="extrema")
                for event in [*blocks, *issues]:
                    event.threshold_fraction = trace.threshold_fraction
                    event.detector = trace.detector
                    event.lowpass_hz = trace.lowpass_hz
                alternative_blocks.extend(blocks)
                channel_issues.extend(issues)
                if diagnostics is not None:
                    traces.append(trace)
            confirmed = extrema_consensus(alternative_blocks)
            channel_blocks.extend(confirmed)
            for block in alternative_blocks:
                if block not in confirmed:
                    channel_issues.append(Issue(block.start, block.end, channel,
                                                "Blok z extrémů nemá potvrzení druhým filtrem.",
                                                block.threshold_fraction, block.detector, block.lowpass_hz))
        candidates.extend(channel_blocks)
        failures.extend(channel_issues)
        if diagnostics is not None:
            diagnostics.append(ChannelDiagnostics(channel, analysis, traces))

    groups = []
    for block in sorted(candidates, key=lambda b: (b.start, b.channel)):
        matching = next((group for group in groups
                         if same_recording_block(group[0], block)), None)
        if matching is None:
            groups.append([block])
        else:
            matching.append(block)
    selected, conflicts = [], []
    for group in groups:
        block = next((candidate for candidate in group if candidate.detector == "zero_crossing"), group[0])
        if len({candidate.data for candidate in group}) != 1:
            # Even --allow-partial must never choose an ambiguous XOR collision.
            conflicts.append(Issue(block.start, block.end, block.channel,
                                   "Kanály nebo prahy dávají rozdílné bloky s platným XOR."))
        else:
            selected.append(block)

    unresolved = []
    for issue in failures:
        if issue_covered(issue, selected):
            continue
        duplicate = next((index for index, previous in enumerate(unresolved)
                          if abs(previous.start - issue.start) < .1), None)
        if duplicate is None:
            unresolved.append(issue)
        elif issue.end > unresolved[duplicate].end:
            unresolved[duplicate] = issue
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
