## Purpose

`dumprx` is the Python replacement for `dumper.sh`: a stateful pipeline that resolves firmware input (download URL, local file, or extracted folder), stage-by-stage decodes and extracts Android partitions, normalizes images, parses device/build properties, generates a dump package (README, file listing, TWRP tree), and — in gitlab/github modes — publishes that package to a remote and notifies a Telegram channel. It is invoked as `uv run dumprx`.

## Requirements

### Requirement: CLI parity
The `dumprx` CLI SHALL accept the same options and semantics as `dumper.sh`: `-p/--push-only`, `-r/--readme-only`, `-m/--mode <local|gitlab|github>`, `-g/--gitlab`, `-b/--github`, `-l/--local`, `--public`, `-h/--help`, plus `--setup`, `--no-setup`, and `-o/--output <dir>`. Single positional input (firmware file, extracted folder, or supported URL). Unknown options MUST print an error and exit non-zero when the operation would parse them. `-h` MUST print help and exit 0. Default mode is `gitlab`; default visibility is `private`. `--setup` SHALL run setup and exit; `--no-setup` SHALL bypass the auto-run of setup.

#### Scenario: All flags accepted
- **WHEN** dumprx is invoked with any documented flag combination
- **THEN** parsing succeeds and behavior matches the flag semantics

#### Scenario: Missing input in extract mode
- **WHEN** neither `--push-only` nor `--readme-only` set and no positional input given, outside the setup-flag flow
- **THEN** CLI prints an error and exits non-zero

#### Scenario: Unknown option
- **WHEN** an unrecognized `-*` option is passed
- **THEN** CLI prints an error and exits non-zero

#### Scenario: Setup flag runs setup only
- **WHEN** `--setup` is passed
- **THEN** setup runs and the CLI exits without requiring a firmware argument

### Requirement: Single-process stage queue
Firmware decoding MUST run in one process. Nested or wrapper artifacts (ozip, ops, ofp, tgz, kdz, ruu, archive-in-folder, archive-in-archive) MUST be handled by re-queuing their produced source onto an internal work list, never by re-invoking the program. Processing MUST continue until a terminal artifact is classified or the queue is exhausted.

#### Scenario: Outer container decodes a terminal artifact
- **WHEN** the current source is a container whose extraction yields a payload.bin
- **THEN** the payload source is queued and processed without spawning a new process

#### Scenario: Queue exhaustion
- **WHEN** all queued sources are processed and none yields a terminal artifact
- **THEN** the pipeline ends with a non-zero exit and a clear error

### Requirement: Input resolution parity
The pipeline SHALL resolve input like `dumper.sh`: download URLs through the hoster handler (mega.nz/mediafire/drive.google.com, androidfilehost, we.tl, direct links via aria2/wget), accept local file paths and extracted folders, detect archive-within-folder and re-queue it, and reject unsupported input with a non-zero exit. Paths containing spaces MUST be handled correctly end to end.

#### Scenario: Supported download URL
- **WHEN** a supported URL is provided
- **THEN** the file is downloaded into the input directory and staged for detection

#### Scenario: Unsupported input
- **WHEN** input matches no supported format or hoster
- **THEN** pipeline errors and exits non-zero

### Requirement: Extraction parity
The pipeline SHALL extract the same firmware families as `dumper.sh`: OZIP, OPS, OFP, TGZ, KDZ/DZ, RUU, AML, DAT OTA, QFIL, NB0, chunked/sparse images, raw images, SIN, PAC, bin, P-suffix, signed (SSSS/BFBF) images, super images (including split/merged/`super_*.img`), payload.bin, Samsung `tar.md5`/lz4, `UPDATE.APP`, Rockchip, and generic zip/rar/7z/tar archives. Each terminal extraction SHALL produce partition `.img` files into the output directory using the same naming and conversion rules.

#### Scenario: Known partition image survives conversion
- **WHEN** a sparse `system.img` is extracted
- **THEN** `OUTDIR/system.img` exists as a raw image after integer-conversion, same as `simg2img` output

#### Scenario: Header-strip transformations preserved
- **WHEN** a partition carries a MOTO or ASUS header
- **THEN** the offset scan and header-strip produce the same image bytes as `dumper.sh` for that partition

### Requirement: Property parsing parity
The pipeline SHALL derive the same firmware metadata set as `dumper.sh` — flavor, release, id, tags, platform, manufacturer, fingerprint, brand, codename, description, incremental, abilist, locale, density, is_ab, treble_support, otaver, transname, osver, xosver, sec_patch, xosid, tranchipset, opchipset, xiaominame, motoname, opname, date, kernel_version, board-info.txt — including vendor-specific overrides (Euclid, Tr* Transsion, Oppo/My*, Realme fallbacks) and the same first-match-wins cascade order.

#### Scenario: Cascading fallback
- **WHEN** a property key is absent from system but present in vendor
- **THEN** the vendor value is used, identical to `dumper.sh` result

#### Scenario: Vendor override applied
- **WHEN** `ro.vendor.mediatek.platform` or a vendor `ro.board.platform` exists
- **THEN** platform is overridden by that value

