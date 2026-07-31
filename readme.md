# Sonata neural voices for NVDA

> **Maintenance fork notice**
>
> The original author, Musharraf Omer ([@mush42](https://github.com/mush42)), [announced on the NVDA Add-ons list](https://nvda-addons.groups.io/g/nvda-addons/message/27636) that commercial contract conflicts prevent him from continuing to maintain this open-source add-on. This fork continues the project to keep the add-on working on current NVDA releases (2026.1+). All credit for the original work belongs to Musharraf Omer; this fork only carries minimal compatibility fixes.

This add-on implements a speech synthesizer driver for NVDA using neural TTS models. It supports [Piper](https://github.com/rhasspy/piper).

[Piper](https://github.com/rhasspy/piper) is a fast, local neural text to speech system that sounds great and is optimized for low-end devices such as the Raspberry Pi.

You can listen to Piper's voice samples here: [Piper voice samples](https://rhasspy.github.io/piper-samples/).

This add-on uses [Sonata: A cross-platform Rust engine for neural TTS models](https://github.com/mush42/sonata) which is being developed by Musharraf Omer.


# Installation

## Downloading the add-on

You can find the add-on package under the assets section of the [release page](https://github.com/austek/sonata-nvda/releases/latest).

## Reporting issues

Please report bugs and feature requests on the [issue tracker for this fork](https://github.com/austek/sonata-nvda/issues).

## Adding voices

The add-on is just  a driver, it comes with no voices by default. You need to download and install the voices you want from the voice manager.

Upon installing the add-on and restarting NVDA, the add-on will ask you to download and install at least one voice, and it will give you the option to open the voice manager.

You can also open the voice manager from NVDA's main menu.

Note that we recommend choosing the `low` or `medium` quality voices for your target language(s), because they generally provide better responsiveness. For additional responsiveness, you can choose to download the `fast` variant of a voice at a cost of slightly lower speech quality.

You can also install voices from local archives. After obtaining the voice's file, open the voice manager, in the installed tab, click the button labeled `Install from local file`. Choose the voice file, wait for the voice to install, and restart NVDA to refresh the voices list.

## GPU acceleration

Sonata prioritizes when the voice actually starts speaking and whether it can
continue without gaps. Standard Piper voices begin with a natural chunk of at
most three words on CPU. Following chunks of at most eight words are generated
while that first speech is playing. Long model-generated tail silence is
removed between chunks, while the final requested sentence silence is kept.

Streaming `+RT` voices keep native real-time output and use DirectML on
supported GPUs. This fixed routing avoids latency changes from switching
providers within one voice type and applies to low, medium, and high quality
voices. The configured speaking rate is not changed.

On the two installed Swedish standard voices used for burst testing, CPU
delivered one, three, and eight words in approximately 43, 75, and 188 ms.
DirectML took approximately 112, 219, and 235 ms for the same cases. The
short CPU start therefore begins standard speech sooner, while background
generation keeps subsequent audio ahead of playback.
The reproducible first-audio benchmark is included as
`tools/benchmark_execution_providers.py`.

DirectML calls are serialized to prevent overlapping inference when NVDA
cancels speech or switches synthesizers. CPU sessions remain concurrent.

Advanced users can set these environment variables before starting NVDA:

- `SONATA_EXECUTION_PROVIDER` controls standard voices. The low-latency default
  is `cpu`; `auto` or `directml` enables DirectML.
- `SONATA_GPU_MIN_PHONEMES` changes the standard-voice crossover point. The
  default is `0`; it is used only when the standard provider is `auto` or
  `directml` and is ignored by the default CPU route.
- `SONATA_STREAMING_EXECUTION_PROVIDER` controls `+RT` voices. The default is
  `directml`; `cpu` disables their GPU acceleration.
- `SONATA_DIRECTML_DEVICE_ID` selects a DirectML adapter. The default is `0`.

## A note on voice quality

The currently available voices are trained using freely available TTS datasets, which are generally of low quality (mostly public domain audio books or research quality recordings).

Additionally, these datasets are not comprehensive, hence some voices may exhibit incorrect or weird pronunciation. Both issues could be resolved by using better datasets for training.

Luckily, the `Piper` developer and some developers from the blind and vision-impaired community are working on training better voices.

# License

Copyright(c) 2024, Musharraf Omer. This software is licensed under The GNU GENERAL PUBLIC LICENSE Version 2 (GPL v2).
