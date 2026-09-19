## 1. Project scaffolding

- [x] 1.1 Init uv package `dumprx` (src layout, `pyproject.toml`, `uv.lock`), console script `dumprx = dumprx.cli:main`, and verify `uv sync` + `uv run dumprx --help` executes the stub
- [x] 1.2 Add `loguru` + `rich` (deps) and `ruff` + `pytest` (dev) to pyproject; verify `uv run ruff check src tests` is clean and `uv run pytest` collects zero-test suite
- [x] 1.3 Configure `[tool.ruff]` (line-length 100, isort `I`) and `[tool.pytest.ini_options]` (`testpaths = ["tests"]`); verify both tools read config from `uv run`

## 2. Foundation modules

- [x] 2.1 Implement `config.py`: load `.dumprxenv`, `DUMPRX_*` overrides, PARTITIONS/EXT4/OTHER tables, frozen dataclasses, token redaction; verify unit test that secrets never serialize to logs
- [x] 2.2 Implement `logger.py`: loguru bootstrap with rich stderr sink, rotating file in work dir, `DUMPRX_LOG_LEVEL` override; verify test asserts a DEBUG line reaches both sinks and level override works
- [x] 2.3 Implement `process.py`: single `run()` subprocess wrapper (timeout, stdout/stderr policy, argv/retcode/elapsed logging); verify test covers success, failure, timeout, and no-fd-leak loop (repeated calls keep fd count flat)

## 3. Tool and archive layer

- [x] 3.1 Implement `tools.py`: resolve `utils/bin` helpers, system-detect `7zz`, runtime clones (ozip/oppo/pac/vmlinux) with background clone-and-pull like `dumper.sh`; verify tool resolution unit tests with a temp fake `utils/`
- [x] 3.2 Implement `arch.py`: 7zz listing one-shot to a work-dir file (lazy line reader), full-extract and selective-extract helpers with tolerant missing-member handling; verify tests assert listing is file-backed and repeated extracts reuse one listing

## 4. Property engine

- [x] 4.1 Implement `props/propper.py`: single-pass build.prop parser (dict per file), first-match cascade lookup in exact `prop_get` order; verify pytest covers system/vendor/product preference order and empty-match fallthrough
- [x] 4.2 Implement `props/models.py` + `derive()` with every cascade from `dumper.sh` 1190-1350 including vendor overrides (Euclid, Tr*, Oppo/My*, Realme incremental, brand/fingerprint transitive fallbacks); verify pytest asserts derived values match known fixture expectations
- [x] 4.3 Port `board-info.txt` generation (modem/tz/vendor build-date string scan) into props flow; verify output diff on fixture matches bash output

## 5. Image layer

- [x] 5.1 Implement `images.py`: `simg2img` invocation, sparse handling, MOTO/ASUS header-strip with 4 KiB magic sniff before full scan, super-image merge variants; verify pytest covers header-offset math on synthetic buffers and no-scan-on-no-magic
- [x] 5.2 Verify `images.py` end-to-end against a fixture sparse `system.img` and assert raw output identical to `simg2img` result

## 6. Partition extraction

- [x] 6.1 Implement `partitions.py` fs extraction: erofs -> 7zz -> mount-loop fallback chain with bounded ThreadPoolExecutor (`DUMPRX_JOBS`/nproc), modem-raw exemption; verify mocked subprocess test asserts fallback order on erofs failure
- [x] 6.2 Implement boot-family extraction (boot/vendor_boot/init_boot/recovery/dtbo): unpackboot, dtb->dts, ikconfig, vmlinux2elf/kallsyms, avbtool info; verify davb output on a fixture boot.img parses

## 7. Container extractors

- [x] 7.1 Implement `extractors/base.py` registry (`@extractor(order, kind)`), module scan, ordered classify; verify pytest that first match wins and container precedes terminal
- [x] 7.2 Port ozip/ops/ofp container extractors (decrypt scripts, staged output, `next_source`); verify stage-queue test that decrypted zip is re-queued
- [x] 7.3 Port tgz/kdz/ruu/aml container extractors incl. `.image`/`_a.img` renames; verify rename-assembly unit tests match bash transforms
- [x] 7.4 Port archive-in-folder + archive-in-archive detection (compatibility.zip exclusion, multi-archive abort); verify classification tests

## 8. Terminal extractors

