import json
import logging
import os
import sys


DEFAULT_CHANNEL = 1
DEFAULT_SUBMISSION_PORT = 0
CONFIG_ENV = 'JIYU_CONFIG_PATH'
SUBMISSION_PORT_ENV = 'TEACHER_SUBMISSION_PORT'
logger = logging.getLogger(__name__)


def config_path():
    override = os.environ.get(CONFIG_ENV, '').strip()
    if override:
        return os.path.abspath(override)
    app_dir = os.path.dirname(sys.executable if getattr(sys, 'frozen', False)
                              else os.path.abspath(__file__))
    return os.path.join(app_dir, 'classroom_config.json')


def valid_channel(value):
    return type(value) is int and 1 <= value <= 32


def valid_submission_port(value):
    return type(value) is int and 0 <= value <= 65535


def has_explicit_submission_port():
    raw = os.environ.get(SUBMISSION_PORT_ENV)
    return raw is not None and bool(raw.strip())


def _read_config(path):
    try:
        with open(path, encoding='utf-8') as config_file:
            config = json.load(config_file)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError) as error:
        logger.warning('读取配置失败，使用各字段默认值：%s (%s)', path, error)
        return {}
    if not isinstance(config, dict):
        logger.warning('配置根节点不是 JSON 对象，使用各字段默认值：%s', path)
        return {}
    return config


def _write_config(config, path):
    temporary_path = f'{path}.{os.getpid()}.tmp'
    try:
        with open(temporary_path, 'w', encoding='utf-8') as config_file:
            json.dump(config, config_file, ensure_ascii=False, indent=2)
            config_file.write('\n')
        os.replace(temporary_path, path)
    except OSError:
        try:
            os.remove(temporary_path)
        except OSError:
            pass
        raise


def _load_channel(config, path):
    channel = config.get('channel', DEFAULT_CHANNEL)
    if not valid_channel(channel):
        logger.warning('频道配置无效，回退到频道 %d：%s (%r)',
                       DEFAULT_CHANNEL, path, channel)
        return DEFAULT_CHANNEL
    return channel


def _load_submission_port(config, path):
    port = config.get('submission_port', DEFAULT_SUBMISSION_PORT)
    if not valid_submission_port(port):
        logger.warning('文件接收端口配置无效，回退到禁用：%s (%r)', path, port)
        return DEFAULT_SUBMISSION_PORT
    return port


def _parse_submission_port_env(raw):
    try:
        port = int(raw, 0)
    except ValueError as error:
        raise ValueError(
            f'{SUBMISSION_PORT_ENV} 必须是 0 到 65535 的整数：{raw!r}'
        ) from error
    if not valid_submission_port(port):
        raise ValueError(f'{SUBMISSION_PORT_ENV} 必须在 0 到 65535 之间：{raw!r}')
    return port


def load_channel(path=None):
    return _load_channel(_read_config(path or config_path()), path or config_path())


def load_submission_port(path=None):
    raw = os.environ.get(SUBMISSION_PORT_ENV)
    if raw is not None and raw.strip():
        return _parse_submission_port_env(raw.strip())
    path = path or config_path()
    return _load_submission_port(_read_config(path), path)


def save_channel(channel, path=None):
    if not valid_channel(channel):
        raise ValueError('频道必须是 1 到 32 的整数')
    path = path or config_path()
    config = _read_config(path)
    config['channel'] = channel
    _write_config(config, path)


def save_submission_port(port, path=None):
    if not valid_submission_port(port):
        raise ValueError('文件接收端口必须是 0 到 65535 的整数')
    path = path or config_path()
    config = _read_config(path)
    config['submission_port'] = port
    _write_config(config, path)


def save_settings(channel, submission_port, path=None):
    if not valid_channel(channel):
        raise ValueError('频道必须是 1 到 32 的整数')
    if not valid_submission_port(submission_port):
        raise ValueError('文件接收端口必须是 0 到 65535 的整数')
    path = path or config_path()
    config = _read_config(path)
    config['channel'] = channel
    config['submission_port'] = submission_port
    _write_config(config, path)
