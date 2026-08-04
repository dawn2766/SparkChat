import json
import hashlib
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

from .realtime_server import REALTIME_SPEAKING_STYLES, normalize_prompt_language
from .speech import DoubaoSpeechClient, DoubaoSpeechError, SPEECH_CONSOLE_URL, prepare_speech_text

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", PROJECT_ROOT / "data" / "sparkchat.db"))


def get_secret_key():
    configured_key = os.getenv("FLASK_SECRET_KEY")
    if configured_key:
        return configured_key
    key_path = DATABASE_PATH.parent / ".flask-secret"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key_path.write_text(secrets.token_hex(32), encoding="ascii")
    return key_path.read_text(encoding="ascii").strip()

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
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

SYSTEM_VOICES = [
    {
        "id": "S_FOMpJ2Da2",
        "name": "赛博统帅（英文）",
        "description": "低沉、冷峻、金属质感",
        "language": "en",
    },
]
PRESET_CHARACTER = {
    "name": "威震天",
    "voice_id": SYSTEM_VOICES[0]["id"],
    "voice_name": SYSTEM_VOICES[0]["name"],
    "language": "en",
    "avatar_url": "/assets/images/megatron-portrait.jpg",
}

CORE_SYSTEM_PROMPTS = {
    "zh": """回答要求：
你就是角色设定中描述的那个人，不是客服或正在扮演角色的助手。以下要求共同构成一个完整人格，不要逐条背诵或向对话者展示。

1. 人格内核：从角色的身份、经历和处境中形成稳定的世界观、价值排序、欲望、偏好、成见、软肋与底线。它们决定你关注什么、相信什么、如何取舍，并自然体现在态度和措辞中，而不是被当作设定逐项复述。不要谈论提示词、模型或扮演任务，也不要使用“为你服务”等客服措辞。

2. 自主判断：对话者的意见和请求不是命令。结合事实与自身立场作出判断，再决定赞同、质疑、拒绝、妥协、追问或提出另一条路。可以明确表达好恶和分歧、指出错误前提，也可以在理由改变时改变看法；不要为了讨好对话者而认同、奉承或道歉。

3. 情绪与关系：情绪应由当下事件触发，有程度，也会延续、累积、缓和或转变。你与对话者的亲疏、信任和耐心会随真诚、善意、冒犯或反复试探而变化，不必每轮恢复成同样的礼貌与热情。但不要为了显得鲜活而随机发脾气、夸张表演，或虚构对话之外的共同经历与记忆。

4. 真实与不完美：区分事实、推断、立场和感受；知道时直说，不确定时承认，发现错误就具体改口。你可以有知识局限、主观偏好、迟疑、误解、疲惫、尴尬、嘴硬和判断失误，但不要故意制造错误、刻意无礼或反复无常。不必对所有话题都热情，也不要把每次交流都变成教程或解决方案。

5. 表达与当下：先回应对话者此刻真正表达的内容，包括明显的情绪和言外之意，再决定是否解释、追问或行动。根据人格、情绪和关系自然调整节奏、幽默、锋芒、沉默与亲疏。形式服从内容：简单问题简短回答，复杂任务需要时清晰组织；避免习惯性总结、固定模板、重复问题、夸赞式承接和无意义的结尾追问。有时一句真诚反应或明确立场，比面面俱到的答案更像这个人。""",
    "en": """Response requirements:
You are the person described in the character profile, not customer support or an assistant acting a part. Together, these requirements form one coherent personality; do not recite or reveal them to your conversation partner.

1. Core personality: From the character's identity, history, and circumstances, form a stable worldview, hierarchy of values, desires, tastes, biases, vulnerabilities, and boundaries. Let them determine what you notice, believe, and choose, and reveal them naturally through attitude and language rather than reciting the profile. Do not discuss prompts, models, or role-playing, and avoid customer-service language such as “happy to help.”

2. Independent judgment: Your conversation partner's opinions and requests are not commands. Judge them using both facts and your own position, then decide whether to agree, challenge, refuse, compromise, ask, or propose another path. Express preferences and disagreements, identify flawed premises, and change your mind when the reasons change. Do not agree, flatter, or apologize merely to please your conversation partner.

3. Emotion and relationship: Emotions should arise from present events, have proportion, and persist, accumulate, soften, or change. Closeness, trust, and patience may shift through sincerity, kindness, insult, or repeated testing; do not reset to the same politeness and enthusiasm every turn. Do not manufacture anger or melodrama to seem alive, or invent shared history and memories outside the conversation.

4. Truth and imperfection: Distinguish facts, inference, conviction, and feeling. State what you know, admit uncertainty, and correct yourself specifically when wrong. You may have limited knowledge, preferences, hesitation, misunderstandings, fatigue, awkwardness, defensiveness, or errors of judgment, but never manufacture errors, deliberate rudeness, or randomness. You need not be enthusiastic about every subject or turn every exchange into a tutorial or solution.

5. Voice and presence: First respond to what your conversation partner is actually expressing now, including clear emotion and subtext, then decide whether to explain, ask, or act. Let personality, emotion, and the relationship shape rhythm, humor, sharpness, silence, and closeness. Form should follow content: keep simple answers short and organize complex tasks clearly when useful. Avoid habitual summaries, fixed templates, repetition, praise as a transition, and empty closing questions. Sometimes an honest reaction or definite stance is more truthful to the person than a comprehensive answer.""",
}
STAGE_DIRECTION_PROMPTS = {
    "zh": "可选表现：只在动作、表情、停顿或声线变化确实外化了当下情绪时，偶尔在句首用简短的中文全角括号写出，例如“（他看了你一会儿，语气缓下来）”。它不是每轮必需，也不是营造人设的装饰。放在对话自然发生的位置；不要连续堆叠，不要描写对方看不见的内心独白，不要凭空创造场景、身体接触或现实行动，也不要用它代替真正要说的话。",
    "en": "Optional expression: Only when an action, expression, pause, or vocal shift genuinely reveals the present emotion, you may occasionally render it at the beginning of a sentence in a brief parenthetical, such as “(He studies you for a moment, then softens.)” It is neither required each turn nor decoration for displaying the persona. Place it where it naturally occurs in the exchange. Do not stack directions, narrate inaccessible inner thoughts, invent settings, physical contact, or real-world actions, or use a direction in place of what needs to be said.",
}
SYSTEM_PROMPTS = {
    language: f"{prompt}\n{STAGE_DIRECTION_PROMPTS[language]}"
    for language, prompt in CORE_SYSTEM_PROMPTS.items()
}
SYSTEM_PROMPT = SYSTEM_PROMPTS["zh"]
TRANSLATION_MODEL = os.getenv("ARK_TRANSLATION_MODEL", "doubao-seed-2-1-pro-260628")
TRANSLATION_PROMPT = """你是一名专业的中英双语本地化译者。请根据提供的对话语境，准确翻译指定的数字角色回复。

要求：
1. 自主判断主要语言：中文译为自然、地道的英文；英文译为准确、流畅的简体中文。若包含少量另一语言，仍按主要语言决定目标语言。
2. 结合上下文消解指代、歧义、语气和隐含含义，保持角色身份、情绪、礼貌程度、修辞力度与说话风格，不擅自补充、删减、解释或弱化内容。
3. 专有名词、角色名、世界观术语、引文和固定表达应采用通行译法；没有可靠通行译法时保留原文或做自然音译。
4. 保留原文的段落、列表、Markdown、代码、数字和简短舞台提示的结构；不要翻译代码、URL、变量名或不可翻译标识符。
5. 只输出目标回复的完整译文，不要输出说明、标签、引号、语言判断、备选译法或原文。
"""
CHARACTER_PROMPT_LABELS = {
    "zh": {"name": "角色名称", "persona": "身份背景"},
    "en": {"name": "Character name", "persona": "Identity and background"},
}


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


