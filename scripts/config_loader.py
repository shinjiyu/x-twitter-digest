#!/usr/bin/env python3
"""Load accounts.json → camp map / account list."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CFG = ROOT / "accounts.json"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path or os.environ.get("ACCOUNTS_FILE") or DEFAULT_CFG)
    data = json.loads(p.read_text(encoding="utf-8"))
    camps = data.get("camps") or {}
    if "Z" not in camps:
        camps["Z"] = {"name": "其他", "emoji": "·", "order": 99, "color": "#6b7280"}
    data["camps"] = camps
    return data


def account_camp_lookup(cfg: dict[str, Any]) -> dict[str, tuple[str, str, str, str]]:
    """screen_name → (camp_id, name, emoji, color). Case-sensitive + lower alias."""
    camps = cfg.get("camps") or {}
    out: dict[str, tuple[str, str, str, str]] = {}
    for acc in cfg.get("accounts") or []:
        sn = (acc.get("screen_name") or "").lstrip("@")
        if not sn:
            continue
        cid = acc.get("camp") or "Z"
        meta = camps.get(cid) or camps.get("Z") or {}
        tup = (
            cid,
            meta.get("name") or cid,
            meta.get("emoji") or "·",
            meta.get("color") or "#6b7280",
        )
        out[sn] = tup
        out[sn.lower()] = tup
    return out


def camp_order_map(cfg: dict[str, Any]) -> dict[str, int]:
    camps = cfg.get("camps") or {}
    return {cid: int(meta.get("order", 99)) for cid, meta in camps.items()}


def camp_meta(cfg: dict[str, Any], camp_id: str) -> dict[str, Any]:
    camps = cfg.get("camps") or {}
    return camps.get(camp_id) or camps.get("Z") or {
        "name": camp_id,
        "emoji": "·",
        "order": 99,
        "color": "#6b7280",
    }
