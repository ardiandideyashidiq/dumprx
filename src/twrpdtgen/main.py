#
# Copyright (C) 2022 The Android Open Source Project
#
# SPDX-License-Identifier: Apache-2.0
#

import sys
from argparse import ArgumentParser
from pathlib import Path

from loguru import logger

from twrpdtgen import __version__ as version
from twrpdtgen import current_path
from twrpdtgen.device_tree import DeviceTree


def main():
	print(f"TWRP device tree generator\n"
	      f"Version {version}\n")

	parser = ArgumentParser(prog='python3 -m twrpdtgen')

	# Main DeviceTree arguments
	parser.add_argument("image", type=Path,
						help="path to an image (recovery image, vendor_boot image or boot image if the device is A/B)")
	parser.add_argument("-o", "--output", type=Path, default=current_path / "output",
						help="custom output folder")

	# Logging
	parser.add_argument("-d", "--debug", action='store_true',
						help="enable debugging features")

	args = parser.parse_args()

	if args.debug:
		logger.remove()
		logger.add(sys.stderr, level="DEBUG")

	device_tree = DeviceTree(images=[args.image])
	folder = device_tree.dump_to_folder(args.output)

	print(f"\nDone! You can find the device tree in {folder}")
