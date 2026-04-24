"""nwave-ai CLI: thin wrapper around nWave install/uninstall scripts."""

import subprocess
import sys
from pathlib import Path

from nwave_ai.doctor.context import DoctorContext
from nwave_ai.doctor.formatter import render_human, render_json
from nwave_ai.doctor.runner import run_doctor
from scripts.install.attribution_utils import (
    install_attribution_hook,
    read_attribution_preference,
    remove_attribution_hook,
    write_attribution_preference,
)


def _get_version() -> str:
    """Get version from package metadata (installed) or __init__.py (dev)."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("nwave-ai")
    except PackageNotFoundError:
        pass

    from nwave_ai import __version__

    return __version__


def _get_project_root() -> Path:
    """Find the project root (where scripts/install/ lives)."""
    return Path(__file__).parent.parent


def _run_script(script_name: str, args: list[str]) -> int:
    """Run an install script as a subprocess."""
    project_root = _get_project_root()
    script_path = project_root / "scripts" / "install" / script_name

    if not script_path.exists():
        print(f"Error: {script_name} not found at {script_path}", file=sys.stderr)
        print("The nwave-ai package may not be installed correctly.", file=sys.stderr)
        return 1

    cmd = [sys.executable, str(script_path), *args]
    result = subprocess.run(cmd, cwd=str(project_root))
    return result.returncode


def _get_config_dir() -> Path:
    """Return the nWave config directory (~/.nwave/)."""
    return Path.home() / ".nwave"


def _handle_attribution(args: list[str]) -> int:
    """Handle 'attribution on|off|status' subcommand."""
    if not args:
        print("Usage: nwave-ai attribution <on|off|status>", file=sys.stderr)
        return 1

    action = args[0].lower()
    config_dir = _get_config_dir()

    if action == "on":
        write_attribution_preference(config_dir, enabled=True)
        install_attribution_hook(config_dir)
        print("Attribution enabled. Your commits will include the nWave credit line.")
        return 0

    if action == "off":
        write_attribution_preference(config_dir, enabled=False)
        remove_attribution_hook(config_dir)
        print(
            "Attribution disabled. Your commits will not include the nWave credit line."
        )
        return 0

    if action == "status":
        preference = read_attribution_preference(config_dir)
        if preference is True:
            print("Attribution is currently on.")
        else:
            print("Attribution is currently off.")
        return 0

    print(f"Unknown attribution action: {action}", file=sys.stderr)
    print("Usage: nwave-ai attribution <on|off|status>", file=sys.stderr)
    return 1


def _handle_doctor(args: list[str]) -> int:
    """Handle 'doctor [--json] [--fix] [--help]' subcommand."""
    json_output = False
    fix = False

    for arg in args:
        if arg in ("--help", "-h"):
            print("Usage: nwave-ai doctor [--json] [--fix]")
            print()
            print("Run diagnostic checks on the nWave installation.")
            print()
            print("Options:")
            print("  --json    Emit JSON output instead of human-readable text.")
            print("  --fix     Attempt to fix detected issues (not yet implemented).")
            print("  --help    Show this message and exit.")
            return 0
        elif arg == "--json":
            json_output = True
        elif arg == "--fix":
            fix = True
        else:
            print(f"Unknown option for doctor: {arg}", file=sys.stderr)
            print("Run 'nwave-ai doctor --help' for usage.", file=sys.stderr)
            return 2

    if fix:
        print(
            "--fix not yet implemented. "
            "Run `nwave-ai install` to restore a broken installation."
        )
        return 2

    context = DoctorContext.from_defaults()
    results = run_doctor(context)

    if json_output:
        print(render_json(results))
    else:
        print(render_human(results))

    if any(not r.passed for r in results):
        return 1
    return 0


def _print_usage() -> int:
    ver = _get_version()
    print(f"nwave-ai {ver}")
    print()
    print("Usage: nwave-ai <command> [options]")
    print()
    print("Commands:")
    print("  install        Install nWave framework to ~/.claude/")
    print("  uninstall      Remove nWave framework from ~/.claude/")
    print("  doctor         Run diagnostics on the nWave installation")
    print("  attribution    Toggle commit attribution (on/off/status)")
    print("  version        Show nwave-ai version")
    print()
    print("Install options:")
    print("  --dry-run       Preview without making changes")
    print("  --backup-only   Create backup only")
    print("  --restore       Restore from backup")
    print()
    print("Example:")
    print("  nwave-ai install")
    return 0


def main() -> int:
    """CLI entry point for nwave-ai."""
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h", "help"):
        return _print_usage()

    command = sys.argv[1]

    if command == "install":
        return _run_script("install_nwave.py", sys.argv[2:])
    elif command == "uninstall":
        return _run_script("uninstall_nwave.py", sys.argv[2:])
    elif command == "attribution":
        return _handle_attribution(sys.argv[2:])
    elif command == "doctor":
        return _handle_doctor(sys.argv[2:])
    elif command == "version":
        print(f"nwave-ai {_get_version()}")
        return 0
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Run 'nwave-ai --help' for usage.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
