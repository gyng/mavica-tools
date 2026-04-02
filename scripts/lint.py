#!/usr/bin/env python3
"""Run ruff lint + format checks. Pass --fix to auto-fix."""

import subprocess
import sys


def main():
    fix = "--fix" in sys.argv
    ok = True

    print("=== ruff check ===")
    cmd = ["python", "-m", "ruff", "check", "."]
    if fix:
        cmd.append("--fix")
    result = subprocess.run(cmd)
    if result.returncode:
        ok = False

    print("\n=== ruff format ===")
    cmd = ["python", "-m", "ruff", "format", "."]
    if not fix:
        cmd.append("--check")
    result = subprocess.run(cmd)
    if result.returncode:
        ok = False

    if not ok:
        print("\nLint/format issues found.", "Fixed." if fix else "Run with --fix to auto-fix.")
        sys.exit(1)
    else:
        print("\nAll checks passed!")


if __name__ == "__main__":
    main()
