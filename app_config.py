import json
import logging
import os
import sys


DEFAULT_CHANNEL = 1
CONFIG_ENV = 'JIYU_CONFIG_PATH'
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


def load_channel(path=None):
    path = path or config_path()
    try:
        with open(path, encoding='utf-8') as config_file:
            config = json.load(config_file)
        if not isinstance(config, dict):
            raise ValueError('配置根节点不是 JSON 对象')
        channel = config['channel']
        if not valid_channel(channel):
            raise ValueError(f'channel 必须是 1 到 32 的整数，实际为 {channel!r}')
        return channel
    except FileNotFoundError:
        return DEFAULT_CHANNEL
    except (OSError, ValueError, TypeError, KeyError) as error:
        logger.warning('读取频道配置失败，回退到频道 %d：%s (%s)',
                       DEFAULT_CHANNEL, path, error)
        return DEFAULT_CHANNEL


def save_channel(channel, path=None):
    if not valid_channel(channel):
        raise ValueError('频道必须是 1 到 32 的整数')
    path = path or config_path()
    try:
        with open(path, encoding='utf-8') as config_file:
            config = json.load(config_file)
        if not isinstance(config, dict):
            config = {}
    except (OSError, ValueError, TypeError):
        config = {}
    config['channel'] = channel
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
