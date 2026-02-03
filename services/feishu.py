# -*- coding: utf-8 -*-
"""
飞书机器人服务模块

提供飞书消息发送和卡片推送功能
"""

import asyncio
import json
import logging
import os
import re
from typing import Optional

import aiohttp

# 导入配置

from config import FEISHU_CONFIG


try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateImageRequest,
        CreateImageRequestBody,
        CreateImageResponse,
        CreateMessageRequest,
        CreateMessageRequestBody,
        CreateMessageResponse,
    )

    LARK_SDK_AVAILABLE = True
except ImportError:
    LARK_SDK_AVAILABLE = False
    lark = None
    CreateMessageRequest = None
    CreateMessageRequestBody = None
    CreateMessageResponse = None
    CreateImageRequest = None
    CreateImageRequestBody = None
    CreateImageResponse = None


class FeishuBot:
    """
    飞书机器人客户端

    支持两种模式：
    1. Webhook模式：通过FEISHU_WEBHOOK环境变量设置的webhook URL发送消息
    2. 应用模式：通过app_id和app_secret使用飞书开放平台API发送卡片消息
    """

    # 通知级别常量
    LEVEL_INFO = "INFO"
    LEVEL_WARNING = "WARNING"
    LEVEL_ERROR = "ERROR"

    # 级别对应的emoji
    LEVEL_EMOJI = {
        "INFO": "✅",
        "WARNING": "⚠️",
        "ERROR": "❌",
    }

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # 飞书应用配置
        self.app_id = FEISHU_CONFIG["app_id"]
        self.app_secret = FEISHU_CONFIG["app_secret"]
        self.template_id = FEISHU_CONFIG["template_id"]
        self.template_version_name = FEISHU_CONFIG["template_version_name"]
        self.user_open_id = FEISHU_CONFIG["user_open_id"]

        # 检查配置状态
        self.has_app_config = bool(
            self.app_id and self.app_secret and LARK_SDK_AVAILABLE
        )

        if not self.has_app_config:
            self.logger.warning(
                "飞书应用配置不完整或lark-oapi未安装，消息将仅在日志中显示"
            )
        else:
            self.logger.info("飞书应用模式已配置")

    async def upload_image_to_feishu(self, image_url: str) -> Optional[str]:
        """
        上传图片到飞书并获取image key

        Args:
            image_url: 图片URL

        Returns:
            str: 飞书image key，失败返回None
        """
        if not self.has_app_config:
            return None

        try:
            # 创建飞书客户端
            client = (
                lark.Client.builder()
                .app_id(self.app_id)
                .app_secret(self.app_secret)
                .log_level(lark.LogLevel.ERROR)
                .build()
            )

            # 下载图片
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as response:
                    if response.status != 200:
                        self.logger.warning(
                            f"下载图片失败: {image_url}, status: {response.status}"
                        )
                        return None

                    image_data = await response.read()

            # 创建临时文件来存储图片
            import tempfile

            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
                temp_file.write(image_data)
                temp_file_path = temp_file.name

            try:
                # 上传图片到飞书
                with open(temp_file_path, "rb") as image_file:
                    request = (
                        CreateImageRequest.builder()
                        .request_body(
                            CreateImageRequestBody.builder()
                            .image_type("message")
                            .image(image_file)
                            .build()
                        )
                        .build()
                    )

                    response = client.im.v1.image.create(request)

                    if response.success():
                        image_key = response.data.image_key
                        self.logger.info(f"图片上传成功，image_key: {image_key}")
                        return image_key
                    else:
                        self.logger.error(f"图片上传失败: {response.msg}")
                        return None
            finally:
                # 清理临时文件
                os.unlink(temp_file_path)

        except Exception as e:
            self.logger.error(f"上传图片到飞书异常: {e}")
            return None

    async def convert_images_in_markdown(self, markdown_content: str) -> str:
        """
        将Markdown中的图片URL转换为飞书image key

        Args:
            markdown_content: 包含图片链接的Markdown内容

        Returns:
            str: 转换后的Markdown内容
        """
        if not self.has_app_config:
            return markdown_content

        # 查找所有图片链接
        image_pattern = r"!\[([^\]]*)\]\(([^)]+)\)"
        matches = re.findall(image_pattern, markdown_content)

        if not matches:
            return markdown_content

        self.logger.info(f"发现 {len(matches)} 个图片链接，开始转换...")

        converted_content = markdown_content
        for alt_text, image_url in matches:
            # 跳过已经是image key的情况
            if image_url.startswith("img_"):
                continue

            # 上传图片并获取image key
            image_key = await self.upload_image_to_feishu(image_url)
            if image_key:
                # 替换原始链接为image key
                old_pattern = f"![{alt_text}]({image_url})"
                new_pattern = f"![{alt_text}]({image_key})"
                converted_content = converted_content.replace(old_pattern, new_pattern)
                self.logger.info(f"图片转换成功: {image_url} -> {image_key}")
            else:
                self.logger.warning(f"图片转换失败，保持原链接: {image_url}")

        return converted_content

    async def send_card_message(
        self, influencer: str, platform: str, markdown_content: str
    ) -> bool:
        """
        发送卡片消息到飞书

        Args:
            influencer: 博主名称
            platform: 平台名称
            markdown_content: Markdown格式的内容

        Returns:
            bool: 发送成功返回True
        """
        if not self.has_app_config:
            # 回退到日志模式
            self.logger.info(
                f"[Mock飞书消息] [{platform}] {influencer}\n{markdown_content}"
            )
            return True

        try:
            # 转换图片链接为飞书image key
            self.logger.info("开始处理Markdown中的图片链接...")
            converted_content = await self.convert_images_in_markdown(markdown_content)

            # 创建飞书客户端
            client = (
                lark.Client.builder()
                .app_id(self.app_id)
                .app_secret(self.app_secret)
                .log_level(lark.LogLevel.ERROR)
                .build()
            )

            # 构建卡片消息内容
            card_content = {
                "data": {
                    "template_id": self.template_id,
                    "template_version_name": self.template_version_name,
                    "template_variable": {
                        "Influencer": influencer,
                        "platform": platform,
                        "markdown_content": converted_content,
                    },
                },
                "type": "template",
            }

            # 构造请求
            request = (
                CreateMessageRequest.builder()
                .receive_id_type("open_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(self.user_open_id)
                    .msg_type("interactive")
                    .content(json.dumps(card_content, ensure_ascii=False))
                    .build()
                )
                .build()
            )

            # 发送请求
            response = client.im.v1.message.create(request)

            if response.success():
                self.logger.info(f"飞书卡片消息发送成功: {influencer} - {platform}")
                return True
            else:
                self.logger.error(f"飞书卡片消息发送失败: {response.msg}")
                return False

        except Exception as e:
            self.logger.error(f"发送飞书卡片消息异常: {e}")
            # 回退到日志模式
            self.logger.info(
                f"[Mock飞书消息] [{platform}] {influencer}\n{markdown_content}"
            )
            return False

    async def send_system_notification(
        self, level: str, title: str, content: str
    ) -> bool:
        """
        发送系统状态通知

        Args:
            level: 通知级别 (INFO/WARNING/ERROR)
            title: 通知标题
            content: 通知内容（支持Markdown）

        Returns:
            bool: 发送成功返回True
        """
        try:
            # 获取级别对应的emoji
            emoji = self.LEVEL_EMOJI.get(level, "📢")

            # 格式化通知内容
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            formatted_content = f"**{emoji} {level}**\n\n"
            formatted_content += f"**{title}**\n\n"
            formatted_content += f"{content}\n\n"
            formatted_content += f"---\n"
            formatted_content += f"时间: {timestamp}"

            # 使用现有的卡片消息发送
            return await self.send_card_message(
                "系统通知", "AI视频机器人", formatted_content
            )

        except Exception as e:
            self.logger.error(f"发送系统通知异常: {e}")
            # 即使发送失败也在日志中记录
            self.logger.info(f"[系统通知] [{level}] {title}: {content}")
            return False


async def _demo():
    """演示函数"""
    logging.basicConfig(level=logging.INFO)
    bot = FeishuBot()
    # 测试卡片消息
    await bot.send_card_message("测试博主", "B站", "这是一个测试卡片消息")


if __name__ == "__main__":
    asyncio.run(_demo())
