#!/usr/bin/env python3
"""Checks Google Play release notes: each <lang>...</lang> block must fit in 500 characters.

Usage: python3 check_play_notes.py notes.txt
"""
import re
import sys

LIMIT = 500


def main(path: str) -> int:
    text = open(path, encoding="utf-8").read()
    blocks = re.findall(r"<([\w-]+)>\n?(.*?)\n?</\1>", text, re.S)
    if not blocks:
        print("No <lang>...</lang> block found")
        return 1
    ok = True
    for lang, body in blocks:
        size = len(body.strip())
        status = "OK" if size <= LIMIT else f"TOO LONG by {size - LIMIT}"
        ok &= size <= LIMIT
        print(f"{lang}: {size}/{LIMIT} {status}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
