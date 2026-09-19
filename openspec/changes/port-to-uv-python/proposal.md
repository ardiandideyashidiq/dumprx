## Why

`dumper.sh` (1780 lines of linear Bash) is hard to extend: format support hangs off one giant `if/elif` chain (lines 388-900), property parsing re-runs `find | grep` per key, and every new firmware family risks breaking unrelated flows. Python gives testability, no subprocess-per-prop, a single managed dependency set under `uv`, and a plugin seam so adding a firmware format no longer means editing a 1800-line script.

## What Changes

- **BREAKING** Replace the Bash entry point with a Python package `dumprx`; invocation becomes `uv run dumprx`. CLI flags kept identical (`--mode`, `--push-only`, `--readme-only`, `--public`, `-g/-b/-l/-m/-p/-r/-h`).
- Port full pipeline: input resolve/download, format detection + extraction, partition normalization, filesystem extraction, property parsing + README, TWRP tree, GitLab/GitHub push, Telegram notify.
- Introduce extractor plugin registry (one module per firmware format; container vs terminal extractors).
- Introduce publisher plugin registry (gitlab/github backends + telegram notification hook).
- Replace bash self-reinvocation (`reload_and_rerun`, `bash "$0"`) with a single-process stage queue.
- Add loguru debug logging at every stage and subprocess call; `DUMPRX_LOG_LEVEL` override; rotating log file in work dir.
- Add memory-leak and performance guarantees: single subprocess runner with timeout, bounded concurrency (`nproc`), streaming IO, prop-cache (parse each build.prop once), header-strip short-circuit, one `7zz x` full extract instead of per-partition pulls.
- Add pytest suite for pure logic: prop cascade, README render, detector classification, header-strip math, super-chunk identification, stage-queue ordering.
- Add ruff linting; wire `loguru`, `rich`, `uv` (`[project.scripts] dumprx`) into `pyproject.toml`.
- Keep `utils/` binaries and helper scripts as subprocess targets; keep `setup.sh` as the system-package installer (`brotli`, `lz4`, `apktool`, `jq`, `curl`, `git-lfs`, etc.).

## Capabilities

### New Capabilities

- `dumprx`: full firmware dump pipeline — CLI, input resolution, extraction orchestration, partition normalization, property parsing, README/all_files.txt generation, TWRP generation, git push, telegram notify. Behavior parity with `dumper.sh`.
- `dumprx/extractor`: firmware-format plugin registry. `Container` extractors decode wrappers (ozip/ops/ofp/tgz/kdz/ruu/archives) and emit the next source; `Terminal` extractors produce partition images. Ordered detection, first match wins, matching the current `elif` chain order.
- `dumprx/publisher`: delivery plugin registry. `gitlab` and `github` backends share staged-commit/LFS/retry logic; `telegram` is a post-push hook invoked by the active publisher.

### Modified Capabilities

None — `openspec/specs/` is currently empty (only `.gitkeep`).

## Impact

- **Removed**: `dumper.sh` (replaced by package entry point on completion of the port; file deleted only when parity verified).
- **New**: `pyproject.toml`, `uv.lock`, `src/dumprx/` (14 modules), `tests/`.
- **Kept**: `utils/` tree (vendor binaries + helper scripts, runtime clones), `setup.sh` (trimmed to system deps only), `.dumprxenv` contract, output layout `/tmp/out`, `all_files.txt` contract, branch naming.
- **Dependencies**: Python stdlib, `loguru`, `rich`, `ruff` (dev), `pytest` (dev), `uv` runtime. External binaries invoked via subprocess unchanged: `7zz`, `simg2img`, `lpunpack`, `fsck.erofs`, `payload-dumper-go`, `dtc`, `unsin`, `avbtool.py`, `sdat2img.py`, `unpackboot.sh`, oppo/KDZ/RUU/PAC helpers, `twrpdtgen`, `apktool`.