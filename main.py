# -*- coding: utf-8 -*-
"""
AI视频机器人主程序

统一的项目入口，整合所有功能模块
"""

import asyncio
import logging
import sys
import socket
from pathlib import Path
from typing import Optional

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config import PANEL_CONFIG, build_bilibili_cookie, get_config_status, reload_config

# 导入核心模块
from core import configure_logging
from services import FeishuBot, MonitorService, XHSMonitorService

# 导入服务模块
from services.ai_summary import AISummaryService


async def _cancel_task(task: Optional[asyncio.Task], name: str) -> None:
    if not task or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"取消任务 {name} 失败: {e}")


async def start_config_panel(on_change=None):
    """启动配置面板服务"""
    from services.config_panel import create_app

    panel_task = None

    try:
        import uvicorn
    except ImportError:
        raise RuntimeError("缺少 uvicorn 依赖，请先安装后再启动配置面板")

    host = PANEL_CONFIG.get("host", "127.0.0.1")
    port = PANEL_CONFIG.get("port", 8765)
    check_host = "127.0.0.1" if host in ("0.0.0.0", "localhost") else host
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((check_host, port)) == 0:
                logger = logging.getLogger(__name__)
                logger.warning("配置面板端口已占用，跳过启动: %s:%s", host, port)
                return
    except Exception:
        pass

    config = uvicorn.Config(
        create_app(on_change=on_change),
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    except OSError as exc:
        logger = logging.getLogger(__name__)
        logger.warning("????????: %s", exc)
    except SystemExit as exc:
        logger = logging.getLogger(__name__)
        logger.warning("????????: %s", exc)


class AIVideoBot:
    """AI视频机器人主类

    整合飞书机器人、AI视频总结服务和B站动态监控功能
    """

    def __init__(self):
        """初始化机器人实例"""
        self.logger = configure_logging()
        self.logger.info("初始化AI视频机器人...")

        # 检查配置状态
        config_status = get_config_status()
        self._log_config_status(config_status)

        # 初始化服务
        self.feishu_bot = FeishuBot()
        self.ai_service = AISummaryService(feishu_bot=self.feishu_bot)  # 使用AI总结服务

        self.logger.info("AI视频机器人初始化完成")

    async def send_startup_notification(self):
        """发送启动通知"""
        try:
            content = "机器人已成功启动\n\n"
            content += "**初始化状态:**\n"
            content += "- 飞书机器人: ✅\n"
            content += "- AI总结服务: ✅\n"
            content += "- 监控服务: 待启动"

            await self.feishu_bot.send_system_notification(
                self.feishu_bot.LEVEL_INFO, "机器人启动成功", content
            )
        except Exception as e:
            self.logger.warning(f"发送启动通知失败: {e}")

    def _log_config_status(self, status: dict):
        """记录配置状态"""
        self.logger.info("配置状态检查:")
        for key, value in status.items():
            emoji = "✅" if value else "❌"
            self.logger.info(f"  {emoji} {key}: {value}")

        if not status["feishu_configured"]:
            self.logger.warning("飞书应用未配置，将使用Mock模式")
        if not status["bilibili_configured"]:
            self.logger.warning("B站认证未配置，部分功能可能受限")

    async def manual_summarize_video(self, video_url: str) -> str:
        """手动总结单个视频

        Args:
            video_url: 视频URL

        Returns:
            str: 总结内容，失败返回空字符串
        """
        try:
            self.logger.info(f"开始总结视频: {video_url}")

            success, message, summary_links, summary_contents = (
                await self.ai_service.summarize_videos([video_url])
            )

            if success and summary_contents:
                # AI总结服务直接返回内容
                self.logger.info("视频总结成功")
                return summary_contents[0]
            else:
                self.logger.error(f"视频总结失败: {message}")
                return ""

        except Exception as e:
            self.logger.error(f"视频总结异常: {e}")
            return ""

    async def send_notification(self, influencer: str, platform: str, content: str):
        """发送通知消息到飞书

        Args:
            influencer: 博主名称
            platform: 平台名称
            content: 消息内容
        """
        try:
            if hasattr(self.feishu_bot, "send_card_message"):
                success = await self.feishu_bot.send_card_message(
                    influencer, platform, content
                )
            else:
                success = await self.feishu_bot.send_text(
                    f"[{platform}] {influencer}\n\n{content}"
                )

            if success:
                self.logger.info(f"通知发送成功: {influencer} - {platform}")
            else:
                self.logger.warning(f"通知发送失败: {influencer} - {platform}")

        except Exception as e:
            self.logger.error(f"发送通知异常: {e}")

    async def start_monitoring(self, once: bool = False):
        """启动动态监控

        Args:
            once: 是否只运行一次检查
        """
        try:
            self.logger.info("启动动态监控...")

            # 创建监控服务
            cookie = build_bilibili_cookie()
            monitor_service = MonitorService(
                feishu_bot=self.feishu_bot, summarizer=self.ai_service, cookie=cookie
            )
            xhs_monitor = XHSMonitorService(
                feishu_bot=self.feishu_bot, summarizer=self.ai_service
            )

            # 加载创作者列表
            creators = monitor_service.load_creators_from_file()
            xhs_creators = xhs_monitor.load_creators_from_file()
            self.logger.info(
                f"加载了 {len(creators)} 个创作者 + {len(xhs_creators)} 个小红书博主"
            )

            # 发送监控启动通知
            try:
                bili_names = ", ".join([c.name for c in creators[:3]])
                if len(creators) > 3:
                    bili_names += f" 等{len(creators)}个创作者"
                if not bili_names:
                    bili_names = "无"

                xhs_names = ", ".join([c.name for c in xhs_creators[:3]])
                if len(xhs_creators) > 3:
                    xhs_names += f" 等{len(xhs_creators)}个博主"
                if not xhs_names:
                    xhs_names = "无"

                content = "监控服务已启动\n\n"
                content += f"**B站:** {bili_names}\n"
                content += f"**小红书:** {xhs_names}\n"
                content += f"**模式:** {'单次检查' if once else '持续监控'}"

                await self.feishu_bot.send_system_notification(
                    self.feishu_bot.LEVEL_INFO, "监控服务启动", content
                )
            except Exception as e:
                self.logger.warning(f"发送监控启动通知失败: {e}")

            # 启动监控
            tasks = [
                asyncio.create_task(
                    monitor_service.start_monitoring(creators, once=once)
                ),
                asyncio.create_task(
                    xhs_monitor.start_monitoring(xhs_creators, once=once)
                ),
            ]
            await asyncio.gather(*tasks)

        except asyncio.CancelledError:
            self.logger.info("监控任务已取消")
            raise
        except Exception as e:
            self.logger.error(f"动态监控异常: {e}")
            # 发送监控异常通知
            try:
                await self.feishu_bot.send_system_notification(
                    self.feishu_bot.LEVEL_ERROR,
                    "监控服务异常停止",
                    f"监控服务遇到异常并停止\n\n**错误信息:**\n```\n{str(e)}\n```",
                )
            except Exception:
                pass

    async def cleanup(self):
        """清理资源"""
        try:
            # AI总结服务不需要清理浏览器资源
            self.logger.info("资源清理完成")
        except Exception as e:
            self.logger.warning(f"资源清理警告: {e}")


async def main():
    """主函数 - 项目统一入口"""
    import argparse

    parser = argparse.ArgumentParser(description="AI视频机器人")
    parser.add_argument(
        "--mode",
        choices=["monitor", "test", "service"],
        default="monitor",
        help="运行模式: monitor(监控模式), test(测试模式) 或 service(服务模式)",
    )
    parser.add_argument("--once", action="store_true", help="仅运行一次检查")
    parser.add_argument(
        "--reset", action="store_true", help="重置监控状态，重新推送历史动态"
    )
    parser.add_argument("--video", type=str, help="测试模式下要总结的视频URL")

    args = parser.parse_args()

    # 创建机器人实例
    bot = AIVideoBot()
    panel_task: Optional[asyncio.Task] = None
    monitor_task: Optional[asyncio.Task] = None

    try:
        # 如果指定了--reset，清空状态文件
        if args.reset:
            print("正在重置监控状态...")
            state_file = Path("data/bilibili_state.json")
            if state_file.exists():
                # 备份当前状态
                import shutil

                backup_file = state_file.with_suffix(".backup.json")
                shutil.copy(state_file, backup_file)
                print(f"已备份当前状态到: {backup_file}")

                # 清空状态
                with open(state_file, "w", encoding="utf-8") as f:
                    f.write("{}")
                print("状态已重置，将重新推送最近48小时内的动态")

        # 发送启动通知（非测试模式）
        if args.mode != "test":
            await bot.send_startup_notification()

        if args.mode == "test":
            # 测试模式
            if args.video:
                print(f"测试视频总结: {args.video}")
                result = await bot.manual_summarize_video(args.video)
                if result:
                    print("总结结果:")
                    print(result)
                else:
                    print("总结失败")
            else:
                print("测试模式需要提供 --video 参数")
        elif args.mode == "service":
            # 服务模式：持续运行，异常时重启
            print("启动服务模式...")
            reload_event = asyncio.Event()

            def trigger_reload():
                reload_event.set()

            panel_task = asyncio.create_task(start_config_panel(trigger_reload))
            bot.logger.info(
                f"配置面板启动: http://{PANEL_CONFIG.get('host', '127.0.0.1')}:{PANEL_CONFIG.get('port', 8765)}"
            )
            monitor_task = asyncio.create_task(bot.start_monitoring(once=False))

            async def restart_services(reason: str) -> None:
                nonlocal bot, monitor_task, panel_task
                bot.logger.info(f"配置变更触发热更新: {reason}")
                reload_config()
                await _cancel_task(monitor_task, "monitor")
                await _cancel_task(panel_task, "panel")
                bot = AIVideoBot()
                panel_task = asyncio.create_task(start_config_panel(trigger_reload))
                bot.logger.info(
                    f"配置面板启动: http://{PANEL_CONFIG.get('host', '127.0.0.1')}:{PANEL_CONFIG.get('port', 8765)}"
                )
                monitor_task = asyncio.create_task(bot.start_monitoring(once=False))

            while True:
                reload_task = asyncio.create_task(reload_event.wait())
                done, _ = await asyncio.wait(
                    [monitor_task, reload_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if reload_event.is_set():
                    reload_event.clear()
                    await _cancel_task(reload_task, "reload-event")
                    await restart_services("config-change")
                    continue
                if reload_task in done:
                    await _cancel_task(reload_task, "reload-event")
                if monitor_task in done:
                    if monitor_task.cancelled():
                        break
                    exc = monitor_task.exception()
                    if exc:
                        bot.logger.error(f"监控循环异常: {exc}")
                    bot.logger.info("等待30秒后重试...")
                    await asyncio.sleep(30)
                    await restart_services("monitor-restart")
        else:
            # 监控模式
            print("启动动态监控模式...")
            await bot.start_monitoring(once=args.once)

    except KeyboardInterrupt:
        print("\n收到中断信号，正在停止...")
        # 发送正常停止通知
        try:
            await bot.feishu_bot.send_system_notification(
                bot.feishu_bot.LEVEL_INFO,
                "机器人正常停止",
                "收到中断信号，机器人正在安全关闭",
            )
        except Exception:
            pass
    except Exception as e:
        print(f"\n机器人运行异常: {e}")
        # 发送异常停止通知
        try:
            await bot.feishu_bot.send_system_notification(
                bot.feishu_bot.LEVEL_ERROR,
                "机器人意外停止",
                f"机器人遇到未捕获的异常并停止\n\n**错误信息:**\n```\n{str(e)}\n```",
            )
        except Exception:
            pass
    finally:
        # 只在测试模式或一次性检查模式下立即清理资源
        if args.mode == "test" or args.once:
            await bot.cleanup()
        await _cancel_task(monitor_task, "monitor")
        await _cancel_task(panel_task, "panel")


if __name__ == "__main__":
    print("AI视频机器人启动中...")
    asyncio.run(main())
