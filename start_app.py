"""一键启动脚本 - 直接由 Python 处理，不再依赖 .bat
双击此 .pyw 文件即可启动（无黑色控制台窗口）；
或在 cmd 里执行：python start_app.py
"""
import os
import sys
import time
import socket
import subprocess
import webbrowser
import threading

# Windows 默认 GBK 控制台写不了所有 Unicode 字符，重新配置为 utf-8 + 替换
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def _safe_write(stream, text: str):
    try:
        stream.write(text)
        stream.flush()
    except UnicodeEncodeError:
        # 兜底：把写不出的字符替换为 ?
        enc = getattr(stream, "encoding", None) or "gbk"
        stream.write(text.encode(enc, errors="replace").decode(enc, errors="replace"))
        stream.flush()

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)
sys.path.insert(0, PROJECT_DIR)

PYTHON_EXE = r"D:\Users\CC\anaconda3\envs\aixcoder\python.exe"
PORT = 4444
LOG_FILE = os.path.join(PROJECT_DIR, "start.log")


def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    _safe_write(sys.stdout, line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def kill_port(port: int):
    """强制结束占用端口的进程"""
    try:
        out = subprocess.check_output(
            f'netstat -ano | findstr ":{port}"',
            shell=True, text=True, encoding="gbk", errors="ignore"
        )
    except subprocess.CalledProcessError:
        return
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}"):
            pids.add(parts[4])
    for pid in pids:
        try:
            subprocess.run(f"taskkill /F /PID {pid}",
                           shell=True, capture_output=True)
            log(f"已结束占用 {port} 端口的旧进程 PID={pid}")
        except Exception:
            pass


def open_browser_later(url: str, delay: float = 4.0):
    time.sleep(delay)
    try:
        webbrowser.open(url)
    except Exception as e:
        log(f"打开浏览器失败: {e}")


def main():
    # 清空旧日志
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        pass

    log("=" * 60)
    log("AI 量化分析终端 启动中")
    log("=" * 60)

    if not os.path.exists(PYTHON_EXE):
        log(f"[FATAL] 找不到 Python: {PYTHON_EXE}")
        log("请修改 start_app.py 中的 PYTHON_EXE 路径")
        try:
            input("按回车键退出...")
        except EOFError:
            pass
        sys.exit(1)

    log(f"Python: {PYTHON_EXE}")
    log(f"项目目录: {PROJECT_DIR}")

    kill_port(PORT)

    # 启动浏览器延迟任务
    threading.Thread(
        target=open_browser_later,
        args=(f"http://127.0.0.1:{PORT}",),
        daemon=True,
    ).start()
    log(f"将在 4 秒后自动打开浏览器 http://127.0.0.1:{PORT}")

    # 启动 Flask 服务（前台运行，关闭窗口 = 停止）
    log("正在启动 Flask 服务...")
    try:
        # 用 bytes 模式读 PIPE：Flask 子进程在 Windows 默认 GBK 输出，
        # 强制 encoding='utf-8' 会让 TextIOWrapper 抛 UnicodeDecodeError，
        # 导致 for 循环立刻结束、误判 Flask 退出。
        proc = subprocess.Popen(
            [PYTHON_EXE, "-u", "app.py"],
            cwd=PROJECT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
    except Exception as e:
        log(f"[FATAL] 启动失败: {e}")
        try:
            input("按回车键退出...")
        except EOFError:
            pass
        sys.exit(1)

    # 实时把 Flask 输出转写到控制台 + 日志（按行读 bytes，自己解码）
    def _emit_line(raw: bytes):
        # 优先尝试 utf-8，失败回退到 gbk
        for enc in ("utf-8", "gbk"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        _safe_write(sys.stdout, text)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass

    leftover = b""
    try:
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                # 进程结束，flush 剩余
                if leftover:
                    _emit_line(leftover)
                    leftover = b""
                break
            data = leftover + chunk
            # 按 \n 切
            *lines, leftover = data.split(b"\n")
            for line in lines:
                _emit_line(line + b"\n")
    except KeyboardInterrupt:
        log("收到中断信号，正在停止服务...")
        proc.terminate()
    finally:
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        log(f"Flask 进程已退出 (code={proc.returncode})")
        log("=" * 60)
        log("服务已停止。可关闭此窗口或按回车退出。")
        log("=" * 60)
        try:
            input("按回车键退出...")
        except EOFError:
            pass


if __name__ == "__main__":
    main()
