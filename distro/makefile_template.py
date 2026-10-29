#!/usr/bin/env python3
# =============================================================================
# GnuChan Program Template - build and install with cross-distribution support
# -----------------------------------------------------------------------------
#     python3 makefile.py            install the packages, build, install
#     python3 makefile.py build      compile only
#     python3 makefile.py run        compile and start on the current display
#     python3 makefile.py uninstall  remove the binary and the desktop entry
#
# This template supports both Debian (apt) and Artix/Arch (pacman) distributions.
#
# To use this template:
# 1. Copy this file to your program's src/ directory as makefile.py
# 2. Set PROGRAM to your program name
# 3. Update SOURCES and HEADERS lists
# 4. Update PACKAGE_CHECKS with your program's dependencies
# 5. Update PKG_CONFIG_MODULES and FALLBACK_LIBS
# 6. Customize desktop_entry(), session_entry(), or install_config() as needed
#
# License: GPL3
# =============================================================================

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Try to import the shared distribution support module
try:
    # First try to import from the local directory (for standalone builds)
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "GnuchanOS" / "distro"))
    from _distribution import DistroSupport, detect_distro, install_packages
except ImportError:
    # Fall back to embedded implementation
    print("  ! Could not import _distribution module; using embedded fallback", file=sys.stderr)
    
    # Embedded minimal version for backward compatibility
    class DistroSupport:
        def __init__(self):
            self.distro = "debian" if shutil.which("apt-get") else "unknown"
        
        def install_packages(self, packages):
            if not packages:
                return True
            if self.distro == "debian":
                env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
                cmd = ["apt-get", "install", "-y", "--no-install-recommends", *packages]
                return subprocess.run(cmd, env=env).returncode == 0
            return False
    
    def detect_distro():
        return "debian" if shutil.which("apt-get") else "unknown"
    
    def install_packages(packages):
        return DistroSupport().install_packages(packages)

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent

# Build output goes under _temp/, not into the tree. A build is not a change to
# the project, and _temp/ is ignored by git — while the binary lived in the
# tree, every run left it behind for git to notice.
BUILD = REPO_ROOT / "_temp" / "gnuchan-build"

# --- Program-specific configuration ------------------------------------------

PROGRAM = "GnuChanProgram"  # CHANGE THIS to your program name
BIN_DIR = Path("/usr/local/bin")
APPS_DIR = Path("/usr/share/applications")
DESKTOP_FILE = APPS_DIR / "gnuchanprogram.desktop"  # CHANGE THIS

# The settings script, if your program has one
CONFIG_SOURCE = ROOT / f"{PROGRAM}_config" / f"{PROGRAM}.py"
CONFIG_DIR_NAME = PROGRAM
CONFIG_FILE_NAME = f"{PROGRAM}.py"

# Source and header files
SOURCES = (
    "main.c",
    # Add your source files here
)

HEADERS = (
    "main.h",
    # Add your header files here
)

ELEVATED_VARIABLE = f"{PROGRAM.upper().replace('GNUCHAN', 'GNUCHAN')}_ELEVATED"

# Package dependencies: (header_file, debian_package_name)
PACKAGE_CHECKS = (
    ("X11/Xlib.h", "libx11-dev"),
    ("X11/Xft/Xft.h", "libxft-dev"),
    ("ft2build.h", "libfreetype-dev"),
    # Add your program's dependencies here
)

# pkg-config modules for build flags
PKG_CONFIG_MODULES = ("x11", "xft", "fontconfig", "freetype2")
FALLBACK_LIBS = ["-lX11", "-lXft", "-lfontconfig", "-lfreetype"]

# --- Common functions --------------------------------------------------------

def step(message: str) -> None:
    print(f"==> {message}", flush=True)

def detail(message: str) -> None:
    print(f"    {message}", flush=True)

def note(message: str) -> None:
    print(message, flush=True)

def run(command: list[str], capture: bool = False,
        environment: dict | None = None, cwd: Path | None = None):
    if capture:
        return subprocess.run(command, check=False, capture_output=True,
                              text=True, env=environment, cwd=cwd)
    return subprocess.run(command, check=False, text=True, env=environment,
                          cwd=cwd)

def apt_environment() -> dict:
    return {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}

def is_root() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return bool(geteuid is not None and geteuid() == 0)

def ensure_root() -> None:
    if is_root():
        return
    if os.environ.get(ELEVATED_VARIABLE) == "1":
        raise SystemExit("error: still not root after sudo")
    sudo = shutil.which("sudo")
    if sudo is None:
        raise SystemExit("error: this installs packages and writes /usr; run as root")
    step("Needs root; re-running through sudo")
    environment = dict(os.environ)
    environment[ELEVATED_VARIABLE] = "1"
    os.execvpe(sudo, [sudo, sys.executable,
                      str(Path(__file__).resolve()), *sys.argv[1:]],
               environment)

