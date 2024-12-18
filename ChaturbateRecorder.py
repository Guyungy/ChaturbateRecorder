import time
import datetime
import os
import sys
import configparser
import streamlink
import subprocess
import queue
import requests
from pathlib import Path
import threading
import certifi
import random

if os.name == 'nt':
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

mainDir = Path(sys.path[0])
Config = configparser.ConfigParser()
setting = {}
shutdown_event = threading.Event()

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36',
]

def readConfig():
    global setting
    config_path = mainDir / 'config.conf'

    if not config_path.exists():
        print("配置文件 config.conf 不存在。")
        sys.exit(1)

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            Config.read_file(f)

        setting = {
            'save_directory': Config.get('paths', 'save_directory'),
            'wishlist': Config.get('paths', 'wishlist'),
            'interval': Config.getint('settings', 'checkInterval'),
            'postProcessingCommand': Config.get('settings', 'postProcessingCommand', fallback=''),
            'genders': [gender.strip().lower() for gender in Config.get('settings', 'genders').split(',')],
            'username': Config.get('login', 'username'),
            'password': Config.get('login', 'password'),
            'postProcessingThreads': Config.getint('settings', 'postProcessingThreads', fallback=1),
            'completed_directory': Config.get('paths', 'completed_directory', fallback=''),
            'proxy': Config.get('settings', 'proxy', fallback=''),
            'max_concurrent': Config.getint('settings', 'max_concurrent', fallback=5)
        }
    except (configparser.NoSectionError, configparser.NoOptionError, ValueError) as e:
        print(f"配置文件错误: {e}")
        sys.exit(1)
    except UnicodeDecodeError as e:
        print(f"编码错误: {e}")
        sys.exit(1)

class Modelo(threading.Thread):
    def __init__(self, modelo):
        super().__init__()
        self.modelo = modelo.strip()
        self._stopevent = threading.Event()
        self.file = None
        self.session = requests.Session()
        self.stream = None

        # 使用代理（如果配置了且非空）
        if setting['proxy']:
            self.session.proxies = {'http': setting['proxy'], 'https': setting['proxy']}

    def run(self):
        print(f"[{self.modelo}] 启动线程")
        if shutdown_event.is_set():
            return

        stream_url = self.isOnline()
        if not stream_url:
            print(f"[{self.modelo}] 无法获取在线源，结束")
            return

        print(f"[{self.modelo}] 在线，开始录制")
        self.recordStream(stream_url)
        print(f"[{self.modelo}] 录制结束")

    def isOnline(self):
        url = f'https://chaturbate.com/api/chatvideocontext/{self.modelo}/'
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Referer': f'https://chaturbate.com/{self.modelo}/',
            'X-Requested-With': 'XMLHttpRequest'
        }

        # 尝试多次获取，遇到429时使用指数退避
        max_attempts = 5
        base_delay = 300  # 初始等待时间(秒)，5分钟
        for attempt in range(1, max_attempts + 1):
            if shutdown_event.is_set():
                return None
            try:
                response = self.session.get(url, headers=headers, verify=certifi.where(), timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    return data.get('hls_source')
                elif response.status_code == 403:
                    print(f"[{self.modelo}] 403 错误，等待1分钟再试")
                    time.sleep(60)
                elif response.status_code == 429:
                    # 429：请求过多，使用指数退避
                    wait_time = base_delay * (2 ** (attempt - 1))
                    print(f"[{self.modelo}] 429 错误，请求过多，等待 {wait_time} 秒后再试")
                    time.sleep(wait_time)
                else:
                    print(f"[{self.modelo}] 状态码 {response.status_code}，尝试下一个，等待30秒")
                    time.sleep(30)
            except requests.exceptions.RequestException as e:
                print(f"[{self.modelo}] 请求错误: {e}, 等待30秒重试")
                time.sleep(30)
        return None

    def recordStream(self, stream_url):
        model_dir = Path(setting['save_directory']) / self.modelo
        model_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y.%m.%d_%H.%M.%S")
        self.file = model_dir / f'{timestamp}_{self.modelo}.ts'

        try:
            session = streamlink.Streamlink()
            # 设置streamlink选项，提高HLS稳定性
            session.set_option("hls-segment-attempts", 5)
            session.set_option("hls-segment-timeout", 30)
            session.set_option("hls-timeout", 120)
            session.set_option("hls-live-edge", 3)

            streams = session.streams(f'hlsvariant://{stream_url}')
            if 'best' not in streams:
                print(f"[{self.modelo}] 未找到合适流")
                return

            with streams['best'].open() as fd, open(self.file, 'wb') as f:
                print(f"[{self.modelo}] 开始录制 -> {self.file}")
                for data in fd:
                    if self._stopevent.is_set() or shutdown_event.is_set():
                        break
                    f.write(data)
        except Exception as e:
            print(f"[{self.modelo}] 录制错误: {e}")

    def stop(self):
        self._stopevent.set()
        if self.stream:
            self.stream.close()
        self.session.close()

if __name__ == '__main__':
    try:
        readConfig()
        models_queue = [m for m in Path(setting['wishlist']).read_text().splitlines() if m.strip()]

        active_threads = []
        # 使用配置文件中的 max_concurrent 值来决定同时启动多少个线程
        for _ in range(min(setting['max_concurrent'], len(models_queue))):
            model_name = models_queue.pop(0)
            t = Modelo(model_name)
            t.start()
            active_threads.append(t)

        # 当有线程结束后立即启动下一个模型线程，直到队列耗尽
        while not shutdown_event.is_set() and (active_threads or models_queue):
            # 检查哪些线程已结束
            finished = [t for t in active_threads if not t.is_alive()]
            # 移除结束的线程
            for t in finished:
                active_threads.remove(t)
                # 若有剩余模型，启动下一个
                if models_queue:
                    next_model = models_queue.pop(0)
                    nt = Modelo(next_model)
                    nt.start()
                    active_threads.append(nt)
            time.sleep(5)
    except KeyboardInterrupt:
        print("正在关闭...")
        shutdown_event.set()
        for t in active_threads:
            t.stop()
            t.join()
        print("所有线程已安全关闭。")
