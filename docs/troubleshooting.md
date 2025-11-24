# 故障排除指南

本文档提供 AI Studio Proxy API 项目常见问题的解决方案和调试方法，涵盖安装、配置、运行、API 使用等各个方面。

## 快速诊断

在深入具体问题之前，可以先进行快速诊断：

### 1. 检查服务状态

```bash
# 检查服务是否正常运行
curl http://127.0.0.1:2048/health

# 检查API信息
curl http://127.0.0.1:2048/api/info
```

### 2. 检查配置文件

```bash
# 检查 .env 文件是否存在
ls -la .env

# 检查关键配置项
grep -E "(PORT|SCRIPT_INJECTION|LOG_LEVEL)" .env
```

### 3. 查看日志

```bash
# 查看最新日志
tail -f logs/app.log

# 查看错误日志
grep -i error logs/app.log
```

## 安装相关问题

### Python 版本兼容性问题

**Python 版本过低**:

- **最低要求**: Python 3.9+
- **推荐版本**: Python 3.10+ 或 3.11+
- **检查版本**: `python --version`

**常见版本问题**:

```bash
# Python 3.8 或更低版本可能出现的错误
TypeError: 'type' object is not subscriptable
SyntaxError: invalid syntax (类型提示相关)

# 解决方案：升级 Python 版本
# macOS (使用 Homebrew)
brew install python@3.11

# Ubuntu/Debian
sudo apt update && sudo apt install python3.11

# Windows: 从 python.org 下载安装
```

**虚拟环境版本问题**:

```bash
# 检查虚拟环境中的 Python 版本
python -c "import sys; print(sys.version)"

# 使用指定版本创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate  # Windows
```

### `pip install camoufox[geoip]` 失败

- 可能是网络问题或缺少编译环境。尝试不带 `[geoip]` 安装 (`pip install camoufox`)。

### `camoufox fetch` 失败

- 常见原因是网络问题或 SSL 证书验证失败。
- 可以尝试运行 [`python fetch_camoufox_data.py`](../fetch_camoufox_data.py) 脚本，它会尝试禁用 SSL 验证来下载 (有安全风险，仅在确认网络环境可信时使用)。

### `playwright install-deps` 失败

- 通常是 Linux 系统缺少必要的库。仔细阅读错误信息，根据提示安装缺失的系统包 (如 `libgbm-dev`, `libnss3` 等)。

## 启动相关问题

### `launch_camoufox.py` 启动报错

- 检查 Camoufox 是否已通过 `camoufox fetch` 正确下载。
- 查看终端输出，是否有来自 Camoufox 库的具体错误信息。
- 确保没有其他 Camoufox 或 Playwright 进程冲突。

### 端口被占用

如果 [`server.py`](../server.py) 启动时提示端口 (`2048`) 被占用：

- 如果使用 [`gui_launcher.py`](../gui_launcher.py) 启动，它会尝试自动检测并提示终止占用进程。
- 手动查找并结束占用进程：

  ```bash
  # Windows
  netstat -ano | findstr 2048

  # Linux/macOS
  lsof -i :2048
  ```

- 或修改 [`launch_camoufox.py`](../launch_camoufox.py) 的 `--server-port` 参数。

### Camoufox 启动时 proxy 错误

**问题现象**: 未配置代理环境变量时，Camoufox 启动失败：

```
Error: proxy: expected object, got null
```

**原因**: Camoufox 0.4.11 的 utils.py 会无条件传递 proxy 参数给 Playwright，即使值为 None。

**修复方法**: 修改 Camoufox 源码文件：

```
/usr/local/lib/python3.10/site-packages/camoufox/utils.py
```

在 `launch_options` 函数中，将：

```python
return {
    ...
    "proxy": proxy,
    ...
}
```

改为：

```python
result = {
    ...  # 删除 "proxy": proxy,其他配置保持不变
}
if proxy is not None:
    result["proxy"] = proxy
return result
```

## 认证相关问题

