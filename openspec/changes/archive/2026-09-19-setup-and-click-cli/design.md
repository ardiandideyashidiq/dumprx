## Context

See proposal.md - Why. Current state that shapes the approach:

- `cli.py:37` `build_parser()` is argparse; `cli.py:124` `main()` returns an `int`, wired via `[project.scripts] dumprx = dumprx.cli:main` (pyproject.toml:13). Tests drive `cli.main([...])` and assert the int return.
- `config.py:180` `build_config()` already accepts `outdir` and threads it into `Paths` (`workdir = outdir/tmp`, `log_path = workdir/dumprx.log`, config.py:186-193) — but `cli.py` never passes it, so `OUTDIR` is pinned to `/tmp/out`.
- `tools.py:89` `ensure_runtime_clones(utilsdir)` clones the five `RUNTIME_CLONES` repos into `utils/` in parallel. It is defined but **never called** anywhere in `src/` — setup becomes its caller.
- `setup.sh` (116 lines of bash) detects the package manager by `command -v` order apt > dnf > pacman > apk (brew on darwin), installs its fixed package list with a `sudo` prefix when not root, then curls the astral `uv` installer (as the `SUDO_USER` when applicable) and aborts on any failure.
- `process.run()` (process.py:44) always discards stdout/stderr when `capture=False` (DEVNULL). Package-manager installs need visible progress and a `sudo` TTY prompt, so setup cannot reuse it for the install steps.

## Goals / Non-Goals

**Goals:**
- One setup path: `dumprx --setup`, plus an auto-run gate keyed off a machine-scoped state file.
- `-o/--output` flows into the existing `build_config(outdir=...)` seam.
- Help rendered by rich into named option groups; all current flags keep their semantics; `main() -> int` contract preserved for the console script and tests.

**Non-Goals:**
- No CLI subcommands (`dumprx dump|setup|...`) — that is a second breaking change.
- No version-gated re-setup in the state file (stored `version` is informational only).
- No per-package prompting or user-selectable setup subsets.
- No changes to the distro package lists — mirrored verbatim from `setup.sh` for parity.
- Not touching `process.py`; setup runs its own interactively-visible subprocesses.

## Decisions

### D1: click + rich-click (imported as `click`), not native click rich
`--help` currently renders one flat argparse table. "Grouped" help requires named option panels. Native `click.RichGroup` (click >= 8.2) renders rich help but only a single Options panel. `rich-click` provides `@click.option_panel(...)` / `@click.command_panel(...)` for named panels (e.g. "Mode", "Setup", "Pipeline", "Output"). Decision: add `click` + `rich-click` runtime deps, `import rich_click as click`, group options into panels via `option_panel`.
Alternatives: native `click.RichGroup` + custom help formatter (more code, limited panel control — rejected); staying on argparse with a custom rich help printer (misses the click ask — rejected).

### D2: Keep the single flat command
`dumprx [OPTIONS] [FIRMWARE]` with `--setup`/`--no-setup` as options, exactly matching today's script-shaped interface. `main(argv=None) -> int` wraps a click group invoked with `standalone_mode=False`, catching `click.exceptions.Exit` (help/`--help` exit 0) and `click.exceptions.ClickException`/`UsageError` (print and return non-zero). Failing `-m <bad>` becomes a click UsageError instead of argparse's SystemExit — the CLI tests are rewritten accordingly.

### D3: Mode aliases keep "last wins"
`-m/--mode` is a `click.Choice`; `-g/--gitlab`, `-b/--github`, `-l/--local` are `is_flag, expose_value=False` options whose shared callback writes `ctx.obj["mode"]`. Click evaluates options in command-line order, so `dumprx -l -g` resolves to `gitlab` naturally, preserving the current argparse shared-dest behavior (test_cli.py:34).
Also fixes the help-wording bug where `-m` claims "default: local" but the code default is `gitlab` (cli.py:55).

### D4: `-o/--output` via the existing seam
A `click.Path(path_type=Path)` option, default `None`, forwarded as `outdir=Path(...) if value else None` into `build_config`. `Paths.outdir`/`workdir`/`log_path` already derive from it, so `--push-only` and `--readme-only` pick up the custom OUTDIR with no further plumbing.

