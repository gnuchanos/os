#!/bin/sh
# =============================================================================
# GnuchanOS - fetch and install every Gnuchan program from its own repository.
# -----------------------------------------------------------------------------
#     sh GnuChanPrograms.sh            fetch and install every program
#     sh GnuChanPrograms.sh --list     print the canonical program list
#
# Run once while the live image is being built (see the hook beside it,
# 0300-gnuchan-programs.hook.chroot). Each program now lives in its own GitHub
# repository rather than in a directory of this tree.
#
# HOW THE REPOSITORIES ARE LAID OUT
# Every program's repository puts its makefile at <repo>/src/makefile.py, and
# that makefile resolves its build output relative to its own file:
#
#     ROOT      = <repo>/src
#     REPO_ROOT = <repo>/src/../..   ==  the directory the repos are cloned INTO
#     build output = REPO_ROOT/_temp/<something>
#
# So the repositories are cloned into ONE directory, which is where their build
# output is written. Nothing is written inside a repository, so the tree this
# fetched stays exactly as it was cloned.
#
# Every picture a program needs - the logo, the wallpaper, the icon - is
# committed in that program's own repository under src/assets or assets, beside
# the makefile that reads it. Nothing has to be copied in from anywhere, and a
# checkout of one repository builds and installs on its own.
#
# FAILURE BEHAVIOR
# Standalone runs default to best-effort: a fetch or build failure is reported,
# and the remaining programs are still attempted. Set GNUCHAN_PROGRAMS_STRICT=1
# to return a failure after the run. The distro hook enables strict mode so an
# incomplete desktop cannot be packaged as a successful release image.
#
# Debian only, on purpose: every one of these programs is, and this installs
# with apt-get and writes /usr.
#
# License: GPL3
# =============================================================================

# No `set -e`: a failed clone or makefile must not prevent attempts to build
# the remaining programs. Strict mode reports the aggregate failure at the end.
# `set -u` is kept, so a misspelled variable is an error rather than an empty
# string.
set -u

# --- what is fetched, and from where ------------------------------------------

#: The GitHub account the programs are published under. Every program is its own
#: repository named exactly as the program is.
ORG="${GNUCHAN_PROGRAMS_ORG:-gnuchanos}"

#: Where a program is cloned from when it is not already on the machine.
BASE="${GNUCHAN_PROGRAMS_BASE:-https://github.com/$ORG}"

#: The directory the repositories are cloned INTO. It is also the common parent
#: the makefiles call REPO_ROOT, so it is not a scratch choice: every repo must
#: sit directly under it, and assets/ and the makefiles' own _temp/ must sit
#: beside them. (It is deliberately NOT named _temp: the makefiles create a
#: _temp/ of their own under this directory, and a directory called _temp
#: holding another one reads as a mistake.)
WORK="${GNUCHAN_PROGRAMS_WORK:-/opt/gnuchanos/programs}"

#: A directory of local checkouts, consulted before the network. A repository
#: already on the machine (a developer's clone, or a build that ran before)
#: is copied rather than fetched, which is what makes an offline build possible.
SRC="${GNUCHAN_PROGRAMS_SRC:-/opt/gnuchanos/repos}"

#: Set to 1 to make a failure exit non-zero. Off by default for standalone
#: runs; the distro hook enables it for release-image builds.
STRICT="${GNUCHAN_PROGRAMS_STRICT:-0}"

#: The programs, in the order they are built and installed: the applications the
#: desktop runs first, then the window manager, then the display manager last.
#: The display manager is last and only ever last: its install reconfigures
#: which manager owns the console and restarts it, so a run that did that in the
#: middle would tear down the session under the remaining installs.
PROGRAMS="
GnuChanTerm
GnuChanFetch
GnuChanRunner
GnuChanWifi
GnuChanNetworkManager
GnuChanDock
GnuChanBrowser
GnuChanSS
GnuChanLockScreen
GnuChanNotification
GnuChanScreenShoot
GnuChanSoftwareCenter
GnuChanTop
GnuChanSettings
GCL
GnuChanWM
GnuChanDM
"

# A fetch that would otherwise sit at a username prompt must fail instead. The
# repositories are private while they are being prepared, and a git that stops
# to ask for a password on a build with no terminal is a build that hangs until
# something times it out. With these set it gives up at once.
export GIT_TERMINAL_PROMPT=0
export GIT_ASKPASS=/bin/true
export GCM_INTERACTIVE=never