### 认证失败 (特别是无头模式)

**最常见**: `auth_profiles/active/` 下的 `.json` 文件已过期或无效。

**解决方案**:

1. 删除 `active` 下的文件
2. 重新运行 [`python launch_camoufox.py --debug`](../launch_camoufox.py) 生成新的认证文件
3. 将新文件移动到 `active` 目录
4. 确认 `active` 目录下只有一个 `.json` 文件

### 检查认证状态

- 查看 [`server.py`](../server.py) 日志（可通过 Web UI 的日志侧边栏查看，或 `logs/app.log`）
- 看是否明确提到登录重定向

## 流式代理服务问题

### 端口冲突

确保流式代理服务使用的端口 (`3120` 或自定义的 `--stream-port`) 未被其他应用占用。

### 代理配置问题

**推荐使用 .env 配置方式**:

```env
# 统一代理配置
UNIFIED_PROXY_CONFIG=http://127.0.0.1:7890
# 或禁用代理
UNIFIED_PROXY_CONFIG=
```

**常见问题**:

- **代理不生效**: 确保在 `.env` 文件中设置 `UNIFIED_PROXY_CONFIG` 或使用 `--internal-camoufox-proxy` 参数
- **代理冲突**: 使用 `UNIFIED_PROXY_CONFIG=` 或 `--internal-camoufox-proxy ''` 明确禁用代理
- **代理连接失败**: 检查代理服务器是否可用，代理地址格式是否正确

### 三层响应获取机制问题

**流式响应中断**:

- 检查集成流式代理状态 (端口 3120)
- 尝试禁用流式代理测试：在 `.env` 中设置 `STREAM_PORT=0`
- 查看 `/health` 端点了解各层状态

**响应获取失败**:

1. **第一层失败**: 检查流式代理服务是否正常运行
2. **第二层失败**: 验证 Helper 服务配置和认证文件
3. **第三层失败**: 检查 Playwright 浏览器连接状态

详细说明请参见 [流式处理模式详解](streaming-modes.md)。

### 自签名证书管理

集成的流式代理服务会在 `certs` 文件夹内生成自签名的根证书。

**证书删除与重新生成**:

- 可以删除 `certs` 目录下的根证书 (`ca.crt`, `ca.key`)，代码会在下次启动时重新生成
- **重要**: 删除根证书时，**强烈建议同时删除 `certs` 目录下的所有其他文件**，避免信任链错误

## API 请求问题

### 5xx / 499 错误

- **503 Service Unavailable**: [`server.py`](../server.py) 未完全就绪
- **504 Gateway Timeout**: AI Studio 响应慢或处理超时
- **502 Bad Gateway**: AI Studio 页面返回错误。检查 `errors_py/` 快照
- **500 Internal Server Error**: [`server.py`](../server.py) 内部错误。检查日志和 `errors_py/` 快照
- **499 Client Closed Request**: 客户端提前断开连接

### 客户端无法连接

- 确认 API 基础 URL 配置正确 (`http://<服务器IP或localhost>:端口/v1`，默认端口 2048)
- 检查 [`server.py`](../server.py) 日志是否有错误

### AI 回复不完整/格式错误

- AI Studio Web UI 输出不稳定。检查 `errors_py/` 快照

## 页面交互问题

### 自动清空上下文失败

- 检查主服务器日志中的警告
- 很可能是 AI Studio 页面更新导致 [`config/selectors.py`](../config/selectors.py) 中的 CSS 选择器失效
- 检查 `errors_py/` 快照，对比实际页面元素更新选择器常量

### AI Studio 页面更新导致功能失效

如果 AI Studio 更新了网页结构或 CSS 类名：

1. 检查主服务器日志中的警告或错误
2. 检查 `errors_py/` 目录下的错误快照
3. 对比实际页面元素，更新 [`config/selectors.py`](../config/selectors.py) 中对应的 CSS 选择器常量

### 模型参数设置未生效

