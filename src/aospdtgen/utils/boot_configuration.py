#
# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#
# dumprx fork: boot images are unpacked with the vendored AOSP unpacker
# (twrpdtgen.image_info, shared with the TWRP tree) instead of AIK, so no
# runtime AIK clone happens and GKI (header v3/v4) images work. Each image is
# unpacked individually and merged as upstream did with its five AIK managers.

from pathlib import Path
from typing import Optional, Union
from loguru import logger

from twrpdtgen.image_info import unpack_images


class BootConfiguration:
    """Class representing a device's boot configuration."""

    def __init__(
        self,
        dump_path: Path,
        workdir: Optional[Path] = None,
        unpack_bootimg_tool: Optional[Path] = None,
    ):
        """
        Given the path to a dump, parse all the images
        and generate a boot configuration.
        """
        self.dump_path = dump_path

        self.boot = self._get_image_path("boot")
        self.dtbo = self._get_image_path("dtbo")
        self.init_boot = self._get_image_path("init_boot")
        self.recovery = self._get_image_path("recovery")
        self.vendor_boot = self._get_image_path("vendor_boot")
        self.vendor_kernel_boot = self._get_image_path("vendor_kernel_boot")

        assert self.boot, "No boot image found"

        self.workdir = workdir or Path.cwd()
        self.unpack_bootimg_tool = unpack_bootimg_tool

        self.boot_image_info = unpack_images(
            [self.boot], self.workdir, self.unpack_bootimg_tool
        )

        self.init_boot_image_info = self._extract_if_exists(self.init_boot)
        self.recovery_image_info = self._extract_if_exists(self.recovery)
        self.vendor_boot_image_info = self._extract_if_exists(self.vendor_boot)
        self.vendor_kernel_boot_image_info = self._extract_if_exists(self.vendor_kernel_boot)

        self.kernel = self.boot_image_info.kernel
        self.dt = self.boot_image_info.dt
        self.dtb = self.boot_image_info.dtb
        self.dtbo = self.boot_image_info.dtbo

        self.base_address = self.boot_image_info.base_address
        self.cmdline = self.boot_image_info.cmdline
        self.pagesize = self.boot_image_info.pagesize

        if self.vendor_boot_image_info:
            self.kernel = self.vendor_boot_image_info.kernel or self.kernel
            self.dt = self.vendor_boot_image_info.dt or self.dt
            self.dtb = self.vendor_boot_image_info.dtb or self.dtb
            self.dtbo = self.vendor_boot_image_info.dtbo or self.dtbo

            self.base_address = self.vendor_boot_image_info.base_address or self.base_address
            self.cmdline = self.vendor_boot_image_info.cmdline or self.cmdline
            self.pagesize = self.vendor_boot_image_info.pagesize or self.pagesize

        if self.init_boot_image_info:
            self.base_address = self.init_boot_image_info.base_address or self.base_address
            self.cmdline = self.init_boot_image_info.cmdline or self.cmdline
            self.pagesize = self.init_boot_image_info.pagesize or self.pagesize

        if self.vendor_kernel_boot_image_info:
            self.kernel = self.vendor_kernel_boot_image_info.kernel or self.kernel
            self.dt = self.vendor_kernel_boot_image_info.dt or self.dt
            self.dtb = self.vendor_kernel_boot_image_info.dtb or self.dtb
            self.dtbo = self.vendor_kernel_boot_image_info.dtbo or self.dtbo

            self.base_address = self.vendor_kernel_boot_image_info.base_address or self.base_address
            self.cmdline = self.vendor_kernel_boot_image_info.cmdline or self.cmdline
            self.pagesize = self.vendor_kernel_boot_image_info.pagesize or self.pagesize

    def _get_image_path(self, partition: str) -> Union[Path, None]:
        path = self.dump_path / f"{partition}.img"
        return path if path.is_file() else None

    def _extract_if_exists(self, image: Optional[Path]):
        """Unpack an auxiliary image, best-effort (upstream used AIK's ignore_ramdisk_errors)."""
        if not image:
            return None

        try:
            return unpack_images([image], self.workdir, self.unpack_bootimg_tool)
        except Exception as exc:  # noqa: BLE001 - auxiliary images are best-effort
            logger.warning("Skipping auxiliary boot image {}: {}", image.name, exc)
            return None

    @property
    def cleanup_run_dir(self) -> Path:
        return self.workdir / "bootimg-unpack"

    def copy_files_to_folder(self, folder: Path) -> None:
        """Copy all prebuilts to a folder."""
        if self.kernel:
            (folder / "kernel").write_bytes(self.kernel.read_bytes())

        if self.dt:
            (folder / "dt.img").write_bytes(self.dt.read_bytes())

        if self.dtb:
            (folder / "dtb.img").write_bytes(self.dtb.read_bytes())

        if self.dtbo:
            (folder / "dtbo.img").write_bytes(self.dtbo.read_bytes())

    def cleanup(self):
        """Cleanup all the temporary files. Do not use this object anymore after calling this."""
        run_dir = self.cleanup_run_dir
        if run_dir.is_dir():
            import shutil

            shutil.rmtree(run_dir, ignore_errors=True)