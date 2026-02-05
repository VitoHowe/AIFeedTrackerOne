# -*- coding: utf-8 -*-
"""
配置管理模块

统一管理项目的配置信息，包括环境变量加载和常量定义
"""

import os
from pathlib import Path
from typing import Dict, Optional

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(*args, **kwargs):
        """备用函数，避免导入错误"""
        pass


# 加载.env文件
project_root = Path(__file__).parent
env_file = project_root / ".env"

# API配置
BILI_SPACE_API = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
BILI_VIDEO_API = "https://api.bilibili.com/x/web-interface/view"

# 配置容器（热更新时就地更新）
FEISHU_CONFIG: Dict[str, Optional[str]] = {}
BILIBILI_CONFIG: Dict[str, Optional[str]] = {}
AI_CONFIG: Dict[str, Optional[str]] = {}
XHS_CONFIG: Dict[str, Optional[str]] = {}
PANEL_CONFIG: Dict[str, Optional[str]] = {}
ANTI_BAN_CONFIG: Dict[str, object] = {}
USER_AGENT = ""


def _get_int_env(name: str, default: int) -> int:
    """安全读取整数环境变量"""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _load_env() -> None:
    if env_file.exists():
        load_dotenv(env_file, override=True)


def _strip_wrapping_quotes(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
        return value[1:-1]
    return value


def reload_config() -> None:
    """热更新配置（就地更新配置字典）"""
    _load_env()

    FEISHU_CONFIG.clear()
    FEISHU_CONFIG.update(
        {
            "app_id": os.getenv("app_id"),
            "app_secret": os.getenv("app_secret"),
            "template_id": os.getenv("FEISHU_TEMPLATE_ID", "YOUR_TEMPLATE_ID"),
            "template_version_name": os.getenv("FEISHU_TEMPLATE_VERSION", "1.0.0"),
            "user_open_id": os.getenv("FEISHU_USER_OPEN_ID", "YOUR_USER_OPEN_ID"),
        }
    )

    BILIBILI_CONFIG.clear()
    BILIBILI_CONFIG.update(
        {
            "SESSDATA": os.getenv("SESSDATA"),
            "bili_jct": os.getenv("bili_jct"),
            "buvid3": os.getenv("buvid3"),
            "DedeUserID": os.getenv("DedeUserID"),
            "DedeUserID__ckMd5": os.getenv("DedeUserID__ckMd5"),
            "refresh_token": os.getenv("refresh_token"),
        }
    )

    AI_CONFIG.clear()
    AI_CONFIG.update(
        {
            "service": os.getenv("AI_SERVICE", "deepseek"),
            "api_key": os.getenv("AI_API_KEY"),
            "base_url": os.getenv("AI_BASE_URL"),
            "model": os.getenv("AI_MODEL"),
        }
    )

    XHS_CONFIG.clear()
    XHS_CONFIG.update(
        {
            "cookie": _strip_wrapping_quotes(os.getenv("XHS_COOKIE")),
            "prompt": os.getenv("XHS_PROMPT"),
            "text_hint_max_len": _get_int_env("XHS_TEXT_HINT_MAX_LEN", 800),
        }
    )

    global USER_AGENT
    env_ua = _strip_wrapping_quotes(os.getenv("USER_AGENT"))
    USER_AGENT = env_ua or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    PANEL_CONFIG.clear()
    PANEL_CONFIG.update(
        {
            "host": os.getenv("PANEL_HOST", "127.0.0.1"),
            "port": _get_int_env("PANEL_PORT", 8765),
            "admin_token": os.getenv("PANEL_ADMIN_TOKEN"),
        }
    )

    ANTI_BAN_CONFIG.clear()
    ANTI_BAN_CONFIG.update(
        {
            "user_agent": USER_AGENT,
            "request_delay": (1, 3),
            "timeout": 30,
        }
    )


def build_bilibili_cookie() -> Optional[str]:
    """构建B站请求所需的Cookie字符串"""
    parts = []
    for key, value in BILIBILI_CONFIG.items():
        if value:
            parts.append(f"{key}={value}")
    return "; ".join(parts) if parts else None


def get_config_status() -> dict:
    """获取配置状态，用于诊断"""
    return {
        "env_file_exists": env_file.exists(),
        "feishu_configured": bool(
            FEISHU_CONFIG["app_id"] and FEISHU_CONFIG["app_secret"]
        ),
        "bilibili_configured": bool(BILIBILI_CONFIG["SESSDATA"]),
        "xhs_configured": bool(XHS_CONFIG.get("cookie")),
        "cookie_available": bool(build_bilibili_cookie()),
    }


reload_config()


if __name__ == "__main__":
    # 配置状态检查
    status = get_config_status()
    print("配置状态检查:")
    for key, value in status.items():
        mark = "OK" if value else "NO"
        print(f"  [{mark}] {key}: {value}")

    if status["cookie_available"]:
        print(f"\nB站Cookie: {build_bilibili_cookie()[:50]}...")
