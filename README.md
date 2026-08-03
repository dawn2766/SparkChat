# SparkChat PWA

SparkChat 是面向移动设备的可安装数字角色对话 PWA，包含账号与角色管理、流式文本聊天、系统音色选择、语音识别、语音合成和端到端实时语音对话。应用壳支持离线打开，联网 API、SSE 和实时语音始终直连服务端，不进入离线缓存。

## 项目结构

```text
SparkChat/
├── backend/                 # 后端应用与豆包服务模块
│   ├── app.py               # Flask API 与 Web 入口
│   ├── speech.py            # 豆包语音合成封装
│   ├── realtime_server.py   # 实时语音代理实现
│   ├── realtime_protocol.py # 实时语音协议编解码
│   ├── web.py               # Flask / WSGI 入口
│   └── realtime.py          # 实时语音命令入口
├── frontend/                # 无构建步骤的原生 ES Modules PWA
│   ├── assets/              # 图标与图片
│   ├── scripts/             # 状态、API、视图和语音模块
│   ├── styles/              # 分层样式
│   ├── index.html
│   ├── manifest.webmanifest
│   └── service-worker.js
├── data/                    # 本地 SQLite 数据（不提交）
├── docs/                    # 需求和验收文档
├── tests/                   # 后端与前端测试
├── .env.example             # 环境变量模板
├── requirements.txt         # Python 依赖
├── start.ps1                # Windows 一键启动
└── README.md                # 项目说明
```

根目录只保留项目元数据、启动脚本和文档；业务源码统一位于 `backend/` 和 `frontend/`。

## 安装

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

复制 `.env.example` 所需字段到 `.env`。豆包语音统一使用新版控制台 API Key：

```dotenv
# 豆包新版控制台 API Key：V3 TTS 和实时语音
DOUBAO_SPEECH_API_KEY=
DOUBAO_REALTIME_RESOURCE_ID=volc.speech.dialog
DOUBAO_REALTIME_PUBLIC_WS=/sparkchat/realtime

ARK_API_KEY=
ARK_MODEL=doubao-seed-character-260628
FLASK_SECRET_KEY=请使用稳定的长随机字符串

SPEECH_ENGINE_PORT=3101
CLIENT_PORT=3002
CLIENT_HOST=127.0.0.1
COOKIE_SECURE=false
```

文本角色回复使用火山方舟模型列表中的 `doubao-seed-character-260628`，也可以通过 `ARK_MODEL` 指定项目内已开通的同类接入点。角色的回答语言保存在角色配置中，支持 `zh`（中文）和 `en`（英文）；威震天默认使用英文。

音色属于数字角色，而不是独立的用户资源。系统通过 `/api/voices` 提供只读音色目录，角色记录中的 `voice_id` 保存真实豆包 speaker ID；预置角色的用户级覆盖也保存自己的 speaker ID。聊天朗读和端到端实时语音都直接读取同一角色 speaker，因此不存在 TTS 音色与实时音色的两套环境映射，也不提供自定义音色设计、声音复刻、训练状态、试听或重命名功能。

聊天朗读使用豆包 V3 HTTP Chunked TTS，资源 `seed-icl-2.0`、模型 `seed-tts-2.0-expressive`，统一通过新版控制台 `X-Api-Key` 鉴权。实时 WebSocket 资源 ID 使用 `DOUBAO_REALTIME_RESOURCE_ID`，角色 speaker 由服务端按角色返回，API Key 不暴露给浏览器。

文本聊天模型可在需要表现情绪、动作或细微表情时，在台词前生成简短括号舞台提示。聊天朗读不会读出提示，使用 `seed-tts-2.0-expressive` 和 `<cot>` 分段语音标签。端到端实时语音不使用括号协议，只将角色身份、回答规则和 `speaking_style` 发送给实时模型，由模型直接控制语音表现。

若 API 未授权、资源未开通或额度不足，接口返回 `actionUrl`，前端会打开[豆包语音控制台](https://console.volcengine.com/speech/new)供管理员处理。

## 本地启动

打开两个终端：

```powershell
python -m backend.realtime
```

文本 Web 服务和实时语音代理需要同时运行。实时代理使用 `SPEECH_ENGINE_PORT`，公网 Nginx 应将 `DOUBAO_REALTIME_PUBLIC_WS` 对应路径转发到该端口。

```powershell
python -m backend.app
```

也可以执行：

```powershell
.\start.ps1
```

Web 服务默认位于 <http://127.0.0.1:3002/>，豆包实时代理监听 `127.0.0.1:3101`。浏览器需要麦克风权限。

## SparkChat-Server 部署

Web 服务使用 Gunicorn：

```bash
gunicorn --workers 2 --threads 4 --bind 127.0.0.1:3002 backend.web:app
```

实时代理独立运行：

```bash
python -m backend.realtime
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

- 音色目录：`GET /api/voices` 返回系统可用音色，角色创建和编辑时由后端校验 speaker ID 属于该目录。
- 音色归属：每个角色和预置角色覆盖记录独立保存 `voice_id` 与 `voice_name`；前端不再提供“我的音色”或自定义音色入口。
- 聊天朗读：`POST /api/characters/:id/speak` 调用豆包 V3 HTTP Chunked TTS。
- 聊天听写：浏览器上传 16 kHz PCM，经实时代理读取 `451 ASRResponse`。
- 实时通话：代理连接 `wss://openspeech.bytedance.com/api/v3/realtime/dialogue`；`ICL_uranus_...` ICL V3 音色使用 O2.0 `2.1.0.0`，SC2.0 音色使用 `2.2.0.0`，输入 16 kHz PCM，输出 24 kHz PCM。

## 验证

```powershell
python -m unittest -v tests.test_app
node tests/frontend/doubao-realtime.test.mjs
Get-Content frontend/scripts/main.js | node --input-type=module --check
Get-Content frontend/service-worker.js | node --input-type=module --check
```

PWA 安装与 service worker 仅在 HTTPS 或 `localhost` 安全上下文中启用。部署在 `/sparkchat/` 等子路径时，清单、API 和离线回退会沿当前应用路径解析。

真实服务器验收需逐项检查登录、文本聊天、系统音色选择、朗读、听写、实时通话建连、字幕、音频播放、静音和挂断，并记录响应头 `X-Tt-Logid`。新增角色或编辑角色时，应确认 TTS 与实时通话返回同一个角色 `voiceId`。