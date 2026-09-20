#
# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#

from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules
from sebaubuntu_libs.libandroid.elf.elf import ELF
from sebaubuntu_libs.libandroid.partitions.partition import AndroidPartition
from sebaubuntu_libs.libexception import format_exception
from sebaubuntu_libs.liblogging import LOGE
from sebaubuntu_libs.libreorder import strcoll_files_key
from typing import Dict, List, Type


_ELF_NEEDED_CACHE: Dict[Path, set] = {}


def _get_needed_libs_cached(file: Path) -> set:
    if file not in _ELF_NEEDED_CACHE:
        try:
            _ELF_NEEDED_CACHE[file] = ELF.get_needed_libs(file)
        except Exception:
            _ELF_NEEDED_CACHE[file] = set()
    return _ELF_NEEDED_CACHE[file]


class Section:
    """Class representing a proprietary files list section."""

    name: str = "Miscellaneous"
    """Name of the section"""
    interfaces: List[str] = []
    """List of interfaces"""
    hardware_modules: List[str] = []
    """List of hardware modules IDs"""
    apexes: List[str] = []
    """List of APEXes"""
    apps: List[str] = []
    """List of app names"""
    binaries: List[str] = []
    """List of binaries/services"""
    libraries: List[str] = []
    """List of libraries (omit the .so)"""
    filenames: List[str] = []
    """List of exact file names"""
    folders: List[str] = []
    """List of folders"""
    patterns: List[str] = []
    """List of basic patterns (use regex)"""
    properties_prefixes: Dict[str, bool] = {}
    """List of properties prefix to whether it's an exact match"""

    def __init__(self):
        """Initialize the section."""
        self.files: List[Path] = []
        self._filenames_set = set(self.filenames)
        self._folders_set = set(self.folders)
        self._apexes_set = set(self.apexes)
        self._apps_set = set(self.apps)
        self._binaries_set = set(self.binaries)
        self._libraries_set = set(self.libraries)
        import re

        self._compiled_patterns = [re.compile(p) for p in self.patterns]

    def add_files(self, files: List[Path], partition: AndroidPartition):
        matched: List[Path] = []
        not_matched: List[Path] = []

        rel_map: Dict[Path, Path] = {file: file.relative_to(partition.path) for file in files}

        for file in files:
            (matched if self.file_match(rel_map[file]) else not_matched).append(file)

        # Index unmatched .so files by name for O(1) lookup
        not_matched_so: Dict[str, List[Path]] = {}
        for file in not_matched:
            if file.suffix == ".so":
                not_matched_so.setdefault(file.name, []).append(file)

        # Handle shared libs
        i = 0
        while i < len(matched):
            file = matched[i]
            i += 1
            file_relative = rel_map.get(file) or file.relative_to(partition.path)
            parts = file_relative.parts
            if not parts or parts[0] not in ("bin", "lib", "lib64"):
                continue

            # Add shared libs used by the section ELFs
            needed_libs = _get_needed_libs_cached(file)
            for lib in needed_libs:
                # Skip the lib if it belongs to another interface section
                if "@" in lib and lib.split("@", 1)[0] in known_interfaces_set:
                    continue
                if "-" in lib and lib.split("-", 1)[0] in known_interfaces_set:
                    continue

                lib_stem = lib[:-3] if lib.endswith(".so") else lib
                if lib_stem in known_libraries_set:
                    continue

                candidates = not_matched_so.pop(lib, None)
                if candidates:
                    for cand in candidates:
                        not_matched.remove(cand)
                        matched.append(cand)
                        rel_map[cand] = cand.relative_to(partition.path)

        self.files.extend(
            partition.model.proprietary_files_prefix / rel_map[file]
            for file in matched
        )

        return not_matched

    def get_files(self):
        """Returns the ordered list of files."""
        self.files.sort(key=strcoll_files_key)
        return self.files

    def file_match(self, file: Path):
        if self.name == "Miscellaneous":
            return True

        parts = file.parts
        if not parts:
            return False

        first = parts[0]
        name = file.name

        # Folders
        for folder in file.parents:
            if str(folder) in self._folders_set:
                return True

        # Filenames
        if name in self._filenames_set:
            return True

        # APEXes
        if first == "apex" and file.suffix == ".apex" and file.stem in self._apexes_set:
            return True

        # Apps
        if first in ("app", "priv-app") and file.suffix == ".apk" and file.stem in self._apps_set:
            return True

        # Binaries
        if first == "bin" and name in self._binaries_set:
            return True

        # Init scripts
        if len(parts) >= 2 and parts[0] == "etc" and parts[1] == "init":
            for binary in self.binaries:
                if (name.endswith(f"{binary}.rc") or name == f"{binary}.rc") and (
                    name.startswith("init.") or name.startswith("init_") or name == f"{binary}.rc"
                ):
                    return True

        # Libraries
        is_lib = first in ("lib", "lib64")
        if is_lib and file.suffix == ".so" and file.stem in self._libraries_set:
            return True

        # Hardware modules
        is_lib_hw = is_lib and len(parts) >= 2 and parts[1] == "hw"
        if is_lib_hw and file.suffix == ".so":
            for hardware_module in self.hardware_modules:
                if name.startswith(f"{hardware_module}."):
                    return True

        # Interfaces
        if self.interfaces:
            # Service binary
            if first == "bin":
                for interface in self.interfaces:
                    if interface in name:
                        return True
            # Service init script
            elif len(parts) >= 2 and parts[0] == "etc" and parts[1] == "init":
                for interface in self.interfaces:
                    if interface in name:
                        return True
            # VINTF fragment
            elif len(parts) >= 3 and parts[0] == "etc" and parts[1] == "vintf" and parts[2] == "manifest":
                for interface in self.interfaces:
                    if interface in name:
                        return True
            # Passthrough impl (only HIDL)
            elif is_lib_hw and name.endswith("-impl.so"):
                for interface in self.interfaces:
                    if name.startswith(interface) and "@" in name:
                        return True
            # Interface libs (AIDL and HIDL)
            elif is_lib and file.suffix == ".so":
                for interface in self.interfaces:
                    if name.startswith(interface) and ("@" in name or "-" in name):
                        return True

        # Patterns
        for pattern in self._compiled_patterns:
            if pattern.match(str(file)):
                return True

        return False

    def property_match(self, prop: str):
        """Check if the property matches the prefixes."""
        for prefix, exact_match in self.properties_prefixes.items():
            if prop == prefix if exact_match else prop.startswith(prefix):
                return True

        return False


sections: List[Section] = []
known_interfaces: List[str] = []
known_libraries: List[str] = []
known_interfaces_set: set = set()
known_libraries_set: set = set()


def register_section(section: Type[Section]):
    sections.append(section())

    for interface in section.interfaces:
        assert interface not in known_interfaces, f"Duplicate interface: {interface}"
        known_interfaces.append(interface)
        known_interfaces_set.add(interface)

    for library in section.libraries:
        assert library not in known_libraries, f"Duplicate shared library: {library}"
        known_libraries.append(library)
        known_libraries_set.add(library)


def register_sections(sections_path: Path):
    """Import all the sections and let them execute register_section()."""
    for section_name in [name for _, name, _ in iter_modules([str(sections_path)])]:
        try:
            import_module(f"aospdtgen.proprietary_files.sections.{section_name}")
        except Exception as e:
            LOGE(f"Error importing section {section_name}:\n{format_exception(e)}")
