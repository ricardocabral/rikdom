#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path



def parse_issue_file(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"{path} must start with '# <title>'")
    title = lines[0][2:].strip()
    body = "\n".join(lines[1:]).strip()
    return title, body



def create_issue(repo: str, title: str, body: str) -> None:
    subprocess.run(
        ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body],
        check=True,
    )



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--issues-dir", default="roadmap/issues")
    args = parser.parse_args()

    issue_dir = Path(args.issues_dir)
    files = sorted(issue_dir.glob("*.md"))
    if not files:
        raise SystemExit(f"No issue files found in {issue_dir}")

    for path in files:
        title, body = parse_issue_file(path)
        print(f"Creating issue: {title}")
        create_issue(args.repo, title, body)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