### Requirement: Output parity
The pipeline SHALL produce the same output artifacts in `OUTDIR` (`/tmp/out`) as `dumper.sh`: partition folders and images, `board-info.txt`, `README.md` dump card, `all_files.txt`, TWRP device tree (when image present and generation succeeds), and the same branch naming derived from otaver/description/xosid. `--push-only` SHALL operate on an existing `OUTDIR` without extraction; `--readme-only` SHALL stop after README generation.

#### Scenario: all_files.txt reflects tree
- **WHEN** extraction and file cleanup complete
- **THEN** `OUTDIR/all_files.txt` lists every file relative to OUTDIR, sorted, excluding `.git/` paths

#### Scenario: readme-only stops early
- **WHEN** `--readme-only` is set
- **THEN** README.md is generated and the pipeline exits before TWRP/push work

### Requirement: Memory-safety and bounded resources
The pipeline MUST process firmware without unbounded memory growth. Subprocess outputs MUST be drained or discarded explicitly (no unread pipes), concurrent workers MUST be capped at `nproc` (per-stage bound), large images MUST be copied/streamed rather than read wholly into memory, and the work directory MUST be cleaned on normal exit, interruption, and error.

#### Scenario: Large archive listing handled lazily
- **WHEN** a very large archive listing is produced
- **THEN** listing is consumed lazily or persisted without accumulating an unbounded in-memory string

#### Scenario: Parallel extraction capped
- **WHEN** multiple filesystem images are extracted concurrently
- **THEN** active workers never exceed the configured bound and no zombie processes remain

### Requirement: Performance floor
The pipeline SHALL read each `build*.prop` file at most once and reuse parsed values across all property lookups. Archive extraction SHALL prefer a single full extract over per-file pulls where the target branch tolerates missing files. Header-strip SHALL sniff the first bytes before running a full-image offset scan.

#### Scenario: Property set parsed once
- **WHEN** the property phase runs against a firmware tree with N build.prop files
- **THEN** each file is read and parsed at most once and no per-key filesystem scans occur

### Requirement: Debug logging
The pipeline SHALL log at debug level by default. Every stage entry/exit, extractor classification decision, container re-queue, and subprocess invocation (argv, retcode, duration) MUST produce a structured log line. Log level MUST be overridable via `DUMPRX_LOG_LEVEL`. A rotating log file MUST be written alongside the work directory for post-mortem analysis. Secrets loaded from `.dumprxenv` MUST NOT be logged.

#### Scenario: Subprocess trace visible
- **WHEN** any external tool runs
- **THEN** a debug line records argv, return code, and elapsed time

#### Scenario: Token redaction
- **WHEN** configuration is loaded or a command built
- **THEN** token values never appear in log output

### Requirement: Environment configuration
The pipeline SHALL source the same environment contract as `.dumprxenv.example`: `GITLAB_TOKEN`, `GITLAB_INSTANCE`, `GITLAB_GROUP`, `GITHUB_TOKEN`, `GITHUB_ORG`, `TG_TOKEN`, `TG_CHAT`, plus `DUMPRX_JOBS` (extraction parallelism) and `DUMPRX_LOG_LEVEL`. Missing required credentials in gitlab/github modes MUST abort with a clear message.

#### Scenario: Missing GitLab token in gitlab mode
- **WHEN** `--mode gitlab` is used without `GITLAB_TOKEN`
- **THEN** pipeline aborts with an explanatory error and non-zero exit

### Requirement: Output directory override
The CLI SHALL accept `-o/--output <dir>` to set the dump output directory (`OUTDIR`). When unset, `OUTDIR` defaults to `/tmp/out`. All output artifacts — README.md, `all_files.txt`, partition images/folders, the work directory, and the rotating log — SHALL be written under the selected `OUTDIR`. Publish phases (`--push-only`) and `--readme-only` SHALL operate on the selected `OUTDIR`.

#### Scenario: Custom output directory
- **WHEN** `dumprx -o /data/dumps firmware.bin` is invoked
- **THEN** all dump artifacts are produced under `/data/dumps`, `README.md` and `all_files.txt` included

#### Scenario: Default output directory preserved
- **WHEN** no `-o/--output` is given
- **THEN** output artifacts are produced under `/tmp/out`

#### Scenario: Publish from custom output
- **WHEN** `dumprx --push-only -o /data/dumps` is invoked
- **THEN** the existing tree under `/data/dumps` is published without extraction

### Requirement: Rich grouped help
The `--help` output SHALL be rendered with rich formatting and SHALL group related options into named sections (for example mode selection, setup, and output control). Help SHALL exit 0 and SHALL be validated against the documented flag surface.

#### Scenario: Grouped help listing
- **WHEN** `dumprx --help` is invoked
- **THEN** options appear grouped into named sections and the exit code is 0

#### Scenario: Flags surfaced in help
- **WHEN** `dumprx --help` is invoked
- **THEN** `--setup`, `--no-setup`, and `-o/--output` are listed alongside the existing flags