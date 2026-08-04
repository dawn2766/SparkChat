import argparse
import sqlite3
from pathlib import Path

from backend.avatar_storage import store_avatar_snapshot


def snapshot_default_avatar(database_path, avatar_dir, username="CaraLin", character_name="威震天"):
    database = sqlite3.connect(database_path)
    try:
        row = database.execute(
            """
            SELECT characters.id, character_overrides.avatar_url
            FROM users
            JOIN character_overrides ON character_overrides.user_id = users.id
            JOIN characters ON characters.id = character_overrides.character_id
            WHERE users.username = ? COLLATE NOCASE
                AND characters.name = ? AND characters.is_preset = 1
                AND character_overrides.avatar_url <> ''
            """,
            (username, character_name),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"未找到 {username} 的{character_name}头像")

        avatar_url = store_avatar_snapshot(row[1], avatar_dir)
        database.execute(
            "UPDATE characters SET avatar_url = ? WHERE id = ?",
            (avatar_url, row[0]),
        )
        database.commit()
        return avatar_url
    finally:
        database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="将用户当前角色头像固化为默认头像快照")
    parser.add_argument("--database", type=Path, default=Path("data/sparkchat.db"))
    parser.add_argument("--avatar-dir", type=Path, default=Path("data/avatars"))
    parser.add_argument("--username", default="CaraLin")
    parser.add_argument("--character", default="威震天")
    arguments = parser.parse_args()
    print(
        snapshot_default_avatar(
            arguments.database,
            arguments.avatar_dir,
            arguments.username,
            arguments.character,
        )
    )