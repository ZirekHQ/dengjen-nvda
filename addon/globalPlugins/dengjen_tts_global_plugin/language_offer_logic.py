"""wx-free decision behind the startup offer to download a voice for NVDA's
interface language."""

from __future__ import annotations


def language_family(code: str) -> str:
    return code.replace("-", "_").split("_")[0].lower()


def language_to_offer(nvda_language, installed, catalog, declined) -> str | None:
    """Family to offer a download for, or None.

    No offer without installed voices: the first-run dialog owns that case.
    """
    family = language_family(nvda_language)
    if not installed or family in declined:
        return None
    if any(language_family(v.language) == family for v in installed):
        return None
    if not any(v.language.family == family for v in catalog):
        return None
    return family
