import asyncio
import argparse

import config
from dialog_session import DialogSession

async def main() -> None:
    parser = argparse.ArgumentParser(description="Real-time Dialog Client")
    parser.add_argument("--format", type=str, default="pcm", help="The audio format (e.g., pcm, pcm_s16le).")
    parser.add_argument("--audio", type=str, default="", help="audio file send to server, if not set, will use microphone input.")
    parser.add_argument("--mode", type=str, default="voice", choices=["voice", "text"], 
                        help="Interaction mode: 'voice' for microphone/audio input, 'text' for text-based chat.")

    args = parser.parse_args()

    session = DialogSession(
        ws_config=config.ws_connect_config, 
        output_audio_format=args.format, 
        audio_file_path=args.audio,
        mode=args.mode
    )
    await session.start()

if __name__ == "__main__":
    asyncio.run(main())
