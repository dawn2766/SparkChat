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
                "voiceId": "archive",
                "voiceName": "方舟档案员",
            },
        )
        self.assertEqual(response.status_code, 201)
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

    def test_custom_character_cannot_use_preset_call_engine(self):
        self.login()
        response = self.client.post(
            "/api/characters",
            json={
                "name": "电话隔离测试",
                "persona": "保持自然。",
                "voiceId": "archive",
                "voiceName": "方舟档案员",
            },
        )
        self.assertEqual(response.status_code, 201)
        character_id = response.json["character"]["id"]
        token_response = self.client.get(f"/api/token?characterId={character_id}")
        self.assertEqual(token_response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
