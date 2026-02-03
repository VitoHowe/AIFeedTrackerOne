# -*- coding: utf-8 -*-
"""
浏览器信息检测工具

检查当前Cookie对应的浏览器信息，确保请求头匹配
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import BILIBILI_CONFIG


def main():
    """主函数"""
    print("=" * 70)
    print("B站Cookie浏览器信息检测")
    print("=" * 70)

    print("\n📋 当前配置的Cookie信息:")
    print("-" * 70)

    # 检查Cookie配置
    sessdata = BILIBILI_CONFIG.get("SESSDATA")
    bili_jct = BILIBILI_CONFIG.get("bili_jct")
    buvid3 = BILIBILI_CONFIG.get("buvid3")
    refresh_token = BILIBILI_CONFIG.get("refresh_token")

    print(f"SESSDATA: {sessdata[:20] if sessdata else '未配置'}...")
    print(f"bili_jct: {bili_jct[:20] if bili_jct else '未配置'}...")
    print(f"buvid3: {buvid3 if buvid3 else '未配置'}")
    print(f"refresh_token: {refresh_token[:20] if refresh_token else '未配置'}...")

    if not all([sessdata, bili_jct, buvid3]):
        print("\n⚠️ 警告：Cookie配置不完整")
        return 1

    print("\n" + "=" * 70)
    print("🔍 获取你的浏览器User-Agent")
    print("=" * 70)

    print("\n请按照以下步骤获取你的浏览器User-Agent:")
    print("-" * 70)

    print("\n方法1：从Console获取（最简单）")
    print("1. 在B站页面按F12打开开发者工具")
    print("2. 切换到 [Console] 控制台")
    print("3. 输入以下命令并回车:")
    print("   navigator.userAgent")
    print("4. 复制输出的完整字符串")

    print("\n方法2：从Network面板获取")
    print("1. 在B站页面按F12打开开发者工具")
    print("2. 切换到 [Network] 标签")
    print("3. 刷新页面(F5)")
    print("4. 点击任意请求")
    print("5. 在Request Headers中找到 User-Agent")
    print("6. 复制它的值")

    print("\n" + "-" * 70)

    # 获取User-Agent
    print("\n请粘贴你的User-Agent:")
    print("（如果留空，将使用默认值）")
    print()

    user_agent = input("User-Agent: ").strip()

    if not user_agent:
        print("\n[INFO] 使用默认User-Agent")
        default_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        print(f"默认值: {default_ua}")
        use_default = input("\n是否使用默认值？(Y/n): ").strip().lower()
        if use_default != "n":
            user_agent = default_ua
        else:
            print("[INFO] 已取消")
            return 0

    # 保存到.env
    print("\n保存中...")
    try:
        env_file = Path(__file__).parent.parent / ".env"

        # 读取现有配置
        env_lines = []
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                env_lines = f.readlines()

        # 查找并更新User-Agent
        found = False
        for i, line in enumerate(env_lines):
            if line.startswith("USER_AGENT="):
                env_lines[i] = f"USER_AGENT={user_agent}\n"
                found = True
                break

        # 如果没找到，添加到末尾
        if not found:
            env_lines.append(f"\n# 浏览器User-Agent（保持与浏览器一致）\n")
            env_lines.append(f"USER_AGENT={user_agent}\n")

        # 写回文件
        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(env_lines)

        print(f"[OK] User-Agent已保存到: {env_file}")

    except Exception as e:
        print(f"[ERROR] 保存失败: {e}")
        return 1

    print("\n" + "=" * 70)
    print("[SUCCESS] 配置完成！")
    print("=" * 70)

    print("\n✅ 配置建议:")
    print("-" * 70)
    print("1. ✅ Cookie已配置")
    print(
        "2. ✅ refresh_token已配置" if refresh_token else "2. ⚠️ 建议配置refresh_token"
    )
    print("3. ✅ User-Agent已配置")

    print("\n🔒 安全建议:")
    print("-" * 70)
    print("• buvid3 来自你的浏览器，保持不变 ✅")
    print("• User-Agent 与浏览器匹配，降低风控风险 ✅")
    print("• refresh_token 启用自动刷新，长期有效 ✅")

    print("\n下一步:")
    print("1. 重启程序以加载新配置")
    print("2. 运行测试: uv run python test_api.py")
    print("3. 启动监控: uv run python main.py --mode monitor")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[INFO] 用户取消操作")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] 发生错误: {e}")
        sys.exit(1)
