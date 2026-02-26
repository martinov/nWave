#!/usr/bin/env python3
"""
OpenCode DES Hook Installer - Manages OpenCode plugin lifecycle.

Installs/uninstalls the nWave DES plugin for OpenCode by copying the TypeScript
plugin to OpenCode's plugin directory and configuring environment variables.

This is the OpenCode equivalent of install_des_hooks.py (Claude Code).
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


class OpenCodeDESHookInstaller:
    """Manages DES plugin installation for OpenCode."""

    # Default OpenCode plugin directories (checked in order)
    OPENCODE_PLUGIN_DIRS = [
        Path.home() / ".config" / "opencode" / "plugins",
        Path(".opencode") / "plugins",
    ]

    PLUGIN_FILENAME = "nwave-des-plugin.ts"

    def __init__(self, plugin_dir: Path | None = None):
        """Initialize installer.

        Args:
            plugin_dir: Override OpenCode plugin directory (default: auto-detect)
        """
        self.plugin_dir = plugin_dir
        self.project_root = Path(__file__).resolve().parent.parent.parent
        self.source_plugin = (
            self.project_root
            / "src"
            / "des"
            / "adapters"
            / "drivers"
            / "hooks"
            / "opencode_plugin.ts"
        )

    def _resolve_plugin_dir(self) -> Path:
        """Resolve the OpenCode plugin directory.

        Uses explicit override if set, otherwise checks default locations.
        Creates the directory if it doesn't exist.

        Returns:
            Path to the plugin directory
        """
        if self.plugin_dir:
            return Path(self.plugin_dir)

        # Prefer user-level config dir
        target = self.OPENCODE_PLUGIN_DIRS[0]
        return target

    def install(self) -> bool:
        """Install the nWave DES plugin for OpenCode.

        Copies the TypeScript plugin to OpenCode's plugin directory and
        creates a companion .env file with NWAVE_ROOT and NWAVE_PYTHON.

        Returns:
            bool: True if installation succeeded
        """
        try:
            if not self.source_plugin.exists():
                print(
                    f"Source plugin not found: {self.source_plugin}",
                    file=sys.stderr,
                )
                return False

            target_dir = self._resolve_plugin_dir()
            target_dir.mkdir(parents=True, exist_ok=True)

            target_plugin = target_dir / self.PLUGIN_FILENAME
            target_env = target_dir / "nwave-des.env"

            # Copy plugin file
            shutil.copy2(self.source_plugin, target_plugin)

            # Create env file with project paths
            env_content = {
                "NWAVE_ROOT": str(self.project_root),
                "NWAVE_PYTHON": sys.executable,
            }
            target_env.write_text(json.dumps(env_content, indent=2) + "\n")

            print(f"nWave DES plugin installed to: {target_plugin}")
            print(f"Environment config: {target_env}")
            print()
            print("Plugin will be loaded on next OpenCode session start.")
            print(
                f"Set NWAVE_ROOT={self.project_root} in your shell if needed."
            )
            return True

        except Exception as e:
            print(f"Installation failed: {e}", file=sys.stderr)
            return False

    def uninstall(self) -> bool:
        """Remove the nWave DES plugin from OpenCode.

        Returns:
            bool: True if uninstallation succeeded
        """
        try:
            target_dir = self._resolve_plugin_dir()
            target_plugin = target_dir / self.PLUGIN_FILENAME
            target_env = target_dir / "nwave-des.env"

            removed = False
            if target_plugin.exists():
                target_plugin.unlink()
                print(f"Removed: {target_plugin}")
                removed = True
            if target_env.exists():
                target_env.unlink()
                print(f"Removed: {target_env}")
                removed = True

            if not removed:
                print("nWave DES plugin not found (nothing to remove)")
            else:
                print("nWave DES plugin uninstalled successfully")
            return True

        except Exception as e:
            print(f"Uninstallation failed: {e}", file=sys.stderr)
            return False

    def status(self) -> bool:
        """Check plugin installation status.

        Returns:
            bool: True if status check succeeded
        """
        try:
            target_dir = self._resolve_plugin_dir()
            target_plugin = target_dir / self.PLUGIN_FILENAME

            if target_plugin.exists():
                print(f"nWave DES plugin is installed at: {target_plugin}")

                # Check env file
                target_env = target_dir / "nwave-des.env"
                if target_env.exists():
                    env_data = json.loads(target_env.read_text())
                    print(f"  NWAVE_ROOT: {env_data.get('NWAVE_ROOT', 'not set')}")
                    print(
                        f"  NWAVE_PYTHON: {env_data.get('NWAVE_PYTHON', 'not set')}"
                    )
            else:
                print("nWave DES plugin is not installed")

            return True

        except Exception as e:
            print(f"Status check failed: {e}", file=sys.stderr)
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Install or uninstall nWave DES plugin for OpenCode"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true", help="Install DES plugin")
    group.add_argument("--uninstall", action="store_true", help="Uninstall DES plugin")
    group.add_argument(
        "--status", action="store_true", help="Check installation status"
    )
    parser.add_argument(
        "--plugin-dir",
        type=Path,
        help="Override OpenCode plugin directory",
    )

    args = parser.parse_args()

    installer = OpenCodeDESHookInstaller(plugin_dir=args.plugin_dir)

    if args.install:
        success = installer.install()
    elif args.uninstall:
        success = installer.uninstall()
    else:
        success = installer.status()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
