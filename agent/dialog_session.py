import asyncio
import queue
import random
import signal
import threading
import time
import uuid
from typing import Optional, Dict, Any
import sys
import platform

if platform.system() != 'Windows':
    import termios
    import tty
    import select
else:
    import msvcrt

import config
import logging
from realtime_dialog_client import RealtimeDialogClient

logger = logging.getLogger(__name__)


class DialogSession:
    """对话会话管理类，支持语音和文本两种交互模式"""
    is_audio_file_input: bool

    def __init__(self, ws_config: Dict[str, Any], output_audio_format: str = "pcm", 
                 audio_file_path: str = "", mode: str = "voice"):
        """
        初始化对话会话
        
        Args:
            ws_config: WebSocket配置
            output_audio_format: 输出音频格式 ("pcm" 或 "pcm_s16le")
            audio_file_path: 音频文件路径（如果非空则从文件读取）
            mode: 交互模式 ("voice" 或 "text")
        """
        self.mode = mode.lower()
        if self.mode not in ["voice", "text"]:
            logger.warning(f"无效的模式 '{mode}'，使用默认模式 'voice'")
            self.mode = "voice"
        
        self.audio_file_path = audio_file_path
        self.is_audio_file_input = self.audio_file_path != ""
        if self.is_audio_file_input:
            self.quit_event = asyncio.Event()

        self.session_id = str(uuid.uuid4())
        self.client = RealtimeDialogClient(config=ws_config, session_id=self.session_id,
                                           output_audio_format=output_audio_format)
        
        # 导入pyaudio，voice/text模式都需要音频输出
        import pyaudio
        if output_audio_format == "pcm_s16le":
            config.output_audio_config["format"] = "pcm_s16le"
            config.output_audio_config["bit_size"] = pyaudio.paInt16

        self.is_running = True
        self.is_session_finished = False
        self.is_user_querying = False
        self.is_sending_chat_tts_text = False
        self.audio_buffer = b''
        self.latest_asr_result = ""

        signal.signal(signal.SIGINT, self._keyboard_signal)

        # 所有模式都初始化音频设备和播放线程
        from audio_manager import AudioDeviceManager, AudioConfig
        self.audio_queue = queue.Queue()
        self.audio_device = AudioDeviceManager(
            AudioConfig(**config.input_audio_config),
            AudioConfig(**config.output_audio_config),
            enable_aec=True  # 启用AEC回音消除
        )
        self.output_stream = self.audio_device.open_output_stream()
        self.is_playing = True
        self.player_thread = threading.Thread(target=self._audio_player_thread)
        self.player_thread.daemon = True
        self.player_thread.start()

        # 语音输入相关初始化
        if self.mode == "voice":
            if not self.is_audio_file_input:
                self.is_recording = True
                self.speaking = False
                self._keyboard_thread = threading.Thread(target=self._keyboard_listener_thread)
                self._keyboard_thread.daemon = True
                self._keyboard_thread.start()
        # 文本输入相关初始化
        elif self.mode == "text":
            self.text_input_queue = queue.Queue()
            self.is_text_input_running = True
            self._text_input_thread_handle = threading.Thread(target=self._text_input_thread)
            self._text_input_thread_handle.daemon = True
            self._text_input_thread_handle.start()

    def _audio_player_thread(self):
        """音频播放线程（voice/text模式均用）"""
        while self.is_playing:
            try:
                audio_data = self.audio_queue.get(timeout=1.0)
                if audio_data is not None:
                    processed_audio = self.audio_device.process_output_audio(audio_data)
                    self.output_stream.write(processed_audio)
            except queue.Empty:
                time.sleep(0.1)
            except Exception as e:
                print(f"音频播放错误: {e}")
                time.sleep(0.1)

    def handle_server_response(self, response: Dict[str, Any]) -> None:
        if response == {}:
            return
        """处理服务器响应"""
        if response['message_type'] == 'SERVER_ACK' and isinstance(response.get('payload_msg'), bytes):
            if self.is_sending_chat_tts_text:
                return
            audio_data = response['payload_msg']
            # 所有模式都播放音频
            self.audio_queue.put(audio_data)
            self.audio_buffer += audio_data
        elif response['message_type'] == 'SERVER_FULL_RESPONSE':
            if self.mode == "text":
                # 文本模式下打印详细信息
                event = response.get('event')
                payload_msg = response.get('payload_msg', {})
                
                # 打印TTS文本内容（如果有）
                if event == 350:
                    tts_type = payload_msg.get("tts_type", "")
                    if tts_type:
                        logger.info(f"TTS类型: {tts_type}")
                
                # 打印ASR识别结果
                if event == 451:
                    if payload_msg.get("results"):
                        self.latest_asr_result = payload_msg.get("results")
                        
                if event == 459:
                    if self.latest_asr_result:
                        asr_text = self.latest_asr_result[0].get("text", "")
                        if asr_text:
                            print(f"\n[识别] {asr_text}")
                    self.is_user_querying = False
                    
                # 打印对话响应文本
                if event == 350 and payload_msg.get("text"):
                    print(f"[回复] {payload_msg.get('text')}")
            else:
                # 语音模式下的原有逻辑
                print(f"服务器响应: {response}")
            
            event = response.get('event')
            payload_msg = response.get('payload_msg', {})

            if event == 450:
                print(f"清空缓存音频: {response['session_id']}")
                if self.mode == "voice":
                    while not self.audio_queue.empty():
                        try:
                            self.audio_queue.get_nowait()
                        except queue.Empty:
                            continue
                self.is_user_querying = True

            if event == 350:
                logger.info("TTS生成开始")

            if event == 350 and self.is_sending_chat_tts_text and payload_msg.get("tts_type") in ["chat_tts_text", "external_rag"]:
                if self.mode == "voice":
                    while not self.audio_queue.empty():
                        try:
                            self.audio_queue.get_nowait()
                        except queue.Empty:
                            continue
                self.is_sending_chat_tts_text = False
            if event == 451:
                if payload_msg.get("results"):
                    self.latest_asr_result = payload_msg.get("results")
            if event == 459:
                self.is_user_querying = False
                if self.mode == "voice":
                    logger.info("收到ASR结果:{}".format(self.latest_asr_result[0].get("text", "") if self.latest_asr_result else ""))
            
        elif response['message_type'] == 'SERVER_ERROR':
            logger.warning(f"服务器返回错误: {response}")
            raise Exception("服务器错误")

    async def trigger_chat_tts_text(self):
        """概率触发发送ChatTTSText请求"""
        print("hit ChatTTSText event, start sending...")
        await self.client.chat_tts_text(
            is_user_querying=self.is_user_querying,
            start=True,
            end=False,
            content="这是第一轮TTS的开始和中间包事件，这两个合而为一了。",
        )
        await self.client.chat_tts_text(
            is_user_querying=self.is_user_querying,
            start=False,
            end=True,
            content="这是第一轮TTS的结束事件。",
        )
        await asyncio.sleep(10)
        await self.client.chat_tts_text(
            is_user_querying=self.is_user_querying,
            start=True,
            end=False,
            content="这是第二轮TTS的开始和中间包事件，这两个合而为一了。",
        )
        await self.client.chat_tts_text(
            is_user_querying=self.is_user_querying,
            start=False,
            end=True,
            content="这是第二轮TTS的结束事件。",
        )

    def _keyboard_signal(self, sig, frame):
        print(f"\nreceive keyboard Ctrl+C")
        self.is_recording = False
        if hasattr(self, 'is_playing'):
            self.is_playing = False
        if hasattr(self, 'is_text_input_running'):
            self.is_text_input_running = False
        self.is_running = False

    def _keyboard_listener_thread(self):
        """在独立线程中监听标准输入的按键（非阻塞）；按空格切换说话/静音状态。（仅语音模式）"""
        if platform.system() == 'Windows':
            print("按空格键切换说话/静音（当前: 静音）")
            try:
                while getattr(self, 'is_running', True):
                    if msvcrt.kbhit():
                        ch = msvcrt.getch()
                        if ch == b' ':
                            # 切换说话状态
                            self.speaking = not getattr(self, 'speaking', False)
                            state = '允许说话' if self.speaking else '关闭说话（静音）'
                            print(f"已切换: {state}")
                    time.sleep(0.05)
            except Exception as e:
                print(f"键盘监听线程错误: {e}")
            return

        fd = sys.stdin.fileno()
        try:
            old_settings = termios.tcgetattr(fd)
        except Exception:
            old_settings = None

        try:
            # 将stdin设置为raw模式以捕获单个按键
            if old_settings is not None:
                tty.setcbreak(fd)

            print("按空格键切换说话/静音（当前: 静音）")
            while getattr(self, 'is_running', True):
                # 使用select进行非阻塞检查
                rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
                if rlist:
                    ch = sys.stdin.read(1)
                    if ch == ' ':
                        # 切换说话状态
                        self.speaking = not getattr(self, 'speaking', False)
                        state = '允许说话' if self.speaking else '关闭说话（静音）'
                        print(f"已切换: {state}")
                        # 当关闭说话时，确保不会发送非零音频（下一帧会被置零）
                        if not self.speaking:
                            # 如果需要可以清理或重置其他缓冲区，这里仅打印提示
                            pass
                else:
                    # 没有输入，休眠短暂时间以避免占用CPU
                    time.sleep(0.05)
        except Exception as e:
            print(f"键盘监听线程错误: {e}")
        finally:
            # 恢复终端设置
            try:
                if old_settings is not None:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass

    def _text_input_thread(self):
        """文本输入线程（仅文本模式）"""
        print("文本模式已启动。输入 'quit' 或 'exit' 退出，输入 Ctrl+C 强制退出。")
        print("请输入您的问题：")
        
        while self.is_text_input_running:
            try:
                user_input = input("> ").strip()
                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("正在退出...")
                    self.is_running = False
                    self.is_text_input_running = False
                    break
                elif user_input:
                    # 将用户输入放入队列
                    self.text_input_queue.put(user_input)
            except EOFError:
                # 处理Ctrl+D
                print("\n正在退出...")
                self.is_running = False
                self.is_text_input_running = False
                break
            except Exception as e:
                print(f"读取输入错误: {e}")
                time.sleep(0.1)

    async def receive_loop(self):
        try:
            while True:
                response = await self.client.receive_server_response()
                self.handle_server_response(response)
                if 'event' in response and (response['event'] == 152 or response['event'] == 153):
                    print(f"receive session finished event: {response['event']}")
                    self.is_session_finished = True
                    break
                if self.is_audio_file_input and 'event' in response and response['event'] == 359:
                    print(f"receive tts ended event")
                    self.is_session_finished = True
                    break
        except asyncio.CancelledError:
            print("接收任务已取消")
        except Exception as e:
            print(f"接收消息错误: {e}")

    async def process_audio_file(self) -> None:
        """处理音频文件输入（仅语音模式）"""
        import wave
        await self.process_audio_file_input(self.audio_file_path)
        while not self.quit_event.is_set():  # 循环直到退出信号被触发
            try:
                await asyncio.sleep(0.01)
                if self.quit_event.is_set():
                    break

                # 发送静音音频
                await self.process_silence_audio()
            except Exception as e:
                print(f"发送音频失败: {e}")
                raise  # 抛出异常终止循环

    async def process_audio_file_input(self, audio_file_path: str) -> None:
        """读取并发送音频文件（仅语音模式）"""
        import wave
        # 读取WAV文件
        with wave.open(audio_file_path, 'rb') as wf:
            chunk_size = config.input_audio_config["chunk"]
            print(f"开始处理音频文件: {audio_file_path}")

            # 分块读取并发送音频数据
            while True:
                audio_data = wf.readframes(chunk_size)
                if not audio_data:
                    break  # 文件读取完毕

                await self.client.task_request(audio_data)

            print(f"音频文件处理完成，等待服务器响应...")
    
    async def process_silence_audio(self) -> None:
        """发送静音音频（仅语音模式）"""
        silence_data = b'\x00' * 320
        await self.client.task_request(silence_data)

    async def process_microphone_input(self) -> None:
        """处理麦克风输入（仅语音模式）"""
        await self.client.say_hello()
        stream = self.audio_device.open_input_stream()
        print("已打开麦克风，请讲话...")
        print("🎙️  AEC回音消除已启用")
        
        # AEC统计计数器
        frame_count = 0

        while self.is_recording:
            try:
                # 添加exception_on_overflow=False参数来忽略溢出错误
                audio_data = stream.read(config.input_audio_config["chunk"], exception_on_overflow=False)
                
                # 应用AEC回音消除
                processed_audio = self.audio_device.process_input_audio(audio_data)

                # 如果当前不允许说话（静音模式），则将所有数据置0（发送静音）
                if not getattr(self, 'speaking', False):
                    processed_audio = b'\x00' * len(processed_audio)

                await self.client.task_request(processed_audio)
                
                # 每隔一段时间打印AEC统计信息
                frame_count += 1
                if frame_count % 500 == 0:  # 每500帧打印一次
                    stats = self.audio_device.get_aec_stats()
                    if stats:
                        print(f"🔊 AEC统计: 回音抑制={stats.get('echo_suppression_db', 0):.1f}dB, "
                              f"收敛度={stats.get('convergence_factor', 0):.2f}, "
                              f"双讲={stats.get('is_double_talk', False)}, "
                              f"滤波器范数={stats.get('filter_norm', 0):.3f}")
                
                await asyncio.sleep(0.01)  # 避免CPU过度使用
            except Exception as e:
                print(f"读取麦克风数据出错: {e}")
                await asyncio.sleep(0.1)  # 给系统一些恢复时间

    async def process_text_input(self) -> None:
        """处理文本输入（文本模式，语音输出）"""
        await self.client.say_hello()
        print("\n等待服务器准备就绪...")
        await asyncio.sleep(1)
        while self.is_running:
            try:
                try:
                    user_text = self.text_input_queue.get_nowait()
                    if user_text:
                        print(f"\n[发送] {user_text}")
                        await self.client.chat_text_query(user_text)
                        await asyncio.sleep(0.1)
                except queue.Empty:
                    await asyncio.sleep(0.1)
            except Exception as e:
                print(f"发送文本查询失败: {e}")
                await asyncio.sleep(0.5)

    async def start(self) -> None:
        """启动对话会话"""
        try:
            await self.client.connect()

            if self.mode == "voice":
                if self.is_audio_file_input:
                    asyncio.create_task(self.process_audio_file())
                    await self.receive_loop()
                    self.quit_event.set()
                    await asyncio.sleep(0.1)
                else:
                    asyncio.create_task(self.process_microphone_input())
                    asyncio.create_task(self.receive_loop())
                    while self.is_running:
                        await asyncio.sleep(0.1)
            
            elif self.mode == "text":
                asyncio.create_task(self.process_text_input())
                asyncio.create_task(self.receive_loop())
                while self.is_running:
                    await asyncio.sleep(0.1)

            await self.client.finish_session()
            while not self.is_session_finished:
                await asyncio.sleep(0.1)
            await self.client.finish_connection()
            await asyncio.sleep(0.1)
            await self.client.close()
        except Exception as e:
            print(f"会话错误: {e}")
        finally:
            if self.mode == "voice" and not self.is_audio_file_input:
                self.audio_device.cleanup()
