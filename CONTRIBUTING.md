# Contributing to Sonata Neural Voices (maintenance fork)

This is a maintenance fork of [mush42/sonata-nvda](https://github.com/mush42/sonata-nvda). The upstream author can no longer maintain the project ([announcement](https://nvda-addons.groups.io/g/nvda-addons/message/27636)); this fork carries compatibility fixes and minor improvements so the add-on keeps working on current NVDA releases.

Contributions are welcome.

## Reporting a bug

Use the **Bug report** template at <https://github.com/austek/sonata-nvda/issues/new/choose>. The template asks for NVDA version, add-on version, OS, voice tested, steps to reproduce, and an NVDA log slice — please fill in as much as you can. Bugs filed without that info almost always end up labelled `needs-reproducer` until they have it.

For installation questions or general usage help, check the [readme](readme.md) first and then ask on the [NVDA add-ons community list](https://nvda-addons.groups.io/g/nvda-addons).

## Suggesting a feature

Use the **Feature request** template. Describe the *problem* you're trying to solve, not just the proposed feature — that often suggests cleaner alternatives.

## Development setup

The add-on is built with [SCons](https://scons.org/) targeting Python 3.13 (the version embedded in NVDA 2026.1+). On Windows or any platform with Python 3.13:

```bash
python -m pip install --upgrade pip wheel
pip install scons markdown pytest
```

## Building the add-on

From the repo root:

```bash
scons
```

The build produces a `.nvda-addon` file in the repo root. Install it by opening the file in NVDA (NVDA menu → Tools → Manage add-ons → Install from external source).

To rebuild the translation template (`.pot`):

```bash
scons pot
```

## Running tests

```bash
pytest
```

The test suite (under `tests/`) covers add-on metadata, build helpers, the TTS system, the `SynthDriver` itself, and several pure-Python parsers extracted from the synth driver. It runs on Linux CI — none of it touches a real NVDA install.

### How the NVDA stubs work

`tests/conftest.py` fakes just enough of NVDA's internal API surface (`config`, `languageHandler`, `synthDriverHandler`, `speech.commands`, `nvwave`, `wx`, `gui`, ...) to import and drive add-on code that would otherwise only run inside a real NVDA process. Two helpers do the heavy lifting:

- `_stub_module(name, **attrs)` — registers a bare `types.ModuleType` in `sys.modules` with the given attributes, for NVDA modules the add-on only touches at the surface (e.g. `config.conf[...]`, `wx.ID_ANY`).
- `load_module_from_path(module_name, path, package=...)` — executes a real add-on `.py` file as a module under the stubs, so its actual logic runs and is covered, instead of being faked.

`synthDriverHandler.SynthDriver` additionally carries a small `_AutoPropertyMeta` metaclass that mimics NVDA's `baseObject.AutoPropertyObject`: it turns `_get_x`/`_set_x` method pairs into a real `x` property, which is what lets tests do `driver.rate = 50` and have it actually call `_set_rate`.

Intra-package submodules with hard platform dependencies (`grpc_client`, the real gRPC engine process; `aio`, background event-loop threads) stay fully stubbed rather than executed — tests assert against the calls the driver makes into them, not their real behavior.

### Adding tests for a new module

1. If the module only needs modules already stubbed in `conftest.py`, load it with `load_module_from_path` at the top of your test file (see `tests/test_synth_driver.py` for the pattern of loading `synthDrivers/sonata_neural_voices/__init__.py` itself).
2. If it needs an NVDA API not yet stubbed, add a minimal `_stub_module(...)` call in `conftest.py` — only the attributes actually touched, not a full re-implementation.
3. Prefer driving real logic (real `.py` file executed under stubs) over re-testing a mock; the goal is coverage of add-on code, not of the test doubles.

## Refreshing the bundled binaries

The add-on bundles three native dependencies built for Python 3.13 / Windows x64:

```bash
python update_grpc.py        # gRPC + protobuf
python update_miniaudio.py   # audio decoding
python update_cffi.py        # C FFI runtime
```

Each script fetches the matching `cp313-win_amd64` wheel from PyPI and swaps the contents under `addon/synthDrivers/sonata_neural_voices/lib/`.

## Submitting a PR

Use the pull request template. Link the issue with `Closes #N` in the PR body — GitHub will auto-close the issue when the PR merges.

Conventions used in this fork:

- **Commit messages**: short imperative subject, blank line, then a body that explains *why*. Reference the relevant issue or upstream report (e.g. "Closes #5", "mirrored from upstream mush42/sonata-nvda#30").
- **PR titles**: same conventional-commits style as the lead commit (`fix:`, `feat:`, `chore:`, `docs:`).
- **Branch naming**: `fix/<short-slug>`, `feat/<short-slug>`, `chore/<short-slug>`.
- **No `Co-Authored-By` trailers.**

## Cutting a release

Releases are tag-driven. Push an annotated tag from `main`:

```bash
git tag -a v3.2.0-beta.N -m "v3.2.0-beta.N: <summary>"
git push origin v3.2.0-beta.N
```

CI builds on Ubuntu, runs pytest on `windows-latest`, and publishes a GitHub Release with the `.nvda-addon`, the `.pot`, and an auto-generated `changelog.md` containing the SHA256. Release Drafter maintains a draft release on every push to `main` — open the draft, set the actual tag, then publish.

Tag scheme: standard semver `vMAJOR.MINOR.PATCH(-prerelease)`, e.g. `v3.2.0-beta.5` for a beta or `v3.2.0` for a stable cut. The `-beta.N` portion stays in the git tag only; `addon_version` in `buildVars.py` must remain strict three-part semver (e.g. `3.2.0`) per `tests/test_buildvars.py`.

Historical tags `v3.2-beta.1` through `v3.2-beta.4` used a non-standard two-part scheme (no `.0` patch component). They're left as-is — already published, already linked — but new tags use the standard form so Release Drafter can anchor against them correctly.
