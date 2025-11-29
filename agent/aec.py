"""
声学回声消除（AEC）模块

本模块实现了基于自适应滤波器的声学回声消除功能，用于消除扬声器输出音频在麦克风中产生的回声。

主要特性：
1. 基于NLMS（归一化最小均方）算法的自适应滤波器
2. 双讲检测（Double Talk Detection）
3. 近端语音活动检测（VAD）
4. 残余回声抑制
5. 非线性处理

版本：v1.0.0
日期：2025-08-14
"""

import numpy as np
import threading
import time
from collections import deque
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class AcousticEchoCanceller:
    """声学回声消除器"""
    
    def __init__(self, 
                 sample_rate: int = 16000,
                 frame_size: int = 160,  # 10ms at 16kHz
                 filter_length: int = 1024,  # 滤波器长度（64ms）
                 step_size: float = 0.3,  # NLMS步长
                 regularization: float = 1e-3,  # 正则化参数
                 echo_suppress_factor: float = 0.05,  # 回音抑制因子
                 residual_suppress_factor: float = 0.02):  # 残余回音抑制因子
        
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        self.filter_length = filter_length
        self.step_size = step_size
        self.regularization = regularization
        self.echo_suppress_factor = echo_suppress_factor
        self.residual_suppress_factor = residual_suppress_factor
        
        # 自适应滤波器权重
        self.filter_weights = np.zeros(filter_length, dtype=np.float32)
        
        # 远端信号缓冲区（扬声器输出）
        self.far_end_buffer = deque(maxlen=filter_length * 2)
        
        # 能量估计
        self.far_end_energy = 0.0
        self.near_end_energy = 0.0
        self.echo_energy = 0.0
        self.error_energy = 0.0
        
        # 双讲检测参数
        self.double_talk_threshold = 2.5  # 进一步调整阈值
        self.is_double_talk = False
        self.geigel_threshold = 0.6  # 调整Geigel阈值
        
        # VAD参数
        self.vad_threshold = 1e-3
        self.noise_floor = 1e-5
        
        # 平滑因子
        self.alpha_energy = 0.95
        self.alpha_suppression = 0.9
        
        # 非线性处理参数
        self.nl_alpha = 0.85
        self.nl_beta = 0.6
        
        # 统计信息
        self.adaptation_count = 0
        self.convergence_factor = 0.0
        
        # 线程锁
        self.lock = threading.Lock()
        
        logger.info(f"AEC初始化: sample_rate={sample_rate}, "
                   f"filter_length={filter_length}, step_size={step_size}")
    
    def add_far_end_signal(self, audio_data: bytes) -> None:
        """添加远端信号（扬声器输出）"""
        with self.lock:
            # 将字节数据转换为浮点数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            
            # 添加到远端缓冲区
            self.far_end_buffer.extend(audio_array)
            
            # 更新远端能量
            far_end_power = np.mean(audio_array ** 2)
            self.far_end_energy = self.alpha_energy * self.far_end_energy + \
                                 (1 - self.alpha_energy) * far_end_power
    
    def process_near_end_signal(self, audio_data: bytes) -> bytes:
        """处理近端信号（麦克风输入），返回回音消除后的音频"""
        with self.lock:
            # 将字节数据转换为浮点数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            
            # 更新近端能量
            near_end_power = np.mean(audio_array ** 2)
            self.near_end_energy = self.alpha_energy * self.near_end_energy + \
                                  (1 - self.alpha_energy) * near_end_power
            
            # 如果远端缓冲区不够长，直接返回原始音频
            if len(self.far_end_buffer) < self.filter_length:
                return audio_data
            
            # 执行自适应滤波
            processed_audio = self._adaptive_filter(audio_array)
            
            # 应用非线性处理
            processed_audio = self._nonlinear_processing(processed_audio, audio_array)
            
            # 应用残余回音抑制
            processed_audio = self._residual_echo_suppression(processed_audio, audio_array)
            
            # 转换回int16格式
            processed_audio = np.clip(processed_audio, -1.0, 1.0)
            processed_audio_int16 = (processed_audio * 32767).astype(np.int16)
            
            return processed_audio_int16.tobytes()
    
    def _adaptive_filter(self, near_end_signal: np.ndarray) -> np.ndarray:
        """NLMS自适应滤波器"""
        output_signal = np.zeros_like(near_end_signal)
        
        for i in range(len(near_end_signal)):
            # 获取远端信号向量
            if len(self.far_end_buffer) >= self.filter_length + i:
                far_end_vector = np.array(list(self.far_end_buffer)[-self.filter_length-i:-i or None])
            else:
                output_signal[i] = near_end_signal[i]
                continue
            
            # 计算估计的回音
            estimated_echo = np.dot(self.filter_weights, far_end_vector)
            
            # 计算误差信号
            error_signal = near_end_signal[i] - estimated_echo
            output_signal[i] = error_signal
            
            # 更新能量估计
            echo_power = estimated_echo ** 2
            error_power = error_signal ** 2
            
            self.echo_energy = self.alpha_energy * self.echo_energy + \
                              (1 - self.alpha_energy) * echo_power
            self.error_energy = self.alpha_energy * self.error_energy + \
                               (1 - self.alpha_energy) * error_power
            
            # 双讲检测
            is_dt = self._detect_double_talk(near_end_signal[i], estimated_echo, far_end_vector)
            
            # 根据双讲状态调整自适应
            if not is_dt and self.far_end_energy > self.noise_floor:
                # 归一化因子
                norm_factor = np.dot(far_end_vector, far_end_vector) + self.regularization
                
                # 动态步长调整
                if self.adaptation_count < 1000:
                    # 初期快速收敛
                    adaptive_step = self.step_size * 1.5
                elif self.convergence_factor > 0.8:
                    # 收敛后减慢步长
                    adaptive_step = self.step_size * 0.3
                else:
                    # 正常步长
                    adaptive_step = self.step_size
                
                # NLMS权重更新
                update_factor = adaptive_step * error_signal / norm_factor
                self.filter_weights += update_factor * far_end_vector
                
                # 权重限制，防止发散
                weight_norm = np.linalg.norm(self.filter_weights)
                if weight_norm > 5.0:
                    self.filter_weights *= 5.0 / weight_norm
                
                self.adaptation_count += 1
        
        return output_signal
    
    def _detect_double_talk(self, near_end_sample: float, estimated_echo: float, 
                           far_end_vector: np.ndarray) -> bool:
        """改进的双讲检测"""
        # 计算当前帧的能量
        near_end_power = near_end_sample ** 2
        echo_power = estimated_echo ** 2
        far_end_power = np.mean(far_end_vector ** 2)
        
        # Geigel算法改进版
        if far_end_power > self.noise_floor:
            far_end_max = np.max(np.abs(far_end_vector))
            if far_end_max > 0:
                geigel_ratio = abs(near_end_sample) / far_end_max
                if geigel_ratio > self.geigel_threshold and near_end_power > self.vad_threshold:
                    self.is_double_talk = True
                    return True
        
        # 基于能量比的检测（更保守）
        if self.near_end_energy > self.vad_threshold and self.echo_energy > self.noise_floor:
            energy_ratio = self.near_end_energy / (self.echo_energy + self.regularization)
            if energy_ratio > self.double_talk_threshold:
                # 额外验证：检查近端能量是否显著大于远端能量
                if self.near_end_energy > 2.0 * self.far_end_energy:
                    self.is_double_talk = True
                    return True
        
        # 如果远端信号很弱，也认为是近端语音
        if self.far_end_energy < self.noise_floor and near_end_power > self.vad_threshold:
            self.is_double_talk = True
            return True
        
        self.is_double_talk = False
        return False
    
    def _nonlinear_processing(self, processed_signal: np.ndarray, 
                             original_signal: np.ndarray) -> np.ndarray:
        """非线性处理，进一步抑制残余回音"""
        if self.echo_energy < self.noise_floor:
            return processed_signal
        
        # 计算抑制因子
        if self.error_energy > 0 and self.echo_energy > 0:
            suppression_ratio = self.error_energy / (self.echo_energy + self.regularization)
            
            if suppression_ratio < self.nl_alpha:
                # 强抑制
                suppression_factor = self.nl_beta * suppression_ratio
            else:
                # 弱抑制或不抑制
                suppression_factor = 1.0
        else:
            suppression_factor = 1.0
        
        # 应用抑制
        return processed_signal * suppression_factor
    
    def _residual_echo_suppression(self, processed_signal: np.ndarray, 
                                  original_signal: np.ndarray) -> np.ndarray:
        """残余回音抑制"""
        if self.is_double_talk:
            # 双讲时不进行残余抑制
            return processed_signal
        
        # 计算信号能量比
        processed_energy = np.mean(processed_signal ** 2)
        original_energy = np.mean(original_signal ** 2)
        
        if original_energy > self.vad_threshold and processed_energy > 0:
            energy_reduction = processed_energy / (original_energy + self.regularization)
            
            # 如果能量减少不够，应用额外抑制
            if energy_reduction > self.residual_suppress_factor:
                additional_suppression = self.residual_suppress_factor / energy_reduction
                processed_signal *= additional_suppression
        
        return processed_signal
    
    def get_stats(self) -> dict:
        """获取AEC统计信息"""
        with self.lock:
            # 计算收敛因子
            if self.adaptation_count > 0:
                self.convergence_factor = min(self.adaptation_count / 10000.0, 1.0)
            
            # 计算回音抑制量
            if self.near_end_energy > 0 and self.error_energy > 0:
                echo_suppression_db = 10 * np.log10(
                    max(self.near_end_energy / self.error_energy, 1.0)
                )
            else:
                echo_suppression_db = 0.0
            
            return {
                "echo_suppression_db": echo_suppression_db,
                "near_end_energy": float(self.near_end_energy),
                "far_end_energy": float(self.far_end_energy),
                "echo_energy": float(self.echo_energy),
                "error_energy": float(self.error_energy),
                "filter_norm": float(np.linalg.norm(self.filter_weights)),
                "is_double_talk": self.is_double_talk,
                "convergence_factor": self.convergence_factor,
                "adaptation_count": self.adaptation_count,
                "buffer_size": len(self.far_end_buffer)
            }
    
    def reset(self):
        """重置AEC状态"""
        with self.lock:
            self.filter_weights.fill(0)
            self.far_end_buffer.clear()
            self.far_end_energy = 0.0
            self.near_end_energy = 0.0
            self.echo_energy = 0.0
            self.error_energy = 0.0
            self.is_double_talk = False
            self.adaptation_count = 0
            self.convergence_factor = 0.0
            
        logger.info("AEC已重置")


class AdvancedAEC(AcousticEchoCanceller):
    """高级AEC，包含频域处理"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # 频域参数
        self.fft_size = 512
        self.overlap = self.fft_size // 4
        
        # 频域缓冲区
        self.freq_buffer_near = deque(maxlen=self.fft_size)
        self.freq_buffer_far = deque(maxlen=self.fft_size)
        
        # 频域滤波器
        self.freq_filter = np.zeros(self.fft_size // 2 + 1, dtype=np.complex64)
        
        logger.info("高级AEC初始化完成")
    
    def _frequency_domain_processing(self, near_end: np.ndarray, far_end: np.ndarray) -> np.ndarray:
        """频域处理"""
        # 这里可以实现更复杂的频域自适应滤波
        # 当前简化实现
        return near_end


def create_aec(aec_type: str = "basic", **kwargs) -> AcousticEchoCanceller:
    """创建AEC实例的工厂函数"""
    if aec_type == "basic":
        return AcousticEchoCanceller(**kwargs)
    elif aec_type == "advanced":
        return AdvancedAEC(**kwargs)
    else:
        raise ValueError(f"不支持的AEC类型: {aec_type}")
