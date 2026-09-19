## Purpose

The publisher registry is the plug-and-play seam for remote delivery of a completed dump. One backend handles repository creation, staged commits, LFS upload, and push; a Telegram notification hook runs after a successful push. Backends SHARE the commit/LFS/retry logic and STAGE the git repository in the exact order `dumper.sh` uses.

## ADDED Requirements

### Requirement: Backend interface
A publisher SHALL expose repo creation, repo metadata (visibility, description), default-branch update, and a shared staged-commit flow. Selecting a mode selects the backend (gitlab -> gitlab backend, github -> github backend, local -> no publisher and no notification).

#### Scenario: GitLab mode selects gitlab backend
- **WHEN** `--mode gitlab` runs with valid credentials
- **THEN** gitlab backend performs all remote delivery

#### Scenario: Local mode skips publishing
- **WHEN** `--mode local` completes a dump
- **THEN** no remote calls occur and no Telegram notification is sent

### Requirement: New backend is a drop-in module
Adding a new delivery target SHALL require only a new module registering a publisher. Commit staging, retry, and LFS logic SHALL be inherited, not duplicated.

#### Scenario: Publisher added without pipeline edits
- **WHEN** a new publisher module is registered
- **THEN** the pipeline selects it by mode without changes outside the module

### Requirement: Already-dumped short-circuit
Before repo creation or any commit, the active backend SHALL check the remote for an existing `all_files.txt` on the target branch; if present, it MUST abort with a message pointing at the existing tree, matching current behavior.

#### Scenario: Firmware already dumped
- **WHEN** remote `all_files.txt` already exists on the branch
- **THEN** pipeline aborts with the existing-tree URL and skips all remote writes

### Requirement: Staged commit order
The shared flow SHALL commit in this exact order, one commit per stage, matching `dumper.sh`: README.md, `.gitattributes` LFS setup, all `*.apk`, partition group dirs (system_ext, product, system_dlkm, odm, odm_dlkm, init_boot, vendor_boot, vendor_dlkm, vendor, system, tr_product, tr_region, with `system/` and `system/system/` prefixes), then remaining extras. Each push SHALL retry up to 5 attempts with a delay before failing.

#### Scenario: Commit sequence preserved
- **WHEN** a full dump is published
- **THEN** remote history contains the staged commits in the documented order

#### Scenario: Push retry
- **WHEN** a push fails transiently
- **THEN** the flow retries up to 5 times with delay before aborting

### Requirement: LFS thresholds per backend
Files larger than 100 MB SHALL be tracked with git-lfs in GitLab mode. GitHub mode SHALL track files larger than 50 MB and SHALL always regenerate tracking patterns on a reused output directory (so files between 50 MB and 100 MB are still picked up). LFS object uploads SHALL use a concurrent worker loop capped to 8 workers with the same retry policy; the LFS upload command MUST be distinct from the push command.

#### Scenario: GitHub regenerates patterns
- **WHEN** a reused OUTDIR is published in github mode
- **THEN** tracking patterns are regenerated and 50-100 MB files are tracked

### Requirement: Repo naming and paths
GitLab backends SHALL create a manufacturer subgroup, then a project named by codename under it, remote `git@{instance}:{group}/{manufacturer}/{codename}.git`; GitHub backends SHALL create a single repo `"{codename}_dump"` (spaces -> `-`), remote `git@github.com:{org}/{repo}.git`. Manufacturer and repo metadata SHALL drive subgroup/project naming exactly as current behavior.

#### Scenario: GitLab group layout
- **WHEN** a gitlab push runs for manufacturer `Xiaomi`, codename `chopin`
- **THEN** the remote path is `group/Xiaomi/chopin` with public subgroup visibility

#### Scenario: GitHub flat naming
- **WHEN** a github push runs for codename `X6878`
- **THEN** the repo name is `X6878_dump` with original casing preserved

### Requirement: Telegram notification hook
After a successful push, the pipeline SHALL send the Telegram dump-card (blockquote header, brand, model, platform, build, version, kernel, security patch, fingerprint, vendor names, tree link) to `TG_CHAT` (default `@DumprXDumps`), using HTML parse mode. A nil `TG_TOKEN` SHALL skip notification silently. Notification failure SHALL NOT fail the pipeline.

#### Scenario: Notification after push
- **WHEN** a gitlab or github push succeeds and `TG_TOKEN` is set
- **THEN** the formatted dump card is posted to the channel

#### Scenario: Notification failure tolerated
- **WHEN** the Telegram API call fails
- **THEN** the error is logged and the pipeline still exits successfully

### Requirement: Credential and config requirements
GitLab mode SHALL require `GITLAB_TOKEN`; GitHub mode SHALL require `GITHUB_TOKEN`. When missing, the backend SHALL abort with an instructive error naming the missing variable and the `.dumprxenv` file to fill. Optional `GITLAB_GROUP` / `GITHUB_ORG` SHALL default to the authenticated user.

#### Scenario: Credential default to authenticated user
- **WHEN** `GITLAB_GROUP` or `GITHUB_ORG` is empty
- **THEN** the backend derives org/group from the authenticated account