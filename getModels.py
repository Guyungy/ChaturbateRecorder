import requests
import sys
import re
import configparser
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from bs4 import BeautifulSoup
import certifi
import time
import logging

# 配置日志记录
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

# 配置读取
Config = configparser.ConfigParser()
Config.read(sys.path[0] + "/config.conf")
genders = re.sub(' ', '', Config.get('settings', 'genders')).split(",")
lastPage = {'female': 100, 'couple': 100, 'trans': 100, 'male': 100}
MAX_RETRIES = int(Config.get('settings', 'maxRetries', fallback=3))
REQUEST_TIMEOUT = int(Config.get('settings', 'requestTimeout', fallback=8))

# 全局队列
q = Queue()
online = []

# 获取在线模型的函数
def get_online_models(page, gender):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            URL = f"https://chaturbate.com/{gender}-cams/?page={page}"
            result = requests.get(URL, timeout=REQUEST_TIMEOUT, verify=certifi.where())
            result.raise_for_status()
            soup = BeautifulSoup(result.text, 'lxml')
            
            if lastPage[gender] == 100:
                endless_links = soup.findAll('a', {'class': 'endless_page_link'})
                if len(endless_links) >= 2:
                    lastPage[gender] = int(endless_links[-2].string)
                else:
                    lastPage[gender] = page
            
            active_page = soup.findAll('li', {'class': 'active'})
            if len(active_page) >= 2 and int(active_page[1].string) == page:
                LIST = soup.findAll('ul', {'class': 'list'})
                if LIST:
                    models = LIST[0].find_all('div', {'class': 'title'})
                    return [model.find_all('a', href=True)[0].string.lower()[1:] for model in models]
            break
        except (requests.exceptions.RequestException, IndexError, ValueError) as e:
            logging.error(f"Attempt {attempt} failed for gender {gender} page {page}: {e}")
            time.sleep(1)  # 重试前等待 1 秒
    return []

# 获取所有模型的函数
def get_models():
    workers = []
    online_models = []

    # 将所有任务添加到队列中
    for gender in genders:
        pages = 2 if gender == 'couple' else 30
        for i in range(1, pages):
            q.put((i, gender))

    # 使用线程池来执行任务
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        while not q.empty():
            page, gender = q.get()
            futures.append(executor.submit(get_online_models, page, gender))

        # 收集线程执行结果
        for future in as_completed(futures):
            result = future.result()
            if result:
                online_models.extend(result)

    return list(set(online_models))

if __name__ == '__main__':
    online = get_models()
    for model in online:
        print(model)
