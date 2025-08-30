#!/usr/bin/env python3
"""
机械狗主控程序
"""

import subprocess
import tempfile
import os
import time
import threading
import json
import signal
import sys
from datetime import datetime

class DogController:
    def __init__(self, server_url="http://localhost:8114"):
        """机械狗控制器"""
        print("🤖 机械狗控制器初始化 ...")
        
        self.server_url = server_url.rstrip('/')
        
        # 音频设备配置
        self.MIC_DEVICE = 'hw:1,0'
        self.SPEAKER_DEVICE = 'hw:1,0'  # USB音频设备
        self.FALLBACK_SPEAKER = 'default'  # 系统默认设备
        
        # 预设音频文件
        self.NOTICE_AUDIO = 'notice.wav'  # "我在，有什么需要帮助的吗"
        
        # 系统状态
        self.is_awake = True  # 直接进入唤醒状态
        self.is_recording = False
        self.is_playing = False
        self.is_processing = False
        self.last_interaction_time = time.time()
        self.silence_timeout = 30.0  # 延长超时时间
        self.shutdown_flag = False
        
        # 音频设备锁 - 新增：防止设备冲突
        self.audio_device_lock = threading.Lock()
        self.last_play_time = 0
        self.device_cooldown = 0.5  # 设备冷却时间（秒）
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # 检查音频权限
        self.check_audio_permission()
        
        print("✅ 控制器初始化完成")
    
    def check_audio_permission(self):
        """检查用户音频权限"""
        try:
            success, output = self.run_local_command('groups')
            if success and 'audio' in output:
                print("✅ 用户在audio组中")
            else:
                print("⚠️ 用户可能不在audio组中，这可能影响音频播放")
                print("💡 请运行: sudo usermod -a -G audio $USER")
        except Exception as e:
            print(f"⚠️ 无法检查用户组: {e}")
    
    def run_local_command(self, command, timeout=10):
        """执行本地命令"""
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, result.stderr
        except subprocess.TimeoutExpired:
            return False, f"命令超时 ({timeout}秒)"
        except Exception as e:
            return False, str(e)
    
    def signal_handler(self, signum, frame):
        """处理系统信号"""
        print(f"\n🛑 收到信号 {signum}，正在安全关闭...")
        self.shutdown_flag = True
    
    def test_server_connection(self):
        """测试本地API服务器连接"""
        try:
            print("🔗 测试本地API服务器连接...")
            
            # 使用curl测试连接
            success, output = self.run_local_command(f'curl -s -m 5 "{self.server_url}/"')
            
            if success:
                print("✅ 本地API服务器连接成功")
                print(f"📝 服务器响应: {output[:100]}...")
                return True
            else:
                print(f"❌ 本地API服务器连接失败")
                print(f"💡 请确保在另一个终端运行: uvicorn main:app --host 0.0.0.0 --port 8114")
                print(f"🔍 错误信息: {output}")
                return False
                
        except Exception as e:
            print(f"❌ 连接测试失败: {e}")
            return False
    
    def set_volume(self, volume_percent=80):
        """设置音频音量"""
        try:
            self.run_local_command(f'amixer -c 1 set PCM {volume_percent}%')
            self.run_local_command(f'amixer -c 1 set Mic {volume_percent}%')
            print(f"🔊 音量设置为 {volume_percent}%")
        except Exception as e:
            print(f"⚠️ 音量设置失败: {e}")
    
    def wait_for_device_ready(self):
        """等待音频设备就绪"""
        current_time = time.time()
        time_since_last_play = current_time - self.last_play_time
        
        if time_since_last_play < self.device_cooldown:
            wait_time = self.device_cooldown - time_since_last_play
            print(f"⏳ 等待音频设备就绪: {wait_time:.2f}秒")
            time.sleep(wait_time)
    
    def play_beep(self):
        """播放简单提示音"""
        try:
            # 获取设备锁
            with self.audio_device_lock:
                self.wait_for_device_ready()
                
                self.is_playing = True
                print("🔊 播放提示音...")
                
                # 使用speaker-test播放简单提示音
                self.run_local_command(f'speaker-test -D {self.SPEAKER_DEVICE} -t sine -f 1000 -l 1', timeout=3)
                
                self.last_play_time = time.time()
            
        except Exception as e:
            print(f"❌ 提示音播放失败: {e}")
        finally:
            self.is_playing = False
    
    def record_audio(self, duration=3, purpose="录音"):
        """录音功能"""
        try:
            print(f"🎤 开始{purpose} {duration}秒...")
            self.is_recording = True
            
            # 创建临时文件
            temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_file.close()
            
            # 录音命令
            record_cmd = f'arecord -D {self.MIC_DEVICE} -f S16_LE -r 16000 -c 1 -d {duration} {temp_file.name}'
            
            success, output = self.run_local_command(record_cmd, timeout=duration+5)
            
            if success:
                file_size = os.path.getsize(temp_file.name)
                
                # 计算期望的最小文件大小 (16kHz, 16-bit, 单声道)
                expected_min_size = 16000 * 2 * 1 * duration * 0.3  # 至少30%的期望大小
                
                print(f"📊 录音文件信息: {file_size} bytes (期望最小: {int(expected_min_size)} bytes)")
                
                if file_size > expected_min_size:
                    print(f"✅ {purpose}完成: {file_size} bytes - 文件大小正常")
                    return temp_file.name
                else:
                    os.unlink(temp_file.name)
                    print(f"❌ 录音文件太小: {file_size} < {int(expected_min_size)} bytes")
                    print("💡 可能原因: 1) 麦克风音量太低 2) 录音期间没有说话 3) 麦克风设备问题")
                    return None
            else:
                print(f"❌ 录音失败: {output}")
                os.unlink(temp_file.name)
                return None
                
        except Exception as e:
            print(f"❌ 录音错误: {e}")
            return None
        finally:
            self.is_recording = False
    
    def test_microphone(self):
        """测试麦克风录音功能"""
        print("🎤 麦克风测试模式")
        print("=" * 40)
        
        try:
            # 测试短录音
            print("📝 测试1: 短录音 (3秒)")
            test_file = self.record_audio(duration=3, purpose="麦克风测试")
            
            if test_file:
                file_size = os.path.getsize(test_file)
                print(f"✅ 短录音成功: {file_size} bytes")
                
                # 尝试转换为M4A
                m4a_file = self.convert_wav_to_m4a(test_file)
                if m4a_file:
                    m4a_size = os.path.getsize(m4a_file)
                    print(f"✅ M4A转换成功: {m4a_size} bytes")
                    os.unlink(m4a_file)
                else:
                    print("❌ M4A转换失败")
                
                os.unlink(test_file)
            else:
                print("❌ 短录音失败")
            
            print("\n📝 测试2: 长录音 (6秒)")
            test_file = self.record_audio(duration=6, purpose="长时间测试")
            
            if test_file:
                file_size = os.path.getsize(test_file)
                print(f"✅ 长录音成功: {file_size} bytes")
                os.unlink(test_file)
            else:
                print("❌ 长录音失败")
                
            print("\n💡 建议:")
            print("- 如果录音文件太小，请检查麦克风音量")
            print("- 如果M4A转换失败，请检查ffmpeg安装")
            print("- 录音时请清晰说话，避免长时间静音")
            
        except Exception as e:
            print(f"❌ 麦克风测试失败: {e}")
    
    def test_audio_playback(self):
        """测试音频播放功能"""
        print("🔊 音频播放测试模式")
        print("=" * 40)
        
        try:
            # 测试1: 播放预设音频
            print("📝 测试1: 播放预设notice.wav文件")
            if os.path.exists(self.NOTICE_AUDIO):
                success = self.play_notice_audio()
                if success:
                    print("✅ 预设音频播放成功")
                else:
                    print("❌ 预设音频播放失败")
            else:
                print(f"⚠️ 预设音频文件不存在: {self.NOTICE_AUDIO}")
            
            # 测试2: 检查音频设备
            print("\n📝 测试2: 检查音频设备状态")
            success, output = self.run_local_command('aplay -l')
            
            if success:
                print("✅ 音频设备列表:")
                print(output)
                
                # 检查指定设备是否存在
                if self.SPEAKER_DEVICE in output:
                    print(f"✅ 指定设备 {self.SPEAKER_DEVICE} 可用")
                else:
                    print(f"⚠️ 指定设备 {self.SPEAKER_DEVICE} 未找到")
                    print("💡 可能需要修改SPEAKER_DEVICE设置")
            else:
                print(f"❌ 无法获取音频设备列表: {output}")
            
            # 测试3: 测试AI回复播放功能
            print("\n📝 测试3: 模拟AI回复播放")
            
            # 查找现有的MP3文件进行测试
            mp3_files = [f for f in os.listdir('.') if f.endswith('.mp3')]
            if mp3_files:
                test_mp3 = mp3_files[0]
                print(f"🎵 使用测试文件: {test_mp3}")
                
                success = self.convert_and_play_audio(test_mp3)
                if success:
                    print("✅ AI回复播放测试成功")
                else:
                    print("❌ AI回复播放测试失败")
            else:
                print("⚠️ 没有找到MP3文件进行播放测试")
                print("💡 请先进行一次对话生成MP3文件")
            
            # 测试4: 音量检查
            print("\n📝 测试4: 检查系统音量")
            success, output = self.run_local_command('amixer -c 1 get PCM')
            
            if success:
                print("🔊 当前音量设置:")
                print(output)
            else:
                print(f"⚠️ 无法获取音量信息: {output}")
                
        except Exception as e:
            print(f"❌ 音频播放测试失败: {e}")
    
    def convert_wav_to_m4a(self, wav_file):
        """将WAV文件转换为M4A格式"""
        try:
            print("🔧 转换WAV到M4A格式...")
            
            # 创建临时M4A文件
            temp_m4a = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
            temp_m4a.close()
            
            # 使用ffmpeg转换WAV到M4A
            ffmpeg_cmd = f'ffmpeg -y -i "{wav_file}" -c:a aac -b:a 128k "{temp_m4a.name}"'
            
            success, output = self.run_local_command(ffmpeg_cmd, timeout=15)
            
            if success:
                file_size = os.path.getsize(temp_m4a.name)
                print(f"✅ WAV转M4A成功: {file_size} bytes")
                return temp_m4a.name
            else:
                print(f"❌ WAV转M4A失败: {output}")
                os.unlink(temp_m4a.name)
                return None
                
        except Exception as e:
            print(f"❌ WAV转M4A错误: {e}")
            return None

    def call_ai_server(self, audio_file):
        """调用AI服务器（将WAV转换为M4A格式发送）"""
        try:
            print("🧠 发送音频到AI服务器...")
            self.is_processing = True
            
            # 将WAV转换为M4A格式（API要求）
            m4a_file = self.convert_wav_to_m4a(audio_file)
            
            if not m4a_file:
                print("❌ M4A转换失败，无法发送到API服务器")
                return None
            
            print("✅ 音频已转换为M4A格式，准备发送")
            
            # 创建临时响应文件
            temp_response = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            temp_response.close()
            
            # 使用curl发送M4A音频请求
            curl_cmd = f'curl -X POST -F "file=@{m4a_file}" --output "{temp_response.name}" --max-time 30 "{self.server_url}/process-audio/"'
            
            success, output = self.run_local_command(curl_cmd, timeout=35)
            
            # 清理临时M4A文件
            if m4a_file and m4a_file != audio_file:
                os.unlink(m4a_file)
            
            if success:
                file_size = os.path.getsize(temp_response.name)
                print(f"📊 服务器响应文件大小: {file_size} bytes")
                
                if file_size > 1000:
                    print(f"✅ AI服务器响应成功: {file_size} bytes")
                    print(f"📁 响应文件路径: {temp_response.name}")
                    
                    # 验证MP3文件格式
                    if self.validate_mp3_file(temp_response.name):
                        print("✅ MP3文件格式验证通过")
                        return temp_response.name
                    else:
                        print("⚠️ MP3文件可能有问题，但仍尝试播放")
                        return temp_response.name
                else:
                    print(f"❌ 服务器返回空响应: {file_size} bytes")
                    print("💡 可能原因: 1) API处理失败 2) 音频生成失败 3) 网络传输问题")
                    
                    # 检查响应文件内容
                    try:
                        with open(temp_response.name, 'rb') as f:
                            content = f.read(100)  # 读取前100字节
                        if b'error' in content.lower() or b'json' in content.lower():
                            print("🔍 响应可能包含错误信息，而不是音频数据")
                    except:
                        pass
                    
                    os.unlink(temp_response.name)
                    return None
            else:
                print(f"❌ 服务器请求失败")
                print(f"🔍 错误信息: {output}")
                os.unlink(temp_response.name)
                return None
                
        except Exception as e:
            print(f"❌ AI服务器调用错误: {e}")
            return None
        finally:
            self.is_processing = False
    
    def validate_mp3_file(self, mp3_file):
        """验证MP3文件是否有效"""
        try:
            # 使用ffprobe检查MP3文件
            probe_cmd = f'ffprobe -v quiet -print_format json -show_format -show_streams "{mp3_file}"'
            
            success, output = self.run_local_command(probe_cmd, timeout=10)
            
            if success:
                info = json.loads(output)
                
                # 检查是否有音频流
                audio_stream = None
                for stream in info.get('streams', []):
                    if stream.get('codec_type') == 'audio':
                        audio_stream = stream
                        break
                
                if audio_stream:
                    duration = float(info['format'].get('duration', 0))
                    codec = audio_stream.get('codec_name', '')
                    
                    print(f"🔍 MP3文件信息: {codec}编码, {duration:.2f}秒")
                    
                    if duration > 0.1:  # 至少0.1秒
                        return True
                    else:
                        print(f"⚠️ MP3文件时长太短: {duration}秒")
                        return False
                else:
                    print("❌ MP3文件中没有音频流")
                    return False
            else:
                print(f"❌ MP3文件验证失败: {output}")
                return False
                
        except Exception as e:
            print(f"⚠️ MP3验证错误: {e}")
            return True  # 验证失败不阻止播放
    
    def validate_wav_file(self, wav_file):
        """验证WAV文件是否有效"""
        try:
            probe_cmd = f'ffprobe -v quiet -print_format json -show_format -show_streams "{wav_file}"'
            success, output = self.run_local_command(probe_cmd, timeout=10)
            
            if success:
                info = json.loads(output)
                
                audio_stream = None
                for stream in info.get('streams', []):
                    if stream.get('codec_type') == 'audio':
                        audio_stream = stream
                        break
                
                if audio_stream:
                    duration = float(info['format'].get('duration', 0))
                    sample_rate = int(audio_stream.get('sample_rate', 0))
                    channels = int(audio_stream.get('channels', 0))
                    
                    print(f"🔍 WAV文件信息: {sample_rate}Hz, {channels}声道, {duration:.2f}秒")
                    
                    if duration > 0.1:
                        return True
                    else:
                        print(f"⚠️ WAV文件时长太短: {duration}秒")
                        return False
                else:
                    print("❌ WAV文件中没有音频流")
                    return False
            else:
                print(f"❌ WAV文件验证失败: {output}")
                return False
                
        except Exception as e:
            print(f"⚠️ WAV验证错误: {e}")
            return True
    
    def convert_notice_audio_format(self, input_file):
        """将notice.wav转换为扬声器兼容格式"""
        try:
            print("🔧 转换预设音频格式...")
            
            # 创建临时转换后的文件
            temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_wav.close()
            
            # 使用ffmpeg转换为扬声器格式（48kHz立体声）
            ffmpeg_cmd = f'ffmpeg -y -i "{input_file}" -ar 48000 -ac 2 -acodec pcm_s16le -f wav "{temp_wav.name}"'
            
            success, output = self.run_local_command(ffmpeg_cmd, timeout=15)
            
            if success:
                print("✅ 预设音频格式转换成功")
                return temp_wav.name
            else:
                print(f"❌ 预设音频格式转换失败: {output}")
                # 如果ffmpeg失败，尝试使用sox
                return self.convert_notice_with_sox(input_file)
                
        except Exception as e:
            print(f"❌ 预设音频转换错误: {e}")
            # 尝试sox作为备选
            return self.convert_notice_with_sox(input_file)
    
    def convert_notice_with_sox(self, input_file):
        """使用sox转换音频格式"""
        try:
            print("🔄 尝试使用sox转换...")
            
            temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_wav.close()
            
            # 使用sox转换
            sox_cmd = f'sox "{input_file}" -r 48000 -c 2 "{temp_wav.name}"'
            
            success, output = self.run_local_command(sox_cmd, timeout=10)
            
            if success:
                print("✅ sox转换成功")
                return temp_wav.name
            else:
                print(f"❌ sox转换失败: {output}")
                return None
                
        except Exception as e:
            print(f"❌ sox转换错误: {e}")
            return None

    def play_notice_audio(self):
        """播放预设的notice.wav文件"""
        try:
            if not os.path.exists(self.NOTICE_AUDIO):
                print(f"⚠️ 预设音频文件不存在: {self.NOTICE_AUDIO}")
                print("💡 请确保notice.wav文件在当前目录")
                return False
            
            print("🔊 播放预设回复: '我在，有什么需要帮助的吗'")
            
            # 获取设备锁
            with self.audio_device_lock:
                self.wait_for_device_ready()
                
                self.is_playing = True
                
                # 先转换音频格式
                converted_file = self.convert_notice_audio_format(self.NOTICE_AUDIO)
                
                if converted_file:
                    # 使用智能播放
                    success = self.smart_audio_play_locked(converted_file)
                    if success:
                        print("✅ 预设音频播放完成")
                        return True
                    else:
                        print("❌ 预设音频播放失败")
                        return False
                else:
                    # 如果转换失败，尝试直接播放（可能失败但值得尝试）
                    print("⚠️ 格式转换失败，尝试直接播放...")
                    
                    # 创建临时文件副本用于智能播放
                    import shutil
                    temp_copy = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    temp_copy.close()
                    shutil.copy2(self.NOTICE_AUDIO, temp_copy.name)
                    
                    success = self.smart_audio_play_locked(temp_copy.name)
                    if success:
                        print("✅ 直接播放成功")
                        return True
                    else:
                        print("❌ 直接播放也失败")
                        return False
                
        except Exception as e:
            print(f"❌ 预设音频播放错误: {e}")
            return False
        finally:
            self.is_playing = False
            self.last_play_time = time.time()

    def smart_audio_play_locked(self, wav_file):
        """智能音频播放（已获取设备锁）"""
        try:
            print(f"🎵 智能播放音频文件...")
            
            # 播放设备优先级列表
            devices_to_try = [
                ('hw:1,0', 'USB音频设备'),
                ('plughw:1,0', 'USB音频设备(插件)'),
                ('default', '系统默认设备'),
                (None, '自动选择设备')  # 不指定设备让系统自动选择
            ]
            
            for device, description in devices_to_try:
                try:
                    # 确保WAV文件存在且可读
                    if not os.path.exists(wav_file):
                        print(f"❌ WAV文件不存在: {wav_file}")
                        continue
                    
                    wav_size = os.path.getsize(wav_file)
                    if wav_size < 1000:
                        print(f"❌ WAV文件太小: {wav_size} bytes")
                        continue
                    
                    if device:
                        play_cmd = f'aplay -D "{device}" "{wav_file}"'
                        print(f"🔊 尝试使用 {description} ({device})...")
                    else:
                        play_cmd = f'aplay "{wav_file}"'
                        print(f"🔊 尝试使用 {description}...")
                    
                    print(f"🎵 播放命令: {play_cmd}")
                    
                    # 播放音频（无超时限制）
                    success, output = self.run_local_command(play_cmd)
                    
                    if success:
                        print(f"✅ 播放成功! 使用设备: {description}")
                        print(f"📊 播放输出: {output}")
                        
                        # 计算播放时长
                        try:
                            # 使用ffprobe获取音频时长
                            duration_cmd = f'ffprobe -v quiet -show_entries format=duration -of csv=p=0 "{wav_file}"'
                            success, duration_output = self.run_local_command(duration_cmd)
                            
                            if success:
                                duration = float(duration_output.strip())
                                print(f"⏱️ 音频时长: {duration:.2f}秒")
                        except:
                            pass
                        
                        # 更新成功的设备配置
                        if device and device != self.SPEAKER_DEVICE:
                            print(f"💡 建议更新SPEAKER_DEVICE为: {device}")
                        
                        os.unlink(wav_file)
                        return True
                    else:
                        print(f"❌ {description} 播放失败: {output}")
                        
                        # 检查常见错误
                        if "Device or resource busy" in output:
                            print("💡 设备忙碌，可能其他进程在使用音频设备")
                        elif "No such file or directory" in output:
                            print("💡 设备不存在或路径错误")
                        elif "Permission denied" in output:
                            print("💡 权限问题，可能需要音频组权限")
                        
                except Exception as e:
                    print(f"❌ {description} 播放异常: {e}")
                    continue
            
            # 所有设备都失败
            print("❌ 所有音频设备都无法播放")
            print("💡 可能的解决方案:")
            print("   1. 检查音频设备连接")
            print("   2. 检查系统音频服务")
            print("   3. 尝试重启音频服务: sudo systemctl restart alsa-state")
            print("   4. 检查用户权限: sudo usermod -a -G audio $USER")
            
            os.unlink(wav_file)
            return False
            
        except Exception as e:
            print(f"❌ 智能播放错误: {e}")
            if os.path.exists(wav_file):
                os.unlink(wav_file)
            return False

    def convert_and_play_audio(self, mp3_file):
        """将MP3转换为WAV并播放"""
        try:
            print("🔧 转换AI回复MP3到WAV格式用于播放...")
            
            # 首先检查输入MP3文件
            if not os.path.exists(mp3_file):
                print(f"❌ MP3文件不存在: {mp3_file}")
                return False
            
            mp3_size = os.path.getsize(mp3_file)
            print(f"📊 输入MP3文件大小: {mp3_size} bytes")
            
            # 验证MP3文件内容
            if not self.validate_mp3_file(mp3_file):
                print("⚠️ MP3文件验证失败，但继续尝试转换")
            
            # 创建临时WAV文件
            temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_wav.close()
            
            # 使用ffmpeg转换MP3到WAV（扬声器格式：48kHz立体声）
            ffmpeg_cmd = f'ffmpeg -y -i "{mp3_file}" -ar 48000 -ac 2 -acodec pcm_s16le -f wav "{temp_wav.name}"'
            
            print(f"🔧 FFmpeg转换命令: {ffmpeg_cmd}")
            success, output = self.run_local_command(ffmpeg_cmd, timeout=15)
            
            if success:
                print("✅ MP3转WAV转换成功")
                
                # 检查转换后的WAV文件
                wav_size = os.path.getsize(temp_wav.name)
                print(f"📊 转换后WAV文件大小: {wav_size} bytes")
                
                if wav_size > 1000:  # 确保文件不为空
                    print("🔊 开始播放AI回复...")
                    
                    # 验证WAV文件格式
                    if self.validate_wav_file(temp_wav.name):
                        print("✅ WAV文件格式验证通过")
                    else:
                        print("⚠️ WAV文件格式可能有问题")
                    
                    # 获取设备锁并播放
                    with self.audio_device_lock:
                        self.wait_for_device_ready()
                        
                        self.is_playing = True
                        
                        # 智能设备选择和播放
                        success = self.smart_audio_play_locked(temp_wav.name)
                        
                        if success:
                            print("🎉 AI回复播放成功!")
                        else:
                            print("❌ AI回复播放失败 - 所有设备都无法播放")
                            
                        return success
                else:
                    print(f"❌ 转换后的WAV文件为空: {wav_size} bytes")
                    print("💡 可能原因: MP3文件损坏或格式不支持")
                    os.unlink(temp_wav.name)
                    return False
            else:
                print(f"❌ MP3转WAV失败")
                print(f"🔍 FFmpeg错误: {output}")
                
                # 检查是否是MP3格式问题
                if "Invalid data found" in output:
                    print("💡 MP3文件可能不是标准格式或已损坏")
                elif "No such file" in output:
                    print("💡 输入文件路径问题")
                
                os.unlink(temp_wav.name)
                return False
                
        except Exception as e:
            print(f"❌ 音频处理错误: {e}")
            return False
        finally:
            self.is_playing = False
            self.last_play_time = time.time()
    
    def simple_wake_word_detect(self, audio_file):
        """简单唤醒词检测"""
        if not audio_file or not os.path.exists(audio_file):
            return False
            
        file_size = os.path.getsize(audio_file)
        # 简单判断：文件大小在合理范围内
        return 5000 < file_size < 100000
    
    def run_conversation_loop(self):
        """直接对话循环（无需唤醒词）"""
        print("💬 开始对话模式")
        print("🎤 随时可以说话，系统会自动处理您的语音")
        conversation_count = 0
        
        while not self.shutdown_flag:
            try:
                # 检查超时
                if time.time() - self.last_interaction_time > self.silence_timeout:
                    print(f"⏰ {self.silence_timeout}秒无对话，程序将退出")
                    break
                
                # 避免在处理时录音
                if self.is_processing or self.is_playing:
                    time.sleep(0.5)
                    continue
                
                # 录音等待用户输入 - 增加重试机制
                print(f"\n🎤 请说话... (对话轮次: {conversation_count + 1})")
                print("💡 请清晰地说话，确保麦克风能录到声音，按Ctrl+C退出")
                
                # 尝试录音，如果失败则重试
                audio_file = None
                retry_count = 0
                max_retries = 3
                
                while retry_count < max_retries and not audio_file:
                    if retry_count > 0:
                        print(f"🔄 录音重试 {retry_count}/{max_retries}")
                        print("💡 请靠近麦克风，大声清晰地说话")
                    
                    # 使用更长的录音时间，确保捕获完整语音
                    audio_file = self.record_audio(duration=6, purpose="对话录音")
                    retry_count += 1
                
                if audio_file:
                    # 短暂延迟，释放设备占用
                    time.sleep(0.5)
                    
                    # 调用AI服务器
                    response_audio = self.call_ai_server(audio_file)
                    
                    if response_audio:
                        # 播放AI服务器回复
                        if self.convert_and_play_audio(response_audio):
                            conversation_count += 1
                            print(f"✅ 对话轮次 {conversation_count} 完成")
                        
                        os.unlink(response_audio)
                    else:
                        # AI服务器处理失败，播放预设音频
                        print("❌ AI服务器处理失败，播放预设回复")
                        self.play_notice_audio()
                    
                    os.unlink(audio_file)
                    self.last_interaction_time = time.time()
                else:
                    print("🔇 多次尝试后仍无法录到有效音频")
                    print("💡 请检查: 1) 麦克风连接 2) 音量设置 3) 设备权限")
                    print("⏸️ 跳过此轮对话，继续等待...")
                
                time.sleep(1)  # 稍微延长等待时间
                
            except Exception as e:
                print(f"❌ 对话错误: {e}")
                time.sleep(2)
        
        print(f"\n🏁 对话结束 (共进行了{conversation_count}轮对话)")
    
    def run_wake_word_loop(self):
        """唤醒词检测循环"""
        print("🌙 等待唤醒词...")
        
        while not self.shutdown_flag:
            try:
                if not self.is_awake and not self.is_processing:
                    # 录音检测唤醒词
                    audio_file = self.record_audio(duration=3, purpose="唤醒词检测")
                    
                    if audio_file:
                        if self.simple_wake_word_detect(audio_file):
                            print("🌞 检测到唤醒词！")
                            self.is_awake = True
                            self.last_interaction_time = time.time()
                            
                            # 播放确认音
                            self.play_beep()
                            
                            # 启动对话模式
                            threading.Thread(target=self.run_conversation_loop, daemon=True).start()
                        
                        os.unlink(audio_file)
                
                time.sleep(0.5)
                
            except KeyboardInterrupt:
                print("\n👋 用户中断")
                break
            except Exception as e:
                print(f"❌ 唤醒检测错误: {e}")
                time.sleep(1)
    
    def run(self):
        """运行主程序"""
        print("=" * 60)
        print("🤖 机械狗语音助手")
        print("=" * 60)
        print(f"AI服务器: {self.server_url}")
        print(f"麦克风: {self.MIC_DEVICE}")
        print(f"扬声器: {self.SPEAKER_DEVICE}")
        print(f"对话超时: {self.silence_timeout}秒")
        print("=" * 60)
        
        # 测试服务器连接
        if not self.test_server_connection():
            print("❌ 无法连接AI服务器，请检查API服务是否启动")
            return
        
        # 设置音量
        self.set_volume(80)
        
        # 直接启动对话系统
        try:
            print("🚀 系统启动，直接进入对话模式...")
            self.run_conversation_loop()
        except KeyboardInterrupt:
            print("\n👋 用户中断，系统关闭")
        except Exception as e:
            print(f"❌ 系统运行错误: {e}")
        
        print("🔚 机械狗对话系统已退出")

