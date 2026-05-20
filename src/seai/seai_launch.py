"""
SEAI 快速启动入口
用于 PyInstaller 打包为独立 .exe 文件。
提供启动状态反馈、错误处理和优雅退出。
所有资源内置加载，无需外部 WWW 目录。
窗口拖动使用 Windows WM_NCHITTEST 原生消息实现。
支持系统托盘、单实例检查、关闭到托盘等功能。
"""
import sys
import os
import time
import ctypes
import signal
import threading
import subprocess
import traceback
import logging
from pathlib import Path


def get_app_root():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def show_status(msg):
    print(f"[SEAI] {msg}", flush=True)


def show_error(msg):
    print(f"[SEAI 错误] {msg}", flush=True)


def _acquire_lock(app_root):
    lock_file = app_root.parent / "data" / "seai.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        if lock_file.exists():
            try:
                old_pid = int(lock_file.read_text().strip())
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
                    if exit_code.value == 259:
                        return False, lock_file
            except Exception:
                pass
        lock_file.write_text(str(os.getpid()))
        return True, lock_file
    except Exception:
        return True, lock_file


def _release_lock(lock_file):
    try:
        if lock_file.exists():
            lock_file.unlink()
    except Exception:
        pass


def _bring_existing_to_front(app_root):
    lock_file = app_root.parent / "data" / "seai.lock"
    try:
        if lock_file.exists():
            old_pid = int(lock_file.read_text().strip())
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


