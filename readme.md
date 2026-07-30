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

Sonata automatically chooses CPU or DirectML for standard Piper voices.
Segments shorter than 64 phonemes use CPU to avoid GPU startup overhead;
larger segments use DirectML. Streaming `+RT` voices use DirectML at all text
lengths. DirectML works with DirectX 12-capable NVIDIA, AMD, and Intel GPUs and
does not require the CUDA toolkit. If DirectML or a compatible GPU is
unavailable, each voice falls back to CPU inference automatically.

The default was selected from 900 complete-audio measurements across all 19
voices installed on the test computer, covering Swedish, English, Spanish,
Norwegian, German, and Finnish text from one to 180 words. The measurement
stops when the engine has generated and delivered the entire audio result;
playback duration is not included.

On an RTX 4060 Laptop GPU, standard one-word text averaged 76 ms on CPU versus
104 ms on GPU, and three-word text averaged 159 ms on CPU versus 239 ms on
GPU. From eight words, GPU averaged 276 ms versus 326 ms on CPU, with the gap
increasing for longer text. Complete generation for streaming `+RT` voices
averaged 597 ms on GPU versus 1,387 ms on CPU across the tested lengths.
The reproducible first-audio benchmark is included as
`tools/benchmark_execution_providers.py`.

DirectML calls are serialized to prevent overlapping inference when NVDA
cancels speech or switches synthesizers. CPU sessions remain concurrent.

Advanced users can set these environment variables before starting NVDA:

- `SONATA_EXECUTION_PROVIDER=cpu` disables GPU acceleration. The default is
  `auto`; `directml` also enables DirectML.
- `SONATA_GPU_MIN_PHONEMES` changes the standard-voice crossover point. The
  tested default is `64`.
- `SONATA_STREAMING_EXECUTION_PROVIDER=cpu` keeps only `+RT` voices on CPU.
- `SONATA_DIRECTML_DEVICE_ID` selects a DirectML adapter. The default is `0`.

## A note on voice quality

The currently available voices are trained using freely available TTS datasets, which are generally of low quality (mostly public domain audio books or research quality recordings).

Additionally, these datasets are not comprehensive, hence some voices may exhibit incorrect or weird pronunciation. Both issues could be resolved by using better datasets for training.

Luckily, the `Piper` developer and some developers from the blind and vision-impaired community are working on training better voices.

# License

Copyright(c) 2024, Musharraf Omer. This software is licensed under The GNU GENERAL PUBLIC LICENSE Version 2 (GPL v2).