这可能是由于 AI Studio 页面的 `localStorage` 中的 `isAdvancedOpen` 未正确设置为 `true`：

- 代理服务在启动时会尝试自动修正这些设置并重新加载页面
- 如果问题依旧，可以尝试清除浏览器缓存和 `localStorage` 后重启代理服务

## Web UI 问题

### 无法显示日志或服务器信息

- 检查浏览器开发者工具 (F12) 的控制台和网络选项卡是否有错误
- 确认 WebSocket 连接 (`/ws/logs`) 是否成功建立
- 确认 `/health` 和 `/api/info` 端点是否能正常访问

## API 密钥相关问题

### key.txt 文件问题

**文件不存在或为空**:

- 系统会自动创建空的 `auth_profiles/key.txt` 文件
- 空文件意味着不需要 API 密钥验证
- 如需启用验证，手动添加密钥到文件中

**文件权限问题**:

```bash
# 检查文件权限
ls -la key.txt

# 修复权限问题
chmod 644 key.txt
```

**文件格式问题**:

- 确保每行一个密钥，无额外空格
- 支持空行和以 `#` 开头的注释行
- 使用 UTF-8 编码保存文件

### API 认证失败

**401 Unauthorized 错误**:

- 检查请求头是否包含正确的认证信息
- 验证密钥是否在 `key.txt` 文件中
- 确认使用正确的认证头格式：
  ```bash
  Authorization: Bearer your-api-key
  # 或
  X-API-Key: your-api-key
  ```

**密钥验证逻辑**:

- 如果 `key.txt` 为空，所有请求都不需要认证
- 如果 `key.txt` 有内容，所有 `/v1/*` 请求都需要认证
- 除外路径：`/v1/models`, `/health`, `/docs` 等

### Web UI 密钥管理问题

**无法验证密钥**:

- 检查输入的密钥格式，确保至少 8 个字符
- 确认服务器上的 `key.txt` 文件包含该密钥
- 检查网络连接，确认 `/api/keys/test` 端点可访问

**验证成功但无法查看密钥列表**:

- 检查浏览器控制台是否有 JavaScript 错误
- 确认 `/api/keys` 端点返回正确的 JSON 格式数据
- 尝试刷新页面重新验证

**验证状态丢失**:

- 验证状态仅在当前浏览器会话中有效
- 关闭浏览器或标签页会丢失验证状态
- 需要重新验证才能查看密钥列表

**密钥显示异常**:

- 确认服务器返回的密钥数据格式正确
- 检查密钥打码显示功能是否正常工作
- 验证 `maskApiKey` 函数是否正确执行

### 客户端配置问题

**Open WebUI 配置**:

- API 基础 URL：`http://127.0.0.1:2048/v1`
- API 密钥：输入有效的密钥或留空（如果服务器不需要认证）
- 确认端口号与服务器实际监听端口一致

**其他客户端配置**:

- 检查客户端是否支持 `Authorization: Bearer` 认证头
- 确认客户端正确处理 401 认证错误
- 验证客户端的超时设置是否合理

### 密钥管理最佳实践

**安全建议**:

- 定期更换 API 密钥
- 不要在日志或公开场所暴露完整密钥
- 使用足够复杂的密钥（建议 16 个字符以上）
- 限制密钥的使用范围和权限

**备份建议**:

- 定期备份 `key.txt` 文件
- 记录密钥的创建时间和用途
- 建立密钥轮换机制

### 对话功能问题

- **发送消息后收到 401 错误**: API 密钥认证失败，需要重新验证密钥
- **无法发送空消息**: 这是正常的安全机制
- **对话请求失败**: 检查网络连接，确认服务器正常运行

## 脚本注入问题 🆕

### 脚本注入功能未启用

**检查配置**:

```bash
# 检查 .env 文件中的配置
grep SCRIPT_INJECTION .env
grep USERSCRIPT_PATH .env
```

**常见问题**:

