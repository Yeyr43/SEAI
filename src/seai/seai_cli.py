"""
SEAI 命令行入口
用法: seai --start    启动 SEAI 应用程序（含单实例检查）
     seai --status   查看 SEAI 运行状态
     seai --stop     停止 SEAI 应用程序
     seai --help     显示帮助信息
"""
import sys
import os
import ctypes
import subprocess
from pathlib import Path


SEAI_HOME = Path(__file__).parent
LOCK_FILE = SEAI_HOME.parent / "data" / "seai.lock"


def _is_running():
    """检查 SEAI 是否已在运行"""
    if not LOCK_FILE.exists():
        return False
    try:
        old_pid = int(LOCK_FILE.read_text().strip())
        import ctypes.wintypes
        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY_INFORMATION = 0x0400
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | SYNCHRONIZE, False, old_pid
        )
        if handle:
            exit_code = ctypes.wintypes.DWORD()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return exit_code.value == 259
        return False
    except Exception:
        return False


def _bring_to_front():
    """将已有实例窗口带到前台"""
    try:
        old_pid = int(LOCK_FILE.read_text().strip())
        import ctypes.wintypes
        PROCESS_QUERY_INFORMATION = 0x0400
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, old_pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            ctypes.windll.user32.AllowSetForegroundWindow(old_pid)
        import httpx
        httpx.post("http://127.0.0.1:8080/api/health", timeout=1)
    except Exception:
        pass


def cmd_start():
    """启动 SEAI 应用程序"""
    if _is_running():
        print("SEAI 已在运行中，正在激活现有窗口...")
        _bring_to_front()
        return

    print("正在启动 SEAI...")

    try:
        launcher = SEAI_HOME / "seai_launch.py"
        if not launcher.exists():
            print("[SEAI 错误] 找不到 seai_launch.py")
            sys.exit(1)

        if sys.platform == "win32":
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            subprocess.Popen(
                [sys.executable, str(launcher)],
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                [sys.executable, str(launcher)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

        print("SEAI 已启动，窗口即将显示...")
    except Exception as e:
        print(f"[SEAI 错误] 启动失败: {e}")
        sys.exit(1)


def cmd_status():
    """查看 SEAI 运行状态"""
    if _is_running():
        print("SEAI 状态: 运行中")
        try:
            import httpx
            resp = httpx.get("http://127.0.0.1:8080/api/health", timeout=2)
            if resp.status_code == 200:
                print("后端服务: 正常")
            else:
                print(f"后端服务: 异常 (HTTP {resp.status_code})")
        except Exception:
            print("后端服务: 不可达")
    else:
        print("SEAI 状态: 未运行")


def cmd_stop():
    """停止 SEAI 应用程序"""
    if not _is_running():
        print("SEAI 未在运行")
        return

    try:
        old_pid = int(LOCK_FILE.read_text().strip())
        import ctypes.wintypes
        PROCESS_TERMINATE = 0x0001
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, old_pid)
        if handle:
            ctypes.windll.kernel32.TerminateProcess(handle, 0)
            ctypes.windll.kernel32.CloseHandle(handle)
            print(f"SEAI 进程 (PID: {old_pid}) 已终止")
        else:
            print("无法终止 SEAI 进程（权限不足）")
    except Exception as e:
        print(f"停止 SEAI 失败: {e}")


def cmd_help():
    """显示帮助信息"""
    print(__doc__)


def main():
    if len(sys.argv) < 2:
        cmd_help()
        return

    cmd = sys.argv[1].lower()

    if cmd in ("--start", "-s", "start"):
        cmd_start()
    elif cmd in ("--status", "status"):
        cmd_status()
    elif cmd in ("--stop", "stop"):
        cmd_stop()
    elif cmd in ("--help", "-h", "help"):
        cmd_help()
    else:
        print(f"未知命令: {cmd}")
        cmd_help()


if __name__ == "__main__":
    main()