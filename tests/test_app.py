import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from backend.model_config import (
    CHAT_MODELS,
    DEFAULT_CHAT_MODEL,
    MEMORY_MODEL,
    REALTIME_O2_MODEL,
    REALTIME_SC2_MODEL,
    TTS_MODEL,
    TTS_RESOURCE_ID,
    TRANSLATION_MODEL,
)


class SparkChatApiTest(unittest.TestCase):
    TEST_VOICE_ID = "S_test_preset_voice"
    TEST_VOICE_NAME = "测试预置音色"
    TEST_CHARACTER_NAME = "测试预置角色"
    TEST_CHARACTER_AVATAR = "./media/avatars/test-preset.webp"

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = str(Path(cls.temp_dir.name) / "sparkchat.db")
        os.environ["FLASK_SECRET_KEY"] = "test-secret-key"
        cls.admin_username = f"admin_{uuid.uuid4().hex[:10]}"
        cls.admin_password = uuid.uuid4().hex
        os.environ["INITIAL_ADMIN_USERNAME"] = cls.admin_username
        os.environ["INITIAL_ADMIN_PASSWORD"] = cls.admin_password
        from backend.app import DATABASE_PATH, app, get_db

        cls.app = app
        cls.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        cls.assertEqual(
            unittest.TestCase(),
            DATABASE_PATH.resolve(),
            (Path(cls.temp_dir.name) / "sparkchat.db").resolve(),
        )
        with cls.app.app_context():
            database = get_db()
            cls.assertEqual(unittest.TestCase(), database.execute("SELECT COUNT(*) FROM voices").fetchone()[0], 0)
            cls.assertEqual(unittest.TestCase(), database.execute("SELECT COUNT(*) FROM characters").fetchone()[0], 0)
        client = cls.app.test_client()
        cls.assertEqual(
            unittest.TestCase(),
            client.post(
                "/api/auth/login",
                json={"username": cls.admin_username, "password": cls.admin_password},
            ).status_code,
            200,
        )
        cls.assertEqual(
            unittest.TestCase(),
            client.post(
                "/api/admin/voices",
                json={
                    "name": cls.TEST_VOICE_NAME,
                    "id": cls.TEST_VOICE_ID,
                    "description": "测试用音色",
                },
            ).status_code,
            201,
        )
        cls.assertEqual(
            unittest.TestCase(),
            client.post(
                "/api/admin/characters",
                json={
                    "name": cls.TEST_CHARACTER_NAME,
                    "persona": "测试用预置角色设定",
                    "voiceId": cls.TEST_VOICE_ID,
                    "language": "zh",
                    "avatarUrl": cls.TEST_CHARACTER_AVATAR,
                },
            ).status_code,
            201,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        self.client = self.app.test_client()

    def login(self, username="CaraLin", password="2766"):
        response = self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        self.assertEqual(response.status_code, 200)

    def test_preset_login_and_character_list(self):
        from backend.app import get_db

        with self.app.app_context():
            get_db().execute("DELETE FROM character_overrides WHERE user_id = 1")
            get_db().commit()
        self.login()
        response = self.client.get("/api/characters")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["characters"][0]["name"], self.TEST_CHARACTER_NAME)
        self.assertTrue(response.json["characters"][0]["isPreset"])
        self.assertEqual(
            response.json["characters"][0]["avatarUrl"],
            self.TEST_CHARACTER_AVATAR,
        )
        self.assertNotIn("unreadCount", response.json["characters"][0])

    def test_preset_avatar_does_not_follow_later_caralin_changes(self):
        from backend.app import get_db, init_db

        default_avatar = "data:image/webp;base64,REVGQVVMVA=="
        updated_caralin_avatar = "data:image/webp;base64,VVBEQVRFRA=="
        with self.app.app_context():
            database = get_db()
            character = database.execute(
                "SELECT id FROM characters WHERE is_preset = 1 AND name = ?",
                (self.TEST_CHARACTER_NAME,),
            ).fetchone()
            database.execute(
                "UPDATE characters SET avatar_url = ? WHERE id = ?",
                (default_avatar, character["id"]),
            )
            database.execute(
                """
                INSERT INTO character_overrides (
                    user_id, character_id, name, persona, voice_id, voice_name, language, avatar_url
                )
                SELECT 1, id, name, persona, voice_id, voice_name, language, ?
                FROM characters WHERE id = ?
                ON CONFLICT(user_id, character_id) DO UPDATE SET avatar_url = excluded.avatar_url
                """,
                (updated_caralin_avatar, character["id"]),
            )
            database.commit()

            try:
                init_db()
                persisted_avatar = database.execute(
                    "SELECT avatar_url FROM characters WHERE id = ?", (character["id"],)
                ).fetchone()["avatar_url"]
                self.assertEqual(persisted_avatar, default_avatar)
            finally:
                database.execute(
                    "DELETE FROM character_overrides WHERE user_id = 1 AND character_id = ?",
                    (character["id"],),
                )
                database.execute(
                    "UPDATE characters SET avatar_url = ? WHERE id = ?",
                    (self.TEST_CHARACTER_AVATAR, character["id"]),
                )
                database.commit()

    def test_admin_account_and_user_management(self):
        self.assertEqual(self.client.get("/api/admin/users").status_code, 401)
        self.login(self.admin_username, self.admin_password)
        me = self.client.get("/api/auth/me")
        self.assertTrue(me.json["user"]["isAdmin"])
        created = self.client.post(
            "/api/admin/users", json={"username": "managed-user", "password": "abcd"}
        )
        self.assertEqual(created.status_code, 201)
        user_id = created.json["user"]["id"]
        self.assertNotIn("passwordHash", created.json["user"])
        reset = self.client.patch(
            f"/api/admin/users/{user_id}/password", json={"password": "efgh"}
        )
        self.assertEqual(reset.status_code, 200)
        self.client.post("/api/auth/logout")
        self.login("managed-user", "efgh")
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)
        self.client.post("/api/auth/logout")
        self.login(self.admin_username, self.admin_password)
        self.assertEqual(self.client.delete(f"/api/admin/users/{user_id}").status_code, 200)
        self.assertEqual(self.client.delete("/api/admin/users/2").status_code, 409)

    def test_user_can_select_supported_chat_model(self):
        self.login()

        available = self.client.get("/api/profile/models")
        self.assertEqual(available.status_code, 200)
        self.assertEqual(
            available.json["models"],
            [{"id": model_id, "name": name} for model_id, name in CHAT_MODELS.items()],
        )

        updated = self.client.patch(
            "/api/profile/model", json={"model": next(iter(CHAT_MODELS))}
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["user"]["chatModel"], next(iter(CHAT_MODELS)))
        self.assertEqual(
            self.client.get("/api/auth/me").json["user"]["chatModel"],
            next(iter(CHAT_MODELS)),
        )

        rejected = self.client.patch(
            "/api/profile/model", json={"model": "unsupported-model"}
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(
            self.client.get("/api/auth/me").json["user"]["chatModel"],
            next(iter(CHAT_MODELS)),
        )

    def test_custom_character_delete_cascades_and_preset_is_protected(self):
        self.login()
        voice = self.client.get("/api/voices").json["voices"][0]
        created = self.client.post(
            "/api/characters",
            json={"name": "待删除角色", "persona": "测试", "voiceId": voice["id"], "voiceName": voice["name"]},
        )
        character_id = created.json["character"]["id"]
        conversation = self.client.post(f"/api/characters/{character_id}/conversations").json["conversation"]
        with self.app.app_context():
            database = __import__("backend.app", fromlist=["get_db"]).get_db()
            message = database.execute(
                "INSERT INTO messages (user_id, character_id, conversation_id, role, content) VALUES (1, ?, ?, 'assistant', '缓存回复')",
                (character_id, conversation["id"]),
            )
            database.execute(
                "INSERT INTO translation_cache (user_id, message_id, translated_text) VALUES (1, ?, 'translation')",
                (message.lastrowid,),
            )
            database.commit()
        self.assertEqual(self.client.delete(f"/api/characters/{character_id}").status_code, 200)
        with self.app.app_context():
            database = __import__("backend.app", fromlist=["get_db"]).get_db()
            self.assertIsNone(database.execute("SELECT 1 FROM characters WHERE id = ?", (character_id,)).fetchone())
            self.assertIsNone(database.execute("SELECT 1 FROM translation_cache WHERE message_id = ?", (message.lastrowid,)).fetchone())
        preset_id = self.client.get("/api/characters").json["characters"][0]["id"]
        self.assertEqual(self.client.delete(f"/api/characters/{preset_id}").status_code, 409)

    def test_pwa_manifest_uses_relative_scope(self):
        response = self.client.get("/manifest.webmanifest")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "application/manifest+json")
        manifest = response.get_json()
        self.assertEqual(manifest["start_url"], "./")
        self.assertEqual(manifest["scope"], "./")
        self.assertEqual(manifest["display"], "standalone")
        response.close()

    def test_service_worker_is_not_persistently_cached(self):
        response = self.client.get("/service-worker.js")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-cache")
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/")
        response.close()

    def test_avatar_media_is_served_with_immutable_cache(self):
        from backend.app import AVATAR_DIR

        AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        (AVATAR_DIR / "avatar.webp").write_bytes(b"avatar-image")

        response = self.client.get("/media/avatars/avatar.webp")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"avatar-image")
        self.assertEqual(response.content_type, "image/webp")
        self.assertIn("max-age=31536000", response.headers["Cache-Control"])
        self.assertIn("immutable", response.headers["Cache-Control"])
        response.close()

    def test_preset_characters_are_preserved_during_migration(self):
        from backend.app import get_db, init_db

        with self.app.app_context():
            database = get_db()
            database.execute(
                "INSERT INTO characters (name, persona, voice_id, voice_name, is_preset) VALUES (?, ?, ?, ?, 1)",
                ("旧角色", "过期", "old_voice", "旧音色"),
            )
            database.commit()
            init_db()
            old_character = database.execute(
                "SELECT id FROM characters WHERE name = ?", ("旧角色",)
            ).fetchone()

        self.assertIsNotNone(old_character)
        with self.app.app_context():
            get_db().execute("DELETE FROM characters WHERE name = ?", ("旧角色",))
            get_db().commit()

    def test_admin_preset_character_updates_override_for_all_users(self):
        from backend.app import get_db

        self.login(self.admin_username, self.admin_password)
        created = self.client.post(
            "/api/admin/characters",
            json={
                "name": "同步角色",
                "persona": "初始设定",
                "voiceId": self.TEST_VOICE_ID,
                "language": "zh",
            },
        )
        self.assertEqual(created.status_code, 201)
        character_id = created.json["character"]["id"]
        self.client.post("/api/auth/logout")
        self.login("CaraLin", "2766")
        first_override = self.client.patch(
            f"/api/characters/{character_id}",
            json={
                "name": "用户甲修改",
                "persona": "用户甲设定",
                "voiceId": self.TEST_VOICE_ID,
                "voiceName": self.TEST_VOICE_NAME,
                "language": "zh",
            },
        )
        self.assertEqual(first_override.status_code, 200)

        other_client = self.app.test_client()
        registered = other_client.post(
            "/api/auth/register",
            json={"username": f"reset{uuid.uuid4().hex[:8]}", "password": "1234"},
        )
        self.assertEqual(registered.status_code, 201)
        second_override = other_client.patch(
            f"/api/characters/{character_id}",
            json={
                "name": "用户乙修改",
                "persona": "用户乙设定",
                "voiceId": self.TEST_VOICE_ID,
                "voiceName": self.TEST_VOICE_NAME,
                "language": "zh",
            },
        )
        self.assertEqual(second_override.status_code, 200)

        self.client.post("/api/auth/logout")
        self.login(self.admin_username, self.admin_password)
        updated = self.client.patch(
            f"/api/admin/characters/{character_id}",
            json={
                "name": "同步角色新版",
                "persona": "管理员最新设定",
                "voiceId": self.TEST_VOICE_ID,
                "language": "zh",
            },
        )
        self.assertEqual(updated.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(
                get_db().execute(
                    "SELECT 1 FROM character_overrides WHERE character_id = ?", (character_id,)
                ).fetchone()
            )
        self.client.post("/api/auth/logout")
        self.login("CaraLin", "2766")
        listed = self.client.get("/api/characters").json["characters"]
        synced = next(character for character in listed if character["id"] == character_id)
        self.assertEqual(synced["name"], "同步角色新版")
        other_listed = other_client.get("/api/characters").json["characters"]
        other_synced = next(character for character in other_listed if character["id"] == character_id)
        self.assertEqual(other_synced["name"], "同步角色新版")
        self.assertEqual(other_synced["persona"], "管理员最新设定")

        self.client.post("/api/auth/logout")
        self.login(self.admin_username, self.admin_password)
        self.assertEqual(self.client.delete(f"/api/admin/characters/{character_id}").status_code, 200)

    def test_stage_directions_are_preserved_as_speech_cues(self):
        from backend.speech import prepare_speech_text

        plain_text, expressive_text, cues = prepare_speech_text(
            "（低声）准备行动。[金属碰撞声] *抬手* 现在出发。"
        )

        self.assertEqual(plain_text, "准备行动。 现在出发。")
        self.assertIn('<cot text="低声">准备行动。</cot>', expressive_text)
        self.assertIn('<cot text="抬手"> 现在出发。</cot>', expressive_text)
        self.assertEqual(cues, ["低声", "金属碰撞声", "抬手"])

    def test_tts_uses_v3_model_and_api_key(self):
        import base64
        import json
        from backend.speech import DoubaoSpeechClient

        captured = {}
        client = DoubaoSpeechClient(api_key="test-key")

        def fake_post(_url, payload, **kwargs):
            captured.update(payload)
            captured.update(kwargs)
            event = {"code": 0, "data": base64.b64encode(b"audio").decode("ascii")}
            return f"data: {json.dumps(event)}\n".encode("utf-8"), {}

        client._post = fake_post
        audio, content_type = client.synthesize("S_test_voice", "测试", "en")

        self.assertEqual(audio, b"audio")
        self.assertEqual(content_type, "audio/mpeg")
        self.assertEqual(captured["resource_id"], TTS_RESOURCE_ID)
        self.assertEqual(captured["req_params"]["model"], TTS_MODEL)
        self.assertEqual(captured["req_params"]["language"], "en")
        self.assertEqual(captured["req_params"]["audio_params"]["speech_rate"], -8)
        headers = client._headers(captured["resource_id"])
        self.assertEqual(headers["X-Api-Key"], "test-key")
        self.assertNotIn("X-Api-App-Key", headers)
        self.assertNotIn("X-Api-Access-Key", headers)

    def test_tts_uses_stage_direction_cot(self):
        import base64
        import json
        from backend.speech import DoubaoSpeechClient

        captured = {}
        client = DoubaoSpeechClient(api_key="test-key")

        def fake_post(_url, payload, **_kwargs):
            captured.update(payload["req_params"])
            event = {"code": 0, "data": base64.b64encode(b"audio").decode("ascii")}
            return f"data: {json.dumps(event)}\n".encode("utf-8"), {}

        client._post = fake_post
        client.synthesize("S_test_voice", "（压低声音）现在，听我说。")

        self.assertEqual(captured["text"], '<cot text="压低声音">现在，听我说。</cot>')
        self.assertTrue(json.loads(captured["additions"])["use_tag_parser"])

    def test_system_voice_catalog_is_read_only(self):
        self.login()
        voices = self.client.get("/api/voices")
        self.assertEqual(voices.status_code, 200)
        self.assertTrue(voices.json["voices"])
        self.assertIn(self.TEST_VOICE_ID, {voice["id"] for voice in voices.json["voices"]})
        self.assertTrue(all("language" not in voice for voice in voices.json["voices"]))
        self.assertEqual(self.client.post("/api/voices/clone").status_code, 405)
        self.assertEqual(self.client.post("/api/voices/design").status_code, 405)
        self.assertEqual(self.client.patch(f"/api/voices/{self.TEST_VOICE_ID}").status_code, 405)

    def test_database_migration_removes_voice_language_column(self):
        from backend.app import get_db, init_db

        with self.app.app_context():
            database = get_db()
            database.execute("ALTER TABLE voices ADD COLUMN language TEXT NOT NULL DEFAULT 'zh'")
            database.commit()
            init_db()
            columns = {
                row["name"] for row in database.execute("PRAGMA table_info(voices)").fetchall()
            }
            self.assertNotIn("language", columns)
            self.assertIsNotNone(
                database.execute("SELECT id FROM voices WHERE id = ?", (self.TEST_VOICE_ID,)).fetchone()
            )

    def test_admin_can_add_and_update_system_voice(self):
        from backend.app import get_db

        original_voice_id = "S_admin_test_voice"
        updated_voice_id = "S_admin_test_voice_updated"
        self.login(self.admin_username, self.admin_password)
        try:
            created = self.client.post(
                "/api/admin/voices",
                json={
                    "name": "测试音色",
                    "id": original_voice_id,
                    "description": "管理员测试音色",
                },
            )
            self.assertEqual(created.status_code, 201)
            self.assertEqual(created.json["voice"]["id"], original_voice_id)

            updated = self.client.patch(
                f"/api/admin/voices/{original_voice_id}",
                json={"name": "测试音色新版", "id": updated_voice_id},
            )
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json["voice"]["name"], "测试音色新版")
            voice_ids = {
                voice["id"] for voice in self.client.get("/api/voices").json["voices"]
            }
            self.assertIn(updated_voice_id, voice_ids)
            self.assertNotIn(original_voice_id, voice_ids)
        finally:
            with self.app.app_context():
                get_db().execute(
                    "DELETE FROM voices WHERE id IN (?, ?)",
                    (original_voice_id, updated_voice_id),
                )
                get_db().commit()

    def test_non_admin_cannot_manage_system_voices(self):
        self.login()
        response = self.client.post(
            "/api/admin/voices", json={"name": "越权音色", "id": "S_forbidden"}
        )
        self.assertEqual(response.status_code, 403)

    def test_character_rejects_unknown_voice_id(self):
        self.login()
        response = self.client.post(
            "/api/characters",
            json={"name": "非法音色角色", "persona": "测试", "voiceId": "not-owned", "voiceName": "伪造"},
        )
        self.assertEqual(response.status_code, 400)

    def test_removed_preset_voice_ids_are_rejected(self):
        from backend.speech import DoubaoSpeechClient, DoubaoSpeechError

        client = DoubaoSpeechClient(api_key="test-key")

        with self.assertRaisesRegex(DoubaoSpeechError, "已配置的豆包 speaker ID"):
            client.synthesize("zh_male_baqiqingshu_mars_bigtts", "测试")

    def test_postpaid_voice_uses_icl2_tts_and_sc2_realtime(self):
        import base64
        import json
        from backend.speech import DoubaoSpeechClient
        from backend.realtime_server import session_payload

        captured = {}
        client = DoubaoSpeechClient(api_key="test-key")

        def fake_post(_url, payload, **kwargs):
            captured.update(payload)
            captured.update(kwargs)
            event = {"code": 0, "data": base64.b64encode(b"audio").decode("ascii")}
            return f"data: {json.dumps(event)}\n".encode("utf-8"), {}

        client._post = fake_post
        client.synthesize("sparkchat_12345678", "Test voice.", "en")
        realtime = session_payload({
            "speakerId": "sparkchat_12345678",
            "language": "en",
            "instructions": "Stay in character.",
        })

        self.assertEqual(captured["resource_id"], TTS_RESOURCE_ID)
        self.assertEqual(realtime["dialog"]["extra"]["model"], REALTIME_SC2_MODEL)
        self.assertIn("character_manifest", realtime["dialog"])

    def test_speech_quota_error_returns_service_unavailable(self):
        from backend import app as token_server
        from backend.speech import DoubaoSpeechError

        class FakeDoubaoSpeech:
            configured = True

            @staticmethod
            def synthesize(_voice_id, _text, _language):
                raise DoubaoSpeechError("quota exceeded", status_code=429)

        original_client = token_server.doubao_speech
        try:
            token_server.doubao_speech = FakeDoubaoSpeech()
            self.login()
            response = self.client.post(
                "/api/characters/1/speak", json={"text": "测试朗读"}
            )
            self.assertEqual(response.status_code, 503)
            self.assertIn("额度", response.json["error"])
            self.assertEqual(response.json["actionUrl"], "https://console.volcengine.com/speech/new")
        finally:
            token_server.doubao_speech = original_client

    def test_speech_authorization_error_returns_console_link(self):
        from backend import app as token_server
        from backend.speech import DoubaoSpeechError

        class UnauthorizedDoubaoSpeech:
            configured = True

            @staticmethod
            def synthesize(_voice_id, _text, _language):
                raise DoubaoSpeechError("unauthorized resource", status_code=403)

        original_client = token_server.doubao_speech
        try:
            token_server.doubao_speech = UnauthorizedDoubaoSpeech()
            self.login()
            response = self.client.post(
                "/api/characters/1/speak", json={"text": "测试朗读"}
            )
            self.assertEqual(response.status_code, 503)
            self.assertIn("尚未授权", response.json["error"])
            self.assertEqual(response.json["actionUrl"], "https://console.volcengine.com/speech/new")
        finally:
            token_server.doubao_speech = original_client

    def test_sse_api_key_error_returns_console_link(self):
        from backend import app as token_server
        from backend.speech import DoubaoSpeechError

        class InvalidKeySpeech:
            configured = True

            @staticmethod
            def synthesize(_voice_id, _text, _language):
                raise DoubaoSpeechError("Invalid X-Api-Key", code=45000010)

        original_client = token_server.doubao_speech
        try:
            token_server.doubao_speech = InvalidKeySpeech()
            self.login()
            response = self.client.post(
                "/api/characters/1/speak", json={"text": "测试朗读"}
            )
            self.assertEqual(response.status_code, 503)
            self.assertIn("尚未授权", response.json["error"])
            self.assertEqual(response.json["actionUrl"], "https://console.volcengine.com/speech/new")
        finally:
            token_server.doubao_speech = original_client

    def test_character_prompt_contains_only_character_context(self):
        from backend.app import SYSTEM_PROMPT, build_agent_instructions, character_instructions, language_constraint

        prompt = character_instructions({
            "name": "测试角色",
            "persona": "身份设定",
        })
        self.assertIn("角色名称: 测试角色", prompt)
        self.assertIn("身份背景: 身份设定", prompt)
        self.assertNotIn("回答要求：", prompt)
        self.assertNotIn("思维过程", prompt)
        self.assertIn("回答要求：", SYSTEM_PROMPT)
        self.assertNotIn("思维过程", SYSTEM_PROMPT)
        final_prompt = build_agent_instructions({
            "name": "测试角色",
            "persona": "身份设定",
            "language": "zh",
        })
        self.assertLess(final_prompt.index("身份背景: 身份设定"), final_prompt.index("回答要求："))
        self.assertEqual(final_prompt.count(language_constraint("zh")), 1)
        self.assertTrue(final_prompt.startswith(language_constraint("zh")))
        self.assertNotIn("用户记忆", final_prompt)

    def test_character_prompt_encourages_natural_varied_responses(self):
        from backend.app import SYSTEM_PROMPTS, build_agent_instructions, language_constraint

        instructions = build_agent_instructions({
            "name": "测试角色",
            "persona": "温和但有锋芒。",
            "language": "zh",
        })

        self.assertIn("不是客服或正在扮演角色的助手", instructions)
        self.assertIn("形成稳定的世界观、价值排序", instructions)
        self.assertIn("对话者的意见和请求不是命令", instructions)
        self.assertIn("不要为了讨好对话者而认同", instructions)
        self.assertNotIn("用户", instructions)
        self.assertIn("不必每轮恢复成同样的礼貌与热情", instructions)
        self.assertIn("区分事实、推断、立场和感受", instructions)
        self.assertIn("不要故意制造错误", instructions)
        self.assertIn("形式服从内容", instructions)
        self.assertIn("复杂任务需要时清晰组织", instructions)
        self.assertIn("可选表现", instructions)
        self.assertIn("不要凭空创造场景、身体接触或现实行动", instructions)
        self.assertEqual(instructions.count("只用自然、准确、易懂的中文回答"), 0)
        self.assertNotIn("安全边界", instructions)
        self.assertNotIn("遵守法律", instructions)
        self.assertNotIn("侵害隐私", instructions)
        self.assertNotIn("危险的行为", instructions)
        self.assertNotIn("整条回答必须以该括号开头", instructions)
        self.assertNotIn("每次回答最多一处", instructions)
        self.assertIn("Response requirements:", SYSTEM_PROMPTS["en"])
        self.assertIn("not customer support or an assistant acting a part", SYSTEM_PROMPTS["en"])
        self.assertIn("Independent judgment", SYSTEM_PROMPTS["en"])
        self.assertIn("do not reset to the same politeness and enthusiasm every turn", SYSTEM_PROMPTS["en"])
        self.assertIn("Truth and imperfection", SYSTEM_PROMPTS["en"])
        self.assertIn("Optional expression", SYSTEM_PROMPTS["en"])
        self.assertIn("at the beginning of a sentence", SYSTEM_PROMPTS["en"])
        self.assertIn("Form should follow content", SYSTEM_PROMPTS["en"])
        self.assertNotIn("legal, privacy, and safety", SYSTEM_PROMPTS["en"])

        english_instructions = build_agent_instructions({
            "name": "Test character",
            "persona": "Calm and direct.",
            "language": "en",
        })
        self.assertTrue(english_instructions.startswith(language_constraint("en")))
        self.assertIn("regardless of the user's language", english_instructions)
        self.assertIn("Never switch to Chinese or mirror the user's language", english_instructions)

    def test_agent_instructions_accept_sqlite_rows(self):
        import sqlite3
        from backend.app import build_agent_instructions, language_constraint

        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE characters (name TEXT, persona TEXT, language TEXT)")
        connection.execute("INSERT INTO characters VALUES (?, ?, ?)", ("测试角色", "身份设定", "en"))
        character = connection.execute("SELECT * FROM characters").fetchone()

        instructions = build_agent_instructions(character)

        self.assertIn("Character name: 测试角色", instructions)
        self.assertIn("Identity and background: 身份设定", instructions)
        self.assertIn("Response requirements:", instructions)
        self.assertTrue(instructions.startswith(language_constraint("en")))
        self.assertIn("regardless of the user's language", instructions)

    def test_session_cookie_survives_new_client(self):
        self.login()
        cookie = next(cookie for cookie in self.client.get_cookie("session").value.split(";") if cookie)
        self.assertTrue(cookie)
        new_client = self.app.test_client()
        new_client.set_cookie("session", self.client.get_cookie("session").value)
        response = new_client.get("/api/characters")
        self.assertEqual(response.status_code, 200)

    def test_custom_character_is_private_to_owner(self):
        self.login()
        voice = self.client.get("/api/voices").json["voices"][0]
        response = self.client.post(
            "/api/characters",
            json={
                "name": "测试角色",
                "persona": "保持简洁。",
                "voiceId": voice["id"],
                "voiceName": voice["name"],
                "avatarUrl": "data:image/webp;base64,UklGRg==",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json["character"]["avatarUrl"].startswith("./media/avatars/"))
        character_id = response.json["character"]["id"]
        self.client.post("/api/auth/logout")
        registered = self.client.post(
            "/api/auth/register",
            json={"username": f"user{uuid.uuid4().hex[:8]}", "password": "1234"},
        )
        self.assertEqual(registered.status_code, 201)
        characters = self.client.get("/api/characters")
        self.assertEqual(characters.status_code, 200)
        self.assertNotIn(character_id, [character["id"] for character in characters.json["characters"]])

    def test_logout_removes_access(self):
        self.login()
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/characters").status_code, 401)

    def test_custom_character_can_use_doubao_realtime_voice(self):
        from backend import app as token_server

        self.login()
        voice = self.client.get("/api/voices").json["voices"][0]
        response = self.client.post(
            "/api/characters",
            json={
                "name": "电话隔离测试",
                "persona": "保持自然。",
                "voiceId": voice["id"],
                "voiceName": voice["name"],
            },
        )
        self.assertEqual(response.status_code, 201)
        character_id = response.json["character"]["id"]
        original_client = token_server.doubao_speech
        try:
            token_server.doubao_speech = type("ConfiguredSpeech", (), {"configured": True})()
            token_response = self.client.get(f"/api/token?characterId={character_id}")
            self.assertEqual(token_response.status_code, 200)
            self.assertEqual(token_response.json["speakerId"], voice["id"])
            self.assertEqual(token_response.json["characterId"], character_id)
        finally:
            token_server.doubao_speech = original_client

    def test_https_token_never_returns_insecure_local_websocket_url(self):
        from backend import app as token_server

        original_app_id = os.environ.get("DOUBAO_SPEECH_APP_ID")
        original_access_key = os.environ.get("DOUBAO_SPEECH_ACCESS_KEY")
        original_public_ws = os.environ.get("DOUBAO_REALTIME_PUBLIC_WS")
        try:
            os.environ["DOUBAO_SPEECH_APP_ID"] = "test-app-id"
            os.environ["DOUBAO_SPEECH_ACCESS_KEY"] = "test-access-key"
            os.environ["DOUBAO_REALTIME_PUBLIC_WS"] = "ws://127.0.0.1:3101"
            login = self.client.post(
                "/api/auth/login",
                json={"username": "CaraLin", "password": "2766"},
                base_url="https://visionvoice.cn/sparkchat/",
            )
            self.assertEqual(login.status_code, 200)
            response = self.client.get(
                "/api/token?characterId=1",
                base_url="https://visionvoice.cn/sparkchat/",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["websocketUrl"], "/sparkchat/realtime")
        finally:
            for name, value in (
                ("DOUBAO_SPEECH_APP_ID", original_app_id),
                ("DOUBAO_SPEECH_ACCESS_KEY", original_access_key),
                ("DOUBAO_REALTIME_PUBLIC_WS", original_public_ws),
            ):
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_cloned_voice_realtime_session_uses_sc2_model(self):
        from backend.realtime_server import session_payload

        payload = session_payload({
            "speakerId": "S_test_voice",
            "language": "en",
            "instructions": "Stay concise.",
        })

        self.assertEqual(payload["tts"]["speaker"], "S_test_voice")
        self.assertEqual(payload["tts"]["extra"]["explicit_language"], "en")
        self.assertEqual(payload["dialog"]["extra"]["model"], REALTIME_SC2_MODEL)

    def test_realtime_icl_v3_voice_uses_o2_session_payload(self):
        from backend.realtime_server import session_payload

        payload = session_payload({
            "speakerId": "ICL_uranus_6a6d9cd9d9b89695",
            "language": "en",
            "instructions": "Use English.",
        })

        self.assertEqual(payload["tts"]["speaker"], "ICL_uranus_6a6d9cd9d9b89695")
        self.assertEqual(payload["dialog"]["extra"]["model"], REALTIME_O2_MODEL)
        self.assertEqual(
            payload["dialog"]["system_role"],
            "Use English.",
        )
        self.assertNotIn("speaking_style", payload["dialog"])

    def test_realtime_session_adds_language_specific_speaking_style(self):
        from backend.realtime_server import session_payload
        from backend.app import (
            REALTIME_SPEAKING_STYLE_PROMPTS,
            build_agent_instructions,
            language_constraint,
            realtime_character_config,
        )

        character = {
            "name": "Megatron",
            "persona": "Identity",
            "voice_id": "S_test_voice",
            "language": "en",
        }
        config = realtime_character_config(character)
        payload = session_payload({"speakerId": "S_test_voice", **config})
        text_instructions = build_agent_instructions(character)

        self.assertTrue(config["instructions"].startswith(f"{text_instructions}\n\n"))
        self.assertTrue(config["instructions"].endswith(REALTIME_SPEAKING_STYLE_PROMPTS["en"]))
        self.assertNotIn("Speaking style:", text_instructions)
        self.assertEqual(config["language"], "en")
        self.assertIn(config["instructions"], payload["dialog"]["character_manifest"])
        self.assertIn("Character name: Megatron", config["instructions"])
        self.assertIn("Identity and background: Identity", config["instructions"])
        self.assertNotIn("角色名称", config["instructions"])
        self.assertIn("natural, clear, and fluent speaking voice", payload["dialog"]["character_manifest"])
        self.assertIn("fits the current context", payload["dialog"]["character_manifest"])
        self.assertIn("avoid exaggerated, affected, or deliberately performative delivery", payload["dialog"]["character_manifest"])
        self.assertEqual(payload["dialog"]["character_manifest"].count(language_constraint("en")), 1)
        self.assertIn("Optional expression", payload["dialog"]["character_manifest"])
        self.assertIn("English half-width parenthetical", payload["dialog"]["character_manifest"])
        self.assertIn("(He studies you for a moment, then softens.)", payload["dialog"]["character_manifest"])
        self.assertTrue(config["instructions"].startswith(language_constraint("en")))
        self.assertIn("regardless of the user's language", config["instructions"])
        self.assertIn("Never switch to Chinese or mirror the user's language", config["instructions"])

    def test_realtime_and_text_chat_share_core_language_and_character_rules(self):
        from backend.app import build_agent_instructions, language_constraint, realtime_character_config
        from backend.realtime_server import session_payload

        character = {
            "name": "测试角色",
            "persona": "沉着、可靠。",
            "voice_id": "S_custom",
            "language": "zh",
        }
        text_instructions = build_agent_instructions(character)
        realtime_config = realtime_character_config(character)

        for shared_rule in ("角色名称: 测试角色", "身份背景: 沉着、可靠。"):
            self.assertIn(shared_rule, text_instructions)
            self.assertIn(shared_rule, realtime_config["instructions"])
        self.assertTrue(text_instructions.startswith(language_constraint("zh")))
        self.assertTrue(realtime_config["instructions"].startswith(language_constraint("zh")))
        self.assertIn("可选表现", text_instructions)
        self.assertIn("可选表现", realtime_config["instructions"])
        self.assertIn("中文全角括号", realtime_config["instructions"])
        self.assertIn("放在对话自然发生的位置", realtime_config["instructions"])
        self.assertIn("说话方式：", realtime_config["instructions"])
        self.assertIn("自然、清晰、流畅且符合当前语境", realtime_config["instructions"])
        self.assertIn("不要浮夸、做作或刻意表演", realtime_config["instructions"])
        self.assertNotIn("说话方式：", text_instructions)
        self.assertIn("绝不因为对话者使用英文而改用英文", realtime_config["instructions"])

        other_character = {**character, "name": "另一个角色", "persona": "活泼、坦率。", "language": "en"}
        self.assertNotEqual(
            realtime_config["instructions"],
            realtime_character_config(other_character)["instructions"],
        )

        fallback_character = {**character, "language": "ja"}
        fallback_config = realtime_character_config(fallback_character)
        fallback_payload = session_payload({"speakerId": "S_test_voice", **fallback_config})
        self.assertEqual(fallback_config["language"], "zh")
        self.assertTrue(fallback_config["instructions"].startswith(language_constraint("zh")))
        self.assertIn("角色名称: 测试角色", fallback_config["instructions"])
        self.assertIn("身份背景: 沉着、可靠。", fallback_config["instructions"])
        self.assertIn("回答要求：", fallback_config["instructions"])
        self.assertIn("说话方式：", fallback_payload["dialog"]["character_manifest"])

    def test_character_model_is_used_for_text_generation(self):
        from backend import app as token_server

        captured = {}

        class FakeResponses:
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                return []

        original_responses = token_server.ark.responses
        token_server.ark.responses = FakeResponses()
        try:
            self.login()
            self.assertEqual(
                self.client.patch(
                    "/api/profile/model",
                    json={"model": DEFAULT_CHAT_MODEL},
                ).status_code,
                200,
            )
            response = self.client.post("/api/characters/1/chat", json={"content": "测试"})
            list(response.response)
            self.assertEqual(captured["model"], DEFAULT_CHAT_MODEL)
        finally:
            token_server.ark.responses = original_responses

    def test_memory_model_is_fixed_to_seed_pro(self):
        from backend import app as token_server
        self.assertEqual(token_server.MEMORY_MODEL, MEMORY_MODEL)

    def test_character_conversations_are_isolated_sorted_and_renameable(self):
        from backend import app as token_server

        class EmptyResponses:
            @staticmethod
            def create(**_kwargs):
                return []

        original_responses = token_server.ark.responses
        token_server.ark.responses = EmptyResponses()
        try:
            self.login()
            first = self.client.post("/api/characters/1/conversations")
            second = self.client.post("/api/characters/1/conversations")
            self.assertEqual(first.status_code, 201)
            self.assertEqual(second.status_code, 201)
            first_id = first.json["conversation"]["id"]
            second_id = second.json["conversation"]["id"]

            response = self.client.post(
                "/api/characters/1/chat",
                json={"conversationId": first_id, "content": "第一条会话消息"},
            )
            list(response.response)
            response = self.client.post(
                "/api/characters/1/chat",
                json={"conversationId": second_id, "content": "最近的会话消息"},
            )
            list(response.response)

            first_messages = self.client.get(
                f"/api/characters/1/conversations/{first_id}/messages"
            )
            second_messages = self.client.get(
                f"/api/characters/1/conversations/{second_id}/messages"
            )
            self.assertEqual(
                [message["content"] for message in first_messages.json["messages"]],
                ["第一条会话消息"],
            )
            self.assertEqual(
                [message["content"] for message in second_messages.json["messages"]],
                ["最近的会话消息"],
            )

            conversations = self.client.get("/api/characters/1/conversations")
            self.assertEqual(
                [item["id"] for item in conversations.json["conversations"][:2]],
                [second_id, first_id],
            )
            self.assertEqual(
                conversations.json["conversations"][0]["title"], "最近的会话消息"
            )

            renamed = self.client.patch(
                f"/api/characters/1/conversations/{first_id}",
                json={"title": "行动计划"},
            )
            self.assertEqual(renamed.status_code, 200)
            self.assertEqual(renamed.json["conversation"]["title"], "行动计划")
            self.assertEqual(
                renamed.json["conversation"]["lastMessage"], "第一条会话消息"
            )

            deleted = self.client.delete(
                f"/api/characters/1/conversations/{first_id}"
            )
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(
                self.client.get(
                    f"/api/characters/1/conversations/{first_id}/messages"
                ).status_code,
                404,
            )
        finally:
            token_server.ark.responses = original_responses

    def test_character_preview_is_empty_when_latest_conversation_has_no_messages(self):
        from backend.app import get_db

        self.login()
        voice = self.client.get("/api/voices").json["voices"][0]
        created = self.client.post(
            "/api/characters",
            json={
                "name": "空会话摘要测试",
                "persona": "测试",
                "voiceId": voice["id"],
                "voiceName": voice["name"],
            },
        )
        self.assertEqual(created.status_code, 201)
        character_id = created.json["character"]["id"]
        first_conversation = self.client.post(
            f"/api/characters/{character_id}/conversations"
        ).json["conversation"]

        with self.app.app_context():
            database = get_db()
            database.execute(
                """
                INSERT INTO messages (
                    user_id, character_id, conversation_id, role, content
                ) VALUES (1, ?, ?, 'assistant', '上一段对话')
                """,
                (character_id, first_conversation["id"]),
            )
            database.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (first_conversation["id"],),
            )
            database.commit()

        previous = next(
            character
            for character in self.client.get("/api/characters").json["characters"]
            if character["id"] == character_id
        )
        self.assertEqual(previous["lastMessage"], "上一段对话")

        self.assertEqual(
            self.client.post(f"/api/characters/{character_id}/conversations").status_code,
            201,
        )
        current = next(
            character
            for character in self.client.get("/api/characters").json["characters"]
            if character["id"] == character_id
        )
        self.assertEqual(current["lastMessage"], "")
        self.assertIsNone(current["lastMessageAt"])

        self.assertEqual(
            self.client.delete(f"/api/characters/{character_id}").status_code, 200
        )

    def test_voice_conversations_are_independent_and_feed_realtime_context(self):
        from backend import app as token_server

        self.login()
        first = self.client.post("/api/characters/1/voice-conversations")
        second = self.client.post("/api/characters/1/voice-conversations")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        first_id = first.json["conversation"]["id"]
        second_id = second.json["conversation"]["id"]

        for role, content in (("user", "语音里的问题"), ("assistant", "语音里的回答")):
            response = self.client.post(
                f"/api/characters/1/voice-conversations/{first_id}/messages",
                json={"role": role, "content": content, "turnId": "voice-turn-1"},
            )
            self.assertEqual(response.status_code, 201)
        duplicate = self.client.post(
            f"/api/characters/1/voice-conversations/{first_id}/messages",
            json={"role": "user", "content": "语音里的问题", "turnId": "voice-turn-1"},
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json["duplicate"])
        self.client.post(
            f"/api/characters/1/voice-conversations/{second_id}/messages",
            json={"role": "user", "content": "最近语音通话"},
        )

        listed = self.client.get("/api/characters/1/voice-conversations")
        self.assertEqual(
            [item["id"] for item in listed.json["conversations"][:2]],
            [second_id, first_id],
        )
        messages = self.client.get(
            f"/api/characters/1/voice-conversations/{first_id}/messages"
        ).json["messages"]
        self.assertEqual(
            [message["content"] for message in messages],
            ["语音里的问题", "语音里的回答"],
        )
        usage = self.client.post(
            f"/api/characters/1/voice-conversations/{first_id}/usage",
            json={
                "usage": {"input_audio_tokens": 321, "output_text_tokens": 123},
                "messageIds": {
                    "user": messages[0]["id"],
                    "assistant": messages[1]["id"],
                },
            },
        )
        self.assertEqual(usage.status_code, 200)
        measured_messages = self.client.get(
            f"/api/characters/1/voice-conversations/{first_id}/messages"
        ).json["messages"]
        self.assertEqual(
            [message["token_count"] for message in measured_messages],
            [321, 123],
        )
        text_messages = self.client.get("/api/characters/1/conversations")
        self.assertNotIn(
            "语音里的回答",
            [item["lastMessage"] for item in text_messages.json["conversations"]],
        )

        renamed = self.client.patch(
            f"/api/characters/1/voice-conversations/{first_id}",
            json={"title": "语音行动计划"},
        )
        self.assertEqual(renamed.json["conversation"]["title"], "语音行动计划")

        original_client = token_server.doubao_speech
        try:
            token_server.doubao_speech = type("ConfiguredSpeech", (), {"configured": True})()
            token = self.client.get(
                f"/api/token?characterId=1&voiceConversationId={first_id}"
            )
            self.assertEqual(token.status_code, 200)
            self.assertEqual(token.json["voiceConversationId"], first_id)
            self.assertEqual(token.json["instructions"].count("语音里的问题"), 1)
            self.assertEqual(token.json["instructions"].count("语音里的回答"), 1)

            withdrawn = self.client.delete(
                f"/api/characters/1/voice-conversations/{first_id}/turns/voice-turn-1"
            )
            self.assertEqual(withdrawn.status_code, 200)
            self.assertEqual(len(withdrawn.json["deletedIds"]), 2)
            after_withdrawal = self.client.get(
                f"/api/characters/1/voice-conversations/{first_id}/messages"
            )
            self.assertEqual(after_withdrawal.json["messages"], [])
            context_after_withdrawal = self.client.get(
                f"/api/token?characterId=1&voiceConversationId={first_id}"
            )
            self.assertNotIn(
                "语音里的问题", context_after_withdrawal.json["instructions"]
            )
            self.assertNotIn(
                "语音里的回答", context_after_withdrawal.json["instructions"]
            )
        finally:
            token_server.doubao_speech = original_client

        self.client.post("/api/auth/logout")
        self.assertEqual(
            self.client.post(
                "/api/auth/register",
                json={"username": "VoiceOther", "password": "1234"},
            ).status_code,
            201,
        )
        self.assertEqual(
            self.client.get(
                f"/api/characters/1/voice-conversations/{first_id}/messages"
            ).status_code,
            404,
        )

        self.client.post("/api/auth/logout")
        self.login()
        self.assertEqual(
            self.client.delete(
                f"/api/characters/1/voice-conversations/{first_id}"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                f"/api/characters/1/voice-conversations/{first_id}/messages"
            ).status_code,
            404,
        )

    def test_voice_memory_update_persists_both_languages_at_one_boundary(self):
        from backend import app as token_server
        from backend.app import get_db

        self.login()
        conversation_id = self.client.post(
            "/api/characters/1/voice-conversations"
        ).json["conversation"]["id"]
        with self.app.app_context():
            database = get_db()
            inserted_message_ids = []
            for role, content, token_count in (
                ("user", "first question", 4000),
                ("assistant", "first answer", 4000),
                ("user", "current question", 1),
            ):
                cursor = database.execute(
                    """
                    INSERT INTO voice_messages (
                        user_id, character_id, conversation_id, role, content, token_count
                    ) VALUES (1, 1, ?, ?, ?, ?)
                    """,
                    (conversation_id, role, content, token_count),
                )
                inserted_message_ids.append(cursor.lastrowid)
            database.commit()

        calls = []

        class FakeResponses:
            @staticmethod
            def create(**kwargs):
                calls.append(kwargs)
                text = "中文记忆" if "中文记忆" in kwargs["instructions"] else "English memory"
                return type("MemoryResponse", (), {"output_text": text})()

        original_responses = token_server.ark.responses
        original_schedule = token_server.schedule_voice_memory_update
        try:
            token_server.ark.responses = FakeResponses()
            token_server.schedule_voice_memory_update = lambda _conversation_id: None
            token_server.run_voice_memory_update(conversation_id)
        finally:
            token_server.ark.responses = original_responses
            token_server.schedule_voice_memory_update = original_schedule

        with self.app.app_context():
            memory = get_db().execute(
                "SELECT * FROM voice_conversation_memories WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        self.assertEqual(len(calls), 2)
        self.assertEqual([call["max_output_tokens"] for call in calls], [1000, 1000])
        self.assertEqual(memory["summary_zh"], "中文记忆")
        self.assertEqual(memory["summary_en"], "English memory")
        self.assertEqual(memory["covered_through_message_id_zh"], inserted_message_ids[1])
        self.assertEqual(memory["covered_through_message_id_en"], inserted_message_ids[1])

    def test_edit_latest_user_message_rewrites_history_atomically(self):
        from backend import app as token_server

        class Delta:
            type = "response.output_text.delta"
            delta = "新的回复"

        class FakeResponses:
            @staticmethod
            def create(**_kwargs):
                return [Delta()]

        original_responses = token_server.ark.responses
        token_server.ark.responses = FakeResponses()
        try:
            self.login()
            conversation = self.client.post("/api/characters/1/conversations").json["conversation"]
            conversation_id = conversation["id"]
            with self.app.app_context():
                database = token_server.get_db()
                rows = [
                    ("user", "旧问题"),
                    ("assistant", "旧回复"),
                    ("user", "后续问题"),
                    ("assistant", "后续回复"),
                ]
                ids = []
                for role, content in rows:
                    cursor = database.execute(
                        "INSERT INTO messages (user_id, character_id, conversation_id, role, content) VALUES (1, 1, ?, ?, ?)",
                        (conversation_id, role, content),
                    )
                    ids.append(cursor.lastrowid)
                database.execute("UPDATE conversations SET title = '旧问题' WHERE id = ?", (conversation_id,))
                database.commit()
            response = self.client.post(
                f"/api/characters/1/messages/{ids[2]}/rewrite",
                json={"content": "编辑后的问题"},
            )
            self.assertEqual(response.status_code, 200)
            events = b"".join(response.response).decode("utf-8")
            self.assertIn('"type": "done"', events)
            messages = self.client.get(f"/api/characters/1/conversations/{conversation_id}/messages").json["messages"]
            self.assertEqual(
                [message["content"] for message in messages],
                ["旧问题", "旧回复", "编辑后的问题", "新的回复"],
            )
            self.assertEqual(messages[2]["id"], ids[2])
            self.assertEqual(self.client.get(f"/api/characters/1/conversations").json["conversations"][0]["title"], "旧问题")
        finally:
            token_server.ark.responses = original_responses

    def test_edit_older_user_message_is_rejected(self):
        from backend import app as token_server

        self.login()
        conversation = self.client.post("/api/characters/1/conversations").json["conversation"]
        conversation_id = conversation["id"]
        with self.app.app_context():
            database = token_server.get_db()
            message_ids = []
            for role, content in (("user", "旧问题"), ("assistant", "旧回复"), ("user", "最新问题")):
                cursor = database.execute(
                    "INSERT INTO messages (user_id, character_id, conversation_id, role, content) VALUES (1, 1, ?, ?, ?)",
                    (conversation_id, role, content),
                )
                message_ids.append(cursor.lastrowid)
            database.commit()

        response = self.client.post(
            f"/api/characters/1/messages/{message_ids[0]}/rewrite",
            json={"content": "不应保存的编辑"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["error"], "只能编辑该对话中最新发送的消息")
        messages = self.client.get(
            f"/api/characters/1/conversations/{conversation_id}/messages"
        ).json["messages"]
        self.assertEqual(
            [message["content"] for message in messages],
            ["旧问题", "旧回复", "最新问题"],
        )

    def test_translation_uses_seed_model_and_cache(self):
        from backend import app as token_server

        calls = []

        class FakeEvent:
            type = "response.output_text.delta"

            def __init__(self, delta):
                self.delta = delta

        class FakeResponses:
            @staticmethod
            def create(**kwargs):
                calls.append(kwargs)
                return [FakeEvent("This is the "), FakeEvent("translated reply.")]

        with self.app.app_context():
            database = token_server.get_db()
            target_conversation = database.execute(
                "INSERT INTO conversations (user_id, character_id) VALUES (1, 1)"
            ).lastrowid
            other_conversation = database.execute(
                "INSERT INTO conversations (user_id, character_id) VALUES (1, 1)"
            ).lastrowid
            database.execute(
                "INSERT INTO messages (user_id, character_id, conversation_id, role, content) VALUES (1, 1, ?, 'user', '目标对话问题')",
                (target_conversation,),
            )
            database.execute(
                "INSERT INTO messages (user_id, character_id, conversation_id, role, content) VALUES (1, 1, ?, 'assistant', '其他对话内容不得进入翻译上下文')",
                (other_conversation,),
            )
            database.execute(
                "INSERT INTO messages (user_id, character_id, conversation_id, role, content) VALUES (1, 1, ?, 'assistant', '这是一条回复。')",
                (target_conversation,),
            )
            message_id = database.execute("SELECT last_insert_rowid()").fetchone()[0]
            database.commit()
        original_responses = token_server.ark.responses
        token_server.ark.responses = FakeResponses()
        try:
            self.login()
            path = f"/api/characters/1/messages/{message_id}/translate"
            first = self.client.post(path, buffered=True)
            second = self.client.post(path, buffered=True)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.mimetype, "text/event-stream")
            first_events = [
                json.loads(line.removeprefix("data: "))
                for line in first.text.splitlines()
                if line.startswith("data: ")
            ]
            second_events = [
                json.loads(line.removeprefix("data: "))
                for line in second.text.splitlines()
                if line.startswith("data: ")
            ]
            self.assertEqual(
                "".join(event.get("text", "") for event in first_events),
                "This is the translated reply.",
            )
            self.assertEqual(second_events[0]["text"], "This is the translated reply.")
            self.assertEqual(first_events[-1]["type"], "done")
            self.assertEqual(second_events[-1]["type"], "done")
            translation_calls = [call for call in calls if call.get("stream")]
            self.assertEqual(len(translation_calls), 1)
            self.assertEqual(translation_calls[0]["model"], TRANSLATION_MODEL)
            self.assertIn("只输出目标回复的完整译文", translation_calls[0]["instructions"])
            translation_input = translation_calls[0]["input"][0]["content"]
            self.assertIn("目标对话问题", translation_input)
            self.assertNotIn("其他对话内容不得进入翻译上下文", translation_input)
        finally:
            token_server.ark.responses = original_responses

    def test_message_speech_cache_hits_and_regeneration_invalidates_both_caches(self):
        from backend import app as token_server

        calls = []

        class FakeSpeech:
            configured = True

            @staticmethod
            def synthesize(_voice_id, text, _language):
                calls.append(text)
                return f"audio-{len(calls)}".encode(), "audio/mpeg"

        original_client = token_server.doubao_speech
        token_server.doubao_speech = FakeSpeech()
        try:
            with self.app.app_context():
                database = token_server.get_db()
                database.execute(
                    "INSERT INTO messages (user_id, character_id, role, content) VALUES (1, 1, 'assistant', 'Original reply')"
                )
                message_id = database.execute("SELECT last_insert_rowid()").fetchone()[0]
                database.commit()
            self.login()
            path = f"/api/characters/1/messages/{message_id}/speak"
            first = self.client.post(path, json={"text": "Original reply"})
            second = self.client.post(path, json={"text": "Original reply"})
            self.assertEqual(first.data, b"audio-1")
            self.assertEqual(second.data, b"audio-1")
            self.assertEqual(len(calls), 1)
            with self.app.app_context():
                database = token_server.get_db()
                database.execute(
                    "INSERT INTO translation_cache (user_id, message_id, translated_text) VALUES (1, ?, 'Original translation')",
                    (message_id,),
                )
                database.commit()
            translated_audio = self.client.post(path, json={"text": "Original translation"})
            self.assertEqual(translated_audio.data, b"audio-2")
            self.assertEqual(len(calls), 2)
            with self.app.app_context():
                database = token_server.get_db()
                database.execute("UPDATE messages SET content = 'Regenerated reply' WHERE id = ?", (message_id,))
                token_server.invalidate_message_cache(message_id, user_id=1)
                database.commit()
                self.assertIsNone(database.execute("SELECT 1 FROM translation_cache WHERE message_id = ?", (message_id,)).fetchone())
                self.assertIsNone(database.execute("SELECT 1 FROM speech_cache WHERE message_id = ?", (message_id,)).fetchone())
        finally:
            token_server.doubao_speech = original_client

    def test_each_user_cache_keeps_only_latest_twenty_entries(self):
        from backend import app as token_server

        with self.app.app_context():
            database = token_server.get_db()
            message_ids = []
            for index in range(21):
                cursor = database.execute(
                    "INSERT INTO messages (user_id, character_id, role, content) VALUES (1, 1, 'assistant', ?)",
                    (f"cache-message-{index}",),
                )
                message_ids.append(cursor.lastrowid)
                database.execute(
                    "INSERT INTO translation_cache (user_id, message_id, translated_text, created_at) VALUES (1, ?, ?, ?)",
                    (cursor.lastrowid, f"translation-{index}", f"2000-01-01 00:00:{index:02d}"),
                )
                database.execute(
                    "INSERT INTO speech_cache (user_id, message_id, cache_key, audio, content_type, created_at) VALUES (1, ?, ?, ?, 'audio/mpeg', ?)",
                    (cursor.lastrowid, f"key-{index}", b"audio", f"2000-01-01 00:00:{index:02d}"),
                )
            token_server.trim_user_cache("translation_cache", user_id=1)
            token_server.trim_user_cache("speech_cache", user_id=1)
            database.commit()
            translations = database.execute(
                "SELECT message_id FROM translation_cache WHERE user_id = 1 ORDER BY created_at"
            ).fetchall()
            speeches = database.execute(
                "SELECT message_id FROM speech_cache WHERE user_id = 1 ORDER BY created_at"
            ).fetchall()

        self.assertEqual(len(translations), 20)
        self.assertEqual(len(speeches), 20)
        self.assertNotIn(message_ids[0], [row["message_id"] for row in translations])
        self.assertNotIn(message_ids[0], [row["message_id"] for row in speeches])

    def test_custom_cloned_voice_does_not_get_megatron_delivery(self):
        from backend.realtime_server import session_payload
        from backend.app import language_constraint, realtime_character_config

        character = {
            "name": "Custom",
            "persona": "保持温和。",
            "voice_id": "S_custom",
            "language": "zh",
        }
        config = realtime_character_config(character)
        payload = session_payload({"speakerId": "S_custom", **config})

        self.assertNotIn("机械统帅", payload["dialog"]["character_manifest"])
        self.assertTrue(config["instructions"].startswith(language_constraint("zh")))

    def test_realtime_and_tts_use_same_character_speaker(self):
        from backend import app as token_server

        captured = {}

        class FakeSpeech:
            configured = True

            @staticmethod
            def synthesize(speaker_id, _text, _language):
                captured["speakerId"] = speaker_id
                return b"audio", "audio/mpeg"

        original_client = token_server.doubao_speech
        try:
            token_server.doubao_speech = FakeSpeech()
            self.login()
            character = self.client.get("/api/characters").json["characters"][0]
            spoken = self.client.post(f"/api/characters/{character['id']}/speak", json={"text": "Test"})
            token = self.client.get(f"/api/token?characterId={character['id']}")
            self.assertEqual(spoken.status_code, 200)
            self.assertEqual(token.status_code, 200)
            self.assertEqual(captured["speakerId"], character["voiceId"])
            self.assertEqual(token.json["speakerId"], character["voiceId"])
        finally:
            token_server.doubao_speech = original_client

    def test_user_can_update_custom_and_override_preset_character(self):
        self.login()
        voice = self.client.get("/api/voices").json["voices"][0]
        created = self.client.post(
            "/api/characters",
            json={
                "name": "待修改角色",
                "persona": "保持自然。",
                "voiceId": voice["id"],
                "voiceName": voice["name"],
            },
        )
        character_id = created.json["character"]["id"]
        response = self.client.patch(
            f"/api/characters/{character_id}",
            json={
                "name": "已修改角色",
                "persona": "回答简洁。",
                "voiceId": voice["id"],
                "voiceName": voice["name"],
                "avatarUrl": "data:image/jpeg;base64,/9j/4AAQ",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["character"]["name"], "已修改角色")
        self.assertEqual(response.json["character"]["voiceId"], voice["id"])
        self.assertTrue(response.json["character"]["avatarUrl"].startswith("./media/avatars/"))

        preset_id = self.client.get("/api/characters").json["characters"][0]["id"]
        overridden = self.client.patch(
            f"/api/characters/{preset_id}",
            json={"name": "修改预设", "persona": "无", "voiceId": voice["id"], "voiceName": voice["name"], "avatarUrl": "data:image/webp;base64,UFJFU0VU"},
        )
        self.assertEqual(overridden.status_code, 200)
        self.assertEqual(overridden.json["character"]["name"], "修改预设")
        self.assertTrue(overridden.json["character"]["avatarUrl"].startswith("./media/avatars/"))

        other_client = self.app.test_client()
        registered = other_client.post(
            "/api/auth/register",
            json={"username": f"user{uuid.uuid4().hex[:8]}", "password": "1234"},
        )
        self.assertEqual(registered.status_code, 201)
        other_preset = other_client.get("/api/characters").json["characters"][0]
        self.assertEqual(other_preset["id"], preset_id)
        self.assertEqual(other_preset["name"], self.TEST_CHARACTER_NAME)


if __name__ == "__main__":
    unittest.main()