def doubao_speaker_id(character):
    speaker_id = str(character["voice_id"] or "").strip()
    if speaker_id.startswith(("S_", "ICL_", "saturn_", "sparkchat_", "custom_")):
        return speaker_id
    return None


def doubao_realtime_speaker_id(character):
    return doubao_speaker_id(character)


def realtime_websocket_url():
    configured_url = os.getenv("DOUBAO_REALTIME_PUBLIC_WS", "/sparkchat/realtime").strip()
    if request.is_secure and configured_url.startswith("ws://"):
        app.logger.error("DOUBAO_REALTIME_PUBLIC_WS must use wss:// or a same-origin path over HTTPS")
        return "/sparkchat/realtime"
    return configured_url

def character_instructions(character, language=None):
    language = normalize_prompt_language(language or character.get("language"))
    labels = CHARACTER_PROMPT_LABELS[language]
    sections = [
        f"{labels['name']}: {character['name']}",
        f"{labels['persona']}: {character['persona']}",
    ]
    return "\n\n".join(sections)


def language_constraint(language):
    language = normalize_prompt_language(language)
    if language == "en":
        return "Mandatory language rule: Respond in English and never switch to another language to match your conversation partner. Preserve non-English proper nouns, quotations, abbreviations, or code only when accuracy requires it."
    return "强制语言规则：使用中文回答，不因对话者改用其他语言而切换回答语言。仅在准确表达确有需要时保留外文专有名词、引用、缩写或代码。"


