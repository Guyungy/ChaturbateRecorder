import requests
import sys
import re
import configparser
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from bs4 import BeautifulSoup

# 配置读取
Config = configparser.ConfigParser()
Config.read(sys.path[0] + "/config.conf")
genders = re.sub(' ', '', Config.get('settings', 'genders')).split(",")
lastPage = {'female': 100, 'couple': 100, 'trans': 100, 'male': 100}

# 全局队列
q = Queue()
online = []

# 获取在线模型的函数
def get_online_models(page, gender):
    attempt = 1
    while attempt <= 3:
        try:
            URL = f"https://chaturbate.com/{gender}-cams/?page={page}"
            result = requests.get(URL, timeout=8)
            result.raise_for_status()
            soup = BeautifulSoup(result.text, 'lxml')
            # 更新最后一页的信息
            if lastPage[gender] == 100:
                lastPage[gender] = int(soup.findAll('a', {'class': 'endless_page_link'})[-2].string)
            # 检查当前页是否是请求的页面
            if int(soup.findAll('li', {'class': 'active'})[1].string) == page:
                LIST = soup.findAll('ul', {'class': 'list'})[0]
                models = LIST.find_all('div', {'class': 'title'})
                return [model.find_all('a', href=True)[0].string.lower()[1:] for model in models]
            break
        except (requests.exceptions.RequestException, IndexError) as e:
            print(f"Attempt {attempt} failed for gender {gender} page {page}: {e}")
            attempt += 1
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
    with ThreadPoolExecutor(max_workers=10) as executor:
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