# --- Distribution-aware functions --------------------------------------------

def freetype_includes() -> tuple[str, ...]:
    """Where freetype keeps its headers."""
    pkg_config = shutil.which("pkg-config")
    if pkg_config is not None:
        result = run([pkg_config, "--cflags-only-I", "freetype2"], capture=True)
        if result.returncode == 0:
            paths = tuple(word[2:] for word in result.stdout.split()
                          if word.startswith("-I"))
            if paths:
                return paths
    
    # Distribution-specific fallbacks
    distro = detect_distro()
    if distro in ("arch", "artix"):
        return ("/usr/include/freetype2",)
    else:  # Debian and others
        return ("/usr/include/freetype2",)

def header_present(header: str, extra_includes: tuple[str, ...] = ()) -> bool:
    """Whether gcc can preprocess a header."""
    gcc = shutil.which("gcc")
    if gcc is None:
        return False
    
    # Get architecture flags from distribution support
    distro_support = DistroSupport()
    arch_flags = distro_support.get_arch_specific_flags()
    
    command = [gcc, "-E", "-xc", "-"]
    command.extend(arch_flags['cflags'])
    for path in extra_includes:
        command += ["-I", path]
    
    result = subprocess.run(command, input=f"#include <{header}>\n",
                            text=True, capture_output=True, check=False)
    return result.returncode == 0

def missing_build_dependencies() -> list[str]:
    """Which packages this machine is missing to build the program."""
    needed: list[str] = []
    
    # Basic build tools
    if shutil.which("gcc") is None:
        needed.append("build-essential" if detect_distro() == "debian" else "base-devel")
    if shutil.which("pkg-config") is None:
        needed.append("pkg-config")
    
    # Check for required headers
    for header, debian_package in PACKAGE_CHECKS:
        if not header_present(header, freetype_includes()):
            needed.append(debian_package)
    
    return needed

def ensure_build_dependencies() -> None:
    """Install build dependencies using appropriate package manager."""
    needed = missing_build_dependencies()
    if not needed:
        return
    
    step("Installing the build dependencies")
    detail("missing: " + ", ".join(needed))
    
    # Map package names for current distribution
    distro_support = DistroSupport()
    mapped_packages = distro_support.map_packages(needed)
    
    if not install_packages(mapped_packages):
        raise SystemExit(f"error: could not install: {', '.join(needed)}")
    
    detail("installed: " + ", ".join(needed))

def x11_flags() -> tuple[list[str], list[str]]:
    """The compiler and linker flags for X libraries."""
    pkg_config = shutil.which("pkg-config")
    if pkg_config is not None:
        cflags = run([pkg_config, "--cflags", *PKG_CONFIG_MODULES], capture=True)
        libs = run([pkg_config, "--libs", *PKG_CONFIG_MODULES], capture=True)
        if cflags.returncode == 0 and libs.returncode == 0:
            return cflags.stdout.split(), libs.stdout.split()
    
    # Fallback with distribution-specific paths
    distro_support = DistroSupport()
    arch_flags = distro_support.get_arch_specific_flags()
    
    fallback_includes = ["-I/usr/include"]
    fallback_includes += ["-I" + path for path in freetype_includes()]
    fallback_includes.extend(arch_flags['cflags'])
    
    libs = list(FALLBACK_LIBS)
    libs.extend(arch_flags['ldflags'])
    
    return fallback_includes, libs

# --- Build and install functions ---------------------------------------------

def check_sources() -> None:
    missing = [name for name in (*SOURCES, *HEADERS)
               if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit("error: missing source files: " + ", ".join(missing))

def build() -> Path:
    check_sources()
    ensure_build_dependencies()

    BUILD.mkdir(parents=True, exist_ok=True)
    output = BUILD / PROGRAM

    cflags, libs = x11_flags()
    
    # Get architecture-specific flags
    distro_support = DistroSupport()
    arch_flags = distro_support.get_arch_specific_flags()
    
    command = [
        "gcc", "-std=c99", "-Wall", "-Wextra", "-Wno-unused-parameter",
        "-O2", "-D_DEFAULT_SOURCE",
        "-I", str(ROOT),
        *cflags,
    ]
    command += [str(ROOT / name) for name in SOURCES]
    command += ["-o", str(output)]
    command += libs
    
    # Add math library if needed
    command += ["-lm"]

    step("Building")
    if run(command, cwd=ROOT).returncode != 0:
        raise SystemExit("error: the build failed")
    detail(f"built {output}")
    return output

def desktop_entry() -> str:
    """Default .desktop file - customize as needed."""
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={PROGRAM}",
        f"Comment=GnuchanOS {PROGRAM}",
        f"Exec={BIN_DIR / PROGRAM}",
        f"TryExec={BIN_DIR / PROGRAM}",
        "Terminal=false",
        "Categories=System;",
        "Icon=applications-system",
        "",
    ])

