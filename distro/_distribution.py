#!/usr/bin/env python3
"""
Distribution utilities for GnuChan programs.
Provides cross-distribution support for Debian (apt) and Artix/Arch (pacman).

This module can be imported by all GnuChan program makefile.py files to add
support for multiple Linux distributions.

Usage:
    from _distribution import DistroSupport
    
    distro = DistroSupport()
    if distro.distro == "debian":
        packages = distro.map_packages(["libx11-dev", "libxft-dev"])
        distro.install_packages(packages)
    elif distro.distro == "arch":
        packages = distro.map_packages(["libx11-dev", "libxft-dev"])
        distro.install_packages(packages)

License: GPL3
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


class DistroSupport:
    """Cross-distribution support for GnuChan programs."""
    
    def __init__(self):
        self.distro = self.detect_distro()
        self.arch = platform.machine() or "unknown"
        self.is_32bit = self.arch in ("i386", "i686", "x86")
        self.is_64bit = self.arch in ("x86_64", "amd64")
        
    def detect_distro(self) -> str:
        """Detect the Linux distribution."""
        # Check for package managers in order of preference
        if shutil.which("apt-get"):
            return "debian"
        elif shutil.which("pacman"):
            # Check if it's Artix specifically
            if os.path.exists("/etc/artix-release"):
                return "artix"
            elif os.path.exists("/etc/arch-release"):
                return "arch"
            else:
                return "arch"  # Assume Arch-like
        elif shutil.which("dnf"):
            return "fedora"
        elif shutil.which("yum"):
            return "rhel"
        elif shutil.which("zypper"):
            return "opensuse"
        else:
            return "unknown"
    
    def get_package_manager(self) -> Optional[str]:
        """Get the appropriate package manager command."""
        if self.distro in ("debian", "ubuntu", "mint"):
            return "apt-get"
        elif self.distro in ("arch", "artix", "manjaro"):
            return "pacman"
        elif self.distro == "fedora":
            return "dnf"
        elif self.distro == "rhel":
            return "yum"
        elif self.distro == "opensuse":
            return "zypper"
        else:
            return None
    
    def map_packages(self, packages: List[str]) -> List[str]:
        """
        Map Debian package names to distribution-specific names.
        
        This function takes a list of Debian-style package names and converts
        them to the appropriate names for the current distribution.
        """
        if not packages:
            return []
        
        # Package name mappings from Debian to other distributions
        debian_to_arch = {
            # X11 development packages
            "libx11-dev": "libx11",
            "libxft-dev": "libxft",
            "libfreetype-dev": "freetype2",
            "libxrender-dev": "libxrender",
            "libxcomposite-dev": "libxcomposite",
            "libxdamage-dev": "libxdamage",
            "libxrandr-dev": "libxrandr",
            "libxcursor-dev": "libxcursor",
            "libxss-dev": "libxss",
            "libxext-dev": "libxext",
            "libxinerama-dev": "libxinerama",
            "libxmu-dev": "libxmu",
            "libxpm-dev": "libxpm",
            
            # Image libraries
            "libimlib2-dev": "imlib2",
            "libpng-dev": "libpng",
            "libjpeg-dev": "libjpeg-turbo",
            
            # Fonts
            "libfontconfig-dev": "fontconfig",
            
            # Build tools
            "build-essential": "base-devel",
            "pkg-config": "pkg-config",
            "gcc": "gcc",
            "g++": "gcc",
            
            # System utilities
            "libpam0g-dev": "pam",
            "libdbus-1-dev": "dbus",
            "libnotify-dev": "libnotify",
            "libpolkit-gobject-1-dev": "polkit",
            
            # Terminal
            "ncurses-bin": "ncurses",
            
            # Additional utilities
            "xauth": "xorg-xauth",
            "xserver-xorg": "xorg-server",
            "xserver-xorg-legacy": "xorg-server",
            "x11-utils": "xorg-xdpyinfo",
            "locales": "glibc",
            "tlp": "tlp",
            "mate-polkit": "polkit",
        }
        
        # For Debian, return packages as-is
        if self.distro == "debian":
            return packages
        
        # For Arch/Artix, map Debian package names to Arch names
        if self.distro in ("arch", "artix"):
            result = []
            for pkg in packages:
                if pkg in debian_to_arch:
                    result.append(debian_to_arch[pkg])
                else:
                    # For unmapped packages, try a simple conversion
                    # Remove -dev suffix and convert to lowercase
                    mapped = pkg.replace("-dev", "").lower()
                    result.append(mapped)
            return result
        
        # For other distributions, return as-is for now
        return packages
    
    def install_packages(self, packages: List[str]) -> bool:
        """Install packages using the appropriate package manager."""
        if not packages:
            return True
        
        pm = self.get_package_manager()
        if not pm:
            print(f"  ! Unknown distribution: {self.distro}", file=sys.stderr)
            return False
        
        if pm == "apt-get":
            return self._apt_install(packages)
        elif pm == "pacman":
            return self._pacman_install(packages)
        elif pm == "dnf":
            return self._dnf_install(packages)
        elif pm == "yum":
            return self._yum_install(packages)
        elif pm == "zypper":
            return self._zypper_install(packages)
        else:
            print(f"  ! Unsupported package manager: {pm}", file=sys.stderr)
            return False
    
    def _apt_install(self, packages: List[str]) -> bool:
        """Install packages using apt-get (Debian/Ubuntu)."""
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
        
        # Update package database
        update_cmd = ["apt-get", "update", "-o", "Acquire::Retries=3"]
        result = subprocess.run(update_cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            print(f"  ! apt-get update failed: {result.stderr}", file=sys.stderr)
            # Continue anyway, the install may still work
        
        # Install packages
        install_cmd = ["apt-get", "install", "-y", "--no-install-recommends", *packages]
        print(f"    running: {' '.join(install_cmd)}")
        result = subprocess.run(install_cmd, text=True, env=env)
        
        if result.returncode == 0:
            print(f"    installed: {', '.join(packages)}")
            return True
        else:
            print(f"  ! apt-get could not install: {', '.join(packages)}", file=sys.stderr)
            return False
    
    def _pacman_install(self, packages: List[str]) -> bool:
        """Install packages using pacman (Arch/Artix)."""
        # Update package database
        sync_cmd = ["pacman", "-Sy"]
        result = subprocess.run(sync_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ! pacman -Sy failed: {result.stderr}", file=sys.stderr)
            # Continue anyway
        
        # Install packages
        install_cmd = ["pacman", "-S", "--noconfirm", "--needed", *packages]
        print(f"    running: {' '.join(install_cmd)}")
        result = subprocess.run(install_cmd, text=True)
        
        if result.returncode == 0:
            print(f"    installed: {', '.join(packages)}")
            return True
        else:
            print(f"  ! pacman could not install: {', '.join(packages)}", file=sys.stderr)
            return False
    
    def _dnf_install(self, packages: List[str]) -> bool:
        """Install packages using dnf (Fedora)."""
        install_cmd = ["dnf", "install", "-y", *packages]
        print(f"    running: {' '.join(install_cmd)}")
        result = subprocess.run(install_cmd, text=True)
        
        if result.returncode == 0:
            print(f"    installed: {', '.join(packages)}")
            return True
        else:
            print(f"  ! dnf could not install: {', '.join(packages)}", file=sys.stderr)
            return False
    
    def _yum_install(self, packages: List[str]) -> bool:
        """Install packages using yum (RHEL/CentOS)."""
        install_cmd = ["yum", "install", "-y", *packages]
        print(f"    running: {' '.join(install_cmd)}")
        result = subprocess.run(install_cmd, text=True)
        
        if result.returncode == 0:
            print(f"    installed: {', '.join(packages)}")
            return True
        else:
            print(f"  ! yum could not install: {', '.join(packages)}", file=sys.stderr)
            return False
    
    def _zypper_install(self, packages: List[str]) -> bool:
        """Install packages using zypper (openSUSE)."""
        install_cmd = ["zypper", "--non-interactive", "install", *packages]
        print(f"    running: {' '.join(install_cmd)}")
        result = subprocess.run(install_cmd, text=True)
        
        if result.returncode == 0:
            print(f"    installed: {', '.join(packages)}")
            return True
        else:
            print(f"  ! zypper could not install: {', '.join(packages)}", file=sys.stderr)
            return False
    
    def get_arch_specific_flags(self) -> Dict[str, str]:
        """
        Get architecture-specific compiler and linker flags.
        
        Returns a dictionary with keys:
        - 'cflags': C compiler flags
        - 'ldflags': Linker flags
        - 'libdirs': Library directories
        """
        flags = {
            'cflags': [],
            'ldflags': [],
            'libdirs': [],
        }
        
        # Architecture-specific flags
        if self.is_32bit:
            flags['cflags'].extend(["-m32"])
            flags['ldflags'].extend(["-m32"])
        elif self.is_64bit:
            flags['cflags'].extend(["-m64"])
            flags['ldflags'].extend(["-m64"])
        
        # Distribution-specific library paths
        if self.distro == "debian":
            if self.is_32bit:
                flags['libdirs'].extend(["/usr/lib/i386-linux-gnu"])
            elif self.is_64bit:
                flags['libdirs'].extend(["/usr/lib/x86_64-linux-gnu"])
        elif self.distro in ("arch", "artix"):
            if self.is_32bit:
                flags['libdirs'].extend(["/usr/lib32"])
            elif self.is_64bit:
                flags['libdirs'].extend(["/usr/lib"])
        
        return flags
    
    def check_header(self, header: str, extra_includes: List[str] = None) -> bool:
        """
        Check if a C header file can be compiled.
        
        This is a cross-distribution version of the header check used by
        GnuChan programs to detect installed development packages.
        """
        if extra_includes is None:
            extra_includes = []
        
        gcc = shutil.which("gcc")
        if gcc is None:
            return False
        
        # Get architecture-specific flags
        arch_flags = self.get_arch_specific_flags()
        
        command = [gcc, "-E", "-xc", "-"]
        command.extend(arch_flags['cflags'])
        for path in extra_includes:
            command.extend(["-I", path])
        
        result = subprocess.run(
            command,
            input=f"#include <{header}>\n",
            text=True,
            capture_output=True,
            check=False
        )
        return result.returncode == 0


# Helper functions for backward compatibility
def detect_distro() -> str:
    """Simple distribution detection (backward compatibility)."""
    return DistroSupport().distro

def is_debian() -> bool:
    """Check if running on Debian (backward compatibility)."""
    return DistroSupport().distro == "debian"

def is_arch() -> bool:
    """Check if running on Arch or Artix."""
    distro = DistroSupport().distro
    return distro in ("arch", "artix")

def install_packages(packages: List[str]) -> bool:
    """Install packages using appropriate package manager (backward compatibility)."""
    return DistroSupport().install_packages(packages)