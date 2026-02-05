# -*- coding: utf-8 -*-
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import AI_CONFIG, reload_config
from services.ai_summary import AISummaryService
from services.feishu import FeishuBot
from services.xhs.monitor import XHSCreator, XHSMonitorService

NOTE_ID = "69842ef5000000002200aaba"
CREATOR = XHSCreator(red_id="5e43524b0000000001006055", name="许小喵")


async def main() -> None:
    reload_config()

    summarizer = AISummaryService(feishu_bot=None)
    feishu = FeishuBot()
    monitor = XHSMonitorService(feishu_bot=feishu, summarizer=summarizer)

    async with aiohttp.ClientSession() as session:
        print("开始解析博主信息...")
        user = await monitor._resolve_user(session, CREATOR)
        if not user or not user.get("user_id"):
            raise RuntimeError("user resolve failed")

        user_id = user["user_id"]
        xsec_token = user.get("xsec_token") or ""
        xsec_source = user.get("xsec_source") or "pc_search"
        print("拉取笔记列表...")
        ok, msg, res = await monitor.client.get_user_note_info(
            session, user_id, "", xsec_token, xsec_source
        )
        if not ok:
            raise RuntimeError(f"get_user_note_info failed: {msg}")

        notes = res.get("data", {}).get("notes", []) or []
        target_note = next((n for n in notes if n.get("note_id") == NOTE_ID), None)
        if not target_note:
            raise RuntimeError("target note not found in latest notes")

        note_url = monitor.client.build_note_url(
            NOTE_ID, target_note.get("xsec_token") or xsec_token, xsec_source
        )
        note_card = target_note.get("note_card") or {}
        if not monitor._has_full_image_list(target_note):
            print("笔记详情不完整，尝试抓取详情页...")
            detail_card = await monitor._fetch_note_detail_card(session, NOTE_ID, note_url)
            if detail_card:
                note_card = detail_card

        image_urls = monitor.client.extract_image_urls(note_card)
        image_urls = monitor._drop_cover_image(note_card, image_urls)
        print(f"图片数量: {len(image_urls)}")
        images = await monitor._fetch_images_base64(session, image_urls)
        if not images:
            raise RuntimeError("no images fetched")

        title = monitor._sanitize_text(
            note_card.get("title") or note_card.get("display_title") or NOTE_ID,
            fallback=NOTE_ID,
        )
        desc = monitor._sanitize_text(note_card.get("desc") or "", fallback="")
        text_hint = " ".join([t for t in [title, desc] if t])[: monitor.text_hint_max_len]

        batch_size = max(1, monitor.image_batch_size)
        batches = monitor._chunk_images(images, batch_size)

        prev_summary = ""
        last_summary = ""
        last_request = None

        system_prompt = "你是专业的图像内容分析助手。"
        temperature = 0.4
        max_tokens = AI_CONFIG.get("max_tokens") if isinstance(AI_CONFIG.get("max_tokens"), int) else None

        for idx, batch in enumerate(batches, 1):
            print(f"调用模型批次 {idx}/{len(batches)}，图片数: {len(batch)}")
            hint = text_hint
            if prev_summary:
                hint = (
                    f"{text_hint}\n\n历史摘要：\n{prev_summary}\n\n"
                    "请融合历史摘要与当前图片内容，输出一份完整的最终总结。"
                    "不要写“历史/摘要/本次/当前/补充/以下是/收到”等字样。"
                )

            prompt = monitor.prompt
            if hint:
                prompt = f"{monitor.prompt}\n\n补充信息：\n{hint}"

            content = [{"type": "text", "text": prompt}]
            for img in batch:
                mime = img.get("mime", "image/jpeg")
                b64 = img.get("base64", "")
                if not b64:
                    continue
                content.append(
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
                )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ]

            last_request = {
                "model": summarizer.ai_client.model,
                "messages": messages,
                "temperature": temperature,
            }
            if max_tokens is not None:
                last_request["max_tokens"] = max_tokens

            response = await summarizer.ai_client.chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if response:
                prev_summary = response
                last_summary = response
                print(f"批次 {idx} 完成，摘要长度: {len(response)}")

        timestamp = datetime.now().strftime("%H%M%S")
        out_path = os.path.join("data", f"xhs_request_response_{NOTE_ID}_{timestamp}.json")
        payload = {
            "note_id": NOTE_ID,
            "note_url": note_url,
            "title": title,
            "desc": desc,
            "images_count": len(images),
            "batch_size": batch_size,
            "request": last_request,
            "response": last_summary,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")

        markdown = f"**{title}**\n\n{desc}\n\n[原帖链接]({note_url})\n\n"
        for idx, img in enumerate(images[:batch_size], 1):
            markdown += f"![图{idx}]({img['url']})\n"
        if last_summary:
            markdown += f"\n\n**AI 总结**\n\n{last_summary}"
        note_time = note_card.get("time") or 0
        if note_time:
            publish_time = datetime.fromtimestamp(note_time / 1000).strftime("%Y-%m-%d %H:%M:%S")
            markdown += f"\n\n发布时间：{publish_time}"

        await feishu.send_card_message(
            monitor._sanitize_text(CREATOR.name, fallback=CREATOR.red_id),
            "小红书",
            markdown,
        )

        print(out_path)


if __name__ == "__main__":
    asyncio.run(main())
