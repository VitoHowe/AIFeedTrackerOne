# -*- coding: utf-8 -*-
"""
手动设置refresh_token工具

当无法使用二维码登录时（如412错误），可以从浏览器手动获取refresh_token
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def update_env_file(refresh_token: str) -> bool:
    """
    更新.env文件中的refresh_token

    Args:
        refresh_token: 从浏览器获取的refresh_token

    Returns:
        是否成功
    """
    try:
        env_file = Path(__file__).parent.parent / ".env"

        # 读取现有配置
        env_lines = []
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                env_lines = f.readlines()

        # 查找并更新refresh_token
        found = False
        for i, line in enumerate(env_lines):
            if line.startswith("refresh_token="):
                env_lines[i] = f"refresh_token={refresh_token}\n"
                found = True
                break

        # 如果没找到，添加到末尾
        if not found:
            env_lines.append(f"\n# B站refresh_token（Cookie自动刷新）\n")
            env_lines.append(f"refresh_token={refresh_token}\n")

        # 写回文件
        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(env_lines)

        print(f"[OK] refresh_token已保存到: {env_file}")
        return True

    except Exception as e:
        print(f"[ERROR] 保存失败: {e}")
        return False


def main():
    """主函数"""
    print("=" * 70)
    print("手动设置refresh_token - B站Cookie自动刷新")
    print("=" * 70)

    print("\n📝 如何从浏览器获取refresh_token:")
    print("-" * 70)
    print("\n方法1：从localStorage获取（推荐）")
    print("1. 在已登录的B站页面，按F12打开开发者工具")
    print("2. 切换到 [Console] 控制台")
    print("3. 输入以下命令并回车:")
    print("   localStorage.getItem('ac_time_value')")
    print("4. 复制输出的字符串（不包括引号）")

    print("\n方法2：从登录请求中获取")
    print("1. 打开B站登录页: https://passport.bilibili.com/login")
    print("2. 按F12打开开发者工具，切换到 [Network] 标签")
    print("3. 完成登录（扫码或密码）")
    print("4. 在Network中找到login相关的请求")
    print("5. 查看Response中的 refresh_token 字段")

    print("\n方法3：从Cookie中查找")
    print("1. 在已登录的B站页面，按F12打开开发者工具")
    print("2. 切换到 [Application] -> [Storage] -> [Cookies]")
    print("3. 查找 ac_time_value 字段的值")

    print("\n" + "-" * 70)

    # 获取用户输入
    print("\n请粘贴你的refresh_token:")
    print("（提示：通常是一串很长的字符串，如：c12a1234567890abcdef...）")
    print()

    refresh_token = input("refresh_token: ").strip()

    if not refresh_token:
        print("\n[ERROR] refresh_token不能为空")
        return 1

    if len(refresh_token) < 20:
        print("\n[WARNING] refresh_token长度似乎太短，请确认是否正确")
        confirm = input("是否继续保存？(y/N): ").strip().lower()
        if confirm != "y":
            print("[INFO] 已取消")
            return 0

    # 保存到.env
    print("\n保存中...")
    if update_env_file(refresh_token):
        print("\n" + "=" * 70)
        print("[SUCCESS] 设置完成！")
        print("=" * 70)
        print("\n✅ refresh_token已保存到.env文件")
        print("✅ Cookie自动刷新功能已启用")
        print("\n下一步:")
        print("1. 运行测试: uv run python test_api.py")
        print("2. 启动监控: uv run python main.py --mode monitor")
        print("\n💡 提示：系统将自动维护Cookie有效期，无需手动更新")
        return 0
    else:
        print("\n[ERROR] 设置失败，请检查错误信息")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[INFO] 用户取消操作")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] 发生错误: {e}")
        sys.exit(1)
