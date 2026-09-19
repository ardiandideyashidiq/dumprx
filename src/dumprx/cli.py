"""DumprX console entry point: full flag parity with dumper.sh.

Pipeline order (bash): pipeline -> props -> readme -> twrp -> publisher ->
notify. `--push-only` skips extraction, `--readme-only` stops after README.
Mode defaults to `gitlab` (the bash default), visibility to `private`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

from dumprx.config import build_config
from dumprx.downloader import DownloadError, download_into
from dumprx.extractors.base import StageLimitError, WorkContext
from dumprx.logger import bootstrap
from dumprx.pipeline import install_cleanup, run_pipeline
from dumprx.process import ProcessError
from dumprx.props.models import FirmwareInfo, derive
from dumprx.props.propper import PropStore
from dumprx.readme import build_tg_html, write_readme
from dumprx.resolution import ResolutionError, resolve_source
from dumprx.tools import Tools
from dumprx.twrp import generate as generate_twrp

_MODE_LABELS = ("local", "gitlab", "github")
_URL_PREFIXES = ("http://", "https://")


class PropError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dumprx",
        description="Dump Android firmware: extract, parse, generate README, and publish.",
        usage="dumprx [OPTIONS] <Firmware File/Extracted Folder -OR- Supported Website Link>",
    )
    parser.add_argument(
        "-p", "--push-only", action="store_true", help="Push only (Skip extraction)"
    )
    parser.add_argument(
        "-r", "--readme-only", action="store_true", help="Generate README.md only (Skip extraction)"
    )
    parser.add_argument(
        "-m",
        "--mode",
        dest="mode",
        choices=_MODE_LABELS,
        default="gitlab",
        help="Choose output mode (default: local)",
    )
    parser.add_argument(
        "-g", "--gitlab", dest="mode", action="store_const", const="gitlab",
        help="Shortcut for --mode gitlab",
    )
    parser.add_argument(
        "-b", "--github", dest="mode", action="store_const", const="github",
        help="Shortcut for --mode github",
    )
    parser.add_argument(
        "-l", "--local", dest="mode", action="store_const", const="local",
        help="Shortcut for --mode local",
    )
    parser.add_argument(
        "--public",
        dest="visibility",
        action="store_const",
        const="public",
        default="private",
        help="Create repo as public (default: private)",
    )
    parser.add_argument(
        "firmware",
        nargs="?",
        metavar="Firmware File/Extracted Folder -OR- URL",
        help="Input firmware archive, extracted folder, or supported download link",
    )
    return parser


def _make_context(config) -> WorkContext:
    config.paths.workdir.mkdir(parents=True, exist_ok=True)
    return WorkContext(
        source=config.paths.workdir,
        outdir=config.paths.outdir,
        workdir=config.paths.workdir,
        config=config,
    )


def _resolve_input(args: argparse.Namespace, config) -> Path:
    """Download remote URLs into INPUTDIR; otherwise use the local path."""
    given = args.firmware.strip()
    if given.startswith(_URL_PREFIXES):
        download_into(given, config.paths.inputdir, Tools(utilsdir=config.paths.utilsdir))
        logger.info("download finished; scanning {}", config.paths.inputdir)
        return config.paths.inputdir
    return Path(given)


def _make_info(config) -> FirmwareInfo:
    """PropStore + derive against OUTDIR; bash aborts when no build*.prop exists."""
    outdir = config.paths.outdir
    info = derive(outdir, PropStore(outdir))
    if not info.manufacturer and not info.codename and not info.description:
        raise PropError("No system/vendor/product build*.prop found, pushing cancelled.")
    return info


def _notify(config, info: FirmwareInfo, tree_url: str, mode: str) -> None:
    if not config.secrets.tg_token:
        return
    from dumprx.notify import send_tg_html

    label = "GitLab Tree" if mode == "gitlab" else "GitHub Tree"
    send_tg_html(build_tg_html(info, tree_url, label), config)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config = build_config(
        mode=args.mode,
        visibility=args.visibility,
        push_only=args.push_only,
        readme_only=args.readme_only,
    )
    bootstrap(level=config.settings.log_level, log_file=config.paths.log_path)
    logger.info("DumprX started: mode={} visibility={}", args.mode, args.visibility)

    if not args.push_only and not args.readme_only:
        if not args.firmware:
            logger.error("No Input Is Given. Pass a firmware file, folder, or website link.")
            return 1
        try:
            source = _resolve_input(args, config)
            resolved = resolve_source(source, config)
            logger.info("resolved source: {} ({})", resolved.path, resolved.kind)
            ctx = _make_context(config)
            ctx.source = resolved.path or ctx.workdir
            install_cleanup(ctx.workdir)
            run_pipeline(ctx)
        except (ResolutionError, DownloadError, ProcessError, StageLimitError) as exc:
            logger.error("pipeline failed: {}", exc)
            return 1

    try:
        info = _make_info(config)
    except PropError as exc:
        logger.error(str(exc))
        return 1

    readme_path = write_readme(config.paths.outdir, info)
    print(readme_path.read_text(encoding="utf-8"), end="")
    print(f"\nrepo: {info.manufacturer}/{info.codename}\n")

    if args.readme_only:
        logger.info("README.md generated. Skipping Tree generation & Pushing.")
        return 0

    generate_twrp(config, is_ab=info.is_ab == "true")

    if args.mode in ("gitlab", "github"):
        from dumprx.publishers import publish

        try:
            tree_url = publish(config, info, info.branch)
        except BaseException as exc:  # noqa: BLE001 - publisher failures surface as messages
            logger.error("publish failed: {}", exc)
            return 1
        _notify(config, info, tree_url, args.mode)
    else:
        logger.info("local mode: dump ready at {}", config.paths.outdir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
