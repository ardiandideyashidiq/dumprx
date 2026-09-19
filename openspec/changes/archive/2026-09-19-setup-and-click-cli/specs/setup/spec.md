## Purpose

Manages first-run device setup for DumprX: installs system prerequisites once, records completion in persistent state, and automatically runs setup when that state is missing or incomplete.

## ADDED Requirements

### Requirement: Setup command
`dumprx --setup` SHALL install the system prerequisites for dumping firmware: system packages through the detected package manager (apt/dnf/pacman/apk/brew), the `uv` tool, runtime helper clones under `utils/`, and Python dependencies via `uv sync`. Setup SHOULD escalate privileges (e.g. `sudo`) only when it lacks write access. On full success it SHALL mark setup complete in persistent state. An explicit `--setup` SHALL re-run setup even when state already reports complete.

#### Scenario: Explicit setup run
- **WHEN** `dumprx --setup` is invoked and setup succeeds
- **THEN** prerequisites are installed and the state file records setup complete

#### Scenario: Re-run after completion
- **WHEN** `dumprx --setup` is invoked and state already reports complete
- **THEN** setup re-runs and state is rewritten on success

### Requirement: Setup state persistence
The setup SHALL record a completion state in a machine-scoped file outside the repository checkout (XDG state location). The state file SHALL identify the recorded state as complete only for a fully successful setup.

#### Scenario: State written on success
- **WHEN** an explicit or auto setup finishes without failure
- **THEN** the state file is (re)written and reports complete

### Requirement: Auto-run setup on incomplete setup
When dumprx is invoked without `--setup` and the state file is missing or does not report complete, the CLI SHALL run setup first, then proceed with the dump path.

#### Scenario: First run without setup
- **WHEN** dumprx is invoked with no state file present
- **THEN** setup runs automatically before the requested operation proceeds

#### Scenario: Partial state ignored
- **WHEN** the state file exists but does not report complete
- **THEN** setup runs automatically and state is rewritten on success

### Requirement: Auto-setup failure tolerance
When setup runs automatically (not via explicit `--setup`) and fails, the CLI SHALL warn and continue with the requested dump operation rather than aborting. Explicit `--setup` failures SHALL exit non-zero.

#### Scenario: Auto-setup fails
- **WHEN** an auto-run setup fails and the user invoked a dump operation
- **THEN** a warning is printed and the dump operation proceeds

#### Scenario: Explicit setup fails
- **WHEN** `dumprx --setup` fails
- **THEN** the CLI exits non-zero

### Requirement: Bypass auto-setup
`--no-setup` SHALL skip the auto-run check entirely and proceed directly to the requested operation, regardless of setup state.

#### Scenario: Bypass with missing state
- **WHEN** `--no-setup` is passed and the state file is missing
- **THEN** no setup runs and the requested operation proceeds