# 小红书测试题生成台 — web 控制台服务(8090)
#
# 服务器自托管模式:DEPLOY_MODE=static,PUBLIC_BASE_URL 指向本服务域名/地址,
# 生成的测试页与封面图由 /quiz 静态路由自托管,不依赖 GitHub。
# 运行: docker run -p 8090:8090 -v redbook_data:/app/data -v redbook_output:/app/output \
#        -e DEEPSEEK_API_KEY=... -e PUBLIC_BASE_URL=https://your.domain redbook-web-console
#
# 构建源均为国内镜像(清华 apt/pip + npmmirror playwright),国内网络构建友好。

FROM python:3.13-slim

# 清华 apt 源(bookworm 用 deb822 格式的 debian.sources)
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    || sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list

# git(gh_pages 模式兜底)+ 中文字体(Playwright 截图必需,否则封面图中文豆腐块)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# Playwright Chromium + 其系统依赖(cover_shots 截图引擎);chromium 走 npmmirror
ENV PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/
RUN python -m playwright install --with-deps chromium

COPY . .

ENV DEPLOY_MODE=static
EXPOSE 8090

CMD ["python", "web_console.py"]
