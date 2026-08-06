import base64
import html
import json
import os
import re
import uuid
from urllib import error, request

from .model_config import TTS_MODEL, TTS_RESOURCE_ID

SPEECH_CONSOLE_URL = "https://console.volcengine.com/speech/new"


STAGE_DIRECTION_PATTERN = re.compile(
    r"（([^（）]*)）|\(([^()]*)\)|\[([^\[\]]*)\]|【([^【】]*)】|\*([^*]+)\*"
)


def prepare_speech_text(text):
    cues = []
    segments = []
    cursor = 0
    active_cue = ""
    for match in STAGE_DIRECTION_PATTERN.finditer(text):
        spoken = text[cursor:match.start()]
        if spoken.strip():
            segments.append((active_cue, spoken))
        cue = next((value.strip() for value in match.groups() if value and value.strip()), "")
        if cue:
            cues.append(cue)
            active_cue = cue
        cursor = match.end()
    if cursor < len(text) and text[cursor:].strip():
        segments.append((active_cue, text[cursor:]))

    plain_text = re.sub(r"[ \t]{2,}", " ", "".join(spoken for _, spoken in segments)).strip()
    expressive_parts = []
    for cue, spoken in segments:
        if not spoken:
            continue
        escaped_spoken = html.escape(spoken, quote=False)
        if cue:
            escaped_cue = html.escape(cue[:80], quote=True)
            expressive_parts.append(f"<cot text=\"{escaped_cue}\">{escaped_spoken}</cot>")
        else:
            expressive_parts.append(escaped_spoken)
    return plain_text, "".join(expressive_parts).strip(), cues[:8]


class DoubaoSpeechError(RuntimeError):
    def __init__(self, message, status_code=502, code=None, log_id=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.log_id = log_id

    @property
    def requires_authorization(self):
        text = str(self).lower()
        return self.code in {45000010, 45000000, 45001001} or self.status_code in {401, 403} or any(
            marker in text for marker in ("unauthorized", "forbidden", "resource", "开通", "授权")
        )


class DoubaoSpeechClient:
    def __init__(self, api_key=None, timeout=60):
        self.api_key = api_key or os.getenv("DOUBAO_SPEECH_API_KEY")
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.api_key)

    def _headers(self, resource_id=None):
        headers = {
            "Content-Type": "application/json",
            "X-Api-Request-Id": str(uuid.uuid4()),
            "X-Api-Key": self.api_key or "",
        }
        if resource_id:
            headers["X-Api-Resource-Id"] = resource_id
        return headers

    def _post(self, url, payload, resource_id=None):
        if not self.configured:
            raise DoubaoSpeechError("服务器尚未配置豆包语音凭证", status_code=503)
        api_request = request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(resource_id),
            method="POST",
        )
        try:
            with request.urlopen(api_request, timeout=self.timeout) as response:
                return response.read(), response.headers
        except error.HTTPError as http_error:
            body = http_error.read().decode("utf-8", errors="replace")
            try:
                details = json.loads(body)
            except json.JSONDecodeError:
                details = {}
            message = details.get("message") or body or http_error.reason
            raise DoubaoSpeechError(
                message,
                status_code=http_error.code,
                code=details.get("code"),
                log_id=http_error.headers.get("X-Tt-Logid"),
            ) from http_error
        except error.URLError as network_error:
            raise DoubaoSpeechError(f"豆包语音网络请求失败：{network_error.reason}") from network_error

    def synthesize(self, speaker_id, text, language="zh"):
        plain_text, expressive_text, cues = prepare_speech_text(text)
        if not plain_text:
            raise DoubaoSpeechError("语音内容不包含可朗读文本", status_code=400)
        if not speaker_id.startswith(("S_", "ICL_", "saturn_", "sparkchat_", "custom_")):
            raise DoubaoSpeechError("当前仅支持已配置的豆包 speaker ID", status_code=400)
        body, headers = self._post(
            "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse",
            {
                "user": {"uid": "sparkchat"},
                "namespace": "BidirectionalTTS",
                "req_params": {
                    "text": expressive_text if cues else plain_text,
                    "speaker": speaker_id,
                    "language": language,
                    "model": TTS_MODEL,
                    "audio_params": {
                        "format": "mp3",
                        "sample_rate": 24000,
                        "speech_rate": -8,
                    },
                    **({"additions": json.dumps({"use_tag_parser": True})} if cues else {}),
                },
            },
            resource_id=TTS_RESOURCE_ID,
        )
        audio_parts = []
        for line in body.decode("utf-8").splitlines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            if event.get("code") not in {0, 20000000}:
                raise DoubaoSpeechError(event.get("message", "豆包语音合成失败"), code=event.get("code"))
            if event.get("data"):
                audio_parts.append(base64.b64decode(event["data"]))
        if not audio_parts:
            raise DoubaoSpeechError("豆包语音合成未返回音频数据", log_id=headers.get("X-Tt-Logid"))
        return b"".join(audio_parts), "audio/mpeg"