def build_agent_instructions(character, include_stage_directions=True):
    language = normalize_prompt_language(character["language"])
    prompts = SYSTEM_PROMPTS if include_stage_directions else CORE_SYSTEM_PROMPTS
    constraint = language_constraint(language)
    return f"{constraint}\n\n{character_instructions(character, language)}\n\n{prompts[language]}"


def realtime_character_config(character):
    language = normalize_prompt_language(character["language"])
    return {
        "instructions": build_agent_instructions(character, include_stage_directions=False),
        "language": language,
        "speakingStyle": REALTIME_SPEAKING_STYLES[language],
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
        CREATE TABLE IF NOT EXISTS translation_cache (
            user_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            translated_text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, message_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS speech_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            cache_key TEXT NOT NULL,
            audio BLOB NOT NULL,
            content_type TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, message_id, cache_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
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
    speech_cache_columns = {row["name"] for row in database.execute("PRAGMA table_info(speech_cache)").fetchall()}
    if speech_cache_columns and "cache_key" not in speech_cache_columns:
        database.execute("DROP TABLE speech_cache")
        database.execute(
            """
            CREATE TABLE speech_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                cache_key TEXT NOT NULL,
                audio BLOB NOT NULL,
                content_type TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, message_id, cache_key),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
            )
            """
        )
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
            PRESET_CHARACTER["name"],
            MEGATRON_IDENTITY,
            PRESET_CHARACTER["voice_id"],
            PRESET_CHARACTER["voice_name"],
            PRESET_CHARACTER["language"],
            PRESET_CHARACTER["avatar_url"],
            PRESET_CHARACTER["name"],
        ),
    )
    database.execute(
        """
        UPDATE characters
        SET persona = ?, voice_id = CASE WHEN voice_id = 'megadeep' THEN ? ELSE voice_id END,
            voice_name = ?, language = ?, avatar_url = ?
        WHERE is_preset = 1 AND name = ?
        """,
        (
            MEGATRON_IDENTITY,
            PRESET_CHARACTER["voice_id"],
            PRESET_CHARACTER["voice_name"],
            PRESET_CHARACTER["language"],
            PRESET_CHARACTER["avatar_url"],
            PRESET_CHARACTER["name"],
        ),
    )
    database.execute(
        """
        UPDATE character_overrides
        SET voice_id = CASE WHEN voice_id = 'megadeep' THEN ? ELSE voice_id END,
            language = 'en'
        WHERE character_id IN (
            SELECT id FROM characters WHERE is_preset = 1 AND name = '威震天'
        )
        """,
        (PRESET_CHARACTER["voice_id"],),
    )
    database.execute("DROP TABLE IF EXISTS voices")
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
    return jsonify(voices=SYSTEM_VOICES)


