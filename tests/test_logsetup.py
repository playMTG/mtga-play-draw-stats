# -*- coding: utf-8 -*-
"""崩溃可诊断性（2026-09-14）。

用户报「插件运行中有闪退」，但进程没留任何痕迹：`start.bat` 用 `start /min` 起
最小化控制台，`uvicorn.run(log_level="warning")` 几乎不输出，崩溃时窗口一闪就没，
事后既不知道是不是崩的、也不知道崩在哪。这一组测试钉住三件事：

1. 日志真的落到 `data/panel.log`；
2. **正常退出写 `exit: clean`** —— 日志尾部没有这行就等价于「被强杀或崩溃」，
   这是事后判断唯一可靠的依据；
3. 主线程与**子线程**的未捕获异常都写完整 traceback（子线程崩了主进程不会退，
   功能会静默停摆，以前只表现为「面板开着但不再记对局」）。
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import logsetup


def _fresh(root: Path) -> logging.Logger:
    """每个用例都重新配置一次：模块级 _configured 是全局的。"""
    logsetup._configured = False
    log = logging.getLogger(logsetup.LOGGER_NAME)
    log.handlers.clear()
    return logsetup.setup(root, 8765)


def test_log_file_gets_start_line(tmp_path):
    log = _fresh(tmp_path)
    log.info("hello")
    text = (tmp_path / "data" / "panel.log").read_text(encoding="utf-8")
    assert "start: pid=" in text
    assert "port=8765" in text
    assert "hello" in text


def test_clean_exit_is_recorded(tmp_path):
    """`exit: clean` 是「不是崩溃」的唯一证据，必须由 atexit 写出来。

    在子进程里验证：atexit 只在解释器正常退出时跑，直接调函数不算数。
    """
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})\n"
        "from pathlib import Path\n"
        "from app import logsetup\n"
        f"logsetup.setup(Path({str(tmp_path)!r}), 8765)\n"
        "logsetup.logger().info('work')\n"
    )
    proc = subprocess.run([sys.executable, "-c", script],
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=60)
    assert proc.returncode == 0, proc.stderr
    text = (tmp_path / "data" / "panel.log").read_text(encoding="utf-8")
    assert "exit: clean" in text
    assert text.index("work") < text.index("exit: clean"), "退出标记必须在业务日志之后"


def test_thread_exception_is_logged(tmp_path):
    """子线程里的未捕获异常要写进日志——主进程不会因此退出，最容易被忽略。"""
    log = _fresh(tmp_path)
    done = threading.Event()

    def boom():
        try:
            raise ValueError("线程里的意外")
        except ValueError:
            # 模拟「未捕获」：直接交给 threading.excepthook
            import sys as _sys
            exc_type, exc, tb = _sys.exc_info()
            threading.excepthook(threading.ExceptHookArgs(
                (exc_type, exc, tb, threading.current_thread())))
        finally:
            done.set()

    t = threading.Thread(target=boom, name="probe-thread")
    t.start()
    assert done.wait(5)
    t.join(5)
    text = (tmp_path / "data" / "panel.log").read_text(encoding="utf-8")
    assert "未捕获异常（线程 probe-thread）" in text
    assert "ValueError: 线程里的意外" in text
    assert "Traceback" in text


def test_heartbeat_is_logged(tmp_path):
    """心跳用于定位「最后还活着是什么时候」。"""
    _fresh(tmp_path)
    logsetup.heartbeat("events=42")
    text = (tmp_path / "data" / "panel.log").read_text(encoding="utf-8")
    assert "alive events=42" in text


def test_setup_is_idempotent(tmp_path):
    """重复调用不能把 handler 挂两遍（否则每条日志写两次）。"""
    log = _fresh(tmp_path)
    logsetup.setup(tmp_path, 8765)
    logsetup.setup(tmp_path, 8765)
    assert len(log.handlers) == 2, [type(h).__name__ for h in log.handlers]


def test_unwritable_log_dir_does_not_break_startup(tmp_path):
    """日志写不进去也不能让面板起不来。"""
    logsetup._configured = False
    logging.getLogger(logsetup.LOGGER_NAME).handlers.clear()
    # 用一个「路径其实是个文件」的位置当 root，mkdir 必定失败
    blocker = tmp_path / "blocked"
    blocker.write_text("x", encoding="utf-8")
    log = logsetup.setup(blocker, 8765)
    assert any(isinstance(h, logging.StreamHandler) for h in log.handlers)
