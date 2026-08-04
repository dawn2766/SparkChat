import base64
import binascii
import hashlib
import re
from pathlib import Path


AVATAR_DATA_URL = re.compile(
    r"^data:image/(?P<format>jpeg|jpg|png|webp);base64,(?P<data>[A-Za-z0-9+/=]+)$"
)
AVATAR_EXTENSIONS = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "webp": "webp"}


def store_avatar_snapshot(data_url, avatar_dir):
    match = AVATAR_DATA_URL.fullmatch(data_url.strip())
    if match is None:
        raise ValueError("头像格式无效")
    try:
        image = base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("头像数据无效") from error
    if not image:
        raise ValueError("头像数据为空")

    extension = AVATAR_EXTENSIONS[match.group("format")]
    filename = f"{hashlib.sha256(image).hexdigest()}.{extension}"
    avatar_dir = Path(avatar_dir)
    avatar_dir.mkdir(parents=True, exist_ok=True)
    destination = avatar_dir / filename
    if not destination.exists():
        temporary = destination.with_suffix(f"{destination.suffix}.tmp")
        temporary.write_bytes(image)
        temporary.replace(destination)
    return f"./media/avatars/{filename}"