log() { printf '==> programs: %s\n' "$1"; }
warn() { printf '  ! programs: %s\n' "$1" >&2; }

# --- the tools the fetch and the build need -----------------------------------

apt_environment() {
    DEBIAN_FRONTEND=noninteractive
    export DEBIAN_FRONTEND
}

ensure_tool() {
    command_name="$1"
    package_name="$2"
    if command -v "$command_name" >/dev/null 2>&1; then
        return 0
    fi
    log "installing $package_name (no $command_name on this machine)"
    apt_environment
    apt-get update -o Acquire::Retries=3 >/dev/null 2>&1 || true
    apt-get install -y --no-install-recommends "$package_name" || {
        warn "could not install $package_name"
        return 1
    }
    command -v "$command_name" >/dev/null 2>&1
}

ensure_tools() {
    okay=0
    command -v git >/dev/null 2>&1 || ensure_tool git git || okay=1
    command -v python3 >/dev/null 2>&1 || ensure_tool python3 python3 || okay=1
    # ca-certificates is what makes the https clone verifiable; without it a
    # clone fails with a certificate error that looks like a missing program.
    if [ ! -d /etc/ssl/certs ] || [ -z "$(ls -A /etc/ssl/certs 2>/dev/null)" ]; then
        ensure_tool update-ca-certificates ca-certificates || okay=1
    fi
    return "$okay"
}

# --- fetching one program -----------------------------------------------------

prepare_test_install() {
    [ "${GNUCHAN_TEST_INSTALL:-0}" = "1" ] || return 0
    name="$1"
    target="$2"
    python3 - "$name" "$target" <<'PY'
from pathlib import Path
import sys

name, repository = sys.argv[1:]
makefile = Path(repository) / "src" / "makefile.py"
if not makefile.is_file():
    makefile = Path(repository) / "makefile.py"
if not makefile.is_file():
    raise SystemExit(f"test install: no makefile.py for {name}")

text = makefile.read_text(encoding="utf-8")
if name == "GnuChanTerm":
    old = 'temporary = BUILD / "gnuchanterm.desktop.new"'
    new = 'temporary = DESKTOP_FILE.with_name(DESKTOP_FILE.name + ".new")'
    replacements = ((old, new),)
elif name == "GnuChanWifi":
    old = 'temporary = BUILD / "gnuchanwifi.desktop.new"'
    new = 'temporary = DESKTOP_FILE.with_name(DESKTOP_FILE.name + ".new")'
    replacements = ((old, new),)
elif name == "GnuChanNetworkManager":
    old_zapret = "        ensure_dpi_dependency()\n        install(binary)"
    new_zapret = (
        '        if os.environ.get("GNUCHAN_TEST_INSTALL") == "1":\n'
        '            detail("test install: skipped zapret installation and service changes")\n'
        "        else:\n"
        "            ensure_dpi_dependency()\n"
        "        install(binary)"
    )
    old_desktop = 'temporary = BUILD / "gnuchannetworkmanager.desktop.new"'
    new_desktop = 'temporary = DESKTOP_FILE.with_name(DESKTOP_FILE.name + ".new")'
    replacements = (
        (old_zapret, new_zapret),
        (old_desktop, new_desktop),
    )
elif name == "GnuChanWM":
    old = 'temporary = BUILD / "gnuchanwm.desktop.new"'
    new = 'temporary = SESSION_FILE.with_name(SESSION_FILE.name + ".new")'
    replacements = ((old, new),)
elif name == "GnuChanDM":
    old = (
        '    if shutil.which("systemctl") is not None:\n'
        "        stop_rival_managers()\n"
        "        enable_service()"
    )
    new = (
        '    if os.environ.get("GNUCHAN_TEST_INSTALL") == "1":\n'
        '        note("Test install: left display-manager activation and running services unchanged.")\n'
        '    elif shutil.which("systemctl") is not None:\n'
        "        stop_rival_managers()\n"
        "        enable_service()"
    )
    replacements = ((old, new),)
else:
    replacements = ()

changed = False
for old, new in replacements:
    if new in text:
        continue
    if old not in text:
        raise SystemExit(f"test install: cannot safely patch {name} makefile {makefile}")
    text = text.replace(old, new, 1)
    changed = True

if changed:
    makefile.write_text(text, encoding="utf-8")
    print(f"==> programs: enabled safe test-install behavior for {name}", flush=True)
PY
}

