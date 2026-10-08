# Copyright (c) 2026 Musharraf Omer, Ali Ustek, and contributors
# This file is covered by the GNU General Public License.

"""Unit tests for audio_processing.py pure logic."""

import array
import os

from tests.conftest import SYNTH_PKG_DIR, load_module_from_path

audio_proc = load_module_from_path(
    "dengjen_neural_voices.domain._audio_processing_under_test",
    os.path.join(SYNTH_PKG_DIR, "domain", "audio_processing.py"),
    package="dengjen_neural_voices.domain",
)
AudioStreamProcessor = audio_proc.AudioStreamProcessor


def _make_sine_pcm(num_samples: int = 100, amp: int = 10000) -> bytes:
    a = array.array("h")
    for i in range(num_samples):
        # simple square/tri wave approximation for testing
        a.append(amp if (i % 4) < 2 else -amp)
    return a.tobytes()


def test_empty_and_subsample_chunks():
    proc = AudioStreamProcessor()
    assert proc.process_chunk(b"") == b""
    # 1 byte is < 2 bytes, should be buffered in remainder
    assert proc.process_chunk(b"\x01") == b""
    # Feeding 1 more byte completes a 2-byte sample
    res = proc.process_chunk(b"\x02")
    assert res == b"\x01\x02"


def test_odd_byte_carried_across_chunks():
    proc = AudioStreamProcessor()
    # 3 bytes: 1 sample (2 bytes) + 1 trailing odd byte
    chunk1 = b"\x01\x00\x02"
    res1 = proc.process_chunk(chunk1)
    assert res1 == b"\x01\x00"

    # Feeding 1 byte pairs with the odd byte to make 1 sample
    chunk2 = b"\x00"
    res2 = proc.process_chunk(chunk2)
    assert res2 == b"\x02\x00"


def test_passthrough_when_all_modes_disabled():
    proc = AudioStreamProcessor(normalize=False, night_mode=False, spatial_audio=False)
    pcm = _make_sine_pcm(50, amp=8000)
    res = proc.process_chunk(pcm)
    assert res == pcm


def test_normalization_gain_continuity():
    proc = AudioStreamProcessor(normalize=True)
    loud_pcm = _make_sine_pcm(100, amp=20000)
    out1 = proc.process_chunk(loud_pcm)
    assert len(out1) == len(loud_pcm)
    gain1 = proc._norm_gain
    assert gain1 is not None

    # Next chunk with lower volume should smoothly adapt running gain rather than jumping
    quiet_pcm = _make_sine_pcm(100, amp=2000)
    out2 = proc.process_chunk(quiet_pcm)
    assert len(out2) == len(quiet_pcm)
    gain2 = proc._norm_gain
    assert gain2 is not None
    # Gain should have increased smoothly
    assert gain2 > gain1


def test_night_mode_softens_and_preserves_filter_state():
    proc = AudioStreamProcessor(night_mode=True)
    pcm1 = _make_sine_pcm(50, amp=15000)
    out1 = proc.process_chunk(pcm1)
    assert len(out1) == len(pcm1)

    arr1 = array.array("h")
    arr1.frombytes(out1)
    # Night mode attenuates amplitude
    assert max(arr1) < 15000
    assert proc._night_mode_prev != 0

    prev_state = proc._night_mode_prev
    pcm2 = _make_sine_pcm(35, amp=8000)
    out2 = proc.process_chunk(pcm2)
    assert len(out2) == len(pcm2)
    # Filter state updated
    assert proc._night_mode_prev != prev_state


def test_spatial_audio_stereo_panning():
    # Left pan (-1.0)
    proc_left = AudioStreamProcessor(spatial_audio=True, pan=-1.0)
    mono = _make_sine_pcm(20, amp=10000)
    stereo_left = proc_left.process_chunk(mono)
    # Output must be double length (stereo 2 channels)
    assert len(stereo_left) == len(mono) * 2

    arr_left = array.array("h")
    arr_left.frombytes(stereo_left)
    # Samples alternate: L, R, L, R
    left_samples = [arr_left[i] for i in range(0, len(arr_left), 2)]
    right_samples = [arr_left[i] for i in range(1, len(arr_left), 2)]
    # Left channel has sound, right channel near zero
    assert max(map(abs, left_samples)) > 5000
    assert max(map(abs, right_samples)) == 0

    # Right pan (1.0)
    proc_right = AudioStreamProcessor(spatial_audio=True, pan=1.0)
    stereo_right = proc_right.process_chunk(mono)
    arr_right = array.array("h")
    arr_right.frombytes(stereo_right)
    r_left = [arr_right[i] for i in range(0, len(arr_right), 2)]
    r_right = [arr_right[i] for i in range(1, len(arr_right), 2)]
    assert max(map(abs, r_right)) > 5000
    assert max(map(abs, r_left)) == 0


def test_flush_resets_remainder():
    proc = AudioStreamProcessor()
    proc.process_chunk(b"\x01")  # sub-sample stored in remainder
    assert proc._remainder == b"\x01"
    flushed = proc.flush()
    assert flushed == b""
    assert proc._remainder == b""
