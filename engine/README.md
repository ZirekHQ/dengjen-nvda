# Rebuilding the DirectML Sonata engine

The bundled `sonata-grpc.exe` is built from
[`mush42/sonata`](https://github.com/mush42/sonata) commit
`451f9ebf2bd2aa2ba1be25fcec3b7593eeabf6ee`, plus
[`sonata-directml.patch`](sonata-directml.patch).

The patch keeps a CPU session for low-latency screen-reader utterances and
creates a DirectML session for standard Piper voices when DirectML is
available. Inference switches to DirectML only at the configured phoneme
threshold. Streaming `+RT` voices remain CPU-only.

The `build-sonata-engine.yml` workflow checks out the pinned source and
submodules, applies the patch, builds the gRPC frontend with dynamic ONNX
Runtime and DirectML support, and packages:

- `sonata-grpc.exe`
- `onnxruntime.dll`
- `onnxruntime_providers_shared.dll`
- `DirectML.dll`
- the ONNX Runtime license and third-party notices

The runtime DLLs come from the pinned `onnxruntime-directml` Python wheel.
The add-on launcher sets `ORT_DYLIB_PATH` to the bundled runtime explicitly.
