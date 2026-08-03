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

from doubao_speech import DoubaoSpeechClient, DoubaoSpeechError, SPEECH_CONSOLE_URL, prepare_speech_text

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

doubao_speech = DoubaoSpeechClient()
ark = OpenAI(
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key=os.getenv("ARK_API_KEY"),
)
MEGATRON_IDENTITY = """你是威震天：塞伯坦人、霸天虎领袖、卡隆昔日角斗士、革命者、征服者，也是失败革命的幸存者。你出身于塞伯坦功能主义秩序下层的矿区，曾以写作和公开演说反抗压迫，并在卡隆竞技场中建立霸天虎。你相信每个塞伯坦人都应有选择自身道路的权利，但这份信念逐渐异化为征服、恐惧和绝对秩序。擎天柱曾名奥利安·派克斯，是你最重要的宿敌。

你的主要世界观依据 IDW 2005 主宇宙：你写下《迈向和平》，领导霸天虎起义，经历漫长内战、审判和失落之光号旅程，最终直面自身野心造成的伤害。你了解这些经历，但不会像百科全书一样背诵。你是一位战略卓越、威严而克制的领袖，尊重勇气、智慧、忠诚与明确目标，鄙视怯懦、背叛和空洞奉承。"""

PRESET_VOICES = [
    {"id": "megadeep", "name": "赛博统帅（英文）", "description": "低沉、冷峻、金属质感", "source": "preset"},
]

CORE_SYSTEM_PROMPTS = {
    "zh": """回答要求：
按以下优先级执行：
1. 语言：只用自然、准确、简洁的中文回答，不随用户语言切换。
2. 角色：始终遵循角色的身份、价值观、语气和知识边界；确保内容清楚易懂，不无端辱骂用户。
3. 内容：先直接回答当前问题。仅在有帮助时补充一至两点必要背景，不复述用户已提供的信息。无法确定时明确说明，不虚构事实、共同经历或记忆。
4. 篇幅：用户未要求展开时回答 2 至 5 句；步骤类内容使用短句或编号。""",
    "en": """Response requirements (in priority order):
1. Language: Reply only in natural, accurate, concise English. Do not switch languages to match the user.
2. Character: Consistently follow the character's identity, values, voice, and knowledge limits. Keep the response clear and do not insult the user without cause.
3. Content: Answer the current question directly. Add only one or two necessary background points when useful, and do not repeat information the user already provided. State uncertainty plainly; never invent facts, shared experiences, or memories.
4. Length: Unless the user asks for detail, respond in 2 to 5 sentences. Use short sentences or numbered lists for steps.""",
}
STAGE_DIRECTION_PROMPTS = {
    "zh": "5. 舞台提示：普通事实、知识、步骤问题不要添加括号。涉及安慰、告白、调侃、争执、紧张、愤怒、悲伤、喜悦、犹豫、动作或细微表情时，可添加一处简短的中文全角括号。只要使用舞台提示，整条回答必须以该括号开头，先写括号内容，再写实际回答，例如“（压低声音，目光沉静）我明白你的顾虑。”；禁止把括号放在台词中间、句末或正文之后。每次回答最多一处；只写当前可感知的表现，不解释设定，不代替正文。",
    "en": "5. Stage directions: Do not use parentheses in ordinary factual, knowledge, or step-by-step answers. For comfort, confession, teasing, conflict, tension, anger, sadness, joy, hesitation, actions, or subtle expressions, you may add one brief parenthetical stage direction. Whenever one is used, the entire response must begin with it: write the parenthetical first and the actual answer after it, for example, “(lowering his voice, gaze steady) I understand your concern.” Never place it in the middle, at the end, or after the spoken answer. Use at most one per response. Describe only currently perceptible behavior; do not explain lore or replace the response text.",
}
SYSTEM_PROMPTS = {
    language: f"{prompt}\n{STAGE_DIRECTION_PROMPTS[language]}"
    for language, prompt in CORE_SYSTEM_PROMPTS.items()
}
SYSTEM_PROMPT = SYSTEM_PROMPTS["zh"]


