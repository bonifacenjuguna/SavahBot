#!/usr/bin/env python3
"""One command to change the version everywhere, or to check that every place agrees.

    python scripts/bump_version.py 1.6.0      # set the version in all places (and the Android versionCode)
    python scripts/bump_version.py --check    # exit 1 if the places disagree (used by the tests)

Places: frontend/src/version.ts, frontend/public/sw.js, frontend/package.json, backend/app/__init__.py,
android/app/build.gradle.kts (versionName and versionCode = major*10000 + minor*100 + patch, so 1.5.0 is 10500).
Add the new "## x.y.z" section to CHANGELOG.md yourself; this script tells you if it is missing. Standard library only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

# (file, pattern with one group around the version, replacement template)
PLACES = [
    ("frontend/src/version.ts", r'(APP_VERSION = ")(\d+\.\d+\.\d+)(")'),
    ("frontend/public/sw.js", r'(const VERSION = ")(\d+\.\d+\.\d+)(";)'),
    ("frontend/package.json", r'("version": ")(\d+\.\d+\.\d+)(")'),
    ("backend/app/__init__.py", r'(__version__ = ")(\d+\.\d+\.\d+)(")'),
    ("android/app/build.gradle.kts", r'(versionName = ")(\d+\.\d+\.\d+)(")'),
]
CODE = ("android/app/build.gradle.kts", r"(versionCode = )(\d+)()")


def code_for(version: str) -> int:
    a, b, c = (int(x) for x in version.split("."))
    return a * 10000 + b * 100 + c


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def versions() -> dict[str, str]:
    out = {}
    for rel, pat in PLACES:
        m = re.search(pat, read(rel))
        out[rel] = m.group(2) if m else "NOT FOUND"
    m = re.search(CODE[1], read(CODE[0]))
    out["android versionCode"] = m.group(2) if m else "NOT FOUND"
    return out


def check() -> list[str]:
    found = versions()
    values = {v for k, v in found.items() if k != "android versionCode"}
    problems = []
    if len(values) != 1 or "NOT FOUND" in values:
        problems.append("the version differs between files: " + ", ".join(f"{k}={v}" for k, v in found.items()))
    else:
        want = code_for(values.pop())
        if found["android versionCode"] != str(want):
            problems.append(f"android versionCode is {found['android versionCode']} but the version needs {want}")
    return problems


def bump(version: str) -> None:
    if not SEMVER.match(version):
        sys.exit("The version must look like 1.6.0")
    old = versions()
    old_version = next(v for k, v in old.items() if k != "android versionCode")
    if tuple(map(int, version.split("."))) <= tuple(map(int, old_version.split("."))):
        sys.exit(f"{version} is not newer than {old_version}. Versions only go up (Android refuses to install an older versionCode).")
    for rel, pat in PLACES + [CODE]:
        text = read(rel)
        new_value = str(code_for(version)) if (rel, pat) == CODE else version
        text, n = re.subn(pat, lambda m: m.group(1) + new_value + m.group(3), text, count=1)
        if n != 1:
            sys.exit(f"Could not find the version in {rel}")
        (ROOT / rel).write_text(text, encoding="utf-8", newline="")
    print(f"Version {old_version} -> {version} (Android versionCode {code_for(version)}).")
    if f"## {version}" not in read("CHANGELOG.md"):
        print(f'REMINDER: add a "## {version}" section to CHANGELOG.md before you release.')


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--check":
        problems = check()
        for p in problems:
            print("-", p)
        print("Versions agree." if not problems else "Versions DISAGREE.")
        sys.exit(1 if problems else 0)
    if len(sys.argv) == 2:
        bump(sys.argv[1])
    else:
        sys.exit(__doc__)
