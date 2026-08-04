import base64
import tempfile
import unittest
from pathlib import Path

from backend.avatar_storage import store_avatar_snapshot


class AvatarStorageTest(unittest.TestCase):
    def test_snapshot_is_content_addressed_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            avatar_dir = Path(temporary_directory)
            data_url = "data:image/webp;base64," + base64.b64encode(b"webp-image").decode("ascii")

            first_url = store_avatar_snapshot(data_url, avatar_dir)
            second_url = store_avatar_snapshot(data_url, avatar_dir)

            self.assertEqual(first_url, second_url)
            self.assertTrue(first_url.startswith("./media/avatars/"))
            self.assertEqual(len(list(avatar_dir.iterdir())), 1)
            self.assertEqual(next(avatar_dir.iterdir()).read_bytes(), b"webp-image")

    def test_snapshot_rejects_invalid_base64(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "头像格式无效"):
                store_avatar_snapshot(
                    "data:image/webp;base64,not-valid!",
                    temporary_directory,
                )


if __name__ == "__main__":
    unittest.main()