"""Report the failing tests in a cargo test log as error annotations.

GitHub serves check-run annotations to anyone, while job logs need a login,
so annotations are how a failure here can be read without credentials. GitHub
keeps at most 10 error annotations per step, so this emits at most 10.

Usage: python annotate-failures.py <cargo test log>
"""

import re
import sys
from pathlib import Path


def esc(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def title(text):
    return esc(text).replace(":", "%3A").replace(",", "%2C")


def main():
    log = Path(sys.argv[1])
    if not log.exists():
        print(f"::error title=no test log::{esc(str(log))}")
        return
    text = log.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    failed = re.findall(r"^test (\S+) \.\.\. FAILED$", text, re.M)
    targets = re.findall(r"^error: test failed, to rerun pass (.+)$", text, re.M)
    sections = re.findall(
        r"^---- (\S+) stdout ----\n(.*?)(?=^---- |^failures:|\Z)", text, re.M | re.S
    )
    for name, body in sections[:9]:
        lines = [
            line
            for line in body.splitlines()
            if line.strip() and not line.startswith("note: run with")
        ]
        print(f"::error title={title(name)}::{esc(chr(10).join(lines[:12]))}")
    if failed or targets:
        summary = f"{len(failed)} failed: " + ", ".join(failed[:40])
        if targets:
            summary += " | rerun: " + "; ".join(targets)
    else:
        summary = "no failing test found; log tail:\n" + "\n".join(text.splitlines()[-25:])
    print(f"::error title=cargo test summary::{esc(summary)}")


if __name__ == "__main__":
    main()
