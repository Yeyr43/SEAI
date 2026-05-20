# ══════════════════════════════════════════════════
# cli.py - 命令行监听终端
# 路径：日志文件位于 SEAI_DATA/logs/seai.log
# ══════════════════════════════════════════════════
import os, time
from pathlib import Path

LOG_FILE = os.environ.get("SEAI_LOG_FILE", str(Path.cwd().parent / "data" / "logs" / "seai.log"))
BASE_URL = "http://127.0.0.1:8080"

def log_monitor():
    if not os.path.exists(LOG_FILE):
        print("LOG> 日志文件不存在，等待服务启动...")
        while not os.path.exists(LOG_FILE): time.sleep(0.5)
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if line: print(f"LOG> {line.rstrip()}", flush=True)
            else: time.sleep(0.3)

if __name__ == "__main__":
    print(f"正在监听 SEAI 本地服务\n客户端开放于 127.0.0.1:8080\nSEAI Api 为：{BASE_URL}/docs")
    try: log_monitor()
    except KeyboardInterrupt: print("\n监听已停止。")