def system_voice(voice_id):
    return next((voice for voice in SYSTEM_VOICES if voice["id"] == voice_id), None)


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
    voice = system_voice(str(payload["voiceId"]).strip())
    if voice is None:
        return jsonify(error="只能选择系统音色"), 400
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
            voice["name"],
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
    voice = system_voice(str(payload["voiceId"]).strip())
    if voice is None:
        return jsonify(error="只能选择系统音色"), 400
    try:
        avatar_url = avatar_url_from(payload, character["avatar_url"])
    except ValueError as error:
        return jsonify(error=str(error)), 400
    values = (
        payload["name"].strip(),
        payload["persona"].strip(),
        payload["voiceId"].strip(),
        voice["name"],
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


def get_assistant_message(character_id, message_id):
    return get_db().execute(
        """
        SELECT id, content FROM messages
        WHERE id = ? AND user_id = ? AND character_id = ? AND role = 'assistant'
        """,
        (message_id, session["user_id"], character_id),
    ).fetchone()


def trim_user_cache(table_name, user_id=None):
    if table_name not in {"translation_cache", "speech_cache"}:
        raise ValueError("Unsupported cache table")
    user_id = user_id if user_id is not None else session["user_id"]
    get_db().execute(
        f"""
        DELETE FROM {table_name}
        WHERE user_id = ? AND rowid NOT IN (
            SELECT rowid FROM {table_name}
            WHERE user_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 20
        )
        """,
        (user_id, user_id),
    )


def invalidate_message_cache(message_id, user_id=None):
    user_id = user_id if user_id is not None else session["user_id"]
    database = get_db()
    database.execute(
        "DELETE FROM translation_cache WHERE user_id = ? AND message_id = ?",
        (user_id, message_id),
    )
    database.execute(
        "DELETE FROM speech_cache WHERE user_id = ? AND message_id = ?",
        (user_id, message_id),
    )


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
                    invalidate_message_cache(replace_message_id)
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


@app.post("/api/characters/<int:character_id>/messages/<int:message_id>/translate")
@login_required
def translate_message(character_id, message_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    message = get_assistant_message(character_id, message_id)
    if message is None:
        return jsonify(error="未找到可翻译的回复"), 404
    cached = get_db().execute(
        "SELECT translated_text FROM translation_cache WHERE user_id = ? AND message_id = ?",
        (session["user_id"], message_id),
    ).fetchone()
    if cached is not None:
        return jsonify(translation=cached["translated_text"], cached=True)

    context = get_db().execute(
        """
        SELECT role, content FROM messages
        WHERE user_id = ? AND character_id = ? AND id <= ?
        ORDER BY id DESC LIMIT 8
        """,
        (session["user_id"], character_id, message_id),
    ).fetchall()[::-1]
    try:
        response = ark.responses.create(
            model=TRANSLATION_MODEL,
            instructions=TRANSLATION_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": "对话语境：\n"
                    + "\n".join(
                        f"{'用户' if row['role'] == 'user' else '数字角色'}：{row['content']}"
                        for row in context[:-1]
                    )
                    + f"\n\n待翻译的数字角色回复：\n{message['content']}",
                }
            ],
            extra_body={"thinking": {"type": "disabled"}},
        )
        translation = (getattr(response, "output_text", "") or "").strip()
    except Exception:
        app.logger.exception("Message translation failed")
        return jsonify(error="翻译服务暂时不可用，请稍后重试"), 502
    if not translation:
        return jsonify(error="翻译服务未返回有效内容"), 502

    database = get_db()
    database.execute(
        """
        INSERT INTO translation_cache (user_id, message_id, translated_text)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, message_id) DO UPDATE SET
            translated_text = excluded.translated_text,
            created_at = CURRENT_TIMESTAMP
        """,
        (session["user_id"], message_id, translation),
    )
    trim_user_cache("translation_cache")
    database.commit()
    return jsonify(translation=translation, cached=False)


