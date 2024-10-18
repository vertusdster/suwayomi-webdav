# 使用官方 Python 基础镜像
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 复制当前目录的内容到容器的 /app 目录
COPY . /app

# 安装所需的 Python 依赖项
# 假设你有一个 requirements.txt 文件，列出所有需要的依赖
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 如果没有 requirements.txt，直接安装 wsgidav 和 requests
# RUN pip install --no-cache-dir wsgidav requests

# 暴露 WebDAV 服务运行的端口（你使用了 8080）
EXPOSE 8080

# 设置容器启动时执行的命令
CMD ["python", "main.py"]
