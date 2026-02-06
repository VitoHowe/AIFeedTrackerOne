# -*- coding: utf-8 -*-
"""
小红书请求签名与请求参数构建
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Dict, Tuple

import execjs

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
XS_JS_PATH = STATIC_DIR / "xhs_xs_xsc_56.js"
XRAY_JS_PATH = STATIC_DIR / "xhs_xray.js"


def _rewrite_xray_requires(content: str, base_dir: Path) -> str:
    static_dir = (base_dir / "static").resolve()
    pack_paths = {
        "xhs_xray_pack1.js": (static_dir / "xhs_xray_pack1.js").as_posix(),
        "xhs_xray_pack2.js": (static_dir / "xhs_xray_pack2.js").as_posix(),
    }
    prefixes = ("./", "./static/", "../static/")
    for filename, abs_path in pack_paths.items():
        for prefix in prefixes:
            content = content.replace(f"require('{prefix}{filename}')", f"require('{abs_path}')")
            content = content.replace(f'require("{prefix}{filename}")', f'require("{abs_path}")')
    return content


def _load_js_context(
    js_path: Path,
    cwd: Path | None = None,
    rewrite_xray_requires: bool = False,
    rewrite_base_dir: Path | None = None,
) -> execjs.ExternalRuntime.Context:
    if not js_path.exists():
        raise FileNotFoundError(f"JS 文件不存在: {js_path}")
    content = js_path.read_text(encoding="utf-8")
    if rewrite_xray_requires:
        base_dir = rewrite_base_dir or js_path.parent
        content = _rewrite_xray_requires(content, base_dir)
    if cwd is not None:
        cwd_str = str(cwd).replace("\\", "\\\\")
        content = f"process.chdir('{cwd_str}');\n{content}"
    return execjs.compile(content)

try:
    XS_CTX = _load_js_context(XS_JS_PATH)
except Exception as exc:
    XS_CTX = None
    logger.error("加载小红书签名 JS 失败: %s", exc)

try:
    XRAY_CTX = _load_js_context(
        XRAY_JS_PATH,
        cwd=BASE_DIR,
        rewrite_xray_requires=True,
        rewrite_base_dir=BASE_DIR,
    )
except Exception as exc:
    XRAY_CTX = None
    logger.error("加载小红书 xray JS 失败: %s", exc)


def parse_cookies(cookies_str: str) -> Dict[str, str]:
    cookies_str = cookies_str or ""
    if "; " in cookies_str:
        pairs = cookies_str.split("; ")
    else:
        pairs = cookies_str.split(";")
    cookies = {}
    for item in pairs:
        if not item:
            continue
        key, _, value = item.partition("=")
        cookies[key.strip()] = value.strip()
    return cookies


def generate_x_b3_traceid(length: int = 16) -> str:
    return "".join(random.choice("abcdef0123456789") for _ in range(length))


def generate_xray_traceid() -> str:
    if XRAY_CTX is None:
        return generate_x_b3_traceid(16)
    try:
        return XRAY_CTX.call("traceId")
    except Exception as exc:
        logger.warning("生成 xray traceId 失败，使用随机值: %s", exc)
        return generate_x_b3_traceid(16)


def get_request_headers_template() -> Dict[str, str]:
    """
    构建完整的Windows Chrome浏览器请求头模板
    包含所有必要的浏览器指纹特征，用于伪装成真实的Windows桌面浏览器
    """
    return {
        "authority": "edith.xiaohongshu.com",
        "accept": "application/json, text/plain, */*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "cache-control": "no-cache",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://www.xiaohongshu.com",
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": "https://www.xiaohongshu.com/",
        # Chrome 131 版本的 sec-ch-ua 格式
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        # Windows 10 + Chrome 131 的标准 User-Agent
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "x-b3-traceid": "",
        "x-mns": "unload",
        "x-s": "",
        "x-s-common": "",
        "x-t": "",
        "x-xray-traceid": generate_xray_traceid(),
    }


def _generate_xs_xs_common(
    a1: str, api: str, data: Dict | str, method: str
) -> Tuple[str, str, str]:
    if XS_CTX is None:
        raise RuntimeError("签名 JS 未加载，无法生成小红书签名")
    ret = XS_CTX.call("get_request_headers_params", api, data, a1, method)
    return ret["xs"], ret["xt"], ret["xs_common"]


def generate_headers(a1: str, api: str, data: Dict | str | None, method: str) -> Tuple[Dict[str, str], str]:
    payload = ""
    data_for_sign = data if data is not None else ""
    xs, xt, xs_common = _generate_xs_xs_common(a1, api, data_for_sign, method)
    if data:
        payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    headers = get_request_headers_template()
    headers["x-s"] = xs
    headers["x-t"] = str(xt)
    headers["x-s-common"] = xs_common
    headers["x-b3-traceid"] = generate_x_b3_traceid()
    return headers, payload


def generate_request_params(
    cookies_str: str, api: str, data: Dict | str | None, method: str
) -> Tuple[Dict[str, str], Dict[str, str], str]:
    cookies = parse_cookies(cookies_str)
    a1 = cookies.get("a1")
    if not a1:
        raise ValueError("XHS_COOKIE 缺少 a1 字段，无法生成签名")
    headers, payload = generate_headers(a1, api, data, method)
    return headers, cookies, payload


def splice_str(api: str, params: Dict[str, str]) -> str:
    url = api + "?"
    for key, value in params.items():
        if value is None:
            value = ""
        url += f"{key}={value}&"
    return url[:-1]
