from dataclasses import dataclass
from typing import Optional, Dict, Any

import pyaudio
import logging
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