- `ENABLE_SCRIPT_INJECTION=false` - 功能被禁用
- 脚本文件路径不正确
- 脚本文件不存在或无法读取

**解决方案**:

```bash
# 启用脚本注入
echo "ENABLE_SCRIPT_INJECTION=true" >> .env

# 检查脚本文件是否存在
ls -la browser_utils/more_modles.js

# 检查文件权限
chmod 644 browser_utils/more_modles.js
```

### 模型未显示在列表中

**前端检查**:

1. 打开浏览器开发者工具 (F12)
2. 查看控制台是否有 JavaScript 错误
3. 检查网络选项卡中的模型列表请求

**后端检查**:

```bash
# 查看脚本注入相关日志
python launch_camoufox.py --debug | grep -i "script\|inject\|model"

# 检查 API 响应
curl http://localhost:2048/v1/models | jq '.data[] | select(.injected == true)'
```

**常见原因**:

- 脚本格式错误，无法解析 `MODELS_TO_INJECT` 数组
- 网络拦截失败，脚本注入未生效
- 模型名称格式不正确

### 脚本解析失败

**检查脚本格式**:

```javascript
// 确保脚本包含正确的模型数组格式
const MODELS_TO_INJECT = [
  {
    name: "models/your-model-name",
    displayName: "Your Model Display Name",
    description: "Model description",
  },
];
```

**调试步骤**:

1. 验证脚本文件的 JavaScript 语法
2. 检查模型数组的格式是否正确
3. 确认模型名称以 `models/` 开头

### 网络拦截失败

**检查 Playwright 状态**:

- 确认浏览器上下文正常创建
- 检查网络路由是否正确设置
- 验证请求 URL 匹配规则

**调试方法**:

```bash
# 启用详细日志查看网络拦截状态
export DEBUG_LOGS_ENABLED=true
python launch_camoufox.py --debug
```

**常见错误**:

- 浏览器上下文创建失败
- 网络路由设置异常
- 请求 URL 不匹配拦截规则

### 模型解析问题

**脚本格式错误**:

```bash
# 检查脚本文件语法
node -c browser_utils/more_modles.js
```

**文件权限问题**:

```bash
# 检查文件权限
ls -la browser_utils/more_modles.js

# 修复权限
chmod 644 browser_utils/more_modles.js
```

**脚本文件不存在**:

- 系统会静默跳过不存在的脚本文件
- 检查 `USERSCRIPT_PATH` 环境变量设置
- 确保脚本文件包含有效的 `MODELS_TO_INJECT` 数组

### 性能问题

**脚本注入延迟**:

- 网络拦截可能增加轻微延迟
- 大量模型注入可能影响页面加载
- 建议限制注入模型数量（< 20 个）

**内存使用**:

- 脚本内容会被缓存在内存中
- 大型脚本文件可能增加内存使用
- 定期重启服务释放内存

### 调试技巧

**启用详细日志**:

```bash
# 在 .env 文件中添加
DEBUG_LOGS_ENABLED=true
TRACE_LOGS_ENABLED=true
SERVER_LOG_LEVEL=DEBUG
```

**检查注入状态**:

```bash
# 查看脚本注入相关的日志输出
tail -f logs/app.log | grep -i "script\|inject"
```

**验证模型注入**:

```bash
# 检查 API 返回的模型列表
curl -s http://localhost:2048/v1/models | jq '.data[] | select(.injected == true) | {id, display_name}'
```

### 禁用脚本注入

如果遇到严重问题，可以临时禁用脚本注入：

```bash
# 方法1：修改 .env 文件
echo "ENABLE_SCRIPT_INJECTION=false" >> .env

# 方法2：使用环境变量
export ENABLE_SCRIPT_INJECTION=false
python launch_camoufox.py --headless

# 方法3：删除脚本文件（临时）
mv browser_utils/more_modles.js browser_utils/more_modles.js.bak
```

## 日志和调试

### 查看详细日志

