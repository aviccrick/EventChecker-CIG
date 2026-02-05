from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Optional, Dict, Any

DEFAULT_INTERVAL_MINUTES = 360  # 6 hours


@dataclass
class HelperState:
    running: bool = False
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    last_error: str = ""
    paused: bool = False
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES


def load_config(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"interval_minutes": DEFAULT_INTERVAL_MINUTES, "paused": False}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {
            "interval_minutes": int(data.get("interval_minutes", DEFAULT_INTERVAL_MINUTES)),
            "paused": bool(data.get("paused", False)),
        }
    except Exception:
        return {"interval_minutes": DEFAULT_INTERVAL_MINUTES, "paused": False}


def save_config(path: str, interval_minutes: int, paused: bool) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"interval_minutes": int(interval_minutes), "paused": bool(paused)}
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def compute_next_run(
    now: datetime,
    interval_minutes: int,
    paused: bool,
    last_run: Optional[datetime],
) -> Optional[datetime]:
    if paused:
        return None
    if last_run is None:
        return now + timedelta(minutes=interval_minutes)
    return last_run + timedelta(minutes=interval_minutes)
