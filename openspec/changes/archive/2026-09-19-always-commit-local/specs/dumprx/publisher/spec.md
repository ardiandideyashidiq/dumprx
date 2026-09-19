## MODIFIED Requirements

### Requirement: Backend interface
A publisher SHALL expose repo creation, repo metadata (visibility, description), default-branch update, and a push operation. Selecting a mode selects the backend (gitlab -> gitlab backend, github -> github backend, local -> no publisher and no notification). All modes SHALL have their dump committed to a local git repo in OUTDIR BEFORE any backend (if one runs) is dispatched.

#### Scenario: GitLab mode selects gitlab backend
- **WHEN** `--mode gitlab` runs with valid credentials
- **THEN** the dump is committed locally first, then the gitlab backend performs all remote delivery

#### Scenario: Local mode skips publishing
- **WHEN** `--mode local` completes a dump
- **THEN** OUTDIR is initialized as a git repo containing the staged commits, no remote is added, no remote call occurs, and no Telegram notification is sent

#### Scenario: Local mode dump is push-ready
- **WHEN** a remote is added to a locally committed dump
- **THEN** pushing the existing branch uploads the dump without further local commits

### Requirement: Already-dumped short-circuit
Before any remote API write or push, the active backend SHALL check the remote for an existing `all_files.txt` on the target branch; if present, it MUST abort with a message pointing at the existing tree. Local commits made before dispatch SHALL remain unaffected.

#### Scenario: Firmware already dumped
- **WHEN** remote `all_files.txt` already exists on the branch
- **THEN** the pipeline aborts with the existing-tree URL, skips all remote writes, and the local committed repo in OUTDIR is left intact

### Requirement: Staged commit order
The shared commit flow SHALL commit in this exact order, one commit per stage, matching `dumper.sh`: README.md, `.gitattributes` LFS setup, all `*.apk`, partition group dirs (system_ext, product, system_dlkm, odm, odm_dlkm, init_boot, vendor_boot, vendor_dlkm, vendor, system, tr_product, tr_region, with `system/` and `system/system/` prefixes), then remaining extras. The commit flow SHALL run locally for every mode — including `--mode local` and `--push-only` — independent of credentials. Push SHALL be a separate step (branch push plus LFS object uploads) that SHALL retry up to 5 attempts with a delay before failing. A push SHALL succeed on an already-committed repo without rerunning the commit stages.

#### Scenario: Commit sequence preserved
- **WHEN** a full dump is published
- **THEN** remote history contains the staged commits in the documented order

#### Scenario: Every mode produces the staged commit graph
- **WHEN** a dump completes in any mode (local, gitlab, github)
- **THEN** OUTDIR contains one commit per documented stage in the documented order

#### Scenario: Push retry
- **WHEN** a push fails transiently
- **THEN** the flow retries up to 5 times with delay before aborting

#### Scenario: Push without new commits
- **WHEN** a backend receives an already-committed repo
- **THEN** the branch pushes successfully without rerunning commit stages

### Requirement: LFS thresholds per backend
Files larger than 100 MB SHALL be tracked with git-lfs in GitLab and local modes. GitHub mode SHALL track files larger than 50 MB and SHALL always regenerate tracking patterns on a reused output directory (so files between 50 MB and 100 MB are still picked up). LFS object uploads SHALL use a concurrent worker loop capped to 8 workers with the same retry policy; the LFS upload command MUST be distinct from the push command.

#### Scenario: Local mode tracks large files
- **WHEN** `--mode local` commits a dump containing a file larger than 100 MB
- **THEN** the file is tracked via `.gitattributes` and committed as an LFS pointer

#### Scenario: GitHub regenerates patterns
- **WHEN** a reused OUTDIR is published in github mode
- **THEN** tracking patterns are regenerated and 50-100 MB files are tracked

### Requirement: Credential and config requirements
GitLab mode SHALL require `GITLAB_TOKEN`; GitHub mode SHALL require `GITHUB_TOKEN`. When missing, the backend SHALL abort with an instructive error naming the missing variable and the `.dumprxenv` file to fill. The abort SHALL occur after the dump is committed locally, so OUTDIR remains a push-ready git repo. Optional `GITLAB_GROUP` / `GITHUB_ORG` SHALL default to the authenticated user.

#### Scenario: Missing token still leaves committed dump
- **WHEN** `--mode gitlab` runs without `GITLAB_TOKEN`
- **THEN** the CLI aborts with an instructive error, OUTDIR contains the staged commits, and no remote API call or push occurs

#### Scenario: Credential default to authenticated user
- **WHEN** `GITLAB_GROUP` or `GITHUB_ORG` is empty
- **THEN** the backend derives org/group from the authenticated account