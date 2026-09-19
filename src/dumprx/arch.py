"""7zz archive layer: one-shot file-backed listing + tolerant extraction.

The listing is written once to a work-dir file (never accumulated in RAM) and
re-read lazily across all extractors, mirroring the cached ARCHIVE_LISTING in
dumper.sh. Extraction mirrors the `-y` tolerant semantics (missing members
and the `dummypartition` sentinel are non-fatal).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from pathlib import Path

from loguru import logger

from dumprx.process import run

_DUMMY_MEMBER = "dummypartition"


class Archive:
    """A single archive file with a lazy, file-backed 7zz listing."""

    def __init__(self, file: Path, listing_file: Path | None = None) -> None:
        self.file = file
        self.listing_file = listing_file
        self._lines: list[str] | None = None

    def write_listing(self, seven_zz: str) -> "Archive":
        """Capture `7zz l -ba` output into listing_file (or memory cache)."""
        res = run([seven_zz, "l", "-ba", str(self.file)], capture=True)
        text = res.stdout.decode("utf-8", errors="replace")
        if self.listing_file is not None:
            self.listing_file.write_text(text, encoding="utf-8", errors="replace")
        self._lines = text.splitlines()
        logger.debug("archive {}: {} listing entries", self.file.name, len(self._lines))
        return self

    def entries(self) -> Iterator[str]:
        """Yield every listing line lazily."""
        if self._lines is not None:
            yield from self._lines
            return
        if self.listing_file is not None and self.listing_file.is_file():
            with self.listing_file.open(encoding="utf-8", errors="replace") as fh:
                yield from fh
            return
        yield from ()

    def member_names(self) -> list[str]:
        """Last whitespace-token of each non-empty entry line, like `gawk $NF`."""
        names: list[str] = []
        for line in self.entries():
            stripped = line.strip()
            if not stripped:
                continue
            names.append(stripped.split()[-1])
        return names

    def has(self, pattern: str) -> bool:
        return any(re.search(pattern, line) for line in self.entries())

    def matched_names(self, pattern: str) -> list[str]:
        return [line.split()[-1] for line in self.entries() if re.search(pattern, line)]

    def extract(
        self,
        seven_zz: str,
        dest: Path,
        members: Iterable[str] | None = None,
        flat: bool = True,
        *,
        log_to: str | None = None,
    ) -> bool:
        """Extract members (default: everything) into dest tolerantly.

        `flat=True` uses `7zz e` (strip paths) plus a path-variant member for
        each requested token, exactly like the dumper.sh two-arm member lists.
        Returns True when 7zz reports success (missing members tolerated).
        """
        dest.mkdir(parents=True, exist_ok=True)
        mode = "e" if flat else "x"
        argv = [seven_zz, "-y", mode, str(self.file)]
        if flat:
            argv.append(f"-o{str(dest)}")
        else:
            argv.append(f"-o{str(dest)}")
        member_args: list[str] = []
        if members is not None:
            member_list = list(members)
            for member in member_list:
                member_args.append(member)
                if flat and member != _DUMMY_MEMBER and not member.startswith("*"):
                    member_args.append(f"*/{member}")
            member_args.append(_DUMMY_MEMBER)
        argv.extend(member_args)
        logger.debug("7zz extract {} members={} flat={}", self.file.name, len(member_args), flat)
        res = run(argv, capture=True)
        if res.returncode != 0:
            logger.warning(
                "7zz extract returned {} for {} (members {} tolerated)",
                res.returncode,
                self.file.name,
                member_args[:3],
            )
        return res.ok

    def extract_all(self, seven_zz: str, dest: Path, flat: bool = False) -> bool:
        return self.extract(seven_zz, dest, members=None, flat=flat)


__all__ = ["Archive"]
