"""Configuration: env, paths, partition tables, frozen dataclasses."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]

PARTITIONS = """system system_ext systemex system_other system_dlkm
vendor vendor_dlkm vendor_boot vendor_kernel_boot
product product_h
odm odm_dlkm odmko
boot init_boot recovery dtbo dtb modem tz vbmeta
cust oem factory xrom hw_product mi_ext
oppo_product opproduct preload preload_common special_preload
my_preload my_odm my_stock my_operator my_country my_product my_company
my_engineering my_heytap my_custom my_manifest my_carrier my_region
my_bigball my_version
tr_product tr_region tr_carrier tr_mi tr_preload tr_company tr_system
tr_overlayfs tr_theme tr_manifest tr_misc
preas preavs reserve version nt_log socko india""".split()

NO_FS_PARTITIONS = {"boot", "init_boot", "recovery", "dtbo", "vendor_boot", "tz", "vbmeta"}

EXT4_PARTITIONS = (
    "system vendor cust odm oem factory product xrom systemex oppo_product "
    "preload_common hw_product product_h preas preavs"
).split()

OTHER_PARTITIONS = {
    "tz.mbn": "tz",
    "tz.img": "tz",
    "modem.img": "modem",
    "NON-HLOS": "modem",
    "boot-verified.img": "boot",
    "recovery-verified.img": "recovery",
    "dtbo-verified.img": "dtbo",
    "vbmeta-verified.img": "vbmeta",
}

_EXPORT_RE = re.compile(r'^[ \t]*export[ \t]+([A-Za-z_][A-Za-z0-9_]*)=(.*)$')
_ENV_LINE_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$')

_FILESYSTEM_EXTRACT_DIRS = ("system_ext", "product", "tr_product", "tr_region")


def _strip_value(raw: str) -> str:
    """Strip shell quoting from an env line value."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1]
    return raw.replace('\\"', '"').replace("\\'", "'")


def load_env_file(path: Path) -> dict[str, str]:
    """Parse a `.dumprxenv`-style file (export KEY=value or KEY=value) into a dict."""
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return env
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _EXPORT_RE.match(stripped) or _ENV_LINE_RE.match(stripped)
        if match:
            env[match.group(1)] = _strip_value(match.group(2))
    return env


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _log_level() -> str:
    return os.environ.get("DUMPRX_LOG_LEVEL", "DEBUG").upper()


def _nproc() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 4


@dataclass(frozen=True)
class Secrets:
    """Credentials from .dumprxenv. repr/str redact all values."""

    gitlab_token: str = ""
    gitlab_instance: str = "gitlab.com"
    gitlab_group: str = ""
    github_token: str = ""
    github_org: str = ""
    tg_token: str = ""
    tg_chat: str = ""

    def __repr__(self) -> str:
        return "Secrets(redacted)"

    def as_log_safe_dict(self) -> dict[str, str]:
        """Names only, for debug output - never values."""
        return {
            "gitlab_instance": self.gitlab_instance,
            "gitlab_group": self.gitlab_group or "(unset)",
            "github_org": self.github_org or "(unset)",
            "tg_chat": self.tg_chat or "(unset)",
            "has_gitlab_token": bool(self.gitlab_token),
            "has_github_token": bool(self.github_token),
            "has_tg_token": bool(self.tg_token),
        }


@dataclass(frozen=True)
class Paths:
    """All filesystem locations the pipeline touches."""

    project_dir: Path
    inputdir: Path
    utilsdir: Path
    outdir: Path = Path("/tmp/out")
    workdir: Path = Path("/tmp/out/tmp")

    @property
    def log_path(self) -> Path:
        return self.workdir / "dumprx.log"


@dataclass(frozen=True)
class Settings:
    """Static launch settings: CLI-derived values plus defaults."""

    mode: str = "gitlab"
    visibility: str = "private"
    push_only: bool = False
    readme_only: bool = False
    jobs: int = 4
    log_level: str = "DEBUG"


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration bundle."""

    paths: Paths
    settings: Settings
    secrets: Secrets = field(default_factory=Secrets)

    @property
    def env(self) -> dict[str, str]:
        return self.secrets.as_log_safe_dict()

    def with_secrets(self, secrets: Secrets) -> "Config":
        return replace(self, secrets=secrets)

    def with_paths(self, paths: Paths) -> "Config":
        return replace(self, paths=paths)


def build_config(
    *,
    mode: str = "gitlab",
    visibility: str = "private",
    push_only: bool = False,
    readme_only: bool = False,
    jobs: int | None = None,
    log_level: str | None = None,
    outdir: Path | None = None,
    project_dir: Path = PROJECT_DIR,
) -> Config:
    """Assemble a Config from CLI args plus `.dumprxenv` and the environment."""
    inputdir = project_dir / "input"
    utilsdir = project_dir / "utils"
    resolved_outdir = outdir or Path("/tmp/out")
    paths = Paths(
        project_dir=project_dir,
        inputdir=inputdir,
        utilsdir=utilsdir,
        outdir=resolved_outdir,
        workdir=resolved_outdir / "tmp",
    )
    env = load_env_file(project_dir / ".dumprxenv")
    secrets = Secrets(
        gitlab_token=env.get("GITLAB_TOKEN") or os.environ.get("GITLAB_TOKEN", ""),
        gitlab_instance=env.get("GITLAB_INSTANCE") or os.environ.get("GITLAB_INSTANCE", "gitlab.com"),
        gitlab_group=env.get("GITLAB_GROUP") or os.environ.get("GITLAB_GROUP", ""),
        github_token=env.get("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN", ""),
        github_org=env.get("GITHUB_ORG") or os.environ.get("GITHUB_ORG", ""),
        tg_token=env.get("TG_TOKEN") or os.environ.get("TG_TOKEN", ""),
        tg_chat=env.get("TG_CHAT") or os.environ.get("TG_CHAT", ""),
    )
    if not secrets.gitlab_instance:
        secrets = Secrets(**{**secrets.__dict__, "gitlab_instance": "gitlab.com"})

    settings = Settings(
        mode=mode,
        visibility=visibility,
        push_only=push_only,
        readme_only=readme_only,
        jobs=jobs or _int_env("DUMPRX_JOBS", _nproc()),
        log_level=(log_level or _log_level()),
    )
    return Config(paths=paths, settings=settings, secrets=secrets)
