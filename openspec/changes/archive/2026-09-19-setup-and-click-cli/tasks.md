## 1. Dependencies

- [x] 1.1 Add `click>=8.2,<9` and `rich-click>=1.8` to `pyproject.toml` dependencies and run `uv lock`; verify `uv sync` succeeds and `uv run python -c "import rich_click"` works
- [x] 1.2 Confirm `rich_click` imports aliased as `click` (`import rich_click as click`) and that `option_panel` is exposed; verify a one-line script decorating a group with `option_panel` parses

## 2. Setup module

- [x] 2.1 Create `src/dumprx/setup.py` with `state_path()` reading `${XDG_STATE_HOME:-~/.local/state}/dumprx/state.json`; verify a unit test checks the default and overridden XDG paths
- [x] 2.2 Add `mark_complete()` / `setup_complete()` writing/reading `{"complete": true, "os", "pm", "version", "at"}`; verify `setup_complete()` is True only after a full marker exists and False for missing/incomplete state
- [x] 2.3 Implement `detect_package_manager()` probing apt/dnf/pacman/apk/brew via `shutil.which`; verify with a monkeypatched `which` test for each manager and for unsupported (returns None)
- [x] 2.4 Port the five package lists verbatim from setup.sh (apt/dnf/pacman/apk/brew) into a manager->packages map; verify the map matches setup.sh line by line
- [x] 2.5 Add `run_visible()` stdlib-subprocess helper with inherited stdio that raises on non-zero; verify a failing `false`-style command raises and a passing one returns the code
- [x] 2.6 Implement `install_uv()` running the astral installer as `SUDO_USER` when sudo is in use; verify via monkeypatched `run_visible` capture of argv (includes sudo user swap when applicable)
- [x] 2.7 Implement `run_setup(config, explicit=False) -> int` orchestrating packages -> uv -> `ensure_runtime_clones(utilsdir)` -> `uv sync` (cwd=project_dir) -> `mark_complete()`; verify explicit failure returns 1 and auto failure returns 0 with a warning, using monkeypatched steps
- [x] 2.8 Ensure a `mark_complete()` failure (read-only state dir) logs a warning and does not abort an explicit setup; verify with a chmod/tmp_path monkeypatch test

## 3. Click CLI refactor

- [x] 3.1 Replace `build_parser()` with a click group (`import rich_click as click`) exposing `-p/-r/-m/-g/-b/-l/--public/--setup/--no-setup/-o/--output` + positional; verify `--help` runs and lists every flag (CliRunner or manual run)
- [x] 3.2 Implement mode aliases as `expose_value=False` flags with a shared `ctx.obj["mode"]` callback so `-l -g` -> gitlab; verify the parity table incl. last-wins through `cli.main()` with captured config
- [x] 3.3 Group options into named `option_panel`s ("Mode", "Setup", "Pipeline", "Output") and attach `-m` default help text showing `gitlab` (fixes stale "default: local"); verify `--help` renders panels and exit code 0
- [x] 3.4 Rewrite `main()` to wrap the click group with `standalone_mode=False`, mapping `click.exceptions.Exit` -> exit code, `UsageError`/`ClickException` -> printed error + non-zero; verify `-m bogus` returns non-zero and `--help` returns 0
- [x] 3.5 Wire setup gating in `main()`: `--setup` runs explicit setup and exits (no firmware required); else if not `--no-setup` and not `setup_complete()` auto-run setup; verify each branch with monkeypatched `run_setup`/`setup_complete`

## 4. Output directory

- [x] 4.1 Forward `-o/--output` into `build_config(outdir=...)`; verify captured `build_config` kwargs carry the Path and that a default run omits it (falls back to `/tmp/out`)
- [x] 4.2 Verify (manual, `--local`) that a custom `-o` dir receives README.md / all_files.txt and that no output lands in `/tmp/out`

## 5. Tests

- [x] 5.1 Rewrite `tests/test_cli.py` parser tests to drive `cli.main()` with monkeypatched `build_config`, preserving the flag parity table (mode/visibility/push/readme) incl. last-wins
- [x] 5.2 Add `tests/test_setup.py` covering: state gate (missing -> setup runs, complete -> skipped, `--no-setup` -> skipped), auto-failure warn-and-continue, explicit-failure exits 1, `mark_complete` warning path
- [x] 5.3 Add an output-dir test: `-o <tmp>` reaches `build_config(outdir=...)` and `--push-only -o <dir>` passes through without an outdir default
- [x] 5.4 Run `uv run ruff check src/dumprx tests` and `uv run pytest`; verify full suite green

## 6. Docs and cleanup

- [x] 6.1 Replace README setup steps (README.md:33-46) with `uv run dumprx --setup` and the auto-run note; add `--setup`, `--no-setup`, `-o/--output` to the flags list and help context
- [x] 6.2 Delete `setup.sh`; verify no remaining references in README or AGENTS.md point to `./setup.sh` as the install path
- [x] 6.3 Update AGENTS.md "Important Commands" and Repository Structure if they reference `setup.sh`
- [x] 6.4 Run `git status --short`; verify only intended files changed