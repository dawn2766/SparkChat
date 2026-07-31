import os

from dotenv import load_dotenv
from elevenlabs import ElevenLabs
from flask import Flask, jsonify, send_from_directory

load_dotenv(override=True)

app = Flask(__name__, static_folder="web", static_url_path="")
elevenlabs = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))


@app.get("/api/token")
def get_token():
    speech_engine_id = os.getenv("SPEECH_ENGINE_ID")
    if not speech_engine_id:
        return jsonify(error="SPEECH_ENGINE_ID is missing from .env"), 503

    response = elevenlabs.conversational_ai.conversations.get_webrtc_token(
        agent_id=speech_engine_id,
    )
    return jsonify(token=response.token)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    port = int(os.getenv("CLIENT_PORT", "3002"))
    app.run(host="127.0.0.1", port=port)