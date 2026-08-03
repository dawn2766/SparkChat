import os
import tempfile
import unittest
from pathlib import Path


class SparkChatApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = str(Path(cls.temp_dir.name) / "sparkchat.db")
        os.environ["FLASK_SECRET_KEY"] = "test-secret-key"
        from backend.app import app

        cls.app = app
        cls.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

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

    def test_cloned_voice_uses_v3_voice_clone_2_model_and_api_key(self):
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

    def test_cloned_voice_uses_stage_direction_cot(self):
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

    def test_removed_preset_voice_ids_are_rejected(self):
        from backend.speech import DoubaoSpeechClient, DoubaoSpeechError

        client = DoubaoSpeechClient(api_key="test-key")

        with self.assertRaisesRegex(DoubaoSpeechError, "仅支持声音复刻 2.0"):
            client.synthesize("zh_male_baqiqingshu_mars_bigtts", "测试")

    def test_speech_quota_error_returns_service_unavailable(self):
        from backend import app as token_server
        from backend.speech import DoubaoSpeechError

        class FakeDoubaoSpeech:
            configured = True

            @staticmethod
            def synthesize(_voice_id, _text, _language):
                raise DoubaoSpeechError("quota exceeded", status_code=429)

        original_client = token_server.doubao_speech
        original_voice = os.environ.get("SPARKCHAT_VOICE_MEGADEEP")
        try:
            token_server.doubao_speech = FakeDoubaoSpeech()
            os.environ["SPARKCHAT_VOICE_MEGADEEP"] = "S_test_voice"
            self.login()
            response = self.client.post(
                "/api/characters/1/speak", json={"text": "测试朗读"}
            )
            self.assertEqual(response.status_code, 503)
            self.assertIn("额度", response.json["error"])
            self.assertEqual(response.json["actionUrl"], "https://console.volcengine.com/speech/new")
        finally:
            token_server.doubao_speech = original_client
            if original_voice is None:
                os.environ.pop("SPARKCHAT_VOICE_MEGADEEP", None)
            else:
                os.environ["SPARKCHAT_VOICE_MEGADEEP"] = original_voice

    def test_speech_authorization_error_returns_console_link(self):
        from backend import app as token_server
        from backend.speech import DoubaoSpeechError

        class UnauthorizedDoubaoSpeech:
            configured = True

            @staticmethod
            def synthesize(_voice_id, _text, _language):
                raise DoubaoSpeechError("unauthorized resource", status_code=403)

        original_client = token_server.doubao_speech
        original_voice = os.environ.get("SPARKCHAT_VOICE_MEGADEEP")
        try:
            token_server.doubao_speech = UnauthorizedDoubaoSpeech()
            os.environ["SPARKCHAT_VOICE_MEGADEEP"] = "S_test_voice"
            self.login()
            response = self.client.post(
                "/api/characters/1/speak", json={"text": "测试朗读"}
            )
            self.assertEqual(response.status_code, 503)
            self.assertIn("尚未授权", response.json["error"])
            self.assertEqual(response.json["actionUrl"], "https://console.volcengine.com/speech/new")
        finally:
            token_server.doubao_speech = original_client
            if original_voice is None:
                os.environ.pop("SPARKCHAT_VOICE_MEGADEEP", None)
            else:
                os.environ["SPARKCHAT_VOICE_MEGADEEP"] = original_voice

    def test_sse_api_key_error_returns_console_link(self):
        from backend import app as token_server
        from backend.speech import DoubaoSpeechError

        class InvalidKeySpeech:
            configured = True

            @staticmethod
            def synthesize(_voice_id, _text, _language):
                raise DoubaoSpeechError("Invalid X-Api-Key", code=45000010)

        original_client = token_server.doubao_speech
        original_voice = os.environ.get("SPARKCHAT_VOICE_MEGADEEP")
        try:
            token_server.doubao_speech = InvalidKeySpeech()
            os.environ["SPARKCHAT_VOICE_MEGADEEP"] = "S_test_voice"
            self.login()
            response = self.client.post(
                "/api/characters/1/speak", json={"text": "测试朗读"}
            )
            self.assertEqual(response.status_code, 503)
            self.assertIn("尚未授权", response.json["error"])
            self.assertEqual(response.json["actionUrl"], "https://console.volcengine.com/speech/new")
        finally:
            token_server.doubao_speech = original_client
            if original_voice is None:
                os.environ.pop("SPARKCHAT_VOICE_MEGADEEP", None)
            else:
                os.environ["SPARKCHAT_VOICE_MEGADEEP"] = original_voice

    def test_character_prompt_contains_only_character_context(self):
        from backend.app import SYSTEM_PROMPT, build_agent_instructions, character_instructions

        prompt = character_instructions({
            "name": "测试角色",
            "persona": "身份设定",
        })
        self.assertIn("角色名称：测试角色", prompt)
        self.assertIn("身份背景：身份设定", prompt)
        self.assertNotIn("回答要求：", prompt)
        self.assertNotIn("思维过程", prompt)
        self.assertIn("回答要求：", SYSTEM_PROMPT)
        self.assertNotIn("思维过程", SYSTEM_PROMPT)
        final_prompt = build_agent_instructions({
            "name": "测试角色",
            "persona": "身份设定",
            "language": "zh",
        })
        self.assertLess(final_prompt.index("身份背景：身份设定"), final_prompt.index("回答要求："))
        self.assertNotIn("用户记忆", final_prompt)

    def test_character_prompt_requires_stage_directions_for_performative_scenes(self):
        from backend.app import SYSTEM_PROMPTS, build_agent_instructions

        instructions = build_agent_instructions({
            "name": "测试角色",
            "persona": "温和但有锋芒。",
            "language": "zh",
        })

        self.assertIn("普通事实、知识、步骤问题不要添加括号", instructions)
        self.assertIn("涉及安慰、告白、调侃、争执", instructions)
        self.assertIn("添加一处简短的中文全角括号", instructions)
        self.assertNotIn("用户未要求展开", SYSTEM_PROMPTS["en"])
        self.assertIn("Response requirements (in priority order):", SYSTEM_PROMPTS["en"])

    def test_agent_instructions_accept_sqlite_rows(self):
        import sqlite3
        from backend.app import build_agent_instructions

        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE characters (name TEXT, persona TEXT, language TEXT)")
        connection.execute("INSERT INTO characters VALUES (?, ?, ?)", ("测试角色", "身份设定", "en"))
        character = connection.execute("SELECT * FROM characters").fetchone()

        instructions = build_agent_instructions(character)

        self.assertIn("角色名称：测试角色", instructions)
        self.assertIn("Response requirements (in priority order):", instructions)
        self.assertIn("Reply only in natural, accurate, concise English", instructions)

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
        response = self.client.post(
            "/api/characters",
            json={
                "name": "测试角色",
                "persona": "保持简洁。",
                "voiceId": "S_test_custom",
                "voiceName": "豆包测试音色",
                "avatarUrl": "data:image/webp;base64,UklGRg==",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["character"]["avatarUrl"], "data:image/webp;base64,UklGRg==")
        character_id = response.json["character"]["id"]
        self.client.post("/api/auth/logout")
        self.client.post("/api/auth/register", json={"username": "AnotherUser", "password": "1234"})
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
        response = self.client.post(
            "/api/characters",
            json={
                "name": "电话隔离测试",
                "persona": "保持自然。",
                "voiceId": "S_test_custom",
                "voiceName": "豆包测试音色",
            },
        )
        self.assertEqual(response.status_code, 201)
        character_id = response.json["character"]["id"]
        original_client = token_server.doubao_speech
        original_app_id = os.environ.get("DOUBAO_SPEECH_APP_ID")
        original_access_key = os.environ.get("DOUBAO_SPEECH_ACCESS_KEY")
        original_realtime_voice = os.environ.get("SPARKCHAT_REALTIME_VOICE_S_TEST_CUSTOM")
        try:
            token_server.doubao_speech = type("ConfiguredSpeech", (), {"configured": True})()
            os.environ["DOUBAO_SPEECH_APP_ID"] = "test-app-id"
            os.environ["DOUBAO_SPEECH_ACCESS_KEY"] = "test-access-key"
            os.environ["SPARKCHAT_REALTIME_VOICE_S_TEST_CUSTOM"] = "zh_male_xiaotian_jupiter_bigtts"
            token_response = self.client.get(f"/api/token?characterId={character_id}")
            self.assertEqual(token_response.status_code, 200)
            self.assertEqual(token_response.json["speakerId"], "zh_male_xiaotian_jupiter_bigtts")
            self.assertEqual(token_response.json["characterId"], character_id)
        finally:
            token_server.doubao_speech = original_client
            if original_app_id is None:
                os.environ.pop("DOUBAO_SPEECH_APP_ID", None)
            else:
                os.environ["DOUBAO_SPEECH_APP_ID"] = original_app_id
            if original_access_key is None:
                os.environ.pop("DOUBAO_SPEECH_ACCESS_KEY", None)
            else:
                os.environ["DOUBAO_SPEECH_ACCESS_KEY"] = original_access_key
            if original_realtime_voice is None:
                os.environ.pop("SPARKCHAT_REALTIME_VOICE_S_TEST_CUSTOM", None)
            else:
                os.environ["SPARKCHAT_REALTIME_VOICE_S_TEST_CUSTOM"] = original_realtime_voice

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

        character = {
            "name": "Megatron",
            "persona": "Identity",
            "voice_id": "megadeep",
            "language": "en",
        }
        config = realtime_character_config(character)
        payload = session_payload({"speakerId": "S_test_voice", **config})

        self.assertEqual(
            config["instructions"],
            build_agent_instructions(character),
        )
        self.assertEqual(config["language"], "en")
        self.assertIn(config["instructions"], payload["dialog"]["character_manifest"])
        self.assertIn("机械统帅", payload["dialog"]["character_manifest"])
        self.assertIn("Stage directions", payload["dialog"]["character_manifest"])
        self.assertIn("entire response must begin with it", payload["dialog"]["character_manifest"])
        self.assertIn("Never place it in the middle, at the end", payload["dialog"]["character_manifest"])
        self.assertTrue(config["instructions"].startswith("Mandatory language rule:"))
        self.assertTrue(config["instructions"].endswith("even if the user does."))
        self.assertIn("Speak only English", config["speakingStyle"])

    def test_realtime_and_text_chat_share_core_language_and_character_rules(self):
        from backend.app import build_agent_instructions, realtime_character_config

        character = {
            "name": "测试角色",
            "persona": "沉着、可靠。",
            "voice_id": "S_custom",
            "language": "zh",
        }
        text_instructions = build_agent_instructions(character)
        realtime_config = realtime_character_config(character)

        for shared_rule in ("角色名称：测试角色", "身份背景：沉着、可靠。", "只用自然、准确、简洁的中文回答"):
            self.assertIn(shared_rule, text_instructions)
            self.assertIn(shared_rule, realtime_config["instructions"])
        self.assertIn("整条回答必须以该括号开头", text_instructions)
        self.assertIn("整条回答必须以该括号开头", realtime_config["instructions"])
        self.assertIn("禁止把括号放在台词中间、句末或正文之后", realtime_config["instructions"])
        self.assertTrue(realtime_config["instructions"].startswith("强制语言规则："))
        self.assertTrue(realtime_config["instructions"].endswith("绝对不要切换语言。"))
        self.assertIn("只说中文，不夹杂英文", realtime_config["speakingStyle"])

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
        self.assertIn("只用自然、准确、简洁的中文回答", config["instructions"])

    def test_realtime_voice_mapping_is_independent_from_cloned_tts_voice(self):
        from backend import app as token_server

        original_voice = os.environ.get("SPARKCHAT_REALTIME_VOICE_MEGADEEP")
        try:
            os.environ["SPARKCHAT_REALTIME_VOICE_MEGADEEP"] = "zh_male_xiaotian_jupiter_bigtts"
            self.login()
            response = self.client.get("/api/token?characterId=1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["speakerId"], "zh_male_xiaotian_jupiter_bigtts")
        finally:
            if original_voice is None:
                os.environ.pop("SPARKCHAT_REALTIME_VOICE_MEGADEEP", None)
            else:
                os.environ["SPARKCHAT_REALTIME_VOICE_MEGADEEP"] = original_voice

    def test_user_can_update_custom_and_override_preset_character(self):
        self.login()
        created = self.client.post(
            "/api/characters",
            json={
                "name": "待修改角色",
                "persona": "保持自然。",
                "voiceId": "S_custom_one",
                "voiceName": "自定义音色一",
            },
        )
        character_id = created.json["character"]["id"]
        response = self.client.patch(
            f"/api/characters/{character_id}",
            json={
                "name": "已修改角色",
                "persona": "回答简洁。",
                "voiceId": "S_custom_two",
                "voiceName": "自定义音色二",
                "avatarUrl": "data:image/jpeg;base64,/9j/4AAQ",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["character"]["name"], "已修改角色")
        self.assertEqual(response.json["character"]["voiceId"], "S_custom_two")
        self.assertEqual(response.json["character"]["avatarUrl"], "data:image/jpeg;base64,/9j/4AAQ")

        preset_id = self.client.get("/api/characters").json["characters"][0]["id"]
        overridden = self.client.patch(
            f"/api/characters/{preset_id}",
            json={"name": "修改预设", "persona": "无", "voiceId": "S_custom_one", "voiceName": "自定义音色一", "avatarUrl": "data:image/webp;base64,UFJFU0VU"},
        )
        self.assertEqual(overridden.status_code, 200)
        self.assertEqual(overridden.json["character"]["name"], "修改预设")
        self.assertEqual(overridden.json["character"]["avatarUrl"], "data:image/webp;base64,UFJFU0VU")

        other_client = self.app.test_client()
        other_client.post("/api/auth/register", json={"username": "OverrideIsolation", "password": "1234"})
        other_preset = other_client.get("/api/characters").json["characters"][0]
        self.assertEqual(other_preset["id"], preset_id)
        self.assertNotEqual(other_preset["name"], "修改预设")


if __name__ == "__main__":
    unittest.main()
