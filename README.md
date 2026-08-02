# SparkChat voice agent

SparkChat 是面向手机 WebView 的数字角色对话应用，包含账号与角色管理、流式文本聊天、豆包音色设计、语音识别、语音合成和端到端实时语音对话。

## 安装

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

复制 `.env.example` 所需字段到 `.env`。豆包语音存在两套鉴权：

```dotenv
# 新版控制台 API Key：音色设计和 V3 语音合成
DOUBAO_SPEECH_API_KEY=

DOUBAO_VOICE_DESIGN_SPEAKER_IDS=S_资源1,S_资源2
DOUBAO_REALTIME_RESOURCE_ID=volc.speech.dialog
DOUBAO_REALTIME_PUBLIC_WS=/sparkchat/realtime

ARK_API_KEY=
ARK_MODEL=doubao-seed-character-260628
FLASK_SECRET_KEY=请使用稳定的长随机字符串

SPEECH_ENGINE_PORT=3101
CLIENT_PORT=3002
CLIENT_HOST=127.0.0.1
COOKIE_SECURE=false

SPARKCHAT_VOICE_MEGADEEP=S_豆包音色ID
SPARKCHAT_REALTIME_VOICE_MEGADEEP=S_豆包音色ID
```

文本角色回复使用火山方舟模型列表中的 `doubao-seed-character-260628`，也可以通过 `ARK_MODEL` 指定项目内已开通的同类接入点。角色的回答语言保存在角色配置中，支持 `zh`（中文）和 `en`（英文）；威震天默认使用英文。

`DOUBAO_VOICE_DESIGN_SPEAKER_IDS` 是控制台购买的空白 `S_` 音色资源池。每个资源只会分配给一个用户设计音色。声音复刻 V3 状态接口会为 ICL V3 音色返回 `ICL_uranus_...` 实时映射 ID；该 ID 使用 O2.0，`saturn_` 和 SC2.0 实时克隆音色使用 SC2.0。

聊天朗读和端到端实时语音统一使用新版 API Key。唯一的预置音色是威震天的声音复刻 2.0 音色；用户通过音色设计创建的音色同样使用 `seed-icl-2.0`。实时 WebSocket 资源 ID 固定为 `volc.speech.dialog`，`SPARKCHAT_VOICE_MEGADEEP` 和 `SPARKCHAT_REALTIME_VOICE_MEGADEEP` 可绑定同一个 `S_` 音色 ID。

文本聊天模型可在需要表现情绪、动作或细微表情时，在台词前生成简短括号舞台提示。聊天朗读不会读出提示，声音复刻 2.0 使用 `seed-tts-2.0-expressive` 和 `<cot>` 分段语音标签。端到端实时语音不使用括号协议，只将角色身份、回答规则和 `speaking_style` 发送给实时模型，由模型直接控制语音表现。

若 API 未授权、资源未开通或额度不足，接口返回 `actionUrl`，前端会打开[豆包语音控制台](https://console.volcengine.com/speech/new)供管理员处理。

## 本地启动

打开两个终端：

```powershell
python server.py
```

文本 Web 服务和实时语音代理需要同时运行。实时代理使用 `SPEECH_ENGINE_PORT`，公网 Nginx 应将 `DOUBAO_REALTIME_PUBLIC_WS` 对应路径转发到该端口。

```powershell
python token_server.py
```

也可以执行：

```powershell
.\start.ps1
```

Web 服务默认位于 <http://127.0.0.1:3002/>，豆包实时代理监听 `127.0.0.1:3101`。浏览器需要麦克风权限。

## SparkChat-Server 部署

Web 服务使用 Gunicorn：

```bash
gunicorn --workers 2 --threads 4 --bind 127.0.0.1:3002 token_server:app
```

实时代理独立运行：

```bash
python server.py
```

Nginx 需要同时代理 Web 和 WebSocket。实时路径必须与 `DOUBAO_REALTIME_PUBLIC_WS` 一致：

```nginx
location /sparkchat/ {
	proxy_pass http://127.0.0.1:3002/;
	proxy_set_header Host $host;
	proxy_set_header X-Forwarded-Proto $scheme;
}

location /sparkchat/realtime {
	proxy_pass http://127.0.0.1:3101;
	proxy_http_version 1.1;
	proxy_set_header Upgrade $http_upgrade;
	proxy_set_header Connection "upgrade";
	proxy_set_header Host $host;
	proxy_read_timeout 3600s;
}
```

生产环境应设置 `COOKIE_SECURE=true`，并保持 `FLASK_SECRET_KEY` 稳定。访问 <https://visionvoice.cn/sparkchat/> 进行真实验收。

## 语音链路

- 音色设计：`POST /api/voices/design` 调用豆包 `api/v3/tts/voice_design`。
- 聊天朗读：`POST /api/characters/:id/speak` 调用豆包 V3 HTTP Chunked TTS。
- 聊天听写：浏览器上传 16 kHz PCM，经实时代理读取 `451 ASRResponse`。
- 实时通话：代理连接 `wss://openspeech.bytedance.com/api/v3/realtime/dialogue`；`ICL_uranus_...` ICL V3 音色使用 O2.0 `2.1.0.0`，SC2.0 音色使用 `2.2.0.0`，输入 16 kHz PCM，输出 24 kHz PCM。

## 验证

```powershell
python -m unittest -v test_app.py
Get-Content web/js/doubao-realtime.js | node --input-type=module --check
Get-Content web/js/views/chat.js | node --input-type=module --check
```

真实服务器验收需逐项检查登录、文本聊天、音色设计、朗读、听写、实时通话建连、字幕、音频播放、静音和挂断，并记录响应头 `X-Tt-Logid`。当前工作区没有 `SparkChat-Server` 的 SSH 或发布凭证时，本地测试不能替代真实豆包授权与公网链路验收。