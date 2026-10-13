"""Headless diagnostic plots using the traces collected during decoding."""

from pathlib import Path

import numpy as np

from .decoder import ONE, PILOT, SYNC, ZERO


def _figure_class():
    try:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
    except ModuleNotFoundError as error:
        raise ValueError("Pro grafy nainstalujte závislosti: python3 -m pip install "
                         "-r tools/wav2tap/requirements-plot.txt") from error
    return Figure, FigureCanvasAgg


def check_plot_support():
    _figure_class()


def plot_window(audio, fs, blocks, issues, start=None, duration=0.02):
    total = len(audio) / fs
    if not np.isfinite(duration) or duration <= 0:
        raise ValueError("Délka detailu grafu musí být kladná a konečná.")
    if start is None:
        focus = (min(issues, key=lambda issue: issue.end).end if issues else
                 (blocks[0].data_start or blocks[0].start) if blocks else 0.0)
        start = max(0.0, min(focus - duration * 0.25, total - duration))
    if not np.isfinite(start) or not 0 <= start < total:
        raise ValueError("Začátek detailu grafu musí ležet uvnitř nahrávky.")
    return float(start), min(total, float(start + duration))


def _wave(ax, signal, fs, start, end, label, color, max_points=8000):
    left, right = max(0, int(start * fs)), min(len(signal), int(np.ceil(end * fs)))
    samples = signal[left:right]
    if len(samples) <= max_points:
        ax.plot(np.arange(left, right) / fs, samples, color=color, lw=0.9, label=label)
        return
    # Min/max bins retain short peaks and dropouts, unlike simple subsampling.
    boundaries = np.linspace(0, len(samples), max_points // 2 + 1, dtype=int)
    minimum = np.minimum.reduceat(samples, boundaries[:-1])
    maximum = np.maximum.reduceat(samples, boundaries[:-1])
    time = (left + (boundaries[:-1] + boundaries[1:] - 1) * 0.5) / fs
    ax.fill_between(time, minimum, maximum, color=color, alpha=0.5, label=label)


def _mark_intervals(ax, blocks, issues, channel, *, labels=False):
    valid_label, invalid_label = "Ověřený blok", "Chybový úsek"
    for block in blocks:
        if block.channel == channel:
            ax.axvspan(block.start, block.end, color="#16a085", alpha=0.13,
                       label=valid_label if labels else None)
            valid_label = None
    for issue in issues:
        if issue.channel == channel:
            ax.axvspan(issue.start, issue.end, color="#d35454", alpha=0.10,
                       label=invalid_label if labels else None)
            ax.axvline(issue.end, color="#c0392b", lw=1, ls="--")
            invalid_label = None


def _trace_for_window(diagnostic, blocks, issues, start, end):
    center = (start + end) / 2
    relevant_issues = [issue for issue in issues if issue.channel == diagnostic.channel
                       and start <= issue.end <= end and issue.threshold_fraction is not None]
    relevant_blocks = [block for block in blocks if block.channel == diagnostic.channel
                       and block.start <= center <= block.end]
    event = relevant_issues[0] if relevant_issues else relevant_blocks[0] if relevant_blocks else None
    fraction = event.threshold_fraction if event else 0.06
    detector = event.detector if event else "zero_crossing"
    cutoff = event.lowpass_hz if event else None
    equalized = event.equalized if event else False
    trace = next(trace for trace in diagnostic.traces if trace.threshold_fraction == fraction
                 and trace.detector == detector and trace.lowpass_hz == cutoff
                 and trace.equalized == equalized)
    speed = relevant_blocks[0].speed if relevant_blocks else 1.0
    return trace, speed, bool(relevant_blocks)


def _references(ax, speed, *, vertical=False, extrema=False):
    entries = [(SYNC[0], "Synchronizace", "#a855a1"),
               (SYNC[1], None, "#a855a1"),
               (ZERO, "Bit 0", "#2980b9"),
               (ONE, "Bit 1", "#e67e22"),
               (PILOT, "Pilot", "#16a085")]
    if extrema:
        entries.append(((ZERO + ONE) / 2, "Přechod 0 ↔ 1", "#64748b"))
    for value, label, color in entries:
        if vertical:
            ax.axvline(value * speed * 1e6, color=color, ls="--", lw=1, label=label)
        else:
            ax.axhline(value * speed * 1e6, color=color, ls="--", lw=1, label=label)


def build_figure(audio, fs, blocks, issues, diagnostics, *, start=None, duration=0.02):
    """Return a Figure for PNG/SVG/PDF export, without a display or pyplot."""
    if audio.ndim == 1:
        audio = audio[:, None]
    if len(diagnostics) != audio.shape[1]:
        raise ValueError("Chybí diagnostika některého kanálu.")
    start, end = plot_window(audio, fs, blocks, issues, start, duration)
    Figure, Canvas = _figure_class()
    channels = audio.shape[1]
    figure = Figure(figsize=(12 if channels == 1 else 18, 12))
    Canvas(figure)
    axes = figure.subplots(4, channels, squeeze=False)
    figure.suptitle(f"Diagnostika kazety · {fs} Hz · Ověřené bloky: {len(blocks)} · "
                   f"Chybová hlášení: {len(issues)}", fontsize=15)
    total = len(audio) / fs

    for column, diagnostic in enumerate(diagnostics):
        channel = diagnostic.channel
        overview, detail, pulses, histogram = axes[:, column]
        trace, speed, calibrated = _trace_for_window(diagnostic, blocks, issues, start, end)
        analysis = trace.analysis if trace.analysis is not None else diagnostic.analysis
        filtered = analysis.filtered
        threshold = analysis.threshold(trace.threshold_fraction)
        extrema = trace.detector == "extrema"

        _wave(overview, audio[:, channel], fs, 0, total, "Původní WAV", "#64748b", 3200)
        _mark_intervals(overview, blocks, issues, channel, labels=True)
        overview.axvspan(start, end, color="#3b82f6", alpha=0.28, label="Zvolený detail")
        overview.set(title=f"Kanál {channel + 1} — celá nahrávka", xlabel="Čas [s]",
                     ylabel="Amplituda", xlim=(0, total))
        overview.legend(loc="upper right", fontsize=8)

        _wave(detail, audio[:, channel], fs, start, end, "Původní WAV", "#94a3b8")
        _wave(detail, filtered, fs, start, end, "Filtrovaný signál", "#2563eb")
        if not extrema:
            _wave(detail, threshold, fs, start, end, "Prahy hystereze", "#d97706")
            _wave(detail, -threshold, fs, start, end, None, "#d97706")
        left, right = np.searchsorted(trace.edges, [start, end])
        edges = trace.edges[left:right]
        visible_edges = edges[::max(1, int(np.ceil(len(edges) / 1500)))]
        if extrema:
            samples = np.clip(np.rint(visible_edges * fs).astype(int), 0, len(filtered) - 1)
            detail.scatter(visible_edges, filtered[samples],
                           color="#7c3aed", s=16, label="Extrémy / středy pulzů")
        else:
            detail.vlines(visible_edges, 0, 1, transform=detail.get_xaxis_transform(),
                          color="#7c3aed", alpha=0.3, lw=0.7, label="Potvrzené hrany")
        detail.axhline(0, color="#475569", lw=0.6)
        _mark_intervals(detail, blocks, issues, channel)
        suffix = f" · zobrazeno {len(visible_edges)}/{len(edges)} hran" if len(edges) > 1500 else ""
        title = (f"Extrémy — filtr {trace.lowpass_hz:g} Hz, prominence {trace.threshold_fraction:g}"
                 if extrema else f"Detail — práh {trace.threshold_fraction:g} × obálka")
        if trace.equalized:
            title += (f" · EQ {diagnostic.equalizer.gain_db:g} dB "
                      f"/ {diagnostic.equalizer.high_hz:g} Hz")
        detail.set(title=title + suffix,
                   xlabel="Čas [s]", ylabel="Amplituda", xlim=(start, end))
        detail.legend(loc="upper right", fontsize=8, ncol=2)

        # Include only complete pulses inside the displayed time interval.
        lengths = np.diff(edges) * 1e6
        times = (edges[:-1] + edges[1:]) / 2
        stride = max(1, int(np.ceil(len(lengths) / 8000)))
        pulses.scatter(times[::stride], lengths[::stride], s=12, color="#475569",
                       label="Intervaly extrémů" if extrema else "Naměřené pulzy")
        _references(pulses, speed, extrema=extrema)
        _mark_intervals(pulses, blocks, issues, channel)
        limit = max(1000, PILOT * speed * 1e6 * 1.6)
        above = int(np.count_nonzero(lengths > limit))
        caption = f"Referenční délky — {'kalibrace pilotem' if calibrated else 'nominální 3,5 MHz'}"
        if above:
            caption += f" · {above} pulzů nad rozsahem"
        duration_label = "Interval extrémů [µs]" if extrema else "Délka pulzu [µs]"
        pulses.set(title=caption, xlabel="Čas [s]", ylabel=duration_label,
                   xlim=(start, end), ylim=(0, limit))
        pulses.legend(loc="upper right", fontsize=8, ncol=3)

        all_lengths = np.diff(trace.edges) * 1e6
        counts, bins = np.histogram(all_lengths, bins=120, range=(0, limit))
        histogram.stairs(counts, bins, fill=True, color="#64748b", alpha=0.55)
        _references(histogram, speed, vertical=True, extrema=extrema)
        histogram.set(title="Histogram celého kanálu — pulzy mimo rozsah: "
                      f"{np.count_nonzero(all_lengths > limit)}", xlabel=duration_label, ylabel="Počet intervalů",
                      xlim=(0, limit), yscale="symlog")
        histogram.legend(loc="upper right", fontsize=8)
        for axis in axes[:, column]:
            axis.grid(alpha=0.18)

    messages = [f"Kanál {issue.channel + 1} · {issue.end:.6f} s: {issue.message}" for issue in issues[:4]]
    if len(issues) > 4:
        messages.append(f"Dalších {len(issues) - 4} hlášení je v JSON protokolu (volba --report).")
    if not messages:
        messages = ["Bez chybových hlášení. Zelené úseky: bloky přijaté do výsledku; "
                    "fialové čáry: hrany; fialové body: středy pulzů z detektoru extrémů."]
    figure.text(0.035, 0.012, "\n".join(messages), fontsize=9, color="#475569")
    figure.tight_layout(rect=(0, 0.025 + 0.014 * len(messages), 1, 0.955))
    return figure


def write_plot(path, audio, fs, blocks, issues, diagnostics, *, start=None, duration=0.02):
    path = Path(path)
    extension = path.suffix.lower().lstrip(".")
    if extension not in ("png", "svg", "pdf"):
        raise ValueError("Graf musí mít příponu .png, .svg nebo .pdf.")
    figure = build_figure(audio, fs, blocks, issues, diagnostics, start=start, duration=duration)
    try:
        with path.open("xb") as stream:
            figure.savefig(stream, format=extension, dpi=150)
    finally:
        figure.clear()
