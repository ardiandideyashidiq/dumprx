## Context

Today the pipeline sends exactly one Telegram message per dump: the README card fired by `_notify()` in `cli.py` after a successful publish, guarded by `config.secrets.tg_token` (cli.py:237-243, notify.py:11). `send_tg_html()` is the single transport: a `curl` POST through `process.run()`, failure-tolerant, `parse_mode=HTML`. Telegram config (`TG_TOKEN`, `TG_CHAT`) is parsed from `.dumprxenv` in `build_config` (config.py:196-205); non-secret run tuning (`DUMPRX_LOG_LEVEL`, `DUMPRX_JOBS`) lives on the `Settings` dataclass. All lifecycle milestones already pass sequentially through `cli.py` (pipeline -> commit -> publish), so every notification hook is on that thread. See proposal.md for motivation and specs for the behavior contract.

## Goals / Non-Goals

**Goals:**
- A single `TG_VERBOSITY` knob, read from `.dumprxenv`, selecting message volume (`minimal | normal | verbose`, default `normal`).
- Progress notifications at the five lifecycle milestones, failure alerts always, and zero impact on dump success/failure semantics.

**Non-Goals:**
- No per-channel/per-mode message customization, no rate limiting, no formatting beyond Telegram HTML, no changes to the README card builder (`build_tg_html`) or the existing final-card behavior other than its verbosity threshold.

## Decisions

### 1. Verbosity lives on `Settings`, sourced from `.dumprxenv`
`Settings` gains `tg_verbosity: str = "normal"`. `build_config` already loads the whole `.dumprxenv` dict via `load_env_file`; it selects the `TG_VERBOSITY` key, lowercases it, validates against `{minimal, normal, verbose}`, and falls back to `normal` on any mismatch or absence. No `.dumprxenv` parser changes are needed.
- Rationale: verbosity is behavior tuning, not a credential — `Secrets` redacts and serializes tokens and should not carry it. This mirrors where `log_level` lives.
- Alternative considered: OS env `DUMPRX_TG_VERBOSITY` in the style of `DUMPRX_LOG_LEVEL`. Rejected: all Telegram configuration already lives in `.dumprxenv`, and that file is what a notification operator edits.

### 2. Threshold-gated send API in `notify.py`
Add one public function while keeping `send_tg_html` as the transport:
- `send_tg_event(config, text, *, min_level="normal") -> bool` — resolves `config.settings.tg_verbosity`, returns `False` without sending when the token is missing or the selected verbosity is below `min_level` (ordering `minimal < normal < verbose`), otherwise posts via `send_tg_html`.
- `send_tg_alert(config, text) -> bool` — always posts via `send_tg_html`; the never-gated path for failures.
- Both go through the token guard inside `send_tg_html`, so an unset `TG_TOKEN` stays a silent no-op (spec: Notifications never abort the dump).
- Alternative considered: gating logic inline at each call site. Rejected: five milestone sites plus four failure sites would repeat the same threshold check and token guard.

### 3. Milestone hooks and thresholds
- extraction started — `cli.py`, before `run_pipeline`, level `normal`, text carries the resolved source file/folder name (the only identity available pre-derive).
- extraction finished — `cli.py`, after `run_pipeline`, level `normal`, text carries `len(result.partitions)`; at `verbose` also carries elapsed time via `time.monotonic()` from just before the started message.
- committed — `cli.py`, after `commit_local` returns, level `normal`, text carries OUTDIR; at `verbose` also the branch.
- uploading — emitted by the publisher (`gitlab.py` / `github.py`) immediately before `push_all`, level `normal`, text carries mode and the exact org/repo path (both publishers already receive `config`).
- upload finished — existing `_notify` call becomes `send_tg_event(..., min_level="minimal")`, so `minimal` users still get the final card (spec: Minimal verbosity sends the final card only).
- Why publishers emit "uploading": the repo path is derived inside each publisher (nested subgroup for GitLab, `{codename}_dump` for GitHub); re-deriving it in `cli.py` would duplicate `_repo_name`/subgroup logic and drift. Publisher test fixtures already build token-less configs, so the token guard keeps those tests off-network.

### 4. Failure alerts in existing exception branches
`cli.py` already catches, logs, and `return 1` at four points: pipeline failure, `PropError`, commit failure, and publish failure (cli.py:152-202). Each branch gains one `send_tg_alert` call carrying a short stage label and the escaped exception string; the publish-failure alert also names OUTDIR (it is preserved for re-push). A tiny cli-local helper wraps `send_tg_alert` + escaping so the four sites stay one-liners.

### 5. HTML escaping of interpolated values
One-liners interpolate file names, paths, branches, and error strings into `parse_mode=HTML` text. Every interpolated value is passed through `html.escape(...)` before posting. The card builder's existing unescaped `<code>` values are left untouched (pre-existing behavior, out of scope).

## Risks / Trade-offs

- [Extra `curl` per event; Telegram can burst-reject rapid sends] -> Milestones are minutes apart in real dumps; sends are failure-tolerant by design (a dropped message never affects exit code).
- [An unescaped `&`/`<` in a message deletes that notification via a 400] -> All interpolated values are `html.escape`d; the only content not escaped is fixed literal text.
- [Publishers now depend on `notify` (new module import)] -> Import is deferred inside the publisher function body; token-less configs short-circuit before any network, so existing publisher tests stay green.
- [Default `normal` newly introduces milestone messages for current users] -> Intended behavior of this change; operators wanting today's quiet single-message behavior set `TG_VERBOSITY=minimal`.

## Migration Plan

- Additive, no data migration. `.dumprxenv.example` documents the new key.
- Rollback for an operator: set `TG_VERBOSITY=minimal` (restores the old single final card) or leave `TG_TOKEN` unset (all Telegram messages stop).
- Validation before merge: `uv run ruff check src/dumprx tests` and `uv run pytest` must pass; a manual `--local` run on a small firmware should show started/finished/committed messages (and, with `--public`/`--mode gitlab` configured, uploading and the final card).

## Open Questions

None material. Per-mode message templates and per-partition progress reporting are deliberately deferred — they would change the spec's message contract and are out of scope.