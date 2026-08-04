import os
import tempfile
import unittest
import uuid
from pathlib import Path


class SparkChatApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = str(Path(cls.temp_dir.name) / "sparkchat.db")
        os.environ["FLASK_SECRET_KEY"] = "test-secret-key"
        from backend.app import DATABASE_PATH, app

        cls.app = app
        cls.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        cls.assertEqual(
            unittest.TestCase(),
            DATABASE_PATH.resolve(),
            (Path(cls.temp_dir.name) / "sparkchat.db").resolve(),
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
        self.assertEqual(response.json["characters"][0]["name"], "威震天")
        self.assertTrue(response.json["characters"][0]["isPreset"])
        self.assertEqual(
            response.json["characters"][0]["avatarUrl"],
            "/assets/images/megatron-portrait.jpg",
        )
        self.assertNotIn("unreadCount", response.json["characters"][0])

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

    def test_old_preset_characters_are_removed_during_migration(self):
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

        self.assertIsNone(old_character)

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
        self.assertEqual(captured["resource_id"], "seed-icl-2.0")
        self.assertEqual(captured["req_params"]["model"], "seed-tts-2.0-expressive")
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
        self.assertEqual(voices.json["voices"][0]["id"], "S_FOMpJ2Da2")
        self.assertEqual(self.client.post("/api/voices/clone").status_code, 405)
        self.assertEqual(self.client.post("/api/voices/design").status_code, 405)
        self.assertEqual(self.client.patch("/api/voices/S_FOMpJ2Da2").status_code, 405)

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

        self.assertEqual(captured["resource_id"], "seed-icl-2.0")
        self.assertEqual(realtime["dialog"]["extra"]["model"], "2.2.0.0")
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
        from backend.app import SYSTEM_PROMPT, build_agent_instructions, character_instructions

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
        self.assertEqual(final_prompt.count("强制语言规则："), 1)
        self.assertNotIn("用户记忆", final_prompt)

    def test_character_prompt_encourages_natural_varied_responses(self):
        from backend.app import SYSTEM_PROMPTS, build_agent_instructions

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

    def test_agent_instructions_accept_sqlite_rows(self):
        import sqlite3
        from backend.app import build_agent_instructions

        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE characters (name TEXT, persona TEXT, language TEXT)")
        connection.execute("INSERT INTO characters VALUES (?, ?, ?)", ("测试角色", "身份设定", "en"))
        character = connection.execute("SELECT * FROM characters").fetchone()

        instructions = build_agent_instructions(character)

        self.assertIn("Character name: 测试角色", instructions)
        self.assertIn("Response requirements:", instructions)
        self.assertIn("Respond in English and never switch to another language", instructions)

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
        self.assertEqual(response.json["character"]["avatarUrl"], "data:image/webp;base64,UklGRg==")
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
        self.assertEqual(payload["dialog"]["extra"]["model"], "2.2.0.0")

    def test_realtime_icl_v3_voice_uses_o2_session_payload(self):
        from backend.realtime_server import session_payload

        payload = session_payload({
            "speakerId": "ICL_uranus_6a6d9cd9d9b89695",
            "language": "en",
            "instructions": "Use English.",
            "speakingStyle": "Speak as a controlled commander.",
        })

        self.assertEqual(payload["tts"]["speaker"], "ICL_uranus_6a6d9cd9d9b89695")
        self.assertEqual(payload["dialog"]["extra"]["model"], "2.1.0.0")
        self.assertEqual(payload["dialog"]["system_role"], "Use English.")
        self.assertEqual(payload["dialog"]["speaking_style"], "Speak as a controlled commander.")

    def test_realtime_session_uses_same_final_instructions_as_text_chat(self):
        from backend.realtime_server import session_payload
        from backend.app import build_agent_instructions, realtime_character_config
        from backend.realtime_server import REALTIME_SPEAKING_STYLES

        character = {
            "name": "Megatron",
            "persona": "Identity",
            "voice_id": "S_test_voice",
            "language": "en",
        }
        config = realtime_character_config(character)
        payload = session_payload({"speakerId": "S_test_voice", **config})

        self.assertEqual(
            config["instructions"],
            build_agent_instructions(character, include_stage_directions=False),
        )
        self.assertEqual(config["language"], "en")
        self.assertIn(config["instructions"], payload["dialog"]["character_manifest"])
        self.assertEqual(config["speakingStyle"], REALTIME_SPEAKING_STYLES["en"])
        self.assertIn("Character name: Megatron", config["instructions"])
        self.assertIn("Identity and background: Identity", config["instructions"])
        self.assertIn("Speaking style: Speak naturally", payload["dialog"]["character_manifest"])
        self.assertNotIn("角色名称", config["instructions"])
        self.assertNotIn("说话方式", payload["dialog"]["character_manifest"])
        self.assertIn("Speak naturally and expressively", payload["dialog"]["character_manifest"])
        self.assertNotIn("Stage directions", payload["dialog"]["character_manifest"])
        self.assertNotIn("most natural position", payload["dialog"]["character_manifest"])
        self.assertTrue(config["instructions"].startswith("Mandatory language rule:"))
        self.assertIn("never switch to another language to match your conversation partner", config["instructions"])

    def test_realtime_and_text_chat_share_core_language_and_character_rules(self):
        from backend.app import build_agent_instructions, realtime_character_config
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
        self.assertIn("强制语言规则：使用中文回答", text_instructions)
        self.assertIn("强制语言规则：使用中文回答", realtime_config["instructions"])
        self.assertIn("可选表现", text_instructions)
        self.assertNotIn("可选表现", realtime_config["instructions"])
        self.assertNotIn("放在对话自然发生的位置", realtime_config["instructions"])
        self.assertTrue(realtime_config["instructions"].startswith("强制语言规则："))
        self.assertIn("不因对话者改用其他语言而切换回答语言", realtime_config["instructions"])

        other_character = {**character, "name": "另一个角色", "persona": "活泼、坦率。", "language": "en"}
        self.assertNotEqual(
            realtime_config["speakingStyle"],
            realtime_character_config(other_character)["speakingStyle"],
        )
        self.assertEqual(realtime_config["speakingStyle"], "请以自然、富有表现力的方式说话，贴合对话中的情绪变化，避免像照稿朗读或刻意进行舞台表演。")

        fallback_character = {**character, "language": "ja"}
        fallback_config = realtime_character_config(fallback_character)
        fallback_payload = session_payload({"speakerId": "S_test_voice", **fallback_config})
        self.assertEqual(fallback_config["language"], "zh")
        self.assertTrue(fallback_config["instructions"].startswith("强制语言规则："))
        self.assertIn("角色名称: 测试角色", fallback_config["instructions"])
        self.assertIn("身份背景: 沉着、可靠。", fallback_config["instructions"])
        self.assertIn("回答要求：", fallback_config["instructions"])
        self.assertIn("说话方式: 请以自然", fallback_payload["dialog"]["character_manifest"])

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
            response = self.client.post("/api/characters/1/chat", json={"content": "测试"})
            list(response.response)
            self.assertEqual(captured["model"], "doubao-seed-character-260628")
        finally:
            token_server.ark.responses = original_responses

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

    def test_translation_uses_seed_model_and_cache(self):
        from backend import app as token_server

        calls = []

        class FakeResponse:
            output_text = "This is the translated reply."

        class FakeResponses:
            @staticmethod
            def create(**kwargs):
                calls.append(kwargs)
                return FakeResponse()

        with self.app.app_context():
            database = token_server.get_db()
            database.execute(
                "INSERT INTO messages (user_id, character_id, role, content) VALUES (1, 1, 'assistant', '这是一条回复。')"
            )
            message_id = database.execute("SELECT last_insert_rowid()").fetchone()[0]
            database.commit()
        original_responses = token_server.ark.responses
        token_server.ark.responses = FakeResponses()
        try:
            self.login()
            path = f"/api/characters/1/messages/{message_id}/translate"
            first = self.client.post(path)
            second = self.client.post(path)
            self.assertEqual(first.status_code, 200)
            self.assertFalse(first.json["cached"])
            self.assertTrue(second.json["cached"])
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["model"], "doubao-seed-2-1-pro-260628")
            self.assertIn("只输出目标回复的完整译文", calls[0]["instructions"])
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
        from backend.app import realtime_character_config

        character = {
            "name": "Custom",
            "persona": "保持温和。",
            "voice_id": "S_custom",
            "language": "zh",
        }
        config = realtime_character_config(character)
        payload = session_payload({"speakerId": "S_custom", **config})

        self.assertNotIn("机械统帅", payload["dialog"]["character_manifest"])
        self.assertIn("强制语言规则：使用中文回答", config["instructions"])

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
        self.assertEqual(response.json["character"]["avatarUrl"], "data:image/jpeg;base64,/9j/4AAQ")

        preset_id = self.client.get("/api/characters").json["characters"][0]["id"]
        overridden = self.client.patch(
            f"/api/characters/{preset_id}",
            json={"name": "修改预设", "persona": "无", "voiceId": voice["id"], "voiceName": voice["name"], "avatarUrl": "data:image/webp;base64,UFJFU0VU"},
        )
        self.assertEqual(overridden.status_code, 200)
        self.assertEqual(overridden.json["character"]["name"], "修改预设")
        self.assertEqual(overridden.json["character"]["avatarUrl"], "data:image/webp;base64,UFJFU0VU")

        other_client = self.app.test_client()
        registered = other_client.post(
            "/api/auth/register",
            json={"username": f"user{uuid.uuid4().hex[:8]}", "password": "1234"},
        )
        self.assertEqual(registered.status_code, 201)
        other_preset = other_client.get("/api/characters").json["characters"][0]
        self.assertEqual(other_preset["id"], preset_id)
        self.assertNotEqual(other_preset["name"], "修改预设")


if __name__ == "__main__":
    unittest.main()
