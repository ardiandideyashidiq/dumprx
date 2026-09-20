# DumprX

Android firmware dumper — extract, parse, and publish partition dumps. A revamped, maintained fork of [Dumpyara](https://github.com/AndroidDumps/) / [Phoenix Firmware Dumper](https://github.com/DroidDumps), rewritten as a Python package.

## Features

- Dumps firmware from files, folders, or direct URLs
- Downloads from filehosters (mega.nz, mediafire, AndroidFileHost, Google Drive)
- Extracts zip/7z/tar, kdz, ozip, ofp, ops, payload.bin, UPDATE.APP, nb0, super, and more
- Generates a device README plus device trees (TWRP/AOSP) from the dump
- Publishes dumps to GitLab or GitHub (private by default), with Telegram notifications
- Every dump is a local git repo, so it stays push-ready even without credentials

## Install

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install git+https://github.com/ardiandideyashidiq/dumprx
```

## Usage

```bash
dumprx 'Firmware File/Folder -OR- Supported Website Link'
```

Useful flags:

```bash
dumprx --local firmware.bin          # extract + README, no push (recommended first run)
dumprx --readme-only                 # regenerate README.md from existing OUTDIR
dumprx --push-only 'link-or-folder'  # skip extraction, push existing OUTDIR
dumprx -o /data/dumps firmware.bin   # write output under /data/dumps instead of /tmp/out
dumprx --setup                       # install prerequisites and record setup state
dumprx --no-setup firmware.bin       # skip the auto-run setup check
dumprx --force firmware.bin          # re-dump even if already dumped on this machine
dumprx --github --public firmware.bin
dumprx --help
```

Runs without `--setup` auto-run setup if the state file is missing or incomplete.

## Configuration

Copy `.dumprxenv.example` to `.dumprxenv` and fill in your tokens:

- `GITLAB_TOKEN` / `GITLAB_INSTANCE` / `GITLAB_GROUP` — GitLab pushes (default mode)
- `GITHUB_TOKEN` / `GITHUB_ORG` — GitHub pushes (`--github` mode)
- `TG_TOKEN` / `TG_CHAT` — Telegram notifications

## Credits

All credit for the underlying tools goes to the original authors:

- [Dumpyara](https://github.com/AndroidDumps/) / [Phoenix Firmware Dumper](https://github.com/DroidDumps) — original firmware dumper this is based on
- [sdat2img](https://github.com/xpirt/sdat2img) (xpirt), [payload-dumper](https://github.com/vm03/payload_dumper) tooling (cyxx), [twrpdtgen](https://github.com/ardiandideyashidiq/twrpdtgen) (SebastianoBarezzi), [aospdtgen](https://github.com/sebaubuntu-python/aospdtgen), plus bkerler (ozip/ofp/ops tools), IgorEisberg (unsin), nkk71 & CaptainThrowback (RUU), and everyone who contributed to the original toolkit.