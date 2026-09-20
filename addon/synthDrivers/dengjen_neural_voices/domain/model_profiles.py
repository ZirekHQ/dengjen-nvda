"""Per-model-type tuning: which NVDA sliders apply and which engine key each uses."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..ports.tts_backend import SynthOptions

SCALE_NAMES = ("length_scale", "noise_scale", "noise_w")


@dataclass(frozen=True)
class ModelProfile:
    tunable: frozenset[str] = frozenset()
    parameter_keys: Mapping[str, str] = field(default_factory=dict)

    def read(self, options: SynthOptions, name: str) -> float | None:
        if name not in self.tunable:
            return None
        key = self.parameter_keys.get(name)
        if key is None:
            return getattr(options, name)
        return options.parameters.get(key)

    def write_kwargs(self, name: str, value: float) -> dict:
        key = self.parameter_keys.get(name)
        if key is None:
            return {name: value}
        return {"parameters": {key: value}}


_NO_TUNING = ModelProfile()

_PROFILES = {
    "piper": ModelProfile(tunable=frozenset(SCALE_NAMES)),
    "melotts": ModelProfile(
        tunable=frozenset(SCALE_NAMES),
        parameter_keys={"noise_w": "noise_scale_w"},
    ),
}


def profile_for(model_type: str) -> ModelProfile:
    return _PROFILES.get(model_type, _NO_TUNING)