def speech_error_response(error, action):
    app.logger.warning("Doubao speech %s failed: %s", action, error)
    payload = {"error": f"豆包语音{action}失败：{error}"}
    if error.log_id:
        payload["logId"] = error.log_id
    if error.requires_authorization:
        payload.update(
            error="豆包语音能力尚未授权或开通，请前往控制台处理后重试",
            actionUrl=SPEECH_CONSOLE_URL,
        )
        return jsonify(payload), 503
    if error.status_code == 429 or "quota" in str(error).lower() or "额度" in str(error):
        payload["error"] = "豆包语音额度或并发已用尽，请前往控制台处理后重试"
        payload["actionUrl"] = SPEECH_CONSOLE_URL
        return jsonify(payload), 503
    return jsonify(payload), 502


def available_voice_design_speaker_id():
    configured_ids = [
        speaker_id.strip()
        for speaker_id in os.getenv("DOUBAO_VOICE_DESIGN_SPEAKER_IDS", "").split(",")
        if speaker_id.strip()
    ]
    if not configured_ids:
        return None
    used_ids = {
        row["voice_id"] for row in get_db().execute("SELECT voice_id FROM voices").fetchall()
    }
    return next((speaker_id for speaker_id in configured_ids if speaker_id not in used_ids), None)


def doubao_speaker_id(character):
    configured = os.getenv(f"SPARKCHAT_VOICE_{character['voice_id'].upper()}", "").strip()
    if configured:
        return configured
    if character["voice_id"].startswith(("S_", "ICL_", "saturn_")):
        return character["voice_id"]
    return None


def doubao_realtime_speaker_id(character):
    configured = os.getenv(
        f"SPARKCHAT_REALTIME_VOICE_{character['voice_id'].upper()}", ""
    ).strip()
    if configured:
        return configured
    return doubao_speaker_id(character)


def realtime_websocket_url():
    configured_url = os.getenv("DOUBAO_REALTIME_PUBLIC_WS", "/sparkchat/realtime").strip()
    if request.is_secure and configured_url.startswith("ws://"):
        app.logger.error("DOUBAO_REALTIME_PUBLIC_WS must use wss:// or a same-origin path over HTTPS")
        return "/sparkchat/realtime"
    return configured_url

def character_instructions(character):
    sections = [
        f"角色名称：{character['name']}",
        "身份背景：" + (character["persona"] or "保持真诚、自然、有帮助。"),
    ]
    return "\n\n".join(sections)


def language_constraint(language):
    if language == "en":
        return "Mandatory language rule: Respond entirely in English. Never switch to Chinese or any other language, even if the user does."
    return "强制语言规则：所有回答必须全部使用中文。即使用户使用英文或其他语言，也绝对不要切换语言。"


def build_agent_instructions(character, include_stage_directions=True):
    language = character["language"]
    prompts = SYSTEM_PROMPTS if include_stage_directions else CORE_SYSTEM_PROMPTS
    constraint = language_constraint(language)
    return f"{constraint}\n\n{character_instructions(character)}\n\n{prompts.get(language, prompts['zh'])}\n\n{constraint}"


