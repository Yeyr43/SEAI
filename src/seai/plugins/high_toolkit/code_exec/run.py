import sys, json, subprocess, tempfile, os

def execute(code: str) -> str:
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code); temp_path = f.name
    try:
        result = subprocess.run(["python", temp_path], capture_output=True, text=True, timeout=15)
        return result.stdout if result.returncode == 0 else f"错误:\n{result.stderr}"
    except Exception as e: return f"执行异常：{e}"
    finally: os.unlink(temp_path)

if __name__ == "__main__":
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(execute(args.get("code", "")))