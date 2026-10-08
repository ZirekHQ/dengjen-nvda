# Copyright (c) 2026 Musharraf Omer, Ali Ustek, and contributors
# This file is covered by the GNU General Public License.

"""Unit tests for phrase_cache.py pure logic."""

import os

from tests.conftest import SYNTH_PKG_DIR, load_module_from_path

phrase_cache_module = load_module_from_path(
    "dengjen_neural_voices.domain._phrase_cache_under_test",
    os.path.join(SYNTH_PKG_DIR, "domain", "phrase_cache.py"),
    package="dengjen_neural_voices.domain",
)
PhraseCache = phrase_cache_module.PhraseCache


def test_rate_zero_does_not_collide_with_rate_fifty():
    cache = PhraseCache()
    chunk_0 = [b"\x00\x01\x00\x02"]
    chunk_50 = [b"\x00\x03\x00\x04"]

    cache.put(
        "test",
        "v1",
        rate=0.0,
        volume=100.0,
        pitch=50.0,
        normalize=False,
        night_mode=False,
        pcm_chunks=chunk_0,
    )
    cache.put(
        "test",
        "v1",
        rate=50.0,
        volume=100.0,
        pitch=50.0,
        normalize=False,
        night_mode=False,
        pcm_chunks=chunk_50,
    )

    res_0 = cache.get(
        "test",
        "v1",
        rate=0.0,
        volume=100.0,
        pitch=50.0,
        normalize=False,
        night_mode=False,
    )
    res_50 = cache.get(
        "test",
        "v1",
        rate=50.0,
        volume=100.0,
        pitch=50.0,
        normalize=False,
        night_mode=False,
    )

    assert res_0 == chunk_0
    assert res_50 == chunk_50
    assert res_0 != res_50


def test_volume_zero_and_pitch_zero_do_not_collide():
    cache = PhraseCache()
    chunk_vol0 = [b"\x11\x11"]
    chunk_vol100 = [b"\x22\x22"]

    cache.put(
        "hello",
        "v1",
        rate=50.0,
        volume=0.0,
        pitch=50.0,
        normalize=False,
        night_mode=False,
        pcm_chunks=chunk_vol0,
    )
    cache.put(
        "hello",
        "v1",
        rate=50.0,
        volume=100.0,
        pitch=50.0,
        normalize=False,
        night_mode=False,
        pcm_chunks=chunk_vol100,
    )

    assert (
        cache.get(
            "hello",
            "v1",
            rate=50.0,
            volume=0.0,
            pitch=50.0,
            normalize=False,
            night_mode=False,
        )
        == chunk_vol0
    )
    assert (
        cache.get(
            "hello",
            "v1",
            rate=50.0,
            volume=100.0,
            pitch=50.0,
            normalize=False,
            night_mode=False,
        )
        == chunk_vol100
    )

    chunk_pitch0 = [b"\x33\x33"]
    chunk_pitch50 = [b"\x44\x44"]

    cache.put(
        "pitch",
        "v1",
        rate=50.0,
        volume=100.0,
        pitch=0.0,
        normalize=False,
        night_mode=False,
        pcm_chunks=chunk_pitch0,
    )
    cache.put(
        "pitch",
        "v1",
        rate=50.0,
        volume=100.0,
        pitch=50.0,
        normalize=False,
        night_mode=False,
        pcm_chunks=chunk_pitch50,
    )

    assert (
        cache.get(
            "pitch",
            "v1",
            rate=50.0,
            volume=100.0,
            pitch=0.0,
            normalize=False,
            night_mode=False,
        )
        == chunk_pitch0
    )
    assert (
        cache.get(
            "pitch",
            "v1",
            rate=50.0,
            volume=100.0,
            pitch=50.0,
            normalize=False,
            night_mode=False,
        )
        == chunk_pitch50
    )


