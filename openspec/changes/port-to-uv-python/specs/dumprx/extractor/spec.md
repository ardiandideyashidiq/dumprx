## Purpose

The extractor registry is the plug-and-play seam for firmware format support. Each supported format is one self-contained module with a detect step and an extract step; adding a format adds a module, never edits to the pipeline. Container extractors decode wrappers and emit the next source into the stage queue; terminal extractors produce partition images.

## ADDED Requirements

### Requirement: Ordered detection, first match wins
Extractors SHALL be registered in the exact order the `dumper.sh` dispatch chain evaluates branches (ozip, ops-in-archive, ops, ofp-in-archive, ofp, tgz, kdz, ruu, aml containers; then dat, qfil, nb0, chunk, raw image, sin, pac, bin, P-suffix, signed, super, tar.md5, payload.bin, archive, UPDATE.APP, rockchip terminals). Classification MUST return the first extractor whose `detect` succeeds, matching current `elif` semantics. Detection MUST consider both the work-directory contents and the cached archive listing, exactly as the current branches do.

#### Scenario: First match determines handling
- **WHEN** two extractors both match a source
- **THEN** the one with the lower registry order is used

#### Scenario: Container superseded only by earlier container
- **WHEN** a source matches both a container and a terminal
- **THEN** the container wins, because all container checks precede the terminal chain

### Requirement: Two extractor kinds
Each extractor SHALL declare its kind. `container` kinds decode a wrapper (e.g. ozip decrypt, kdz unkdz, archive re-entry) and, when successful, expose the next source for re-queueing. `terminal` kinds run in the work directory and produce partition images or trigger `super` handling. A container MUST NOT also act as a terminal for the same input.

#### Scenario: Container yields next source
- **WHEN** a container successfully decodes an ozip
- **THEN** the produced zip/directory is queued as the next source and processed in the same process

#### Scenario: Terminal extracts partitions
- **WHEN** a terminal extractor runs on payload.bin
- **THEN** partition images are emitted into the work/output directories

### Requirement: New format is a drop-in module
Adding support for a new firmware format SHALL require only a new module registering an extractor with a unique order, detect, and extract implementation. The pipeline, registry, and other extractors SHALL remain unchanged.

#### Scenario: Plugin added without pipeline edits
- **WHEN** a new extractor module is dropped into the registry
- **THEN** the pipeline picks it up by registry order and classification works without code changes outside the module

### Requirement: Origin context for late archive pulls
After container stages have extracted inner content, a terminal extractor SHALL retain a reference to the original outer archive and its cached listing, so missing partitions or other-partitions can be pulled from that archive exactly as the current `ARCHIVE_LISTING`-based loops do.

#### Scenario: Missing partition pulled from origin
- **WHEN** a partition image is absent from the work directory but exists in the original outer archive
- **THEN** the extractor pulls it from the origin archive and converts it like the current `.img` loop

### Requirement: Classify failure is explicit
When no extractor matches, classification MUST raise a clear error identifying the source and the formats attempted. The pipeline MUST NOT silently continue without classification.

#### Scenario: Unsupported firmware
- **WHEN** no registered extractor detects the source
- **THEN** the pipeline reports the unsupported input and exits non-zero, listing the candidates evaluated

### Requirement: Extractor failures are scoped
A terminal extractor failure MUST log its context and exact failing step, but SHALL follow the current branch fallback behavior: extraction paths deliberately tolerate failures and continue with the next fallback (e.g. erofs -> 7zz -> mount). Only the input-rejection paths SHALL abort non-zero.

#### Scenario: Filesystem fallback chain
- **WHEN** erofs extraction fails for a partition
- **THEN** the 7zz path, then mount path, run as fallbacks in order, matching current behavior