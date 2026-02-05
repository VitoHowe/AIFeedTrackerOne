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

from config import XHS_CONFIG, AI_CONFIG
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

    def get_daily_seen(self, red_id: str, day_key: str) -> List[str]:
        entry = self.state.get(red_id, {})
        daily = entry.get("daily_seen", {})
        if not isinstance(daily, dict):
            return []
        items = daily.get(day_key, [])
        return items if isinstance(items, list) else []

    def set_daily_seen(self, red_id: str, day_key: str, note_ids: List[str]) -> None:
        entry = self.state.setdefault(red_id, {})
        daily = entry.setdefault("daily_seen", {})
        if not isinstance(daily, dict):
            daily = {}
            entry["daily_seen"] = daily
        daily[day_key] = note_ids
        # 只保留最近 7 天记录
        if len(daily) > 7:
            keys = sorted(daily.keys())
            for old_key in keys[:-7]:
                daily.pop(old_key, None)

    def add_daily_seen(self, red_id: str, day_key: str, note_id: str) -> None:
        entry = self.state.setdefault(red_id, {})
        daily = entry.setdefault("daily_seen", {})
        if not isinstance(daily, dict):
            daily = {}
            entry["daily_seen"] = daily
        items = daily.get(day_key)
        if not isinstance(items, list):
            items = []
            daily[day_key] = items
        if note_id not in items:
            items.append(note_id)


