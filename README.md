# ChaturbateRecorder（Chaturbate录制器）

鸣谢 @beaston02 和 @ahsand97

这是一个用于自动录制来自 **chaturbate.com** 的公共网络摄像头直播的脚本。

我已经在以下系统上测试过此脚本：Debian（7和8）、Ubuntu 14、FreeNAS 10（在 Jail 环境中）以及 Mac OS X（10.10.4）。理论上也可以运行在其他操作系统上。  
我没有 Windows 设备进行测试，但有其他用户在 Windows 上测试过。报告显示，6/21/17 的更新在 Windows 10 上可以正常运行，使用的是 Python 3.6.2（可能也支持 Python 3.5 及以上版本）。

## 环境需求
1. 创建虚拟环境
`conda create -n myenv python=3.11`

2. 激活虚拟环境
`conda activate myenv`

3. 安装所需模块，运行以下命令：  
`pip install streamlink bs4 lxml gevent`

4. 编辑配置文件 **config.conf**，设置以下参数：
- 录制文件的保存路径
- “wanted” 文件的路径
- 需要录制的性别分类
- 检查间隔（以秒为单位）

5. 运行脚本 
`python ChaturbateRecorder.py`

在 **wanted.txt** 文件中添加要录制的主播名称（每行只写一个主播的名称）。  
主播名称应与其聊天室 URL 中的用户名一致（例如 `https://chaturbate.com/{modelname}/`）。只需填写 URL 中的 `{modelname}` 部分，不需要填写完整的 URL。