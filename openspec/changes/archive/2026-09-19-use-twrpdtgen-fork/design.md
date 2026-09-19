## Context

Upstream `twrpdtgen` v3.0 (`ariandi...` fork == pristine upstream master at
scaffold time) cannot unpack GKI modern images through its AIK-based
`AIKManager.unpackimg`, so `twrp.py:12`'s `uvx --from git+@master` subprocess
yields no tree on exactly these firmwares. The dump pipeline calls
`generate_twrp(config, is_ab=...)` at `cli.py:183`; OUTDIR holds whatever
subset of `recovery.img` / `boot.img` / `vendor_boot.img` / `init_boot.img`
the firmware provided (promoted by `pipeline.promote_partitions`, unpacked by
`boot.py`). `pyproject.toml` uses `uv_build` src-layout; that backend's
`module-name` setting accepts a list, so a vendored second package is
buildable alongside `dumprx`. Motivation and capability contract: see
`proposal.md` and `specs/dumprx/twrp/spec.md`.

## Goals / Non-Goals

**Goals:**
- One repository owns the TWRP generator (vendored fork), so fixes ship with
  the dump tool and no runtime tool download is needed.
- GKI/modern firmware (picture: boot + vendor_boot + init_boot, headers
  v3/v4) produces a TWRP tree where it currently produces nothing.
- The generator accepts the image *set*, not one pre-picked image; ramdisk
  source and metadata are chosen adaptively.
- Preserve the output contract (`twrp-device-tree/<manu>/<codename>/`, wiki
  README, `.git` removal, best-effort failures) exactly.

**Non-Goals:**
- The aospdtgen generation items (proprietary-files, `.prop` scanning, symlink
  blobs, proper codename) are explicitly parked out of scope.
- Upstream merge automation; merging stays manual.
- Rewriting the fork's `Fstab`/`BuildProp`/`DeviceInfo` logic — only the
  image-unpacking path and invocation surface change.
- Generating a tree when the set carries *no* ramdisk-bearing image at all
  (spec already defines that as "skip").

## Decisions

