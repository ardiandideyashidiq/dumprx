#
# Copyright (C) 2022 The Android Open Source Project
#
# SPDX-License-Identifier: Apache-2.0
#

from datetime import datetime
from os import chmod
from pathlib import Path
from shutil import copyfile, rmtree
from stat import S_IRGRP, S_IROTH, S_IRWXU
from typing import Any, List

from loguru import logger
from sebaubuntu_libs.libandroid.device_info import DeviceInfo
from sebaubuntu_libs.libandroid.fstab import Fstab
from sebaubuntu_libs.libandroid.props import BuildProp

from twrpdtgen import __version__ as version
from twrpdtgen.image_info import unpack_images
from twrpdtgen.templates import render_template

BUILDPROP_LOCATIONS = [Path() / "default.prop",
                       Path() / "prop.default",]
BUILDPROP_LOCATIONS += [Path() / dir / "build.prop"
                        for dir in ["system", "vendor"]]
BUILDPROP_LOCATIONS += [Path() / dir / "etc" / "build.prop"
                        for dir in ["system", "vendor"]]

FSTAB_LOCATIONS = [Path() / "etc" / "recovery.fstab"]
FSTAB_LOCATIONS += [Path() / dir / "etc" / "recovery.fstab"
                    for dir in ["system", "vendor"]]

INIT_RC_LOCATIONS = [Path()]
INIT_RC_LOCATIONS += [Path() / dir / "etc" / "init"
                      for dir in ["system", "vendor"]]

