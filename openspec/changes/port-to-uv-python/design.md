## Context

Current `dumper.sh` is 1780 sequential Bash lines with a dominant `if/elif` dispatch, breadcrumb `find | grep` prop parsing, and process self-reinvocation for nested artifacts. See proposal.md - Why for motivation. Ground observations that shape this design (line refs are in the checked-in dumper.sh at proposal time):

- Containers (ozip/ops/ofp/tgz/kdz/ruu/aml) are sequential `if` blocks that re-invoke the script; the terminal `elif` chain only runs after all container checks pass.
- `ARCHIVE_LISTING` (7zz listing) is cached once and reused by terminal branches to pull missing partitions from the origin archive.
- Prop cascade re-runs `find | grep` per key (15+ filesystem scans per firmware).
- erofs extraction already parallelizes with `nproc` cap; LFS uploads use `xargs -P 8`.

## Goals / Non-Goals

**Goals:**
- Behavior parity with `dumper.sh` everywhere the specs pin behavior (see specs/dumprx, specs/dumprx/extractor, specs/dumprx/publisher).
- Bottom-up port: leaf modules first, each pytest-green before the next.
- Plug-and-play registry for extractors and publishers.
- Bounded memory, bounded concurrency, structured debug logging.

**Non-Goals:**
- Pure-Python reimplementation of `simg2img`, `lpunpack`, `fsck.erofs`, `payload-dumper-go`, 7z, or the SparseImage semantic. These remain subprocess targets.
- Backward compatibility for the Bash entry point beyond the end of this change (see Migration Plan).
- New firmware formats in this change — only porting exists.

## Decisions

### D1. Module layout and tooling
Package: `src/dumprx`, console script `dumprx`, managed by `uv` (`pyproject.toml` + `uv.lock`). Deps: `loguru`, `rich`. Dev: `ruff`, `pytest`. Console script declared as `[project.scripts] dumprx = "dumprx.cli:main"`. `uv run dumprx` is the only entry point.

```
src/dumprx/
  cli.py            argparse parity + main() orchestration
  config.py         .dumprxenv load (redact), PARTITIONS/EXT4/OTHER tables, dirs
  logger.py         loguru bootstrap: stderr rich sink + rotating file DUMPRX_LOG_LEVEL
  process.py        single subprocess runner (timeout, drain, retcode-log)
  tools.py          resolve/clone utils/bin helpers; 7zz discovery
  arch.py           7zz listing cache (file-backed) + extract helpers
  pipeline.py       stage queue + context object + finalize (board-info, [SYS] rm, all_files.txt)
  images.py         simg2img / sparse / MOTO+ASUS header-strip / super merge
  partitions.py     fsextract (erofs->7zz->mount, bounded pool) + boot unpack helpers
  props/
    propper.py      build.prop single-pass parser -> dict; cascade lookup
    models.py       FirmwareInfo dataclass + derive() with all fallbacks
  readme.py         README.md + tg.html
  twrp.py           twrpdtgen runner + [SYS] cleanup
  notify.py         telegram send
  extractors/
    base.py         Extractor ABC, order/kind, registry (decorator)
    containers.py   ozip ops ofp tgz kdz ruu aml archive-in-folder
    terminals.py    dat qfil nb0 chunk rawimg sin pac bin psuffix signed super
                    tarmd5 payload archives update.app rockchip
    super.py        unified super.img handling: lpunpack loop, split/merge, super_*.img ident
  gitpush/
    base.py         git init, staged commits, retry_push, push_lfs, LFS thresholds
    gitlab.py       subgroup/project API, SSH remote, default branch
    github.py       repo API, _dump naming, default branch
tests/
  test_props.py test_readme.py test_super.py test_images.py
  test_pipeline.py test_process.py test_cli.py test_extractors.py
```

Alternative considered: flat `src/dumprx/*.py`. Rejected: 12+ files at top level hides the two plugin seams.

### D2. Stage queue replaces self-reinvocation
Pipeline ownership: one process, one `deque[Source]`. Each loop iteration pops a source, stages it into the work dir, classifies via extractor registry, then:

- container matched: `extract()` then push `next_source()` to the deque, continue loop.
- terminal matched: `extract()` then break to normalize/props/readme/push phases.
- none matched: abort with candidate list.

Alternatives considered: preserving recursive subprocess spawn (rejected: breaks unified cleanup + logging, complicates testing), recursive function calls (rejected: recursion depth, no backtracking, shared mutable state).

### D3. Context object carries origin
A single `WorkContext` (dataclass) is passed to every extractor, never a bare path. It holds: `source` (current artifact), `origin_archive` (outer archive reference), `archive_listing` (cached, file-backed lazy reader), `outdir`, `workdir`, `config`. This preserves the `ARCHIVE_LISTING`-based late-pull loops (otherpartition loop, `.img` pull loop) without losing the origin after container nesting.

### D4. Extractor registry
`Extractor` ABC (`order: int`, `kind: "container"|"terminal"`, `detect(ctx) -> bool`, terminal `extract(ctx)`, container `next_source(ctx) -> Path|None`). Registry builds at import from module scan; load order == `order`. Classification = first `detect` true, parallel to the current `elif` order. Single decorator `@extractor(order, kind)`. New format = new module, zero pipeline edits. (Spec: specs/dumprx/extractor/spec.md.)