def test_none_numeric_settings_use_sensible_defaults():
    cache = PhraseCache()
    chunk = [b"\xaa\xbb"]
    cache.put(
        "hi",
        "v1",
        rate=None,
        volume=None,
        pitch=None,
        normalize=False,
        night_mode=False,
        pcm_chunks=chunk,
    )
    # Looking up with default values (50.0, 100.0, 50.0) should hit the entry stored with None
    assert (
        cache.get(
            "hi",
            "v1",
            rate=50.0,
            volume=100.0,
            pitch=50.0,
            normalize=False,
            night_mode=False,
        )
        == chunk
    )


def test_normalize_and_night_mode_differentiate_cache():
    cache = PhraseCache()
    c_norm = [b"\x01"]
    c_night = [b"\x02"]
    c_plain = [b"\x03"]

    cache.put(
        "text",
        "v1",
        rate=50,
        volume=100,
        pitch=50,
        normalize=True,
        night_mode=False,
        pcm_chunks=c_norm,
    )
    cache.put(
        "text",
        "v1",
        rate=50,
        volume=100,
        pitch=50,
        normalize=False,
        night_mode=True,
        pcm_chunks=c_night,
    )
    cache.put(
        "text",
        "v1",
        rate=50,
        volume=100,
        pitch=50,
        normalize=False,
        night_mode=False,
        pcm_chunks=c_plain,
    )

    assert (
        cache.get(
            "text",
            "v1",
            rate=50,
            volume=100,
            pitch=50,
            normalize=True,
            night_mode=False,
        )
        == c_norm
    )
    assert (
        cache.get(
            "text",
            "v1",
            rate=50,
            volume=100,
            pitch=50,
            normalize=False,
            night_mode=True,
        )
        == c_night
    )
    assert (
        cache.get(
            "text",
            "v1",
            rate=50,
            volume=100,
            pitch=50,
            normalize=False,
            night_mode=False,
        )
        == c_plain
    )


def test_speaker_differentiates_cache():
    cache = PhraseCache()
    spk1_chunk = [b"\x01\x01"]
    spk2_chunk = [b"\x02\x02"]

    cache.put(
        "text",
        "v1",
        rate=50,
        volume=100,
        pitch=50,
        normalize=False,
        night_mode=False,
        pcm_chunks=spk1_chunk,
        speaker="spk1",
    )
    cache.put(
        "text",
        "v1",
        rate=50,
        volume=100,
        pitch=50,
        normalize=False,
        night_mode=False,
        pcm_chunks=spk2_chunk,
        speaker="spk2",
    )

    assert (
        cache.get(
            "text",
            "v1",
            rate=50,
            volume=100,
            pitch=50,
            normalize=False,
            night_mode=False,
            speaker="spk1",
        )
        == spk1_chunk
    )
    assert (
        cache.get(
            "text",
            "v1",
            rate=50,
            volume=100,
            pitch=50,
            normalize=False,
            night_mode=False,
            speaker="spk2",
        )
        == spk2_chunk
    )


def test_lru_eviction():
    cache = PhraseCache(max_size=2)
    cache.put("t1", "v1", 50, 100, 50, False, False, [b"1"])
    cache.put("t2", "v1", 50, 100, 50, False, False, [b"2"])
    cache.put("t3", "v1", 50, 100, 50, False, False, [b"3"])

    # t1 should be evicted
    assert cache.get("t1", "v1", 50, 100, 50, False, False) is None
    assert cache.get("t2", "v1", 50, 100, 50, False, False) == [b"2"]
    assert cache.get("t3", "v1", 50, 100, 50, False, False) == [b"3"]


def test_max_entry_bytes_rejection():
    cache = PhraseCache(max_entry_bytes=10)
    big_chunk = [b"x" * 11]
    cache.put("big", "v1", 50, 100, 50, False, False, big_chunk)
    assert cache.get("big", "v1", 50, 100, 50, False, False) is None


def test_clear():
    cache = PhraseCache()
    cache.put("t", "v1", 50, 100, 50, False, False, [b"data"])
    assert cache.get("t", "v1", 50, 100, 50, False, False) == [b"data"]
    cache.clear()
    assert cache.get("t", "v1", 50, 100, 50, False, False) is None
