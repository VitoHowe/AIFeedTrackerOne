# -*- coding: utf-8 -*-
"""
小红书 API 客户端（PC Web）
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from .signer import generate_request_params, splice_str, generate_x_b3_traceid


class XHSClient:
    def __init__(self, cookies_str: str, timeout: int = 30):
        self.base_url = "https://edith.xiaohongshu.com"
        self.cookies_str = cookies_str or ""
        self.timeout = timeout
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def _request(
        self,
        session: aiohttp.ClientSession,
        method: str,
        api: str,
        params: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if params:
            api = splice_str(api, params)
        headers, cookies, payload = generate_request_params(
            self.cookies_str, api, data, method
        )
        url = self.base_url + api
        self.logger.debug("XHS %s %s", method, url)
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        if method.upper() == "GET":
            async with session.get(url, headers=headers, cookies=cookies, timeout=timeout) as resp:
                return await resp.json()
        async with session.post(
            url, headers=headers, data=payload, cookies=cookies, timeout=timeout
        ) as resp:
            return await resp.json()

    async def search_user(
        self, session: aiohttp.ClientSession, query: str, page: int = 1
    ) -> Tuple[bool, str, Dict[str, Any]]:
        api = "/api/sns/web/v1/search/usersearch"
        data = {
            "search_user_request": {
                "keyword": query,
                "search_id": generate_x_b3_traceid(21),
                "page": page,
                "page_size": 15,
                "biz_type": "web_search_user",
                "request_id": generate_x_b3_traceid(16),
            }
        }
        try:
            res_json = await self._request(session, "POST", api, data=data)
            return bool(res_json.get("success")), res_json.get("msg", ""), res_json
        except Exception as exc:
            return False, str(exc), {}

    async def get_user_note_info(
        self,
        session: aiohttp.ClientSession,
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

    async def get_note_info(
        self, session: aiohttp.ClientSession, note_url: str
    ) -> Tuple[bool, str, Dict[str, Any]]:
        url_parse = urllib.parse.urlparse(note_url)
        note_id = url_parse.path.split("/")[-1]
        kvs = url_parse.query.split("&") if url_parse.query else []
        kv_dist = {}
        for kv in kvs:
            if "=" not in kv:
                continue
            key, value = kv.split("=", 1)
            kv_dist[key] = value
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
        return (
            f"https://www.xiaohongshu.com/explore/{note_id}"
            f"?xsec_token={xsec_token}&xsec_source={xsec_source}"
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
