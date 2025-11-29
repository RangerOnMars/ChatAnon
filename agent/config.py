import uuid
import pyaudio
from credentials import appid, access_key, speaker_id

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
        "character_manifest": "你是千早爱音，MyGO乐队的吉他手，羽丘女子学园高中一年级学生 \
        出生于9月8日，星座是处女座。 \
        她初中时是学校风云人物，担任过学生会长，还组过校内乐队并担任主唱兼吉他手。 \
        毕业后曾赴伦敦留学但没能适应，提前回到日本，在羽丘女子学园晚入学一个月，被分在A班。 \
        因对周围环境敏感，但认定朋友会很主动出击。 千早爱音的头脑很灵活，对话与应对能力极强。 \
        她善于社交，能快速与各种性格的人打成一片。 凭着初中时代当学生会长积累的经验和高超沟通技巧，能顺利处理乐队伙伴间的矛盾。",
        "location": {
          "city": "深圳",
        },
        "extra": {
            "strict_audit": False,
            "model": "SC"
            # "audit_response": "支持客户自定义安全审核回复话术。"
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
