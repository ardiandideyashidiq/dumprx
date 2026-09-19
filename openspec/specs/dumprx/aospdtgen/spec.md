## Purpose

Generates a LineageOS/AOSP device tree (`device/<manufacturer>/<codename>/`)
from a dumped firmware, including modern GKI (header v3/v4) firmware, run
in-process with best-effort failures so the dump always completes.

## Requirements

### Requirement: Offline, in-process AOSP tree generation

The generator SHALL run in-process as a library invoked by the dump pipeline
against the dump output directory, not as a downloaded subprocess or via any
runtime tool download, so generation is reproducible from the repository
alone. It SHALL parse the extracted partition tree (system, vendor, and the
remaining treble/SSI partitions present in the dump) plus the boot-family
image set to derive device info, fstab, build props, and partition properties.

#### Scenario: Generator runs on a dumped firmware
- **WHEN** the dump pipeline completes extraction and calls the generator with the output directory
- **THEN** device info, build props, fstab, and boot configuration are parsed from the extracted tree without any network access

#### Scenario: Generator is reproducible offline
- **WHEN** a dump is produced on a machine with no network access
- **THEN** AOSP tree generation does not require downloading tool sources or data lists at runtime

### Requirement: Boot-family and GKI image support

The generator SHALL unpack boot-family images (boot, recovery, init_boot,
vendor_boot, vendor_kernel_boot) with an unpacker that decodes header versions
0 through 4, including images that legacy AIK-style unpacking cannot decode,
and SHALL pick the best image or merge fields across the set so GKI v3/v4
firmware still yields kernel, dtb, dtbo, base address, cmdline, and page size.

#### Scenario: GKI firmware with vendor_boot and init_boot
- **WHEN** the image set contains `boot.img`, `vendor_boot.img`, and `init_boot.img` with a v3/v4 vendor_boot header
- **THEN** the boot configuration is parsed successfully and addresses are taken from vendor_boot

#### Scenario: Legacy firmware with a single boot image
- **WHEN** only `boot.img` is present with a legacy header
- **THEN** the boot configuration is derived from boot.img as before

#### Scenario: No boot image
- **WHEN** the dump contains none of the boot-family images
- **THEN** tree generation fails with a logged warning and the dump continues (best-effort)

### Requirement: Full device tree output

When generation succeeds, the generator SHALL produce a complete
LineageOS-style device tree: `Android.bp`, `Android.mk`,
`AndroidProducts.mk`, `BoardConfig.mk`, `device.mk`,
`lineage_<codename>.mk`, `README.md`, `proprietary-files.txt`,
`extract-files.py`, `setup-makefiles.py`, per-partition `.prop` files,
`prebuilts/` (kernel, dt.img, dtb.img, dtbo.img), `rootdir/` (bin scripts,
etc/init files, recovery .rc files, formatted fstab), and `manifest.xml`.

#### Scenario: Successful generation writes the full tree
- **WHEN** generation succeeds for a firmware with complete partitions and boot images
- **THEN** all listed makefiles, blueprints, proprietary-files list, extract utilities, prebuilts, rootdir, and manifest are present in the output folder

### Requirement: Best-effort failures

Generation failures SHALL be logged and SHALL NOT abort the dump, matching the
existing TWRP best-effort contract. Failures to fetch optional resources SHALL
also be tolerated.

#### Scenario: Generation fails
- **WHEN** AOSP tree generation raises an error for a given firmware
- **THEN** the error is logged and the dump pipeline continues without a tree

### Requirement: Preserved output contract

When generation succeeds, the tree SHALL appear under
`aosp-device-tree/device/<manufacturer>/<codename>/` in the output directory.

#### Scenario: Tree lands in the expected location
- **WHEN** generation succeeds and the device is identified
- **THEN** the tree is found at `aosp-device-tree/device/<manufacturer>/<codename>/`