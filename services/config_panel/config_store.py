# -*- coding: utf-8 -*-
"""
配置读写模块

- 读取/更新 .env 配置（保留未知行和注释）
- 读取/更新 B 站监控博主列表
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
CREATORS_PATH = PROJECT_ROOT / "data" / "bilibili_creators.json"
CREATORS_EXAMPLE_PATH = PROJECT_ROOT / "data" / "bilibili_creators.json.example"
XHS_CREATORS_PATH = PROJECT_ROOT / "data" / "xhs_creators.json"
XHS_CREATORS_EXAMPLE_PATH = PROJECT_ROOT / "data" / "xhs_creators.json.example"


def _load_env_lines(env_path: Path) -> List[str]:
    if not env_path.exists():
        return []
    with open(env_path, "r", encoding="utf-8") as f:
        return f.readlines()


def _env_key_from_line(line: str) -> Optional[str]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if "=" not in line:
        return None
    key = line.split("=", 1)[0].strip()
    return key or None


def _env_value_from_line(line: str) -> str:
    return line.split("=", 1)[1].rstrip("\r\n")


def read_env_values(keys: Iterable[str], env_path: Path = ENV_PATH) -> Dict[str, Optional[str]]:
    values: Dict[str, Optional[str]] = {key: None for key in keys}
    for line in _load_env_lines(env_path):
        key = _env_key_from_line(line)
        if key and key in values:
            values[key] = _env_value_from_line(line)
    return values


def _quote_env_value(value: str) -> str:
    if value == "":
        return value
    needs_quotes = any(ch.isspace() for ch in value) or "#" in value
    if not needs_quotes:
        return value
    escaped = value.replace("\"", "\\\"")
    return f"\"{escaped}\""


def _normalize_env_updates(updates: Dict[str, Optional[str]]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for key, value in updates.items():
        if value is None:
            continue
        normalized[key] = _quote_env_value(str(value))
    return normalized


def update_env_values(
    updates: Dict[str, Optional[str]],
    env_path: Path = ENV_PATH,
) -> None:
    normalized = _normalize_env_updates(updates)
    if not normalized:
        return

    lines = _load_env_lines(env_path)
    remaining = set(normalized.keys())

    for index, line in enumerate(lines):
        key = _env_key_from_line(line)
        if key in normalized:
            lines[index] = f"{key}={normalized[key]}\n"
            remaining.discard(key)

    if remaining:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] = f"{lines[-1]}\n"
        if lines and lines[-1].strip():
            lines.append("\n")
        for key in sorted(remaining):
            lines.append(f"{key}={normalized[key]}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _validate_creators(creators: List[dict]) -> None:
    if not isinstance(creators, list):
        raise ValueError("creators 必须是列表")
    for item in creators:
        if not isinstance(item, dict) or "uid" not in item:
            raise ValueError("每个 creator 必须包含 uid 字段")


def _validate_xhs_creators(creators: List[dict]) -> None:
    if not isinstance(creators, list):
        raise ValueError("xhs_creators 必须是列表")
    for item in creators:
        if not isinstance(item, dict) or "red_id" not in item:
            raise ValueError("每个 xhs creator 必须包含 red_id 字段")


def read_creators(path: Path = CREATORS_PATH) -> List[dict]:
    target = path if path.exists() else CREATORS_EXAMPLE_PATH
    if not target.exists():
        return []
    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("creators 文件必须是数组")
    _validate_creators(data)
    return data


def write_creators(creators: List[dict], path: Path = CREATORS_PATH) -> None:
    _validate_creators(creators)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(creators, f, ensure_ascii=False, indent=2)
        f.write("\n")


def read_xhs_creators(path: Path = XHS_CREATORS_PATH) -> List[dict]:
    target = path if path.exists() else XHS_CREATORS_EXAMPLE_PATH
    if not target.exists():
        return []
    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("xhs_creators 文件必须是数组")
    _validate_xhs_creators(data)
    return data


def write_xhs_creators(creators: List[dict], path: Path = XHS_CREATORS_PATH) -> None:
    _validate_xhs_creators(creators)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(creators, f, ensure_ascii=False, indent=2)
        f.write("\n")