### D5: New `dumprx/setup.py` module (not bash), state in XDG
Module name `setup` inside the package (repo root has no `setup.py`; no setuptools collision). Contents:
- `state_path()`: `${XDG_STATE_HOME:-~/.local/state}/dumprx/state.json` — machine-scoped, survives repo re-clones (system packages are machine-wide). Alternative: project `./.dumprx/state.json` — rejected, resets on re-clone.
- `setup_complete()` / `mark_complete()`: JSON `{"complete": true, "os", "pm", "version", "at"}`.
- `detect_package_manager()`: `command -v` order apt > dnf > pacman > apk (linux), brew (darwin) — mirrors setup.sh. Unknown distro -> `None` with warning, continue.
- Fixed package lists copied verbatim from setup.sh lines 60/70/79/87/97 keyed by manager.
- `run_visible(argv)`: local helper using stdlib `subprocess.run` with inherited stdio (sudo TTY + progress visible, unlike `process.run`'s DEVNULL), raising on non-zero (setup.sh `abort` parity).
- `run_setup(config, *, explicit) -> int`: detect pm -> install packages (sudo-prefixed when not root; osx skip) -> install uv via `bash -c "$(curl -sL https://astral.sh/uv/install.sh)"` as `SUDO_USER` when sudo used (setup.sh:106-110 parity) -> `ensure_runtime_clones(utilsdir)` -> `uv sync` in `project_dir` -> `mark_complete()`. Explicit failure -> return 1; auto failure -> warn and still finish normally (spec: auto-setup tolerance).
- `state_path()`, `detect_package_manager`, `run_visible`, `mark_complete` stay un-discoverable public functions so tests can exercise the gate without running real installs.

### D6: Main() wiring for setup gating
New order in `main`: parse -> bootstrap logger -> build config -> route:
```
args.setup            -> run_setup(explicit=True)            ; 0/1
not args.no_setup and not setup_complete()                  -> run_setup(explicit=False)  # warn-and-continue
otherwise                                                   -> existing dump path
```
`--setup` exits before the firmware-required check, so `dumprx --setup` needs no positional. Auto-run happens for `--readme-only`/`--push-only` too. `--no-setup` skips the gate entirely.

### D7: Dead-code activation
`ensure_runtime_clones` becomes the only place clones happen; `--setup` (explicit or auto) guarantees the `utils/` clones that OZIP/OFP/PAC extractors seek via `TOOL_MAP`. Previously nothing invoked it, so those extractors relied on a manual/untracked clone.

## Risks / Trade-offs

- **Auto-run invokes sudo + network on first dump** -> Mitigated by `--no-setup` escape and warn-and-continue on failure; the gate runs once, recorded by the state file.
- **selinux/immutable HOME or read-only XDG_STATE_HOME** -> `mark_complete` failure must not abort an explicit setup; log a warning and continue (state gate simply re-runs next time). Recorded as a task.
- **Package list drift from `setup.sh`** -> Lists are copied verbatim; if a distro list is later wrong, the fix is a one-line change in `setup.py` only.
- **Click migration churn in `tests/test_cli.py`** -> All parser tests rewrite to drive `cli.main()` with monkeypatched `build_config` (existing pattern); the flag-parity table is preserved as assertions on captured config kwargs.
- **Pinned CLI semantics change (argparse -> click error messages/exit codes)** -> Observable difference is limited to error wording and `-m bogus` returning 2 (click UsageError) instead of argparse's general non-zero; documented as breaking in proposal.

## Migration Plan

- No intermediate dual-path: `setup.sh` is deleted in this change and README setup instructions (README.md:33-46) point to `uv run dumprx --setup` / the auto-run note. Rollback is a git revert restoring `setup.sh` and the argparse cli.py.
- State file must not block rollback: deleting the state file re-enables auto-setup on the old code only if the old code is restored — rollback deletes `setup.sh` content and keeps `--setup` behavior, so no manual cleanup needed.