import logging


class EventChannel:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def publish(self, *args):
        for callback in tuple(self.callbacks):
            callback(*args)


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
