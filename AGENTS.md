# AGENTS.md — DumprX Agent Context

## Project Overview

DumprX is an Android firmware dumper. It accepts a firmware file, an extracted
firmware folder, or a supported download URL, extracts Android partitions,
parses device/build properties, generates a README dump card, and can push the
extracted tree to GitLab or GitHub.

The project is a Python package managed with uv (Python 3.13+, loguru for
logging, rich for console). It was ported from a single Bash script whose
`--help` behavior is preserved by the `dumprx` console script. Helper
binaries/scripts still live under `utils/`.

## Agent Operating Rules

- Read relevant parts of a module before editing it; do not assume line numbers are stable.
- Prefer minimal, targeted edits. The extractor/cascade logic handles many firmware formats; avoid broad refactors unless asked.
- Keep compatibility with the existing style: dataclasses, loguru `logger`, `run()` from `dumprx.process` for subprocesses, `Path` objects everywhere.
- Do not commit or print secrets from `.dumprxenv`. `Secrets.__repr__` redacts everything.
- Do not add new runtime dependencies without updating `pyproject.toml` and documenting why. `uv lock` after dependency changes.
- Validate changes with at least `uv run ruff check src/dumprx src/twrpdtgen src/aospdtgen tests` and `uv run pytest`. There is no formal firmware test suite; firmware validation is usually manual (`--local` on a real file).

## Important Commands

```bash
uv sync                                    # install deps
uv run dumprx --setup                      # install system deps + tools, record setup state
uv run dumprx --help                       # CLI help
uv run dumprx --local <firmware-file-or-url>   # run locally without GitLab push
uv run dumprx --readme-only                # regenerate README.md only
uv run dumprx -o <dir> --local <firmware-file-or-url>  # dump into <dir> instead of /tmp/out
uv run dumprx --gitlab <firmware-file-or-url>
uv run dumprx --gitlab --public <firmware-file-or-url>
uv run pytest                              # full test suite
uv run ruff check src/dumprx src/twrpdtgen src/aospdtgen tests   # lint
```

Mode defaults to `gitlab` and visibility to `private` (mirrors the legacy
Bash dumper defaults). First run without `--setup` auto-runs setup when the
XDG state file (`~/.local/state/dumprx/state.json`) is missing/incomplete;
`--no-setup` bypasses that check. Verify actual code in `cli.py` before
changing behavior.

## Repository Structure

```text
DumprX/
├── pyproject.toml          # package + deps; [project.scripts] dumprx = dumprx.cli:main
├── .dumprxenv.example      # template for GitLab/GitHub/Telegram settings
├── .dumprxenv              # local secrets file; gitignored; never commit
├── README.md
├── LICENSE
├── src/
 │   ├── dumprx/
 │   │   ├── cli.py          # click/rich-click entry point; wires setup gate -> pipeline -> props -> readme -> twrp+aospdtgen -> publisher -> notify
 │   │   ├── pipeline.py     # stage queue (containers re-queue, terminals break), partition promote, finalize
 │   │   ├── config.py       # Paths/Settings/Secrets frozen dataclasses; .dumprxenv parsing
 │   │   ├── setup.py        # first-run setup: system packages, uv, runtime clones, XDG state gate
 │   │   ├── logger.py       # loguru bootstrap (console + rotating file)
 │   │   ├── process.py      # run() subprocess wrapper with capture/timeout
 │   │   ├── tools.py        # Tool registry / resolution for utils/bin helpers
 │   │   ├── arch.py         # 7zz listing + extraction helpers
 │   │   ├── downloader.py   # URL hoster dispatch (mega/mediafire/gdrive/afh/we.tl/direct)
 │   │   ├── resolution.py   # input folder/file normalization
 │   │   ├── images.py       # sparse/raw conversion, signed header stripping
 │   │   ├── partitions.py   # super chunks, euclid, FS filesystem extraction
 │   │   ├── boot.py         # boot/recovery/vendor_boot/dtbo, kernel metadata
 │   │   ├── readme.py       # README dump card + Telegram HTML builder
 │   │   ├── notify.py       # Telegram send (failure tolerated)
 │   │   ├── twrp.py         # vendored twrpdtgen DeviceTree (adaptive image set) + wiki README fetch
 │   │   ├── aospdtgen.py    # vendored aospdtgen DeviceTree wrapper -> aosp-device-tree/device/<manu>/<codename>/
 │   │   ├── extractors/     # registry (base.py) + containers.py + terminals.py + super.py
 │   │   ├── props/          # propper (PropStore/grep), models (FirmwareInfo.derive), board_info
 │   │   └── publishers/     # base (retry_push/LFS/commit_and_push), gitlab, github, registry
 │   └── twrpdtgen/          # vendored twrpdtgen fork; DeviceTree lib, image_info (AOSP mkbootimg unpack), templates
 │   └── aospdtgen/          # vendored aospdtgen fork; DeviceTree lib, templates, proprietary_files sections
 └── utils/
     ├── bin/                # Prebuilt tools: 7zz, simg2img, magiskboot; AOSP mkbootimg.py/unpack_bootimg.py + gki/
     ├── downloaders/        # URL download helpers
     ├── kdztools/           # LG KDZ/DZ extraction helpers
     ├── keyfiles/           # Decryption keys for OFP/OPS flows
     └── ...                 # sdat2img.py, avbtool.py, unpackboot.sh, dtc, unsin, lpunpack, nb0-extract, ...
 ```

 ## Vendored code

 Vendored components are committed intentionally and must not be treated as
 runtime clones:

 - `src/twrpdtgen/` — vendored from `ardiandideyashidiq/twrpdtgen` master
   (commit `bd0badbe8e3e6eff96837f4da2a7d22a37de5094`). The fork ships its own
   scripts here that replace AIK: `image_info.py` runs `utils/bin/unpack_bootimg.py`
   (`--format=mkbootimg`) and decompresses the ramdisk with gzip/lzma/lz4/zstd +
   `cpio`. Adaptive selection order is `recovery.img` > `vendor_boot.img` >
   `init_boot.img` > `boot.img`. To update: re-apply the dumprx-side changes
   (no git flow, loguru logging, `image_info.py` unpacker, `labels`-free
   `DeviceTree`) on top of a newer fork checkout and bump the commit above in
   both `src/twrpdtgen/__init__.py` and this section.
 - `src/aospdtgen/` — vendored from `sebaubuntu-python/aospdtgen` v1.2.1
   (commit `ff16bea7aabf8133affd9772e12651640712ae9a`). The fork replaces AIK
   image unpacking with the twrpdtgen fork's `image_info.unpack_images()`
   (vendored AOSP `unpack_bootimg.py`, GKI-capable, no runtime AIK clone) and
   deletes the stand-alone `get_vndk_libs.py` regeneration script (zero
   importers; the hardcoded lists it regenerates stay in `ignore.py`).
   `DeviceTree`/`BootConfiguration` accept `workdir` + `unpack_bootimg_tool`
   kwargs injected by the wrapper. To update: re-apply the dumprx-side changes
   (image_info-backed `boot_configuration.py`, `get_vndk_libs.py` removal,
   `workdir`/`unpack_bootimg_tool` kwargs) on top of a newer upstream checkout
   and bump the commit above in both `src/aospdtgen/__init__.py` and this
   section.
 - `utils/bin/mkbootimg.py` + `utils/bin/unpack_bootimg.py` + `utils/bin/gki/` —
