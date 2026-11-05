"""MiniMedia 文件提交 TCP 接收服务，仅依赖 ``minimedia_protocol`` 的稳定 API。

线上格式依据 temp/minimedia-server-findings.md：12 字节头为
``[version:LE32][magic:LE32][bodyLength:LE32]``；WORB 无应答；LIFD 触发
TRFD；BFPU 顺序追加文件数据，零长度且 status=0 的 BFPU 表示上传完成。
"""

import logging
import os
import socket
import struct
import threading
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath

import minimedia_protocol as protocol


LOGGER = logging.getLogger(__name__)

VERSION = protocol.VERSION
HEADER_SIZE = protocol.HEADER.size

BACKLOG = 10
DEFAULT_MAX_FILE = 64 * 1024 * 1024
DEFAULT_MAX_BLOCK = 65536
DEFAULT_MAX_FRAME_BODY = 1024 * 1024
DEFAULT_TIMEOUT = 30.0
MAX_NAME_UNITS = 240

STATUS_BAD_NAME = 1
STATUS_TOO_LARGE = 2
STATUS_DUPLICATE = 3
STATUS_BAD_REQUEST = 4
STATUS_IO_ERROR = 5

WINDOWS_RESERVED = frozenset(
    ['CON', 'PRN', 'AUX', 'NUL']
    + [f'COM{i}' for i in range(1, 10)]
    + [f'LPT{i}' for i in range(1, 10)]
)

_INFO_SEQUENCE_KEYS = ('sequence', 'seq', 'request_id', 'id', 'request_sequence')
_INFO_SIZE_KEYS = ('size', 'file_size', 'filesize', 'length', 'total', 'total_size')
_INFO_NAME_KEYS = ('path', 'name', 'filename', 'file_name', 'file', 'file_path', 'filepath')
_DATA_SEQUENCE_KEYS = ('sequence', 'seq', 'request_id', 'id')
_DATA_STATUS_KEYS = ('status', 'state', 'code', 'flag', 'final')
_DATA_PAYLOAD_KEYS = ('data', 'payload', 'chunk', 'content', 'body', 'bytes')


