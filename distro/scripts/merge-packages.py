#!/usr/bin/env python3
"""Merge Archiso package lists, preserving base order and deduplicating."""

import argparse
from pathlib import Path


def package_names(path: Path) -> list[str]:
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            names.append(name)
    return names


def merge(base: Path, additions: Path) -> list[str]:
    result = []
    seen = set()
    for path in (base, additions):
        for name in package_names(path):
            if name not in seen:
                result.append(name)
                seen.add(name)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("additions", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    packages = merge(args.base, args.additions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(packages) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
