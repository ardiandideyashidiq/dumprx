## Purpose

Defines Telegram notification behavior for the DumprX dump lifecycle: which lifecycle milestones produce channel messages, how the `TG_VERBOSITY` setting selects message detail, the always-send failure-alert rule, and the guarantee that notifications never break a dump.

## ADDED Requirements

### Requirement: Verbosity selection via TG_VERBOSITY
The system SHALL read a `TG_VERBOSITY` value from `.dumprxenv` with one of `minimal | normal | verbose` and a default of `normal`. Unrecognized values SHALL be treated as `normal`. `TG_VERBOSITY` SHALL be documented in `.dumprxenv.example`. Verbatim progress messages that carry no device identity (the extraction-started milestone) SHALL use the firmware source file name.

#### Scenario: Default when unset
- **WHEN** `TG_VERBOSITY` is absent from `.dumprxenv`
- **THEN** the effective verbosity is `normal`

#### Scenario: Explicit verbose
- **WHEN** `TG_VERBOSITY=verbose` is set in `.dumprxenv`
- **THEN** all milestone messages and their extended detail are sent

#### Scenario: Invalid value tolerated
- **WHEN** `TG_VERBOSITY` is set to anything other than `minimal`, `normal`, or `verbose`
- **THEN** the effective verbosity is `normal` and the dump proceeds

### Requirement: Lifecycle milestone notifications
The system SHALL send a Telegram message at each dump lifecycle milestone whose send threshold is met by the selected verbosity: extraction started (threshold `normal`, message carries the source file name), extraction finished (threshold `normal`, message carries the number of promoted partitions), committed locally (threshold `normal`, message carries the output directory), uploading to the remote (threshold `normal`, message carries the target mode and repository), and upload finished (threshold `minimal`, message carries the README card and repository tree URL). At `verbose`, milestone messages SHALL additionally carry detail such as the git branch, elapsed durations, and repository path.

#### Scenario: Normal verbosity sends milestones
- **WHEN** `TG_VERBOSITY=normal` and a dump runs through extraction, commit, and publish
- **THEN** extraction started, extraction finished, committed, uploading, and upload-finished messages are all sent

#### Scenario: Minimal verbosity sends the final card only
- **WHEN** `TG_VERBOSITY=minimal` and a dump runs through extraction, commit, and publish
- **THEN** only the upload-finished message (README card with tree URL) is sent

#### Scenario: Extraction started references source only
- **WHEN** the extraction-started message is sent before device properties are derived
- **THEN** the message identifies the dump by source file name and does not claim brand or model

#### Scenario: Mode without publish
- **WHEN** the dump runs in `local` mode or stops at `--readme-only`
- **THEN** milestones that never occur are not sent, and the milestones that do occur are sent per the selected verbosity

### Requirement: Failure alerts always sent
The system SHALL send a Telegram failure alert whenever the pipeline aborts — extraction failed, property parsing produced no identity, the local commit failed, or the remote publish failed — regardless of the selected verbosity level. Failure alerts SHALL include the reason and, where applicable, note that the locally committed dump is preserved for a later re-push.

#### Scenario: Failure alert at minimal verbosity
- **WHEN** `TG_VERBOSITY=minimal` and the pipeline aborts
- **THEN** a failure alert is still sent to the channel

#### Scenario: Publish failure notes preserved dump
- **WHEN** the remote publish fails after the local commit succeeded
- **THEN** the failure alert states the error and the output directory where the committed dump is preserved

### Requirement: Notifications never abort the dump
The system SHALL tolerate every Telegram send failure: a failed send SHALL be logged and never change the dump's exit code or outcome. When `TG_TOKEN` is unset, the system SHALL skip all Telegram notification and proceed normally.

#### Scenario: Unset token proceeds
- **WHEN** `TG_TOKEN` is not configured
- **THEN** no Telegram send is attempted and the dump completes normally

#### Scenario: Failed send is tolerated
- **WHEN** a Telegram send fails (network, API, or token rejection)
- **THEN** the failure is logged and the dump continues without altering its exit code