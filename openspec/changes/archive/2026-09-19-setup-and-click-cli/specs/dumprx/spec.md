## MODIFIED Requirements

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

## ADDED Requirements

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