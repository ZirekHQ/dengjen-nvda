import pytest
from dengjen_neural_voices.domain.model_profiles import SCALE_NAMES, profile_for
from dengjen_neural_voices.ports.tts_backend import SynthOptions


def _options(**overrides):
    base = {
        "speaker": None,
        "length_scale": 1.0,
        "noise_scale": 0.667,
        "noise_w": 0.8,
    }
    return SynthOptions(**{**base, **overrides})


def test_piper_reads_all_three_scales_from_named_fields():
    profile = profile_for("piper")
    values = [profile.read(_options(), name) for name in SCALE_NAMES]
    assert values == [1.0, 0.667, 0.8]


def test_melotts_reads_noise_w_from_its_engine_parameter():
    profile = profile_for("melotts")
    options = _options(parameters={"noise_scale_w": 0.55})
    assert profile.read(options, "noise_w") == 0.55
    assert profile.read(options, "noise_scale") == 0.667


def test_melotts_writes_noise_w_as_a_parameter():
    assert profile_for("melotts").write_kwargs("noise_w", 0.4) == {
        "parameters": {"noise_scale_w": 0.4}
    }


def test_piper_writes_noise_w_as_its_named_field():
    assert profile_for("piper").write_kwargs("noise_w", 0.4) == {"noise_w": 0.4}


@pytest.mark.parametrize("model_type", ["kokoro", "unknown"])
def test_untunable_models_have_no_sliders(model_type):
    profile = profile_for(model_type)
    assert profile.tunable == frozenset()
    assert profile.read(_options(), "noise_scale") is None
