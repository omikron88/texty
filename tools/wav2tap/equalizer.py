"""Optional tape equalization with a linear-phase FIR and no PCM clipping."""

from dataclasses import asdict, dataclass

import numpy as np
from scipy.signal import firwin2, oaconvolve


@dataclass(frozen=True)
class EqualizerSettings:
    pilot_hz: float = 3_500_000 / (2 * 2168)
    high_hz: float = 4500.0
    gain_db: float = 15.0

    def validate(self, fs):
        if not all(np.isfinite(value) for value in
                   (fs, self.pilot_hz, self.high_hz, self.gain_db)):
            raise ValueError("Nastavení ekvalizéru musí obsahovat konečná čísla.")
        if not 0 < self.pilot_hz < self.high_hz or self.high_hz + 1000 >= fs / 2:
            raise ValueError("Ekvalizér vyžaduje 0 < pilot < horní mez "
                             "a horní mez + 1000 Hz pod polovinou vzorkovací frekvence.")
        if not 0 <= self.gain_db <= 30:
            raise ValueError("Zisk ekvalizéru musí být v rozsahu 0 až 30 dB.")

    def summary(self):
        return dict(asdict(self), stop_db=-40.0, low_stop_hz=self.pilot_hz * .62,
                    high_stop_hz=self.high_hz + 1000)


def design_equalizer(fs, settings):
    """Rise linearly in dB/log-frequency from pilot to the upper passband."""
    settings.validate(fs)
    band = np.geomspace(settings.pilot_hz, settings.high_hz, 33)
    db = settings.gain_db * np.log(band / settings.pilot_hz) / np.log(
        settings.high_hz / settings.pilot_hz)
    frequencies = np.r_[0, settings.pilot_hz * .62, band,
                        settings.high_hz + 1000, fs / 2]
    gain = np.r_[.01, .01, 10 ** (db / 20), .01, .01]
    # About 21 ms at every supported sample rate; odd length permits exact
    # compensation of the integer group delay using centered convolution.
    taps = 2 * round(fs * (512 / 48000)) + 1
    return firwin2(taps, frequencies, gain, fs=fs)


def apply_equalizer(audio, coefficients):
    """Process one channel; extend its endpoints to avoid artificial steps."""
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim != 1:
        raise ValueError("Ekvalizér zpracovává vždy jeden kanál.")
    if not len(audio):
        return audio.copy()
    half = len(coefficients) // 2
    padded = np.pad(audio, (half, half), mode="edge")
    return oaconvolve(padded, coefficients, mode="valid")