# Put the program's source directly under $WORK so the makefile's REPO_ROOT -
# two levels above its own file - lands on $WORK, where assets/ and _temp/ are.
# A local checkout wins over the network. The directory is built fresh each
# time: a partially fetched one from an earlier run is not something to build on
# top of.
fetch_one() {
    name="$1"
    target="$WORK/$name"

    # The repository's name, where it differs from the program's: the GCL
    # language's repository is `gcl`, in lower case, while its directory here
    # is GCL so that the program list reads as program names.
    repo="$name"
    if [ "$name" = "GCL" ]; then
        repo=gcl
    fi

    rm -rf "$target"

    if [ -d "$SRC/$name" ]; then
        cp -a "$SRC/$name" "$target"
        rm -rf "$target/.git"
        prepare_test_install "$name" "$target" || return 1
        return 0
    fi
    if [ "$name" = "GCL" ] && [ -d "$SRC/gcl" ]; then
        cp -a "$SRC/gcl" "$target"
        rm -rf "$target/.git"
        prepare_test_install "$name" "$target" || return 1
        return 0
    fi

    git clone --depth 1 --quiet "$BASE/$repo.git" "$target" 2>/dev/null || {
        rm -rf "$target"
        return 1
    }
    rm -rf "$target/.git"
    prepare_test_install "$name" "$target" || return 1
    return 0
}

# --- installing one program ---------------------------------------------------

