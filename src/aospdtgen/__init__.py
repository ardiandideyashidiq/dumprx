#
# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#
# Vendored from sebaubuntu-python/aospdtgen @ v1.2.1 (dumprx-specific fork)
#   https://github.com/sebaubuntu-python/aospdtgen
#   source commit: ff16bea7aabf8133affd9772e12651640712ae9a
# Changes on top of upstream since that commit live only here: the AIK image
# unpacking in utils/boot_configuration.py is replaced with the vendored
# twrpdtgen.image_info unpacker (no runtime AIK clone, GKI-capable), and the
# stand-alone get_vndk_libs.py regeneration script was deleted. Re-vendor by
# re-applying them to a newer upstream checkout (see AGENTS.md "Vendored code").
#
"""aospdtgen module."""

from pathlib import Path

from aospdtgen.proprietary_files.section import register_sections

__version__ = "1.2.1"

module_path = Path(__file__).parent
sections_path = module_path / "proprietary_files" / "sections"
current_path = Path.cwd()

register_sections(sections_path)