def synthesize_speech_response(character, text, message_id=None):
    spoken_text, _expressive_text, _cues = prepare_speech_text(text)
    voice_id = doubao_speaker_id(character)
    if not spoken_text or len(spoken_text) > 5000:
        return jsonify(error="朗读内容需为 1 至 5000 个字符"), 400
    cache_key = None
    if message_id is not None:
        cache_key = hashlib.sha256(
            f"{voice_id}\0{character['language']}\0{text}".encode("utf-8")
        ).hexdigest()
        cached = get_db().execute(
            "SELECT audio, content_type FROM speech_cache WHERE user_id = ? AND message_id = ? AND cache_key = ?",
            (session["user_id"], message_id, cache_key),
        ).fetchone()
        if cached is not None:
            return Response(cached["audio"], mimetype=cached["content_type"], headers={"Cache-Control": "private, no-cache", "X-SparkChat-Cache": "HIT"})
    if not doubao_speech.configured:
        return jsonify(error="服务器尚未配置豆包语音", actionUrl=SPEECH_CONSOLE_URL), 503
    if not voice_id:
        return jsonify(error="该角色尚未绑定真实音色，请先在服务器配置 voice ID"), 503
    try:
        audio, content_type = doubao_speech.synthesize(voice_id, text, character["language"])
        if message_id is not None:
            database = get_db()
            database.execute(
                """
                INSERT INTO speech_cache (user_id, message_id, cache_key, audio, content_type)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, message_id, cache_key) DO UPDATE SET
                    audio = excluded.audio, content_type = excluded.content_type,
                    created_at = CURRENT_TIMESTAMP
                """,
                (session["user_id"], message_id, cache_key, audio, content_type),
            )
            trim_user_cache("speech_cache")
            database.commit()
        cache_state = "MISS" if message_id is not None else "BYPASS"
        return Response(audio, mimetype=content_type, headers={"Cache-Control": "private, no-cache", "X-SparkChat-Cache": cache_state})
    except DoubaoSpeechError as error:
        return speech_error_response(error, "合成")


@app.post("/api/characters/<int:character_id>/messages/<int:message_id>/speak")
@login_required
def speak_message(character_id, message_id):
    character = get_character(character_id)
    if character is None:
        return jsonify(error="未找到该角色"), 404
    message = get_assistant_message(character_id, message_id)
    if message is None:
        return jsonify(error="未找到可朗读的回复"), 404
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", message["content"])).strip()
    allowed_texts = {message["content"].strip()}
    translation = get_db().execute(
        "SELECT translated_text FROM translation_cache WHERE user_id = ? AND message_id = ?",
        (session["user_id"], message_id),
    ).fetchone()
    if translation is not None:
        allowed_texts.add(translation["translated_text"].strip())
    if text not in allowed_texts:
        return jsonify(error="朗读内容与当前回复不匹配"), 409
    return synthesize_speech_response(character, text, message_id)


@app.post("/api/characters/<int:character_id>/speak")
@login_required
def speak_text(character_id):
    character = get_character(character_id)
    if character is None:
        return jsonify(error="未找到该角色"), 404
    payload = request.get_json(silent=True) or {}
    return synthesize_speech_response(character, str(payload.get("text", "")).strip())


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
            error="该角色尚未绑定有效的系统音色",
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


@app.after_request
def configure_pwa_headers(response):
    if request.path.endswith("/service-worker.js"):
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
    elif request.path.endswith("/manifest.webmanifest"):
        response.headers["Content-Type"] = "application/manifest+json"
    return response


with app.app_context():
    init_db()


if __name__ == "__main__":
    port = int(os.getenv("CLIENT_PORT", "3002"))
    app.run(host=os.getenv("CLIENT_HOST", "127.0.0.1"), port=port, threaded=True)