def install(binary: Path) -> None:
    step("Installing")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    APPS_DIR.mkdir(parents=True, exist_ok=True)

    # The program already running is the one this install is replacing, so
    # writing to its path would fail with ETXTBSY. The new binary is written
    # beside it and renamed over it.
    staged = BIN_DIR / (PROGRAM + ".new")
    shutil.copyfile(binary, staged)
    staged.chmod(0o755)
    os.replace(str(staged), str(BIN_DIR / PROGRAM))
    detail(f"installed {BIN_DIR / PROGRAM}")

    temporary = BUILD / f"{PROGRAM.lower()}.desktop.new"
    temporary.write_text(desktop_entry(), encoding="utf-8")
    os.replace(str(temporary), str(DESKTOP_FILE))
    DESKTOP_FILE.chmod(0o644)
    detail(f"installed {DESKTOP_FILE}")

def invoking_user() -> tuple[Path, int, int] | None:
    """The home and ids of the person who ran sudo, not root."""
    name = os.environ.get("SUDO_USER")
    if not name:
        return None
    try:
        import pwd
        info = pwd.getpwnam(name)
        return Path(info.pw_dir), info.pw_uid, info.pw_gid
    except (ImportError, KeyError):
        return None

def install_config() -> None:
    """Install configuration file if it exists."""
    if not CONFIG_SOURCE.is_file():
        return
    user = invoking_user()
    if user is None:
        detail("skipped the config: no login user to install it for")
        return

    home, uid, gid = user
    directory = home / ".config" / CONFIG_DIR_NAME
    target = directory / CONFIG_FILE_NAME

    if CONFIG_SOURCE.stat().st_size == 0:
        raise SystemExit(
            f"error: {CONFIG_SOURCE} is empty, so the program would have "
            f"nothing to read"
        )

    directory.mkdir(parents=True, exist_ok=True)

    if target.exists():
        target.unlink()
        detail(f"removed the old {target}")

    shutil.copyfile(CONFIG_SOURCE, target)

    try:
        os.chown(directory, uid, gid)
        os.chown(target, uid, gid)
    except OSError:
        pass

    detail(f"installed {target}")

def uninstall() -> None:
    step("Uninstalling")
    for target in (BIN_DIR / PROGRAM, DESKTOP_FILE):
        if target.exists():
            target.unlink()
            detail(f"removed {target}")
    note(f"The settings script under ~/.config/{CONFIG_DIR_NAME}/ was left alone.")

def run_program(binary: Path) -> int:
    if not os.environ.get("DISPLAY"):
        raise SystemExit("error: DISPLAY is not set, so there is no X server to run on")
    step("Starting on the current display")
    return run([str(binary)], cwd=ROOT).returncode

def install_everything() -> int:
    ensure_build_dependencies()
    binary = build()
    install(binary)
    install_config()
    print("")
    print(f"{PROGRAM} is installed. It is in the applications menu, and")
    print(f"{BIN_DIR / PROGRAM} runs it from a shell.")
    return 0

# --- Main function -----------------------------------------------------------

def main() -> int:
    if platform.system().lower() != "linux":
        raise SystemExit(
            f"error: {PROGRAM} is a Linux program; this is {platform.system()}"
        )
    
    # Check if we support this distribution
    distro = detect_distro()
    if distro not in ("debian", "arch", "artix"):
        raise SystemExit(
            f"error: {PROGRAM} currently supports Debian and Arch/Artix; "
            f"this is {distro}"
        )

    action = sys.argv[1] if len(sys.argv) > 1 else "install"
    known = ("install", "build", "run", "uninstall")
    if action not in known:
        print(f"error: unknown action '{action}'", file=sys.stderr)
        print("usage: python3 makefile.py [" + "|".join(known) + "]", file=sys.stderr)
        return 2

    if action in ("install", "uninstall"):
        ensure_root()

    if action == "uninstall":
        uninstall()
        return 0

    if action == "build":
        binary = build()
        print(f"Built {binary}.")
        return 0

    if action == "run":
        return run_program(build())

    return install_everything()

if __name__ == "__main__":
    raise SystemExit(main())