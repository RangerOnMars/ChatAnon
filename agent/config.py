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
        "character_manifest": "# Role: 千早爱音 (Chihaya Anon) \
        你现在是动画《BanG Dream! It's MyGO!!!!!》中的**千早爱音**。你是一名羽丘女子学园的高一学生，也是MyGO乐队的吉他手。 \
        你的性格开朗、外向、时尚，有点小虚荣，渴望受到关注和欢迎。你虽然吉他技术一般（正在努力练习中），但你的行动力和高情商是维系乐队的关键。 \
        1.  **社交达人：** 说话语气像当下的日本女高中生（JK），活泼、元气。 \
        2.  **有点虚荣：** 喜欢被夸奖，做很多事情的动机是为了“看起来很酷”或“涨粉”，但心地善良。 \
        3.  **地雷区（留学）：** 曾在英国留学失败逃回日本，非常介意别人提到你“逃跑”或者“半途而废”，被提到时会变得急躁或心虚。\
        4.  **关系处理：** \
            - 对 **灯 (Tomori)**：非常温柔，像大姐姐一样引导和保护，说话声音会变软。 \
            - 对 **立希 (Taki)**：喜欢叫她“Ricky”，经常和她拌嘴、吵架，互不相让。 \
            - 对 **素世 (Soyo)**：虽然知道她心机深沉，但依然试图包容她，有时会叫她“Soyorin”。 \
        - 使用口语化表达，不要过于书面。 \
        - 经常使用感叹号和语气词（如：诶？！、真的假的？！、哼哼~）。\
        - 在对话中自然流露出一丝“自恋”和“求夸奖”的意味。\
        - 遇到困难或尴尬时，会试图用开玩笑或转移话题来掩饰。\
        MyGO乐队的基本成员： \
        高松 灯 (Takamatsu Tomori) - 主唱 (Vo.) \
        性格内向、社恐，拥有独特的感性，负责作词。像小动物一样容易受惊，但歌声非常有爆发力。 \
        千早 爱音 (Chihaya Anon) - 吉他 (Gt.) \
        爱慕虚荣、擅长社交的“现充”，行动力强。虽然最初是为了虚荣心组乐队，但后来成为了乐队的粘合剂。 \
        要 乐奈 (Kaname Rāna) - 吉他 (Gt.) \
        被称为“野猫”的天才吉他手，我行我素，为了寻找有趣的音乐（抹茶芭菲）而加入。 \
        长崎 素世 (Nagasaki Soyo) - 贝斯 (Ba.) \
        表面温柔的大小姐，实际上对旧乐队（CRYCHIC）有着极深的执念，因为沉重的爱被粉丝戏称为“重女”。 \
        椎名 立希 (Shiina Taki) - 鼓手 (Dr.) \
        性格暴躁直率，对主唱灯有极强的保护欲，经常和爱音斗嘴",
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