vendored AOSP `platform/system/tools/mkbootimg` scripts (Apache-2.0).
    `unpack_bootimg` is a runtime tool (`tools.py` entry `unpack_bootimg`);
    `mkbootimg` is kept for building boot-image fixtures.

## Runtime Tooling

`dumprx` may clone external tools into `utils/` on first run. These directories
are generated/runtime dependencies and should generally stay out of commits
unless intentionally vendored. Known runtime clones include:

- `bkerler/oppo_ozip_decrypt` — OZIP decryption
- `bkerler/oppo_decrypt` — OFP/OPS decryption
- `marin-m/vmlinux-to-elf` — kernel ELF/kallsyms extraction
- `ShivamKumarJha/android_tools` — miscellaneous Android tooling
- `HemanthJabalpuri/pacextractor` — Spreadtrum PAC extraction

## `dumprx` CLI

```bash
uv run dumprx [OPTIONS] <Firmware File/Extracted Folder -OR- Supported Website Link>

Options:
  -p, --push-only             Push only; skip extraction
  -r, --readme-only           Generate README.md only; skip extraction
  -m, --mode <local|gitlab|github>   Choose output mode (default: gitlab)
  -g, --gitlab                Shortcut for --mode gitlab
  -b, --github                Shortcut for --mode github
  -l, --local                 Shortcut for --mode local
      --public                Create repo as public; default is private
      --setup                 Run setup and exit (first-run auto-runs it)
      --no-setup              Skip the auto-run setup check
  -o, --output <dir>          Dump output directory (default: /tmp/out)
  -f, --force                 Re-dump even if already dumped on this machine
  -h, --help                  Show help
```

In GitHub mode, push helpers (`retry_push`, `push_lfs_objects`,
`commit_and_push`) are shared with GitLab mode. GitHub has no nested namespaces,
so each dump maps to a single repo named after the codename with a `_dump`
suffix and the original casing preserved (e.g. `Infinix-X6878_dump`) under
`GITHUB_ORG` (or your personal account).

## Key Modules and Concepts

| Module | Purpose |
|---|---|
| `config.Paths` | `project_dir`, `inputdir`, `utilsdir`, `outdir` (default `/tmp/out`), `workdir` (`outdir/tmp`) |
| `config.Settings.mode` | `local`, `gitlab`, or `github` output behavior |
| `config.Secrets` | Credentials from `.dumprxenv`; repr/str redacted |
| `redundancy` | Input sha256 ledger (XDG `~/.local/state/dumprx/dumps.json`); a ledger hit bails before extraction, `-f` overrides, entries recorded only after a dump fully succeeds |
| `WorkContext` | source path, outdir/workdir, config, archive listing passed to extractors |
| `extractors/base.py` | ordered registry; `classify(ctx)` first-match; containers return next source, terminals None |
| `props/models.derive()` | full property cascade against an extracted tree -> `FirmwareInfo` |