def main():
    show_status("正在初始化 SEAI 应用程序...")

    app_root = get_app_root()
    os.chdir(str(app_root))
    sys.path.insert(0, str(app_root))

    show_status(f"工作目录: {app_root}")

    acquired, lock_file = _acquire_lock(app_root)
    if not acquired:
        show_status("SEAI 已在运行中，正在激活现有窗口...")
        _bring_existing_to_front(app_root)
        sys.exit(0)

    try:
        import uvicorn
        show_status("核心模块加载成功")
    except ImportError as e:
        show_error(f"缺少核心依赖: {e}")
        show_error("请确保完整安装 SEAI 及其依赖")
        _release_lock(lock_file)
        input("按 Enter 键退出...")
        sys.exit(1)

    HOST = "127.0.0.1"
    PORT = 8080

    server_started = threading.Event()
    server_error = [None]

    def run_server():
        try:
            config = uvicorn.Config(
                "app:app",
                host=HOST,
                port=PORT,
                log_level="warning",
                reload=False,
            )
            server = uvicorn.Server(config)
            server_started.set()
            server.run()
        except Exception as e:
            server_error[0] = e
            server_started.set()

    show_status("正在启动后端服务...")
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    server_started.wait(timeout=5)
    if server_error[0]:
        show_error(f"后端服务启动失败: {server_error[0]}")
        _release_lock(lock_file)
        input("按 Enter 键退出...")
        sys.exit(1)

    show_status("等待后端服务就绪...")
    start_time = time.time()
    ready = False
    import httpx
    while time.time() - start_time < 60:
        try:
            resp = httpx.get(f"http://{HOST}:{PORT}/api/health", timeout=2)
            if resp.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(0.5)

    if not ready:
        show_error("后端服务启动超时（60秒）")
        show_error("请检查端口 8080 是否被占用，或配置文件是否正确")
        _release_lock(lock_file)
        input("按 Enter 键退出...")
        sys.exit(1)

    show_status("后端服务就绪，正在启动窗口界面...")

    try:
        from PyQt6.QtCore import Qt, QUrl, QTimer, pyqtSignal, QObject, pyqtSlot, QEvent
        from PyQt6.QtGui import QIcon, QPixmap, QAction
        from PyQt6.QtWidgets import (
            QApplication, QMainWindow, QVBoxLayout, QWidget,
            QSystemTrayIcon, QMenu, QMessageBox, QPushButton
        )
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEngineProfile
        from PyQt6.QtWebChannel import QWebChannel
    except ImportError as e:
        show_error(f"缺少 PyQt6 依赖: {e}")
        show_error("请确保已安装 PyQt6 和 PyQt6-WebEngine")
        _release_lock(lock_file)
        input("按 Enter 键退出...")
        sys.exit(1)

    from seai_window import _get_seai_icon_bytes

    TOPBAR_HEIGHT = 44

    WM_NCHITTEST = 0x0084
    HTCAPTION = 2

    class _DragHandle(QWidget):
        """原生 Qt 透明拖拽手柄 — 置于 QWebEngineView 上方捕获鼠标事件"""
        def __init__(self, parent):
            super().__init__(parent)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setCursor(Qt.CursorShape.ArrowCursor)

        def mousePressEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton:
                wh = self.window().windowHandle()
                if wh:
                    wh.startSystemMove()
            event.accept()

    class WindowBridge(QObject):
        minimize_requested = pyqtSignal()
        hide_to_tray = pyqtSignal()

        def __init__(self, window):
            super().__init__()
            self._window = window

        @pyqtSlot()
        def minimize(self):
            self.minimize_requested.emit()

        @pyqtSlot()
        def close(self):
            self.hide_to_tray.emit()

        @pyqtSlot()
        def start_system_move(self):
            window_handle = self._window.windowHandle()
            if window_handle:
                window_handle.startSystemMove()

    class SEAIMainWindow(QMainWindow):

        def __init__(self):
            super().__init__()
            self.setWindowTitle("SEAI")
            self.setFixedSize(1050, 680)
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
            self.winId()  # 强制创建原生窗口句柄，确保 nativeEvent 可用

            icon_bytes = _get_seai_icon_bytes()
            pixmap = QPixmap()
            pixmap.loadFromData(icon_bytes)
            self.setWindowIcon(QIcon(pixmap))

            self._bridge = WindowBridge(self)
            self._bridge.minimize_requested.connect(self.showMinimized)
            self._bridge.hide_to_tray.connect(self._hide_to_tray)

            self._channel = QWebChannel()
            self._channel.registerObject("seaiWindow", self._bridge)

            self._webview = QWebEngineView()
            self._webview.page().setWebChannel(self._channel)

            # 从本地 HTTP 服务加载 Web 前端（保证 QWebChannel 正确注入）
            self._webview.load(QUrl(f"http://{HOST}:{PORT}/"))

            settings = self._webview.page().settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)

            profile = self._webview.page().profile()
            profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)

            container = QWidget()
            layout = QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(self._webview)
            container.setLayout(layout)
            self.setCentralWidget(container)

            self._webview.page().windowCloseRequested.connect(self._hide_to_tray)
            self._webview.page().loadFinished.connect(self._on_page_loaded)

            # 原生 Qt 拖拽手柄 — 置于 QWebEngineView 上方，覆盖顶栏中间区域
            self._drag_handle = _DragHandle(self)
            self._drag_handle.setGeometry(200, 0, 1050 - 200 - 120, TOPBAR_HEIGHT)
            self._drag_handle.show()
            self._drag_handle.raise_()

            # 原生 Qt 覆盖按钮 — 无需 QWebChannel 也始终可用
            self._setup_native_window_buttons()

        def _setup_native_window_buttons(self):
            """在顶栏右侧创建原生 Qt 最小化/关闭按钮，永远可用"""
            btn_w, btn_h = 36, 36
            btn_y = (TOPBAR_HEIGHT - btn_h) // 2
            close_x = 1050 - 8 - btn_w
            min_x = close_x - 4 - btn_w

            self._native_min_btn = QPushButton(self)
            self._native_min_btn.setFixedSize(btn_w, btn_h)
            self._native_min_btn.setText("─")
            self._native_min_btn.setToolTip("最小化")
            self._native_min_btn.clicked.connect(self.showMinimized)
            self._native_min_btn.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);"
                " border-radius: 8px; color: #aaa; font-size: 16px; font-weight: bold; }"
                "QPushButton:hover { background: rgba(255,255,255,0.15); color: #fff; }"
            )
            self._native_min_btn.move(min_x, btn_y)
            self._native_min_btn.show()
            self._native_min_btn.raise_()

            self._native_close_btn = QPushButton(self)
            self._native_close_btn.setFixedSize(btn_w, btn_h)
            self._native_close_btn.setText("✕")
            self._native_close_btn.setToolTip("关闭到托盘")
            self._native_close_btn.clicked.connect(self._hide_to_tray)
            self._native_close_btn.setStyleSheet(
                "QPushButton { background: rgba(232,17,35,0.12); border: 1px solid rgba(232,17,35,0.15);"
                " border-radius: 8px; color: #e81123; font-size: 16px; font-weight: bold; }"
                "QPushButton:hover { background: rgba(232,17,35,0.85); color: #fff; }"
            )
            self._native_close_btn.move(close_x, btn_y)
            self._native_close_btn.show()
            self._native_close_btn.raise_()

        def _on_page_loaded(self, ok):
            """页面加载完成后注入 JS 隐藏 Web 按钮（使用原生覆盖按钮）"""
            if ok:
                self._webview.page().runJavaScript(
                    "var mb=document.getElementById('winMinBtn'); if(mb) mb.style.display='none';"
                    "var cb=document.getElementById('winCloseBtn'); if(cb) cb.style.display='none';"
                )

        def _hide_to_tray(self):
            self.hide()
            tray = QApplication.instance().property("_seai_tray")
            if tray and tray.supportsMessages():
                tray.showMessage(
                    "SEAI",
                    "SEAI 已在后台运行，双击托盘图标可重新打开窗口",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000
                )

        def nativeEvent(self, eventType, message):
            if eventType == b"windows_generic_MSG":
                try:
                    msg = ctypes.wintypes.MSG.from_address(int(message))
                except Exception:
                    return False, 0
                if msg.message == WM_NCHITTEST:
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    g = self.geometry()
                    top = g.y()
                    right = g.x() + g.width()

                    if y < top + TOPBAR_HEIGHT:
                        if x < right - 120:
                            return True, HTCAPTION

            return False, 0

        def closeEvent(self, event):
            event.ignore()
            self._hide_to_tray()

        def eventFilter(self, obj, event):
            """Qt 级拖拽兜底 — 捕获 QWebEngineView 上的 mousedown 并触发 startSystemMove"""
            if obj is self._webview and event.type() == QEvent.Type.MouseButtonPress:
                pos = event.position()
                if pos.y() < TOPBAR_HEIGHT and pos.x() < self.width() - 120:
                    wh = self.windowHandle()
                    if wh:
                        wh.startSystemMove()
                        return True
            return super().eventFilter(obj, event)

    def _create_tray_icon(app, window):
        icon_bytes = _get_seai_icon_bytes()
        pixmap = QPixmap()
        pixmap.loadFromData(icon_bytes)
        icon = QIcon(pixmap)

        tray = QSystemTrayIcon(icon, app)
        tray.setToolTip("SEAI - 智能助手")

        menu = QMenu()

        action_show = QAction("快速打开客户端", menu)
        action_show.triggered.connect(lambda: _show_window(window))
        menu.addAction(action_show)

        action_cli = QAction("快速打开CLI", menu)
        action_cli.triggered.connect(_open_cli)
        menu.addAction(action_cli)

        menu.addSeparator()

        action_quit = QAction("关闭进程", menu)
        action_quit.triggered.connect(lambda: _quit_app(app, window))
        menu.addAction(action_quit)

        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: _on_tray_activated(reason, window))
        tray.show()

        app.setProperty("_seai_tray", tray)
        return tray

    def _show_window(window):
        window.show()
        window.raise_()
        window.activateWindow()

    def _open_cli():
        try:
            subprocess.Popen(
                ["cmd.exe", "/k", f"cd /d {app_root} && title SEAI 控制台 && echo SEAI 控制台 - 可用命令: python seai_cli.py --status / --stop / --help && echo."],
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        except Exception as e:
            QMessageBox.warning(None, "SEAI", f"无法打开 CLI: {e}")

    def _on_tray_activated(reason, window):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            _show_window(window)

    def _quit_app(app, window):
        window._webview.page().profile().clearHttpCache()
        _release_lock(lock_file)
        tray = app.property("_seai_tray")
        if tray:
            tray.hide()
        app.quit()
        QTimer.singleShot(200, lambda: os._exit(0))

    show_status("启动窗口界面...")
    app = QApplication(sys.argv)
    app.setApplicationName("SEAI")
    app.setOrganizationName("SEAI")
    app.setQuitOnLastWindowClosed(False)

    def _sigint_handler(signum, frame):
        print("\n正在退出 SEAI...")
        app.quit()

    signal.signal(signal.SIGINT, _sigint_handler)

    if sys.platform == "win32":
        def _win_ctrl_handler(ctrl_type):
            app.quit()
            return 1
        _ctrl_handler_ref = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ulong)(_win_ctrl_handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_ctrl_handler_ref, True)

    icon_bytes = _get_seai_icon_bytes()
    pixmap = QPixmap()
    pixmap.loadFromData(icon_bytes)
    app.setWindowIcon(QIcon(pixmap))

    window = SEAIMainWindow()
    _create_tray_icon(app, window)
    window.show()

    show_status("SEAI 启动完成！")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()