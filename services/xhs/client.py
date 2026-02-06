# -*- coding: utf-8 -*-
"""
小红书 API 客户端（PC Web）
使用 curl_cffi 模拟 Chrome 浏览器 TLS/JA3 指纹，绕过反爬检测
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import string
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from curl_cffi.requests import AsyncSession

from .signer import generate_request_params, splice_str, parse_cookies
from config import ANTI_BAN_CONFIG


_BASE36 = string.ascii_lowercase + string.digits


def _random_base36(length: int) -> str:
    return "".join(random.choice(_BASE36) for _ in range(length))


def _generate_request_id() -> str:
    return f"{random.randint(10000000, 99999999)}-{int(time.time() * 1000)}"


class XHSClient:
    """
    小红书 API 客户端
    使用 curl_cffi 模拟完整的 Chrome 浏览器 TLS/JA3 指纹
    支持 HTTP/2，自动处理压缩，完美伪装成真实浏览器
    """
    
    # Chrome 浏览器版本，用于 curl_cffi 的 impersonate 参数
    # 支持的版本: chrome99, chrome100, chrome101, chrome104, chrome107, chrome110, 
    #            chrome116, chrome119, chrome120, chrome123, chrome124, chrome131 等
    BROWSER_IMPERSONATE = "chrome131"
    
    def __init__(self, cookies_str: str, timeout: int = 30):
        self.base_url = "https://edith.xiaohongshu.com"
        self.cookies_str = cookies_str or ""
        self.timeout = timeout
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Windows 10 + Chrome 131 的标准 User-Agent
        self.browser_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
        # Chrome 131 版本的 sec-ch-ua 格式
        self.browser_sec_ch_ua = '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"'

    def _build_browser_headers(self, referer: str) -> Dict[str, str]:
        """
        构建完整的浏览器请求头，用于访问小红书网页
        包含所有必要的浏览器指纹特征
        """
        return {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "priority": "u=0, i",
            "referer": referer,
            "sec-ch-ua": self.browser_sec_ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "user-agent": self.browser_user_agent,
        }

    async def _request(
        self,
        session: AsyncSession,
        method: str,
        api: str,
        params: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        发送 API 请求，使用 curl_cffi 模拟 Chrome 浏览器指纹
        """
        retry_delay = ANTI_BAN_CONFIG.get("api_retry_delay", 30)
        api_path = api
        last_error: Optional[Exception] = None
        
        for attempt in range(2):
            try:
                api_with_params = splice_str(api_path, params) if params else api_path
                headers, cookies, payload = generate_request_params(
                    self.cookies_str, api_with_params, data, method
                )
                url = self.base_url + api_with_params
                self.logger.debug("XHS %s %s", method, url)
                
                if method.upper() == "GET":
                    resp = await session.get(
                        url, 
                        headers=headers, 
                        cookies=cookies, 
                        timeout=self.timeout,
                        impersonate=self.BROWSER_IMPERSONATE
                    )
                else:
                    resp = await session.post(
                        url, 
                        headers=headers, 
                        data=payload, 
                        cookies=cookies, 
                        timeout=self.timeout,
                        impersonate=self.BROWSER_IMPERSONATE
                    )
                
                res_json = resp.json()

                if (
                    isinstance(res_json, dict)
                    and res_json.get("success") is False
                    and attempt == 0
                ):
                    self.logger.warning(
                        "XHS API 返回失败，%s 秒后重试: api=%s, code=%s, msg=%s",
                        retry_delay,
                        api_with_params,
                        res_json.get("code"),
                        res_json.get("msg"),
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                return res_json
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    self.logger.warning(
                        "XHS API 请求异常，%s 秒后重试: api=%s, err=%s",
                        retry_delay,
                        api_with_params,
                        exc,
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                break
        self.logger.error("XHS API 请求失败: %s", last_error)
        return {}

    async def search_user(
        self, session: AsyncSession, query: str, page: int = 1
    ) -> Tuple[bool, str, Dict[str, Any]]:
        api = "/api/sns/web/v1/search/usersearch"
        data = {
            "search_user_request": {
                "keyword": query,
                "search_id": _random_base36(21),
                "page": page,
                "page_size": 15,
                "biz_type": "web_search_user",
                "request_id": _generate_request_id(),
            }
        }
        try:
            res_json = await self._request(session, "POST", api, data=data)
            return bool(res_json.get("success")), res_json.get("msg", ""), res_json
        except Exception as exc:
            return False, str(exc), {}

    async def get_user_note_info(
        self,
        session: AsyncSession,
        user_id: str,
        cursor: str,
        xsec_token: str,
        xsec_source: str = "pc_search",
    ) -> Tuple[bool, str, Dict[str, Any]]:
        api = "/api/sns/web/v1/user_posted"
        params = {
            "num": "30",
            "cursor": cursor,
            "user_id": user_id,
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token or "",
            "xsec_source": xsec_source or "pc_search",
        }
        try:
            res_json = await self._request(session, "GET", api, params=params)
            return bool(res_json.get("success")), res_json.get("msg", ""), res_json
        except Exception as exc:
            return False, str(exc), {}


    async def fetch_profile_page(self, session: AsyncSession, user_id: str) -> str:
        """
        获取用户主页 HTML，使用 curl_cffi 模拟 Chrome 浏览器
        """
        url = f"https://www.xiaohongshu.com/user/profile/{user_id}"
        headers = self._build_browser_headers("https://www.xiaohongshu.com/")
        cookies = parse_cookies(self.cookies_str)
        
        resp = await session.get(
            url,
            headers=headers,
            cookies=cookies,
            timeout=self.timeout,
            impersonate=self.BROWSER_IMPERSONATE
        )
        
        # 调试日志：记录响应状态和内容长度
        html = resp.text
        self.logger.debug(
            "获取用户主页: user_id=%s, status=%s, html_len=%d",
            user_id, resp.status_code, len(html)
        )
        
        # 如果 HTML 太短或包含验证页面特征，记录警告
        if len(html) < 1000 or "验证" in html or "captcha" in html.lower():
            self.logger.warning(
                "用户主页可能被拦截: user_id=%s, status=%s, html_preview=%s",
                user_id, resp.status_code, html[:200]
            )
        
        return html

    async def fetch_note_page(
        self,
        session: AsyncSession,
        note_id: str,
        xsec_token: str = "",
        xsec_source: str = "pc_search",
    ) -> str:
        """
        获取笔记页面 HTML，使用 curl_cffi 模拟 Chrome 浏览器
        """
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if xsec_token:
            url = f"{url}?xsec_token={xsec_token}&xsec_source={xsec_source}"
        headers = self._build_browser_headers("https://www.xiaohongshu.com/")
        cookies = parse_cookies(self.cookies_str)
        
        resp = await session.get(
            url,
            headers=headers,
            cookies=cookies,
            timeout=self.timeout,
            impersonate=self.BROWSER_IMPERSONATE
        )
        
        # 调试日志：记录响应状态和内容长度
        html = resp.text
        self.logger.debug(
            "获取笔记页面: note_id=%s, status=%s, html_len=%d, url=%s",
            note_id, resp.status_code, len(html), url
        )
        
        # 如果 HTML 太短或包含验证页面特征，记录警告
        if len(html) < 1000 or "验证" in html or "captcha" in html.lower():
            self.logger.warning(
                "笔记页面可能被拦截: note_id=%s, status=%s, html_preview=%s",
                note_id, resp.status_code, html[:200]
            )
        
        return html

    @staticmethod
    def extract_xsec_from_html(html: str) -> Tuple[str, str]:
        token = ""
        source = ""
        if not html:
            return token, source
        token_match = re.search(r"xsec_token=([^&\"']+)", html)
        if token_match:
            token = urllib.parse.unquote(token_match.group(1))
        source_match = re.search(r"xsec_source=([^&\"']+)", html)
        if source_match:
            source = urllib.parse.unquote(source_match.group(1))
        return token, source

    async def get_profile_xsec_token(
        self, session: AsyncSession, user_id: str
    ) -> Tuple[bool, str, Tuple[str, str]]:
        try:
            html = await self.fetch_profile_page(session, user_id)
            token, source = self.extract_xsec_from_html(html)
            if not token:
                return False, "profile html missing xsec_token", ("", "")
            return True, "", (token, source)
        except Exception as exc:
            return False, str(exc), ("", "")

    async def get_note_xsec_token(
        self,
        session: AsyncSession,
        note_id: str,
        xsec_token: str = "",
        xsec_source: str = "pc_search",
    ) -> Tuple[bool, str, Tuple[str, str]]:
        try:
            html = await self.fetch_note_page(session, note_id, xsec_token, xsec_source)
            token, source = self.extract_xsec_from_html(html)
            if not token:
                return False, "note html missing xsec_token", ("", "")
            return True, "", (token, source)
        except Exception as exc:
            return False, str(exc), ("", "")

    async def get_note_info(
        self, session: AsyncSession, note_url: str
    ) -> Tuple[bool, str, Dict[str, Any]]:
        url_parse = urllib.parse.urlparse(note_url)
        note_id = url_parse.path.split("/")[-1]
        kvs = url_parse.query.split("&") if url_parse.query else []
        kv_dist = {}
        for kv in kvs:
            if "=" not in kv:
                continue
            key, value = kv.split("=", 1)
            kv_dist[key] = urllib.parse.unquote(value)
        xsec_token = kv_dist.get("xsec_token")
        xsec_source = kv_dist.get("xsec_source", "pc_search")
        if not xsec_token:
            return False, "note_url 缺少 xsec_token", {}
        api = "/api/sns/web/v1/feed"
        data = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": "1"},
            "xsec_source": xsec_source,
            "xsec_token": xsec_token,
        }
        try:
            res_json = await self._request(session, "POST", api, data=data)
            return bool(res_json.get("success")), res_json.get("msg", ""), res_json
        except Exception as exc:
            return False, str(exc), {}

    @staticmethod
    def build_note_url(note_id: str, xsec_token: str, xsec_source: str = "pc_search") -> str:
        safe_token = urllib.parse.quote(xsec_token or "", safe="")
        safe_source = urllib.parse.quote(xsec_source or "", safe="")
        return (
            f"https://www.xiaohongshu.com/explore/{note_id}"
            f"?xsec_token={safe_token}&xsec_source={safe_source}"
        )

    @staticmethod
    def extract_image_urls(note_card: Dict[str, Any]) -> List[str]:
        images: List[str] = []
        for img in note_card.get("image_list", []) or []:
            info_list = img.get("info_list") or []
            url = None
            if info_list:
                url = info_list[-1].get("url") or info_list[0].get("url")
            if not url:
                url = img.get("url")
            if url:
                images.append(url)
        return images


    @staticmethod
    def extract_image_urls_from_note(note: Dict[str, Any]) -> List[str]:
        if not note:
            return []
        note_card = note.get("note_card") or {}
        if note_card:
            return XHSClient.extract_image_urls(note_card)
        images: List[str] = []
        seen = set()
        for img in note.get("image_list", []) or []:
            info_list = img.get("info_list") or []
            url = None
            if info_list:
                url = info_list[-1].get("url") or info_list[0].get("url")
            if not url:
                url = img.get("url")
            if url:
                if url not in seen:
                    images.append(url)
                    seen.add(url)
        cover = note.get("cover")
        if isinstance(cover, dict):
            info_list = cover.get("info_list") or []
            for info in info_list:
                url = info.get("url")
                if url and url not in seen:
                    images.append(url)
                    seen.add(url)
            for key in ("url", "url_default", "url_pre"):
                url = cover.get(key)
                if url and url not in seen:
                    images.append(url)
                    seen.add(url)
        elif isinstance(cover, str):
            if cover and cover not in seen:
                images.append(cover)
        return images