- `logs/app.log`: FastAPI 服务器详细日志
- `logs/launch_app.log`: 启动器日志
- Web UI 右侧边栏: 实时显示 `INFO` 及以上级别的日志

### 环境变量控制

可以通过环境变量控制日志详细程度：

```bash
# 设置日志级别
export SERVER_LOG_LEVEL=DEBUG

# 启用详细调试日志
export DEBUG_LOGS_ENABLED=true

# 启用跟踪日志（通常不需要）
export TRACE_LOGS_ENABLED=true
```

### 错误快照

出错时会自动在 `errors_py/` 目录保存截图和 HTML，这些文件对调试很有帮助。

## 性能问题

### Asyncio 相关错误

您可能会在日志中看到一些与 `asyncio` 相关的错误信息，特别是在网络连接不稳定时。如果核心代理功能仍然可用，这些错误可能不直接影响主要功能。

### 首次访问新主机的性能问题

当通过流式代理首次访问一个新的 HTTPS 主机时，服务需要动态生成证书，这个过程可能比较耗时。一旦证书生成并缓存后，后续访问会显著加快。

## 获取帮助

如果问题仍未解决：

1. 查看项目的 [GitHub Issues](https://github.com/CJackHwang/AIstudioProxyAPI/issues)
2. 提交新的 Issue 并包含：
   - 详细的错误描述
   - 相关的日志文件内容
   - 系统环境信息
   - 复现步骤

## 下一步

故障排除完成后，请参考：

- [脚本注入指南](script_injection_guide.md) - 脚本注入功能详细说明
- [日志控制指南](logging-control.md)
- [高级配置指南](advanced-configuration.md)

---

## Authentication Rotation Failures

### Error: "Rotation Failed: No available auth profiles found"

**Symptom:**
The server log shows a critical error `Rotation Failed: No available auth profiles found`, and the system may enter "Emergency Operation Mode." This typically happens after a series of token limit, quota, or rate limit errors.

**Cause:**
This error is not a bug in the rotation logic. It means the system has run out of healthy, usable authentication profiles. The "smart rotation" mechanism has scanned all profile directories (`auth_profiles/saved`, `auth_profiles/active`, and `auth_profiles/emergency`) and found that every single profile is currently in a "cooldown" state.

A profile is put into cooldown if:
1.  It has just hit a rate limit or quota limit.
2.  It failed a "canary test," meaning it was selected for rotation but was found to be unhealthy or expired.

**Strategic Solution: Managing Profile Pools**

You are correct that simply copying the same profile into all three directories (`saved`, `active`, `emergency`) will **not** solve the problem. The cooldown is tied to the profile's file path and, more importantly, to the underlying account that is rate-limited.

The directories are meant to hold **different, unique** profiles to create layers of resilience:

1.  **`auth_profiles/saved` (Primary Pool):** This should be your main collection of healthy, unique profiles. The system will primarily use these.
2.  **`auth_profiles/emergency` (Backup Pool):** This should contain a separate, smaller set of unique profiles that are *only* used when the primary pool is completely exhausted. Do not duplicate profiles from the `saved` directory here.
3.  **`auth_profiles/active`:** This directory is for internal state management of the currently active profile. You should not place files here manually.

**How to Fix and Prevent This Error:**

1.  **Immediate Action: Wait.** The system will automatically recover once the cooldown timers on the profiles expire. You can see the cooldown duration in the logs when a profile is placed on cooldown.
2.  **Long-Term Solution: Increase Profile Diversity.** The most effective way to prevent this is to increase the total number of **unique** authentication profiles in your `auth_profiles/saved` and `auth_profiles/emergency` directories. A larger and more diverse pool of profiles makes it statistically much less likely that all of them will be on cooldown at the same time.
3.  **Review Cooldown Timers:** If this happens frequently, you can review the `RATE_LIMIT_COOLDOWN_SECONDS` and `QUOTA_EXCEEDED_COOLDOWN_SECONDS` settings in the `config/timeouts.py` file, but the primary solution should be to add more profiles.
