## 1. Split commit/push helpers in base.py

- [x] 1.1 Factor `commit_local(outdir, description, *, mode, branch)` out of `commit_and_push` in `src/dumprx/publishers/base.py`: staged commits only (README, LFS setup, APKs, partition groups, extras) in the current order, each stage committing only when `git diff --cached --quiet` reports unstaged work; verify the shared partition-group iteration is preserved and no `retry_push`/`push_lfs_objects` call remains in the commit path
- [x] 1.2 Add `push_all(outdir, branch)`: `retry_push(outdir, "-u", "origin", branch)` then `push_lfs_objects(outdir)`; verify it surfaces the existing 5-attempt retry and 8-worker LFS uploads unchanged
- [x] 1.3 Remove `commit_and_push`, update `__all__` and the module docstring to `commit_local`/`push_all`, and update the import in `tests/test_publishers.py`; verify `uv run ruff check src/dumprx tests`

## 2. Always init + commit in the CLI

- [x] 2.1 In `src/dumprx/cli.py`, before the mode dispatch run `init_repo(outdir, info.branch, fallback_branch=info.incremental)` then `commit_local(outdir, info.description, mode="gitlab" if local else mode, branch=branch)` for all modes including `--push-only`; verify the local phase-order test now also records the commit step
- [x] 2.2 Update the local-mode branch to log the dump as git-committed and push-ready (no remote added, no notify); verify the `_make_info`/twrp ordering is unchanged and `--readme-only` still stops before any git work
- [x] 2.3 Confirm `init_repo` idempotency is no longer relied on by publishers (they now receive the effective branch) and verify the returned fallback branch propagates to `publish`

## 3. Make publishers push-only

- [x] 3.1 Update `src/dumprx/publishers/gitlab.py`: drop `init_repo`, keep token check (abort message notes the dump is committed locally at OUTDIR), keep `_already_dumped` + subgroup/project API, then `git remote add origin` + `push_all(outdir, branch)` + the existing metadata/default-branch PATCHes; verify the API-sequence test passes
- [x] 3.2 Update `src/dumprx/publishers/github.py` the same way (`_dump` repo creation, remote add, `push_all`, visibility/default-branch PATCHes); verify github API-sequence and user-scoped tests pass
- [x] 3.3 Update `tests/test_publishers.py` mocks from `commit_and_push`/`init_repo` to `push_all` and assert token-missing publish still raises `PushError`; verify all publisher tests green

## 4. Tests for local commits

- [x] 4.1 Add a `commit_local` unit test asserting the exact stage order (README, LFS/`.gitattributes`, APKs, partition groups, extras) and the empty-stage skip via `git diff --cached --quiet`; verify it passes
- [x] 4.2 Add a CLI test asserting local mode calls `init_repo` + `commit_local` and exits 0 with no remote/notify; add a gitlab-without-token test asserting the committed dump survives the abort; verify `uv run pytest`

## 5. Docs and final checks

- [x] 5.1 Update README to state that every dump is a git repository with staged commits by default (local mode included) and that a missing token still leaves a push-ready repo; verify no `.dumprxenv.example` change is needed
- [x] 5.2 Run `uv run ruff check src/dumprx tests` and `uv run pytest`; verify both pass and `git status --short` shows only intended changes