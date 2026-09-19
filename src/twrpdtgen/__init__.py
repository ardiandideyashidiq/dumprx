#
# Copyright (C) 2022 The Android Open Source Project
#
# SPDX-License-Identifier: Apache-2.0
#
#
# Vendored from ardiandideyashidiq/twrpdtgen @ master (dumprx-specific fork)
#   https://github.com/ardiandideyashidiq/twrpdtgen
#   source commit: bd0badbe8e3e6eff96837f4da2a7d22a37de5094
# Changes on top of upstream since that commit live only here; re-vendor by
# re-applying them to a newer fork checkout (see AGENTS.md "Vendored code").
#

from pathlib import Path

__version__ = "3.0.0"

module_path = Path(__file__).parent
current_path = Path.cwd()
