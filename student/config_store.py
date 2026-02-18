# student/config_store.py
from __future__ import annotations
import json
import os
from pathlib import Path

APP_NAME = "PQLS"
CFG_NAME = "config.json"

def _appdata_dir() -> Path:
    # Win10: %APPDATA%/PQLS
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d

def load_config() -> dict:
    p = _appdata_dir() / CFG_NAME
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_config(cfg: dict):
    p = _appdata_dir() / CFG_NAME
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def get_library_dir() -> Path | None:
    cfg = load_config()
    v = cfg.get("library_dir")
    if not v:
        return None
    p = Path(v)
    return p if p.exists() else None

def set_library_dir(p: Path):
    cfg = load_config()
    cfg["library_dir"] = str(Path(p).resolve())
    save_config(cfg)
