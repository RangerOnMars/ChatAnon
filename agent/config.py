import uuid
import pyaudio
from pathlib import Path
from credentials import appid, access_key, speaker_id

# 读取角色设定文件
def load_character_manifest():
    manifest_path = Path(__file__).parent / "prompts" / "character_manifest.md"
    with open(manifest_path, "r", encoding="utf-8") as f:
        return f.read()

# 配置信息
ws_connect_config = {
    "base_url": "wss://openspeech.bytedance.com/api/v3/realtime/dialogue",
    "headers": {
        "X-Api-App-ID": appid,
        "X-Api-Access-Key": access_key,
        "X-Api-Resource-Id": "volc.speech.dialog",  # 固定值
        "X-Api-App-Key": "PlgvMymc7f3tQnJ6",  # 固定值
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
}

start_session_req = {
    "tts": {
        "speaker": speaker_id,
        "audio_config": {
            "channel": 1,
            "format": "pcm",
            "sample_rate": 24000
        },
    },
    "dialog": {
        "character_manifest": load_character_manifest(),
        "location": {
          "city": "深圳",
        },
        "extra": {
            "strict_audit": False,
            "model": "SC",
            "audit_response": "爱音酱听不懂这些啦，换个话题吧~"
        }
    }
}

input_audio_config = {
    "chunk": 3200,
    "format": "pcm",
    "channels": 1,
    "sample_rate": 16000,
    "bit_size": pyaudio.paInt16
}

output_audio_config = {
    "chunk": 3200,
    "format": "pcm",
    "channels": 1,
    "sample_rate": 24000,
    "bit_size": pyaudio.paFloat32
}