### D1. Vendored package at `src/twrpdtgen/` (sibling, not subpackage)
The fork's internal imports are absolute (`from twrpdtgen.device_tree import
DeviceTree`, `from twrpdtgen.templates import render_template`), so it must
stay a top-level importable package at `src/twrpdtgen/`. `pyproject.toml` gets
`module-name = ["dumprx", "twrpdtgen"]` under `[tool.uv]` (uv_build's
`settings.rs` documents a list form for exactly this). The fork's own
`pyproject.toml`/`poetry.lock` are dropped; its runtime deps are folded into
`dumprx`'s `[project.dependencies]`.
*Alternatives rejected:* subpackage under `src/dumprx/` (breaks internal
imports); keep `uvx --from git+...` (runtime network, single-image interface,
user chose vendoring).

### D2. Replace AIK with a vendored AOSP `unpack_bootimg`
The fork drops `AIKManager().unpackimg` (and `libaik` imports). In its place a
new fork module runs AOSP `mkbootimg`/`unpack_bootimg` on the chosen image and
returns the same attribute surface the templates consume:
`ramdisk` (extracted + decompressed), `kernel`, `dt`, `dtb`, `dtbo`,
`header_version`, `base_address`, `cmdline`, `pagesize`, `ramdisk_offset`,
`tags_offset`, `origsize`, `ramdisk_compression`, `sigtype`. `sigtype`
(default "none") is sniffed best-effort via avbtool when available.
The image tools are *vendored scripts* (`utils/bin/unpack_bootimg.py` +
`mkbootimg.py`, Apache-2.0 from AOSP) mirroring the existing
`utils/avbtool.py` pattern — no OS package, reproducible offline, matches the
spec's offline/reproducibility requirement.
*Alternatives rejected:* `magiskboot` (already in `utils/bin`, but user asked
for mkbootimg and its header print is less canonical); distro/`pip install`
mkbootimg (availability varies, breaks offline reproducibility).

### D3. Adaptive image selection (buy-line for GKI)
`twrp.py` collects the image set present in OUTDIR and passes it to the fork
as an ordered list `images`. The fork's `DeviceTree` picks:
1. `recovery.img` — legacy fallback
2. `vendor_boot.img` — A/B + GKI: ramdisk + dtb + vendor cmdline
3. `init_boot.img` — GKI v4 generic ramdisk (used when vendor_boot's ramdisk
   lacks fstab/init.rc, or only init_boot+boot provided)
4. `boot.img` — pre-v3 boot or GKI when nothing else provides a ramdisk

Metadata (dtb, cmdline, addresses) is merged from the auxiliary images when
the primary ramdisk source lacks them. The old `is_ab` boolean at
`cli.py:183` becomes the image-set handoff; `is_ab` is still derivable inside
the fork from header/partitions if a template needs it.

### D4. `twrp.py` calls the library directly
`generate(config, outdir_image_set)` imports `twrpdtgen.device_tree.DeviceTree`,
writes into `outdir/"twrp-device-tree"`, then
`device_tree.dump_to_folder(...)` + `cleanup()` in a `try/finally`; the existing
wiki-README fetch and `.git` removal stay in `twrp.py`, and every failure is
logged (spec: best-effort). No subprocess, no `_TWRPDTGEN` constant.

### D5. Fork dependency trim
- **Drop** `GitPython` and the `--git` flow in the fork (`main.py` arg and the
  `Repo`-based block in `device_tree.py`); dumprx already owns git.
- **Replace** `sebaubuntu_libs.liblogging` (`LOGD`) with loguru `logger.debug`
  (loguru is already a dumprx dep).
- **Keep** `sebaubuntu_libs.libandroid` (`DeviceInfo`, `Fstab`, `BuildProp`)
  and **add** `sebaubuntu_libs` + `jinja2` to `[project.dependencies]`.
  `libaik` remains installed inside `sebaubuntu-libs` but is never imported —
  dead weight, not a fix.
- `uv lock` after any dependency change.

### D6. Licensing and provenance
Every vendored fork file keeps its Apache-2.0 SPDX header. The fork source
commit is recorded (AGENTS/README note) so manual upstream merges are
possible. README already credits twrpdtgen by @SebaUbuntu; extend with the
fork source note.

## Risks / Trade-offs

- [Manual fork merges drift from upstream] → Record the vendored source commit
  and a short "updating the fork" note in AGENTS.md; keep `Fstab`/`BuildProp`
  divergences zero so merges stay surgical.
- [`libaik` + other sebaubuntu_libs subpackages installed but unused] →
  Accepted dead weight for now; a later change can vendor only `libandroid`.
- [`unpack_bootimg` surface ≠ AIK surface for legacy v2 images, notably the
  late `dt` image slot] → Best-effort: absent `dt` simply suppresses
  `BOARD_KERNEL_SEPARATED_DT`/prebuilt `dt.img`; no crash.
- [vendor_boot v4 ramdisk may be split into multiple fragments] → `unpack_bootimg`
  emits them concatenated; decompression and selection need verification
  against a real GKI image during implementation (see Open Questions).
- [Tests currently mock `_render_img`] → Reworked to mock the vendored
  `DeviceTree`; asserting the tree dir exists stays the observable contract.

## Migration Plan

1. Add the vendored package + tool scripts + `pyproject` config (D1, D2, D6).
2. Rewrite `twrp.py` and `cli.py` handoff (D3, D4) in the same change so
   there is no interim "downloads twrpdtgen at runtime" state.
3. Trim fork deps (D5), update AGENTS/README, run `uv lock`.
4. Rollback: single `git revert` — the old `uvx --from git+@master` line is
   the fallback if the vendored path regresses, but the new code is the
   default.

## Open Questions

- Exact `unpack_bootimg` invocation/output for header-v4 vendor_boot on a real
  GKI dump — confirm fragment handling and ramdisk decompression against one
  real firmware when implementing; resolution stays inside the fork's unpack
  module and does not change specs, approach, or task breakdown.