# 象哥 AI 硬件投资内参

抓取过去 24 小时的 AI 芯片、机器人、算力基础设施、硬件融资新闻（不足 10 条时扩展到一周），翻译成中文，可一键导出 PDF 内参。

- `ai_news_desktop.py`：桌面窗口版（刷新内参 / 生成 PDF），PDF 存到程序旁的 `reports/`
- `ai_news.py`：早期命令行版，终端里打印新闻表格
- `象哥AI硬件内参.spec`：PyInstaller 打包配置

## 运行

```bash
pip install -r requirements.txt
python ai_news_desktop.py
```

新闻源是 Google News RSS，需要能访问 Google 的网络；走代理时设置 `HTTP_PROXY` / `HTTPS_PROXY`。

翻译依次尝试 Google 翻译接口 → deep-translator Google → MyMemory，全部失败才保留英文。
PDF 优先用微软雅黑，找不到依次换等线、黑体，最后退回内置宋体。

## 打包成 exe

```bash
python -m PyInstaller --noconfirm 象哥AI硬件内参.spec
```

生成 `dist/象哥AI硬件内参.exe`。注意 spec 里源码路径写的是 `D:\Gemini\ai_news_desktop.py`，换目录打包需改成实际路径。
