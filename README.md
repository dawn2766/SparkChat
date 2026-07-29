# SparkChat voice agent

这是一个最小的 ElevenLabs Speech Engine + 豆包 Seed 2.1 语音智能体。

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

## 说明

`server.py` 使用 OpenAI 兼容接口连接豆包 Seed 2.1，模型默认读取 `ARK_MODEL`，未设置时使用 `doubao-seed-2-1-pro-260628`。ElevenLabs API key 只在服务端使用，浏览器通过 `/api/token` 获取短期 WebRTC token。