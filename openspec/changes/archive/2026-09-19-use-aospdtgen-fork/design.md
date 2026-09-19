## Context

aospdtgen is a LineageOS/AOSP device-tree generator: given an extracted
firmware dump (system/vendor/product trees + boot images) it emits a
`device/`-style tree with makefiles, proprietary-files, rootdir, fstab,
manifest and build props. It shares the same fixed point that motivated the
existing TWRP fork: image unpacking runs through `sebaubuntu_libs.libaik`
(`AIKManager`), which clones `SebaUbuntu/AIK-Linux-mirror` from GitHub into a
tmpdir on every run and cannot decode GKI (header v3/v4) boot images. See
proposal.md for motivation; the twrpdtgen fork at `src/twrpdtgen/` (via AOSP
`unpack_bootimg.py` + `image_info.py`) is the working, verified replacement
pattern this design reuses.

Verified facts from investigation:

- aospdtgen v1.2.1, upstream `sebaubuntu-python/aospdtgen` (Apache-2.0).
- Its runtime deps (`sebaubuntu-libs 1.6.1`, `jinja2`) are already satisfied
  by the DumprX venv via the twrpdtgen fork. `GitPython` is used only by
  `libaik`; `requests` only by `proprietary_files/get_vndk_libs.py`, which has
  zero importers (stand-alone regeneration script — "Use n.py to update this
  list").
- `aospdtgen/device_tree.py:99 dump_to_folder(folder)` writes flat into the
  given folder (no `<manu>/<codename>` nesting), whereas the twrpdtgen fork
  nests internally at `device_tree.py:103`. Therefore the aosp wrapper must
  build the full `<manu>/<codename>` path; the twrp wrapper can keep passing a
  base and let the fork nest, only adding the `device/` segment.
- `Partitions` probing (`sebaubuntu_libs.libandroid.partitions`) matches the
  DumprX OUTDIR layout (system/, vendor/, product/...) — the aospdtgen run
  during planning parsed props and fstab successfully and failed only at the
  AIK clone.

## Goals / Non-Goals

**Goals:**

- AOSP tree generation is fully offline and in-process, sharing the vendored
  AOSP boot-image unpacker already shipped for twrpdtgen.
- Dumps contain both trees: `aosp-device-tree/device/<manu>/<codename>/` and
  `twrp-device-tree/device/<manu>/<codename>/`, emitted back-to-back at the
  end of the pipeline, both best-effort.
- Dead code (`get_vndk_libs.py`) and now-unused deps (`GitPython`) are removed
  from the runtime path.

**Non-Goals:**

- No new boot-image unpacking logic; `twrpdtgen.image_info` is reused as-is.
- No changes to aospdtgen's tree contents or template set — only the
  AIK→unpack-images plumbing and the wrapper are new.
- No new CLI flags in this change; both trees generate on every dump with no
  opt-out. A future change can gate them.
- No auto-detection of manufacturer/codename disagreement between the two
  generators; both derive from the same `DeviceInfo` class so they agree.

## Decisions

### D1. Vendor aospdtgen at `src/aospdtgen/` (sibling, not subpackage)
Mirrors the twrpdtgen decision (D1 of `openspec/changes/archive/2026-09-19-use-twrpdtgen-fork/design.md`):
aospdtgen imports itself absolutely (`from aospdtgen...`), so it must be a
top-level importable package. `pyproject.toml` `[tool.uv] module-name` becomes
`["dumprx", "twrpdtgen", "aospdtgen"]`; the fork's own `pyproject.toml` is
dropped. The installed 1.2.1 package is the vendoring baseline; source commit
is recorded at implementation time from the upstream repo
(`sebaubuntu-python/aospdtgen`).
*Alternatives rejected:* vendoring from a third-party fork (none known that
fixes the AIK path); keeping `uvx --from` aospdtgen as a subprocess (runtime
network, no GKI support, mirrors the pre-fork twrpdtgen problem).

### D2. Rewrite `utils/boot_configuration.py` to use `twrpdtgen.image_info`
`BootConfiguration` currently owns five `AIKManager` instances (boot,
init_boot, recovery, vendor_boot, vendor_kernel_boot), each cloning AIK in its
constructor then `unpackimg(...)`. The rewrite keeps `BootConfiguration`'s
public shape (`boot_image_info`, `init_boot_image_info`, `recovery_image_info`,
`vendor_boot_image_info`, `vendor_kernel_boot_image_info`, `kernel`, `dt`,
`dtb`, `dtbo`, `base_address`, `cmdline`, `pagesize`, `copy_files_to_folder`,
`cleanup`) but backs each manager by our vendored
`twrpdtgen.image_info.unpack_images([image], ...)`.

The `AIKImageInfo` surface maps 1:1 onto vendored `ImageInfo`
(`image_info.py:41-55`): base_address, cmdline, pagesize, header_version,
origsize, sigtype, kernel, dt, dtb, dtbo, ramdisk. The template consumer
(`BoardConfig.mk.jinja2`) reads `boot_image_info.header_version`,
`origsize`, `sigtype` plus the merged `boot_configuration.*` fields — all
present on `ImageInfo`. The aospdtgen `device_tree.py:79-83` recovery-ramdisk
walk reads `*_aik_manager.ramdisk_path`; `ImageInfo.ramdisk` is the extracted
ramdisk dir, so a thin adapter exposes it (and falls back to boot ramdisk the
same way the current code does).

The GKI-ramdisk/LZ4-legacy fixes shipped for twrpdtgen carry over for free —
`extract_ramdisk` in `image_info.py` already handles LZ4 legacy magic and
missing-ramdisk tolerance (`_pick_vendor_ramdisk_fragment`).
*Alternatives rejected:* vendoring AIK into `utils/` (keeps bash unpackimg.sh,
still lacks GKI support, reintroduces a runtime clone target); porting the
aospdtgen template set to read `ImageInfo` directly without the
`BootConfiguration` adapter (touches several templates for no behavioral
gain).

### D3. Delete `proprietary_files/get_vndk_libs.py`
No importers in the package; it is a dev-side regeneration helper whose
`main()` runs at module import and fetches VNDK/GSI lists over HTTP. Removing
it kills the only `requests` runtime usage in aospdtgen and closes the last
network dependency of the module. The hardcoded list it regenerates
(`ignore.py:233 IGNORE_SHARED_LIBS`, 468 entries) stays vendored as-is.
*Alternatives rejected:* keeping it (offline violation, dead code);
vendoring the fetched lists (no functional benefit, they change rarely and
only on the dev maintenance path).

### D4. `src/dumprx/aospdtgen.py` wrapper + dual output contract
New module, sibling of `twrp.py`, exposing `generate(config) -> None`:

```
outdir = config.paths.outdir
dump = aospdtgen.device_tree.DeviceTree(<outdir tree, no_proprietary_files=False>)
target = outdir / "aosp-device-tree" / "device" \
       / dump.device_info.manufacturer / dump.device_info.codename
dump.dump_to_folder(target)      # writes flat into target
dump.cleanup()
```

Because aospdtgen's `dump_to_folder` nests nothing, the wrapper builds the
full path from `dump.device_info` (manufacturer/codename), guaranteeing the
same names the twrp fork derives internally from the identical `DeviceInfo`
class. Failures wrap in try/except with a loguru warning (best-effort), like
`twrp.py:44`. Best-effort also covers `device_tree.py:53`'s
`assert fstabs, "No fstab found"` — a firmware without an fstab must log and
continue, not abort.

TWRP side: `twrp.py:34` changes `twrp_out` to
`outdir / "twrp-device-tree" / "device"` so the fork's internal
`/<manu>/<codename>` nesting yields `twrp-device-tree/device/<manu>/<codename>/`
(mathes the updated spec and proposal's **BREAKING** note).
*Alternatives rejected:* writing aosp target as `outdir/device/...` directly
(collides with any product tree); a shared device-tree base dir
(`outdir/device/twrp/...`) — diverges from the established `*-device-tree`
top-level naming both existing outputs already use.

### D5. Run both generators at the end of the pipeline
`cli.py:183` already calls `generate_twrp(config)` immediately before
`init_repo`/`commit_local`. The change adds `generate_aospdtgen(config)` as
the next line; both are no-ops on missing boot images and best-effort on
failure. `commit_local` (cli.py:185) `git add`s the OUTDIR, so both trees are
committed with no publisher changes.
*Alternatives rejected:* running aospdtgen inside the extractor pipeline
(needs the finalized OUTDIR partition tree, which only exists post-extraction —
the end-of-pipeline slot is the correct point).

### D6. Provenance, lint, and licensing
Keep Apache-2.0 SPDX headers on every vendored file. Record the upstream
commit in AGENTS.md's vendored-code section (mirroring the twrpdtgen fork
note, including the "update the fork" recipe: re-apply dumprx-side changes
over a newer checkout). Add a ruff per-path ignore for `src/aospdtgen/**`
in `pyproject.toml` mirroring `src/twrpdtgen/**` (fork code does not follow
dumprx style). No changes to twrpdtgen tests are expected; `image_info` is
untouched.

## Risks / Trade-offs

- [aospdtgen emits `lineage_<codename>.mk` and asserts an fstab; some exotic
  dumps lack one] → Wrapper wraps the whole construction in try/except and
  logs a warning (spec: best-effort). No behavioral change to the dump.
- [The `device/` path segment on the TWRP tree breaks existing consumers of
  `twrp-device-tree/<manu>/<codename>/`] → Accepted; documented as BREAKING
  in proposal and the twrp spec delta. Internal consumers (commit stage)
  are path-agnostic (`git add -A`).
- [aospdtgen merge semantics across the five boot images differ subtly from
  AIK's (e.g. vendor_boot fragments)] → `image_info._pick_vendor_ramdisk_fragment`
  already selects the recovery fragment for vendor_boot v4; verified against
  the itel P55 5G dump during planning for the twrp path, same images.
- [version drift: aospdtgen runtime assumes a newer `sebaubuntu-libs` than
  1.6.1] → aospdtgen's release metadata pins `>=1.6.1,<2` and the venv has
  1.6.1 — already satisfied; re-check on fork re-vendoring.
- [Manual upper-merges drift] → same mitigation as the twrpdtgen fork: pinned
  commit + update note in AGENTS.md.

## Migration Plan

1. Vendor `src/aospdtgen/` from `sebaubuntu-python/aospdtgen` at the pinned
   commit; record the commit in AGENTS.md and this change's design.
2. Apply the two surgical edits: `boot_configuration.py` (AIK → image_info)
   and delete `get_vndk_libs.py`.
3. Add `src/dumprx/aospdtgen.py`; edit `twrp.py:34` and `cli.py:183`.
4. Update `pyproject.toml` (`module-name`, ruff ignores); `uv lock`.
5. Validate: `uv run ruff check`, `uv run pytest`, and a real-firmware dump
   locally to confirm both trees land and commit.
6. Rollback: single `git revert` restores the pre-fork runtime (`uvx` aospdtgen
   was never wired in, so rollback is clean — this change only adds).

## Open Questions

- Exact upstream commit hash of `sebaubuntu-python/aospdtgen` matching 1.2.1
  — **resolved: tag `v1.2.1` = `ff16bea7aabf8133affd9772e12651640712ae9a`**
  (verified `device_tree.py` byte-identical to the installed 1.2.1);
  recorded in AGENTS.md and `src/aospdtgen/__init__.py`.