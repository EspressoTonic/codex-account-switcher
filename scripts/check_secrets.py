#!/usr/bin/env python3
"""Limited Git secret guard. Reports locations/rules, never matching values."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_NAMES = {"auth.json", ".credentials.json", "credentials.json", "profiles.json", ".env", "history.jsonl"}
PRIVATE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".age", ".log", ".db", ".sqlite", ".lock"}
RULES = [
    ("private key", re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----")),
    ("provider token", re.compile(rb"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("JWT", re.compile(rb"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b")),
    ("assigned secret", re.compile(rb'''(?i)["']?(?:access[_-]?token|refresh[_-]?token|api[_-]?key|client[_-]?secret|bearer)["']?\s*[:=]\s*["'][A-Za-z0-9_./+=-]{24,}["']''')),
]


def inspect(name, data):
    path = Path(name)
    private = path.name in PRIVATE_NAMES or path.suffix in PRIVATE_SUFFIXES
    private |= path.name.startswith(".env.") and path.name != ".env.example"
    private |= any(part in {"homes", "sessions", "secrets", "local-data", "captures", "diagnostics"} for part in path.parts)
    findings = [(name, "private runtime file")] if private else []
    for rule, pattern in RULES:
        found = pattern.search(data)
        if found:
            findings.append((name + ":" + str(data[:found.start()].count(b"\n") + 1), rule))
    return findings


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def main():
    options = argparse.ArgumentParser(description=__doc__)
    options.add_argument("--history", action="store_true", help="Inspect every reachable blob, including deleted files.")
    arguments = options.parse_args()
    entries = []
    if arguments.history:
        for line in git("rev-list", "--objects", "--all").decode().splitlines():
            value = line.split(" ", 1)
            if len(value) == 2 and git("cat-file", "-t", value[0]).strip() == b"blob":
                entries.append((value[1], git("cat-file", "blob", value[0])))
    else:
        names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
        for name in sorted(set(names) - {""}):
            if (ROOT / name).is_file():
                entries.append((name, (ROOT / name).read_bytes()))
    findings = sorted(set(item for name, data in entries for item in inspect(name, data)))
    for name, rule in findings:
        print("BLOCKED: " + name + " (" + rule + "; value redacted)", file=sys.stderr)
    if findings:
        print("Remove private data before commit. Revoke any real exposed credentials.", file=sys.stderr)
        return 1
    print("Secret guard: no covered patterns in " + str(len(entries)) + " files/blobs; manual review still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
