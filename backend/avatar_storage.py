import base64
import binascii
import hashlib
import re
import secrets
from pathlib import Path


AVATAR_DATA_URL = re.compile(
    r"^data:image/(?P<format>jpeg|jpg|png|webp);base64,(?P<data>[A-Za-z0-9+/=]+)$"
)
AVATAR_EXTENSIONS = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "webp": "webp"}
MAX_AVATAR_BYTES = 5 * 1024 * 1024


def store_avatar_snapshot(data_url, avatar_dir):
    match = AVATAR_DATA_URL.fullmatch(data_url.strip())
    if match is None:
        raise ValueError("头像格式无效")
    encoded_image = match.group("data")
    if len(encoded_image) > (MAX_AVATAR_BYTES * 4 // 3) + 4:
        raise ValueError("头像文件过大")
    try:
        image = base64.b64decode(encoded_image, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("头像数据无效") from error
    if not image:
        raise ValueError("头像数据为空")
    if len(image) > MAX_AVATAR_BYTES:
        raise ValueError("头像文件过大")

    extension = AVATAR_EXTENSIONS[match.group("format")]
    filename = f"{hashlib.sha256(image).hexdigest()}.{extension}"
    avatar_dir = Path(avatar_dir)
    avatar_dir.mkdir(parents=True, exist_ok=True)
    destination = avatar_dir / filename
    if not destination.exists():
        temporary = destination.with_suffix(
            f"{destination.suffix}.{secrets.token_hex(8)}.tmp"
        )
        try:
            temporary.write_bytes(image)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return f"./media/avatars/{filename}"