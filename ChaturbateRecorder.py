import time
import datetime
import os
import threading
import sys
import configparser
import streamlink
import subprocess
import queue
import requests
from pathlib import Path

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

    Config.read(mainDir / 'config.conf')
    setting = {
        'save_directory': Config.get('paths', 'save_directory'),
        'wishlist': Config.get('paths', 'wishlist'),
        'interval': int(Config.get('settings', 'checkInterval')),
        'postProcessingCommand': Config.get('settings', 'postProcessingCommand'),
    }
    try:
        setting['postProcessingThreads'] = int(Config.get('settings', 'postProcessingThreads'))
    except ValueError:
        if setting['postProcessingCommand'] and not setting['postProcessingThreads']:
            setting['postProcessingThreads'] = 1

    save_path = Path(setting["save_directory"])
    if not save_path.exists():
        save_path.mkdir(parents=True)

# 后处理函数
def postProcess():
    while not shutdown_event.is_set():
        try:
            parameters = processingQueue.get(timeout=1)
            if parameters is None:
                break  # Stop the thread
            model = parameters['model']
            path = parameters['path']
            filename = os.path.split(path)[-1]
            directory = os.path.dirname(path)
            file = os.path.splitext(filename)[0]
            try:
                subprocess.run(setting['postProcessingCommand'].split() + [path, filename, directory, model, file, 'cam4'], check=True)
            except subprocess.CalledProcessError as e:
                with open('log.log', 'a+') as f:
                    f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} POST-PROCESS ERROR: {e}\n')
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
        isOnline = self.isOnline()
        if not isOnline:
            self.online = False
        else:
            self.online = True
            model_dir = Path(setting['save_directory']) / self.modelo
            model_dir.mkdir(parents=True, exist_ok=True)
            self.file = model_dir / f'{datetime.datetime.fromtimestamp(time.time()).strftime("%Y.%m.%d_%H.%M.%S")}_{self.modelo}.ts'
            try:
                self.session = streamlink.Streamlink()
                streams = self.session.streams(f'hlsvariant://{isOnline}')
                if 'best' not in streams:
                    raise ValueError("No suitable stream found for the model.")
                self.stream = streams['best']
                with self.stream.open() as fd, open(self.file, 'wb') as f:
                    self.lock.acquire()
                    recording.append(self)
                    for index, hilo in enumerate(hilos):
                        if hilo.modelo == self.modelo:
                            del hilos[index]
                            break
                    self.lock.release()
                    while not (self._stopevent.is_set() or shutdown_event.is_set() or os.fstat(f.fileno()).st_nlink == 0):
                        if self._stopevent.is_set() or shutdown_event.is_set():
                            break
                        try:
                            data = fd.read(1024)
                            if not data:
                                break
                            f.write(data)
                        except Exception as e:
                            with open('log.log', 'a+') as log_file:
                                log_file.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} STREAM ERROR: {e}\n')
                            break
                if setting['postProcessingCommand']:
                    processingQueue.put({'model': self.modelo, 'path': str(self.file)})
            except Exception as e:
                with open('log.log', 'a+') as f:
                    f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} EXCEPTION: {e}\n')
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
                f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} EXCEPTION: {e}\n')
        finally:
            # 显式关闭会话，以确保后台任务停止
            if self.stream:
                try:
                    self.stream.close()
                except Exception as e:
                    with open('log.log', 'a+') as f:
                        f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} STREAM CLOSE ERROR: {e}\n')
            if self.session:
                try:
                    self.session.close()
                except Exception as e:
                    with open('log.log', 'a+') as f:
                        f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} SESSION CLOSE ERROR: {e}\n')
                self.session = None

    def isOnline(self):
        try:
            resp = requests.get(f'https://chaturbate.com/api/chatvideocontext/{self.modelo}/')
            if 'hls_source' in resp.json():
                return resp.json()['hls_source']
            else:
                return False
        except Exception as e:
            with open('log.log', 'a+') as f:
                f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} IS-ONLINE CHECK ERROR: {e}\n')
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
                log_file.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} STOP ERROR: {e}\n')

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
                    print('The following models are more than once in wanted: [' + ', '.join(model for model in addModelsThread.repeatedModels) + ']')
                print(f'{len(hilos):02d} alive Threads (1 Thread per non-recording model), cleaning dead/not-online Threads in {cleaningThread.interval:02d} seconds, {addModelsThread.counterModel:02d} models in wanted')
                print(f'Online Threads (models): {len(recording):02d}')
                print('The following models are being recorded:')
                for hiloModelo in recording:
                    print(f'  Model: {hiloModelo.modelo}  -->  File: {os.path.basename(hiloModelo.file)}')
                print(f'Next check in {i:02d} seconds\r', end='')
                time.sleep(1)
            addModelsThread.join()
    except KeyboardInterrupt:
        print("\nGracefully shutting down...")
        shutdown_event.set()  # 设置全局关闭事件

        # 停止所有 Modelo 线程
        for hilo in hilos:
            hilo.stop()
        for hilo in hilos:
            hilo.join()

        # 停止 CleaningThread
        cleaningThread.join()

        # 停止 AddModelsThread 如果它还在运行
        if addModelsThread.is_alive():
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
            f.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} MAIN LOOP ERROR: {e}\n')
