"""
SEAI 命令行监听终端 - 仅展示原始数据
"""
import sys, os, time, argparse
from pathlib import Path

LOG_FILE = os.environ.get("SEAI_LOG_FILE", str(Path.cwd().parent / "data" / "logs" / "seai.log"))
BASE_URL = "http://127.0.0.1:8080"

def log_monitor(json_mode=False):
    if not os.path.exists(LOG_FILE):
        print("LOG> 日志文件不存在，等待服务启动...")
        while not os.path.exists(LOG_FILE):
            time.sleep(0.5)
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if line:
                if json_mode:
                    import json
                    print(json.dumps({"type":"log","content":line.rstrip()}, ensure_ascii=False), flush=True)
                else:
                    print(f"LOG> {line.rstrip()}", flush=True)
            else:
                time.sleep(0.3)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出日志")
    args = parser.parse_args()
    print(f"正在监听 SEAI web")
    print(f"客户端开放于 127.0.0.1:8080")
    print(f"SEAI Api 为：{BASE_URL}/docs")
    try:
        log_monitor(json_mode=args.json)
    except KeyboardInterrupt:
        print("\n监听已停止。")