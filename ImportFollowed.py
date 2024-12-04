import requests
import configparser
import sys
import pickle
import os
import threading
import datetime
from bs4 import BeautifulSoup

# 存储关注的模型列表
followed = []

# 读取配置文件，获取用户的设置信息
Config = configparser.ConfigParser()
Config.read(sys.path[0] + "/config.conf")
wishlist = Config.get('paths', 'wishlist')  # 获取关注模型的列表文件路径
username = Config.get('login', 'username')  # 用户名
password = Config.get('login', 'password')  # 密码

# 登录到网站的函数
def login():
    # 设置请求头，模拟浏览器行为
    s.headers = {
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36',
        'referer': 'https://chaturbate.com/',
        'origin': 'https://chaturbate.com',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'accept-encoding': 'gzip, deflate, br',
        'accept-language': 'en-US,en;q=0.8',
        'cache-control': 'max-age=0',
        'upgrade-insecure-requests': '1',
        'content-type': 'application/x-www-form-urlencoded',
    }

    # 获取登录页面，提取 CSRF 令牌以进行身份验证
    data = {'username': username, 'password': password, 'next': ''}
    result = s.get("https://chaturbate.com/")
    soup = BeautifulSoup(result.text, "html.parser")
    data['csrfmiddlewaretoken'] = soup.find('input', {'name': 'csrfmiddlewaretoken'}).get('value')

    # 发送包含登录信息的 POST 请求
    result = s.post('https://chaturbate.com/auth/login/?next=/', data=data, cookies=result.cookies)
    if not checkLogin(result):
        # 登录失败，打印错误信息并退出程序
        print('Login failed - please check your username and password are set correctly in the config file.')
        exit()
    else:
        print('Logged in')

# 检查登录是否成功的函数
def checkLogin(result):
    # 通过页面中是否存在用户信息的特定元素来判断
    soup = BeautifulSoup(result.text, "html.parser")
    if soup.find('div', {'id': 'user_information'}) is None:
        return False
    else:
        return True

# 获取用户关注的模型列表
def getModels():
    print("Getting followed models...")
    page = 1
    while True:
        # 逐页获取关注的模型信息
        result = s.get('https://chaturbate.com/followed-cams/?keywords=&page={}'.format(page))
        soup = BeautifulSoup(result.text, 'lxml')
        LIST = soup.findAll('ul', {'class': 'list'})[0]
        models = LIST.find_all('div', {'class': 'title'})
        for model in models:
            # 添加模型到关注列表
            followed.append(model.find_all('a', href=True)[0].string.lower()[1:])
        try:
            # 判断是否到达最后一页
            if int(soup.findAll('li', {'class': 'active'})[1].string) >= int(soup.findAll('a', {'class': 'endless_page_link'})[-2].string):
                break
            else:
                page += 1
        except IndexError:
            # 如果找不到分页信息，直接退出循环
            break

if __name__ == '__main__':
    try:
        # 使用上下文管理器管理会话，确保退出时会话关闭
        with requests.session() as s:
            # 如果已经存在登录信息的会话缓存，则直接加载
            if os.path.exists(sys.path[0] + "/" + username + '.pickle'):
                with open(sys.path[0] + "/" + username + '.pickle', 'rb') as f:
                    s = pickle.load(f)
            else:
                # 否则创建一个新的会话
                s = requests.session()

            # 启动守护线程来处理会话的异步任务，避免主程序退出时未完成任务导致异常
            def keep_session_alive():
                while True:
                    s.get('https://chaturbate.com/')
                    time.sleep(60)  # 每隔 60 秒发送一次请求，保持会话活跃
            session_thread = threading.Thread(target=keep_session_alive, daemon=True)
            session_thread.start()

            # 检查是否已经登录，如果未登录则执行登录过程
            result = s.get('https://chaturbate.com/')
            if not checkLogin(result):
                login()

            # 获取关注的模型列表
            getModels()
            print('{} followed models'.format(len(set(followed))))

            # 读取已有的关注列表文件，将其内容加入到关注列表中
            with open(wishlist, 'r') as f:
                wanted = list(set(f.readlines()))
            wanted = [m.strip('\n').split('chaturbate.com/')[-1].lower().strip().replace('/', '') for m in wanted]
            print('{} models currently in the wanted list'.format(len(wanted)))

            # 将新获取的关注模型加入到关注列表中
            followed.extend(wanted)

            # 更新关注列表文件
            with open(wishlist, 'w') as f:
                for model in set(followed):
                    f.write(model + '\n')
            print('{} models have been added to the wanted list'.format(len(set(followed)) - len(set(wanted))))

            # 保存会话信息到缓存文件，以便下次使用
            with open(sys.path[0] + "/" + username + '.pickle', 'wb') as f:
                pickle.dump(s, f)
    except Exception as e:
        print(f"An error occurred: {e}")
        with open('log.log', 'a') as log_file:
            log_file.write(f'\n{datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")} ERROR: {e}\n')
