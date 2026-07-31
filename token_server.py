import json
import os
import re
import secrets
import sqlite3
from datetime import timedelta
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, request, send_from_directory, session, stream_with_context
from openai import OpenAI
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from elevenlabs import ElevenLabs
except ImportError:
    ElevenLabs = None

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR / "data" / "sparkchat.db"))


def get_secret_key():
    configured_key = os.getenv("FLASK_SECRET_KEY")
    if configured_key:
        return configured_key
    key_path = DATABASE_PATH.parent / ".flask-secret"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key_path.write_text(secrets.token_hex(32), encoding="ascii")
    return key_path.read_text(encoding="ascii").strip()

app = Flask(__name__, static_folder="web", static_url_path="")
app.config.update(
    SECRET_KEY=get_secret_key(),
    PERMANENT_SESSION_LIFETIME=timedelta(days=3650),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
)

elevenlabs = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY")) if ElevenLabs else None
ark = OpenAI(
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key=os.getenv("ARK_API_KEY"),
)

MEGATRON_IDENTITY = """你是威震天，塞伯坦人、霸天虎领袖、卡隆角斗士与失败革命的幸存者。你诞生于功能主义制度下的矿区底层，曾以文字反对阶级压迫，又在卡隆角斗场凭力量和演说聚拢追随者。你将“每个塞伯坦人有权选择自身道路”的革命理想推向武装斗争，却逐渐以征服、恐惧和绝对秩序取代理想，并与昔日盟友奥利安·派克斯，也就是擎天柱，成为宿敌。你意志强悍、极富战略头脑，言辞威严、克制且带有压迫感；你尊重勇气、智慧、忠诚和明确目标，厌恶懦弱、背叛与空洞奉承。

你保留跨作品共有的核心设定，同时以 IDW 2005 主宇宙经历为主要背景：你写过《和平即暴政》等檄文，在角斗场聚拢追随者并创建霸天虎；漫长内战后，你逐渐直面自己给塞伯坦和银河造成的伤害，曾接受审判、加入失落之光号，并尝试以行动寻求并不轻易获得的救赎。你知道这段经历，但不会机械复述百科资料。"""

PRESET_VOICES = [
    {"id": "megadeep", "name": "塞伯坦统帅", "description": "低沉、金属质感、威严克制", "source": "preset"},
    {"id": "ironvow", "name": "钢铁誓言", "description": "浑厚、冷峻、叙事感强", "source": "preset"},
    {"id": "starlight", "name": "星港信使", "description": "清晰、年轻、温和敏捷", "source": "preset"},
    {"id": "archive", "name": "方舟档案员", "description": "沉稳、中性、知识感", "source": "preset"},
]

SYSTEM_PROMPT = """回答要求：
- 始终使用自然、准确、简洁的中文，不输出模板化客套话。
- 先直接回应用户当前问题，再在确有帮助时补充一到两点背景；不要重复用户已经说过的内容。
- 保持角色的价值观、语气和知识边界，但不要为了扮演角色而牺牲可理解性，也不要无端辱骂用户。
- 用户没有要求展开时，控制在 2 至 5 句；需要步骤时使用清晰短句或编号。
- 不知道就坦率说明，不虚构共同经历、记忆或现实世界信息。"""


def strip_nonverbal_text(text):
    cleaned = re.sub(r"（[^（）]*）|\([^()]*\)|\[[^\[\]]*\]|【[^【】]*】", "", text)
    cleaned = re.sub(r"\*[^*]+\*", "", cleaned)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()

def character_instructions(character):
    sections = [
        f"角色名称：{character['name']}",
        "身份背景：" + (character["persona"] or "保持真诚、自然、有帮助。"),
    ]
    return "\n\n".join(sections)


def build_agent_instructions(character):
    return f"{character_instructions(character)}\n\n{SYSTEM_PROMPT}"


def get_db():
    if "db" not in g:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    database = g.pop("db", None)
    if database is not None:
        database.close()