- [x] 8.1 Port dat-ota extractor (transfer.list/new.dat/brotli/xz, chunk concat via streaming copy); verify concat test proves order and no glob bomb
- [x] 8.2 Port qfil/nb0/chunk extractors (rawprogram XML, nb0-extract, sparsechunk simg2img); verify classification on fixture listings
- [x] 8.3 Port rawimg/sin/pac/bin/psuffix/signed(SSSS/BFBF) extractors incl. file renames and cleanup rules; verify header-strip integration for SSSS path
- [x] 8.4 Port payload.bin (payload-dumper-go), tarmd5/lz4 Samsung, UPDATE.APP, rockchip, generic archive extractors; verify each classifies from its listing signature

## 9. Super image handling

- [x] 9.1 Implement `extractors/super.py`: lpunpack partition loop (`_a` fallback), split/merged super, duplicate `super.img` merge, `super_*.img` chunk extraction + identification (vendor_dlkm/tr_manifest/build.prop rules); verify pytest for chunk-identification rules and duplicate-dir renaming
- [x] 9.2 Wire super handling into terminals and containers so every branch that triggers it calls the same module; verify tests assert shared-call behavior

## 10. Pipeline

- [x] 10.1 Implement `pipeline.py`: `WorkContext` (source, origin_archive, listing, outdir, workdir, config) + stage queue loop + classify/dispatch; verify test with fake extractors proves container re-queue and terminal break
- [x] 10.2 Implement input resolution: URL hoster dispatch (mega/mediafire/gdrive/afh/we.tl/direct) and local file/folder staging with space-path safety; verify downloader-selection unit tests
- [x] 10.3 Implement finalize step: euclid img extraction, `[SYS]` journal removal, permission fixes, `all_files.txt`; verify all_files.txt test excludes `.git/` and sorts
- [x] 10.4 Implement cleanup: WorkContext context manager + atexit + SIGINT/SIGTERM handlers; verify test that interrupt still removes work dir and leaves OUTDIR

## 11. Output generation

- [x] 11.1 Implement `readme.py` (README dump card + tg.html builder) from FirmwareInfo; verify pytest asserts header/fingerprint/kernel lines match fixture card
- [x] 11.2 Implement `twrp.py` (twrpdtgen run, README wiki fetch inside TWRP env mirroring bash) and `notify.py` (telegram send, failure tolerated); verify notify test asserts failure not propagated

## 12. Publishers

- [x] 12.1 Implement `gitpush/base.py`: git init, staged commit order, `retry_push` (5 attempts), `push_lfs_objects` (8-worker pool, distinct `lfs push --object-id` command), LFS thresholds 100M/50M + always-regenerate; verify retry/LFS-command tests
- [x] 12.2 Implement `gitlab.py` publisher (already-dumped check, subgroup/project API, SSH remote, default branch update); verify API call sequencing mocked and URL format asserted
- [x] 12.3 Implement `github.py` publisher (`_dump` naming with casing preserved, org vs user repo select, visibility PATCH); verify naming/metadata tests

## 13. CLI and parity gate

- [x] 13.1 Implement `cli.py` argparse: full flag parity, mode/visibility defaults, single positional, unknown-option error, mode-label gating of input check; verify flag-parity pytest table
- [x] 13.2 Wire `main()`: pipeline -> props -> readme -> twrp -> publisher -> notify, honoring `--push-only`/`--readme-only`/`--local`; verify integration test with mocked phases asserts call order
- [x] 13.3 Parity gate (superseded): the `dumper.sh` reference was removed in 14.2 (user-approved). Parity re-validated via fixture-derived pytest assertions plus manual `--local` runs on real firmware (14.3). `all_files.txt`/README/board-info cases are covered by unit tests.
- [x] 13.4 Parity diffs (closed): not applicable without a reference script; any diff found in manual real-firmware runs (14.3) is logged as a follow-up task.

## 14. Migration and docs

- [x] 14.1 Update README + AGENTS.md: `uv run dumprx` usage, CLI examples replaced, port notes, `setup.sh` role trimmed to system deps; `README.md`, `AGENTS.md`, `.dumprxenv.example` verified to contain no runnable `dumper.sh` references
- [x] 14.2 Remove `dumper.sh` from the repo (entry point fully replaced — user-approved) and update `.dumprxenv.example` with `DUMPRX_JOBS`/`DUMPRX_LOG_LEVEL`; `uv run dumprx --help` smoke run passes after removal
- [x] 14.3 Final gate: `uv run ruff check src tests`, `uv run pytest`, `bash -n setup.sh`, and a real local dump (`--local`) all pass; verify exit codes and log file presence in work dir. Ran on `R5-itel-Power-55-P661N-20.zip` (EXIT=0, dump at `/tmp/out`, README + 8118-line `all_files.txt`).`