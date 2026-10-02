# coding: utf-8

# Copyright (c) 2026 Musharraf Omer, Ali Ustek, and contributors
# This file is covered by the GNU General Public License.

"""
Audio post-processing utilities for Dengjen Neural Voices.

Provides:
  - normalize_audio()      : RMS-based volume normalization with peak limiter
  - mono_to_stereo_panned(): Convert mono PCM to stereo with equal-power panning
  - apply_night_mode()     : Soften audio for quiet/night-time listening
"""

import array
import math

_INT16_MAX = 32767
_INT16_MIN = -32768
_TARGET_RMS = 0.20
_PEAK_CEILING = 0.95

_NIGHT_MODE_GAIN = 0.55
_NIGHT_MODE_HIGHFREQ_DAMP = 0.40


def _pcm_to_array(pcm_bytes: bytes) -> array.array:
    a = array.array("h")
    a.frombytes(pcm_bytes)
    return a


def _array_to_pcm(a: array.array) -> bytes:
    return a.tobytes()


def normalize_audio(pcm_bytes: bytes) -> bytes:
    """Normalize the RMS level of 16-bit mono PCM audio."""
    if len(pcm_bytes) < 2:
        return pcm_bytes

    samples = _pcm_to_array(pcm_bytes)
    n = len(samples)
    if n == 0:
        return pcm_bytes

    sum_sq = sum(s * s for s in samples)
    rms = math.sqrt(sum_sq / n) / _INT16_MAX

    if rms < 1e-6:
        return pcm_bytes

    gain = min(_TARGET_RMS / rms, 4.0)
    ceiling = int(_PEAK_CEILING * _INT16_MAX)

    result = array.array("h", (
        max(_INT16_MIN, min(ceiling, int(s * gain)))
        for s in samples
    ))
    return _array_to_pcm(result)


def mono_to_stereo_panned(pcm_bytes: bytes, pan: float) -> bytes:
    """
    Convert 16-bit mono PCM to 16-bit stereo PCM with equal-power panning.
    pan: float in [-1.0, 1.0] (-1.0 = left, 0.0 = center, +1.0 = right)
    """
    if len(pcm_bytes) < 2:
        return pcm_bytes * 2

    pan = max(-1.0, min(1.0, pan))
    angle = (pan + 1.0) / 2.0 * (math.pi / 2.0)
    left_gain = math.cos(angle)
    right_gain = math.sin(angle)

    mono = _pcm_to_array(pcm_bytes)
    stereo = array.array("h")
    for s in mono:
        l = max(_INT16_MIN, min(_INT16_MAX, int(s * left_gain)))
        r = max(_INT16_MIN, min(_INT16_MAX, int(s * right_gain)))
        stereo.append(l)
        stereo.append(r)

    return _array_to_pcm(stereo)


def apply_night_mode(pcm_bytes: bytes) -> bytes:
    """Apply night-mode softening to 16-bit mono PCM audio."""
    if len(pcm_bytes) < 2:
        return pcm_bytes

    samples = _pcm_to_array(pcm_bytes)
    result = array.array("h")
    prev = 0
    alpha = _NIGHT_MODE_HIGHFREQ_DAMP

    for s in samples:
        filtered = int(alpha * s + (1.0 - alpha) * prev)
        prev = filtered
        out = int(filtered * _NIGHT_MODE_GAIN)
        result.append(max(_INT16_MIN, min(_INT16_MAX, out)))

    return _array_to_pcm(result)