class UploadRejected(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _field(parsed, names, default=None):
    if isinstance(parsed, Mapping):
        for name in names:
            if name in parsed:
                return parsed[name]
        lowered = {str(key).lower(): value for key, value in parsed.items()}
        for name in names:
            if name.lower() in lowered:
                return lowered[name.lower()]
    elif not isinstance(parsed, (tuple, list)):
        for name in names:
            if hasattr(parsed, name):
                return getattr(parsed, name)
    return default


def _parse_info_raw(body):
    if len(body) < 14 or len(body) % 2:
        raise ValueError('LIFD 负载长度无效')
    sequence, size_low, size_high = struct.unpack_from('<III', body)
    size = size_low | (size_high << 32)
    tail = bytes(body[12:])
    for skip in (0, 2, 4):
        chunk = tail[skip:]
        if len(chunk) < 2 or len(chunk) % 2:
            continue
        try:
            text = chunk.decode('utf-16-le', errors='strict')
        except UnicodeDecodeError:
            continue
        if '\x00' not in text:
            continue
        name, rest = text.split('\x00', 1)
        if all(char == '\x00' for char in rest):
            return {'sequence': sequence, 'size': size, 'name': name}
    raise ValueError('LIFD 文件名无法解析')


def _has_embedded_nul(body):
    tail = bytes(body[12:])
    if len(tail) < 2 or len(tail) % 2:
        return True
    try:
        text = tail.decode('utf-16-le', errors='strict')
    except UnicodeDecodeError:
        return True
    return '\x00' in text.strip('\x00')


def _parse_data_raw(body):
    if len(body) < 8:
        raise ValueError('BFPU 负载长度不足')
    sequence, status = struct.unpack_from('<II', body)
    return {'sequence': sequence, 'status': status, 'data': bytes(body[8:])}


def _build_response(sequence, status, size=0):
    try:
        return protocol.upload_response(sequence, status, size)
    except TypeError:
        pass
    try:
        return protocol.upload_response(sequence=sequence, status=status, size=size)
    except TypeError:
        pass
    return protocol.frame(protocol.TRFD, struct.pack('<IIQIQ', sequence, status, size, 0, 0))


def _validate_name(name):
    if not isinstance(name, str) or not name:
        raise ValueError('文件名不能为空')
    if '\x00' in name:
        raise ValueError('文件名包含 NUL')
    if name in ('.', '..') or '..' in name:
        raise ValueError('拒绝路径遍历')
    if any(char in name for char in ('/', '\\', ':')):
        raise ValueError('拒绝路径分隔符、盘符或备用数据流')
    if name != name.strip() or name[-1] in '. ':
        raise ValueError('文件名首尾空白或结尾点不合法')
    if any(ord(char) < 32 for char in name):
        raise ValueError('文件名包含控制字符')
    if Path(name).name != name or PureWindowsPath(name).name != name:
        raise ValueError('只允许单个文件名')
    if Path(name).is_absolute() or PureWindowsPath(name).is_absolute():
        raise ValueError('拒绝绝对路径')
    if name.split('.', 1)[0].upper() in WINDOWS_RESERVED:
        raise ValueError('拒绝系统保留设备名')
    encoded = name.encode('utf-16-le')
    if len(encoded) // 2 > MAX_NAME_UNITS:
        raise ValueError('UTF-16 文件名过长')
    return encoded


class FrameStream:
    """按 12 字节头拆包，并限制声明的 bodyLength。"""

    def __init__(self, maximum=DEFAULT_MAX_FRAME_BODY):
        if not isinstance(maximum, int) or maximum <= 0:
            raise ValueError('bodyLength 上限必须为正整数')
        self.maximum = maximum
        self.buffer = bytearray()

    def feed(self, data):
        if data:
            self.buffer.extend(data)
        packets = []
        while len(self.buffer) >= HEADER_SIZE:
            _, _, length = protocol.HEADER.unpack_from(self.buffer)
            if length > self.maximum:
                raise ValueError(f'MiniMedia 负载超过限制：{length}')
            total = HEADER_SIZE + length
            if len(self.buffer) < total:
                break
            packet = bytes(self.buffer[:total])
            del self.buffer[:total]
            packets.append(protocol.decode_frame(packet))
        return packets


class UploadSession:
    def __init__(self, server, connection, address):
        self.server = server
        self.connection = connection
        self.address = address
        self.directory = server.directory
        self.maximum = server.maximum
        self.max_block = server.max_block
        self.timeout = server.timeout
        self.stream = FrameStream(server.max_frame_body)
        self.send_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.closed = False
        self.info_received = False
        self.upload = None
        self.claimed_name = None
        self.worb_options = []

    def _emit(self, kind, **details):
        self.server._emit(kind, self.address, details)

    def _send(self, packet):
        with self.send_lock:
            if self.closed:
                return False
            try:
                self.connection.sendall(packet)
                return True
            except OSError as error:
                LOGGER.warning('[MiniMedia] %s 发送失败：%s', self.address, error)
                return False

    def _release_name(self):
        with self.state_lock:
            name = self.claimed_name
            self.claimed_name = None
        if name is not None:
            self.server._release_name(name)

    def _discard(self, upload):
        file = upload.get('file')
        if file is not None:
            try:
                file.close()
            except OSError:
                pass
            upload['file'] = None
        try:
            upload['temporary'].unlink(missing_ok=True)
        except OSError as error:
            LOGGER.warning('[MiniMedia] 删除临时文件失败 %s：%s', upload['temporary'], error)

    def close(self):
        with self.state_lock:
            if self.closed:
                return
            self.closed = True
            upload = self.upload
            self.upload = None
        if upload is not None:
            self._discard(upload)
        self._release_name()
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.connection.close()
        except OSError:
            pass
        self.server._session_finished(self)

    def run(self):
        try:
            self.connection.settimeout(self.timeout)
            while True:
                try:
                    data = self.connection.recv(65536)
                except socket.timeout as error:
                    raise TimeoutError(f'MiniMedia 接收超时（{self.timeout:g}s）') from error
                if not data:
                    break
                for version, magic, body in self.stream.feed(data):
                    if self.closed:
                        return
                    self._dispatch(version, magic, body)
        except (OSError, ValueError, TimeoutError) as error:
            with self.state_lock:
                shutdown = self.closed
            if shutdown:
                LOGGER.debug('[MiniMedia] %s 会话关闭时中断接收：%s',
                             self.address, error)
                return
            name = None
            with self.state_lock:
                if self.upload is not None:
                    name = self.upload['name']
            details = {'error': str(error), 'name': name or ''}
            if isinstance(error, UploadRejected):
                details['status'] = error.status
            self._emit('error', **details)
            LOGGER.warning('[MiniMedia] %s 会话失败：%s', self.address, error)
        except Exception as error:
            self._emit('error', error=str(error))
            LOGGER.exception('[MiniMedia] %s 会话异常', self.address)
        finally:
            self.close()

    def _dispatch(self, version, magic, body):
        if magic == protocol.WORB:
            if body:
                raise ValueError('WORB 不应携带负载')
            self.worb_options.append(version)
            LOGGER.info('[MiniMedia] %s WORB option=0x%08X（只记录，不回复）',
                        self.address, version)
            return
        if version != VERSION:
            LOGGER.warning('[MiniMedia] %s 收到版本号 0x%08X（预期 0x%08X）',
                           self.address, version, VERSION)
        if magic == protocol.LIFD:
            self._handle_info(self._parse_info(body), body)
        elif magic == protocol.BFPU:
            self._handle_data(self._parse_data(body))
        else:
            raise ValueError(f'不支持的 MiniMedia 请求：0x{magic:08X}')

    def _parse_info(self, body):
        parsed = None
        try:
            parsed = protocol.parse_upload_info(body)
        except (ValueError, TypeError, UnicodeError, struct.error) as error:
            LOGGER.debug('[MiniMedia] parse_upload_info 回退原始解析：%s', error)
        if parsed is not None:
            try:
                sequence = int(_field(parsed, _INFO_SEQUENCE_KEYS))
                size = int(_field(parsed, _INFO_SIZE_KEYS))
                name = _field(parsed, _INFO_NAME_KEYS)
                if isinstance(name, str):
                    return {'sequence': sequence, 'size': size, 'name': name}
            except (TypeError, ValueError):
                pass
        try:
            return _parse_info_raw(body)
        except ValueError:
            if len(body) < 4:
                raise
            sequence = struct.unpack_from('<I', body)[0]
            return {'sequence': sequence, 'size': 0, 'name': '\x00'}

    def _parse_data(self, body):
        parsed = None
        try:
            parsed = protocol.parse_upload_data(body)
        except (ValueError, TypeError, UnicodeError, struct.error) as error:
            LOGGER.debug('[MiniMedia] parse_upload_data 回退原始解析：%s', error)
        if parsed is not None:
            try:
                sequence = int(_field(parsed, _DATA_SEQUENCE_KEYS))
                status = int(_field(parsed, _DATA_STATUS_KEYS, 0) or 0)
                data = _field(parsed, _DATA_PAYLOAD_KEYS)
                if isinstance(data, (bytes, bytearray, memoryview)):
                    return {'sequence': sequence, 'status': status, 'data': bytes(data)}
            except (TypeError, ValueError):
                pass
        return _parse_data_raw(body)

    def _reject(self, status, message, sequence):
        self._send(_build_response(sequence, status, 0))
        raise UploadRejected(status, message)

    def _handle_info(self, info, body):
        with self.state_lock:
            if self.info_received:
                self._reject(STATUS_BAD_REQUEST, '同一连接只能提交一个文件', info['sequence'])
            self.info_received = True
        sequence, size, name = info['sequence'], info['size'], info['name']
        if size < 0 or size > self.maximum:
            self._reject(STATUS_TOO_LARGE, f'文件超过接收大小限制 {self.maximum}', sequence)
        try:
            _validate_name(name)
            if _has_embedded_nul(body):
                raise ValueError('文件名包含 NUL')
        except (ValueError, UnicodeError) as error:
            self._reject(STATUS_BAD_NAME, str(error), sequence)

        target = self.directory / name
        temporary = self.directory / f'.{name}.part'
        if target.parent != self.directory or target.name != name:
            self._reject(STATUS_BAD_NAME, '目标不在接收目录内', sequence)
        if not self.server._claim_name(name, target, temporary):
            self._reject(STATUS_DUPLICATE, f'接收文件已存在或正在上传：{name}', sequence)

        try:
            file = temporary.open('xb')
        except OSError as error:
            self.server._release_name(name)
            self._reject(STATUS_IO_ERROR, f'创建临时文件失败：{error}', sequence)
        with self.state_lock:
            self.claimed_name = name
            self.upload = {
                'sequence': sequence,
                'size': size,
                'name': name,
                'target': target,
                'temporary': temporary,
                'file': file,
                'received': 0,
            }
        if not self._send(_build_response(sequence, 0, 0)):
            raise OSError('发送 TRFD 失败')
        self._emit('started', name=name, size=size, sequence=sequence)

    def _handle_data(self, data):
        with self.state_lock:
            upload = self.upload
        if upload is None:
            raise ValueError('BFPU 在 LIFD 之前到达')
        sequence, status, chunk = data['sequence'], data['status'], data['data']
        if sequence != upload['sequence']:
            raise ValueError(f'BFPU 序号 {sequence} 与 LIFD {upload["sequence"]} 不一致')
        if status:
            raise ValueError(f'BFPU 状态非零：{status}')
        if len(chunk) > self.max_block:
            raise ValueError(f'BFPU 数据块超过 {self.max_block} 字节')
        if upload['received'] + len(chunk) > upload['size']:
            raise ValueError('BFPU 数据超过 LIFD 声明的文件大小')
        if not chunk:
            self._finish(upload)
            return
        upload['file'].write(chunk)
        upload['received'] += len(chunk)

    def _finish(self, upload):
        received, size = upload['received'], upload['size']
        if received != size:
            raise ValueError(f'上传结束时文件大小不完整：{received}/{size}')
        file = upload['file']
        file.flush()
        file.close()
        upload['file'] = None
        target, temporary = upload['target'], upload['temporary']
        if target.exists() or target.is_symlink():
            raise ValueError('目标文件在上传期间已存在')
        os.replace(temporary, target)
        with self.state_lock:
            if self.upload is upload:
                self.upload = None
        self._release_name()
        self._emit('completed', name=upload['name'], path=str(target),
                   size=size, received=received, sequence=upload['sequence'])


class MiniMediaServer:
    """独立 TCP 接收服务；start/close 可重复、线程安全地调用。"""

    def __init__(self, bind_ip, port, directory, event_handler=None,
                 maximum=DEFAULT_MAX_FILE, timeout=DEFAULT_TIMEOUT,
                 max_block=DEFAULT_MAX_BLOCK,
                 max_frame_body=DEFAULT_MAX_FRAME_BODY,
                 *, allow_ephemeral=False):
        if isinstance(port, bool) or not isinstance(port, int):
            raise ValueError('MiniMedia 监听端口必须是整数')
        if port == 0:
            if not allow_ephemeral:
                raise ValueError('端口 0 仅用于测试自动分配；生产端口必须显式指定 1..65535')
        elif not 1 <= port <= 65535:
            raise ValueError('MiniMedia 监听端口必须在 1 到 65535 之间')
        if not isinstance(maximum, int) or maximum <= 0:
            raise ValueError('文件大小上限必须为正整数')
        if not isinstance(max_block, int) or max_block <= 0:
            raise ValueError('数据块上限必须为正整数')
        if not isinstance(max_frame_body, int) or max_frame_body < max_block + 8:
            raise ValueError('bodyLength 上限必须至少能容纳一个数据块')
        self.timeout = float(timeout)
        if self.timeout <= 0:
            raise ValueError('接收超时必须为正数')

        self.bind_ip = bind_ip
        self.requested_port = port
        self.port = port
        self.bound_port = None
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.directory.is_dir():
            raise ValueError(f'接收目录无效：{self.directory}')
        self.event_handler = event_handler
        self.maximum = maximum
        self.max_block = max_block
        self.max_frame_body = max_frame_body

        self.listener = None
        self.thread = None
        self.sessions = set()
        self._active_names = set()
        self.lock = threading.RLock()
        self.names_lock = threading.Lock()
        self.stopping = threading.Event()

    @classmethod
    def for_test(cls, bind_ip, directory, **kwargs):
        return cls(bind_ip, 0, directory, allow_ephemeral=True, **kwargs)

    def start(self):
        with self.lock:
            if self.listener is not None:
                return self.bound_port
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((self.bind_ip, self.requested_port))
                listener.listen(BACKLOG)
                listener.settimeout(0.5)
            except BaseException:
                listener.close()
                raise
            stopping = threading.Event()
            self.listener = listener
            self.stopping = stopping
            self.bound_port = listener.getsockname()[1]
            self.port = self.bound_port
            thread = threading.Thread(target=self._accept_loop,
                                      args=(listener, stopping),
                                      name='minimedia-listen', daemon=True)
            self.thread = thread
            thread.start()
            LOGGER.info('[MiniMedia] 上传接收监听 %s:%d 目录=%s',
                        self.bind_ip, self.bound_port, self.directory)
            return self.bound_port

    def _accept_loop(self, listener, stopping):
        while not stopping.is_set():
            try:
                connection, address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if stopping.is_set():
                connection.close()
                break
            connection.settimeout(self.timeout)
            session = UploadSession(self, connection, address)
            with self.lock:
                self.sessions.add(session)
            threading.Thread(target=session.run, name='minimedia-upload',
                             daemon=True).start()

    def _emit(self, kind, address, details):
        handler = self.event_handler
        if handler is None:
            return
        try:
            handler(kind, address, details)
        except Exception:
            LOGGER.exception('[MiniMedia] 事件回调失败 kind=%s', kind)

    def _session_finished(self, session):
        with self.lock:
            self.sessions.discard(session)

    def _claim_name(self, name, target, temporary):
        with self.names_lock:
            if name in self._active_names:
                return False
            if target.exists() or target.is_symlink() or temporary.exists():
                return False
            try:
                if target.resolve(strict=False).parent != self.directory:
                    return False
            except OSError:
                return False
            self._active_names.add(name)
            return True

    def _release_name(self, name):
        with self.names_lock:
            self._active_names.discard(name)

    def close(self):
        with self.lock:
            listener = self.listener
            thread = self.thread
            sessions = list(self.sessions)
            self.listener = None
            self.thread = None
            self.bound_port = None
            self.stopping.set()
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        for session in sessions:
            session.close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
