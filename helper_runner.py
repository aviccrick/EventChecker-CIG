from __future__ import annotations

from pathlib import Path
from typing import List


def build_run_command(repo_root: Path) -> List[str]:
    python_path = repo_root / ".venv" / "bin" / "python3"
    checker_path = repo_root / "checker.py"
    return [str(python_path), str(checker_path)]
