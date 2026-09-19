## Why

`dumprx` currently leaves a loose folder in `OUTDIR` whenever it cannot or should not publish: `--mode local` never touches git, and gitlab/github mode aborts at the token check before any commit exists. A completed dump should always be a git repo with the staged commit graph in place, so it is push-ready the moment credentials arrive.

## What Changes

- **Always initialize and commit**: after TWRP generation, the CLI SHALL run `git init` + the staged commit sequence in `OUTDIR` for every mode (local, gitlab, github), including `--push-only`. The token-missing path therefore leaves a committed, push-ready dump instead of an empty abort.
- **BREAKING — publisher contract**: publishers become push-only. `commit_and_push` is split into a local commit step (staged commits only) and a push step (`git push` + LFS object upload). Backends no longer create commits; the CLI does, before dispatch.
- **Local mode commits**: `--mode local` SHALL produce the same git repo and commit graph (including git-lfs tracking of files > 100 MB) as gitlab mode, but with no remote added and no push.
- **`--readme-only` unchanged**: still a maintenance command that regenerates README.md and stops; no git work.
- **Branch/identity unchanged**: commits use the derived `info.branch` (fallback `info.incremental`) and the existing local `user.email`/`user.name` fallback.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `dumprx/publisher`: the backend interface, staged-commit-order, and credential requirements change so that (a) local mode produces a committed git repo, (b) staged commits always run locally before any push, and (c) backends push only, so a missing token still leaves the dump committed.

## Impact

- `src/dumprx/cli.py` — always run `init_repo` + local commit before the mode dispatch.
- `src/dumprx/publishers/base.py` — split `commit_and_push` into a commit-only helper plus a push helper (`git push` + `push_lfs_objects`).
- `src/dumprx/publishers/gitlab.py`, `github.py` — become push-only after token check / repo API / remote add; no commit staging.
- `tests/test_publishers.py`, `tests/test_cli.py` — update mocks and add local-commit scenarios.
- `README.md` — document that every dump is a git repository by default.