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
        from token_server import app

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
        self.assertNotIn("unreadCount", response.json["characters"][0])

    def test_nonverbal_stage_directions_are_removed_from_speech(self):
        from token_server import strip_nonverbal_text

        self.assertEqual(
            strip_nonverbal_text("（低声）准备行动。[金属碰撞声] *抬手* 现在出发。"),
            "准备行动。 现在出发。",
        )

    def test_designed_voice_uses_expressive_tts_2_model(self):
        import base64
        import json
        from doubao_speech import DoubaoSpeechClient

        captured = {}
        client = DoubaoSpeechClient(api_key="test-key")

        def fake_post(_url, payload, **_kwargs):
            captured.update(payload)
            event = {"code": 0, "data": base64.b64encode(b"audio").decode("ascii")}
            return f"data: {json.dumps(event)}\n".encode("utf-8"), {}

        client._post = fake_post
        audio, content_type = client.synthesize("S_test_voice", "测试")

        self.assertEqual(audio, b"audio")
        self.assertEqual(content_type, "audio/mpeg")
        self.assertEqual(captured["req_params"]["model"], "seed-tts-2.0-expressive")
        self.assertEqual(captured["req_params"]["audio_params"]["speech_rate"], -8)

    def test_speech_quota_error_returns_service_unavailable(self):
        import token_server
        from doubao_speech import DoubaoSpeechError

        class FakeDoubaoSpeech:
            configured = True

            @staticmethod
            def synthesize(_voice_id, _text):
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
        import token_server
        from doubao_speech import DoubaoSpeechError

        class UnauthorizedDoubaoSpeech:
            configured = True

            @staticmethod
            def synthesize(_voice_id, _text):
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
        import token_server
        from doubao_speech import DoubaoSpeechError

        class InvalidKeySpeech:
            configured = True

            @staticmethod
            def synthesize(_voice_id, _text):
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
        from token_server import SYSTEM_PROMPT, build_agent_instructions, character_instructions

        prompt = character_instructions({
            "name": "测试角色",
            "persona": "身份设定",
            "background": "背景经历",
            "memory": "用户记忆",
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
            "background": "",
            "memory": "",
        })
        self.assertLess(final_prompt.index("身份背景：身份设定"), final_prompt.index("回答要求："))
        self.assertNotIn("用户记忆", final_prompt)

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
                "tagline": "集成测试",
                "persona": "保持简洁。",
                "background": "测试背景。",
                "memory": "测试记忆。",
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
        import token_server

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
        try:
            token_server.doubao_speech = type("ConfiguredSpeech", (), {"configured": True})()
            os.environ["DOUBAO_SPEECH_APP_ID"] = "test-app-id"
            os.environ["DOUBAO_SPEECH_ACCESS_KEY"] = "test-access-key"
            token_response = self.client.get(f"/api/token?characterId={character_id}")
            self.assertEqual(token_response.status_code, 200)
            self.assertEqual(token_response.json["speakerId"], "S_test_custom")
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

    def test_user_can_update_custom_and_override_preset_character(self):
        self.login()
        created = self.client.post(
            "/api/characters",
            json={
                "name": "待修改角色",
                "persona": "保持自然。",
                "voiceId": "archive",
                "voiceName": "方舟档案员",
            },
        )
        character_id = created.json["character"]["id"]
        response = self.client.patch(
            f"/api/characters/{character_id}",
            json={
                "name": "已修改角色",
                "tagline": "新的定位",
                "persona": "回答简洁。",
                "background": "新的背景。",
                "memory": "新的记忆。",
                "voiceId": "ironvow",
                "voiceName": "钢铁誓言",
                "avatarUrl": "data:image/webp;base64,V0VCUA==",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["character"]["name"], "已修改角色")
        self.assertEqual(response.json["character"]["voiceId"], "ironvow")
        self.assertEqual(response.json["character"]["avatarUrl"], "data:image/webp;base64,V0VCUA==")

        preset_id = self.client.get("/api/characters").json["characters"][0]["id"]
        overridden = self.client.patch(
            f"/api/characters/{preset_id}",
            json={"name": "修改预设", "persona": "无", "voiceId": "archive", "voiceName": "方舟档案员", "avatarUrl": "data:image/webp;base64,UFJFU0VU"},
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