### D5. Publisher registry
`Publisher` ABC with `push(info, outdir)` and shared base `StagedGit` implementing README -> LFS -> apk -> partition-group -> extras commit order, `retry_push` (5 attempts, delay), `push_lfs_objects` (8-worker bounded pool, distinct `lfs push --object-id` command), LFS thresholds (100M gitlab / 50M github + always-regenerate). `notify.py` invoked by `push()` on success. Mode string selects backend. (Spec: specs/dumprx/publisher/spec.md.)

### D6. Memory-safety guarantees
- `process.py:run()` is the only subprocess path: always `subprocess.run` with explicit stdout/stderr handling (DEVNULL or `communicate`) and timeout. No Popen-without-wait anywhere; eliminates fd-exhaustion masquerading as leaks.
- Listing: `arch.py` writes raw 7zz listing to work-dir file, consumed lazily per line — no unbounded in-memory accumulation.
- Copies: `shutil.copyfileobj` with 1 MiB buffer; whole images never loaded into RAM.
- Cleanup: work dir created/owned by `WorkContext` context manager; `atexit` + SIGINT/SIGTERM handlers remove it. OUTDIR survives deliberately.
- `config.py` returns frozen dataclasses; no module-level mutable globals.

### D7. Performance decisions
- Prop cache: parse each `build*.prop` once into `dict[str, str]`; cascade is dict lookups in the same first-match order. Replaces 15+ `find|xargs grep` subprocess chains per firmware. Kernel/boot prop exceptions decompressed via subprocess on demand, same as now.
- One `7zz x` full extract per branch that previously issued per-partition `7zz e` calls; per-file pulls remain only where the branch needs selective extraction (late-pull loops), using `arch.py`.
- Header-strip: read 4 KiB prefix, sniff MOTO/ASUS magic; full-image offset scan (`\x53\xEF` search) only when magic present — skips O(image) scan on ordinary Qualcomm images.
- DAT chunk concat via single streaming copy (replaces `cat *.new.dat.{0..999}` glob bomb).
- Parallel workers: `ThreadPoolExecutor(max_workers=min(nproc, needed))` for erofs fs extract and LFS push; lpunpack scan capped same way. No unbounded `&`/`wait -n` churn.

### D8. Debug logging everywhere
- `DUMPRX_LOG_LEVEL` env, default DEBUG.
- Sinks: rich stderr console + `RotatingFileHandler` at `WORK_TMPDIR/dumprx.log` (1 MiB x 3), so dead dumps are searchable.
- `process.py` logs every invocation: `cmd=... cwd=... retcode=... elapsed_ms=...` at DEBUG.
- Pipeline logs stage transitions (source -> classified kind/name -> outcome); extractors log detect reasons and next_source emissions.
- Redaction: `config.py` masks token values in any log-writable object; `.dumprxenv` never echoed. Tokens may not appear in CLI args (they live in env only), which also keeps subprocess argv clean.

### D9. pyproject contract
`[tool.ruff]` line-length 100, default ruleset plus `I` (isort). `[tool.pytest.ini_options]` `testpaths = ["tests"]`. `[tool.uv]` `package = true`. Build: standard (src layout). Lint gate per AGENTS.md: `uv run ruff check src tests` before any finish.

## Risks / Trade-offs

- Behavior drift in fallback chains during port (set -e tolerant branches) → Verify each terminal branch against the bash branch on the same fixture firmware before advancing; keep the bash script untouched as the reference until parity check passes.
- Sudo mount fallback path (sudo passwords, non-root CI) → Same limitation as today; documented, integration-tested manually, never unit-tested.
- Registry order coupling: order isn't discoverable by reader → extractor modules name their format in `order` comments mirroring the dumper.sh chain; a `list` CLI subcommand prints registry order for audit.
- One `7zz x` may surface files bash silently skipped via `-e dummypartition` tolerance → Extract-download lists tolerantly (ignore missing member errors) using `arch.py` semantics matching `-y` behavior.
- uv requirement on fresh machines → `setup.sh` already installs uv for all supported distros; unchanged contract.
- Threaded subprocess sharing stdout of a lazy listing → listing never streamed from subprocess; it is written to file first, threads read the file.

## Migration Plan

1. Port bottom-up (tasks.md order), each module + tests land incrementally; `dumper.sh` stays untouched as the behavioral reference.
2. Parity gate: run Python pipeline end-to-end on a fixture (known payload.bin/zip) and diff outputs (partition listing, README, props, all_files.txt) against `dumper.sh` run.
3. On green parity: switch entry point — README documents `uv run dumprx`, `dumper.sh` removed.
4. Rollback: git history retains `dumper.sh`; single `git revert` restores it.

## Open Questions

- None blocking. Deferrable: whether `setup.sh` eventually shrinks to only system deps (non-python) — cosmetic, does not change specs, design, or tasks; decide during tasks.md execution.
- `DUMPRX_LOG_LEVEL` default DEBUG is a deliberate choice for dumper workflows; if wall-clock hurt appears on tiny dumps, override default to INFO — runtime option already exists, no design change requires.