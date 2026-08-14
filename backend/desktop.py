"""桌面入口：进程内起 FastAPI，再开一个原生窗口指向它。

- 关闭窗口 = 退出整个应用（服务线程随进程结束，不残留后台进程）。
- 若端口上已有一个实例在跑（比如上次没关干净），直接复用它开窗。
- 加 --server 参数，或所在环境没有 WebView 组件（如未装 WebKitGTK 的
  Linux）时，退化为「起服务 + 打开系统浏览器」。
用法：python desktop.py [--server]
"""
from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser

HOST = "127.0.0.1"
PORT = 8642     # 固定专用端口，避开常用的 8000/5173


def _port_open(timeout: float = 0.3) -> bool:
    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex((HOST, PORT)) == 0


def _wait_ready(timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open():
            return True
        time.sleep(0.2)
    return False


def _start_server():
    if _port_open():
        return
    import uvicorn
    from app.main import app

    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    if not _wait_ready():
        raise SystemExit("后端启动失败：请在终端运行 desktop.py 查看报错")


def main():
    url = f"http://{HOST}:{PORT}"

    if "--server" not in sys.argv:
        try:
            import webview
        except ImportError:
            print("未找到 WebView 组件（Linux 需要 gir1.2-webkit2-4.1），改用浏览器打开。")
        else:
            _start_server()
            webview.create_window("合账", url, width=1280, height=840, min_size=(960, 640))
            webview.start()
            return

    _start_server()
    webbrowser.open(url)
    print(f"合账 LedgerFuse 运行中：{url}（Ctrl+C 退出）")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
