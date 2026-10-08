# Copyright (c) 2026 Musharraf Omer, Ali Ustek, and contributors
# This file is covered by the GNU General Public License.

"""Structural reading: alternate speakers for bracketed/quoted text segments."""

import re
from dataclasses import dataclass

_ASIDE_PATTERNS = [
    re.compile(r"\(([^)]{1,200})\)", re.DOTALL),
    re.compile(r"\[([^\]]{1,200})\]", re.DOTALL),
    re.compile(r'"([^"]{1,200})"', re.DOTALL),
    re.compile(r"「([^」]{1,200})」", re.DOTALL),
]


@dataclass
class SpeechSegment:
    text: str
    speaker_name: str | None = None


def _collect_aside_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for pattern in _ASIDE_PATTERNS:
        for m in pattern.finditer(text):
            spans.append((m.start(), m.end()))
    return sorted(spans)


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not spans:
        return []
    merged = [spans[0]]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _build_segments_from_spans(
    text: str,
    merged: list[tuple[int, int]],
    default_speaker: str | None,
    alt_speaker: str | None,
) -> list[SpeechSegment]:
    segments: list[SpeechSegment] = []
    cursor = 0
    effective_alt = alt_speaker or default_speaker

    for aside_start, aside_end in merged:
        if cursor < aside_start:
            main_text = text[cursor:aside_start]
            if main_text.strip():
                segments.append(
                    SpeechSegment(text=main_text, speaker_name=default_speaker)
                )
        aside_text = text[aside_start:aside_end]
        if aside_text.strip():
            segments.append(SpeechSegment(text=aside_text, speaker_name=effective_alt))
        cursor = aside_end

    if cursor < len(text):
        tail = text[cursor:]
        if tail.strip():
            segments.append(SpeechSegment(text=tail, speaker_name=default_speaker))

    return segments


def split_into_segments(
    text: str, default_speaker: str | None = None, alt_speaker: str | None = None
) -> list[SpeechSegment]:
    if not text:
        return []

    spans = _collect_aside_spans(text)
    if not spans:
        return [SpeechSegment(text=text, speaker_name=default_speaker)]

    merged = _merge_spans(spans)
    segments = _build_segments_from_spans(text, merged, default_speaker, alt_speaker)
    return (
        segments
        if segments
        else [SpeechSegment(text=text, speaker_name=default_speaker)]
    )