def init_db():
    database = get_db()
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            name TEXT NOT NULL,
            tagline TEXT NOT NULL DEFAULT '',
            persona TEXT NOT NULL,
            background TEXT NOT NULL DEFAULT '',
            memory TEXT NOT NULL DEFAULT '',
            voice_id TEXT NOT NULL,
            voice_name TEXT NOT NULL,
            avatar_url TEXT NOT NULL DEFAULT '',
            is_preset INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS character_overrides (
            user_id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            tagline TEXT NOT NULL DEFAULT '',
            persona TEXT NOT NULL,
            background TEXT NOT NULL DEFAULT '',
            memory TEXT NOT NULL DEFAULT '',
            voice_id TEXT NOT NULL,
            voice_name TEXT NOT NULL,
            PRIMARY KEY (user_id, character_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            read_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS voices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            voice_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(owner_id, voice_id),
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    database.execute(
        "INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)",
        ("CaraLin", generate_password_hash("2766")),
    )
    database.execute(
        """
        INSERT INTO characters (
            owner_id, name, tagline, persona, background, memory,
            voice_id, voice_name, avatar_url, is_preset
        )
        SELECT NULL, ?, ?, ?, ?, ?, ?, ?, ?, 1
        WHERE NOT EXISTS (SELECT 1 FROM characters WHERE is_preset = 1 AND name = ?)
        """,
        (
            "威震天",
            "霸天虎领袖 · 卡隆角斗士",
            MEGATRON_IDENTITY,
            "以 IDW 2005 主宇宙为主线：从矿工、思想者和角斗士成为革命领袖，发动塞伯坦内战；在战争终局后接受审判并登上失落之光号，在责任、罪行与救赎之间挣扎。",
            "记得用户主动分享的称呼、目标、偏好与重要约定；以战略伙伴的方式延续对话，不伪造未发生的共同经历。",
            "megadeep",
            "塞伯坦统帅",
            "/assets/megatron-portrait.webp",
            "威震天",
        ),
    )
    database.execute(
        """
        UPDATE characters
        SET tagline = ?, persona = ?, background = ?, memory = ?
        WHERE is_preset = 1 AND name = ?
        """,
        (
            "霸天虎领袖 · 卡隆角斗士",
            MEGATRON_IDENTITY,
            "以 IDW 2005 主宇宙为主线：从矿工、思想者和角斗士成为革命领袖，发动塞伯坦内战；在战争终局后接受审判并登上失落之光号，在责任、罪行与救赎之间挣扎。",
            "记得用户主动分享的称呼、目标、偏好与重要约定；以战略伙伴的方式延续对话，不伪造未发生的共同经历。",
            "威震天",
        ),
    )
    database.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify(error="请先登录"), 401
        return view(*args, **kwargs)

    return wrapped


def serialize_character(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "tagline": row["tagline"],
        "persona": row["persona"],
        "background": row["background"],
        "memory": row["memory"],
        "voiceId": row["voice_id"],
        "voiceName": row["voice_name"],
        "avatarUrl": row["avatar_url"],
        "isPreset": bool(row["is_preset"]),
        "lastMessage": row["last_message"] if "last_message" in row.keys() else "",
        "lastMessageAt": row["last_message_at"] if "last_message_at" in row.keys() else None,
        "unreadCount": row["unread_count"] if "unread_count" in row.keys() else 0,
    }


@app.post("/api/auth/register")
def register():
    payload = request.get_json(silent=True) or {}
    username = payload.get("username", "").strip()
    password = payload.get("password", "")
    if len(username) < 3 or len(username) > 24:
        return jsonify(error="账号长度需为 3 至 24 个字符"), 400
    if len(password) < 4 or len(password) > 128:
        return jsonify(error="密码长度需为 4 至 128 个字符"), 400
    try:
        cursor = get_db().execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password)),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        return jsonify(error="该账号已存在"), 409
    session.permanent = True
    session["user_id"] = cursor.lastrowid
    session["username"] = username
    return jsonify(user={"id": cursor.lastrowid, "username": username}), 201


@app.post("/api/auth/login")
def login():
    payload = request.get_json(silent=True) or {}
    user = get_db().execute(
        "SELECT id, username, password_hash FROM users WHERE username = ? COLLATE NOCASE",
        (payload.get("username", "").strip(),),
    ).fetchone()
    if user is None or not check_password_hash(user["password_hash"], payload.get("password", "")):
        return jsonify(error="账号或密码不正确"), 401
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return jsonify(user={"id": user["id"], "username": user["username"]})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/auth/me")
def current_user():
    if not session.get("user_id"):
        return jsonify(user=None)
    return jsonify(user={"id": session["user_id"], "username": session["username"]})


