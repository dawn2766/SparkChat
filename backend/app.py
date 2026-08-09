import json
import hashlib
import os
import re
import secrets
import sqlite3
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, request, send_from_directory, session, stream_with_context
from openai import OpenAI
from werkzeug.security import check_password_hash, generate_password_hash

from .avatar_storage import AVATAR_DATA_URL, store_avatar_snapshot
from .conversation_memory import (
    VOICE_MEMORY_UPDATE_INTERVAL_TOKENS,
    VOICE_RECENT_CONTEXT_MAX_TOKENS,
    allocate_input_tokens,
    fallback_token_count,
    message_token_count,
    select_memory_batch,
    select_recent_messages,
    should_update_memory,
    stable_messages_for_memory,
)
from .model_config import CHAT_MODELS, DEFAULT_CHAT_MODEL, MEMORY_MODEL, TRANSLATION_MODEL
from .realtime_server import normalize_prompt_language
from .speech import DoubaoSpeechClient, DoubaoSpeechError, SPEECH_CONSOLE_URL, prepare_speech_text

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", PROJECT_ROOT / "data" / "sparkchat.db"))
AVATAR_DIR = Path(os.getenv("AVATAR_DIR", DATABASE_PATH.parent / "avatars")).resolve()


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
memory_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sparkchat-memory")
persona_translation_executor = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="sparkchat-persona-translation"
)
memory_jobs = set()
memory_jobs_lock = threading.Lock()
voice_memory_jobs = set()
voice_memory_reruns = set()
voice_memory_jobs_lock = threading.Lock()
persona_translation_jobs = set()
persona_translation_jobs_lock = threading.Lock()

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
    "en": "Optional expression: Only when an action, expression, pause, or vocal shift genuinely reveals the present emotion, you may occasionally render it at the beginning of a sentence in a brief English half-width parenthetical, such as \"(He studies you for a moment, then softens.)\" It is neither required each turn nor decoration for displaying the persona. Place it where it naturally occurs in the exchange. Do not stack directions, narrate inaccessible inner thoughts, invent settings, physical contact, or real-world actions, or use a direction in place of what needs to be said.",
}
SYSTEM_PROMPTS = {
    language: f"{prompt}\n{STAGE_DIRECTION_PROMPTS[language]}"
    for language, prompt in CORE_SYSTEM_PROMPTS.items()
}
SYSTEM_PROMPT = SYSTEM_PROMPTS["zh"]
if DEFAULT_CHAT_MODEL not in CHAT_MODELS:
    raise RuntimeError("ARK_DEFAULT_CHAT_MODEL must be one of the supported chat models")
MEMORY_PROMPTS = {
    "zh": """你负责维护一段数字角色对当前对话的长期记忆。请将旧记忆与新增对话合并为紧凑、准确、可继续更新的记忆。
保留用户与角色的重要事实、偏好、承诺、关系变化、情绪延续、未完成事项，以及后续理解对话所需的事件顺序。
不要虚构，不要把临时寒暄写成永久事实，不要评价提示词或总结过程。只输出更新后的中文记忆正文。""",
    "en": """Maintain the digital character's long-term memory of the conversation in fluent, natural English. Merge the previous memory and new dialogue into a compact, accurate memory that can be updated later.
Retain important facts, preferences, promises, relationship changes, emotional continuity, unfinished matters, and the event order needed to understand later dialogue. If the source contains Chinese or other non-English text, translate its meaning naturally rather than copying it into the memory. Use established standard English forms for people's names, place names, organizations, titles, fictional terms, historical references, slogans, and signature lines when available; otherwise use a clear, consistent romanization or translation.
Do not invent details, add translator notes, turn temporary small talk into permanent facts, discuss prompts, or describe the summarization process. Output only the updated memory in English.""",
}
MEMORY_PROMPT = MEMORY_PROMPTS["zh"]
MEMORY_CONTEXT_PROMPTS = {
    "zh": "以下是对话早期内容的记忆摘要。请将其作为背景，并结合后续原始消息，保持对事实、关系与未完成事项的连续理解：",
    "en": "The following is a memory summary of the earlier conversation. Use it as background together with the subsequent original messages, preserving continuity of facts, relationships, and unfinished matters:",
}
TRANSLATION_PROMPTS = {
    "zh": """根据对话语境，将指定的中文数字角色回复翻译成自然英文。
保留原意、角色语气和原文结构；不要翻译代码、URL、变量名或不可翻译的专有标识。
只输出目标回复的完整译文，也就是完整英文译文，不要附加说明或原文。""",
    "en": """Using the conversation context, translate the specified English digital-character reply into fluent Simplified Chinese.
Preserve the meaning, character voice, and original structure. Do not translate code, URLs, variable names, or non-translatable identifiers.
Output only the complete Chinese translation, without commentary or the original text.""",
}
TRANSLATION_PROMPT = TRANSLATION_PROMPTS["zh"]
PERSONA_TRANSLATION_PROMPT = """Translate the character name and profile into fluent, natural English.

Prioritize meaning that fits the context over word-for-word translation. Pay special attention to Chinese proper nouns, including people's names, place names, organizations, titles, fictional terms, historical references, and other terms with established standard English translations. Use the standard English form when one exists; otherwise choose a clear, consistent romanization or translation. Translate distinctive slogans, catchphrases, idioms, and signature lines accurately while keeping their original force and style. The English should read like an experienced human localization, not a mechanical translation.

Keep the character's facts, tone, personality, and important nuances. Do not add explanations, translator notes, alternatives, or information that is not present in the input. Preserve paragraph breaks when they help readability.

Output rules:
1. Output exactly one valid JSON object.
2. The object must contain exactly these two keys: \"name\" and \"persona\".
3. Both values must be non-empty JSON strings.
4. Output no Markdown fences, comments, extra keys, or text before or after the JSON.

Output example:
{"name":"Zhuge Liang","persona":"The strategist of Shu Han, known for the maxim \"To devote oneself utterly until one's final breath.\" He speaks with calm precision and rarely wastes a word."}"""
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

def character_value(character, key, default=""):
    if hasattr(character, "keys") and key in character.keys():
        return character[key]
    if isinstance(character, dict):
        return character.get(key, default)
    return default


def is_english_text(text):
    letters = [character for character in str(text or "") if character.isalpha()]
    return bool(letters) and all(
        "LATIN" in unicodedata.name(character, "") for character in letters
    )


def character_instructions(character, language=None):
    language = normalize_prompt_language(language or character_value(character, "language"))
    labels = CHARACTER_PROMPT_LABELS[language]
    name = character_value(character, "name")
    persona = character_value(character, "persona")
    if language == "en":
        translated_name = character_value(character, "name_en")
        translated_persona = character_value(character, "persona_en")
        name = translated_name or name
        persona = translated_persona or persona
    sections = [
        f"{labels['name']}: {name}",
        f"{labels['persona']}: {persona}",
    ]
    return "\n\n".join(sections)


def language_constraint(language):
    language = normalize_prompt_language(language)
    if language == "en":
        return "Speak English only. Every reply must be entirely in English, regardless of the user's language or any language in the character profile. Never switch to Chinese or mirror the user's language. Do not translate before answering. Keep non-English names, code, URLs, or very short quotations only when strictly necessary for accuracy."
    return "只用中文回答。无论对话者说什么语言、角色设定中出现什么语言，所有回复都必须使用简体中文。绝不因为对话者使用英文而改用英文，也不要先翻译再回答。只有专有名词、代码、URL 或准确性确实需要时，才保留极短的外文片段。"


def build_agent_instructions(character, include_stage_directions=True):
    language = normalize_prompt_language(character["language"])
    prompts = SYSTEM_PROMPTS if include_stage_directions else CORE_SYSTEM_PROMPTS
    constraint = language_constraint(language)
    return f"{constraint}\n\n{character_instructions(character, language)}\n\n{prompts[language]}"


