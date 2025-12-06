#!/usr/bin/env python
"""
文本模式对话客户端
纯文本交互，无需音频设备
"""

import asyncio
import argparse

import config
from dialog_session import DialogSession


async def main() -> None:
    """启动文本模式对话客户端"""
    parser = argparse.ArgumentParser(description="Text-based Dialog Client")
    parser.add_argument("--format", type=str, default="pcm", 
                        help="The audio format for server responses (e.g., pcm, pcm_s16le). Note: Audio output is not played in text mode.")
    
    args = parser.parse_args()
    
    print("="*60)
    print("文本对话模式")
    print("="*60)
    print("说明：")
    print("  - 输入您的问题并按回车发送")
    print("  - 输入 'quit', 'exit' 或 'q' 退出")
    print("  - 按 Ctrl+C 强制退出")
    print("="*60)
    print()

    session = DialogSession(
        ws_config=config.ws_connect_config, 
        output_audio_format=args.format,
        mode="text"
    )
    
    await session.start()
    print("\n会话已结束。")


if __name__ == "__main__":
    asyncio.run(main())
