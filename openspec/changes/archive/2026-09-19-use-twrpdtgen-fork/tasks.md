## 1. Vendored fork package

- [x] 1.1 Vendor `src/twrpdtgen/` from `ardiandideyashidiq/twrpdtgen` master (record source commit; keep every Apache-2.0 SPDX header, drop the fork's `pyproject.toml`/`poetry.lock`) and verify `uv run python -c "import twrpdtgen"` imports under the dumprx venv
- [x] 1.2 Set `module-name = ["dumprx", "twrpdtgen"]` under `[tool.uv]` in `pyproject.toml` and add `sebaubuntu-libs` + `jinja2` to runtime deps; verify `uv lock` and `uv sync` succeed and both `dumprx` and `twrpdtgen` import
- [x] 1.3 Trim the fork: remove the `--git`/GitPython flow (`main.py` arg + the `Repo` block in `device_tree.py`) and replace `sebaubuntu_libs.liblogging` `LOGD` calls with loguru `logger.debug`; verify `gitpython`/`libaik`/`liblogging` are never imported and `uv run ruff check src/twrpdtgen` passes

## 2. mkbootimg unpacker

- [x] 2.1 Vendor AOSP `mkbootimg.py` + `unpack_bootimg.py` into `utils/bin/` (Apache-2.0, mirroring the `avbtool.py` pattern) and register in `src/dumprx/tools.py`; verify `unpack_bootimg` decodes a real `boot.img` fixture with the full header print
- [x] 2.2 Replace `AIKManager().unpackimg` in the fork's `DeviceTree` with a mkbootimg-backed unpack module returning the `image_info` surface (decompressed `ramdisk`, `kernel`/`dt`/`dtb`/`dtbo`, `header_version`, `base_address`, `cmdline`, `pagesize`, `ramdisk_offset`, `tags_offset`, `origsize`, `ramdisk_compression`, best-effort `sigtype`); verify the ramdisk assertion passes on both a v2 boot image and a v3/v4 vendor_boot image

## 3. Adaptive selection and library wiring

- [x] 3.1 Implement adaptive image selection in the fork (`recovery.img` > `vendor_boot.img` > `init_boot.img` > `boot.img`) with metadata (dtb/cmdline/addresses) merged from auxiliary images; verify selection picks vendor_boot for a GKI set and recovery for a legacy set
- [x] 3.2 Rewrite `twrp.py` to import the vendored `DeviceTree`, feed it the OUTDIR image set, dump into `twrp-device-tree/`, keep wiki README fetch and `.git` removal, and log-fail best-effort; update `tests/test_output.py` twrp mocks to stub the vendored `DeviceTree` and verify `uv run pytest tests/test_output.py` is green
- [x] 3.3 Change the `cli.py:183` handoff from the `is_ab` boolean to the image-set handoff; verify the cli integration test asserting generation call order passes

## 4. Docs and compliance

- [x] 4.1 Update `AGENTS.md` (repo structure, vendored fork source commit, "updating the fork" note) and README (twrpdtgen fork provenance + `unpack_bootimg` tooling); verify `git status --short` shows only intended files
- [x] 4.2 Run `uv run ruff check src/dumprx src/twrpdtgen tests` and `uv run pytest`; verify both pass