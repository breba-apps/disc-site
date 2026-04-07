from __future__ import annotations

import json
from pathlib import Path

from breba_app.chainlit_bridge import BrebaMessage


def load_messages(case_dir: Path) -> list[BrebaMessage]:
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    return [BrebaMessage(role=m["role"], content=m["content"]) for m in case["messages"]]


def load_dir_texts(dir_path: Path) -> dict[str, str]:
    if not dir_path.exists():
        return {}
    out: dict[str, str] = {}
    for p in dir_path.rglob("*"):
        if p.is_file():
            rel = p.relative_to(dir_path).as_posix()
            out[rel] = p.read_text(encoding="utf-8")
    return out


def load_initial_files(case_dir: Path) -> dict[str, str]:
    return load_dir_texts(case_dir / "initial")


def load_evals(case_dir: Path) -> dict:
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    return case["evals"]