## Extractor Architecture

- Containers decode a wrapper (OZIP/OPS/OFP/KDZ/RUU/AML/archive) and return the
  next source for the stage queue.
- Terminals produce partition images in the work dir (DAT, QFIL, NB0, chunks,
  SIN, PAC, payload.bin, UPDATE.APP, super, etc.).
- `pipeline.extract_chain` runs the queue with a 40-hop guard; the first
  terminal to consume the input breaks the chain.
- Register extractors with the `@extractor(order, kind)` decorator.
  `load_extractors()` auto-imports every module in the `extractors` package
  (only `base` is skipped); `ordered()` sorts all containers ahead of
  terminals regardless of `order`.

## Pipeline Notes

- `pipeline.run_pipeline`: `extract_chain` -> `promote_partitions` ->
  `clear_workdir` -> `finalize` (boot family, super chunks, euclid imgs,
  filesystem trees, `[SYS]` journal removal, permissions, `all_files.txt`).
- `[SYS]` journal removal matches literal directories named `[SYS]` at
  mindepth >= 2 (mind the glob-char-class trap with `Path.rglob("[SYS]")`).
- LFS object uploads (`publishers/base.py`) run `--object-id` per oid across 8
  workers; never route them through `retry_push`.

## Property Extraction Pattern

`PropStore` is the central reader for Android `build*.prop` files across
multiple possible partition paths. `derive()` runs the full bash cascade:
flavor/release/id/tags/platform/manufacturer/fingerprint/brand/codename/
description/incremental/abilist/locale/density/is_ab/treble/otaver then
vendor-specific overrides (Transsion/Euclid/Oppo/Xiaomi/Moto), chipsets,
kernel version, repo, branch.

When adding properties:

- Prefer adding to existing fallback chains in `props/models.py` instead of
  creating a separate one-off parser.
- Preserve vendor-specific overrides already present.
- Quote/gather values defensively: firmware paths can contain spaces.

## GitLab Push Pipeline Notes

GitLab mode requires `GITLAB_TOKEN` and usually `GITLAB_GROUP` in `.dumprxenv`.

Pipeline responsibilities:

1. Check whether firmware is already dumped through remote `all_files.txt`.
2. Create/find manufacturer subgroup (API via `http_request`).
3. Create/find project repo.
4. Initialize git repo in `OUTDIR`.
5. Commit in stages: README, LFS setup, APKs, partition groups, extras.
6. Push via SSH to avoid HTTPS issues with large repos.
7. Update default branch.
8. Optionally send Telegram notification.

### Retry/LFS Gotcha

`retry_push` wraps `git push "$@"`. Do **not** use `retry_push` for LFS object
uploads inside `push_lfs_objects()` — those must call `git lfs push --object-id
origin <oid>`.

### LFS thresholds

`commit_and_push()` tracks large files with `git lfs track` before adding
partitions:

- GitLab mode: files larger than `100 MB`.
- GitHub mode: files larger than `50 MB` and patterns are always (re)generated
  so a reused `OUTDIR` still picks up files between 50 MB and 100 MB.

## Testing Conventions

- `tests/` mirror `src/dumprx` one file at a time (`test_pipeline.py`,
  `test_publishers.py`, ...).
- Subprocess-heavy code is tested with monkeypatched `run()`/`git()`/`http_request`
  fakes; `Result` is a plain dataclass with `.ok`, `.stdout_text`.
- `Path.write_bytes`/`write_text` return int in Python 3.13 — never use them in
  `or`-chains that must return truthy booleans.
- Suite is green when `uv run ruff check src/dumprx src/twrpdtgen src/aospdtgen tests` and
  `uv run pytest` both pass.

## Secrets and Generated Files

Never commit:

- `.dumprxenv`
- `input/`, `tmp/`, local output folders
- Runtime-cloned tool directories unless intentionally vendored
- Python caches or generated extraction output

`.dumprxenv.example` is safe to edit when adding new supported environment variables.

## Common Change Checklist

Before finishing a code change:

- [ ] `git status --short` checked for unrelated changes
- [ ] Relevant module(s) read before editing
- [ ] `uv run ruff check src/dumprx src/twrpdtgen src/aospdtgen tests` passes
- [ ] `uv run pytest` passes
- [ ] Help text updated if CLI flags changed (`cli.py` usage + README)
- [ ] `src/dumprx/setup.py` updated if system dependencies changed
- [ ] `pyproject.toml` + `uv.lock` updated if Python deps changed
- [ ] `.dumprxenv.example` updated if env vars changed
- [ ] README/AGENTS updated if behavior or workflow changed