# Find the makefile: every repository puts it at src/makefile.py, and one that
# puts it at the root is accepted too rather than skipped over a layout choice.
program_makefile() {
    name="$1"
    for candidate in "$WORK/$name/src/makefile.py" "$WORK/$name/makefile.py"; do
        if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# Run the program's own makefile with `install`. It is run from the directory
# holding it, which is where every one of them expects to be. The makefile
# installs into /usr and this whole script runs as root inside the image build.
# GCL's makefile still names its sources under _SRC/ - the layout it had when it
# lived inside the GnuchanOS tree, before it was moved into a repository of its
# own - while the sources really sit directly under src/. One relative link
# gives it the tree it expects, without changing the repository:
#
#   src/_SRC   -> .   so every "_SRC/..." path in the makefile resolves to the
#                     sources beside it
#
# It is relative, so it names the build directory rather than a fixed place and
# nothing here has to know where the build is running. GCL's own assets - the
# icon, the wallpaper and the logo its IDE embeds - are committed in its
# repository, so nothing has to be linked or copied for those.
prepare_gcl_tree() {
    repo="$1"
    [ -e "$repo/src/_SRC" ] || ln -s . "$repo/src/_SRC" 2>/dev/null || true
}

install_one() {
    name="$1"
    if [ "$name" = "GCL" ]; then
        prepare_gcl_tree "$WORK/$name"
    fi
    makefile=$(program_makefile "$name") || {
        warn "$name has no makefile.py; it is not a Gnuchan program"
        return 1
    }
    ( cd "$(dirname "$makefile")" && python3 "$(basename "$makefile")" install )
}

# --- the run ------------------------------------------------------------------

main() {
    if [ "${1:-}" = "--list" ]; then
        [ "$#" -eq 1 ] || {
            warn "usage: GnuChanPrograms.sh --list"
            return 2
        }
        printf '%s\n' $PROGRAMS
        return 0
    fi

    if [ "${1:-}" = "--update" ]; then
        [ "$#" -ge 3 ] || {
            warn "usage: GnuChanPrograms.sh --update USER PROGRAM..."
            return 2
        }
        update_user="$2"
        shift 2
        case "$update_user" in
            ""|*[!a-zA-Z0-9_-]*)
                warn "invalid update account"
                return 2
                ;;
        esac
        user_record=$(getent passwd "$update_user") || {
            warn "account does not exist: $update_user"
            return 2
        }
        update_home=$(printf '%s\n' "$user_record" | cut -d: -f6)
        [ -n "$update_home" ] && [ -d "$update_home" ] || {
            warn "account home directory is unavailable: $update_user"
            return 2
        }
        selected=""
        for requested in "$@"; do
            case "$requested" in
                GnuChanTerm|GnuChanFetch|GnuChanRunner|GnuChanWifi|\
                GnuChanNetworkManager|GnuChanDock|GnuChanBrowser|GnuChanSS|\
                GnuChanLockScreen|GnuChanNotification|GnuChanScreenShoot|\
                GnuChanSoftwareCenter|GnuChanTop|GnuChanSettings|GCL|\
                GnuChanWM|GnuChanDM)
                    selected="$selected $requested"
                    ;;
                *)
                    warn "refusing unknown program name: $requested"
                    return 2
                    ;;
            esac
        done
        PROGRAMS="$selected"
        STRICT=1
        export GNUCHAN_TEST_INSTALL=1
        export HOME="$update_home" USER="$update_user" LOGNAME="$update_user"
        export SUDO_USER="$update_user"
        export XDG_CONFIG_HOME="$update_home/.config"
        export XDG_DATA_HOME="$update_home/.local/share"
        export XDG_CACHE_HOME="$update_home/.cache"
    fi

    if ! command -v apt-get >/dev/null 2>&1; then
        warn "this is not a Debian machine; the programs are Debian-only"
        return 1
    fi

    if ! ensure_tools; then
        warn "git and python3 are needed to build the programs; nothing was built"
        [ "$STRICT" = "1" ] && return 1
        return 0
    fi

    mkdir -p "$WORK"

    total=0
    for name in $PROGRAMS; do
        total=$((total + 1))
    done

    installed=""
    failed=""
    critical_failed=""
    index=0
    
    # Define critical programs - without these, the ISO won't boot properly
    CRITICAL_PROGRAMS="GnuChanWM GnuChanDM GCL"
    
    for name in $PROGRAMS; do
        index=$((index + 1))
        printf '\n'
        log "[$index/$total] $name"

        if ! fetch_one "$name"; then
            warn "$name could not be fetched from $BASE/$name.git"
            failed="$failed $name"
            # Check if this is a critical program
            if echo "$CRITICAL_PROGRAMS" | grep -q "\b$name\b"; then
                critical_failed="$critical_failed $name"
                warn "CRITICAL: $name is required for a bootable system"
            fi
            continue
        fi

        if install_one "$name"; then
            installed="$installed $name"
        else
            warn "$name: makefile.py install failed; see its output above"
            failed="$failed $name"
            # Check if this is a critical program
            if echo "$CRITICAL_PROGRAMS" | grep -q "\b$name\b"; then
                critical_failed="$critical_failed $name"
                warn "CRITICAL: $name failed to install - system may not boot properly"
            fi
        fi
    done

    printf '\n'
    log "Summary"
    [ -n "$installed" ] && printf '    installed:%s\n' "$installed"
    if [ -n "$failed" ]; then
        printf '    FAILED:%s\n' "$failed"
        printf '    (a program that failed is missing from the image; the remaining\n'
        printf '     programs were still attempted - see the file comment)\n'
    fi
    if [ -n "$critical_failed" ]; then
        warn "CRITICAL PROGRAMS FAILED:$critical_failed"
        warn "  Without these, the system may not boot or function properly:"
        for crit in $critical_failed; do
            case "$crit" in
                GnuChanWM) warn "    - GnuChanWM: Window manager (desktop won't start)" ;;
                GnuChanDM) warn "    - GnuChanDM: Display manager (no login screen)" ;;
                GCL) warn "    - GCL: Programming language and IDE" ;;
            esac
        done
    fi
    [ -z "$installed" ] && [ -z "$failed" ] && printf '    no programs were listed\n'

    # The clones are removed whether the run went well or not: what was built
    # has been installed into /usr, and the sources are not wanted on the image.
    rm -rf "$WORK"

    # Fail if critical programs failed, regardless of STRICT setting
    if [ -n "$critical_failed" ]; then
        warn "CRITICAL programs failed - build should not continue"
        warn "  Fix these issues or add local repositories to $SRC/"
        return 1
    fi
    
    if [ -n "$failed" ] && [ "$STRICT" = "1" ]; then
        warn "GNUCHAN_PROGRAMS_STRICT is set, so a missing program fails the build"
        return 1
    fi
    return 0
}

main "$@"