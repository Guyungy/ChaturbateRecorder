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
import certifi  # 确保已安装 certifi

if os.name == 'nt':
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

mainDir = Path(sys.path[0])
Config = configparser.ConfigParser()
setting = {}

recording = []
hilos = []

# 全局关闭事件
shutdown_event = threading.Event()

# 清屏函数
def cls():
    os.system('cls' if os.name == 'nt' else 'clear')

# 读取配置文件
def readConfig():
    global setting

    config_path = mainDir / 'config.conf'
    if not config_path.exists():
        print("配置文件 config.conf 不存在。请确保配置文件位于脚本所在目录。")
        sys.exit(1)

    Config.read(config_path)

    try:
        setting = {
            'save_directory': Config.get('paths', 'save_directory'),
            'wishlist': Config.get('paths', 'wishlist'),
            'interval': int(Config.get('settings', 'checkInterval')),
            'postProcessingCommand': Config.get('settings', 'postProcessingCommand'),
            'genders': [gender.strip().lower() for gender in Config.get('settings', 'genders').split(',')],
            'username': Config.get('login', 'username'),
            'password': Config.get('login', 'password')
        }
        setting['postProcessingThreads'] = int(Config.get('settings', 'postProcessingThreads')) if Config.get('settings', 'postProcessingThreads') else 1
    except (configparser.NoSectionError, configparser.NoOptionError, ValueError) as e:
        print(f"配置文件错误: {e}")
        sys.exit(1)

    # 检查用户名和密码
    if not setting['username'] or not setting['password']:
        print("用户名或密码未设置。请在配置文件的 [login] 部分填写 username 和 password。")
        sys.exit(1)

    # 检查 wishlist 文件是否存在
    wishlist_path = Path(setting['wishlist'])
    if not wishlist_path.exists():
        print(f"wishlist 文件不存在: {wishlist_path}")
        sys.exit(1)

    # 创建保存目录
    save_path = Path(setting["save_directory"])
    if not save_path.exists():
        try:
            save_path.mkdir(parents=True, exist_ok=True)
            print(f"已创建保存目录: {save_path}")
        except Exception as e:
            print(f"无法创建保存目录 {save_path}: {e}")
            sys.exit(1)

# 后处理函数
def postProcess():
    while not shutdown_event.is_set():
        try:
            parameters = processingQueue.get(timeout=1)
            if parameters is None:
                break  # 停止线程
            model = parameters['model']
            path = parameters['path']
            filename = os.path.split(path)[-1]
            directory = os.path.dirname(path)
            file = os.path.splitext(filename)[0]
            try:
                subprocess.run(setting['postProcessingCommand'].split() + [path, filename, directory, model, file, 'cam4'], check=True)
            except subprocess.CalledProcessError as e:
                with open('log.log', 'a+') as f:
                    f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} 后处理错误: {e}\n')
        except queue.Empty:
            continue

# 模型类，用于处理流媒体的下载和管理
class Modelo(threading.Thread):
    def __init__(self, modelo):
        threading.Thread.__init__(self)
        self.modelo = modelo
        self._stopevent = threading.Event()
        self.file = None
        self.online = None
        self.lock = threading.Lock()
        self.session = None
        self.stream = None

    def run(self):
        global recording, hilos
        print(f"启动模型线程: {self.modelo}")
        while not shutdown_event.is_set() and not self._stopevent.is_set():
            isOnline = self.isOnline()
            if not isOnline:
                print(f"模型 {self.modelo} 不在线")
                self.online = False
                time.sleep(10)  # 等待一段时间后重新检查
                continue
            else:
                print(f"模型 {self.modelo} 在线，开始录制")
                model_dir = Path(setting['save_directory']) / self.modelo
                model_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.datetime.fromtimestamp(time.time()).strftime("%Y.%m.%d_%H.%M.%S")
                self.file = model_dir / f'{timestamp}_{self.modelo}.ts'
                try:
                    self.session = streamlink.Streamlink()
                    streams = self.session.streams(f'hlsvariant://{isOnline}')
                    if 'best' not in streams:
                        raise ValueError("未找到适合的流。")
                    self.stream = streams['best']
                    with self.stream.open() as fd, open(self.file, 'wb') as f:
                        self.lock.acquire()
                        recording.append(self)
                        for index, hilo in enumerate(hilos):
                            if hilo.modelo == self.modelo:
                                del hilos[index]
                                break
                        self.lock.release()
                        start_time = time.time()
                        while not (self._stopevent.is_set() or shutdown_event.is_set() or os.fstat(f.fileno()).st_nlink == 0):
                            current_time = time.time()
                            elapsed = current_time - start_time
                            if elapsed >= 1800:  # 30分钟 = 1800秒
                                print(f"模型 {self.modelo} 已录制30分钟，正在停止并保存文件。")
                                break
                            try:
                                data = fd.read(1024)
                                if not data:
                                    break
                                f.write(data)
                            except Exception as e:
                                with open('log.log', 'a+') as log_file:
                                    log_file.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} 流错误: {e}\n')
                                break
                    if setting['postProcessingCommand']:
                        processingQueue.put({'model': self.modelo, 'path': str(self.file)})
                except Exception as e:
                    with open('log.log', 'a+') as f:
                        f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} 异常: {e}\n')
                    self.stop()
                finally:
                    self.exceptionHandler()

    def exceptionHandler(self):
        self.stop()
        self.online = False
        self.lock.acquire()
        if self in recording:
            recording.remove(self)
        self.lock.release()
        try:
            file = Path(self.file)
            if file.is_file() and file.stat().st_size <= 1024:
                file.unlink()
        except Exception as e:
            with open('log.log', 'a+') as f:
                f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} 异常: {e}\n')
        finally:
            # 显式关闭会话，以确保后台任务停止
            if self.stream:
                try:
                    self.stream.close()
                except Exception as e:
                    with open('log.log', 'a+') as f:
                        f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} 流关闭错误: {e}\n')
            if self.session:
                try:
                    self.session.close()
                except Exception as e:
                    with open('log.log', 'a+') as f:
                        f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} 会话关闭错误: {e}\n')
                self.session = None

    def isOnline(self):
        try:
            # 临时绕过 SSL 验证（不推荐）
            resp = requests.get(
                f'https://chaturbate.com/api/chatvideocontext/{self.modelo}/',
                verify=False  # 添加此参数绕过 SSL 验证
            )
            # 如果需要，也可以使用 certifi 提供的证书
            # resp = requests.get(
            #     f'https://chaturbate.com/api/chatvideocontext/{self.modelo}/',
            #     verify=certifi.where()
            # )
            data = resp.json()
            print(f"检查模型 {self.modelo} 的在线状态: {data}")
            if 'hls_source' in data:
                return data['hls_source']
            else:
                return False
        except Exception as e:
            with open('log.log', 'a+') as f:
                f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} 在线检查错误: {e}\n')
            return False

    def stop(self):
        self._stopevent.set()
        try:
            # 停止流会话
            if self.stream:
                self.stream.close()
            if self.session:
                self.session.close()
            # 删除小于1KB的残留文件
            if hasattr(self, 'file') and self.file:
                if os.path.exists(self.file) and os.path.isfile(self.file):
                    if os.path.getsize(self.file) <= 1024:
                        os.remove(self.file)
        except Exception as e:
            with open('log.log', 'a+') as log_file:
                log_file.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} 停止错误: {e}\n')

class CleaningThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.interval = 0
        self.lock = threading.Lock()

    def run(self):
        global hilos, recording
        while not shutdown_event.is_set():
            self.lock.acquire()
            # 只保留活跃的线程
            hilos = [hilo for hilo in hilos if hilo.is_alive() or hilo.online]
            self.lock.release()
            for i in range(10, 0, -1):
                self.interval = i
                if shutdown_event.is_set():
                    break
                time.sleep(1)

class AddModelsThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.wanted = []
        self.lock = threading.Lock()
        self.repeatedModels = []
        self.counterModel = 0

    def run(self):
        global hilos, recording
        lines = Path(setting['wishlist']).read_text().splitlines()
        self.wanted = [x.lower() for x in lines if x]
        self.lock.acquire()
        try:
            aux = []
            for model in self.wanted:
                if shutdown_event.is_set():
                    break
                if model in aux:
                    self.repeatedModels.append(model)
                else:
                    aux.append(model)
                    self.counterModel += 1
                    if not isModelInListofObjects(model, hilos) and not isModelInListofObjects(model, recording):
                        thread = Modelo(model)
                        thread.start()
                        hilos.append(thread)
            for hilo in recording:
                if hilo.modelo not in aux:
                    hilo.stop()
        finally:
            self.lock.release()

# 检查模型是否在对象列表中
def isModelInListofObjects(obj, lista):
    return any(i.modelo == obj for i in lista)

if __name__ == '__main__':
    try:
        readConfig()
        if setting['postProcessingCommand']:
            processingQueue = queue.Queue()
            postprocessingWorkers = [threading.Thread(target=postProcess, daemon=True) for _ in range(setting['postProcessingThreads'])]
            for t in postprocessingWorkers:
                t.start()
        cleaningThread = CleaningThread()
        cleaningThread.start()
        while not shutdown_event.is_set():
            readConfig()
            addModelsThread = AddModelsThread()
            addModelsThread.start()
            for i in range(setting['interval'], 0, -1):
                if shutdown_event.is_set():
                    break
                cls()
                if addModelsThread.repeatedModels:
                    print('以下模型在愿望列表中出现多次: [' + ', '.join(model for model in addModelsThread.repeatedModels) + ']')
                print(f'{len(hilos):02d} 个活跃线程（每个非录制模型一个线程），在 {cleaningThread.interval:02d} 秒内清理死线程或非在线线程，愿望列表中有 {addModelsThread.counterModel:02d} 个模型')
                print(f'在线线程（模型）: {len(recording):02d}')
                print('以下模型正在被录制:')
                for hiloModelo in recording:
                    print(f'  模型: {hiloModelo.modelo}  -->  文件: {os.path.basename(hiloModelo.file)}')
                print(f'下次检查将在 {i:02d} 秒后进行\r', end='')
                time.sleep(1)
            addModelsThread.join()
    except KeyboardInterrupt:
        print("\n正在优雅地关闭...")
        shutdown_event.set()  # 设置全局关闭事件

        # 停止所有 Modelo 线程
        for hilo in hilos:
            hilo.stop()
        for hilo in hilos:
            hilo.join()

        # 停止 CleaningThread
        cleaningThread.join()

        # 停止 AddModelsThread 如果它还在运行
        if 'addModelsThread' in locals() and addModelsThread.is_alive():
            addModelsThread.join()

        # 停止 post-processing workers
        if setting.get('postProcessingCommand'):
            # 发送停止信号
            for worker in postprocessingWorkers:
                processingQueue.put(None)
            for worker in postprocessingWorkers:
                worker.join()

        print("所有线程已安全关闭。")
        sys.exit(0)
    except Exception as e:
        with open('log.log', 'a+') as f:
            f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} 主循环错误: {e}\n')
