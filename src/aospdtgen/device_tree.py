#
# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#

from os import chmod
from pathlib import Path
from sebaubuntu_libs.libandroid.device_info import DeviceInfo
from sebaubuntu_libs.libandroid.fstab import Fstab
from sebaubuntu_libs.libandroid.partitions.partitions import Partitions
from sebaubuntu_libs.libandroid.props import BuildProp
from sebaubuntu_libs.liblogging import LOGI
from sebaubuntu_libs.libpath import is_relative_to
from sebaubuntu_libs.libreorder import strcoll_files_key
from shutil import rmtree
from stat import S_IRWXU, S_IRGRP, S_IROTH
from typing import Any, Optional

from aospdtgen.proprietary_files.proprietary_files_list import ProprietaryFilesList
from aospdtgen.templates import render_template
from aospdtgen.utils.boot_configuration import BootConfiguration
from aospdtgen.utils.format_props import dump_partition_build_prop


class DeviceTree:
    """Class representing an Android device tree."""

    def __init__(
        self,
        path: Path,
        no_proprietary_files: bool = False,
        workdir: Optional[Path] = None,
        unpack_bootimg_tool: Optional[Path] = None,
        firmware_info: Optional[Any] = None,
    ):
        """Given a path to a dumpyara dump path, generate a device tree by parsing it."""
        self.path = path

        LOGI("Figuring out partitions scheme")
        self.partitions = Partitions(self.path)

        self.system = self.partitions.system
        self.vendor = self.partitions.vendor

        LOGI("Parsing build props and device info")
        self.build_prop = BuildProp()
        for partition in self.partitions.get_all_partitions():
            self.build_prop.import_props(partition.build_prop)
        self.device_info = DeviceInfo(self.build_prop)

        if firmware_info is not None:
            if getattr(firmware_info, "codename", None):
                self.device_info.codename = firmware_info.codename
            if getattr(firmware_info, "manufacturer", None):
                self.device_info.manufacturer = firmware_info.manufacturer.lower()
            if getattr(firmware_info, "brand", None):
                self.device_info.brand = firmware_info.brand
            if getattr(firmware_info, "model", None):
                self.device_info.model = firmware_info.model
            elif getattr(firmware_info, "transname", None):
                self.device_info.model = firmware_info.transname
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

        mfr_prefix = f"{self.device_info.manufacturer.lower()}-"
        if self.device_info.codename.lower().startswith(mfr_prefix):
            self.device_info.codename = self.device_info.codename[len(mfr_prefix):]
        elif self.device_info.brand:
            brand_prefix = f"{self.device_info.brand.lower()}-"
            if self.device_info.codename.lower().startswith(brand_prefix):
                self.device_info.codename = self.device_info.codename[len(brand_prefix):]

        if self.device_info.bootloader_board_name and self.device_info.bootloader_board_name.lower().startswith(mfr_prefix):
            self.device_info.bootloader_board_name = self.device_info.bootloader_board_name[len(mfr_prefix):]

        LOGI("Parsing fstab")
        fstabs = [
            file
            for file in self.vendor.files
            if (
                is_relative_to(file.relative_to(self.vendor.path), "etc")
                and file.name.startswith("fstab.")
            )
        ]
        assert fstabs, "No fstab found"
        fstab = fstabs[0]
        self.fstab = Fstab(fstab)

        # Let the partitions know their fstab entries if any
        for partition in self.partitions.get_all_partitions():
            partition.fill_fstab_entry(self.fstab)

        LOGI("Extracting boot image")
        self.boot_configuration = BootConfiguration(
            self.path,
            workdir=workdir,
            unpack_bootimg_tool=unpack_bootimg_tool,
        )

        LOGI("Getting list of rootdir files")
        self.rootdir_bin_files = [
            file
            for file in self.vendor.files
            if is_relative_to(file.relative_to(self.vendor.path), "bin") and file.suffix == ".sh"
        ]
        self.rootdir_bin_files.sort(key=strcoll_files_key)

        self.rootdir_etc_files = [
            file
            for file in self.vendor.files
            if is_relative_to(file.relative_to(self.vendor.path), "etc/init/hw")
        ]
        self.rootdir_etc_files.sort(key=strcoll_files_key)

        recovery_resources_location = (
            self.boot_configuration.recovery_image_info.ramdisk
            if (
                self.boot_configuration.recovery_image_info
                and self.boot_configuration.recovery_image_info.ramdisk is not None
            )
            else self.boot_configuration.boot_image_info.ramdisk
        )
        if recovery_resources_location is not None and recovery_resources_location.is_dir():
            self.rootdir_recovery_etc_files = [
                file
                for file in recovery_resources_location.iterdir()
                if is_relative_to(file.relative_to(recovery_resources_location), ".")
                and file.suffix == ".rc"
            ]
        else:
            self.rootdir_recovery_etc_files = []
        self.rootdir_recovery_etc_files.sort(key=strcoll_files_key)

        self.proprietary_files_list: Optional[ProprietaryFilesList] = None
        if not no_proprietary_files:
            LOGI("Generating proprietary files list")
            self.proprietary_files_list = ProprietaryFilesList(
                [value for value in self.partitions.get_all_partitions()]
            )

    def dump_to_folder(self, folder: Path):
        """Dump all makefiles, blueprint and prebuilts to a folder."""
        if folder.is_dir():
            rmtree(folder)
        folder.mkdir(parents=True)

        # Makefiles/blueprints
        self._render_template(folder, "Android.bp", comment_prefix="//")
        self._render_template(folder, "Android.mk")
        self._render_template(folder, "AndroidProducts.mk")
        self._render_template(folder, "BoardConfig.mk")
        self._render_template(folder, "device.mk")
        self._render_template(
            folder, "lineage_device.mk", out_file=f"lineage_{self.device_info.codename}.mk"
        )
        self._render_template(folder, "README.md")

        # Proprietary files list and extract utils
        if self.proprietary_files_list:
            self._render_template(folder, "extract-files.py")
            self._render_template(folder, "setup-makefiles.py")
            chmod(folder / "extract-files.py", S_IRWXU | S_IRGRP | S_IROTH)
            chmod(folder / "setup-makefiles.py", S_IRWXU | S_IRGRP | S_IROTH)

            (folder / "proprietary-files.txt").write_text(
                self.proprietary_files_list.get_formatted_list(self.device_info.build_description),
                encoding="utf-8",
            )

        # Dump build props
        for partition in self.partitions.get_all_partitions():
            dump_partition_build_prop(partition.build_prop, folder / f"{partition.model.name}.prop")

        # Dump boot image prebuilt files
        prebuilts_path = folder / "prebuilts"
        prebuilts_path.mkdir()

        self.boot_configuration.copy_files_to_folder(prebuilts_path)

        # Dump rootdir
        rootdir_path = folder / "rootdir"
        rootdir_path.mkdir()

        self._render_template(rootdir_path, "rootdir_Android.bp", "Android.bp", comment_prefix="//")
        self._render_template(rootdir_path, "rootdir_Android.mk", "Android.mk")

        # rootdir/bin
        rootdir_bin_path = rootdir_path / "bin"
        rootdir_bin_path.mkdir()

        for file in self.rootdir_bin_files:
            (rootdir_bin_path / file.name).write_bytes(file.read_bytes())

        # rootdir/etc
        rootdir_etc_path = rootdir_path / "etc"
        rootdir_etc_path.mkdir()

        for file in self.rootdir_etc_files + self.rootdir_recovery_etc_files:
            (rootdir_etc_path / file.name).write_bytes(file.read_bytes())

        (rootdir_etc_path / self.fstab.fstab.name).write_text(self.fstab.format(), encoding="utf-8")

        # Manifest
        (folder / "manifest.xml").write_text(str(self.vendor.manifest), encoding="utf-8")

    def cleanup(self) -> None:
        """
        Cleanup all the temporary files.

        After you call this, you should throw away this object and never use it anymore.
        """
        self.boot_configuration.cleanup()

    def _render_template(self, *args, comment_prefix: str = "#", **kwargs):
        return render_template(
            *args,
            boot_configuration=self.boot_configuration,
            comment_prefix=comment_prefix,
            device_info=self.device_info,
            fstab=self.fstab,
            proprietary_files_list=self.proprietary_files_list,
            rootdir_bin_files=self.rootdir_bin_files,
            rootdir_etc_files=self.rootdir_etc_files,
            rootdir_recovery_etc_files=self.rootdir_recovery_etc_files,
            partitions=self.partitions,
            **kwargs,
        )
