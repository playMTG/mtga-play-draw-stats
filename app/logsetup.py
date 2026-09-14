# -*- coding: utf-8 -*-
"""把面板的运行与崩溃写进 `data/panel.log`。

**为什么要有这个模块**：用户报「插件运行中有闪退」，但进程没留下任何痕迹。
`start.bat` 用 `start /min` 起一个最小化控制台，`uvicorn.run(log_level="warning")`
几乎不输出，崩溃时窗口一闪就没了——事后既看不出是不是崩的，也看不出崩在哪。
没有日志就没法查，所以先补日志。

三件事：

1. 日志追加写 `data/panel.log`（滚动，最多两份），同时仍打到 stderr；
2. **主线程与子线程**的未捕获异常都写完整 traceback（`sys.excepthook` +
   `threading.excepthook`）——子线程崩了主进程不会退，但功能会静默停摆，
   这类问题以前只表现为「面板开着但不再记对局」；
3. 启动写一行 `start:`，**正常退出写一行 `exit: clean`**。于是日志尾部没有
   `exit: clean` 就等价于「被强杀或崩溃」——这正是本次最缺的那条判断依据。
"""
from __future__ import annotations

import atexit
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

LOGGER_NAME = "mtga"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 2
_configured = False


def logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def setup(root: Path, port: int | None = None) -> logging.Logger:
    """配置一次即可（重复调用不会重复挂 handler）。"""
    global _configured
    log = logger()
    if _configured:
        return log

    log.setLevel(logging.INFO)
    log.propagate = False

    try:
        log_dir = Path(root) / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "panel.log", maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
        log.addHandler(file_handler)
    except OSError:
        # 日志写不进去也不能让面板起不来：退回只打 stderr。
        pass

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(stream)

    def on_main_exception(exc_type, exc, tb):
        log.critical("未捕获异常（主线程）", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def on_thread_exception(args):
        if args.exc_type is SystemExit:
            return
        log.critical("未捕获异常（线程 %s）", getattr(args.thread, "name", "?"),
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    def on_exit():
        """正常退出留一行 `exit: clean`。

        先摘掉控制台 handler 再写：进程退出时 stderr 可能已经被关闭
        （pytest 的捕获、被管道接管的父进程都会这样），继续往它写会让
        logging 自己抛 `I/O operation on closed file`，把退出标记也弄丢。
        """
        for handler in list(log.handlers):
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                    handler, logging.FileHandler):
                log.removeHandler(handler)
        try:
            log.info("exit: clean")
        finally:
            logging.shutdown()

    sys.excepthook = on_main_exception
    threading.excepthook = on_thread_exception
    atexit.register(on_exit)

    log.info("start: pid=%s port=%s python=%s cwd=%s",
             os.getpid(), port, sys.version.split()[0], Path.cwd())
    _configured = True
    return log


def heartbeat(extra: str = "") -> None:
    """定期打一行「还活着」——崩溃后靠它定位最后存活时间。"""
    logger().info("alive%s", f" {extra}" if extra else "")
