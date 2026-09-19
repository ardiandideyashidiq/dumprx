## Why

Setup currently requires a separate manual bash step (`./setup.sh`) that users must discover and remember, first-run creates no guardrail when tools are missing, the dump output directory is hardcoded to `/tmp/out`, and `--help` is a flat argparse listing. The first-run experience and CLI presentation lag the rest of the port.

## What Changes

- `dumprx --setup` runs the pythonized equivalent of `setup.sh`: installs system packages via the detected package manager (apt/dnf/pacman/apk/brew), installs `uv`, clones runtime helper tools into `utils/`, and runs `uv sync`. On success it writes a state file.
- A setup state file (XDG state dir) records that setup completed. On every invocation without `--setup`, if the state file is missing or incomplete, dumprx auto-runs setup before the dump path.
- `--no-setup` bypasses the auto-run (escape hatch for scripts/CI). Auto-run setup failures warn and continue rather than aborting the dump.
- `-o/--output <dir>` sets the dump output directory (`outdir`); default remains `/tmp/out`.
- CLI moves from argparse to click with rich-rendered grouped help (`rich-click` option panels). All existing flags and their semantics are preserved; help output text/rendering changes.
- **BREAKING**: `setup.sh` is removed from the documented setup path and replaced by `dumprx --setup`; README setup instructions update accordingly.

## Capabilities

### New Capabilities

- `setup`: device setup state management — installing system prerequisites, recording completion in a state file, and auto-running setup when the state is missing or incomplete. New `specs/setup/spec.md`.

### Modified Capabilities

- `dumprx`: CLI parity requirement is extended — new `--setup`, `--no-setup`, `-o/--output` options, `outdir` overrideability, and rich grouped help rendering. Delta at `specs/dumprx/spec.md`.

## Impact

- `src/dumprx/cli.py`: argparse parser replaced with a click command; `main()` return-value contract preserved; wires `--setup`/`--no-setup` and `-o/--output`.
- New module for setup logic (system package install, uv install, state read/write) — `ensure_runtime_clones` (currently dead code in `tools.py`) gains its only caller here.
- `src/dumprx/config.py`: state file path resolution (`XDG_STATE_HOME`); `outdir` already accepted by `build_config`, now fed from the CLI.
- `pyproject.toml`: add `click` and `rich-click` runtime deps; `uv.lock` regenerated.
- `setup.sh`: removed (superseded by `--setup`).
- `README.md`: setup + output-dir + help documentation updated.
- `tests/test_cli.py`: parser tests rewritten for the click-based CLI; new tests for setup state gating and `-o/--output`.