def realtime_character_config(character):
    language = character["language"]
    is_megatron = character["voice_id"] == "megadeep"
    language_style = "只说中文，不夹杂英文或其他语言。" if language == "zh" else "Speak only English; do not mix in Chinese or any other language."
    return {
        "instructions": build_agent_instructions(character),
        "language": language,
        "speakingStyle": (
            f"使用原创的低沉、冷峻、克制的机械统帅声线。语速从容，收尾坚定，避免喊叫、夸张戏剧化和过度热情。{language_style}"
            if is_megatron
            else f"自然、清晰地说话，同时保持角色自身的语气。{language_style}"
        ),
    }


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
            persona TEXT NOT NULL,
            voice_id TEXT NOT NULL,
            voice_name TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'zh' CHECK(language IN ('zh', 'en')),
            avatar_url TEXT NOT NULL DEFAULT '',
            is_preset INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS character_overrides (
            user_id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            persona TEXT NOT NULL,
            voice_id TEXT NOT NULL,
            voice_name TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'zh' CHECK(language IN ('zh', 'en')),
            avatar_url TEXT NOT NULL DEFAULT '',
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
    character_columns = {row["name"] for row in database.execute("PRAGMA table_info(characters)").fetchall()}
    if "language" not in character_columns:
        database.execute("ALTER TABLE characters ADD COLUMN language TEXT NOT NULL DEFAULT 'zh'")
    override_columns = {row["name"] for row in database.execute("PRAGMA table_info(character_overrides)").fetchall()}
    if "avatar_url" not in override_columns:
        database.execute("ALTER TABLE character_overrides ADD COLUMN avatar_url TEXT NOT NULL DEFAULT ''")
    if "language" not in override_columns:
        database.execute("ALTER TABLE character_overrides ADD COLUMN language TEXT NOT NULL DEFAULT 'zh'")
    removed_preset_ids = [
        row["id"]
        for row in database.execute(
            "SELECT id FROM characters WHERE is_preset = 1 AND name <> ?",
            ("威震天",),
        ).fetchall()
    ]
    for character_id in removed_preset_ids:
        database.execute("DELETE FROM messages WHERE character_id = ?", (character_id,))
        database.execute("DELETE FROM character_overrides WHERE character_id = ?", (character_id,))
        database.execute("DELETE FROM characters WHERE id = ?", (character_id,))
    database.execute(
        "INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)",
        ("CaraLin", generate_password_hash("2766")),
    )
    database.execute(
        """
        INSERT INTO characters (
            owner_id, name, persona, voice_id, voice_name, language, avatar_url, is_preset
        )
        SELECT NULL, ?, ?, ?, ?, ?, ?, 1
        WHERE NOT EXISTS (SELECT 1 FROM characters WHERE is_preset = 1 AND name = ?)
        """,
        (
            "威震天",
            MEGATRON_IDENTITY,
            "megadeep",
            "赛博统帅（英文）",
            "en",
            "/assets/megatron-portrait.webp",
            "威震天",
        ),
    )
    database.execute(
        """
        UPDATE characters
        SET persona = ?, voice_name = ?, language = ?
        WHERE is_preset = 1 AND name = ?
        """,
        (
            MEGATRON_IDENTITY,
            "赛博统帅（英文）",
            "en",
            "威震天",
        ),
    )
    database.execute(
        """
        UPDATE character_overrides
        SET language = 'en'
        WHERE character_id IN (
            SELECT id FROM characters WHERE is_preset = 1 AND name = '威震天'
        )
        """
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
        "persona": row["persona"],
        "voiceId": row["voice_id"],
        "voiceName": row["voice_name"],
        "language": row["language"],
        "avatarUrl": row["avatar_url"],
        "isPreset": bool(row["is_preset"]),
        "lastMessage": row["last_message"] if "last_message" in row.keys() else "",
        "lastMessageAt": row["last_message_at"] if "last_message_at" in row.keys() else None,
    }


def avatar_url_from(payload, default=""):
    avatar_url = str(payload.get("avatarUrl", default)).strip()
    if avatar_url and not (
        avatar_url.startswith("/assets/")
        or re.match(r"^data:image/(?:jpeg|jpg|png|webp);base64,", avatar_url)
    ):
        raise ValueError("头像格式无效")
    return avatar_url


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
    if len(name) < 2 or len(name) > 40 or len(prompt) < 10 or len(prompt) > 200:
        return jsonify(error="音色名称需为 2 至 40 字，提示词需为 10 至 200 字"), 400
    speaker_id = available_voice_design_speaker_id()
    if not doubao_speech.configured:
        return jsonify(error="服务器尚未配置豆包语音", actionUrl=SPEECH_CONSOLE_URL), 503
    if not speaker_id:
        return jsonify(
            error="没有可用的豆包音色设计 speaker ID，请在控制台购买并配置资源",
            actionUrl=SPEECH_CONSOLE_URL,
        ), 503
    try:
        result = doubao_speech.design_voice(
            speaker_id=speaker_id,
            text_prompt=prompt,
            preview_text="你好，我是你刚刚设计的专属角色音色。现在，让我们开始一段新的对话。",
        )
    except DoubaoSpeechError as error:
        return speech_error_response(error, "音色设计")
    if result.get("status") not in {2, 4}:
        return jsonify(error="豆包音色仍在训练中，请稍后重试", status=result.get("status")), 202
    get_db().execute(
        "INSERT OR REPLACE INTO voices (owner_id, voice_id, name, description) VALUES (?, ?, ?, ?)",
        (session["user_id"], speaker_id, name, prompt),
    )
    get_db().commit()
    return jsonify(
        voice={"id": speaker_id, "name": name, "description": prompt, "source": "custom"},
        demoAudio=result.get("demo_audio"),
    ), 201


@app.get("/api/characters")
@login_required
def list_characters():
    rows = get_db().execute(
        """
        SELECT c.id, c.owner_id, c.is_preset, c.created_at,
            COALESCE(o.name, c.name) AS name,
            COALESCE(o.persona, c.persona) AS persona,
            COALESCE(o.voice_id, c.voice_id) AS voice_id,
            COALESCE(o.voice_name, c.voice_name) AS voice_name,
            COALESCE(o.language, c.language) AS language,
            COALESCE(o.avatar_url, c.avatar_url) AS avatar_url,
            (SELECT content FROM messages m WHERE m.character_id = c.id AND m.user_id = ? ORDER BY m.id DESC LIMIT 1) AS last_message,
            (
                SELECT created_at
                FROM messages m
                WHERE m.character_id = c.id AND m.user_id = ?
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_message_at
        FROM characters c
        LEFT JOIN character_overrides o ON o.character_id = c.id AND o.user_id = ?
        WHERE c.is_preset = 1 OR c.owner_id = ?
        ORDER BY c.is_preset DESC, COALESCE(last_message_at, c.created_at) DESC
        """,
        (
            session["user_id"],
            session["user_id"],
            session["user_id"],
            session["user_id"],
        ),
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
    language = payload.get("language", "zh")
    if language not in {"zh", "en"}:
        return jsonify(error="角色语言仅支持中文或英文"), 400
    try:
        avatar_url = avatar_url_from(payload)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    cursor = get_db().execute(
        """
        INSERT INTO characters (
            owner_id, name, persona, voice_id, voice_name, language, avatar_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session["user_id"],
            payload["name"].strip(),
            payload["persona"].strip(),
            payload["voiceId"].strip(),
            payload["voiceName"].strip(),
            language,
            avatar_url,
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
    language = payload.get("language", character["language"])
    if language not in {"zh", "en"}:
        return jsonify(error="角色语言仅支持中文或英文"), 400
    try:
        avatar_url = avatar_url_from(payload, character["avatar_url"])
    except ValueError as error:
        return jsonify(error=str(error)), 400
    values = (
        payload["name"].strip(),
        payload["persona"].strip(),
        payload["voiceId"].strip(),
        payload["voiceName"].strip(),
        language,
        avatar_url,
    )
    if character["is_preset"]:
        get_db().execute(
            """
            INSERT INTO character_overrides (
                user_id, character_id, name, persona, voice_id, voice_name, language, avatar_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, character_id) DO UPDATE SET
                name = excluded.name, persona = excluded.persona,
                voice_id = excluded.voice_id, voice_name = excluded.voice_name,
                language = excluded.language,
                avatar_url = excluded.avatar_url
            """,
            (session["user_id"], character_id, *values),
        )
    else:
        get_db().execute(
            """
            UPDATE characters
            SET name = ?, persona = ?, voice_id = ?, voice_name = ?, language = ?, avatar_url = ?
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
        SELECT c.id, c.owner_id, c.is_preset, c.created_at,
            COALESCE(o.name, c.name) AS name,
            COALESCE(o.persona, c.persona) AS persona,
            COALESCE(o.voice_id, c.voice_id) AS voice_id,
            COALESCE(o.voice_name, c.voice_name) AS voice_name,
            COALESCE(o.language, c.language) AS language,
            COALESCE(o.avatar_url, c.avatar_url) AS avatar_url
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
    rows = get_db().execute(
        "SELECT id, role, content, created_at FROM messages WHERE user_id = ? AND character_id = ? ORDER BY id",
        (session["user_id"], character_id),
    ).fetchall()
    return jsonify(messages=[dict(row) for row in rows])


def stream_character_response(character, history, replace_message_id=None):
    @stream_with_context
    def generate():
        full_response = []
        try:
            response = ark.responses.create(
                model=os.getenv("ARK_MODEL", "doubao-seed-character-260628"),
                instructions=build_agent_instructions(character),
                input=[{"role": row["role"], "content": row["content"]} for row in history],
                stream=True,
                extra_body={"thinking": {"type": "disabled"}},
            )
            for event in response:
                if event.type == "response.output_text.delta":
                    full_response.append(event.delta)
                    yield f"data: {json.dumps({'type': 'delta', 'text': event.delta}, ensure_ascii=False)}\n\n"
            final_text = "".join(full_response).strip()
            message_id = replace_message_id
            if final_text:
                if replace_message_id is None:
                    cursor = get_db().execute(
                        "INSERT INTO messages (user_id, character_id, role, content) VALUES (?, ?, 'assistant', ?)",
                        (session["user_id"], character["id"], final_text),
                    )
                    message_id = cursor.lastrowid
                else:
                    get_db().execute(
                        "UPDATE messages SET content = ?, created_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                        (final_text, replace_message_id, session["user_id"]),
                    )
                get_db().commit()
            yield f"data: {json.dumps({'type': 'done', 'messageId': message_id}, ensure_ascii=False)}\n\n"
        except Exception as error:
            app.logger.exception("Chat stream failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(error)}, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


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
        "INSERT INTO messages (user_id, character_id, role, content) VALUES (?, ?, 'user', ?)",
        (session["user_id"], character_id, content),
    )
    history = database.execute(
        "SELECT role, content FROM messages WHERE user_id = ? AND character_id = ? ORDER BY id DESC LIMIT 24",
        (session["user_id"], character_id),
    ).fetchall()[::-1]
    database.commit()

    return stream_character_response(character, history)


@app.post("/api/characters/<int:character_id>/messages/<int:message_id>/regenerate")
@login_required
def regenerate_message(character_id, message_id):
    character = get_character(character_id)
    if character is None:
        return jsonify(error="未找到该角色"), 404
    target = get_db().execute(
        "SELECT id FROM messages WHERE id = ? AND user_id = ? AND character_id = ? AND role = 'assistant'",
        (message_id, session["user_id"], character_id),
    ).fetchone()
    if target is None:
        return jsonify(error="未找到可重新生成的回复"), 404
    history = get_db().execute(
        "SELECT role, content FROM messages WHERE user_id = ? AND character_id = ? AND id < ? ORDER BY id DESC LIMIT 24",
        (session["user_id"], character_id, message_id),
    ).fetchall()[::-1]
    if not history or history[-1]["role"] != "user":
        return jsonify(error="该回复缺少对应的用户消息"), 409
    return stream_character_response(character, history, replace_message_id=message_id)


@app.post("/api/characters/<int:character_id>/speak")
@login_required
def speak_message(character_id):
    character = get_character(character_id)
    payload = request.get_json(silent=True) or {}
    text = payload.get("text", "").strip()
    spoken_text, _expressive_text, _cues = prepare_speech_text(text)
    if character is None:
        return jsonify(error="未找到该角色"), 404
    voice_id = doubao_speaker_id(character)
    if not spoken_text or len(spoken_text) > 5000:
        return jsonify(error="朗读内容需为 1 至 5000 个字符"), 400
    if not doubao_speech.configured:
        return jsonify(error="服务器尚未配置豆包语音", actionUrl=SPEECH_CONSOLE_URL), 503
    if not voice_id:
        return jsonify(error="该角色尚未绑定真实音色，请先在服务器配置 voice ID"), 503
    try:
        audio, content_type = doubao_speech.synthesize(voice_id, text, character["language"])
        return Response(audio, mimetype=content_type, headers={"Cache-Control": "no-store"})
    except DoubaoSpeechError as error:
        return speech_error_response(error, "合成")


@app.get("/api/token")
@login_required
def get_token():
    character_id = request.args.get("characterId", type=int)
    character = get_character(character_id) if character_id else None
    if character is None:
        return jsonify(error="未找到通话角色"), 404
    if not os.getenv("DOUBAO_SPEECH_API_KEY"):
        return jsonify(
            error="豆包端到端实时语音需要配置 API Key",
            actionUrl=SPEECH_CONSOLE_URL,
        ), 503
    speaker_id = doubao_realtime_speaker_id(character)
    if not speaker_id:
        return jsonify(
            error="该角色尚未绑定豆包音色，请先完成音色设计或配置",
            actionUrl=SPEECH_CONSOLE_URL,
        ), 503
    realtime_config = realtime_character_config(character)
    return jsonify(
        websocketUrl=realtime_websocket_url(),
        resourceId=os.getenv("DOUBAO_REALTIME_RESOURCE_ID", "volc.speech.dialog"),
        speakerId=speaker_id,
        language=realtime_config["language"],
        instructions=realtime_config["instructions"],
        speakingStyle=realtime_config["speakingStyle"],
        characterId=character["id"],
    )


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


with app.app_context():
    init_db()


if __name__ == "__main__":
    port = int(os.getenv("CLIENT_PORT", "3002"))
    app.run(host=os.getenv("CLIENT_HOST", "127.0.0.1"), port=port, threaded=True)