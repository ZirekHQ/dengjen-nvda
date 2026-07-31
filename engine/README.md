# Rebuilding the DirectML Sonata engine

The bundled `sonata-grpc.exe` is built from
[`mush42/sonata`](https://github.com/mush42/sonata) commit
`451f9ebf2bd2aa2ba1be25fcec3b7593eeabf6ee`, plus
[`sonata-directml.patch`](sonata-directml.patch).

The patch keeps CPU sessions as a fallback and creates DirectML sessions for
both standard and streaming `+RT` Piper voices when DirectML is available.
The default threshold is zero, so every standard utterance uses DirectML.
Streaming `+RT` voices also use DirectML at all text lengths. The NVDA client
keeps standard requests short so the first completed waveform can start
playing while the next request is generated.
DirectML sessions are serialized because the provider does not support
concurrent `Run` calls on one session; CPU sessions remain concurrent.
Streaming encoder or decoder initialization failures fall back to CPU without
preventing the voice from loading.

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
