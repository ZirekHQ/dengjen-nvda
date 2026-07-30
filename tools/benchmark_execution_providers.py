#!/usr/bin/env python3
"""Benchmark Sonata CPU and DirectML inference with installed Piper voices.

This script deliberately runs outside NVDA. It starts the bundled gRPC engine
in a fresh process for each voice/provider pair, so model caches and execution
provider state cannot leak between CPU and GPU measurements.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ADDON_PACKAGE = (
    REPOSITORY_ROOT / "addon" / "synthDrivers" / "sonata_neural_voices"
)
GRPC_CLIENT = ADDON_PACKAGE / "grpc_client"
BIN_DIRECTORY = ADDON_PACKAGE / "bin"
DEFAULT_VOICES_DIRECTORY = (
    Path(os.environ["APPDATA"]) / "nvda" / "sonata" / "voices" / "piper"
)
DEFAULT_ESPEAK_DIRECTORY = Path(r"C:\Program Files\NVDA\synthDrivers")

sys.path.insert(0, os.fspath(GRPC_CLIENT))

try:
    import grpc  # noqa: E402
except ImportError:
    # NVDA bundles grpcio for its own Python version. Reuse it when the
    # benchmark runs under that interpreter, while allowing a normal grpcio
    # installation in an isolated development environment.
    sys.path.insert(0, os.fspath(ADDON_PACKAGE / "lib"))
    import grpc  # noqa: E402
from grpc_protos import sonata_grpc_pb2 as messages  # noqa: E402
from grpc_protos.sonata_grpc_pb2_grpc import sonata_grpcStub  # noqa: E402


TEXT_LENGTHS = (
    ("one_word", 1),
    ("very_short", 3),
    ("short_sentence", 8),
    ("sentence", 20),
    ("paragraph", 60),
    ("long_passage", 180),
)

LANGUAGE_TEXT = {
    "de_DE": (
        "Hallo",
        "Diese Stimme liest einen natürlichen deutschen Beispielsatz mit "
        "verschiedenen Wörtern und Satzzeichen für den Geschwindigkeitstest.",
    ),
    "en_US": (
        "Hello",
        "This voice reads a natural English sample sentence with different "
        "words and punctuation for the performance comparison.",
    ),
    "es": (
        "Hola",
        "Esta voz lee una frase natural en español con distintas palabras y "
        "signos de puntuación para comparar el rendimiento.",
    ),
    "fi_FI": (
        "Hei",
        "Tämä ääni lukee luonnollisen suomenkielisen esimerkkilauseen, jossa "
        "on erilaisia sanoja ja välimerkkejä nopeusvertailua varten.",
    ),
    "no_NO": (
        "Hei",
        "Denne stemmen leser en naturlig norsk eksempelsetning med forskjellige "
        "ord og tegnsetting for å sammenligne ytelsen.",
    ),
    "sv_SE": (
        "Hej",
        "Den här rösten läser en naturlig svensk exempelmening med olika ord "
        "och skiljetecken för att jämföra prestandan.",
    ),
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--voices-directory",
        type=Path,
        default=DEFAULT_VOICES_DIRECTORY,
    )
    parser.add_argument(
        "--engine",
        type=Path,
        default=BIN_DIRECTORY / "sonata-grpc.exe",
    )
    parser.add_argument(
        "--bin-directory",
        type=Path,
        default=BIN_DIRECTORY,
    )
    parser.add_argument(
        "--espeak-directory",
        type=Path,
        default=DEFAULT_ESPEAK_DIRECTORY,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "benchmark-results.json",
    )
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=("auto", "cpu", "directml"),
        default=("cpu", "directml"),
    )
    parser.add_argument("--directml-device-id", default="0")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument(
        "--max-words",
        type=int,
        default=180,
        help="Skip benchmark cases longer than this many words.",
    )
    parser.add_argument(
        "--cancel-after-first",
        action="store_true",
        help=(
            "Stress-test cancellation after first audio. Normal benchmarks "
            "consume the stream but only score first-audio latency."
        ),
    )
    parser.add_argument("--voice", action="append", default=[])
    parser.add_argument(
        "--standard-only",
        action="store_true",
        help="Skip +RT streaming voices.",
    )
    parser.add_argument(
        "--streaming-only",
        action="store_true",
        help="Skip standard voices.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Keep completed voice/provider pairs in an existing output file.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print the summary from an existing output file without benchmarking.",
    )
    return parser.parse_args()


def language_from_voice_key(voice_key):
    language = voice_key.split("-", 1)[0]
    if language not in LANGUAGE_TEXT:
        raise ValueError(f"No benchmark text is defined for language {language!r}")
    return language


def text_with_word_count(language, word_count):
    first_word, sentence = LANGUAGE_TEXT[language]
    if word_count == 1:
        return first_word
    words = sentence.split()
    repeated = (words * ((word_count + len(words) - 1) // len(words)))[:word_count]
    text = " ".join(repeated)
    return text.rstrip(".,;:!?") + "."


def find_voice_configs(voices_directory, selected_voices):
    voices = []
    for voice_directory in sorted(path for path in voices_directory.iterdir() if path.is_dir()):
        if selected_voices and voice_directory.name not in selected_voices:
            continue
        configs = sorted(voice_directory.glob("*.json"))
        if len(configs) != 1:
            raise RuntimeError(
                f"Expected one JSON config in {voice_directory}, found {len(configs)}"
            )
        voices.append(
            {
                "key": voice_directory.name,
                "config": configs[0],
                "language": language_from_voice_key(voice_directory.name),
                "streaming": "+RT" in voice_directory.name,
            }
        )
    return voices


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def engine_environment(
    provider,
    port,
    bin_directory,
    espeak_directory,
    directml_device_id,
):
    environment = dict(os.environ)
    environment.update(
        {
            "ORT_DYLIB_PATH": os.fspath(bin_directory / "onnxruntime.dll"),
            "SONATA_DIRECTML_DEVICE_ID": str(directml_device_id),
            "SONATA_ESPEAKNG_DATA_DIRECTORY": os.fspath(espeak_directory),
            "SONATA_EXECUTION_PROVIDER": provider,
            "SONATA_GPU_MIN_PHONEMES": "0",
            "SONATA_GRPC": "debug",
            "SONATA_GRPC_SERVER_PORT": str(port),
            # Patched benchmark engines use this for +RT encoder/decoder sessions.
            "SONATA_STREAMING_EXECUTION_PROVIDER": provider,
        }
    )
    existing_path = environment.get("PATH", "")
    environment["PATH"] = os.pathsep.join((os.fspath(bin_directory), existing_path))
    return environment


def synthesize(
    stub,
    voice_id,
    text,
    streaming,
    *,
    stop_after_first,
    timeout=120,
):
    utterance = messages.Utterance(voice_id=voice_id, text=text)
    method = (
        stub.SynthesizeUtteranceRealtime
        if streaming
        else stub.SynthesizeUtterance
    )
    started = time.perf_counter()
    first_audio_ms = None
    chunks = 0
    audio_bytes = 0
    call = method(utterance, timeout=timeout)
    for response in call:
        now = time.perf_counter()
        if first_audio_ms is None:
            first_audio_ms = (now - started) * 1000
        chunks += 1
        audio_bytes += len(response.wav_samples)
        if stop_after_first:
            call.cancel()
            break
    total_ms = (time.perf_counter() - started) * 1000
    if first_audio_ms is None or audio_bytes == 0:
        raise RuntimeError("The engine returned no audio")
    return {
        "first_audio_ms": first_audio_ms,
        "total_ms": total_ms,
        "chunks": chunks,
        "audio_bytes": audio_bytes,
    }


def benchmark_voice_provider(
    voice,
    provider,
    args,
    log_directory,
):
    port = find_free_port()
    log_path = log_directory / f"{voice['key']}--{provider}.log"
    environment = engine_environment(
        provider,
        port,
        args.bin_directory,
        args.espeak_directory,
        args.directml_device_id,
    )
    records = []
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(
            [os.fspath(args.engine)],
            cwd=os.fspath(args.bin_directory),
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        channel = grpc.insecure_channel(f"127.0.0.1:{port}")
        try:
            grpc.channel_ready_future(channel).result(timeout=30)
            stub = sonata_grpcStub(channel)
            voice_info = stub.LoadVoice(
                messages.VoicePath(config_path=os.fspath(voice["config"])),
                timeout=120,
            )
            for length_name, word_count in TEXT_LENGTHS:
                if word_count > args.max_words:
                    continue
                text = text_with_word_count(voice["language"], word_count)
                for _ in range(args.warmups):
                    synthesize(
                        stub,
                        voice_info.voice_id,
                        text,
                        voice["streaming"],
                        stop_after_first=args.cancel_after_first,
                    )
                for repetition in range(args.repetitions):
                    measurement = synthesize(
                        stub,
                        voice_info.voice_id,
                        text,
                        voice["streaming"],
                        stop_after_first=args.cancel_after_first,
                    )
                    records.append(
                        {
                            "voice": voice["key"],
                            "language": voice["language"],
                            "streaming": voice["streaming"],
                            "provider": provider,
                            "length": length_name,
                            "words": word_count,
                            "characters": len(text),
                            "repetition": repetition + 1,
                            **measurement,
                        }
                    )
        finally:
            channel.close()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    metadata = {
        "voice": voice["key"],
        "provider": provider,
        "log": os.fspath(log_path),
        "directml_enabled": "DirectML acceleration enabled" in log_text
        or "DirectML streaming acceleration enabled" in log_text,
        "directml_inferences": log_text.count("Using DirectML"),
    }
    return records, metadata


def load_or_create_results(args):
    if args.resume and args.output.exists():
        return json.loads(args.output.read_text(encoding="utf-8"))
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "engine": os.fspath(args.engine.resolve()),
        "voices_directory": os.fspath(args.voices_directory.resolve()),
        "repetitions": args.repetitions,
        "warmups": args.warmups,
        "lengths": [
            {"name": name, "words": words} for name, words in TEXT_LENGTHS
        ],
        "records": [],
        "runs": [],
    }


def save_results(results, output):
    output.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def median_cases(records):
    grouped = defaultdict(list)
    for record in records:
        key = (
            record["voice"],
            record["streaming"],
            record["provider"],
            record["length"],
            record["words"],
        )
        grouped[key].append(record)
    cases = {}
    for key, group in grouped.items():
        cases[key] = {
            "total_ms": statistics.median(item["total_ms"] for item in group),
            "first_audio_ms": statistics.median(
                item["first_audio_ms"] for item in group
            ),
        }
    return cases


def print_summary(results):
    cases = median_cases(results["records"])
    comparisons = []
    for key, cpu in cases.items():
        voice, streaming, provider, length, words = key
        if provider != "cpu":
            continue
        gpu = cases.get((voice, streaming, "directml", length, words))
        if gpu is None:
            continue
        comparisons.append(
            {
                "voice": voice,
                "streaming": streaming,
                "length": length,
                "words": words,
                "cpu_total_ms": cpu["total_ms"],
                "gpu_total_ms": gpu["total_ms"],
                "cpu_first_ms": cpu["first_audio_ms"],
                "gpu_first_ms": gpu["first_audio_ms"],
            }
        )

    print(
        "kind,length,words,voices,cpu_total_ms,gpu_total_ms,"
        "total_speedup,cpu_first_ms,gpu_first_ms,first_audio_speedup,"
        "gpu_first_audio_wins"
    )
    for streaming in (False, True):
        for length, words in TEXT_LENGTHS:
            group = [
                item
                for item in comparisons
                if item["streaming"] == streaming and item["length"] == length
            ]
            if not group:
                continue
            cpu_total = statistics.mean(item["cpu_total_ms"] for item in group)
            gpu_total = statistics.mean(item["gpu_total_ms"] for item in group)
            cpu_first = statistics.mean(item["cpu_first_ms"] for item in group)
            gpu_first = statistics.mean(item["gpu_first_ms"] for item in group)
            wins = sum(item["gpu_first_ms"] < item["cpu_first_ms"] for item in group)
            print(
                f"{'streaming' if streaming else 'standard'},"
                f"{length},{words},{len(group)},"
                f"{cpu_total:.3f},{gpu_total:.3f},{cpu_total / gpu_total:.3f},"
                f"{cpu_first:.3f},{gpu_first:.3f},{cpu_first / gpu_first:.3f},"
                f"{wins}/{len(group)}"
            )

    for streaming in (False, True):
        group = [item for item in comparisons if item["streaming"] == streaming]
        if not group:
            continue
        cpu_first = statistics.mean(item["cpu_first_ms"] for item in group)
        gpu_first = statistics.mean(item["gpu_first_ms"] for item in group)
        ratios = [item["cpu_first_ms"] / item["gpu_first_ms"] for item in group]
        geometric_speedup = statistics.geometric_mean(ratios)
        wins = sum(item["gpu_first_ms"] < item["cpu_first_ms"] for item in group)
        print(
            f"OVERALL {'streaming' if streaming else 'standard'}: "
            f"balanced first-audio mean CPU {cpu_first:.3f} ms, "
            f"GPU {gpu_first:.3f} ms, ratio {cpu_first / gpu_first:.3f}x, "
            f"geometric speedup {geometric_speedup:.3f}x, "
            f"GPU first-audio wins {wins}/{len(group)}"
        )


def main():
    args = parse_args()
    if args.standard_only and args.streaming_only:
        raise SystemExit("--standard-only and --streaming-only are mutually exclusive")
    if args.summary_only:
        print_summary(json.loads(args.output.read_text(encoding="utf-8")))
        return

    voices = find_voice_configs(args.voices_directory, set(args.voice))
    if args.standard_only:
        voices = [voice for voice in voices if not voice["streaming"]]
    if args.streaming_only:
        voices = [voice for voice in voices if voice["streaming"]]
    if not voices:
        raise SystemExit("No matching voices found")

    results = load_or_create_results(args)
    completed = {
        (run["voice"], run["provider"])
        for run in results["runs"]
        if run.get("completed")
    }
    log_directory = args.output.with_suffix("").with_name(
        args.output.stem + "-logs"
    )
    log_directory.mkdir(parents=True, exist_ok=True)

    for voice_index, voice in enumerate(voices):
        providers = list(args.providers)
        if voice_index % 2:
            providers.reverse()
        for provider in providers:
            if (voice["key"], provider) in completed:
                continue
            print(f"Benchmarking {voice['key']} with {provider}", flush=True)
            records, metadata = benchmark_voice_provider(
                voice,
                provider,
                args,
                log_directory,
            )
            results["records"].extend(records)
            results["runs"].append({**metadata, "completed": True})
            save_results(results, args.output)

    print_summary(results)


if __name__ == "__main__":
    main()
