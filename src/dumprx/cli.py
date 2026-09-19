"""DumprX console entry point: full flag parity with dumper.sh.

Pipeline order (bash): pipeline -> props -> readme -> twrp -> publisher ->
notify. `--push-only` skips extraction, `--readme-only` stops after README.
Mode defaults to `gitlab` (the bash default), visibility to `private`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import rich_click as click
from loguru import logger

from dumprx.config import build_config
from dumprx.downloader import DownloadError, download_into
from dumprx.extractors.base import StageLimitError, WorkContext
from dumprx.logger import bootstrap
from dumprx.pipeline import install_cleanup, run_pipeline
from dumprx.process import ProcessError
from dumprx.props.models import FirmwareInfo, derive
from dumprx.props.propper import PropStore
from dumprx.publishers.base import commit_local, init_repo
from dumprx.readme import build_tg_html, write_readme
from dumprx.redundancy import lookup, record, sha256_stream
from dumprx.resolution import ResolutionError, resolve_source
from dumprx.setup import run_setup, setup_complete
from dumprx.tools import Tools
from dumprx.twrp import generate as generate_twrp

_MODE_LABELS = ("local", "gitlab", "github")
_URL_PREFIXES = ("http://", "https://")


class PropError(RuntimeError):
    pass


@click.command(
    "dumprx",
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Dump Android firmware: extract, parse, generate README, and publish.",
)
@click.argument(
    "firmware",
    required=False,
    metavar="Firmware File/Extracted Folder -OR- URL",
)
@click.option(
    "-p",
    "--push-only",
    is_flag=True,
    help="Push only (skip extraction)",
)
@click.option(
    "-r",
    "--readme-only",
    is_flag=True,
    help="Generate README.md only (skip extraction)",
)
@click.option(
    "-m",
    "--mode",
    "mode",
    type=click.Choice(_MODE_LABELS),
    default="gitlab",
    help="Choose output mode (default: gitlab)",
)
@click.option("-g", "--gitlab", "mode", flag_value="gitlab", help="Shortcut for --mode gitlab")
@click.option("-b", "--github", "mode", flag_value="github", help="Shortcut for --mode github")
@click.option("-l", "--local", "mode", flag_value="local", help="Shortcut for --mode local")
@click.option(
    "--public",
    "visibility",
    flag_value="public",
    default="private",
    help="Create repo as public (default: private)",
)
@click.option("--setup", is_flag=True, help="Run setup and exit (first-run auto-runs it)")
@click.option("--no-setup", is_flag=True, help="Skip the auto-run setup check")
@click.option(
    "-o",
    "--output",
    "output",
    type=click.Path(path_type=Path),
    default=None,
    help="Dump output directory (default: /tmp/out)",
)
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    default=False,
    help="Re-dump even if this firmware was already dumped on this machine",
)
@click.option_panel("Mode", options=["-m", "--gitlab", "--github", "--local", "--public"])
@click.option_panel("Setup", options=["--setup", "--no-setup"])
@click.option_panel("Pipeline", options=["--push-only", "--readme-only"])
@click.option_panel("Output", options=["--output"])
def cli(
    firmware: str | None,
    mode: str,
    visibility: str,
    push_only: bool,
    readme_only: bool,
    setup: bool,
    no_setup: bool,
    output: Path | None,
    force: bool,
) -> int:
    """Dump firmware, or run/ensure device setup."""
    config = build_config(
        mode=mode,
        visibility=visibility,
        push_only=push_only,
        readme_only=readme_only,
        outdir=output,
        force=force,
    )
    bootstrap(level=config.settings.log_level, log_file=config.paths.log_path)
    logger.info("DumprX started: mode={} visibility={}", mode, visibility)

    if setup:
        return run_setup(config, explicit=True)

    if not no_setup and not setup_complete():
        run_setup(config, explicit=False)

    digest = ""

    if not push_only and not readme_only:
        if not firmware:
            logger.error("No Input Is Given. Pass a firmware file, folder, or website link.")
            return 1
        try:
            source = _resolve_input(firmware, config)
            resolved = resolve_source(source, config)
            logger.info("resolved source: {} ({})", resolved.path, resolved.kind)
            if resolved.path is not None and resolved.path.is_file():
                digest = sha256_stream(resolved.path)
                if digest and not force and lookup(digest):
                    logger.info(
                        "firmware already dumped on this machine; re-run with --force to redo"
                    )
                    return 0
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

    if readme_only:
        logger.info("README.md generated. Skipping Tree generation & Pushing.")
        return 0

    generate_twrp(config, is_ab=info.is_ab == "true")

    branch = init_repo(config.paths.outdir, info.branch, fallback_branch=info.incremental)
    try:
        commit_local(
            config.paths.outdir,
            info.description,
            mode="gitlab" if mode == "local" else mode,
            branch=branch,
        )
    except BaseException as exc:  # noqa: BLE001 - commit failures surface as messages
        logger.error("local commit failed: {}", exc)
        return 1

    if mode == "local":
        record(digest, outdir=config.paths.outdir, mode=mode, info=info)
        logger.info(
            "local mode: dump ready at {} (git committed, push-ready)", config.paths.outdir
        )
        return 0

    from dumprx.publishers import publish

    try:
        tree_url = publish(config, info, branch)
    except BaseException as exc:  # noqa: BLE001 - publisher failures surface as messages
        logger.error(
            "publish failed: {} (local commits preserved at {})",
            exc,
            config.paths.outdir,
        )
        return 1
    record(digest, outdir=config.paths.outdir, mode=mode, info=info)
    _notify(config, info, tree_url, mode)

    return 0


def _make_context(config) -> WorkContext:
    config.paths.workdir.mkdir(parents=True, exist_ok=True)
    return WorkContext(
        source=config.paths.workdir,
        outdir=config.paths.outdir,
        workdir=config.paths.workdir,
        config=config,
    )


def _resolve_input(given: str, config) -> Path:
    """Download remote URLs into INPUTDIR; otherwise use the local path."""
    given = given.strip()
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
    """Console-script entry: exit-code contract preserved for `dumprx`."""
    try:
        return cli(args=list(argv) if argv is not None else None, standalone_mode=False, prog_name="dumprx")
    except click.exceptions.Exit as exc:
        return exc.exit_code or 0
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
