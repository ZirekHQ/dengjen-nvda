"""
Tests for language_offer_logic.py: the wx-free decision behind the startup
offer to download a voice for NVDA's interface language (issue #246).
"""

import os
from types import SimpleNamespace

import pytest

from tests.conftest import GLOBAL_PLUGIN_PKG_DIR, load_module_from_path

logic = load_module_from_path(
    "dengjen_tts_global_plugin._language_offer_logic_under_test",
    os.path.join(GLOBAL_PLUGIN_PKG_DIR, "language_offer_logic.py"),
    package="dengjen_tts_global_plugin",
)


def installed(language):
    return SimpleNamespace(language=language)


def catalog(family):
    return SimpleNamespace(language=SimpleNamespace(family=family))


class TestLanguageFamily:
    @pytest.mark.parametrize(
        "code, family",
        [("tr", "tr"), ("tr_TR", "tr"), ("pt-BR", "pt"), ("EN_us", "en")],
    )
    def test_reduces_a_code_to_its_lowercase_family(self, code, family):
        assert logic.language_family(code) == family


class TestLanguageToOffer:
    def test_offers_the_family_when_only_other_languages_are_installed(self):
        assert (
            logic.language_to_offer("tr", [installed("en_US")], [catalog("tr")], set())
            == "tr"
        )

    def test_offers_for_a_regional_nvda_language(self):
        assert (
            logic.language_to_offer(
                "pt_BR", [installed("en_US")], [catalog("pt")], set()
            )
            == "pt"
        )

    def test_skips_when_a_regional_variant_is_installed(self):
        assert (
            logic.language_to_offer("tr", [installed("tr_TR")], [catalog("tr")], set())
            is None
        )

    def test_skips_when_the_language_was_declined(self):
        assert (
            logic.language_to_offer("tr", [installed("en_US")], [catalog("tr")], {"tr"})
            is None
        )

    def test_skips_when_the_catalog_has_no_voice_for_the_language(self):
        assert (
            logic.language_to_offer("tr", [installed("en_US")], [catalog("de")], set())
            is None
        )

    def test_skips_when_the_catalog_is_empty(self):
        assert logic.language_to_offer("tr", [installed("en_US")], [], set()) is None

    def test_skips_when_no_voice_is_installed(self):
        assert logic.language_to_offer("tr", [], [catalog("tr")], set()) is None