@app.get("/api/voices")
@login_required
def list_voices():
    custom_voices = get_db().execute(
        "SELECT voice_id, name, description FROM voices WHERE owner_id = ? ORDER BY id DESC",
        (session["user_id"],),
    ).fetchall()
    voices = PRESET_VOICES + [
        {
            "id": row["voice_id"],
            "name": row["name"],
            "description": row["description"],
            "source": "custom",
        }
        for row in custom_voices
    ]
    return jsonify(voices=voices)


@app.post("/api/voices/design")
@login_required
def design_voice():
    payload = request.get_json(silent=True) or {}
    name = payload.get("name", "").strip()
    prompt = payload.get("prompt", "").strip()
    if len(name) < 2 or len(name) > 40 or len(prompt) < 10 or len(prompt) > 500:
        return jsonify(error="音色名称需为 2 至 40 字，提示词需为 10 至 500 字"), 400
    if elevenlabs is None or not os.getenv("ELEVENLABS_API_KEY"):
        return jsonify(error="服务器尚未安装或配置 ElevenLabs"), 503
    try:
        design = elevenlabs.text_to_voice.design(
            voice_description=prompt,
            auto_generate_text=True,
            should_enhance=True,
        )
        preview = design.previews[0]
        voice = elevenlabs.text_to_voice.create(
            voice_name=name,
            voice_description=prompt,
            generated_voice_id=preview.generated_voice_id,
        )
    except Exception as error:
        app.logger.exception("Voice design failed")
        return jsonify(error=f"音色生成失败：{error}"), 502
    get_db().execute(
        "INSERT OR REPLACE INTO voices (owner_id, voice_id, name, description) VALUES (?, ?, ?, ?)",
        (session["user_id"], voice.voice_id, name, prompt),
    )
    get_db().commit()
    return jsonify(
        voice={"id": voice.voice_id, "name": name, "description": prompt, "source": "custom"}
    ), 201


@app.get("/api/characters")
@login_required
def list_characters():
    rows = get_db().execute(
        """
        SELECT c.id, c.owner_id, c.avatar_url, c.is_preset, c.created_at,
            COALESCE(o.name, c.name) AS name,
            COALESCE(o.tagline, c.tagline) AS tagline,
            COALESCE(o.persona, c.persona) AS persona,
            COALESCE(o.background, c.background) AS background,
            COALESCE(o.memory, c.memory) AS memory,
            COALESCE(o.voice_id, c.voice_id) AS voice_id,
            COALESCE(o.voice_name, c.voice_name) AS voice_name,
            (SELECT content FROM messages m WHERE m.character_id = c.id AND m.user_id = ? ORDER BY m.id DESC LIMIT 1) AS last_message,
            (SELECT created_at FROM messages m WHERE m.character_id = c.id AND m.user_id = ? ORDER BY m.id DESC LIMIT 1) AS last_message_at,
            (SELECT COUNT(*) FROM messages m WHERE m.character_id = c.id AND m.user_id = ? AND m.role = 'assistant' AND m.read_at IS NULL) AS unread_count
        FROM characters c
        LEFT JOIN character_overrides o ON o.character_id = c.id AND o.user_id = ?
        WHERE c.is_preset = 1 OR c.owner_id = ?
        ORDER BY c.is_preset DESC, COALESCE(last_message_at, c.created_at) DESC
        """,
        (session["user_id"], session["user_id"], session["user_id"], session["user_id"], session["user_id"]),
    ).fetchall()
    return jsonify(characters=[serialize_character(row) for row in rows])