class DeviceTree:
	"""
	A class representing a device tree

	It initialize a basic device tree structure
	and save the location of some important files
	"""
	def __init__(self, images: List[Path], unpack_bootimg_tool: Path | None = None,
	             workdir: Path | None = None, dtbo: Path | None = None,
	             firmware_info: Any | None = None):
		"""Initialize the device tree class."""
		self.images = images

		self.current_year = str(datetime.now().year)

		# Check that the images exist
		if not images:
			raise FileNotFoundError("No image to unpack")
		for image in images:
			if not image.is_file():
				raise FileNotFoundError(f"Specified file doesn't exist: {image}")

		# Extract the best image and merge the auxiliary ones
		self.image_info = unpack_images(images=images,
		                                workdir=workdir or Path.cwd(),
		                                unpack_bootimg_tool=unpack_bootimg_tool)
		if dtbo is not None and self.image_info.dtbo is None:
			self.image_info.dtbo = dtbo

		assert self.image_info.ramdisk, "Ramdisk not found"

		logger.debug("Getting device infos...")
		self.build_prop = BuildProp()
		for build_prop in [self.image_info.ramdisk / location for location in BUILDPROP_LOCATIONS]:
			if not build_prop.is_file():
				continue

			self.build_prop.import_props(build_prop)

		self.device_info = DeviceInfo(self.build_prop)

		if firmware_info is not None:
			if getattr(firmware_info, "fingerprint", None):
				self.device_info.build_fingerprint = firmware_info.fingerprint
			if getattr(firmware_info, "description", None):
				self.device_info.build_description = firmware_info.description
			if getattr(firmware_info, "sec_patch", None):
				self.device_info.vendor_build_security_patch = firmware_info.sec_patch
				self.device_info.build_security_patch = firmware_info.sec_patch
			if getattr(firmware_info, "density", None) and firmware_info.density != "undefined":
				self.device_info.screen_density = firmware_info.density
			if getattr(firmware_info, "platform", None):
				self.device_info.platform = firmware_info.platform.lower()
			if getattr(firmware_info, "brand", None):
				self.device_info.brand = firmware_info.brand
			if getattr(firmware_info, "transname", None):
				self.device_info.model = firmware_info.transname

		mfr_prefix = f"{self.device_info.manufacturer.lower()}-"
		if self.device_info.codename.lower().startswith(mfr_prefix):
			self.device_info.codename = self.device_info.codename[len(mfr_prefix):]
		elif self.device_info.brand:
			brand_prefix = f"{self.device_info.brand.lower()}-"
			if self.device_info.codename.lower().startswith(brand_prefix):
				self.device_info.codename = self.device_info.codename[len(brand_prefix):]

		if self.device_info.bootloader_board_name and self.device_info.bootloader_board_name.lower().startswith(mfr_prefix):
			self.device_info.bootloader_board_name = self.device_info.bootloader_board_name[len(mfr_prefix):]

		logger.debug(
			"Device info resolved: manufacturer={}, codename={}, platform={}, fingerprint={}",
			self.device_info.manufacturer,
			self.device_info.codename,
			self.device_info.platform,
			self.device_info.build_fingerprint,
		)

		# Generate fstab
		fstab = None
		for fstab_location in [self.image_info.ramdisk / location for location in FSTAB_LOCATIONS]:
			if not fstab_location.is_file():
				continue

			logger.debug(f"Generating fstab using {fstab_location} as reference...")
			fstab = Fstab(fstab_location)
			break

		if fstab is None:
			raise AssertionError("fstab not found")

		self.fstab = fstab

		# Search for init rc files
		self.init_rcs: List[Path] = []
		for init_rc_path in [self.image_info.ramdisk / location for location in INIT_RC_LOCATIONS]:
			if not init_rc_path.is_dir():
				continue

			self.init_rcs += [init_rc for init_rc in init_rc_path.iterdir()
			                  if init_rc.name.endswith(".rc") and init_rc.name != "init.rc"]

	def dump_to_folder(self, output_path: Path) -> Path:
		device_tree_folder = output_path / self.device_info.manufacturer / self.device_info.codename
		prebuilt_path = device_tree_folder / "prebuilt"
		recovery_root_path = device_tree_folder / "recovery" / "root"

		logger.debug("Creating device tree folders...")
		if device_tree_folder.is_dir():
			rmtree(device_tree_folder, ignore_errors=True)
		device_tree_folder.mkdir(parents=True)
		prebuilt_path.mkdir(parents=True)
		recovery_root_path.mkdir(parents=True)

		logger.debug("Writing makefiles/blueprints")
		self._render_template(device_tree_folder, "Android.bp", comment_prefix="//")
		self._render_template(device_tree_folder, "Android.mk")
		self._render_template(device_tree_folder, "AndroidProducts.mk")
		self._render_template(device_tree_folder, "BoardConfig.mk")
		self._render_template(device_tree_folder, "device.mk")
		self._render_template(device_tree_folder, "extract-files.sh")
		self._render_template(device_tree_folder, "twrp_device.mk", out_file=f"twrp_{self.device_info.codename}.mk")
		self._render_template(device_tree_folder, "README.md")
		self._render_template(device_tree_folder, "setup-makefiles.sh")
		self._render_template(device_tree_folder, "vendorsetup.sh")

		# Set permissions
		chmod(device_tree_folder / "extract-files.sh", S_IRWXU | S_IRGRP | S_IROTH)
		chmod(device_tree_folder / "setup-makefiles.sh", S_IRWXU | S_IRGRP | S_IROTH)

		logger.debug("Copying kernel...")
		if not self.image_info.is_header_v4_gki and self.image_info.kernel is not None:
			copyfile(self.image_info.kernel, prebuilt_path / "kernel")
		if self.image_info.dt is not None:
			copyfile(self.image_info.dt, prebuilt_path / "dt.img")
		if self.image_info.dtb is not None:
			copyfile(self.image_info.dtb, prebuilt_path / "dtb.img")
		if not self.image_info.is_header_v4_gki and self.image_info.dtbo is not None:
			copyfile(self.image_info.dtbo, prebuilt_path / "dtbo.img")

		logger.debug("Copying fstab...")
		(device_tree_folder / "recovery.fstab").write_text(self.fstab.format(twrp=True))

		logger.debug("Copying init scripts...")
		for init_rc in self.init_rcs:
			copyfile(init_rc, recovery_root_path / init_rc.name, follow_symlinks=True)

		return device_tree_folder

	def _render_template(self, *args, comment_prefix: str = "#", **kwargs):
		return render_template(*args,
		                       comment_prefix=comment_prefix,
		                       current_year=self.current_year,
		                       device_info=self.device_info,
		                       fstab=self.fstab,
		                       image_info=self.image_info,
		                       version=version,
		                       **kwargs)