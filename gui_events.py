import logging
import threading


logger = logging.getLogger(__name__)

# 防止 log_events 回调异常 -> logger.exception -> LogBridge -> log_events 递归。
_publish_guard = threading.local()


class EventChannel:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def publish(self, *args):
        # 单个 GUI 回调异常不能中断网络线程（例如把预览发布误判为解码失败）。
        for callback in tuple(self.callbacks):
            try:
                callback(*args)
            except Exception:
                if getattr(_publish_guard, 'active', False):
                    continue
                _publish_guard.active = True
                try:
                    logger.exception('[Events] 回调失败 callback=%s',
                                     getattr(callback, '__qualname__', callback))
                finally:
                    _publish_guard.active = False


preview_events = EventChannel()
chat_events = EventChannel()
submission_events = EventChannel()


class LogBridge(logging.Handler):
    def emit(self, record):
        if record.name.startswith('student_sim') or not log_events.callbacks:
            return
        try:
            log_events.publish(self.format(record), record.levelno)
        except Exception:
            self.handleError(record)


log_events = EventChannel()


def install_log_bridge(logger):
    if any(isinstance(handler, LogBridge) for handler in logger.handlers):
        return
    handler = LogBridge()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter('%(asctime)s  %(message)s', datefmt='%H:%M:%S'))
    logger.addHandler(handler)
