# SparkChat voice agent

SparkChat 是一个面向手机 WebView 的数字角色对话应用，包含账号管理、角色与记忆库、流式文本聊天、语音转文字、文本朗读和 ElevenLabs 实时语音通话。

## 1. 安装依赖

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

确保 `.env` 至少包含：

```dotenv
ELEVENLABS_API_KEY=...
ARK_API_KEY=...
FLASK_SECRET_KEY=请使用稳定的长随机字符串
```

## 2. 创建 Speech Engine

先让公网 WebSocket 地址指向 Speech Engine 本地端口（默认 3101）：

```powershell
ngrok http 3101
```

把 ngrok 的 HTTPS 地址改成 `wss://.../ws`，写入 `.env`：

```dotenv
SPEECH_ENGINE_WS_URL=wss://your-ngrok-host.ngrok-free.app/ws
```

然后创建 Speech Engine：

```powershell
python create_engine.py
```

把打印出的 ID 写入 `.env`：

```dotenv
SPEECH_ENGINE_ID=seng_...
```

## 3. 启动

配置过 `SPEECH_ENGINE_ID` 后，推荐使用一键启动脚本。它会启动或复用 ngrok、同步最新公网 URL，并启动两个服务：

```powershell
.\start.ps1
```

也可以打开两个 PowerShell 窗口手动运行：

打开两个 PowerShell 窗口，分别运行：

```powershell
python server.py
```

```powershell
python token_server.py
```

浏览器打开 <http://127.0.0.1:3002>，点击“开始对话”并允许麦克风权限。

预置登录账号为 `CaraLin`，密码为 `2766`。首次启动会在 `data/sparkchat.db` 创建 SQLite 数据库；账号、角色、消息和自定义音色均按用户保存。登录 Cookie 默认保存十年，生产环境必须保持 `FLASK_SECRET_KEY` 不变。

## 测试

```powershell
python -m unittest -v test_app.py
```

生产环境可使用：

```bash
gunicorn --workers 2 --threads 4 --bind 127.0.0.1:3002 token_server:app
```

## 说明

`server.py` 使用 OpenAI 兼容接口连接豆包 Seed 2.1，模型默认读取 `ARK_MODEL`，未设置时使用 `doubao-seed-2-1-pro-260628`。ElevenLabs API key 只在服务端使用，浏览器通过 `/api/token` 获取短期 WebRTC token。