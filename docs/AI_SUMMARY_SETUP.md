# AI 视频总结服务配置指南

本项目使用国内 AI 服务（DeepSeek、智谱 AI、通义千问等）实现视频总结功能。本文档将指导您完成配置。

## 快速开始

### 1. 选择 AI 服务

项目支持以下 AI 服务（均兼容 OpenAI 接口）：

| 服务名称      | 推荐指数   | 特点             | 官网                           |
| ------------- | ---------- | ---------------- | ------------------------------ |
| **DeepSeek**  | ⭐⭐⭐⭐⭐ | 性价比高，质量好 | https://platform.deepseek.com/ |
| 智谱 AI (GLM) | ⭐⭐⭐⭐   | 国产化，兼容性好 | https://open.bigmodel.cn/      |
| 通义千问      | ⭐⭐⭐⭐   | 阿里云生态，稳定 | https://dashscope.aliyun.com/  |

**推荐使用 DeepSeek**，原因：

- 价格最低：¥1/百万 tokens（输入），¥2/百万 tokens（输出）
- 质量优秀：基于最新的大模型技术
- 速度快：响应时间短
- 稳定性好：API 可用性高

### 2. 获取 API Key

以 DeepSeek 为例：

1. 访问 https://platform.deepseek.com/
2. 注册账号并登录
3. 进入"API Keys"页面
4. 点击"创建新的 API Key"
5. 复制生成的 API Key（形如：`sk-...`）

### 3. 配置环境变量

编辑项目根目录的 `.env` 文件（如果不存在，复制 `env.example`）：

```env
# AI服务配置
AI_SERVICE=deepseek
AI_API_KEY=sk-your-actual-api-key-here
```

### 4. 测试配置

运行测试脚本验证配置：

```bash
python tests/test_ai_summary.py
```

如果看到"✅ 字幕获取成功"和"✅ 总结成功"，说明配置正确。

## 详细配置

### 环境变量说明

| 变量名        | 必填   | 说明                               | 默认值                   |
| ------------- | ------ | ---------------------------------- | ------------------------ |
| `AI_SERVICE`  | 否     | AI 服务名称（deepseek/zhipu/qwen） | deepseek                 |
| `AI_API_KEY`  | **是** | AI 服务的 API 密钥                 | 无                       |
| `AI_BASE_URL` | 否     | API 地址（自定义服务）             | 根据 AI_SERVICE 自动选择 |
| `AI_MODEL`    | 否     | 模型名称                           | 根据 AI_SERVICE 自动选择 |

### 各服务默认配置

#### DeepSeek

```env
AI_SERVICE=deepseek
AI_API_KEY=sk-xxx
# 以下为默认值，通常不需要设置
# AI_BASE_URL=https://api.deepseek.com
# AI_MODEL=deepseek-chat
```

#### 智谱 AI (GLM)

```env
AI_SERVICE=zhipu
AI_API_KEY=your-zhipu-api-key
# 以下为默认值，通常不需要设置
# AI_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
# AI_MODEL=glm-4
```

#### 通义千问

```env
AI_SERVICE=qwen
AI_API_KEY=your-qwen-api-key
# 以下为默认值，通常不需要设置
# AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# AI_MODEL=qwen-turbo
```

## 工作原理

AI 视频总结服务的工作流程：

```
1. 接收视频URL
   ↓
2. 从B站获取AI生成的字幕
   ↓
3. 将字幕发送给AI服务
   ↓
4. AI生成结构化总结
   ↓
5. 返回Markdown格式的总结内容
```

### 总结格式

生成的总结包含以下部分：

- **📌 核心观点**：3-5 个关键要点
- **💡 关键亮点**：重要信息摘要
- **📝 详细总结**：按逻辑分段的详细内容

示例：

```markdown
📌 **核心观点**

- 视频主要讨论了 xxx
- 关键技术是 yyy
- 最终结论是 zzz

💡 **关键亮点**

本视频深入分析了...

📝 **详细总结**


