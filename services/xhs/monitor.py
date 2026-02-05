# -*- coding: utf-8 -*-
"""
小红书博主监控服务
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any, Dict, List, Optional

import aiofiles
import aiohttp

from config import XHS_CONFIG
from ..ai_summary.summary_generator import SummaryGenerator
from .client import XHSClient


@dataclass
class XHSCreator:
    red_id: str
    name: str
    check_interval: int = 600


class JsonState:
    def __init__(self, path: str):
        self.path = path
        self.state: Dict[str, Any] = {}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
            except Exception:
                self.state = {}
        else:
            self.state = {}

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def has_seen(self, red_id: str, note_id: str) -> bool:
        entry = self.state.get(red_id, {})
        return note_id in entry.get("seen", [])

    def mark_seen(self, red_id: str, note_id: str) -> None:
        entry = self.state.setdefault(red_id, {"seen": []})
        seen = entry.setdefault("seen", [])
        if note_id not in seen:
            seen.append(note_id)
        if len(seen) > 200:
            entry["seen"] = seen[-200:]


class XHSMonitorService:
    STATE_PATH = os.path.join("data", "xhs_state.json")
    CREATORS_PATH = os.path.join("data", "xhs_creators.json")

    DEFAULT_PROMPT = SummaryGenerator.XHS_IMAGE_PROMPT
    TEXT_HINT_MAX_LEN = 800

    def __init__(self, feishu_bot=None, summarizer=None, cookie: Optional[str] = None):
        self.feishu_bot = feishu_bot
        self.summarizer = summarizer
        self.cookie = cookie or XHS_CONFIG.get("cookie")
        self.prompt = XHS_CONFIG.get("prompt") or self.DEFAULT_PROMPT
        self.text_hint_max_len = int(
            XHS_CONFIG.get("text_hint_max_len", self.TEXT_HINT_MAX_LEN)
        )
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.state = JsonState(self.STATE_PATH)

        if not self.cookie:
            self.logger.warning("未配置 XHS_COOKIE，小红书监控将跳过")

        self.client = XHSClient(self.cookie or "")

    @staticmethod
    def _is_today(timestamp_ms: int) -> bool:
        try:
            note_date = datetime.fromtimestamp(timestamp_ms / 1000).date()
            return note_date == date.today()
        except Exception:
            return False

    @staticmethod
    def load_creators_from_file(path: str = CREATORS_PATH) -> List[XHSCreator]:
        os.makedirs(os.path.dirname(path), exist_ok=True)

        default = [
            {"red_id": "579739786", "name": "许小喵", "check_interval": 600},
        ]

        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)

        try:
            with open(path, "r", encoding="utf-8") as f:
                items = json.load(f)
            creators = []
            for item in items:
                creators.append(
                    XHSCreator(
                        red_id=str(item["red_id"]),
                        name=str(item.get("name") or item["red_id"]),
                        check_interval=int(item.get("check_interval", 600)),
                    )
                )
            return creators
        except Exception:
            return [
                XHSCreator(
                    red_id=str(i["red_id"]),
                    name=str(i.get("name") or i["red_id"]),
                    check_interval=int(i.get("check_interval", 600)),
                )
                for i in default
            ]

    async def _resolve_user(
        self, session: aiohttp.ClientSession, creator: XHSCreator
    ) -> Optional[Dict[str, str]]:
        def _extract_profile_id(raw: str) -> str:
            if not raw:
                return ""
            if "xiaohongshu.com/user/profile/" in raw:
                raw = raw.split("xiaohongshu.com/user/profile/")[-1]
                raw = raw.split("?")[0]
            return raw

        def _is_profile_id(raw: str) -> bool:
            return bool(re.fullmatch(r"[0-9a-f]{24}", raw))

        async def _search(keyword: str):
            ok, msg, res = await self.client.search_user(session, keyword, page=1)
            if not ok:
                self.logger.warning(
                    "??????: %s, msg=%s, code=%s",
                    keyword,
                    msg,
                    res.get("code"),
                )
                return None, res
            users = res.get("data", {}).get("users", [])
            if not users:
                self.logger.warning("???????: %s", keyword)
            return users, res

        raw_id = _extract_profile_id(creator.red_id)
        if _is_profile_id(raw_id):
            ok, msg, token_data = await self.client.get_profile_xsec_token(session, raw_id)
            if not ok:
                self.logger.warning("?? profile xsec_token ??: %s, msg=%s", raw_id, msg)
            token, source = token_data
            return {
                "user_id": raw_id,
                "xsec_token": token or "",
                "xsec_source": source or "pc_user",
                "name": creator.name,
            }

        users, _ = await _search(raw_id)
        if not users and creator.name and creator.name != raw_id:
            users, _ = await _search(creator.name)
        if not users:
            return None
        target = None
        for u in users:
            if str(u.get("red_id")) == raw_id:
                target = u
                break
        if not target:
            target = users[0]
        return {
            "user_id": str(target.get("id") or target.get("user_id") or ""),
            "xsec_token": target.get("xsec_token") or "",
            "xsec_source": target.get("xsec_source") or "pc_search",
            "name": target.get("name") or creator.name,
        }

    async def _download_images(
        self,
        session: aiohttp.ClientSession,
        creator: XHSCreator,
        note_id: str,
        image_urls: List[str],
    ) -> List[Dict[str, str]]:
        saved: List[Dict[str, str]] = []
        base_dir = os.path.join("data", "xhs_media", creator.red_id, note_id)
        os.makedirs(base_dir, exist_ok=True)
        for idx, url in enumerate(image_urls, 1):
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    content = await resp.read()
                filename = os.path.join(base_dir, f"{idx}.jpg")
                async with aiofiles.open(filename, "wb") as f:
                    await f.write(content)
                b64 = base64.b64encode(content).decode("utf-8")
                saved.append({"path": filename, "base64": b64, "url": url})
            except Exception as exc:
                self.logger.warning("下载图片失败: %s, err=%s", url, exc)
        return saved

    async def _fetch_images_base64(
        self, session: aiohttp.ClientSession, image_urls: List[str]
    ) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        for url in image_urls[:4]:
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    content = await resp.read()
                    content_type = resp.headers.get("Content-Type", "image/jpeg")
                mime = content_type.split(";")[0] if content_type else "image/jpeg"
                b64 = base64.b64encode(content).decode("utf-8")
                results.append({"mime": mime, "base64": b64, "url": url})
            except Exception as exc:
                self.logger.warning("读取图片失败: %s, err=%s", url, exc)
        return results

    async def _summarize_images(
        self, images: List[Dict[str, str]], text_hint: str = ""
    ) -> Optional[str]:
        if not self.summarizer or not images:
            return None
        payloads = [{"mime": "image/jpeg", "base64": img["base64"]} for img in images]
        prompt = self.prompt
        if text_hint:
            prompt = f"{self.prompt}\n\n补充文字内容：\n{text_hint}"
        try:
            return await self.summarizer.summarize_images(payloads, prompt=prompt)
        except Exception as exc:
            self.logger.error("图片总结失败: %s", exc)
            return None

    async def test_latest_note(self, creator: XHSCreator) -> Dict[str, Any]:
        if not self.cookie:
            raise ValueError("XHS_COOKIE is missing")
        if not self.summarizer:
            raise ValueError("AI summary service not initialized")

        async with aiohttp.ClientSession() as session:
            user = await self._resolve_user(session, creator)
            if not user or not user.get("user_id"):
                raise ValueError("user not found or missing user_id")

            user_id = user["user_id"]
            xsec_token = user.get("xsec_token") or ""
            xsec_source = user.get("xsec_source") or "pc_search"
            ok, msg, res = await self.client.get_user_note_info(
                session, user_id, "", xsec_token, xsec_source
            )
            if not ok:
                raise ValueError(f"failed to fetch notes: {msg}")

            notes = res.get("data", {}).get("notes", []) or []
            candidate = None
            candidate_time = 0

            for note in notes[:10]:
                note_id = note.get("note_id")
                if not note_id:
                    continue
                note_url = self.client.build_note_url(
                    note_id, note.get("xsec_token") or xsec_token, xsec_source
                )
                ok, msg, detail = await self.client.get_note_info(session, note_url)
                note_card = {}
                if ok:
                    items = detail.get("data", {}).get("items", [])
                    if not items:
                        continue
                    note_card = items[0].get("note_card", {})
                else:
                    code = detail.get("code") if isinstance(detail, dict) else None
                    self.logger.warning(
                        "failed to fetch note detail: %s, msg=%s, code=%s", note_id, msg, code
                    )
                    note_card = note.get("note_card") or {}

                note_time = note_card.get("time") or note.get("time") or 0
                if note_card and note_card.get("type") != "normal":
                    continue
                image_urls = (
                    self.client.extract_image_urls(note_card)
                    if note_card
                    else self.client.extract_image_urls_from_note(note)
                )
                if not image_urls:
                    continue
                if note_time > candidate_time:
                    candidate_time = note_time
                    candidate = {
                        "note_id": note_id,
                        "note_url": note_url,
                        "note_card": note_card,
                        "image_urls": image_urls,
                    }

            if not candidate:
                raise ValueError("no analyzable image notes found")

            images = await self._fetch_images_base64(
                session, candidate["image_urls"]
            )
            note_card = candidate["note_card"] or {}
            text_hint = " ".join(
                [t for t in [note_card.get("title"), note_card.get("desc")] if t]
            )[: self.text_hint_max_len]
            summary = await self._summarize_images(images, text_hint=text_hint)

            note_time = note_card.get("time") or 0
            publish_time = (
                datetime.fromtimestamp(note_time / 1000).strftime("%Y-%m-%d %H:%M:%S")
                if note_time
                else ""
            )
            return {
                "creator": {
                    "red_id": creator.red_id,
                    "name": creator.name,
                },
                "note": {
                    "note_id": candidate["note_id"],
                    "note_url": candidate["note_url"],
                    "title": note_card.get("title") or "",
                    "desc": note_card.get("desc") or "",
                    "publish_time": publish_time,
                    "image_urls": candidate["image_urls"][:4],
                },
                "summary": summary or "",
            }

    async def process_creator(
        self, session: aiohttp.ClientSession, creator: XHSCreator
    ) -> None:
        if not self.cookie:
            return

        user = await self._resolve_user(session, creator)
        if not user or not user.get("user_id"):
            self.logger.warning("未找到用户: %s", creator.red_id)
            return

        user_id = user["user_id"]
        xsec_token = user.get("xsec_token") or ""
        xsec_source = user.get("xsec_source") or "pc_search"
        ok, msg, res = await self.client.get_user_note_info(
            session, user_id, "", xsec_token, xsec_source
        )
        if not ok:
            code = res.get("code") if isinstance(res, dict) else None
            self.logger.warning(
                "获取笔记列表失败: %s, msg=%s, code=%s", creator.red_id, msg, code
            )
            return

        notes = res.get("data", {}).get("notes", []) or []
        for note in notes:
            note_id = note.get("note_id")
            if not note_id or self.state.has_seen(creator.red_id, note_id):
                continue

            note_url = self.client.build_note_url(
                note_id, note.get("xsec_token") or xsec_token, xsec_source
            )
            ok, msg, detail = await self.client.get_note_info(session, note_url)
            note_card = {}
            if ok:
                items = detail.get("data", {}).get("items", [])
                if not items:
                    continue
                note_card = items[0].get("note_card", {})
            else:
                code = detail.get("code") if isinstance(detail, dict) else None
                self.logger.warning(
                    "获取笔记详情失败: %s, msg=%s, code=%s", note_id, msg, code
                )
                note_card = note.get("note_card") or {}

            note_time = note_card.get("time") or note.get("time")
            if not note_time or not self._is_today(note_time):
                self.state.mark_seen(creator.red_id, note_id)
                self.state.save()
                continue

            if note_card and note_card.get("type") != "normal":
                self.state.mark_seen(creator.red_id, note_id)
                self.state.save()
                continue

            image_urls = (
                self.client.extract_image_urls(note_card)
                if note_card
                else self.client.extract_image_urls_from_note(note)
            )
            if not image_urls:
                self.state.mark_seen(creator.red_id, note_id)
                self.state.save()
                continue

            images = await self._download_images(session, creator, note_id, image_urls)
            text_hint = " ".join(
                [t for t in [note_card.get("title"), note_card.get("desc")] if t]
            )[: self.text_hint_max_len]
            summary = await self._summarize_images(images, text_hint=text_hint)

            title = note_card.get("title") or "无标题"
            desc = note_card.get("desc") or ""
            publish_time = datetime.fromtimestamp(note_time / 1000).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            markdown = f"**{title}**\n\n{desc}\n\n"
            markdown += f"[原帖链接]({note_url})\n\n"

            for idx, img in enumerate(images[:4], 1):
                markdown += f"![图{idx}]({img['url']})\n"

            if summary:
                markdown += f"\n\n**AI 总结**\n\n{summary}"
            markdown += f"\n\n发布时间：{publish_time}"

            if self.feishu_bot:
                await self.feishu_bot.send_card_message(
                    creator.name, "小红书", markdown
                )

            self.state.mark_seen(creator.red_id, note_id)
            self.state.save()

    async def monitor_single_creator(
        self, session: aiohttp.ClientSession, creator: XHSCreator
    ) -> None:
        while True:
            try:
                self.logger.info(
                    "检查小红书博主 %s (red_id=%s) 的新笔记",
                    creator.name,
                    creator.red_id,
                )
                await self.process_creator(session, creator)

                await asyncio.sleep(creator.check_interval)
            except Exception as exc:
                self.logger.error("监控小红书博主异常: %s", exc)
                await asyncio.sleep(60)

    async def start_monitoring(
        self, creators: List[XHSCreator], once: bool = False
    ) -> None:
        if not creators:
            self.logger.warning("未配置小红书博主列表")
            return

        async with aiohttp.ClientSession() as session:
            if once:
                for creator in creators:
                    await self.process_creator(session, creator)
                return

            tasks = [asyncio.create_task(self.monitor_single_creator(session, c)) for c in creators]
            await asyncio.gather(*tasks)
