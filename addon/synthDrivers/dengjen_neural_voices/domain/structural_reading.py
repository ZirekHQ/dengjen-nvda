# coding: utf-8

# Copyright (c) 2026 Musharraf Omer, Ali Ustek, and contributors
# This file is covered by the GNU General Public License.

"""
Structural reading: alternate speakers for bracketed/quoted text segments.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

_ASIDE_PATTERNS = [
    re.compile(r"\(([^)]{1,200})\)", re.DOTALL),
    re.compile(r"\[([^\]]{1,200})\]", re.DOTALL),
    re.compile(r'"([^"]{1,200})"', re.DOTALL),
    re.compile(r"「([^」]{1,200})」", re.DOTALL),
]


@dataclass
class SpeechSegment:
    text: str
    speaker_index: Optional[int] = None


def split_into_segments(text: str) -> List[SpeechSegment]:
    if not text:
        return []

    aside_spans = []
    for pattern in _ASIDE_PATTERNS:
        for m in pattern.finditer(text):
            aside_spans.append((m.start(), m.end()))

    if not aside_spans:
        return [SpeechSegment(text=text)]

    aside_spans.sort()
    merged = [aside_spans[0]]
    for start, end in aside_spans[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    segments: List[SpeechSegment] = []
    cursor = 0
    for aside_start, aside_end in merged:
        if cursor < aside_start:
            main_text = text[cursor:aside_start]
            if main_text.strip():
                segments.append(SpeechSegment(text=main_text, speaker_index=None))
        aside_text = text[aside_start:aside_end]
        if aside_text.strip():
            segments.append(SpeechSegment(text=aside_text, speaker_index=1))
        cursor = aside_end

    if cursor < len(text):
        tail = text[cursor:]
        if tail.strip():
            segments.append(SpeechSegment(text=tail, speaker_index=None))

    return segments if segments else [SpeechSegment(text=text)]