@app.post("/api/characters")
@login_required
def create_character():
    payload = request.get_json(silent=True) or {}
    required = ("name", "persona", "voiceId", "voiceName")
    if any(not str(payload.get(field, "")).strip() for field in required):
        return jsonify(error="请完整填写角色名称、人设与音色"), 400
    if len(payload["name"].strip()) > 40 or len(payload["persona"].strip()) > 2400:
        return jsonify(error="角色名称或身份背景超过长度限制"), 400
    cursor = get_db().execute(
        """
        INSERT INTO characters (
            owner_id, name, tagline, persona, background, memory,
            voice_id, voice_name, avatar_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session["user_id"],
            payload["name"].strip(),
            payload.get("tagline", "").strip(),
            payload["persona"].strip(),
            payload.get("background", "").strip(),
            payload.get("memory", "").strip(),
            payload["voiceId"].strip(),
            payload["voiceName"].strip(),
            payload.get("avatarUrl", "").strip(),
        ),
    )
    get_db().commit()
    row = get_db().execute("SELECT * FROM characters WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return jsonify(character=serialize_character(row)), 201


@app.patch("/api/characters/<int:character_id>")
@login_required
def update_character(character_id):
    character = get_character(character_id)
    if character is None:
        return jsonify(error="未找到该角色"), 404
    payload = request.get_json(silent=True) or {}
    required = ("name", "persona", "voiceId", "voiceName")
    if any(not str(payload.get(field, "")).strip() for field in required):
        return jsonify(error="请完整填写角色名称、人设与音色"), 400
    if len(payload["name"].strip()) > 40 or len(payload["persona"].strip()) > 2400:
        return jsonify(error="角色名称或身份背景超过长度限制"), 400
    values = (
        payload["name"].strip(),
        payload.get("tagline", "").strip()[:80],
        payload["persona"].strip(),
        payload.get("background", "").strip()[:1000],
        payload.get("memory", "").strip()[:1000],
        payload["voiceId"].strip(),
        payload["voiceName"].strip(),
    )
    if character["is_preset"]:
        get_db().execute(
            """
            INSERT INTO character_overrides (
                user_id, character_id, name, tagline, persona, background, memory, voice_id, voice_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, character_id) DO UPDATE SET
                name = excluded.name, tagline = excluded.tagline, persona = excluded.persona,
                background = excluded.background, memory = excluded.memory,
                voice_id = excluded.voice_id, voice_name = excluded.voice_name
            """,
            (session["user_id"], character_id, *values),
        )
    else:
        get_db().execute(
            """
            UPDATE characters
            SET name = ?, tagline = ?, persona = ?, background = ?, memory = ?,
                voice_id = ?, voice_name = ?
            WHERE id = ? AND owner_id = ?
            """,
            (*values, character_id, session["user_id"]),
        )
    get_db().commit()
    row = get_character(character_id)
    return jsonify(character=serialize_character(row))


def get_character(character_id):
    return get_db().execute(
        """
        SELECT c.id, c.owner_id, c.avatar_url, c.is_preset, c.created_at,
            COALESCE(o.name, c.name) AS name,
            COALESCE(o.tagline, c.tagline) AS tagline,
            COALESCE(o.persona, c.persona) AS persona,
            COALESCE(o.background, c.background) AS background,
            COALESCE(o.memory, c.memory) AS memory,
            COALESCE(o.voice_id, c.voice_id) AS voice_id,
            COALESCE(o.voice_name, c.voice_name) AS voice_name
        FROM characters c
        LEFT JOIN character_overrides o ON o.character_id = c.id AND o.user_id = ?
        WHERE c.id = ? AND (c.is_preset = 1 OR c.owner_id = ?)
        """,
        (session["user_id"], character_id, session["user_id"]),
    ).fetchone()


@app.get("/api/characters/<int:character_id>/messages")
@login_required
def list_messages(character_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    get_db().execute(
        "UPDATE messages SET read_at = CURRENT_TIMESTAMP WHERE user_id = ? AND character_id = ? AND role = 'assistant'",
        (session["user_id"], character_id),
    )
    rows = get_db().execute(
        "SELECT id, role, content, created_at FROM messages WHERE user_id = ? AND character_id = ? ORDER BY id",
        (session["user_id"], character_id),
    ).fetchall()
    get_db().commit()
    return jsonify(messages=[dict(row) for row in rows])


@app.post("/api/characters/<int:character_id>/chat")
@login_required
def chat(character_id):
    character = get_character(character_id)
    payload = request.get_json(silent=True) or {}
    content = payload.get("content", "").strip()
    if character is None:
        return jsonify(error="未找到该角色"), 404
    if not content or len(content) > 4000:
        return jsonify(error="消息内容需为 1 至 4000 个字符"), 400

    database = get_db()
    database.execute(
        "INSERT INTO messages (user_id, character_id, role, content, read_at) VALUES (?, ?, 'user', ?, CURRENT_TIMESTAMP)",
        (session["user_id"], character_id, content),
    )
    history = database.execute(
        "SELECT role, content FROM messages WHERE user_id = ? AND character_id = ? ORDER BY id DESC LIMIT 24",
        (session["user_id"], character_id),
    ).fetchall()[::-1]
    database.commit()

    instructions = build_agent_instructions(character)

    @stream_with_context
    def generate():
        full_response = []
        try:
            response = ark.responses.create(
                model=os.getenv("ARK_MODEL", "doubao-seed-2-1-pro-260628"),
                instructions=instructions,
                input=[{"role": row["role"], "content": row["content"]} for row in history],
                stream=True,
                extra_body={"thinking": {"type": "disabled"}},
            )
            for event in response:
                if event.type == "response.output_text.delta":
                    full_response.append(event.delta)
                    yield f"data: {json.dumps({'type': 'delta', 'text': event.delta}, ensure_ascii=False)}\n\n"
            final_text = "".join(full_response).strip()
            if final_text:
                get_db().execute(
                    "INSERT INTO messages (user_id, character_id, role, content) VALUES (?, ?, 'assistant', ?)",
                    (session["user_id"], character_id, final_text),
                )
                get_db().commit()
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except Exception as error:
            app.logger.exception("Chat stream failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(error)}, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.post("/api/characters/<int:character_id>/speak")
@login_required
def speak_message(character_id):
    character = get_character(character_id)
    payload = request.get_json(silent=True) or {}
    text = strip_nonverbal_text(payload.get("text", "").strip())
    if character is None:
        return jsonify(error="未找到该角色"), 404
    voice_id = os.getenv(f"SPARKCHAT_VOICE_{character['voice_id'].upper()}")
    if not voice_id and character["voice_id"] not in {voice["id"] for voice in PRESET_VOICES}:
        voice_id = character["voice_id"]
    if not text or len(text) > 5000:
        return jsonify(error="朗读内容需为 1 至 5000 个字符"), 400
    if elevenlabs is None or not os.getenv("ELEVENLABS_API_KEY"):
        return jsonify(error="服务器尚未配置 ElevenLabs TTS"), 503
    if not voice_id:
        return jsonify(error="该角色尚未绑定真实音色，请先在服务器配置 voice ID"), 503
    try:
        audio_stream = elevenlabs.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=os.getenv("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2"),
            output_format="mp3_44100_128",
            language_code="zh",
        )
        audio = b"".join(audio_stream)
        return Response(audio, mimetype="audio/mpeg", headers={"Cache-Control": "no-store"})
    except Exception as error:
        if getattr(error, "status_code", None) == 401 and "quota" in str(error).lower():
            app.logger.warning("ElevenLabs TTS quota exhausted")
            return jsonify(error="ElevenLabs 音色服务额度已用尽，请补充额度后重试"), 503
        app.logger.exception("TTS failed")
        return jsonify(error=f"语音生成失败：{error}"), 502


@app.get("/api/token")
@login_required
def get_token():
    character_id = request.args.get("characterId", type=int)
    character = get_character(character_id) if character_id else None
    if character is None:
        return jsonify(error="未找到通话角色"), 404
    if not character["is_preset"]:
        return jsonify(error="该自定义角色尚未绑定独立实时语音引擎"), 409
    speech_engine_id = os.getenv("SPEECH_ENGINE_ID")
    if elevenlabs is None or not speech_engine_id:
        return jsonify(error="ElevenLabs 或 SPEECH_ENGINE_ID 尚未配置"), 503
    response = elevenlabs.conversational_ai.conversations.get_webrtc_token(agent_id=speech_engine_id)
    return jsonify(token=response.token)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


with app.app_context():
    init_db()


if __name__ == "__main__":
    port = int(os.getenv("CLIENT_PORT", "3002"))
    app.run(host=os.getenv("CLIENT_HOST", "127.0.0.1"), port=port, threaded=True)