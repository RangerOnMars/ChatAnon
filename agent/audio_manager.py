import asyncio
import queue
import random
import signal
import threading
import time
import uuid
import wave
from dataclasses import dataclass
from typing import Optional, Dict, Any

import pyaudio
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
from aec import create_aec, AcousticEchoCanceller


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    # level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


@dataclass
class AudioConfig:
    """音频配置数据类"""
    format: str
    bit_size: int
    channels: int
    sample_rate: int
    chunk: int


class AudioDeviceManager:
    """音频设备管理类，处理音频输入输出"""

    def __init__(self, input_config: AudioConfig, output_config: AudioConfig, enable_aec: bool = True):
        self.input_config = input_config
        self.output_config = output_config
        self.pyaudio = pyaudio.PyAudio()
        self.input_stream: Optional[pyaudio.Stream] = None
        self.output_stream: Optional[pyaudio.Stream] = None
        
        # AEC回音消除器
        self.enable_aec = enable_aec
        self.aec: Optional[AcousticEchoCanceller] = None
        if enable_aec:
            self.aec = create_aec(
                aec_type="basic",
                sample_rate=input_config.sample_rate,
                frame_size=input_config.chunk,
                filter_length=1024,  # 64ms @ 16kHz
                step_size=0.5,
                echo_suppress_factor=0.02,
                residual_suppress_factor=0.01
            )

    def open_input_stream(self) -> pyaudio.Stream:
        """打开音频输入流"""
        # p = pyaudio.PyAudio()
        self.input_stream = self.pyaudio.open(
            format=self.input_config.bit_size,
            channels=self.input_config.channels,
            rate=self.input_config.sample_rate,
            input=True,
            frames_per_buffer=self.input_config.chunk
        )
        return self.input_stream

    def open_output_stream(self) -> pyaudio.Stream:
        """打开音频输出流"""
        self.output_stream = self.pyaudio.open(
            format=self.output_config.bit_size,
            channels=self.output_config.channels,
            rate=self.output_config.sample_rate,
            output=True,
            frames_per_buffer=self.output_config.chunk
        )
        return self.output_stream

    def cleanup(self) -> None:
        """清理音频设备资源"""
        for stream in [self.input_stream, self.output_stream]:
            if stream:
                stream.stop_stream()
                stream.close()
        self.pyaudio.terminate()
    
    def process_input_audio(self, audio_data: bytes) -> bytes:
        """处理输入音频（应用AEC回音消除）"""
        if self.enable_aec and self.aec:
            return self.aec.process_near_end_signal(audio_data)
        return audio_data
    
    def process_output_audio(self, audio_data: bytes) -> bytes:
        """处理输出音频（记录远端信号用于AEC）"""
        if self.enable_aec and self.aec:
            self.aec.add_far_end_signal(audio_data)
        return audio_data
    
    def get_aec_stats(self) -> Dict[str, Any]:
        """获取AEC统计信息"""
        if self.enable_aec and self.aec:
            return self.aec.get_stats()
        return {}
    
    def reset_aec(self) -> None:
        """重置AEC"""
        if self.enable_aec and self.aec:
            self.aec.reset()


class DialogSession:
    """对话会话管理类"""
    is_audio_file_input: bool

    def __init__(self, ws_config: Dict[str, Any], output_audio_format: str = "pcm", audio_file_path: str = ""):

        self.audio_file_path = audio_file_path
        self.is_audio_file_input = self.audio_file_path != ""
        if self.is_audio_file_input:
            self.quit_event = asyncio.Event()

        self.session_id = str(uuid.uuid4())
        self.client = RealtimeDialogClient(config=ws_config, session_id=self.session_id,
                                           output_audio_format=output_audio_format)
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
        self.audio_queue = queue.Queue()
        if not self.is_audio_file_input:
            self.audio_device = AudioDeviceManager(
                AudioConfig(**config.input_audio_config),
                AudioConfig(**config.output_audio_config),
                enable_aec=True  # 启用AEC回音消除
            )
            # 初始化音频队列和输出流
            self.output_stream = self.audio_device.open_output_stream()
            # 启动播放线程
            self.is_recording = True
            self.is_playing = True
            self.player_thread = threading.Thread(target=self._audio_player_thread)
            self.player_thread.daemon = True
            self.player_thread.start()
            # 控制用户是否允许说话（按空格切换）
            self.speaking = False
            # 启动键盘监听线程，用于检测空格按下以切换说话状态
            self._keyboard_thread = threading.Thread(target=self._keyboard_listener_thread)
            self._keyboard_thread.daemon = True
            self._keyboard_thread.start()

    def _audio_player_thread(self):
        """音频播放线程"""
        while self.is_playing:
            try:
                # 从队列获取音频数据
                audio_data = self.audio_queue.get(timeout=1.0)
                if audio_data is not None:
                    # 处理输出音频（记录远端信号用于AEC）
                    processed_audio = self.audio_device.process_output_audio(audio_data)
                    self.output_stream.write(processed_audio)
            except queue.Empty:
                # 队列为空时等待一小段时间
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
            if not self.is_audio_file_input:
                logger.debug(f"收到音频数据包，大小: {len(audio_data)} 字节")
                # Write audio data to output stream
                self.audio_queue.put(audio_data)
            self.audio_buffer += audio_data
        elif response['message_type'] == 'SERVER_FULL_RESPONSE':
            print(f"服务器响应: {response}")
            event = response.get('event')
            payload_msg = response.get('payload_msg', {})

            if event == 450:
                print(f"清空缓存音频: {response['session_id']}")
                while not self.audio_queue.empty():
                    try:
                        self.audio_queue.get_nowait()
                    except queue.Empty:
                        continue
                self.is_user_querying = True

            if event == 350:
                logger.info("TTS生成开始")

            if event == 350 and self.is_sending_chat_tts_text and payload_msg.get("tts_type") in ["chat_tts_text", "external_rag"]:
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
                logger.info("收到ASR结果:{}".format(self.latest_asr_result[0].get("text", "")))
                # print("ASR结果:", self.latest_asr_result[0].get("text", ""))
                # print(payload_msg)
                # if random.randint(0, 100000)%1 == 0:
                #     self.is_sending_chat_tts_text = True
                #     asyncio.create_task(self.trigger_chat_tts_text())
                #     asyncio.create_task(self.trigger_chat_rag_text())
            
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
        print(f"receive keyboard Ctrl+C")
        self.is_recording = False
        self.is_playing = False
        self.is_running = False

    def _keyboard_listener_thread(self):
        """在独立线程中监听标准输入的按键（非阻塞）；按空格切换说话/静音状态。"""
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
        """发送静音音频"""
        silence_data = b'\x00' * 320
        await self.client.task_request(silence_data)

    async def process_microphone_input(self) -> None:
        await self.client.say_hello()
        """处理麦克风输入"""
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

    async def start(self) -> None:
        """启动对话会话"""
        try:
            await self.client.connect()

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



            await self.client.finish_session()
            while not self.is_session_finished:
                await asyncio.sleep(0.1)
            await self.client.finish_connection()
            await asyncio.sleep(0.1)
            await self.client.close()
        except Exception as e:
            print(f"会话错误: {e}")
        finally:
            if not self.is_audio_file_input:
                self.audio_device.cleanup()


