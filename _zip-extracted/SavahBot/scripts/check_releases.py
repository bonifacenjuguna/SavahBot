#!/usr/bin/env python3
"""Checks everything under releases/<product>/<version>/ (run by the "Protect releases" workflow, and runnable by hand).

    python scripts/check_releases.py

For every version folder: the folder name is a version (1.5.0), it holds exactly one APK named <Something>-<version>.apk,
a SHA256SUMS file whose checksum matches that APK, and a RELEASE.md. Exit code 1 and a list of problems otherwise.
Standard library only.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "releases"
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
LINE = re.compile(r"^([0-9a-f]{64}) [ *](.+)$")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check(root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    if not root.is_dir():
        return problems
    for product in sorted(p for p in root.iterdir() if p.is_dir()):
        for ver in sorted(v for v in product.iterdir() if v.is_dir()):
            where = f"{product.name}/{ver.name}"
            if not VERSION.match(ver.name):
                problems.append(f"{where}: the folder name must be a version like 1.5.0")
                continue
            apks = sorted(ver.glob("*.apk"))
            if len(apks) != 1:
                problems.append(f"{where}: expected exactly one .apk, found {len(apks)}")
                continue
            apk = apks[0]
            if not apk.name.endswith(f"-{ver.name}.apk"):
                problems.append(f"{where}: the APK is named {apk.name}; it must end with -{ver.name}.apk")
            if not (ver / "RELEASE.md").is_file():
                problems.append(f"{where}: RELEASE.md is missing")
            sums = ver / "SHA256SUMS"
            if not sums.is_file():
                problems.append(f"{where}: SHA256SUMS is missing")
                continue
            listed = {}
            for raw in sums.read_text(encoding="utf-8").splitlines():
                m = LINE.match(raw.strip())
                if m:
                    listed[m.group(2)] = m.group(1)
            if apk.name not in listed:
                problems.append(f"{where}: SHA256SUMS does not list {apk.name}")
            elif listed[apk.name] != sha256(apk):
                problems.append(f"{where}: {apk.name} does not match its checksum in SHA256SUMS (the file was changed)")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("Release check FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    count = sum(1 for p in ROOT.glob("*/*") if p.is_dir()) if ROOT.is_dir() else 0
    print(f"Release check OK ({count} release folder(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
