#!/usr/bin/env python3
"""
机械狗音频播放SSH测试工具
测试AI生成的MP3在机械狗上的播放效果
"""

import subprocess
import os
import time
import tempfile

class DogAudioTester:
    def __init__(self, ssh_host="ysc@10.168.2.77"):
        self.ssh_host = ssh_host
        self.dog_speaker_device = 'hw:1,0'
        self.fallback_devices = ['plughw:1,0', 'default']
        
    def run_ssh_command(self, command, timeout=30):
        """通过SSH执行机械狗上的命令"""
        try:
            ssh_cmd = ['ssh', self.ssh_host, command]
            print(f"🔧 SSH执行: {command}")
            
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
            
            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, result.stderr
                
        except subprocess.TimeoutExpired:
            return False, f"命令超时 ({timeout}秒)"
        except Exception as e:
            return False, str(e)
    
    def upload_file_to_dog(self, local_file, remote_path):
        """上传文件到机械狗"""
        try:
            scp_cmd = ['scp', local_file, f"{self.ssh_host}:{remote_path}"]
            print(f"📤 上传文件: {local_file} → {remote_path}")
            
            result = subprocess.run(scp_cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print("✅ 文件上传成功")
                return True
            else:
                print(f"❌ 文件上传失败: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ 上传异常: {e}")
            return False
    
    def test_mp3_conversion_and_play(self, mp3_file):
        """测试MP3转换和播放的完整流程"""
        print(f"\n🧪 测试MP3文件: {mp3_file}")
        print("=" * 40)
        
        if not os.path.exists(mp3_file):
            print(f"❌ MP3文件不存在: {mp3_file}")
            return False
        
        mp3_size = os.path.getsize(mp3_file)
        print(f"📊 MP3文件大小: {mp3_size} bytes")
        
        # 步骤1: 分析本地MP3格式
        print("\n📝 步骤1: 分析MP3格式")
        probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', mp3_file]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        
        if probe_result.returncode == 0:
            import json
            info = json.loads(probe_result.stdout)
            
            for stream in info.get('streams', []):
                if stream.get('codec_type') == 'audio':
                    sample_rate = stream.get('sample_rate')
                    channels = stream.get('channels')
                    duration = float(stream.get('duration', 0))
                    print(f"🎵 MP3格式: {sample_rate}Hz, {channels}声道, {duration:.2f}秒")
                    break
        else:
            print(f"❌ 无法分析MP3格式: {probe_result.stderr}")
            return False
        
        # 步骤2: 本地转换为机械狗格式
        print("\n📝 步骤2: 转换为机械狗WAV格式 (48kHz立体声)")
        temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temp_wav.close()
        
        convert_cmd = [
            'ffmpeg', '-y', '-i', mp3_file,
            '-ar', '48000',          # 48kHz采样率
            '-ac', '2',              # 立体声
            '-acodec', 'pcm_s16le',  # 16-bit PCM
            '-f', 'wav', temp_wav.name
        ]
        
        convert_result = subprocess.run(convert_cmd, capture_output=True, text=True)
        
        if convert_result.returncode == 0:
            wav_size = os.path.getsize(temp_wav.name)
            print(f"✅ 转换成功: {wav_size} bytes")
        else:
            print(f"❌ 转换失败: {convert_result.stderr}")
            os.unlink(temp_wav.name)
            return False
        
        # 步骤3: 上传WAV文件到机械狗
        print("\n📝 步骤3: 上传WAV文件到机械狗")
        remote_wav_path = f"/tmp/test_audio_{int(time.time())}.wav"
        
        if not self.upload_file_to_dog(temp_wav.name, remote_wav_path):
            os.unlink(temp_wav.name)
            return False
        
        # 清理本地临时文件
        os.unlink(temp_wav.name)
        
        # 步骤4: 在机械狗上测试播放
        print("\n📝 步骤4: 在机械狗上测试播放")
        
        # 首先检查文件是否上传成功
        success, output = self.run_ssh_command(f"ls -la {remote_wav_path}")
        if success:
            print(f"✅ 文件上传确认: {output.strip()}")
        else:
            print(f"❌ 文件上传验证失败: {output}")
            return False
        
        # 测试不同的播放设备
        devices_to_test = [
            ('hw:1,0', 'USB音频设备'),
            ('plughw:1,0', 'USB音频设备(插件)'),
            ('default', '默认设备')
        ]
        
        for device, description in devices_to_test:
            print(f"\n🔊 测试 {description} ({device})...")
            
            play_command = f"aplay -D {device} {remote_wav_path}"
            success, output = self.run_ssh_command(play_command, timeout=15)
            
            if success:
                print(f"✅ {description} 播放成功!")
                
                # 清理远程文件
                self.run_ssh_command(f"rm -f {remote_wav_path}")
                return True
            else:
                print(f"❌ {description} 播放失败: {output}")
        
        # 清理远程文件
        self.run_ssh_command(f"rm -f {remote_wav_path}")
        return False
    
    def test_dog_audio_system(self):
        """测试机械狗音频系统状态"""
        print("\n🔍 检查机械狗音频系统状态")
        print("=" * 40)
        
        # 检查音频设备
        print("📝 检查音频设备列表:")
        success, output = self.run_ssh_command("aplay -l")
        if success:
            print("✅ 音频设备:")
            print(output)
        else:
            print(f"❌ 无法获取音频设备: {output}")
        
        # 检查音量设置
        print("\n📝 检查音量设置:")
        success, output = self.run_ssh_command("amixer -c 1 get PCM")
        if success:
            print("🔊 音量信息:")
            print(output)
        else:
            print(f"⚠️ 无法获取音量信息: {output}")
        
        # 检查音频权限
        print("\n📝 检查用户音频权限:")
        success, output = self.run_ssh_command("groups")
        if success and 'audio' in output:
            print("✅ 用户在audio组中")
        else:
            print("⚠️ 用户可能不在audio组中，这可能影响音频播放")

def main():
    """主测试函数"""
    print("🤖 机械狗音频播放SSH测试工具")
    print("=" * 60)
    print("🎯 目标: 测试AI生成的MP3在机械狗上的播放")
    print("🔗 连接: SSH到机械狗进行远程测试")
    print("📋 流程: MP3分析 → WAV转换 → 上传 → 远程播放测试")
    print()
    
    tester = DogAudioTester()
    
    # 检查SSH连接
    print("🔗 测试SSH连接...")
    success, output = tester.run_ssh_command("echo 'SSH连接测试'")
    if not success:
        print(f"❌ SSH连接失败: {output}")
        print("💡 请确保:")
        print("  1. SSH密钥已配置")
        print("  2. 机械狗IP地址正确 (10.168.2.77)")
        print("  3. 用户名正确 (ysc)")
        return
    
    print("✅ SSH连接成功")
    
    # 测试机械狗音频系统
    tester.test_dog_audio_system()
    
    # 查找AI回复的MP3文件
    print("\n🔍 查找AI回复MP3文件...")
    mp3_files = []
    
    # 查找response.mp3或类似文件
    for filename in os.listdir('.'):
        if filename.endswith('.mp3') and ('response' in filename or 'processed' in filename or 'ai_' in filename):
            mp3_files.append(filename)
    
    if not mp3_files:
        print("❌ 没有找到AI回复的MP3文件")
        print("💡 请先进行一次对话生成response.mp3文件")
        print("💡 或者将AI回复文件重命名为response.mp3")
        return
    
    # 测试每个MP3文件
    success_count = 0
    for mp3_file in mp3_files:
        if tester.test_mp3_conversion_and_play(mp3_file):
            success_count += 1
    
    # 总结结果
    print("\n" + "=" * 60)
    print(f"📊 测试结果: {success_count}/{len(mp3_files)} 个MP3文件播放成功")
    
    if success_count > 0:
        print("🎉 AI音频播放修复成功!")
        print("✅ 机械狗现在可以播放AI回复了")
    else:
        print("❌ AI音频播放仍有问题")
        print("🔍 可能需要:")
        print("  1. 检查机械狗音频驱动")
        print("  2. 调整音频设备配置")
        print("  3. 验证音频格式转换")

if __name__ == "__main__":
    main()
