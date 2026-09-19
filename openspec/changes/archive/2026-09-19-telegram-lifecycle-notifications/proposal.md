## Why

Today DumprX sends exactly one Telegram message per dump: the README card after a successful publish (`cli.py:_notify`). Long extractions run silently, and pipeline/publish/commit failures are invisible to the channel. Operators get no progress feedback and no failure alert.

## What Changes

- Add a `TG_VERBOSITY` knob to `.dumprxenv` (`minimal | normal | verbose`, default `normal`) that controls which Telegram lifecycle messages are sent and how much detail they carry.
- Send lifecycle notifications from the CLI pipeline: extraction started (one line, source filename), extraction finished (one line, partition count), committed locally (one line, OUTDIR), uploading started (one line, target mode/repo), and upload finished (the existing README card, gated at `minimal`).
- Always send failure alerts — pipeline failed, property parse failed, commit failed, publish failed — regardless of verbosity level.
- Notifications remain failure-tolerant: no Telegram path aborts the dump (existing `send_tg_html` contract).

## Capabilities

### New Capabilities
- `dumprx/notify`: Telegram notification behavior for the dump lifecycle — verbosity selection via `TG_VERBOSITY`, per-milestone messages, the always-send failure-alert rule, and the failure-tolerant send contract.

### Modified Capabilities
- None. The existing `dumprx` umbrella spec's environment paragraph lists `.dumprxenv.example` keys but its requirements do not enumerate Telegram notification behavior; the new capability carries the delta.

## Impact

- `src/dumprx/notify.py` — add verbosity-gated event sending alongside `send_tg_html`.
- `src/dumprx/cli.py` — emit started/finished/committed/uploading notifications at the pipeline hooks and failure alerts in existing exception branches.
- `src/dumprx/config.py` — new `Settings.tg_verbosity` field; parse/validate `TG_VERBOSITY` from `.dumprxenv` in `build_config`.
- `.dumprxenv.example` — document `TG_VERBOSITY`.
- Tests — new `tests/test_notify.py` (gating + failure-tolerant contract); extend `tests/test_cli.py` for hook output and `tests/test_foundation.py` for settings parsing.
- Processing cost: one `curl` POST per notified event, via the existing `run()`-based send path.