# B 站配置完整指南

本文档包含 B 站 Cookie 获取、配置和自动刷新的完整说明。

## 目录

1. [为什么需要配置](#为什么需要配置)
2. [方式一：手动获取 Cookie](#方式一手动获取cookie)
3. [方式二：手动获取 refresh_token](#方式二手动获取refresh_token)
4. [配置 User-Agent](#配置user-agent)
5. [验证配置](#验证配置)
6. [自动刷新机制](#自动刷新机制)
7. [常见问题](#常见问题)

---

## 为什么需要配置

B 站动态监控功能需要访问 B 站 API，需要以下信息：

- **Cookie**: 用于身份认证，证明你已登录
- **refresh_token**: 用于自动刷新 Cookie，避免频繁手动更新
- **User-Agent**: 浏览器标识，与 Cookie 匹配可降低风控风险

## 方式一：手动获取 Cookie

### 步骤 1：获取 Cookie 字段

1. 打开 [B 站首页](https://www.bilibili.com) 并登录
2. 按 `F12` 打开开发者工具
3. 切换到 `Application` 标签
4. 左侧选择 `Storage` → `Cookies` → `https://www.bilibili.com`
5. 找到以下 Cookie 字段并复制值：
   - `SESSDATA`
   - `bili_jct`
   - `buvid3`
   - `DedeUserID`
   - `DedeUserID__ckMd5`

### 步骤 2：保存到.env 文件

编辑项目根目录的 `.env` 文件，添加：

```env
# B站Cookie配置
SESSDATA=你的SESSDATA值
bili_jct=你的bili_jct值
buvid3=你的buvid3值
DedeUserID=你的DedeUserID值
DedeUserID__ckMd5=你的DedeUserID__ckMd5值
```

### 注意事项

- 所有 Cookie 必须从**同一个浏览器**复制
- Cookie 有效期约 30 天
- 不配置 refresh_token 则需要定期手动更新

---

## 方式二：手动获取 refresh_token

有了 refresh_token，系统可以自动刷新 Cookie，无需手动更新。

### 什么是 refresh_token

refresh_token 是一个长效令牌，当 Cookie 过期时，可以用它向 B 站申请新的 Cookie。

### 获取方法

**在 B 站页面 Console 获取**

1. 在已登录的 B 站页面按 `F12`
2. 切换到 `Console` 标签
3. 输入并回车：
   ```javascript
   localStorage.getItem("ac_time_value");
   ```
4. 复制输出的值（不包括引号）

**如果返回 null**

1. 退出 B 站重新登录
2. 登录后立即执行上述命令
3. 或者从 Application → Local Storage 中查找

### 保存 refresh_token

运行配置工具：

```bash
cd E:\ai_video_robot
uv run python tools/manual_set_refresh_token.py
```

按提示粘贴 refresh_token，工具会自动保存到 `.env` 文件。

### 完整配置示例

```env
# B站Cookie配置
SESSDATA=你的SESSDATA值
bili_jct=你的bili_jct值
buvid3=你的buvid3值
DedeUserID=你的DedeUserID值
DedeUserID__ckMd5=你的DedeUserID__ckMd5值

# 自动刷新配置
refresh_token=你的refresh_token值
```

---

## 配置 User-Agent

为了降低 B 站风控风险，建议配置与浏览器一致的 User-Agent。

### 获取 User-Agent

在 B 站页面 Console 中执行：

```javascript
navigator.userAgent;
```

复制输出的完整字符串。

### 保存配置

运行工具：

```bash
uv run python tools/check_browser_info.py
```

或手动添加到 `.env`：

```env
# 浏览器User-Agent
USER_AGENT=你的User-Agent字符串
```


具体b站api参考文档：[bilibili-API-collect](https://socialsisteryi.github.io/bilibili-API-collect/docs/index.html)