# Contributing to Dengjen Neural Voices (maintenance fork)

This is a maintenance fork of [mush42/sonata-nvda](https://github.com/mush42/sonata-nvda). The upstream author can no longer maintain the project ([announcement](https://nvda-addons.groups.io/g/nvda-addons/message/27636)); this fork carries compatibility fixes and minor improvements so the add-on keeps working on current NVDA releases.

Contributions are welcome.

## Reporting a bug

Use the **Bug report** template at <https://github.com/austek/dengjen-nvda/issues/new/choose>. The template asks for NVDA version, add-on version, OS, voice tested, steps to reproduce, and an NVDA log slice — please fill in as much as you can. Bugs filed without that info almost always end up labelled `needs-reproducer` until they have it.

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
pytest                    # the stub-based suite -- runs anywhere, incl. Linux
pytest tests_contract/    # real sonata-grpc.exe        (Windows only)
pytest tests_gui/         # real wxPython               (Windows only)
```

Three trees, because the process-wide fakes they need are mutually exclusive:

| Tree | Fakes | Real | Runs on |
| --- | --- | --- | --- |
| `tests/` | NVDA, `wx`, `grpc` | add-on logic | Linux + Windows |
| `tests_contract/` | NVDA | `grpc`, `sonata-grpc.exe` | Windows |
| `tests_gui/` | NVDA | `wxPython` | Windows |

`tests/conftest.py` installs a stub `wx` into `sys.modules` for the whole process, so a test needing real wx cannot live there — hence `tests_gui/`. Same reason `tests_contract/` is separate: it needs the real `grpc` that `tests/` mocks. `pytest.ini`'s `testpaths = tests` keeps both Windows-only trees out of a bare `pytest`, and their test modules self-skip on other platforms, so a Linux `pytest` is always green.

You cannot run `tests_gui/` on Linux at all — wxPython publishes no Linux wheels on PyPI for any release, so `pip install`ing it there is a doomed source build. The tree self-skips instead (see below), and verification happens on the `windows-latest` CI leg.

### How the NVDA stubs work

`tests/nvda_stubs.py` fakes just enough of NVDA's internal API surface (`config`, `languageHandler`, `synthDriverHandler`, `speech.commands`, `nvwave`, `gui`, ...) to import and drive add-on code that would otherwise only run inside a real NVDA process. `install(*, stub_wx: bool = True)` is what `tests/conftest.py` calls; `tests_gui/conftest.py` calls `install(stub_wx=False)` to keep real wxPython. Three helpers do the work:

- `_stub_module(name, **attrs)` — registers a bare `types.ModuleType` in `sys.modules`, for NVDA modules the add-on only touches at the surface (e.g. `config.conf[...]`).
- `load_module_from_path(module_name, path, package=...)` — executes a real add-on `.py` file as a module under the stubs, so its actual logic runs and is covered, instead of being faked.
- `_AutoPropertyMeta` — mimics NVDA's `baseObject.AutoPropertyObject`, turning `_get_x`/`_set_x` pairs into a real `x` property. That is what lets tests do `driver.rate = 50` and have it call `_set_rate`.

Intra-package submodules with hard platform dependencies (`grpc_client`, `aio`) stay fully stubbed in `tests/` rather than executed — tests assert against the calls the driver makes into them.

**Never stub a base class with a `MagicMock`.** Subclassing a `MagicMock()` instance does not raise: it silently produces a `MagicMock` and discards the class body, so every method under test becomes a no-op that still passes. Stub NVDA base classes as plain empty classes, the way `synthDriverHandler.SynthDriver` and `globalPluginHandler.GlobalPlugin` are.

### Adding tests for a new module

1. **Pure logic, no wx?** Put it in `tests/`. If the module only needs modules already stubbed, load it with `load_module_from_path` at the top of your test file (see `tests/test_synth_driver.py` for the pattern of loading `synthDrivers/dengjen_neural_voices/__init__.py` itself).
2. **Needs an NVDA API not yet stubbed?** Add a minimal `_stub_module(...)` call in `tests/nvda_stubs.py` — only the attributes actually touched.
3. **Needs real wx widgets?** Put it in `tests_gui/`, guard the module with `pytest.skip(..., allow_module_level=True)` on non-Windows (see any file under `tests_gui/` for the exact guard), and use the `nvda_gui` fixture for a real parent window.
4. Prefer driving real logic (a real `.py` file executed under stubs) over re-testing a mock; the goal is coverage of add-on code, not of the doubles.

#### `tests_gui/` gotchas

Each of these cost a CI round or a review finding to nail down — read before writing a new `tests_gui/` test:

- **wx swallows exceptions raised inside event handlers.** It prints the traceback to stderr and moves on; nothing propagates to the test, so `pytest.raises` around a `ProcessEvent` call can never see an exception a handler throws. Assert an observable effect instead (see `test_list_view.py`'s mutation-guard tests, which assert via a different code path, not via `ProcessEvent`).
- **`IsEnabled()` is ancestor-aware**: it returns `False` if *any* ancestor is disabled, and several panels are disabled at construction. `IsThisEnabled()` reports only the widget's own flag. Pick the one your assertion actually means (`test_voice_manager_dialog.py` has examples of both, and of the bug you get from using the wrong one).
- **Never re-`Bind` a handler you're trying to verify, and never monkeypatch it.** `Bind` captures the bound method at construction time, so patching the instance attribute afterwards only proves `Bind` + `ProcessEvent` work — that's wxPython's job, not yours to re-test. Fire a real event at the construction-time binding and observe a collaborator the real handler calls (a mocked `gui.*` call, a mocked downloader class, a control's own state).
- **`gui.messageBox` returns `wx.YES` / `wx.NO` / `wx.OK` / `wx.CANCEL`, not `wx.ID_*`.** The `wx.ID_*` constants come from `wx.MessageDialog.ShowModal()`, a different API. The add-on compares `retval == wx.YES`, so a mock returning `wx.ID_YES` looks right but silently skips every confirm-then-act branch.
- **Never call `ShowModal()`.** With no running event loop it blocks until the CI job times out. Construct the dialog, assert against it, `Destroy()` it.

Coverage note: `tests_contract/` and `tests_gui/` are pass/fail gates and contribute nothing to `coverage.xml`, so the modules only they reach stay in `sonar.coverage.exclusions` in `sonar-project.properties`.

## Refreshing the bundled binaries

The add-on bundles three native dependencies built for Python 3.13 / Windows x64:

```bash
python update_grpc.py        # gRPC + protobuf
python update_miniaudio.py   # audio decoding
python update_cffi.py        # C FFI runtime
```

Each script fetches the matching `cp313-win_amd64` wheel from PyPI and swaps the contents under `addon/synthDrivers/dengjen_neural_voices/lib/`.

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