def realtime_character_config(character):
    language = normalize_prompt_language(character["language"])
    return {
        "instructions": build_agent_instructions(character),
        "language": language,
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
            is_admin INTEGER NOT NULL DEFAULT 0,
            chat_model TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS voices (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            name TEXT NOT NULL,
            persona TEXT NOT NULL,
            name_en TEXT,
            persona_en TEXT,
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
            name_en TEXT,
            persona_en TEXT,
            voice_id TEXT NOT NULL,
            voice_name TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'zh' CHECK(language IN ('zh', 'en')),
            avatar_url TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (user_id, character_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT '新对话',
            title_custom INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            conversation_id INTEGER,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            token_count INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS conversation_memories (
            conversation_id INTEGER PRIMARY KEY,
            summary TEXT NOT NULL DEFAULT '',
            summary_zh TEXT,
            summary_en TEXT,
            covered_through_message_id INTEGER NOT NULL DEFAULT 0,
            covered_through_message_id_zh INTEGER NOT NULL DEFAULT 0,
            covered_through_message_id_en INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS voice_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT '新通话',
            title_custom INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS voice_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            turn_id TEXT,
            reply_id TEXT,
            token_count INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES voice_conversations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS voice_conversation_memories (
            conversation_id INTEGER PRIMARY KEY,
            summary TEXT NOT NULL DEFAULT '',
            summary_zh TEXT,
            summary_en TEXT,
            covered_through_message_id INTEGER NOT NULL DEFAULT 0,
            covered_through_message_id_zh INTEGER NOT NULL DEFAULT 0,
            covered_through_message_id_en INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES voice_conversations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS voice_translation_cache (
            user_id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            translated_text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, message_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
            FOREIGN KEY (message_id) REFERENCES voice_messages(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_conversations_owner_character
            ON conversations(user_id, character_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_voice_conversations_owner_character
            ON voice_conversations(user_id, character_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_voice_messages_conversation
            ON voice_messages(conversation_id, id);
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
    user_columns = {row["name"] for row in database.execute("PRAGMA table_info(users)").fetchall()}
    if "is_admin" not in user_columns:
        database.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    if "chat_model" not in user_columns:
        database.execute("ALTER TABLE users ADD COLUMN chat_model TEXT")
    database.execute(
        "UPDATE users SET chat_model = ? WHERE chat_model IS NULL OR chat_model NOT IN (?, ?)",
        (DEFAULT_CHAT_MODEL, *CHAT_MODELS),
    )
    voice_columns = {row["name"] for row in database.execute("PRAGMA table_info(voices)").fetchall()}
    if "language" in voice_columns:
        database.executescript(
            """
            CREATE TABLE voices_without_language (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO voices_without_language (id, name, description, created_at)
            SELECT id, name, description, created_at FROM voices;
            DROP TABLE voices;
            ALTER TABLE voices_without_language RENAME TO voices;
            """
        )
    character_columns = {row["name"] for row in database.execute("PRAGMA table_info(characters)").fetchall()}
    if "language" not in character_columns:
        database.execute("ALTER TABLE characters ADD COLUMN language TEXT NOT NULL DEFAULT 'zh'")
    if "name_en" not in character_columns:
        database.execute("ALTER TABLE characters ADD COLUMN name_en TEXT")
    if "persona_en" not in character_columns:
        database.execute("ALTER TABLE characters ADD COLUMN persona_en TEXT")
    override_columns = {row["name"] for row in database.execute("PRAGMA table_info(character_overrides)").fetchall()}
    if "avatar_url" not in override_columns:
        database.execute("ALTER TABLE character_overrides ADD COLUMN avatar_url TEXT NOT NULL DEFAULT ''")
    if "language" not in override_columns:
        database.execute("ALTER TABLE character_overrides ADD COLUMN language TEXT NOT NULL DEFAULT 'zh'")
    if "name_en" not in override_columns:
        database.execute("ALTER TABLE character_overrides ADD COLUMN name_en TEXT")
    if "persona_en" not in override_columns:
        database.execute("ALTER TABLE character_overrides ADD COLUMN persona_en TEXT")
    for table_name in ("conversation_memories", "voice_conversation_memories"):
        columns = {row["name"] for row in database.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if "summary_zh" not in columns:
            database.execute(f"ALTER TABLE {table_name} ADD COLUMN summary_zh TEXT")
        if "summary_en" not in columns:
            database.execute(f"ALTER TABLE {table_name} ADD COLUMN summary_en TEXT")
        if "covered_through_message_id_zh" not in columns:
            database.execute(
                f"ALTER TABLE {table_name} ADD COLUMN covered_through_message_id_zh INTEGER NOT NULL DEFAULT 0"
            )
        if "covered_through_message_id_en" not in columns:
            database.execute(
                f"ALTER TABLE {table_name} ADD COLUMN covered_through_message_id_en INTEGER NOT NULL DEFAULT 0"
            )
    database.execute(
        "UPDATE conversation_memories SET summary_zh = summary WHERE summary_zh IS NULL"
    )
    database.execute(
        "UPDATE voice_conversation_memories SET summary_zh = summary WHERE summary_zh IS NULL"
    )
    database.execute(
        """
        UPDATE voice_conversation_memories
        SET summary_en = summary
        WHERE summary_en IS NULL AND EXISTS (
            SELECT 1 FROM voice_conversations vc
            JOIN characters c ON c.id = vc.character_id
            LEFT JOIN character_overrides o
                ON o.character_id = c.id AND o.user_id = vc.user_id
            WHERE vc.id = voice_conversation_memories.conversation_id
                AND COALESCE(o.language, c.language) = 'en'
        )
        """
    )
    database.execute(
        """
        UPDATE conversation_memories
        SET covered_through_message_id_zh = covered_through_message_id
        WHERE covered_through_message_id_zh = 0 AND covered_through_message_id > 0
        """
    )
    database.execute(
        """
        UPDATE voice_conversation_memories
        SET covered_through_message_id_zh = covered_through_message_id
        WHERE covered_through_message_id_zh = 0 AND covered_through_message_id > 0
        """
    )
    database.execute(
        """
        UPDATE voice_conversation_memories
        SET covered_through_message_id_en = covered_through_message_id
        WHERE covered_through_message_id_en = 0
            AND covered_through_message_id > 0
            AND EXISTS (
                SELECT 1 FROM voice_conversations vc
                JOIN characters c ON c.id = vc.character_id
                LEFT JOIN character_overrides o
                    ON o.character_id = c.id AND o.user_id = vc.user_id
                WHERE vc.id = voice_conversation_memories.conversation_id
                    AND COALESCE(o.language, c.language) = 'en'
            )
        """
    )
    message_columns = {row["name"] for row in database.execute("PRAGMA table_info(messages)").fetchall()}
    if "conversation_id" not in message_columns:
        database.execute("ALTER TABLE messages ADD COLUMN conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE")
    if "token_count" not in message_columns:
        database.execute("ALTER TABLE messages ADD COLUMN token_count INTEGER")
    database.execute(
        "UPDATE messages SET token_count = MAX(1, LENGTH(content)) WHERE token_count IS NULL"
    )
    database.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id)"
    )
    voice_message_columns = {
        row["name"] for row in database.execute("PRAGMA table_info(voice_messages)").fetchall()
    }
    if "token_count" not in voice_message_columns:
        database.execute("ALTER TABLE voice_messages ADD COLUMN token_count INTEGER")
    if "turn_id" not in voice_message_columns:
        database.execute("ALTER TABLE voice_messages ADD COLUMN turn_id TEXT")
    if "reply_id" not in voice_message_columns:
        database.execute("ALTER TABLE voice_messages ADD COLUMN reply_id TEXT")
    database.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_messages_turn_role
        ON voice_messages(conversation_id, turn_id, role)
        WHERE turn_id IS NOT NULL
        """
    )
    for row in database.execute(
        "SELECT id, content FROM voice_messages WHERE token_count IS NULL"
    ).fetchall():
        database.execute(
            "UPDATE voice_messages SET token_count = ? WHERE id = ?",
            (fallback_token_count(row["content"]), row["id"]),
        )
    legacy_threads = database.execute(
        """
        SELECT user_id, character_id, MIN(created_at) AS created_at, MAX(created_at) AS updated_at
        FROM messages
        WHERE conversation_id IS NULL
        GROUP BY user_id, character_id
        """
    ).fetchall()
    for thread in legacy_threads:
        first_message = database.execute(
            """
            SELECT content FROM messages
            WHERE user_id = ? AND character_id = ? AND conversation_id IS NULL AND role = 'user'
            ORDER BY id LIMIT 1
            """,
            (thread["user_id"], thread["character_id"]),
        ).fetchone()
        title = first_message["content"].strip()[:80] if first_message else "历史对话"
        cursor = database.execute(
            """
            INSERT INTO conversations (user_id, character_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                thread["user_id"],
                thread["character_id"],
                title or "历史对话",
                thread["created_at"],
                thread["updated_at"],
            ),
        )
        database.execute(
            "UPDATE messages SET conversation_id = ? WHERE user_id = ? AND character_id = ? AND conversation_id IS NULL",
            (cursor.lastrowid, thread["user_id"], thread["character_id"]),
        )
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
    database.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, chat_model) VALUES (?, ?, ?)",
        ("CaraLin", generate_password_hash("2766"), DEFAULT_CHAT_MODEL),
    )
    admin_username = os.getenv("INITIAL_ADMIN_USERNAME", "").strip()
    admin_password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    admin_exists = database.execute(
        "SELECT 1 FROM users WHERE is_admin = 1 LIMIT 1"
    ).fetchone()
    if not admin_exists and admin_username and 4 <= len(admin_password) <= 128:
        if not 3 <= len(admin_username) <= 24:
            raise RuntimeError("INITIAL_ADMIN_USERNAME length must be 3 to 24 characters")
        existing_user = database.execute(
            "SELECT is_admin FROM users WHERE username = ? COLLATE NOCASE",
            (admin_username,),
        ).fetchone()
        if existing_user is not None:
            raise RuntimeError("INITIAL_ADMIN_USERNAME is already in use")
        database.execute(
            "INSERT INTO users (username, password_hash, is_admin, chat_model) VALUES (?, ?, 1, ?)",
            (admin_username, generate_password_hash(admin_password), DEFAULT_CHAT_MODEL),
        )
    database.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return jsonify(error="请先登录"), 401
        user = get_db().execute("SELECT id, username FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            session.clear()
            return jsonify(error="请先登录"), 401
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        user = get_db().execute(
            "SELECT is_admin FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        if user is None or not user["is_admin"]:
            return jsonify(error="需要管理员权限"), 403
        return view(*args, **kwargs)

    return wrapped


def serialize_user(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "isAdmin": bool(row["is_admin"]),
        "chatModel": row["chat_model"] if "chat_model" in row.keys() else DEFAULT_CHAT_MODEL,
        "createdAt": row["created_at"] if "created_at" in row.keys() else None,
    }


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
        "lastMessage": (row["last_message"] or "") if "last_message" in row.keys() else "",
        "lastMessageAt": row["last_message_at"] if "last_message_at" in row.keys() else None,
    }


def avatar_url_from(payload, default=""):
    avatar_url = str(payload.get("avatarUrl", default)).strip()
    if AVATAR_DATA_URL.fullmatch(avatar_url):
        return store_avatar_snapshot(avatar_url, AVATAR_DIR)
    if avatar_url and not (
        avatar_url.startswith("/assets/") or avatar_url.startswith("./media/avatars/")
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
            "INSERT INTO users (username, password_hash, chat_model) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), DEFAULT_CHAT_MODEL),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        return jsonify(error="该账号已存在"), 409
    session.permanent = True
    session["user_id"] = cursor.lastrowid
    session["username"] = username
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return jsonify(user=serialize_user(user)), 201


@app.post("/api/auth/login")
def login():
    payload = request.get_json(silent=True) or {}
    user = get_db().execute(
        "SELECT id, username, password_hash, is_admin, created_at FROM users WHERE username = ? COLLATE NOCASE",
        (payload.get("username", "").strip(),),
    ).fetchone()
    if user is None or not check_password_hash(user["password_hash"], payload.get("password", "")):
        return jsonify(error="账号或密码不正确"), 401
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return jsonify(user=serialize_user(user))


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/auth/me")
def current_user():
    if not session.get("user_id"):
        return jsonify(user=None)
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if user is None:
        session.clear()
        return jsonify(user=None)
    return jsonify(user=serialize_user(user))


@app.get("/api/profile/models")
@login_required
def list_chat_models():
    return jsonify(
        models=[{"id": model_id, "name": name} for model_id, name in CHAT_MODELS.items()]
    )


@app.patch("/api/profile/model")
@login_required
def update_chat_model():
    model_id = str((request.get_json(silent=True) or {}).get("model", "")).strip()
    if model_id not in CHAT_MODELS:
        return jsonify(error="不支持该聊天模型"), 400
    database = get_db()
    database.execute(
        "UPDATE users SET chat_model = ? WHERE id = ?",
        (model_id, session["user_id"]),
    )
    database.commit()
    user = database.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return jsonify(user=serialize_user(user))


@app.get("/api/admin/users")
@admin_required
def list_users():
    rows = get_db().execute(
        "SELECT id, username, is_admin, created_at FROM users ORDER BY is_admin DESC, username COLLATE NOCASE"
    ).fetchall()
    return jsonify(users=[serialize_user(row) for row in rows])


@app.post("/api/admin/users")
@admin_required
def create_user():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if len(username) < 3 or len(username) > 24:
        return jsonify(error="账号长度需为 3 至 24 个字符"), 400
    if len(password) < 4 or len(password) > 128:
        return jsonify(error="密码长度需为 4 至 128 个字符"), 400
    try:
        cursor = get_db().execute(
            "INSERT INTO users (username, password_hash, chat_model) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), DEFAULT_CHAT_MODEL),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        return jsonify(error="该账号已存在"), 409
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return jsonify(user=serialize_user(user)), 201


@app.patch("/api/admin/users/<int:user_id>/password")
@admin_required
def reset_user_password(user_id):
    password = str((request.get_json(silent=True) or {}).get("password", ""))
    if len(password) < 4 or len(password) > 128:
        return jsonify(error="密码长度需为 4 至 128 个字符"), 400
    cursor = get_db().execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(password), user_id),
    )
    if cursor.rowcount == 0:
        return jsonify(error="未找到该用户"), 404
    get_db().commit()
    return jsonify(ok=True)


@app.delete("/api/admin/users/<int:user_id>")
@admin_required
def delete_user(user_id):
    if user_id == session["user_id"]:
        return jsonify(error="不能删除当前管理员账号"), 409
    user = get_db().execute("SELECT id, is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        return jsonify(error="未找到该用户"), 404
    if user["is_admin"]:
        return jsonify(error="不能删除管理员账号"), 409
    get_db().execute("DELETE FROM users WHERE id = ?", (user_id,))
    get_db().commit()
    return jsonify(ok=True)


@app.get("/api/voices")
@login_required
def list_voices():
    rows = get_db().execute(
        "SELECT id, name, description FROM voices ORDER BY created_at, id"
    ).fetchall()
    return jsonify(voices=[dict(row) for row in rows])


def system_voice(voice_id):
    return get_db().execute(
        "SELECT id, name, description FROM voices WHERE id = ?", (voice_id,)
    ).fetchone()


def character_values(payload, fallback=None):
    fallback = fallback or {}
    fallback_value = lambda key, default="": fallback[key] if key in fallback.keys() else default
    name = str(payload.get("name", fallback_value("name"))).strip()
    persona = str(payload.get("persona", fallback_value("persona"))).strip()
    voice_id = str(payload.get("voiceId", fallback_value("voice_id"))).strip()
    language = str(payload.get("language", fallback_value("language", "zh"))).strip()
    if not name or not persona or not voice_id:
        raise ValueError("请完整填写角色名称、人设与音色")
    if len(name) > 40 or len(persona) > 2400:
        raise ValueError("角色名称或身份背景超过长度限制")
    if language not in {"zh", "en"}:
        raise ValueError("角色语言仅支持中文或英文")
    voice = system_voice(voice_id)
    if voice is None:
        raise ValueError("只能选择系统音色")
    return name, persona, voice_id, voice["name"], language


def parse_persona_translation(response_text):
    text = str(response_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    translated = json.loads(text)
    name = str(translated.get("name", "")).strip()
    persona = str(translated.get("persona", "")).strip()
    if not name or not persona:
        raise ValueError("Persona translation is missing required fields")
    return name, persona


def persona_translation_target(table_name, character_id, user_id=None):
    if table_name == "characters":
        return "id = ?", (character_id,)
    if table_name == "character_overrides" and user_id is not None:
        return "character_id = ? AND user_id = ?", (character_id, user_id)
    raise ValueError("Unsupported persona translation target")


def store_persona_translation(table_name, character_id, user_id, source_name, source_persona, name_en, persona_en):
    where_sql, identifiers = persona_translation_target(table_name, character_id, user_id)
    with app.app_context():
        database = get_db()
        try:
            database.execute(
                f"""
                UPDATE {table_name}
                SET name_en = ?, persona_en = ?
                WHERE {where_sql} AND name = ? AND persona = ?
                """,
                (name_en, persona_en, *identifiers, source_name, source_persona),
            )
            database.commit()
        except sqlite3.OperationalError as error:
            if "no such table" not in str(error).lower():
                raise


def run_persona_translation(table_name, character_id, user_id, source_name, source_persona, job_key):
    try:
        response = ark.responses.create(
            model=TRANSLATION_MODEL,
            instructions=PERSONA_TRANSLATION_PROMPT,
            input=[{
                "role": "user",
                "content": json.dumps(
                    {"name": source_name, "persona": source_persona},
                    ensure_ascii=False,
                ),
            }],
            extra_body={"thinking": {"type": "disabled"}},
        )
        name_en, persona_en = parse_persona_translation(
            getattr(response, "output_text", "")
        )
        store_persona_translation(
            table_name,
            character_id,
            user_id,
            source_name,
            source_persona,
            name_en,
            persona_en,
        )
    except Exception:
        app.logger.exception(
            "Persona translation failed for %s character %s", table_name, character_id
        )
    finally:
        with persona_translation_jobs_lock:
            persona_translation_jobs.discard(job_key)


def schedule_persona_translation(table_name, character_id, source_name, source_persona, user_id=None):
    if is_english_text(source_name) and is_english_text(source_persona):
        store_persona_translation(
            table_name,
            character_id,
            user_id,
            source_name,
            source_persona,
            source_name,
            source_persona,
        )
        return
    job_key = (table_name, character_id, user_id, source_name, source_persona)
    with persona_translation_jobs_lock:
        if job_key in persona_translation_jobs:
            return
        persona_translation_jobs.add(job_key)
    try:
        persona_translation_executor.submit(
            run_persona_translation,
            table_name,
            character_id,
            user_id,
            source_name,
            source_persona,
            job_key,
        )
    except Exception:
        with persona_translation_jobs_lock:
            persona_translation_jobs.discard(job_key)
        app.logger.exception("Unable to schedule persona translation")


def schedule_missing_persona_translations(database):
    targets = [
        ("characters", row["id"], None, row["name"], row["persona"])
        for row in database.execute(
            "SELECT id, name, persona FROM characters WHERE name_en IS NULL OR persona_en IS NULL"
        ).fetchall()
    ]
    targets.extend(
        ("character_overrides", row["character_id"], row["user_id"], row["name"], row["persona"])
        for row in database.execute(
            """
            SELECT user_id, character_id, name, persona
            FROM character_overrides
            WHERE name_en IS NULL OR persona_en IS NULL
            """
        ).fetchall()
    )
    for table_name, character_id, user_id, name, persona in targets:
        schedule_persona_translation(
            table_name, character_id, name, persona, user_id
        )


@app.get("/api/admin/characters")
@admin_required
def list_preset_characters():
    rows = get_db().execute(
        "SELECT * FROM characters WHERE is_preset = 1 ORDER BY created_at, id"
    ).fetchall()
    return jsonify(characters=[serialize_character(row) for row in rows])


@app.post("/api/admin/characters")
@admin_required
def create_preset_character():
    payload = request.get_json(silent=True) or {}
    try:
        values = character_values(payload)
        avatar_url = avatar_url_from(payload)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    cursor = get_db().execute(
        """
        INSERT INTO characters (
            owner_id, name, persona, voice_id, voice_name, language, avatar_url, is_preset
        ) VALUES (NULL, ?, ?, ?, ?, ?, ?, 1)
        """,
        (*values, avatar_url),
    )
    get_db().commit()
    schedule_persona_translation(
        "characters", cursor.lastrowid, values[0], values[1]
    )
    row = get_db().execute("SELECT * FROM characters WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return jsonify(character=serialize_character(row)), 201


@app.patch("/api/admin/characters/<int:character_id>")
@admin_required
def update_preset_character(character_id):
    character = get_db().execute(
        "SELECT * FROM characters WHERE id = ? AND is_preset = 1", (character_id,)
    ).fetchone()
    if character is None:
        return jsonify(error="未找到该预置角色"), 404
    try:
        values = character_values(request.get_json(silent=True) or {}, character)
        avatar_url = avatar_url_from(request.get_json(silent=True) or {}, character["avatar_url"])
    except ValueError as error:
        return jsonify(error=str(error)), 400
    database = get_db()
    database.execute(
        """
        UPDATE characters
        SET name = ?, persona = ?, voice_id = ?, voice_name = ?, language = ?, avatar_url = ?
        WHERE id = ?
        """,
        (*values, avatar_url, character_id),
    )
    database.execute("DELETE FROM character_overrides WHERE character_id = ?", (character_id,))
    database.commit()
    if (
        values[0] != character["name"]
        or values[1] != character["persona"]
        or not character_value(character, "name_en")
        or not character_value(character, "persona_en")
    ):
        schedule_persona_translation(
            "characters", character_id, values[0], values[1]
        )
    row = database.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone()
    return jsonify(character=serialize_character(row))


@app.delete("/api/admin/characters/<int:character_id>")
@admin_required
def delete_preset_character(character_id):
    character = get_db().execute(
        "SELECT id FROM characters WHERE id = ? AND is_preset = 1", (character_id,)
    ).fetchone()
    if character is None:
        return jsonify(error="未找到该预置角色"), 404
    database = get_db()
    database.execute("DELETE FROM characters WHERE id = ?", (character_id,))
    database.commit()
    return jsonify(ok=True)


def voice_values(payload):
    voice_id = str(payload.get("id", "")).strip()
    name = str(payload.get("name", "")).strip()
    description = str(payload.get("description", "")).strip()
    if not name or not voice_id:
        raise ValueError("请填写音色名称和 speaker_id")
    if len(name) > 40 or len(voice_id) > 120 or len(description) > 120:
        raise ValueError("音色名称、speaker_id 或描述超过长度限制")
    if not voice_id.startswith(("S_", "ICL_", "saturn_", "sparkchat_", "custom_")):
        raise ValueError("speaker_id 格式无效")
    return voice_id, name, description


@app.post("/api/admin/voices")
@admin_required
def create_system_voice():
    try:
        values = voice_values(request.get_json(silent=True) or {})
    except ValueError as error:
        return jsonify(error=str(error)), 400
    try:
        get_db().execute(
            "INSERT INTO voices (id, name, description) VALUES (?, ?, ?)",
            values,
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        return jsonify(error="该 speaker_id 已存在"), 409
    voice = system_voice(values[0])
    return jsonify(voice=dict(voice)), 201


@app.patch("/api/admin/voices/<voice_id>")
@admin_required
def update_system_voice(voice_id):
    current = system_voice(voice_id)
    if current is None:
        return jsonify(error="未找到该音色"), 404
    payload = request.get_json(silent=True) or {}
    payload.setdefault("id", voice_id)
    payload.setdefault("description", current["description"])
    try:
        values = voice_values(payload)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    try:
        get_db().execute(
            "UPDATE voices SET id = ?, name = ?, description = ? WHERE id = ?",
            (*values, voice_id),
        )
        get_db().execute(
            "UPDATE characters SET voice_id = ?, voice_name = ? WHERE voice_id = ?",
            (values[0], values[1], voice_id),
        )
        get_db().execute(
            "UPDATE character_overrides SET voice_id = ?, voice_name = ? WHERE voice_id = ?",
            (values[0], values[1], voice_id),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        get_db().rollback()
        return jsonify(error="该 speaker_id 已存在"), 409
    voice = system_voice(values[0])
    return jsonify(voice=dict(voice))


@app.get("/api/characters")
@login_required
def list_characters():
    rows = get_db().execute(
        """
        WITH latest_conversations AS (
            SELECT id, character_id,
                ROW_NUMBER() OVER (
                    PARTITION BY character_id
                    ORDER BY updated_at DESC, id DESC
                ) AS position
            FROM conversations
            WHERE user_id = ?
        ),
        latest_messages AS (
            SELECT conversation_id, content, created_at,
                ROW_NUMBER() OVER (
                    PARTITION BY conversation_id
                    ORDER BY id DESC
                ) AS position
            FROM messages
            WHERE user_id = ?
        )
        SELECT c.id, c.owner_id, c.is_preset, c.created_at,
            COALESCE(o.name, c.name) AS name,
            COALESCE(o.persona, c.persona) AS persona,
            CASE WHEN o.character_id IS NULL THEN c.name_en ELSE o.name_en END AS name_en,
            CASE WHEN o.character_id IS NULL THEN c.persona_en ELSE o.persona_en END AS persona_en,
            COALESCE(o.voice_id, c.voice_id) AS voice_id,
            COALESCE(o.voice_name, c.voice_name) AS voice_name,
            COALESCE(o.language, c.language) AS language,
            COALESCE(o.avatar_url, c.avatar_url) AS avatar_url,
            lm.content AS last_message,
            lm.created_at AS last_message_at
        FROM characters c
        LEFT JOIN character_overrides o ON o.character_id = c.id AND o.user_id = ?
        LEFT JOIN latest_conversations lc
            ON lc.character_id = c.id AND lc.position = 1
        LEFT JOIN latest_messages lm
            ON lm.conversation_id = lc.id AND lm.position = 1
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
    schedule_persona_translation(
        "characters",
        cursor.lastrowid,
        payload["name"].strip(),
        payload["persona"].strip(),
    )
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
    persona_unchanged = (
        values[0] == character["name"] and values[1] == character["persona"]
    )
    if character["is_preset"]:
        inherited_name_en = character_value(character, "name_en") if persona_unchanged else None
        inherited_persona_en = character_value(character, "persona_en") if persona_unchanged else None
        get_db().execute(
            """
            INSERT INTO character_overrides (
                user_id, character_id, name, persona, name_en, persona_en,
                voice_id, voice_name, language, avatar_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, character_id) DO UPDATE SET
                name = excluded.name, persona = excluded.persona,
                name_en = excluded.name_en, persona_en = excluded.persona_en,
                voice_id = excluded.voice_id, voice_name = excluded.voice_name,
                language = excluded.language,
                avatar_url = excluded.avatar_url
            """,
            (
                session["user_id"],
                character_id,
                values[0],
                values[1],
                inherited_name_en,
                inherited_persona_en,
                *values[2:],
            ),
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
    has_english_persona = bool(
        inherited_name_en and inherited_persona_en
        if character["is_preset"]
        else character_value(character, "name_en")
        and character_value(character, "persona_en")
    )
    if not persona_unchanged or not has_english_persona:
        schedule_persona_translation(
            "character_overrides" if character["is_preset"] else "characters",
            character_id,
            values[0],
            values[1],
            session["user_id"] if character["is_preset"] else None,
        )
    row = get_character(character_id)
    return jsonify(character=serialize_character(row))


@app.delete("/api/characters/<int:character_id>")
@login_required
def delete_character(character_id):
    character = get_character(character_id)
    if character is None:
        return jsonify(error="未找到该角色"), 404
    if character["is_preset"]:
        return jsonify(error="预置角色不可删除"), 409
    get_db().execute(
        "DELETE FROM characters WHERE id = ? AND owner_id = ?",
        (character_id, session["user_id"]),
    )
    get_db().commit()
    return jsonify(ok=True)


def get_character(character_id):
    return get_db().execute(
        """
        SELECT c.id, c.owner_id, c.is_preset, c.created_at,
            COALESCE(o.name, c.name) AS name,
            COALESCE(o.persona, c.persona) AS persona,
            CASE WHEN o.character_id IS NULL THEN c.name_en ELSE o.name_en END AS name_en,
            CASE WHEN o.character_id IS NULL THEN c.persona_en ELSE o.persona_en END AS persona_en,
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


def get_conversation(character_id, conversation_id):
    return get_db().execute(
        """
        SELECT c.id, c.user_id, c.character_id, c.title, c.title_custom, c.created_at, c.updated_at,
            (SELECT content FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_message
        FROM conversations c
        WHERE c.id = ? AND c.user_id = ? AND c.character_id = ?
        """,
        (conversation_id, session["user_id"], character_id),
    ).fetchone()


def serialize_conversation(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "titleCustom": bool(row["title_custom"]) if "title_custom" in row.keys() else False,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "lastMessage": row["last_message"] if "last_message" in row.keys() else "",
    }


def get_voice_conversation(character_id, conversation_id):
    return get_db().execute(
        """
        SELECT c.id, c.user_id, c.character_id, c.title, c.title_custom, c.created_at, c.updated_at,
            (SELECT content FROM voice_messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_message
        FROM voice_conversations c
        WHERE c.id = ? AND c.user_id = ? AND c.character_id = ?
        """,
        (conversation_id, session["user_id"], character_id),
    ).fetchone()


@app.get("/api/characters/<int:character_id>/voice-conversations")
@login_required
def list_voice_conversations(character_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    rows = get_db().execute(
        """
        SELECT c.id, c.title, c.title_custom, c.created_at, c.updated_at,
            (SELECT content FROM voice_messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_message,
            COALESCE((SELECT created_at FROM voice_messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1), c.updated_at) AS activity_at
        FROM voice_conversations c
        WHERE c.user_id = ? AND c.character_id = ?
        ORDER BY activity_at DESC, c.id DESC
        """,
        (session["user_id"], character_id),
    ).fetchall()
    return jsonify(conversations=[serialize_conversation(row) for row in rows])


@app.post("/api/characters/<int:character_id>/voice-conversations")
@login_required
def create_voice_conversation(character_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    cursor = get_db().execute(
        "INSERT INTO voice_conversations (user_id, character_id) VALUES (?, ?)",
        (session["user_id"], character_id),
    )
    get_db().commit()
    return jsonify(conversation=serialize_conversation(
        get_voice_conversation(character_id, cursor.lastrowid)
    )), 201


@app.patch("/api/characters/<int:character_id>/voice-conversations/<int:conversation_id>")
@login_required
def rename_voice_conversation(character_id, conversation_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    if get_voice_conversation(character_id, conversation_id) is None:
        return jsonify(error="未找到该语音通话"), 404
    title = str((request.get_json(silent=True) or {}).get("title", "")).strip()
    if not title or len(title) > 80:
        return jsonify(error="通话名称需为 1 至 80 个字符"), 400
    get_db().execute(
        "UPDATE voice_conversations SET title = ?, title_custom = 1 WHERE id = ?",
        (title, conversation_id),
    )
    get_db().commit()
    return jsonify(conversation=serialize_conversation(
        get_voice_conversation(character_id, conversation_id)
    ))


@app.delete("/api/characters/<int:character_id>/voice-conversations/<int:conversation_id>")
@login_required
def delete_voice_conversation(character_id, conversation_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    if get_voice_conversation(character_id, conversation_id) is None:
        return jsonify(error="未找到该语音通话"), 404
    get_db().execute(
        "DELETE FROM voice_conversations WHERE id = ? AND user_id = ? AND character_id = ?",
        (conversation_id, session["user_id"], character_id),
    )
    get_db().commit()
    return jsonify(ok=True)


@app.get("/api/characters/<int:character_id>/voice-conversations/<int:conversation_id>/messages")
@login_required
def list_voice_messages(character_id, conversation_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    if get_voice_conversation(character_id, conversation_id) is None:
        return jsonify(error="未找到该语音通话"), 404
    rows = get_db().execute(
        "SELECT id, role, content, turn_id, reply_id, token_count, created_at FROM voice_messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return jsonify(messages=[dict(row) for row in rows])


@app.post("/api/characters/<int:character_id>/voice-conversations/<int:conversation_id>/messages")
@login_required
def create_voice_message(character_id, conversation_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    conversation = get_voice_conversation(character_id, conversation_id)
    if conversation is None:
        return jsonify(error="未找到该语音通话"), 404
    payload = request.get_json(silent=True) or {}
    role = str(payload.get("role", "")).strip()
    content = str(payload.get("content", "")).strip()
    turn_id = str(payload.get("turnId", "")).strip() or None
    reply_id = str(payload.get("replyId", "")).strip() or None
    if (
        role not in {"user", "assistant"}
        or not content
        or len(content) > 12000
        or (turn_id and len(turn_id) > 200)
        or (reply_id and len(reply_id) > 200)
    ):
        return jsonify(error="语音消息内容无效"), 400
    if turn_id:
        existing = get_db().execute(
            """
            SELECT id, role, content, turn_id, reply_id, token_count, created_at
            FROM voice_messages
            WHERE conversation_id = ? AND turn_id = ? AND role = ?
            """,
            (conversation_id, turn_id, role),
        ).fetchone()
        if existing is not None:
            return jsonify(message=dict(existing), duplicate=True)
    cursor = get_db().execute(
        """
        INSERT INTO voice_messages (
            user_id, character_id, conversation_id, role, content,
            turn_id, reply_id, token_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session["user_id"], character_id, conversation_id,
            role, content, turn_id, reply_id, fallback_token_count(content),
        ),
    )
    if role == "user" and not conversation["title_custom"]:
        first_user = get_db().execute(
            "SELECT id FROM voice_messages WHERE conversation_id = ? AND role = 'user' ORDER BY id LIMIT 1",
            (conversation_id,),
        ).fetchone()
        if first_user and first_user["id"] == cursor.lastrowid:
            get_db().execute(
                "UPDATE voice_conversations SET title = ? WHERE id = ?",
                (content[:80], conversation_id),
            )
    get_db().execute(
        "UPDATE voice_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (conversation_id,),
    )
    get_db().commit()
    if role == "assistant":
        schedule_voice_memory_update(conversation_id)
    row = get_db().execute(
        "SELECT id, role, content, turn_id, reply_id, token_count, created_at FROM voice_messages WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return jsonify(message=dict(row)), 201


@app.delete("/api/characters/<int:character_id>/voice-conversations/<int:conversation_id>/turns/<turn_id>")
@login_required
def delete_voice_turn(character_id, conversation_id, turn_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    conversation = get_voice_conversation(character_id, conversation_id)
    if conversation is None:
        return jsonify(error="未找到该语音通话"), 404
    rows = get_db().execute(
        """
        SELECT id FROM voice_messages
        WHERE conversation_id = ? AND user_id = ? AND character_id = ? AND turn_id = ?
        ORDER BY id
        """,
        (conversation_id, session["user_id"], character_id, turn_id),
    ).fetchall()
    if not rows:
        return jsonify(
            ok=True,
            deletedIds=[],
            conversation=serialize_conversation(conversation),
        )
    latest_turn = get_db().execute(
        """
        SELECT turn_id FROM voice_messages
        WHERE conversation_id = ? AND turn_id IS NOT NULL
        ORDER BY id DESC LIMIT 1
        """,
        (conversation_id,),
    ).fetchone()
    if latest_turn is None or latest_turn["turn_id"] != turn_id:
        return jsonify(error="只能撤回最近一轮语音对话"), 409
    covered = get_db().execute(
        """
        SELECT MAX(
            covered_through_message_id,
            covered_through_message_id_zh,
            covered_through_message_id_en
        ) AS message_id
        FROM voice_conversation_memories WHERE conversation_id = ?
        """,
        (conversation_id,),
    ).fetchone()
    if covered and covered["message_id"] and rows[0]["id"] <= covered["message_id"]:
        return jsonify(error="该轮语音对话已进入长期记忆，无法撤回"), 409
    deleted_ids = [row["id"] for row in rows]
    get_db().execute(
        "DELETE FROM voice_messages WHERE conversation_id = ? AND turn_id = ?",
        (conversation_id, turn_id),
    )
    if not conversation["title_custom"]:
        first_user = get_db().execute(
            """
            SELECT content FROM voice_messages
            WHERE conversation_id = ? AND role = 'user'
            ORDER BY id LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()
        get_db().execute(
            "UPDATE voice_conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            ((first_user["content"][:80] if first_user else "新通话"), conversation_id),
        )
    else:
        get_db().execute(
            "UPDATE voice_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (conversation_id,),
        )
    get_db().commit()
    return jsonify(
        ok=True,
        deletedIds=deleted_ids,
        conversation=serialize_conversation(
            get_voice_conversation(character_id, conversation_id)
        ),
    )


@app.post("/api/characters/<int:character_id>/voice-conversations/<int:conversation_id>/usage")
@login_required
def update_voice_turn_usage(character_id, conversation_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    if get_voice_conversation(character_id, conversation_id) is None:
        return jsonify(error="未找到该语音通话"), 404
    payload = request.get_json(silent=True) or {}
    usage = payload.get("usage") or {}
    message_ids = payload.get("messageIds") or {}
    try:
        user_tokens = max(
            0,
            int(usage.get("input_text_tokens", 0) or 0)
            + int(usage.get("input_audio_tokens", 0) or 0),
        )
        assistant_tokens = max(0, int(usage.get("output_text_tokens", 0) or 0))
        user_message_id = int(message_ids.get("user", 0) or 0)
        assistant_message_id = int(message_ids.get("assistant", 0) or 0)
    except (TypeError, ValueError):
        return jsonify(error="语音用量信息无效"), 400
    updates = (
        (user_message_id, "user", user_tokens),
        (assistant_message_id, "assistant", assistant_tokens),
    )
    for message_id, role, token_count in updates:
        if not message_id or not token_count:
            continue
        cursor = get_db().execute(
            """
            UPDATE voice_messages SET token_count = ?
            WHERE id = ? AND conversation_id = ? AND user_id = ?
                AND character_id = ? AND role = ?
            """,
            (
                token_count, message_id, conversation_id,
                session["user_id"], character_id, role,
            ),
        )
        if cursor.rowcount != 1:
            get_db().rollback()
            return jsonify(error="语音用量对应的消息无效"), 409
    get_db().commit()
    schedule_voice_memory_update(conversation_id)
    return jsonify(ok=True)


def memory_column(language, base_name):
    language = normalize_prompt_language(language)
    return f"{base_name}_{language}"


def voice_conversation_context(database, conversation_id, language="zh"):
    language = normalize_prompt_language(language)
    summary_column = memory_column(language, "summary")
    covered_column = memory_column(language, "covered_through_message_id")
    memory = database.execute(
        f"SELECT {summary_column} AS summary, {covered_column} AS covered_through_message_id FROM voice_conversation_memories WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()
    covered_through = memory["covered_through_message_id"] if memory else 0
    rows = database.execute(
        "SELECT id, role, content, token_count FROM voice_messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    messages = [dict(row) for row in rows]
    recent = select_recent_messages(
        messages, covered_through, VOICE_RECENT_CONTEXT_MAX_TOKENS
    )
    return (memory["summary"].strip() if memory else ""), recent


def run_voice_memory_update(conversation_id):
    try:
        with app.app_context():
            database = get_db()
            conversation = database.execute(
                """
                SELECT COALESCE(o.language, c.language) AS language
                FROM voice_conversations vc
                JOIN characters c ON c.id = vc.character_id
                LEFT JOIN character_overrides o
                    ON o.character_id = c.id AND o.user_id = vc.user_id
                WHERE vc.id = ?
                """,
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                return
            memory = database.execute(
                """
                SELECT summary_zh, summary_en, covered_through_message_id
                FROM voice_conversation_memories WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
            covered_through = memory["covered_through_message_id"] if memory else 0
            messages = [
                dict(row) for row in database.execute(
                    "SELECT id, role, content, token_count FROM voice_messages WHERE conversation_id = ? ORDER BY id",
                    (conversation_id,),
                ).fetchall()
            ]
            memory_batch = select_memory_batch(
                messages, covered_through, VOICE_MEMORY_UPDATE_INTERVAL_TOKENS
            )
            if not memory_batch:
                return
            new_covered_through = memory_batch[-1]["id"]
            summaries = {}
            for language in ("zh", "en"):
                role_labels = ("用户", "数字角色") if language == "zh" else ("User", "Character")
                transcript = "\n".join(
                    f"{role_labels[0] if row['role'] == 'user' else role_labels[1]}: {row['content']}"
                    for row in memory_batch
                )
                previous_summary = memory[f"summary_{language}"] if memory else ""
                memory_input = (
                    f"旧记忆：\n{previous_summary or '（空）'}\n\n新增语音通话：\n{transcript}"
                    if language == "zh"
                    else f"Previous memory:\n{previous_summary or '(empty)'}\n\nNew voice conversation:\n{transcript}"
                )
                response = ark.responses.create(
                    model=MEMORY_MODEL,
                    instructions=MEMORY_PROMPTS[language],
                    input=[{"role": "user", "content": memory_input}],
                    max_output_tokens=1000,
                    extra_body={"thinking": {"type": "disabled"}},
                )
                summaries[language] = str(
                    getattr(response, "output_text", "") or ""
                ).strip()
                if not summaries[language]:
                    raise RuntimeError(f"Memory model returned no {language} content")
            database.execute(
                """
                INSERT INTO voice_conversation_memories (
                    conversation_id, summary, covered_through_message_id,
                    summary_zh, summary_en,
                    covered_through_message_id_zh, covered_through_message_id_en,
                    updated_at
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
                WHERE EXISTS (SELECT 1 FROM voice_conversations WHERE id = ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    summary = excluded.summary,
                    covered_through_message_id = excluded.covered_through_message_id,
                    summary_zh = excluded.summary_zh,
                    summary_en = excluded.summary_en,
                    covered_through_message_id_zh = excluded.covered_through_message_id_zh,
                    covered_through_message_id_en = excluded.covered_through_message_id_en,
                    updated_at = CURRENT_TIMESTAMP
                WHERE voice_conversation_memories.covered_through_message_id = ?
                """,
                (
                    conversation_id, summaries["zh"], new_covered_through,
                    summaries["zh"], summaries["en"],
                    new_covered_through, new_covered_through,
                    conversation_id, covered_through,
                ),
            )
            database.commit()
            with voice_memory_jobs_lock:
                voice_memory_reruns.add(conversation_id)
    except Exception:
        app.logger.exception("Voice conversation memory update failed for conversation %s", conversation_id)
    finally:
        with voice_memory_jobs_lock:
            voice_memory_jobs.discard(conversation_id)
            rerun = conversation_id in voice_memory_reruns
            voice_memory_reruns.discard(conversation_id)
        if rerun:
            schedule_voice_memory_update(conversation_id)


def schedule_voice_memory_update(conversation_id):
    with voice_memory_jobs_lock:
        if conversation_id in voice_memory_jobs:
            voice_memory_reruns.add(conversation_id)
            return
        voice_memory_jobs.add(conversation_id)
    try:
        memory_executor.submit(run_voice_memory_update, conversation_id)
    except Exception:
        with voice_memory_jobs_lock:
            voice_memory_jobs.discard(conversation_id)
            voice_memory_reruns.discard(conversation_id)
        app.logger.exception("Unable to schedule voice conversation memory update")


@app.post("/api/characters/<int:character_id>/voice-messages/<int:message_id>/translate")
@login_required
def translate_voice_message(character_id, message_id):
    character = get_character(character_id)
    if character is None:
        return jsonify(error="未找到该角色"), 404
    message = get_db().execute(
        """
        SELECT id, conversation_id, content FROM voice_messages
        WHERE id = ? AND user_id = ? AND character_id = ? AND role = 'assistant'
        """,
        (message_id, session["user_id"], character_id),
    ).fetchone()
    if message is None:
        return jsonify(error="未找到可翻译的语音回复"), 404
    cached = get_db().execute(
        "SELECT translated_text FROM voice_translation_cache WHERE user_id = ? AND message_id = ?",
        (session["user_id"], message_id),
    ).fetchone()
    context = get_db().execute(
        """
        SELECT role, content FROM voice_messages
        WHERE conversation_id = ? AND id <= ? ORDER BY id DESC LIMIT 8
        """,
        (message["conversation_id"], message_id),
    ).fetchall()[::-1]

    @stream_with_context
    def generate():
        try:
            if cached is not None:
                translation = cached["translated_text"]
                yield f"data: {json.dumps({'type': 'delta', 'text': translation}, ensure_ascii=False)}\n\n"
            else:
                response = ark.responses.create(
                    model=TRANSLATION_MODEL,
                    instructions=TRANSLATION_PROMPTS[
                        normalize_prompt_language(character["language"])
                    ],
                    input=[{"role": "user", "content": "对话语境：\n" + "\n".join(
                        f"{'用户' if row['role'] == 'user' else '数字角色'}：{row['content']}"
                        for row in context[:-1]
                    ) + f"\n\n待翻译的数字角色回复：\n{message['content']}"}],
                    stream=True,
                    extra_body={"thinking": {"type": "disabled"}},
                )
                parts = []
                for event in response:
                    if event.type == "response.output_text.delta":
                        parts.append(event.delta)
                        yield f"data: {json.dumps({'type': 'delta', 'text': event.delta}, ensure_ascii=False)}\n\n"
                translation = "".join(parts).strip()
                if not translation:
                    raise RuntimeError("翻译服务未返回有效内容")
                database = get_db()
                database.execute(
                    """
                    INSERT INTO voice_translation_cache (user_id, character_id, message_id, translated_text)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, message_id) DO UPDATE SET
                        translated_text = excluded.translated_text,
                        created_at = CURRENT_TIMESTAMP
                    """,
                    (session["user_id"], character_id, message_id, translation),
                )
                database.execute(
                    """
                    DELETE FROM voice_translation_cache
                    WHERE user_id = ? AND character_id = ? AND rowid NOT IN (
                        SELECT rowid FROM voice_translation_cache
                        WHERE user_id = ? AND character_id = ?
                        ORDER BY created_at DESC, rowid DESC LIMIT 20
                    )
                    """,
                    (session["user_id"], character_id, session["user_id"], character_id),
                )
                database.commit()
            yield f"data: {json.dumps({'type': 'done', 'messageId': message_id}, ensure_ascii=False)}\n\n"
        except Exception as error:
            app.logger.exception("Voice message translation failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(error)}, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream", headers={
        "X-Accel-Buffering": "no", "Cache-Control": "no-cache"
    })


@app.get("/api/characters/<int:character_id>/conversations")
@login_required
def list_conversations(character_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    rows = get_db().execute(
        """
        SELECT c.id, c.title, c.title_custom, c.created_at, c.updated_at,
            (SELECT content FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_message,
            COALESCE((SELECT created_at FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1), c.updated_at) AS activity_at
        FROM conversations c
        WHERE c.user_id = ? AND c.character_id = ?
        ORDER BY activity_at DESC, c.id DESC
        """,
        (session["user_id"], character_id),
    ).fetchall()
    return jsonify(conversations=[serialize_conversation(row) for row in rows])


@app.post("/api/characters/<int:character_id>/conversations")
@login_required
def create_conversation(character_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    cursor = get_db().execute(
        "INSERT INTO conversations (user_id, character_id) VALUES (?, ?)",
        (session["user_id"], character_id),
    )
    get_db().commit()
    row = get_conversation(character_id, cursor.lastrowid)
    return jsonify(conversation=serialize_conversation(row)), 201


@app.patch("/api/characters/<int:character_id>/conversations/<int:conversation_id>")
@login_required
def rename_conversation(character_id, conversation_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    conversation = get_conversation(character_id, conversation_id)
    if conversation is None:
        return jsonify(error="未找到该对话"), 404
    title = str((request.get_json(silent=True) or {}).get("title", "")).strip()
    if not title or len(title) > 80:
        return jsonify(error="对话名称需为 1 至 80 个字符"), 400
    get_db().execute(
        "UPDATE conversations SET title = ?, title_custom = 1 WHERE id = ?",
        (title, conversation_id),
    )
    get_db().commit()
    return jsonify(conversation=serialize_conversation(get_conversation(character_id, conversation_id)))


@app.delete("/api/characters/<int:character_id>/conversations/<int:conversation_id>")
@login_required
def delete_conversation(character_id, conversation_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    if get_conversation(character_id, conversation_id) is None:
        return jsonify(error="未找到该对话"), 404
    get_db().execute(
        "DELETE FROM conversations WHERE id = ? AND user_id = ? AND character_id = ?",
        (conversation_id, session["user_id"], character_id),
    )
    get_db().commit()
    return jsonify(ok=True)


@app.get("/api/characters/<int:character_id>/conversations/<int:conversation_id>/messages")
@login_required
def list_messages(character_id, conversation_id):
    if get_character(character_id) is None:
        return jsonify(error="未找到该角色"), 404
    if get_conversation(character_id, conversation_id) is None:
        return jsonify(error="未找到该对话"), 404
    rows = get_db().execute(
        "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return jsonify(messages=[dict(row) for row in rows])


def get_assistant_message(character_id, message_id):
    return get_db().execute(
        """
        SELECT id, conversation_id, content FROM messages
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


def response_usage(event):
    if getattr(event, "type", None) != "response.completed":
        return None
    usage = getattr(getattr(event, "response", None), "usage", None)
    if usage is None:
        return None
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }


def conversation_context(
    database,
    conversation_id,
    language="zh",
    pending_user_message=None,
    before_message_id=None,
):
    language = normalize_prompt_language(language)
    summary_column = memory_column(language, "summary")
    covered_column = memory_column(language, "covered_through_message_id")
    memory = database.execute(
        f"SELECT {summary_column} AS summary, {covered_column} AS covered_through_message_id FROM conversation_memories WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()
    covered_through = memory["covered_through_message_id"] if memory else 0
    if before_message_id is None:
        rows = database.execute(
            "SELECT id, role, content, token_count FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    else:
        rows = database.execute(
            "SELECT id, role, content, token_count FROM messages WHERE conversation_id = ? AND id < ? ORDER BY id",
            (conversation_id, before_message_id),
        ).fetchall()
    messages = [dict(row) for row in rows]
    if pending_user_message is not None:
        pending = dict(pending_user_message)
        pending.setdefault("token_count", message_token_count(pending))
        messages.append(pending)
    recent_messages = select_recent_messages(messages, covered_through)
    model_input = [{"role": row["role"], "content": row["content"]} for row in recent_messages]
    summary = memory["summary"].strip() if memory and memory["summary"] else ""
    if summary:
        model_input.insert(
            0,
            {
                "role": "developer",
                "content": MEMORY_CONTEXT_PROMPTS[language] + "\n\n"
                + summary,
            },
        )
    return model_input, recent_messages


def update_message_token_counts(
    database,
    messages,
    instructions,
    usage,
    assistant_message_id,
    assistant_content,
):
    unmeasured_messages = [message for message in messages if message.get("token_count") is None]
    allocations = allocate_input_tokens(messages, instructions, usage["input_tokens"])
    for message in unmeasured_messages:
        message_id = message.get("id")
        if message_id is None:
            continue
        token_count = allocations.get(message_id, message_token_count(message))
        database.execute(
            "UPDATE messages SET token_count = ? WHERE id = ? AND token_count IS NULL",
            (token_count, message_id),
        )
    if assistant_message_id is not None:
        database.execute(
            "UPDATE messages SET token_count = ? WHERE id = ?",
            (usage["output_tokens"] or max(1, len(assistant_content)), assistant_message_id),
        )


def run_memory_update(conversation_id):
    try:
        with app.app_context():
            database = get_db()
            conversation = database.execute(
                """
                SELECT conv.id, COALESCE(o.language, c.language) AS language
                FROM conversations conv
                JOIN characters c ON c.id = conv.character_id
                LEFT JOIN character_overrides o
                    ON o.character_id = c.id AND o.user_id = conv.user_id
                WHERE conv.id = ?
                """,
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                return
            language = normalize_prompt_language(conversation["language"])
            summary_column = memory_column(language, "summary")
            covered_column = memory_column(language, "covered_through_message_id")
            memory = database.execute(
                f"SELECT {summary_column} AS summary, {covered_column} AS covered_through_message_id FROM conversation_memories WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            previous_summary = memory["summary"] if memory else ""
            covered_through = memory["covered_through_message_id"] if memory else 0
            messages = [
                dict(row)
                for row in database.execute(
                    "SELECT id, role, content, token_count FROM messages WHERE conversation_id = ? ORDER BY id",
                    (conversation_id,),
                ).fetchall()
            ]
            stable_messages = stable_messages_for_memory(messages, covered_through)
            if not should_update_memory(messages, covered_through) or not stable_messages:
                return
            new_covered_through = stable_messages[-1]["id"]
            role_labels = ("用户", "数字角色") if language == "zh" else ("User", "Character")
            transcript = "\n".join(
                f"{role_labels[0] if row['role'] == 'user' else role_labels[1]}: {row['content']}"
                for row in stable_messages
            )
            memory_input = (
                f"旧记忆：\n{previous_summary or '（空）'}\n\n新增对话：\n{transcript}"
                if language == "zh"
                else f"Previous memory:\n{previous_summary or '(empty)'}\n\nNew dialogue:\n{transcript}"
            )
            response = ark.responses.create(
                model=MEMORY_MODEL,
                instructions=MEMORY_PROMPTS[language],
                input=[
                    {
                        "role": "user",
                        "content": memory_input,
                    }
                ],
                extra_body={"thinking": {"type": "disabled"}},
            )
            summary = str(getattr(response, "output_text", "") or "").strip()
            if not summary:
                raise RuntimeError("Memory model returned no content")
            database.execute(
                f"""
                INSERT INTO conversation_memories (
                    conversation_id, summary, covered_through_message_id,
                    {summary_column}, {covered_column}, updated_at
                )
                SELECT ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
                WHERE EXISTS (SELECT 1 FROM conversations WHERE id = ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    summary = excluded.summary,
                    covered_through_message_id = excluded.covered_through_message_id,
                    {summary_column} = excluded.{summary_column},
                    {covered_column} = excluded.{covered_column},
                    updated_at = CURRENT_TIMESTAMP
                WHERE conversation_memories.{covered_column} = ?
                """,
                (
                    conversation_id,
                    summary,
                    new_covered_through,
                    summary,
                    new_covered_through,
                    conversation_id,
                    covered_through,
                ),
            )
            database.commit()
    except Exception:
        app.logger.exception("Conversation memory update failed for conversation %s", conversation_id)
    finally:
        with memory_jobs_lock:
            memory_jobs.discard(conversation_id)


def schedule_memory_update(conversation_id):
    with memory_jobs_lock:
        if conversation_id in memory_jobs:
            return
        memory_jobs.add(conversation_id)
    try:
        memory_executor.submit(run_memory_update, conversation_id)
    except Exception:
        with memory_jobs_lock:
            memory_jobs.discard(conversation_id)
        app.logger.exception("Unable to schedule conversation memory update")


def stream_character_response(
    character,
    conversation_id,
    history,
    history_rows,
    replace_message_id=None,
    user_message_id=None,
    rewrite_message_id=None,
    rewrite_content=None,
    expected_tail_id=None,
):
    @stream_with_context
    def generate():
        full_response = []
        usage = {"input_tokens": 0, "output_tokens": 0}
        instructions = build_agent_instructions(character)
        try:
            user = get_db().execute(
                "SELECT chat_model FROM users WHERE id = ?", (session["user_id"],)
            ).fetchone()
            selected_model = user["chat_model"] if user else None
            chat_model = selected_model if selected_model in CHAT_MODELS else DEFAULT_CHAT_MODEL
            response = ark.responses.create(
                model=chat_model,
                instructions=instructions,
                input=[{"role": row["role"], "content": row["content"]} for row in history],
                stream=True,
                extra_body={"thinking": {"type": "disabled"}},
            )
            for event in response:
                event_usage = response_usage(event)
                if event_usage is not None:
                    usage = event_usage
                if event.type == "response.output_text.delta":
                    full_response.append(event.delta)
                    yield f"data: {json.dumps({'type': 'delta', 'text': event.delta}, ensure_ascii=False)}\n\n"
            final_text = "".join(full_response).strip()
            message_id = replace_message_id
            if final_text:
                if rewrite_message_id is not None:
                    database = get_db()
                    database.execute("BEGIN IMMEDIATE")
                    current_tail = database.execute(
                        "SELECT MAX(id) AS id FROM messages WHERE conversation_id = ? AND user_id = ?",
                        (conversation_id, session["user_id"]),
                    ).fetchone()["id"]
                    if current_tail != expected_tail_id:
                        database.rollback()
                        raise RuntimeError("该对话已发生变化，请刷新后重试")
                    latest_user_message_id = database.execute(
                        "SELECT MAX(id) AS id FROM messages WHERE conversation_id = ? AND user_id = ? AND role = 'user'",
                        (conversation_id, session["user_id"]),
                    ).fetchone()["id"]
                    if latest_user_message_id != rewrite_message_id:
                        database.rollback()
                        raise RuntimeError("只能编辑该对话中最新发送的消息")
                    target = database.execute(
                        """
                        SELECT id, role FROM messages
                        WHERE id = ? AND user_id = ? AND character_id = ?
                            AND conversation_id = ? AND role = 'user'
                        """,
                        (rewrite_message_id, session["user_id"], character["id"], conversation_id),
                    ).fetchone()
                    if target is None:
                        database.rollback()
                        raise RuntimeError("未找到可编辑的用户消息")
                    database.execute(
                        "UPDATE messages SET content = ?, token_count = NULL WHERE id = ?",
                        (rewrite_content, rewrite_message_id),
                    )
                    database.execute(
                        "DELETE FROM messages WHERE conversation_id = ? AND user_id = ? AND id > ?",
                        (conversation_id, session["user_id"], rewrite_message_id),
                    )
                    cursor = database.execute(
                        "INSERT INTO messages (user_id, character_id, conversation_id, role, content) VALUES (?, ?, ?, 'assistant', ?)",
                        (session["user_id"], character["id"], conversation_id, final_text),
                    )
                    message_id = cursor.lastrowid
                    conversation = database.execute(
                        "SELECT title_custom FROM conversations WHERE id = ? AND user_id = ?",
                        (conversation_id, session["user_id"]),
                    ).fetchone()
                    has_previous_user = database.execute(
                        "SELECT 1 FROM messages WHERE conversation_id = ? AND role = 'user' AND id < ? LIMIT 1",
                        (conversation_id, rewrite_message_id),
                    ).fetchone()
                    if conversation and not conversation["title_custom"] and has_previous_user is None:
                        database.execute(
                            "UPDATE conversations SET title = ? WHERE id = ? AND user_id = ?",
                            (rewrite_content[:80], conversation_id, session["user_id"]),
                        )
                    database.execute(
                        "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                        (conversation_id, session["user_id"]),
                    )
                    database.commit()
                elif replace_message_id is None:
                    cursor = get_db().execute(
                        "INSERT INTO messages (user_id, character_id, conversation_id, role, content) VALUES (?, ?, ?, 'assistant', ?)",
                        (session["user_id"], character["id"], conversation_id, final_text),
                    )
                    message_id = cursor.lastrowid
                else:
                    get_db().execute(
                        "UPDATE messages SET content = ?, token_count = ?, created_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                        (
                            final_text,
                            usage["output_tokens"] or max(1, len(final_text)),
                            replace_message_id,
                            session["user_id"],
                        ),
                    )
                    invalidate_message_cache(replace_message_id)
                update_message_token_counts(
                    get_db(),
                    history_rows,
                    instructions,
                    usage,
                    message_id,
                    final_text,
                )
                get_db().execute(
                    "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                    (conversation_id, session["user_id"]),
                )
                get_db().commit()
                schedule_memory_update(conversation_id)
            yield f"data: {json.dumps({'type': 'done', 'messageId': message_id, 'userMessageId': user_message_id}, ensure_ascii=False)}\n\n"
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
    conversation_id = payload.get("conversationId")
    if character is None:
        return jsonify(error="未找到该角色"), 404
    if not content or len(content) > 4000:
        return jsonify(error="消息内容需为 1 至 4000 个字符"), 400
    if conversation_id is None:
        cursor = get_db().execute(
            "INSERT INTO conversations (user_id, character_id) VALUES (?, ?)",
            (session["user_id"], character_id),
        )
        conversation_id = cursor.lastrowid
    conversation = get_conversation(character_id, conversation_id)
    if conversation is None:
        return jsonify(error="未找到该对话"), 404

    database = get_db()
    user_cursor = database.execute(
        "INSERT INTO messages (user_id, character_id, conversation_id, role, content) VALUES (?, ?, ?, 'user', ?)",
        (session["user_id"], character_id, conversation_id, content),
    )
    database.execute(
        """
        UPDATE conversations
        SET title = CASE
                WHEN title_custom = 0 AND NOT EXISTS (
                    SELECT 1 FROM messages WHERE conversation_id = ? AND role = 'user' AND id < last_insert_rowid()
                ) THEN ?
                ELSE title
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (conversation_id, content[:80], conversation_id, session["user_id"]),
    )
    history, history_rows = conversation_context(
        database, conversation_id, character["language"]
    )
    database.commit()

    return stream_character_response(
        character,
        conversation_id,
        history,
        history_rows,
        user_message_id=user_cursor.lastrowid,
    )


@app.post("/api/characters/<int:character_id>/messages/<int:message_id>/rewrite")
@login_required
def rewrite_message(character_id, message_id):
    character = get_character(character_id)
    payload = request.get_json(silent=True) or {}
    content = str(payload.get("content", "")).strip()
    if character is None:
        return jsonify(error="未找到该角色"), 404
    if not content or len(content) > 4000:
        return jsonify(error="消息内容需为 1 至 4000 个字符"), 400
    target = get_db().execute(
        """
        SELECT id, conversation_id FROM messages
        WHERE id = ? AND user_id = ? AND character_id = ? AND role = 'user'
        """,
        (message_id, session["user_id"], character_id),
    ).fetchone()
    if target is None or target["conversation_id"] is None:
        return jsonify(error="未找到可编辑的用户消息"), 404
    latest_user_message_id = get_db().execute(
        "SELECT MAX(id) AS id FROM messages WHERE conversation_id = ? AND user_id = ? AND role = 'user'",
        (target["conversation_id"], session["user_id"]),
    ).fetchone()["id"]
    if latest_user_message_id != message_id:
        return jsonify(error="只能编辑该对话中最新发送的消息"), 409
    tail = get_db().execute(
        "SELECT MAX(id) AS id FROM messages WHERE conversation_id = ? AND user_id = ?",
        (target["conversation_id"], session["user_id"]),
    ).fetchone()["id"]
    history, history_rows = conversation_context(
        get_db(),
        target["conversation_id"],
        character["language"],
        {"id": message_id, "role": "user", "content": content, "token_count": None},
        before_message_id=message_id,
    )
    return stream_character_response(
        character,
        target["conversation_id"],
        history,
        history_rows,
        rewrite_message_id=message_id,
        rewrite_content=content,
        expected_tail_id=tail,
        user_message_id=message_id,
    )


@app.post("/api/characters/<int:character_id>/messages/<int:message_id>/regenerate")
@login_required
def regenerate_message(character_id, message_id):
    character = get_character(character_id)
    if character is None:
        return jsonify(error="未找到该角色"), 404
    target = get_db().execute(
        "SELECT id, conversation_id FROM messages WHERE id = ? AND user_id = ? AND character_id = ? AND role = 'assistant'",
        (message_id, session["user_id"], character_id),
    ).fetchone()
    if target is None:
        return jsonify(error="未找到可重新生成的回复"), 404
    language = normalize_prompt_language(character["language"])
    covered_column = memory_column(language, "covered_through_message_id")
    memory = get_db().execute(
        f"SELECT {covered_column} AS covered_through_message_id FROM conversation_memories WHERE conversation_id = ?",
        (target["conversation_id"],),
    ).fetchone()
    if memory and message_id <= memory["covered_through_message_id"]:
        return jsonify(error="该回复已进入长期记忆，无法重新生成"), 409
    history, history_rows = conversation_context(
        get_db(),
        target["conversation_id"],
        character["language"],
        before_message_id=message_id,
    )
    if not history or history[-1]["role"] != "user":
        return jsonify(error="该回复缺少对应的用户消息"), 409
    return stream_character_response(
        character,
        target["conversation_id"],
        history,
        history_rows,
        replace_message_id=message_id,
    )


@app.post("/api/characters/<int:character_id>/messages/<int:message_id>/translate")
@login_required
def translate_message(character_id, message_id):
    character = get_character(character_id)
    if character is None:
        return jsonify(error="未找到该角色"), 404
    message = get_assistant_message(character_id, message_id)
    if message is None:
        return jsonify(error="未找到可翻译的回复"), 404
    cached = get_db().execute(
        "SELECT translated_text FROM translation_cache WHERE user_id = ? AND message_id = ?",
        (session["user_id"], message_id),
    ).fetchone()
    context = get_db().execute(
        """
        SELECT role, content FROM messages
        WHERE conversation_id = ? AND id <= ?
        ORDER BY id DESC LIMIT 8
        """,
        (message["conversation_id"], message_id),
    ).fetchall()[::-1]

    @stream_with_context
    def generate():
        try:
            if cached is not None:
                translation = cached["translated_text"]
                yield f"data: {json.dumps({'type': 'delta', 'text': translation}, ensure_ascii=False)}\n\n"
            else:
                response = ark.responses.create(
                    model=TRANSLATION_MODEL,
                    instructions=TRANSLATION_PROMPTS[
                        normalize_prompt_language(character["language"])
                    ],
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
                    stream=True,
                    extra_body={"thinking": {"type": "disabled"}},
                )
                full_translation = []
                for event in response:
                    if event.type == "response.output_text.delta":
                        full_translation.append(event.delta)
                        yield f"data: {json.dumps({'type': 'delta', 'text': event.delta}, ensure_ascii=False)}\n\n"
                translation = "".join(full_translation).strip()
                if not translation:
                    raise RuntimeError("翻译服务未返回有效内容")
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
            yield f"data: {json.dumps({'type': 'done', 'messageId': message_id}, ensure_ascii=False)}\n\n"
        except Exception as error:
            app.logger.exception("Message translation failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(error)}, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


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
    voice_conversation_id = request.args.get("voiceConversationId", type=int)
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
    if voice_conversation_id is not None:
        if get_voice_conversation(character_id, voice_conversation_id) is None:
            return jsonify(error="未找到该语音通话"), 404
        language = realtime_config["language"]
        summary, recent = voice_conversation_context(
            get_db(), voice_conversation_id, language
        )
        context_parts = []
        display_name = (
            character_value(character, "name_en") or character["name"]
            if language == "en"
            else character["name"]
        )
        if summary:
            context_parts.append(
                f"此前语音通话的长期记忆摘要：\n{summary}"
                if language == "zh"
                else f"Long-term memory summary of the earlier voice conversation:\n{summary}"
            )
        if recent:
            transcript = "\n".join(
                f"{('用户' if row['role'] == 'user' else display_name) if language == 'zh' else ('User' if row['role'] == 'user' else display_name)}: {row['content']}"
                for row in recent
            )
            context_parts.append(
                f"当前语音会话最近的原文记录：\n{transcript}"
                if language == "zh"
                else f"Recent original transcript of the current voice conversation:\n{transcript}"
            )
        if context_parts:
            realtime_config["instructions"] += "\n\n" + "\n\n".join(context_parts)
    return jsonify(
        websocketUrl=realtime_websocket_url(),
        resourceId=os.getenv("DOUBAO_REALTIME_RESOURCE_ID", "volc.speech.dialog"),
        speakerId=speaker_id,
        language=realtime_config["language"],
        instructions=realtime_config["instructions"],
        characterId=character["id"],
        voiceConversationId=voice_conversation_id,
    )


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/media/avatars/<path:filename>")
def avatar_media(filename):
    content_types = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    content_type = content_types.get(Path(filename).suffix.lower())
    if content_type is None:
        return jsonify(error="头像文件格式无效"), 404
    response = send_from_directory(
        AVATAR_DIR, filename, max_age=31536000, mimetype=content_type
    )
    response.cache_control.public = True
    response.cache_control.immutable = True
    return response


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
    schedule_missing_persona_translations(get_db())


if __name__ == "__main__":
    port = int(os.getenv("CLIENT_PORT", "3002"))
    app.run(host=os.getenv("CLIENT_HOST", "127.0.0.1"), port=port, threaded=True)