class XHSMonitorService:
    STATE_PATH = os.path.join("data", "xhs_state.json")
    CREATORS_PATH = os.path.join("data", "xhs_creators.json")

    DEFAULT_PROMPT = SummaryGenerator.XHS_IMAGE_PROMPT
    TEXT_HINT_MAX_LEN = 800
    IMAGE_BATCH_SIZE = 5

    def __init__(self, feishu_bot=None, summarizer=None, cookie: Optional[str] = None):
        self.feishu_bot = feishu_bot
        self.summarizer = summarizer
        self.cookie = cookie or XHS_CONFIG.get("cookie")
        self.prompt = XHS_CONFIG.get("prompt") or self.DEFAULT_PROMPT
        self.text_hint_max_len = int(
            XHS_CONFIG.get("text_hint_max_len", self.TEXT_HINT_MAX_LEN)
        )
        self.image_batch_size = int(
            XHS_CONFIG.get("image_batch_size", self.IMAGE_BATCH_SIZE)
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
                    "搜索用户失败: %s, msg=%s, code=%s",
                    keyword,
                    msg,
                    res.get("code"),
                )
                return None, res
            users = res.get("data", {}).get("users", [])
            if not users:
                self.logger.warning("未找到用户: %s", keyword)
            return users, res

        raw_id = _extract_profile_id(creator.red_id)
        if _is_profile_id(raw_id):
            ok, msg, token_data = await self.client.get_profile_xsec_token(session, raw_id)
            if not ok:
                self.logger.warning("获取 profile xsec_token 失败: %s, msg=%s", raw_id, msg)
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

    @staticmethod
    def _has_full_image_list(note: Dict[str, Any]) -> bool:
        note_card = note.get("note_card") or {}
        if note_card.get("image_list"):
            return True
        if note.get("image_list"):
            return True
        return False

    async def _fetch_note_detail_card(
        self, session: aiohttp.ClientSession, note_id: str, note_url: str
    ) -> Optional[Dict[str, Any]]:
        ok, msg, detail = await self.client.get_note_info(session, note_url)
        if not ok:
            code = detail.get("code") if isinstance(detail, dict) else None
            self.logger.warning(
                "获取笔记详情失败: %s, msg=%s, code=%s", note_id, msg, code
            )
            ok2, msg2, token_data = await self.client.get_note_xsec_token(
                session, note_id
            )
            if ok2:
                token, source = token_data
                retry_url = self.client.build_note_url(note_id, token, source or "pc_search")
                ok, msg, detail = await self.client.get_note_info(session, retry_url)
                if not ok:
                    code = detail.get("code") if isinstance(detail, dict) else None
                    self.logger.warning(
                        "重试获取笔记详情失败: %s, msg=%s, code=%s",
                        note_id,
                        msg,
                        code,
                    )
                    return None
            else:
                self.logger.warning(
                    "获取笔记页面 xsec_token 失败: %s, msg=%s", note_id, msg2
                )
                return None
        items = detail.get("data", {}).get("items", [])
        if not items:
            self.logger.warning("笔记详情为空: %s", note_id)
            return None
        return items[0].get("note_card") or {}

    async def _fetch_images_base64(
        self, session: aiohttp.ClientSession, image_urls: List[str]
    ) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        for url in image_urls:
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

    @staticmethod
    def _drop_cover_image(note: Dict[str, Any], image_urls: List[str]) -> List[str]:
        if not image_urls:
            return image_urls
        cover_url = None
        cover = note.get("cover")
        if isinstance(cover, dict):
            for key in ("url", "url_default", "url_pre"):
                if cover.get(key):
                    cover_url = cover.get(key)
                    break
            if not cover_url:
                info_list = cover.get("info_list") or []
                if info_list:
                    cover_url = info_list[-1].get("url") or info_list[0].get("url")
        elif isinstance(cover, str):
            cover_url = cover
        if cover_url:
            return [url for url in image_urls if url != cover_url]
        return image_urls

    @staticmethod
    def _chunk_images(images: List[Dict[str, str]], size: int) -> List[List[Dict[str, str]]]:
        if size <= 0:
            return [images]
        return [images[i : i + size] for i in range(0, len(images), size)]

    @staticmethod
    def _sanitize_text(value: Optional[str], fallback: str = "") -> str:
        if value is None:
            return fallback
        text = str(value).strip()
        if not text:
            return fallback
        if all(ch in {"?", "？"} for ch in text):
            return fallback
        return text

    async def _summarize_images(
        self, images: List[Dict[str, str]], text_hint: str = ""
    ) -> Optional[str]:
        if not self.summarizer or not images:
            return None
        payloads = [{"mime": "image/jpeg", "base64": img["base64"]} for img in images]
        prompt = self.prompt
        if text_hint:
            prompt = f"{self.prompt}\n\n补充信息：\n{text_hint}"
        try:
            return await self.summarizer.summarize_images(payloads, prompt=prompt)
        except Exception as exc:
            self.logger.error("图片总结失败: %s", exc)
            return None

    async def _summarize_text(self, prompt: str) -> Optional[str]:
        if not self.summarizer or not prompt:
            return None
        try:
            messages = [
                {"role": "system", "content": "你是专业的投研总结助手。"},
                {"role": "user", "content": prompt},
            ]
            max_tokens = (
                AI_CONFIG.get("max_tokens")
                if isinstance(AI_CONFIG.get("max_tokens"), int)
                else None
            )
            return await self.summarizer.ai_client.chat_completion(
                messages=messages, temperature=0.4, max_tokens=max_tokens
            )
        except Exception as exc:
            self.logger.error("最终总结失败: %s", exc)
            return None

    async def _summarize_images_in_batches(
        self, images: List[Dict[str, str]], text_hint: str = ""
    ) -> Optional[str]:
        if not images:
            return None
        batch_size = max(1, self.image_batch_size)
        batches = self._chunk_images(images, batch_size)
        if len(batches) == 1:
            return await self._summarize_images(batches[0], text_hint=text_hint)

        prev_summary = ""
        last_summary = ""
        for batch in batches:
            hint = text_hint
            if prev_summary:
                hint = (
                    f"{text_hint}\n\n历史摘要：\n{prev_summary}\n\n"
                    "请融合历史摘要与当前图片内容，输出一份完整的最终总结。"
                    "不要写“历史/摘要/本次/当前/补充/以下是/收到”等字样。"
                )
            summary = await self._summarize_images(batch, text_hint=hint)
            if summary:
                last_summary = summary
                prev_summary = summary
        return last_summary or None

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
                note_card = note.get("note_card") or {}
                note_time = note_card.get("time") or note.get("time") or 0
                note_type = note_card.get("type") or note.get("type")
                image_urls: List[str] = []

                if self._has_full_image_list(note):
                    image_urls = self.client.extract_image_urls_from_note(note)
                else:
                    detail_card = await self._fetch_note_detail_card(
                        session, note_id, note_url
                    )
                    if not detail_card:
                        continue
                    note_card = detail_card
                    note_time = note_card.get("time") or note_time
                    note_type = note_card.get("type") or note_type
                    image_urls = self.client.extract_image_urls(note_card)

                if note_type and note_type != "normal":
                    continue
                if not image_urls:
                    continue
                if note_time:
                    if note_time > candidate_time:
                        candidate_time = note_time
                        candidate = {
                            "note_id": note_id,
                            "note_url": note_url,
                            "note_card": note_card,
                            "image_urls": image_urls,
                        }
                elif candidate is None:
                    candidate = {
                        "note_id": note_id,
                        "note_url": note_url,
                        "note_card": note_card,
                        "image_urls": image_urls,
                    }

            if not candidate:
                raise ValueError("no analyzable image notes found")

            image_urls = self._drop_cover_image(
                candidate["note_card"] or {}, candidate["image_urls"]
            )
            images = await self._fetch_images_base64(
                session, image_urls
            )
            note_card = candidate["note_card"] or {}
            title = self._sanitize_text(
                note_card.get("title") or note_card.get("display_title") or "",
                fallback="",
            )
            if not title and notes:
                title = self._sanitize_text(notes[0].get("display_title") or "", fallback="")
            desc = self._sanitize_text(note_card.get("desc") or "", fallback="")
            text_hint = " ".join([t for t in [title, desc] if t])[
                : self.text_hint_max_len
            ]
            summary = await self._summarize_images_in_batches(
                images, text_hint=text_hint
            )

            note_time = note_card.get("time") or 0
            publish_time = (
                datetime.fromtimestamp(note_time / 1000).strftime("%Y-%m-%d %H:%M:%S")
                if note_time
                else ""
            )
            return {
                "creator": {
                    "red_id": creator.red_id,
                    "name": self._sanitize_text(creator.name, fallback=creator.red_id),
                },
                "note": {
                    "note_id": candidate["note_id"],
                    "note_url": candidate["note_url"],
                    "title": title or candidate["note_id"],
                    "desc": desc,
                    "publish_time": publish_time,
                    "image_urls": image_urls[: self.image_batch_size],
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
            self.logger.warning("未解析到 user_id: %s", creator.red_id)
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
        today_key = date.today().isoformat()
        today_note_ids: List[str] = []
        today_notes: List[Dict[str, Any]] = []
        note_time_map: Dict[str, int] = {}

        for note in notes:
            note_id = note.get("note_id")
            if not note_id:
                continue
            note_card = note.get("note_card") or {}
            note_time = note_card.get("time") or note.get("time") or 0
            if note_time and self._is_today(note_time):
                today_note_ids.append(note_id)
                today_notes.append(note)
                note_time_map[note_id] = int(note_time)

        if not today_note_ids:
            return

        seen_today = self.state.get_daily_seen(creator.red_id, today_key)
        if not seen_today:
            # 首次运行：推送最近 3 条当日笔记（如有），并记录当日基线
            today_notes.sort(
                key=lambda item: note_time_map.get(item.get("note_id") or "", 0),
                reverse=True,
            )
            initial_notes = today_notes[:3]
            if initial_notes:
                initial_notes.sort(
                    key=lambda item: note_time_map.get(item.get("note_id") or "", 0)
                )
                for note in initial_notes:
                    await self._process_today_note(
                        session,
                        creator,
                        user,
                        note,
                        xsec_token,
                        xsec_source,
                        today_key,
                    )
            self.state.set_daily_seen(creator.red_id, today_key, today_note_ids)
            self.state.save()
            return

        seen_today_set = set(seen_today)
        new_notes: List[Dict[str, Any]] = []
        for note in today_notes:
            note_id = note.get("note_id")
            if not note_id or note_id in seen_today_set:
                continue
            new_notes.append(note)

        if not new_notes:
            return

        new_notes.sort(key=lambda item: note_time_map.get(item.get("note_id") or "", 0))

        updated = False
        for note in new_notes:
            note_id = note.get("note_id")
            if not note_id:
                continue
            if self.state.has_seen(creator.red_id, note_id):
                self.state.add_daily_seen(creator.red_id, today_key, note_id)
                updated = True
                continue

            handled = await self._process_today_note(
                session,
                creator,
                user,
                note,
                xsec_token,
                xsec_source,
                today_key,
            )
            if handled:
                updated = True

        if updated:
            self.state.save()

    async def _process_today_note(
        self,
        session: aiohttp.ClientSession,
        creator: XHSCreator,
        user: Dict[str, str],
        note: Dict[str, Any],
        xsec_token: str,
        xsec_source: str,
        today_key: str,
    ) -> bool:
        note_id = note.get("note_id")
        if not note_id:
            return False

        note_url = self.client.build_note_url(
            note_id, note.get("xsec_token") or xsec_token, xsec_source
        )
        note_card = note.get("note_card") or {}
        note_time = note_card.get("time") or note.get("time")
        note_type = note_card.get("type") or note.get("type")
        image_urls: List[str] = []

        if self._has_full_image_list(note):
            image_urls = self.client.extract_image_urls_from_note(note)
        else:
            detail_card = await self._fetch_note_detail_card(
                session, note_id, note_url
            )
            if detail_card:
                note_card = detail_card
                note_time = note_card.get("time") or note_time
                note_type = note_card.get("type") or note_type
                image_urls = self.client.extract_image_urls(note_card)

        if note_type and note_type != "normal":
            self.state.add_daily_seen(creator.red_id, today_key, note_id)
            self.state.mark_seen(creator.red_id, note_id)
            return True

        if not image_urls:
            self.state.add_daily_seen(creator.red_id, today_key, note_id)
            self.state.mark_seen(creator.red_id, note_id)
            return True

        image_urls = self._drop_cover_image(note_card, image_urls)
        images = await self._download_images(session, creator, note_id, image_urls)
        author_name = self._sanitize_text(
            (note_card.get("user") or {}).get("nickname")
            or (note.get("user") or {}).get("nickname")
            or user.get("name")
            or creator.name,
            fallback=creator.red_id,
        )
        title = self._sanitize_text(
            note_card.get("title") or note.get("display_title") or note_id,
            fallback=note_id,
        )
        desc = self._sanitize_text(note_card.get("desc") or "", fallback="")
        text_hint = " ".join([t for t in [title, desc] if t])[
            : self.text_hint_max_len
        ]
        summary = await self._summarize_images_in_batches(
            images, text_hint=text_hint
        )

        publish_time = (
            datetime.fromtimestamp(note_time / 1000).strftime("%Y-%m-%d %H:%M:%S")
            if note_time
            else ""
        )

        markdown = f"**{title}**\n\n{desc}\n\n"
        markdown += f"[原帖链接]({note_url})\n\n"

        for idx, img in enumerate(images[: self.image_batch_size], 1):
            markdown += f"![图{idx}]({img['url']})\n"

        if summary:
            markdown += f"\n\n**AI 总结**\n\n{summary}"
        if publish_time:
            markdown += f"\n\n发布时间：{publish_time}"

        if self.feishu_bot:
            await self.feishu_bot.send_card_message(
                author_name, "小红书", markdown
            )

        self.state.add_daily_seen(creator.red_id, today_key, note_id)
        self.state.mark_seen(creator.red_id, note_id)
        return True

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
