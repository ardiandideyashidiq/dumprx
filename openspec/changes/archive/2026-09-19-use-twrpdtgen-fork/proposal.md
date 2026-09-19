## Why

Upstream `twrpdtgen` v3.0 unpacks images through Android Image Kitchen (AIK),
which cannot decode modern GKI firmware (vendor_boot/init_boot, boot image
headers v3/v4), so `twrp.py` produces no TWRP tree at all on exactly the
firmware dumper users care about most. Upstream has effectively stopped fixing
this (the maintainer redirects newer devices to aospdtgen; issues sit open for
years). We forked twrpdtgen to `ardiandideyashidiq/twrpdtgen`, and the highest
leverage path is to vendor that fork directly into this repository and fix
image handling at the source.

## What Changes

- **Vendor the twrpdtgen fork** into the package tree at `src/twrpdtgen/`
  (Apache-2.0), importable as `twrpdtgen` and built by the same `uv_build`
  backend as `dumprx` (via `module-name`).
- **Replace AIK with mkbootimg**: unpack boot/vendor_boot/init_boot images
  with mkbootimg's `unpack_bootimg`, reading header version, base address,
  offsets, pagesize, cmdline and original size into the `image_info` surface
  that the `BoardConfig.mk`/`device.mk` templates already consume.
- **Adaptive image selection**: the generator accepts the whole boot-family
  image set present in OUTDIR (recovery/boot/vendor_boot/init_boot), selects
  the ramdisk-bearing image per header version, and merges kernel/dtb/cmdline
  across the set so GKI v3/v4 firmware still yields a tree.
- **Library invocation**: `twrp.py` calls the vendored `DeviceTree` directly
  instead of shelling out to `uvx --from git+...@master twrpdtgen`; the
  `_TWRPDTGEN` subprocess string goes away.
- **Dependency trim in the fork**: remove the `libaik` unpacker and
  `liblogging` (`LOGD` -> loguru), drop the unused `--git`/gitpython path,
  keep `sebaubuntu_libs.libandroid` (DeviceInfo/Fstab/BuildProp) as a runtime
  dependency.
- **Runtime tooling**: `mkbootimg` added to the setup/system dependency flow
  alongside `dtc`/`7zz`.
- Output contract unchanged: tree lands at
  `twrp-device-tree/<manufacturer>/<codename>/...`, wiki README still fetched,
  `.git` dirs still removed, generation stays best-effort (failures log, dump
  continues).

## Capabilities

### New Capabilities
- `dumprx/twrp`: vendored adaptive TWRP device tree generation from the
  boot-family image set, covering GKI/modern firmware (mkbootimg unpacking,
  address extraction, image selection) and the preserved output contract
  (tree layout, wiki README fetch, `.git` cleanup, best-effort failure).

### Modified Capabilities
(none — the existing `dumprx` output-parity statement "TWRP device tree (when
image present and generation succeeds)" remains true; this change adds a
precise spec for the tree-generation step itself)

## Impact

- `src/dumprx/twrp.py` — rewritten: library call, image-set parameter.
- `src/dumprx/cli.py:183` — passes the boot-family image set instead of a
  single boolean/`is_ab`.
- `pyproject.toml` — `module-name = ["dumprx", "twrpdtgen"]`, new runtime dep
  `sebaubuntu_libs`, `uv lock`.
- `src/dumprx/setup.py` — install `mkbootimg` as runtime tooling.
- `src/dumprx/tools.py` — register `mkbootimg` if needed for address reads.
- `tests/test_output.py` — twrp mocks updated for library invocation and the
  image set.
- New vendored package `src/twrpdtgen/` (derived from
  `ardiandideyashidiq/twrpdtgen`, which is a fork of `twrpdtgen/twrpdtgen`).
- `AGENTS.md`/README — repository structure and tooling notes updated.