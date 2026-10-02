# coding: utf-8

# Copyright (c) 2026 Musharraf Omer, Ali Ustek, and contributors
# This file is covered by the GNU General Public License.

"""
Phrase cache for Dengjen Neural Voices.

Caches synthesized PCM audio for short, frequently-used phrases to eliminate
gRPC round-trip latency for common UI strings (e.g. "OK", "Cancel", desktop icons).
"""

import threading
from collections import OrderedDict
from typing import List, Optional, Tuple


_MAX_CACHE_SIZE = 120
_MAX_ENTRY_SIZE_BYTES = 12 * 1024  # 12 KB max per phrase


class PhraseCache:
    """Thread-safe LRU cache for synthesized PCM audio chunks."""

    def __init__(self, max_size: int = _MAX_CACHE_SIZE, max_entry_bytes: int = _MAX_ENTRY_SIZE_BYTES):
        self._max_size = max_size
        self._max_entry_bytes = max_entry_bytes
        self._cache: OrderedDict[Tuple, List[bytes]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _make_key(self, text: str, voice_key: str, rate: Optional[float], volume: Optional[float], pitch: Optional[float]) -> Tuple:
        return (
            text.strip(),
            voice_key,
            round(rate or 50.0, 1),
            round(volume or 100.0, 1),
            round(pitch or 50.0, 1),
        )

    def get(self, text: str, voice_key: str, rate: Optional[float], volume: Optional[float], pitch: Optional[float]) -> Optional[List[bytes]]:
        """Return cached PCM chunks or None on miss."""
        key = self._make_key(text, voice_key, rate, volume, pitch)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                return list(self._cache[key])
            self._misses += 1
            return None

    def put(self, text: str, voice_key: str, rate: Optional[float], volume: Optional[float], pitch: Optional[float], pcm_chunks: List[bytes]):
        """Store PCM chunks in the cache if they are small enough."""
        total_bytes = sum(len(c) for c in pcm_chunks)
        if total_bytes > self._max_entry_bytes or not pcm_chunks:
            return
        key = self._make_key(text, voice_key, rate, volume, pitch)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = list(pcm_chunks)
                return
            self._cache[key] = list(pcm_chunks)
            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate_voice(self, voice_key: str):
        """Remove all entries for a specific voice (e.g. after voice change)."""
        with self._lock:
            to_delete = [k for k in self._cache if k[1] == voice_key]
            for k in to_delete:
                del self._cache[k]

    def clear(self):
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0


phrase_cache = PhraseCache()
