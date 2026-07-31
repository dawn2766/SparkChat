import base64
import json
import os
import uuid
from urllib import error, request


SPEECH_CONSOLE_URL = "https://console.volcengine.com/speech/new"


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
    def __init__(self, api_key=None, app_id=None, access_key=None, timeout=60):
        self.api_key = api_key or os.getenv("DOUBAO_SPEECH_API_KEY")
        self.app_id = app_id or os.getenv("DOUBAO_SPEECH_APP_ID")
        self.access_key = access_key or os.getenv("DOUBAO_SPEECH_ACCESS_KEY")
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.api_key or (self.app_id and self.access_key))

    def _headers(self, resource_id=None, prefer_legacy=False):
        headers = {
            "Content-Type": "application/json",
            "X-Api-Request-Id": str(uuid.uuid4()),
        }
        if self.api_key and not prefer_legacy:
            headers["X-Api-Key"] = self.api_key
        else:
            headers["X-Api-App-Key"] = self.app_id or ""
            headers["X-Api-Access-Key"] = self.access_key or ""
        if resource_id:
            headers["X-Api-Resource-Id"] = resource_id
        return headers

    def realtime_headers(self, resource_id=None):
        return self._headers(resource_id)

    def _post(self, url, payload, resource_id=None, prefer_legacy=False):
        if not self.configured:
            raise DoubaoSpeechError("服务器尚未配置豆包语音凭证", status_code=503)
        api_request = request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(resource_id, prefer_legacy),
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

    def design_voice(self, speaker_id, text_prompt, preview_text):
        body, _headers = self._post(
            "https://openspeech.bytedance.com/api/v3/tts/voice_design",
            {
                "speaker_id": speaker_id,
                "text": preview_text,
                "prompt": {"text_prompt": text_prompt},
                "language": 0,
            },
            prefer_legacy=bool(self.app_id and self.access_key),
        )
        result = json.loads(body.decode("utf-8"))
        if result.get("icl_list"):
            return result["icl_list"][0]
        return result

    def synthesize(self, speaker_id, text):
        resource_id = (
            os.getenv("DOUBAO_ICL_TTS_RESOURCE_ID", "seed-icl-2.0")
            if speaker_id.startswith(("S_", "ICL_", "saturn_"))
            else os.getenv("DOUBAO_TTS_RESOURCE_ID", "seed-tts-1.0")
        )
        body, headers = self._post(
            "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse",
            {
                "user": {"uid": "sparkchat"},
                "namespace": "BidirectionalTTS",
                "req_params": {
                    "text": text,
                    "speaker": speaker_id,
                    **(
                        {"model": "seed-tts-2.0-expressive"}
                        if speaker_id.startswith(("S_", "ICL_", "saturn_"))
                        else {}
                    ),
                    "audio_params": {
                        "format": "mp3",
                        "sample_rate": 24000,
                        "speech_rate": -8 if speaker_id.startswith(("S_", "ICL_", "saturn_")) else 0,
                    },
                },
            },
            resource_id=resource_id,
            prefer_legacy=speaker_id.startswith(("S_", "ICL_", "saturn_")),
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