if __name__ == "__main__":
    print("🤖 机械狗控制器启动")
    print("=" * 40)
    
    # 显示配置
    print("📋 系统配置:")
    print("AI服务器: http://localhost:8114")
    print("依赖: 仅使用系统命令 (curl, arecord, aplay, ffmpeg)")
    print("音频格式: WAV录音 → M4A发送 → MP3接收")
    print("模式: 直接对话模式（无需唤醒词）")
    print("💡 本地API服务器模式 - 确保API服务已在8114端口启动")
    
    print("\n🚀 启动前检查:")
    print("1. 请确保API服务器已在另一个终端启动:")
    print("   cd /tmp/RealTimeChat/")
    print("   uvicorn main:app --host 0.0.0.0 --port 8114")
    print("2. 确保音频设备 hw:1,0 可用")
    print("3. 确保notice.wav文件在当前目录（AI失败时的备用回复）")
    print("4. 启动后直接开始对话，无需唤醒词")
    
    print("\n🛠️ 选择启动模式:")
    print("1. 正常启动 (y)")
    print("2. 麦克风测试模式 (m)")
    print("3. 音频播放测试模式 (p)")
    print("4. 取消 (n)")
    
    choice = input("\n请选择 (y/m/p/N): ").strip().lower()
    
    if choice in ['m', 'mic', 'test']:
        # 麦克风测试模式
        try:
            controller = DogController()
            controller.test_microphone()
        except Exception as e:
            print(f"❌ 麦克风测试失败: {e}")
        exit(0)
    elif choice in ['p', 'play', 'audio']:
        # 音频播放测试模式
        try:
            controller = DogController()
            controller.test_audio_playback()
        except Exception as e:
            print(f"❌ 播放测试失败: {e}")
        exit(0)
    elif choice not in ['y', 'yes']:
        print("❌ 用户取消启动")
        exit(0)
    
    try:
        controller = DogController()
        controller.run()
    except KeyboardInterrupt:
        print("\n👋 用户中断")
    except Exception as e:
        print(f"❌ 启动失败: {e}")
    finally:
        print("🔚 程序结束")