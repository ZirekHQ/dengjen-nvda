# coding: utf-8

"""The TTSBackend port: the one interface a TTS engine adapter must satisfy.

No implementation and no NVDA/gRPC imports live here -- this module is the
seam domain/tts_system.py and every adapters/*_backend implementation both
depend on.
"""

from dataclasses import dataclass
from typing import AsyncIterator, Mapping, Optional, Protocol


@dataclass(frozen=True)
class SynthOptions:
    """A voice's per-utterance synthesis parameters.

    Doubles as both "the defaults a voice loaded with" (LoadedVoice.defaults)
    and "the live value of one option" (TTSBackend.get_synth_options) --
    both are the same four fields.
    """

    speaker: Optional[str]
    length_scale: float
    noise_scale: float
    noise_w: float


@dataclass(frozen=True)
class LoadedVoice:
    """What a backend returns after registering a voice for synthesis."""

    backend_voice_id: str
    supports_streaming_output: bool
    sample_rate: int
    speakers: Mapping[str, str]
    defaults: SynthOptions


class BackendError(Exception):
    """Base for every TTSBackend failure."""


class BackendUnavailableError(BackendError):
    """The backend could not be started or connected to."""


class VoiceLoadError(BackendError):
    """A specific voice failed to load, or a synth-option call on it failed."""


class SynthesisError(BackendError):
    """Audio generation failed for a given utterance."""


class TTSBackend(Protocol):
    """A TTS engine, addressed independently of transport or process shape.

    initialize/check_version/shutdown/load_voice/get_synth_options/
    set_synth_options are blocking calls -- NVDA calls SynthDriver's setter
    properties synchronously from its main thread, so these have to block
    too. Only synthesize() is a true async generator, run from inside the
    dedicated speech-task asyncio loop (see adapters/nvda/synth_driver.py's
    process_speech).
    """

    def initialize(self) -> None: ...

    def check_version(self) -> str: ...

    def shutdown(self) -> None: ...

    def load_voice(self, config_path: str) -> LoadedVoice: ...

    def get_synth_options(self, backend_voice_id: str) -> SynthOptions: ...

    def set_synth_options(self, backend_voice_id: str, **kwargs) -> None: ...

    def synthesize(
        self,
        backend_voice_id: str,
        text: str,
        rate: Optional[float],
        volume: Optional[float],
        pitch: Optional[float],
        sentence_silence_ms: Optional[float],
        streaming: bool,
    ) -> AsyncIterator[bytes]: ...
