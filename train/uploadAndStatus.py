import base64
import os
import requests


host = "https://openspeech.bytedance.com"


def train(appid, token, audio_path, spk_id):
    url = host + "/api/v1/mega_tts/audio/upload"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer;" + token,
        "Resource-Id": "volc.megatts.voiceclone",
        # "Resource-Id": "seed-icl-1.0",
    }
    encoded_data, audio_format = encode_audio_file(audio_path)
    text = "喜欢少女乐队的小朋友你们好啊，我是吉他手千草爱音，关注邦多利，谢谢喵。\
            这是一段测试用的语音，爱音将阅读这一段对话，并生成音频，用于将语音模型和数据复制至火山引擎。"
    audios = [{"audio_bytes": encoded_data, "audio_format": audio_format, "text": text}]
    data = {"appid": appid, "speaker_id": spk_id, "audios": audios, "source": 2, "language": 0,"model_type": 1, "enable_audio_denoise": True}
    # data = {"appid": appid, "speaker_id": spk_id, "audios": audios, "source": 2, "language": 0, "model_type": 0 }
    # 额外参数
    extra_params = {}
    if extra_params:
        data["extra_params"] =  json.dumps(extra_params)
    response = requests.post(url, json=data, headers=headers)

    print("status code = ", response.status_code)
    if response.status_code != 200:
        raise Exception("train请求错误:" + response.text)
    print("headers = ", response.headers)
    print(response.json())


def get_status(appid, token, spk_id):
    url = host + "/api/v1/mega_tts/status"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer;" + token,
        "Resource-Id": "volc.megatts.voiceclone",
    }
    body = {"appid": appid, "speaker_id": spk_id}
    response = requests.post(url, headers=headers, json=body)
    print(response.json())


def encode_audio_file(file_path):
    with open(file_path, 'rb') as audio_file:
        audio_data = audio_file.read()
        encoded_data = str(base64.b64encode(audio_data), "utf-8")
        audio_format = os.path.splitext(file_path)[1][1:]  # 获取文件扩展名作为音频格式
        return encoded_data, audio_format


if __name__ == "__main__":
    from credentials import appid, token, spk_id
    train(appid=appid, token=token, audio_path="data/vocu_anon.mp3", spk_id=spk_id)
    get_status(appid=appid, token=token, spk_id=spk_id)
    