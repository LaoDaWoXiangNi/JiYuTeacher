"""MiniMedia 学生上传方向的协议帧构造与解析。

公共帧头为 12 字节 ``<III>``：version 0x10000、magic、bodyLength；
完整包长 = 12 + bodyLength。WORB 是客户端首包且服务器无应答；LIFD 携带
序号、64 位文件大小与含终止 NUL 的 UTF-16LE 路径，服务器回 TRFD；BFPU
顺序携带文件数据，零长度且 status=0 的 BFPU 表示上传完成。
"""

import struct

VERSION = 0x10000
WORB = 0x42524F57
LIFD = 0x4446494C
TRFD = 0x44465254
BFPU = 0x55504642

HEADER = struct.Struct('<III')
INFO_PREFIX = struct.Struct('<IQ')
RESPONSE_BODY = struct.Struct('<IIQIQ')
DATA_PREFIX = struct.Struct('<II')

MAX_BLOCK = 65536
MAX_PATH_BYTES = 520
U32_MAX = 0xFFFFFFFF
U64_MAX = 0xFFFFFFFFFFFFFFFF

__all__ = [
    'VERSION', 'WORB', 'LIFD', 'TRFD', 'BFPU', 'HEADER',
    'MAX_BLOCK', 'MAX_PATH_BYTES',
    'frame', 'worb', 'decode_frame',
    'upload_info', 'parse_upload_info',
    'upload_response', 'parse_upload_response',
    'upload_data', 'parse_upload_data',
]


def _unsigned(value, maximum, name):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f'MiniMedia {name} 超出范围')
    return value


def _octets(value, name):
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError(f'MiniMedia {name} 必须是字节序列')
    return bytes(value)


def frame(magic, body=b'', version=VERSION):
    """构造 ``[version][magic][bodyLength][body]`` 帧。"""
    _unsigned(version, U32_MAX, 'version')
    _unsigned(magic, U32_MAX, 'magic')
    body = _octets(body, 'body')
    if len(body) > U32_MAX:
        raise ValueError('MiniMedia 负载长度超出 u32 范围')
    return HEADER.pack(version, magic, len(body)) + body


def worb(option=VERSION):
    """构造 12 字节 WORB 首包；服务器不回应，不应等待响应。"""
    return frame(WORB, version=option)


def decode_frame(packet):
    """解析完整帧，返回 ``(version, magic, body)``。"""
    packet = _octets(packet, 'packet')
    if len(packet) < HEADER.size:
        raise ValueError('MiniMedia 包头不足 12 字节')
    version, magic, length = HEADER.unpack_from(packet)
    if len(packet) != HEADER.size + length:
        raise ValueError('MiniMedia 包声明长度与实际长度不符')
    return version, magic, packet[HEADER.size:]


def _encode_path(path):
    if not isinstance(path, str):
        raise ValueError('MiniMedia 上传路径必须是字符串')
    if not path or '\x00' in path:
        raise ValueError('MiniMedia 上传路径无效')
    try:
        encoded = path.encode('utf-16-le')
    except UnicodeEncodeError as error:
        raise ValueError('MiniMedia 上传路径不是有效 UTF-16') from error
    if len(encoded) + 2 > MAX_PATH_BYTES:
        raise ValueError('MiniMedia 上传路径过长')
    return encoded + b'\x00\x00'


def upload_info(sequence, path, size):
    """构造 LIFD 文件信息请求：``<IQ>`` + UTF-16LE 路径 + 终止 NUL。"""
    _unsigned(sequence, U32_MAX, '序号')
    _unsigned(size, U64_MAX, '文件大小')
    body = INFO_PREFIX.pack(sequence, size) + _encode_path(path)
    return frame(LIFD, body)


def parse_upload_info(body):
    """严格解析 LIFD 负载，返回 ``sequence``、``size``、``path``。"""
    body = _octets(body, 'LIFD 负载')
    if (len(body) < INFO_PREFIX.size + 2 or len(body) % 2
            or len(body) > INFO_PREFIX.size + MAX_PATH_BYTES):
        raise ValueError('LIFD 负载长度无效')
    sequence, size = INFO_PREFIX.unpack_from(body)
    raw = body[INFO_PREFIX.size:]
    if raw[-2:] != b'\x00\x00':
        raise ValueError('LIFD 路径缺少终止 NUL')
    try:
        text = raw.decode('utf-16-le', errors='strict')
    except UnicodeDecodeError as error:
        raise ValueError('LIFD 路径不是有效 UTF-16LE') from error
    path = text[:-1]
    if not path or '\x00' in path:
        raise ValueError('LIFD 文件路径无效')
    return {'sequence': sequence, 'size': size, 'path': path}


def upload_response(sequence, status=0, size=0, attributes=0x80, timestamp=0):
    """构造固定 28 字节负载的 TRFD 应答：``<IIQIQ>``。"""
    _unsigned(sequence, U32_MAX, '序号')
    _unsigned(status, U32_MAX, '状态')
    _unsigned(size, U64_MAX, '文件大小')
    _unsigned(attributes, U32_MAX, '文件属性')
    _unsigned(timestamp, U64_MAX, '时间戳')
    return frame(TRFD, RESPONSE_BODY.pack(sequence, status, size, attributes, timestamp))


def parse_upload_response(body):
    """严格解析 TRFD 负载，返回五个字段。"""
    body = _octets(body, 'TRFD 负载')
    if len(body) != RESPONSE_BODY.size:
        raise ValueError(f'TRFD 负载长度必须为 {RESPONSE_BODY.size} 字节')
    sequence, status, size, attributes, timestamp = RESPONSE_BODY.unpack(body)
    return {'sequence': sequence, 'status': status, 'size': size,
            'attributes': attributes, 'timestamp': timestamp}


def upload_data(sequence, data, final=False):
    """构造 BFPU 数据帧；零长度帧固定 status=0 表示上传完成。

    携带数据且 ``final`` 为真时，把 status/结束标志置 1；否则为 0。
    """
    _unsigned(sequence, U32_MAX, '序号')
    data = _octets(data, '数据块')
    if len(data) > MAX_BLOCK:
        raise ValueError(f'单个 BFPU 数据块不能超过 {MAX_BLOCK} 字节')
    if not isinstance(final, (bool, int)):
        raise ValueError('MiniMedia 结束标志无效')
    status = 1 if final and data else 0
    return frame(BFPU, DATA_PREFIX.pack(sequence, status) + data)


def parse_upload_data(body):
    """严格解析 BFPU 负载，返回 ``sequence``、``status``、``data``。"""
    body = _octets(body, 'BFPU 负载')
    if len(body) < DATA_PREFIX.size:
        raise ValueError('BFPU 负载长度不足 8 字节')
    sequence, status = DATA_PREFIX.unpack_from(body)
    data = body[DATA_PREFIX.size:]
    if len(data) > MAX_BLOCK:
        raise ValueError(f'单个 BFPU 数据块不能超过 {MAX_BLOCK} 字节')
    return {'sequence': sequence, 'status': status, 'data': data}
