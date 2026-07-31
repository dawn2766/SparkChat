# SparkChat voice agent

SparkChat 是一个面向手机 WebView 的数字角色对话应用，包含账号管理、角色与记忆库、流式文本聊天、语音转文字、文本朗读和 ElevenLabs 实时语音通话。

## 前端结构

前端使用原生 ES Modules，不需要额外构建步骤。各层职责如下：

```text
web/
├── index.html              # 页面骨架和静态资源入口
├── styles/
│   ├── app.css             # 样式入口
│   ├── base.css            # 设计变量、重置和基础规则
│   ├── components.css      # 导航、表单、按钮等通用组件
│   ├── views.css           # 认证、联系人、角色、聊天页面
│   └── responsive.css      # 响应式与动效偏好
└── js/
	├── main.js             # 应用启动与页面切换
	├── api.js              # HTTP 与流式聊天请求
	├── state.js            # 共享运行时状态
	├── dom.js              # DOM、转义和通知工具
	└── views/              # 各页面控制器
```

页面模块只负责所属页面的渲染和交互；网络请求统一放在 `api.js`，共享状态统一放在 `state.js`，避免重新把样式、接口和业务逻辑写回 `index.html`。

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
SPARKCHAT_VOICE_MEGADEEP=ElevenLabs中真实的voice_id
SPARKCHAT_VOICE_IRONVOW=ElevenLabs中真实的voice_id
SPARKCHAT_VOICE_STARLIGHT=ElevenLabs中真实的voice_id
SPARKCHAT_VOICE_ARCHIVE=ElevenLabs中真实的voice_id
```

## 2. 创建 Speech Engine

生产环境由 Nginx 将 `/sparkchat/ws` 反向代理到 Speech Engine 本地端口 `3101`，无需 ngrok。写入 `.env`：

```dotenv
SPEECH_ENGINE_WS_URL=wss://visionvoice.cn/sparkchat/ws
SPEECH_ENGINE_PORT=3101
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

配置过 `SPEECH_ENGINE_ID` 后，服务器分别启动 Speech Engine 和 Web 服务：

打开两个 PowerShell 窗口，分别运行：

```powershell
python server.py
```

```powershell
python token_server.py
```

公网浏览器打开 <https://visionvoice.cn/sparkchat/> 并允许麦克风权限。

本地默认地址由 `CLIENT_PORT` 决定，例如 `CLIENT_PORT=3002` 时访问 <http://127.0.0.1:3002/>。消息旁的朗读按钮使用 ElevenLabs，而不是浏览器系统音色；预置的“塞伯坦统帅”需要通过 `SPARKCHAT_VOICE_MEGADEEP` 绑定真实 voice ID。自定义音色在创建成功后会直接保存真实 ID，无需额外映射。

`create_megatron_voice.py` 使用 ElevenLabs Voice Design API 生成原创的 Megatron 风格中文指挥官音色。该 API 要求付费计划；免费计划下应用使用已明确标注的真实预置音色作为临时降级，账号升级后重新运行脚本即可替换，不会伪造生成结果或复用具体演员的声音。

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

当前实时电话由单个 Speech Engine 驱动，只对已绑定该引擎的预置角色开放。自定义角色不会再静默串用威震天的人设；要开放其电话能力，需要为该角色创建独立 Speech Engine，并在令牌接口中维护角色到引擎的映射。