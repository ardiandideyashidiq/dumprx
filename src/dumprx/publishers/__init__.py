"""Publisher registry: mode name -> publish(config, info, branch) -> tree URL."""

from __future__ import annotations

from dumprx.config import Config
from dumprx.props.models import FirmwareInfo
from dumprx.publishers import github, gitlab
from dumprx.publishers.base import PushError

PUBLISHERS: dict[str, object] = {
    "gitlab": gitlab.publish,
    "github": github.publish,
}


def publish(config: Config, info: FirmwareInfo, branch: str) -> str:
    """Dispatch by config.settings.mode."""
    func = PUBLISHERS.get(config.settings.mode)
    if func is None:
        raise PushError(f"No publisher for mode '{config.settings.mode}'")
    return func(config, info, branch)


__all__ = ["PUBLISHERS", "PushError", "publish"]
