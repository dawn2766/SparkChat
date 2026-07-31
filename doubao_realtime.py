import json
import struct


FULL_CLIENT_REQUEST = 0x1
AUDIO_ONLY_REQUEST = 0x2
FULL_SERVER_RESPONSE = 0x9
AUDIO_ONLY_RESPONSE = 0xB
ERROR_RESPONSE = 0xF

START_CONNECTION = 1
FINISH_CONNECTION = 2
START_SESSION = 100
FINISH_SESSION = 102
TASK_REQUEST = 200

CONNECTION_EVENTS = {1, 2, 50, 51, 52}


def encode_event(event, payload=b"", session_id=None, message_type=FULL_CLIENT_REQUEST):
    if isinstance(payload, dict):
        payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        serialization = 1
    else:
        serialization = 0
    header = bytes((0x11, (message_type << 4) | 0x4, serialization << 4, 0x00))
    optional = struct.pack(">I", event)
    if session_id is not None:
        encoded_session_id = session_id.encode("utf-8")
        optional += struct.pack(">I", len(encoded_session_id)) + encoded_session_id
    return header + optional + struct.pack(">I", len(payload)) + payload


def decode_event(data):
    if len(data) < 12:
        raise ValueError("豆包实时语音响应帧过短")
    header_size = (data[0] & 0x0F) * 4
    message_type = data[1] >> 4
    flags = data[1] & 0x0F
    serialization = data[2] >> 4
    offset = header_size
    result = {"message_type": message_type, "event": None, "session_id": None}
    if message_type == ERROR_RESPONSE:
        result["code"] = struct.unpack_from(">I", data, offset)[0]
        offset += 4
    if flags & 0x3:
        result["sequence"] = struct.unpack_from(">i", data, offset)[0]
        offset += 4
    if flags & 0x4:
        result["event"] = struct.unpack_from(">I", data, offset)[0]
        offset += 4
    if result["event"] in CONNECTION_EVENTS:
        connect_size = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        result["connect_id"] = data[offset:offset + connect_size].decode("utf-8")
        offset += connect_size
    elif result["event"] is not None:
        session_size = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        result["session_id"] = data[offset:offset + session_size].decode("utf-8")
        offset += session_size
    payload_size = struct.unpack_from(">I", data, offset)[0]
    offset += 4
    payload = data[offset:offset + payload_size]
    if len(payload) != payload_size:
        raise ValueError("豆包实时语音响应负载不完整")
    if serialization == 1 and payload:
        result["payload"] = json.loads(payload.decode("utf-8"))
    else:
        result["payload"] = payload
    return result