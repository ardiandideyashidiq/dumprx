## Context

Today the git path is owned entirely by publishers and gated on mode (see proposal.md — Why). `commit_and_push` (src/dumprx/publishers/base.py) interleaves a staged commit with a `retry_push` at every stage, and `cli.py` calls a publisher only for `--mode gitlab|github`. Local mode leaves a loose folder; gitlab/github with a missing token abort before any commit exists. The commit sequence and its ordering are already spec'd as the single `commit_and_push` entry point, so the refactor must preserve that ordering while decoupling commits from pushes.

## Goals / Non-Goals

**Goals:**
- Every completed dump (all modes, `--push-only` included) is a git repo in OUTDIR with the staged commit graph.
- Publishers push only; commit staging logic is shared and lives once.
- Token-missing and already-dumped aborts leave the committed repo intact.
- Local mode uses gitlab's 100 MB LFS threshold so a later `git remote add` + `git push` needs no commit work.

**Non-Goals:**
- Per-commit incremental push / resumability (commits are all local before push; a single branch push covers them).
- Changing `--readme-only` (still stops before git work) or branch/identity derivation.
- Solving git-lfs-not-installed environments (pre-existing caveat, unchanged).

## Decisions

**Split `commit_and_push` into `commit_local` + `push_all` (base.py).**
`commit_local(outdir, description, *, mode, branch)` runs today's staged sequence with every `retry_push`/`push_lfs_objects` call removed: README, LFS setup, APKs, partition groups, extras. `push_all(outdir, branch)` runs the push side: `retry_push("-u", "origin", branch)` then `push_lfs_objects(outdir)`. The partition-group iteration stays a single shared helper so ordering can't drift.
- *Alternative rejected:* a `push: bool` flag on `commit_and_push`. It keeps publishers committing, which fights the requirement that commits always happen before dispatch and makes the "always" guarantee a failure-fallback, not a structure.

**CLI runs `init_repo` + `commit_local` before the mode dispatch (cli.py).**
```
branch   = init_repo(outdir, info.branch, fallback_branch=info.incremental)
commit_local(outdir, info.description, mode=lfs_mode, branch=branch)
if mode == "local": log "dump ready (git committed, push-ready)"; exit 0
else: tree_url = publish(config, info, branch); _notify(...)
```
`lfs_mode` maps local → "gitlab" (100 MB thresholds). Publishers receive the already-effective branch and drop their own `init_repo` call (re-initing after the CLI would be duplicate work).
- *Alternative rejected:* publishers keep committing and the CLI handles missing-token via a post-failure fallback commit. Risky on mid-push crashes (double commit → "nothing to commit") and leaves the guarantee unenforced.

**Publishers become push-only (gitlab.py, github.py).**
Each keeps the order: token check → `_already_dumped` check → repo/subgroup API → `git remote add origin ...` → `push_all(outdir, branch)` → metadata/default-branch PATCHes. Token-missing and already-dumped raise `PushError` after the CLI already committed, so the abort message notes the dump remains committed at OUTDIR. The first push uses `-u origin branch` (the branch is freshly created; `-f` from the old README-only first push is no longer needed, and the already-dumped check guards non-fast-forward).

**`commit_local` skips empty stages instead of failing.**
Each stage: `git add <stage>` then `git diff --cached --quiet`; commit only when something was staged. This makes `--push-only` and reused OUTDIRs work — today an unchanged stage would die on `nothing to commit`, breaking re-publish.

## Risks / Trade-offs

- **Single push vs per-stage pushes** — a very large dump is now one long SSH/HTTP transfer instead of several small ones. → `retry_push` still wraps it with 5 attempts; the object set is identical, so wire cost is the same; only progress granularity changes. If it ever regresses, pushing per-commit can be revived inside `push_all` without spec changes.
- **Unchanged-stage commits now silently skipped instead of erroring** — previously a re-push of an unchanged OUTDIR failed loudly. → Desired for reuse; the `already-dumped` check still prevents accidental remote duplication.
- **LFS pointers committed locally without objects** — pushes depend on `push_lfs_objects` uploading the objects afterwards; a push that stops between branch and LFS leaves remote pointers without blobs. → Ordering is branch-then-LFS in `push_all`; retries cover transient failures; a re-run's `push_lfs_objects` re-uploads every oid.
- **Test churn** — publisher tests mock `commit_and_push`/`init_repo`; they must now mock `push_all` and assert the CLI-level commit. → Contained to `test_publishers.py`/`test_cli.py`.

## Migration Plan

Behavior change is local-only and additive: existing remote pushes keep the same commit graph (the graph is built identically, just earlier). Rollback is a revert of the split (revert commit_local/push_all and the cli wiring). No config, env, or data migrations.