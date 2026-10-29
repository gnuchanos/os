#!/usr/bin/env python3
"""Install local Gnuchan checkouts and ISO desktop settings on a Debian test system.

Usage:
    sudo python3 update_gnuchanos.py
    sudo python3 update_gnuchanos.py --build
    sudo python3 update_gnuchanos.py --settings

The script does not partition disks or reinstall the operating system. Test
installs leave display-manager activation and zapret setup unchanged.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

OS_ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS = OS_ROOT.parent
PROGRAMS_SCRIPT = OS_ROOT / "distro" / "GnuChanPrograms.sh"
DOTFILES_HOOK = OS_ROOT / "distro" / "config" / "hooks" / "normal" / "0200-dotfiles.hook.chroot"
LOGIND_LID_CONFIG = OS_ROOT / "distro" / "config" / "systemd" / "99-gnuchanos-lid.conf"
SYSTEM_LOGIND_CONFIG = Path("/etc/systemd/logind.conf.d/99-gnuchanos-lid.conf")

CONFIGS = (
    ("GnuChanTerm", "GnuChanTerm_config/GnuChanTerm.py", "GnuChanTerm", "GnuChanTerm.py"),
    ("GnuChanFetch", "GnuChanFetch_config/GnuChanFetch.py", "GnuChanFetch", "GnuChanFetch.py"),
    ("GnuChanRunner", "GnuChanRunner_config/config.py", "GnuChanRunner", "config.py"),
    ("GnuChanWifi", "GnuChanWifi_config/config.py", "GnuChanWifi", "config.py"),
    ("GnuChanNetworkManager", "GnuChanNetworkManager_config/config.py", "GnuChanNetworkManager", "config.py"),
    ("GnuChanDock", "GnuChanDock_config/GnuChanDock.py", "GnuChanDock", "GnuChanDock.py"),
    ("GnuChanSS", "GnuChanSS_config/GnuChanSS.py", "GnuChanSS", "GnuChanSS.py"),
    ("GnuChanLockScreen", "GnuChanSL_config/GnuChanSL.py", "GnuChanLockScreen", "GnuChanSL.py"),
    ("GnuChanNotification", "GnuChanNotification_config/GnuChanNotification.py", "GnuChanNotification", "GnuChanNotification.py"),
    ("GnuChanScreenShoot", "GnuChanScreenShoot_config/GnuChanScreenShoot.py", "GnuChanScreenShoot", "GnuChanScreenShoot.py"),
    ("GnuChanTop", "GnuChanTop_config/GnuChanTop.py", "GnuChanTop", "GnuChanTop.py"),
    ("GnuChanWM", "GnuChanWM_config/GnuChanWM.py", "GnuChanWM", "GnuChanWM.py"),
    ("GnuChanDM", "GnuChanDM_config/GnuChanDM.py", "GnuChanDM", "GnuChanDM.py"),
    ("GnuChanSoftwareCenter", "GnuChanSoftwareCenter_config/GnuChanSoftwareCenter.py", "GnuChanSoftwareCenter", "GnuChanSoftwareCenter.py"),
)


@dataclass(frozen=True)
class Account:
    name: str
    home: str
    uid: int
    gid: int


def log(message: str) -> None:
    print(f"==> update_gnuchanos: {message}", flush=True)


def die(message: str) -> None:
    raise SystemExit(f"error: update_gnuchanos: {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--build", action="store_true", help="build and install programs only")
    actions.add_argument("--settings", action="store_true", help="apply per-user settings and ISO desktop themes only")
    parser.add_argument("--user", help="account whose desktop is being tested (defaults to the sudo caller)")
    parser.add_argument("--hardware-fixes", action="store_true", help="also apply the ISO's Vostro A860-specific fixes")
    parser.add_argument("--dry-run", action="store_true", help="validate local checkouts and print the planned actions")
    return parser.parse_args()


def target_user(requested: str | None) -> Account:
    sudo_user = os.environ.get("SUDO_USER")
    current_user = getpass.getuser()
    if not requested and not sudo_user and current_user == "root":
        die("when running directly as root, pass the desktop account with --user USER")
    name = requested or sudo_user or current_user
    if not name:
        die("cannot determine the desktop account; pass --user USER")
    if shutil.which("getent") is None:
        die("getent is required to resolve the target account")
    result = subprocess.run(
        ["getent", "passwd", name],
        check=False,
        capture_output=True,
        text=True,
    )
    fields = result.stdout.rstrip("\n").split(":")
    if result.returncode != 0 or len(fields) != 7:
        die(f"account does not exist: {name}")
    home = fields[5]
    if not home or not Path(home).is_dir():
        die(f"home directory is unavailable for {name}: {home}")
    try:
        uid, gid = int(fields[2]), int(fields[3])
    except ValueError:
        die(f"account has invalid numeric IDs: {name}")
    return Account(name=fields[0], home=home, uid=uid, gid=gid)


def ensure_root(user: str, argv: list[str]) -> None:
    if os.geteuid() == 0:
        return
    sudo = shutil.which("sudo")
    if sudo is None:
        die("program installation writes system directories; run with sudo")
    args = [sudo, sys.executable, str(Path(__file__).resolve()), *argv]
    if not any(argument == "--user" or argument.startswith("--user=") for argument in argv):
        args.extend(["--user", user])
    os.execvpe(sudo, args, os.environ.copy())


def require_debian_tools() -> None:
    missing = [tool for tool in ("apt-get", "git", "python3", "sh") if shutil.which(tool) is None]
    if missing:
        die("Debian tools are missing: " + ", ".join(missing))


def canonical_program_list() -> list[str]:
    if not PROGRAMS_SCRIPT.is_file():
        die(f"ISO program helper is missing: {PROGRAMS_SCRIPT}")
    if shutil.which("sh") is None:
        die("sh is required to read the ISO program list")
    result = subprocess.run(
        ["sh", str(PROGRAMS_SCRIPT), "--list"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        die(f"could not read the ISO program list from {PROGRAMS_SCRIPT}")
    programs = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not programs:
        die("the ISO program list is empty")
    return programs


def validate_local_repositories(programs: list[str]) -> None:
    missing: list[str] = []
    for program in programs:
        repository = "gcl" if program == "GCL" else program
        root = DOCUMENTS / repository
        if not root.is_dir() or not any(
            (root / candidate).is_file()
            for candidate in ("src/makefile.py", "makefile.py")
        ):
            missing.append(f"{program} ({root})")
    if missing:
        die("local repositories are missing or incomplete; no network clones are used:\n  "
            + "\n  ".join(missing))


def update_local_repositories(programs: list[str]) -> None:
    failures: list[str] = []
    updates: list[tuple[str, list[str]]] = []
    git_environment = dict(os.environ)
    git_environment.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
    })

    repositories = [("GnuchanOS", OS_ROOT)]
    repositories.extend(
        ("gcl" if program == "GCL" else program,
         DOCUMENTS / ("gcl" if program == "GCL" else program))
        for program in programs
    )
    for repository, root in repositories:
        if not root.is_dir():
            failures.append(f"{repository}: checkout is missing at {root}")
            continue

        git_root = root.resolve()
        git_command = [
            "git",
            "-c",
            f"safe.directory={git_root}",
            "-C",
            str(git_root),
        ]
        owner_uid = root.stat().st_uid
        if os.geteuid() != owner_uid:
            sudo = shutil.which("sudo")
            if sudo is None:
                failures.append(f"{repository}: sudo is required to update as its owner")
                continue
            owner_result = subprocess.run(
                ["getent", "passwd", str(owner_uid)],
                check=False,
                capture_output=True,
                text=True,
            )
            owner_fields = owner_result.stdout.rstrip("\n").split(":")
            if owner_result.returncode != 0 or len(owner_fields) != 7:
                failures.append(
                    f"{repository}: checkout owner uid {owner_uid} has no account"
                )
                continue
            owner_name = owner_fields[0]
            prefix = [
                sudo, "-H", "-u", owner_name, "--", "env",
                "GIT_TERMINAL_PROMPT=0", "GCM_INTERACTIVE=never",
                *git_command,
            ]
        else:
            prefix = git_command

        status = subprocess.run(
            [*prefix, "status", "--porcelain", "--untracked-files=no"],
            check=False,
            capture_output=True,
            text=True,
            env=git_environment,
        )
        if status.returncode != 0:
            failures.append(f"{repository}: cannot inspect git worktree: {status.stderr.strip()}")
            continue
        changed_files = status.stdout.strip()
        if changed_files:
            failures.append(
                f"{repository}: tracked local changes prevent a safe update: "
                + changed_files.replace("\n", "; ")
            )
            continue
        updates.append((repository, prefix))

    if failures:
        die(
            "could not safely update GnuchanOS and every local program repository; "
            "no programs were installed:\n  "
            + "\n  ".join(failures)
        )

    failures = []
    for repository, prefix in updates:
        log(f"pulling {repository}")
        result = subprocess.run(
            [*prefix, "pull", "--ff-only"],
            check=False,
            capture_output=True,
            text=True,
            env=git_environment,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            failures.append(f"{repository}: git pull --ff-only failed: {detail}")
            continue
        output = result.stdout.strip().splitlines()
        log(f"{repository}: {output[-1] if output else 'already up to date'}")

    if failures:
        die(
            "could not safely update every local program repository; no programs were installed:\n  "
            + "\n  ".join(failures)
        )


def validate_test_install_support() -> None:
    compatible_sources = {
        "GnuChanTerm": (
            Path("GnuChanTerm") / "src" / "makefile.py",
            (
                'temporary = BUILD / "gnuchanterm.desktop.new"',
                'temporary = DESKTOP_FILE.with_name(DESKTOP_FILE.name + ".new")',
            ),
        ),
        "GnuChanWifi": (
            Path("GnuChanWifi") / "src" / "makefile.py",
            (
                'temporary = BUILD / "gnuchanwifi.desktop.new"',
                'temporary = DESKTOP_FILE.with_name(DESKTOP_FILE.name + ".new")',
            ),
        ),
        "GnuChanNetworkManager": (
            Path("GnuChanNetworkManager") / "src" / "makefile.py",
            (
                '        ensure_dpi_dependency()\n        install(binary)',
                'if os.environ.get("GNUCHAN_TEST_INSTALL") == "1":',
            ),
        ),
        "GnuChanWM": (
            Path("GnuChanWM") / "src" / "makefile.py",
            (
                'temporary = BUILD / "gnuchanwm.desktop.new"',
                'temporary = SESSION_FILE.with_name(SESSION_FILE.name + ".new")',
            ),
        ),
        "GnuChanDM": (
            Path("GnuChanDM") / "src" / "makefile.py",
            (
                '    if shutil.which("systemctl") is not None:\n        stop_rival_managers()\n        enable_service()',
                'if os.environ.get("GNUCHAN_TEST_INSTALL") == "1":',
            ),
        ),
    }
    stale: list[str] = []
    for repository, (relative_path, compatible_markers) in compatible_sources.items():
        source = DOCUMENTS / relative_path
        try:
            contents = source.read_text(encoding="utf-8")
        except OSError as error:
            die(f"cannot check test-install safeguards in {source}: {error}")
        if not any(marker in contents for marker in compatible_markers):
            stale.append(repository)
    if stale:
        die(
            "local program checkouts have unsupported installer code: "
            + ", ".join(stale)
            + ". No programs were installed."
        )


def install_programs(user: Account, programs: list[str]) -> int:
    with tempfile.TemporaryDirectory(prefix="gnuchanos-update-") as temporary:
        work = Path(temporary) / "programs"
        environment = dict(os.environ)
        environment.update({
            "GNUCHAN_PROGRAMS_SRC": str(DOCUMENTS),
            "GNUCHAN_PROGRAMS_WORK": str(work),
            "GNUCHAN_PROGRAMS_STRICT": "1",
            "GNUCHAN_TEST_INSTALL": "1",
        })
        command = ["sh", str(PROGRAMS_SCRIPT), "--update", user.name, *programs]
        log(f"installing {len(programs)} programs from local checkouts for {user.name}")
        result = subprocess.run(command, env=environment, check=False)
        if result.returncode != 0:
            log(
                f"program installation reported exit code {result.returncode}; "
                "per-user settings and themes will still be applied"
            )
        return result.returncode


def apply_program_settings(user: Account) -> None:
    home = Path(user.home)
    config_home = home / ".config"
    for repository, source_relative, target_directory, target_name in CONFIGS:
        source = DOCUMENTS / repository / "src" / source_relative
        if not source.is_file():
            die(f"authored configuration is missing: {source}")
        target = config_home / target_directory / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and target.read_bytes() == source.read_bytes():
            log(f"settings unchanged: {target}")
            continue
        if target.is_file():
            backup = target.with_name(target.name + ".bak")
            shutil.copy2(target, backup)
            os.chown(backup, user.uid, user.gid)
            log(f"saved previous settings to {backup}")
        shutil.copy2(source, target)
        os.chown(target, user.uid, user.gid)
        log(f"installed settings: {target}")

    system_conf = config_home / "GnuChanSettings" / "system.conf"
    if not system_conf.exists():
        system_conf.parent.mkdir(parents=True, exist_ok=True)
        system_conf.write_text(
            "# GnuchanOS settings. Edit with GnuChanSettings or by hand.\n"
            'ApplicationLanguage = "English"\n',
            encoding="utf-8",
        )
        os.chown(system_conf, user.uid, user.gid)
        log(f"created {system_conf}")
    elif "ApplicationLanguage" not in system_conf.read_text(encoding="utf-8"):
        with system_conf.open("a", encoding="utf-8") as settings:
            settings.write('\nApplicationLanguage = "English"\n')
        os.chown(system_conf, user.uid, user.gid)
        log(f"added the default application language to {system_conf}")


def apply_iso_dotfiles(user: Account, hardware_fixes: bool) -> None:
    if not DOTFILES_HOOK.is_file():
        die(f"ISO dotfiles hook is missing: {DOTFILES_HOOK}")
    environment = dict(os.environ)
    environment.update({
        "GNUCHANOS_STAGE": str(OS_ROOT),
        "GNUCHANOS_LIVE_USER": user.name,
        "GNUCHANOS_SKIP_HARDWARE_FIXES": "0" if hardware_fixes else "1",
    })
    log(f"applying ISO theme and desktop files for {user.name}")
    result = subprocess.run(["sh", str(DOTFILES_HOOK)], env=environment, check=False)
    if result.returncode != 0:
        die(f"ISO dotfiles hook failed with exit code {result.returncode}")


def apply_lid_policy() -> None:
    if not LOGIND_LID_CONFIG.is_file():
        die(f"ISO lid policy is missing: {LOGIND_LID_CONFIG}")
    expected = LOGIND_LID_CONFIG.read_bytes()
    if SYSTEM_LOGIND_CONFIG.is_file() and SYSTEM_LOGIND_CONFIG.read_bytes() == expected:
        log(f"lid-ignore policy unchanged: {SYSTEM_LOGIND_CONFIG}")
        return
    SYSTEM_LOGIND_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LOGIND_LID_CONFIG, SYSTEM_LOGIND_CONFIG)
    os.chmod(SYSTEM_LOGIND_CONFIG, 0o644)
    log(
        f"installed lid-ignore policy: {SYSTEM_LOGIND_CONFIG}; "
        "reboot to make systemd-logind ignore lid events"
    )


def main() -> int:
    args = parse_args()
    user = target_user(args.user)
    programs = canonical_program_list()
    validate_local_repositories(programs)

    do_build = args.build or not (args.build or args.settings)
    do_settings = args.settings or not (args.build or args.settings)
    if args.dry_run:
        log("would run git pull --ff-only in GnuchanOS and every local program checkout")
        if do_build:
            validate_test_install_support()
        log(f"target account: {user.name} ({user.home})")
        if do_build:
            log(f"would install {len(programs)} local programs: {' '.join(programs)}")
            log("GnuChanDM activation and zapret setup will be left unchanged")
        if do_settings:
            log("would refresh authored settings, apply ISO themes, and disable lid actions")
            if not args.hardware_fixes:
                log("Vostro A860 hardware fixes are skipped (use --hardware-fixes to opt in)")
        return 0

    require_debian_tools()
    ensure_root(user.name, sys.argv[1:])
    update_local_repositories(programs)
    validate_local_repositories(programs)
    if do_build:
        validate_test_install_support()

    installation_status = 0
    if do_build:
        installation_status = install_programs(user, programs)
    if do_settings:
        apply_program_settings(user)
        apply_iso_dotfiles(user, args.hardware_fixes)
        apply_lid_policy()
    if installation_status != 0:
        die(f"program installation failed with exit code {installation_status}")
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
