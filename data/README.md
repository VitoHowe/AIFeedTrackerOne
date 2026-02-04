# Data 目录说明

此目录用于存储项目的配置和运行时数据。

## 文件说明

### bilibili_creators.json（必需）

存储您想要监控的 B 站博主列表。

**首次使用**：复制示例文件并修改

```bash
cp bilibili_creators.json.example bilibili_creators.json
```

**文件结构**：

```json
[
  {
    "uid": 11473291, // B站用户ID（必需）
    "name": "博主名称", // 显示名称（必需）
    "platform": "bilibili", // 平台（固定为bilibili）
    "enable_comments": false, // 是否启用评论监控（可选）
    "comment_keywords": [], // 评论关键词过滤（可选）
    "check_interval": 300 // 检查间隔（秒），默认300秒
  }
]
```

**如何获取博主 UID**：

1. 访问博主的 B 站主页
2. URL 中的数字即为 UID：`https://space.bilibili.com/11473291`

### bilibili_state.json（自动生成，无需手动创建）

存储动态监控的状态，记录已推送的动态 ID，避免重复推送。

**重要**：此文件由程序自动创建和管理，您**不需要**手动创建或修改。

**自动生成时机**：

- 首次运行 `main.py --mode monitor` 时自动创建
- 程序会自动初始化为空对象 `{}`
- 监控到动态后自动更新

**格式**：

```json
{
  "11473291": {
    "last_seen": "最近一次推送的动态ID",
    "seen": ["已推送的动态ID历史列表"]
  }
}
```

**重置方法**（重新推送历史动态）：

- 方法 1：删除此文件，程序会自动重建
- 方法 2：使用重置命令：`uv run python main.py --reset`

### bilibili_auth.json（可选）

存储 B 站认证令牌（refresh_token）用于自动刷新 Cookie。

**注意**：此文件包含敏感信息，已在.gitignore 中忽略，不会被推送到 GitHub。

详细配置请参考：[../docs/BILIBILI_SETUP.md](../docs/BILIBILI_SETUP.md)

## 安全提示

- ⚠️ **不要**将包含真实数据的 `.json` 文件推送到 GitHub
- ✅ **使用** `.example` 示例文件作为参考
- ✅ 实际配置文件已在 `.gitignore` 中被忽略
- ✅ 只有示例文件（`.example`）会被 Git 追踪

## 快速开始

### 必需配置（用户需要操作）

```bash
# 1. 复制示例文件
cp data/bilibili_creators.json.example data/bilibili_creators.json

# 2. 编辑配置文件，添加您要监控的博主UID
# 使用文本编辑器修改 bilibili_creators.json
```

### 自动生成文件（程序自动创建）

以下文件会在程序首次运行时自动创建，**无需手动操作**：

- ✅ `bilibili_state.json` - 动态监控状态
- ✅ `bilibili_auth.json` - B 站认证令牌（如果配置了 refresh_token）

### 测试运行

```bash
# 运行一次检查（测试配置是否正确）
uv run python main.py --mode monitor --once
```
