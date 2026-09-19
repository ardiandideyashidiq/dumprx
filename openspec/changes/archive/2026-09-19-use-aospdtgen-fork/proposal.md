## Why

aospdtgen is the upstream LineageOS/AOSP device-tree generator that the
twrpdtgen maintainer redirects modern-device users to; it produces a buildable
`device/<manufacturer>/<codename>/` tree (proprietary-files, build props,
rootdir, fstab, manifest) for custom-ROM development. Like twrpdtgen before the
fork, aospdtgen unpacks boot images through `sebaubuntu_libs.libaik.AIKManager`,
which fails on GKI (header v3/v4) firmware and clones an external Git repo into
a tempdir on every run — a runtime network dependency that hangs and is not
offline-reproducible. We already forked twrpdtgen to remove exactly this
dependency; forking aospdtgen the same way gives firmware dumps a complete,
offline custom-ROM tree alongside the recovery tree.

## What Changes

- **Vendor the aospdtgen package** into the tree at `src/aospdtgen/`
  (Apache-2.0), importable as `aospdtgen` and built by the same `uv_build`
  backend as `dumprx` and `twrpdtgen` (via `module-name`).
- **Replace AIK with the existing vendored unpacker**: rewrite
  `aospdtgen/utils/boot_configuration.py` so its five AIK managers
  (boot/init_boot/recovery/vendor_boot/vendor_kernel_boot) route through our
  already-vendored `twrpdtgen.image_info.unpack_images()` + vendored AOSP
  `unpack_bootimg`, eliminating the runtime AIK clone and adding GKI support.
  The `AIKImageInfo` field surface maps 1:1 onto our vendored `ImageInfo`.
- **Delete dead code**: `proprietary_files/get_vndk_libs.py` is a stand-alone
  generator script with no importers (its comments say "Use n.py to update
  this list"); it fetches VNDK lists from android.googlesource.com. It is not
  on the dump path and is removed with the vendoring.
- **Add a pipeline wrapper** `src/dumprx/aospdtgen.py` (sibling of `twrp.py`)
  that runs aospdtgen in-process against the dump OUTDIR and writes the tree to
  `aosp-device-tree/device/<manufacturer>/<codename>/`.
- **Align the TWRP output contract**: both generators now place trees under a
  `device/` segment — TWRP moves from `twrp-device-tree/<manufacturer>/<codename>/`
  to `twrp-device-tree/device/<manufacturer>/<codename>/`. This is **BREAKING**
  for consumers of the previous path.
- **Run both generators at the end of the pipeline**, immediately after the
  existing `generate_twrp` call, both best-effort and independently.
- **Dependency trim**: `GitPython` (AIK-only) and the aospdtgen-only `requests`
  usage (get_vndk_libs) fall out of the runtime; no net-new Python dependency
  is required (`sebaubuntu-libs 1.6.1` + `jinja2` are already present via the
  twrpdtgen fork).

## Capabilities

### New Capabilities
- `dumprx/aospdtgen`: offline, GKI-capable generation of a LineageOS/AOSP `device/<manufacturer>/<codename>/` tree from a dumped firmware, run in-process at the end of the dump pipeline with best-effort failures.

### Modified Capabilities
- `dumprx/twrp`: the preserved output contract changes — the TWRP tree SHALL land
  under `twrp-device-tree/device/<manufacturer>/<codename>/` (a new `device/`
  path segment) instead of `twrp-device-tree/<manufacturer>/<codename>/`.

## Impact

- **Code**: `src/aospdtgen/` (vendored package); `src/dumprx/aospdtgen.py`,
  `src/dumprx/twrp.py`, `src/dumprx/cli.py` (wrapper + output path + run both);
  `src/twrpdtgen/image_info.py` is reused as-is (no changes expected).
- **Build**: `pyproject.toml` `[tool.uv] module-name` gains `"aospdtgen"`;
  ruff per-path ignores (`src/aospdtgen/**` mirroring `src/twrpdtgen/**`);
  `uv lock` if dependency constraints change (expected: none added, GitPython
  may drop from the resolution if unused).
- **Docs**: AGENTS.md vendored-fork provenance section (commit pin for
  aospdtgen, "updating the fork" note), README generator credit.
- **Tests**: `tests/test_aospdtgen.py` (mock the vendored `DeviceTree`, assert
  tree dir) matching the twrpdtgen test pattern; update twrp output-path tests;
  `tests/test_pipeline.py` `commit_local`-adjacent assertions if they reference
  the twrp path.
- **Risks**: moving the TWRP tree path is a breaking change for anyone
  consuming `twrp-device-tree/<manu>/<codename>/`; verified only against the
  itel P55 5G (TranOS/MT6833) dump during planning — other firmware shapes get
  manual verification during implementation.