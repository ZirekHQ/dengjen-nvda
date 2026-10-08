# Copyright (c) 2026 Musharraf Omer, Ali Ustek, and contributors
# This file is covered by the GNU General Public License.

"""Phrase cache for Dengjen Neural Voices.

Caches synthesized PCM audio for short, frequently-used phrases to eliminate
gRPC round-trip latency for common UI strings (e.g. "OK", "Cancel", desktop icons).
"""

import threading
from collections import OrderedDict

_MAX_CACHE_SIZE = 120
_MAX_ENTRY_SIZE_BYTES = 12 * 1024  # 12 KB max per phrase


class PhraseCache:
    """Thread-safe LRU cache for synthesized PCM audio chunks."""

    def __init__(
        self,
        max_size: int = _MAX_CACHE_SIZE,
        max_entry_bytes: int = _MAX_ENTRY_SIZE_BYTES,
    ):
        self._max_size = max_size
        self._max_entry_bytes = max_entry_bytes
        self._cache: OrderedDict[tuple, list[bytes]] = OrderedDict()
        self._lock = threading.Lock()

    def _make_key(
        self,
        text: str,
        voice_key: str,
        rate: float | None,
        volume: float | None,
        pitch: float | None,
        normalize: bool,
        night_mode: bool,
        speaker: str | None = None,
    ) -> tuple:
        return (
            text.strip(),
            voice_key,
            speaker,
            round(50.0 if rate is None else rate, 1),
            round(100.0 if volume is None else volume, 1),
            round(50.0 if pitch is None else pitch, 1),
            normalize,
            night_mode,
        )

    def get(
        self,
        text: str,
        voice_key: str,
        rate: float | None,
        volume: float | None,
        pitch: float | None,
        normalize: bool = False,
        night_mode: bool = False,
        speaker: str | None = None,
    ) -> list[bytes] | None:
        """Return cached PCM chunks or None on miss."""
        key = self._make_key(
            text, voice_key, rate, volume, pitch, normalize, night_mode, speaker
        )
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return list(self._cache[key])
            return None

    def put(
        self,
        text: str,
        voice_key: str,
        rate: float | None,
        volume: float | None,
        pitch: float | None,
        normalize: bool,
        night_mode: bool,
        pcm_chunks: list[bytes],
        speaker: str | None = None,
    ):
        """Store PCM chunks in the cache if they are small enough."""
        total_bytes = sum(len(c) for c in pcm_chunks)
        if total_bytes > self._max_entry_bytes or not pcm_chunks:
            return
        key = self._make_key(
            text, voice_key, rate, volume, pitch, normalize, night_mode, speaker
        )
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = list(pcm_chunks)
                return
            self._cache[key] = list(pcm_chunks)
            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def clear(self):
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()


phrase_cache = PhraseCache()
