## 1. Configuration

- [x] 1.1 Add `tg_verbosity: str = "normal"` to the `Settings` dataclass in `src/dumprx/config.py` and verify `uv run ruff check src/dumprx tests` passes
- [x] 1.2 In `build_config`, read `TG_VERBOSITY` from the `.dumprxenv` dict, normalize to lowercase, validate against `{minimal, normal, verbose}` with fallback to `"normal"`, and pass it into `Settings`; verify with a `build_config(project_dir=tmp_path)` test covering unset, valid `verbose`, and invalid values
- [x] 1.3 Document `TG_VERBOSITY` in `.dumprxenv.example` under the Telegram section (comment describing `minimal|normal|verbose`, default `normal`)

## 2. Notification API in notify.py

- [x] 2.1 Add `send_tg_event(config, text, *, min_level="normal") -> bool` that resolves `Settings.tg_verbosity`, short-circuits (returns False) when the token is missing or the selected verbosity is below `min_level` (ordering `minimal < normal < verbose`), else posts via the existing `send_tg_html`; verify `uv run ruff check src/dumprx tests` passes
- [x] 2.2 Add `send_tg_alert(config, text) -> bool` that posts via `send_tg_html` without any verbosity gating
- [x] 2.3 Escape every interpolated value interpolated into a message with `html.escape` before posting and verify a message containing `&`/`<` still builds a valid HTML payload
- [x] 2.4 Export the new functions in `__all__` and create `tests/test_notify.py` covering: gated send skipped at `minimal`, sent at `normal`/`verbose` (monkeypatched `send_tg_html`/`run`), alert sent at `minimal`, token-less short-circuit returns False

## 3. CLI lifecycle hooks

- [x] 3.1 Emit "extraction started" (level `normal`) before `run_pipeline` in `cli.py`, carrying the resolved source file/folder name; verify it appears on a token-configured run and is skipped otherwise
- [x] 3.2 Capture the `PipelineResult` from `run_pipeline` and emit "extraction finished" (level `normal`) carrying the promoted partition count, plus elapsed time at `verbose`; verify the message text in a monkeypatched test
- [x] 3.3 Emit "committed" (level `normal`) after `commit_local` succeeds, carrying OUTDIR and (at `verbose`) the branch
- [x] 3.4 Reroute the existing final notify call to `send_tg_event(..., min_level="minimal")` so `minimal` still receives the README card; verify via `tests/test_cli.py` that card sending survives the reroute
- [x] 3.5 Add `send_tg_alert` failure notifications to the four existing failure branches (pipeline exception tuple, `PropError`, commit failure, publish failure), with the publish-failure alert naming OUTDIR; verify each return-1 path still returns 1 and the alert is attempted

## 4. Publisher uploading event

- [x] 4.1 Emit "uploading" (level `normal`) from `gitlab.py` immediately before `push_all`, carrying mode and the exact `org/repo` path
- [x] 4.2 Emit "uploading" (level `normal`) from `github.py` immediately before `push_all`, carrying mode and the `org/{codename}_dump` path
- [x] 4.3 Verify existing publisher tests stay green (token-less configs short-circuit before network) and add a test asserting the uploading notification is requested before `push_all` in each publisher

## 5. Final verification

- [x] 5.1 Run `uv run ruff check src/dumprx tests` and confirm zero findings
- [x] 5.2 Run `uv run pytest` and confirm the full suite is green
- [x] 5.3 Run `uv run dumprx --help` and `git status --short` to confirm no unrelated changes and no help-text regression