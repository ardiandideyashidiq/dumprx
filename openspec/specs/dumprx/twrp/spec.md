## Purpose

Generates a TWRP-compatible device tree from the boot-family images of a
dumped firmware, including modern GKI (header v3/v4) firmware that legacy
unpacking cannot decode, and preserves the established TWRP output contract.

## Requirements

### Requirement: Adaptive boot-family image set

The TWRP tree generator SHALL accept the full boot-family image set present in
the dump output directory — any combination of `recovery.img`, `boot.img`,
`vendor_boot.img`, and `init_boot.img` — and SHALL produce a device tree for
both legacy firmware (single boot or recovery image) and modern firmware
(boot plus vendor_boot, with or without init_boot) without requiring the
caller to pre-select a single image. When both legacy and modern images are
present, the generator SHALL prefer the image that carries the device ramdisk
(recovery for legacy, vendor_boot for A/B and GKI firmware) and SHALL ignore
GKI-only images that carry no device-specific ramdisk when a better source
exists.

#### Scenario: GKI firmware with vendor_boot and init_boot
- **WHEN** the image set contains `boot.img`, `vendor_boot.img`, and `init_boot.img` and no `recovery.img`
- **THEN** a device tree is generated successfully using `vendor_boot.img` as the ramdisk source

#### Scenario: Legacy firmware with a single recovery image
- **WHEN** the image set contains only `recovery.img`
- **THEN** a device tree is generated as before

#### Scenario: No eligible image
- **WHEN** the image set contains none of `recovery.img`, `boot.img`, `vendor_boot.img`, or `init_boot.img`
- **THEN** no tree generation is attempted and the dump continues

### Requirement: Modern image parsing with readable header fields

The generator SHALL parse boot-family images (boot, vendor_boot, init_boot,
recovery) with an unpacker that decodes header versions 0 through 4 —
including images that legacy AIK-style unpacking cannot decode — and SHALL
extract the fields needed to emit a correct `BoardConfig.mk`: header version,
base address, page size, kernel/ramdisk/tags offsets, command line, and
original image size. The extracted kernel, dtb, dtbo, and ramdisk blobs SHALL
be reproduced in the generated tree structure exactly as before.

#### Scenario: Header v4 vendor_boot image
- **WHEN** the chosen image has a v3/v4 header (vendor_boot format)
- **THEN** parsing succeeds and `BoardConfig.mk` carries the correct decoded header version and address fields

#### Scenario: Address fields feed BoardConfig.mk
- **WHEN** header fields are decoded by the unpacker
- **THEN** `BOARD_BOOTIMG_HEADER_VERSION`, `BOARD_KERNEL_BASE`, `BOARD_KERNEL_CMDLINE`, `BOARD_KERNEL_PAGESIZE`, `BOARD_RAMDISK_OFFSET`, `BOARD_KERNEL_TAGS_OFFSET`, and `BOARD_BOOTIMAGE_PARTITION_SIZE` reflect those decoded values

### Requirement: In-process invocation and best-effort failure

The generator SHALL run in-process as a library invoked by the dump pipeline,
not as a downloaded subprocess, so the generator is reproducible from the
repository alone. Generation failures SHALL be logged and SHALL NOT abort the
dump, matching the current best-effort contract.

#### Scenario: Generation fails
- **WHEN** device tree generation raises an error for a given firmware
- **THEN** the error is logged and the dump pipeline continues without a tree

#### Scenario: Generator is reproducible offline
- **WHEN** a dump is produced on a machine with no network access
- **THEN** tree generation does not require downloading tool sources at runtime

### Requirement: Preserved output contract

When generation succeeds, the tree SHALL appear under
`twrp-device-tree/<manufacturer>/<codename>/` in the output directory, the
build-from-source wiki README SHALL be fetched into that folder, and all
`.git` directories inside the generated tree SHALL be removed before the dump
finishes.

#### Scenario: Tree lands in the expected location
- **WHEN** generation succeeds and the device is identified
- **THEN** the tree is found at `twrp-device-tree/<manufacturer>/<codename>/`

#### Scenario: Wiki README fetched and repositories stripped
- **WHEN** generation succeeds
- **THEN** the wiki README is present in the tree folder and no `.git`
  directory remains under `twrp-device-tree/`