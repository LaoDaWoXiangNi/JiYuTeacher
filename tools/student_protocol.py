"""极域 V6 学生端模拟所需的无副作用协议构造函数。"""
from __future__ import annotations

import getpass
import os
import platform
import socket
import struct
import uuid
from typing import Iterable, Sequence

MAIN_PORT = 4705
SESSION_BASE_PORT = 5000
SESSION_PORT_STRIDE = 0x200
MAIN_MCAST = '224.50.50.42'

MAGIC_LOGI = 0x49474F4C
MAGIC_ANNO = 0x4F4E4E41
MAGIC_MESS = 0x5353454D
MAGIC_QRMS = 0x534D5251
MAGIC_RRMS = 0x534D5252
MAGIC_LPNT = 0x544E504C
MAGIC_DMOC = 0x434F4D44

LOGI_SIZE = 0x300
SYSTEM_INFO_SIZE = 0x2FA
HAND_UP_FLAG = 0x100000
STUDENT_GUID = uuid.UUID('f96a6d19-5b29-46b9-ab95-8a143ecddc26')
LPNT_GUID = bytes.fromhex('aa3a8dbe2b906645908ea29526218540')


def session_endpoint(channel: int) -> tuple[str, int]:
    if not 1 <= channel <= 32:
        raise ValueError('频道必须在 1 到 32 之间')
    return f'225.2.{channel + 1}.1', SESSION_BASE_PORT + channel * SESSION_PORT_STRIDE


def packet(magic: int, version: int, body: bytes, guid: bytes = STUDENT_GUID.bytes_le) -> bytes:
    if len(guid) != 16:
        raise ValueError('GUID 必须为 16 字节')
    return struct.pack('<III', magic, version, len(body)) + guid + body


def fixed_wstr(text: str, chars: int) -> bytes:
    encoded = text.encode('utf-16-le')[:max(0, chars - 1) * 2]
    return encoded + b'\x00' * (chars * 2 - len(encoded))


def decode_wstr(raw: bytes) -> str:
    if len(raw) % 2:
        raw = raw[:-1]
    return raw.decode('utf-16-le', errors='replace').split('\x00', 1)[0]


def build_logi(student_ip: str, computer_name: str, user_name: str,
               channel: int = 1, student_id: int = 1) -> bytes:
    socket.inet_aton(student_ip)
    session_endpoint(channel)
    body = bytearray(LOGI_SIZE - 28)
    body[0:4] = socket.inet_aton(student_ip)
    struct.pack_into('<II', body, 4, channel, student_id & 0xFFFFFFFF)
    body[12:76] = fixed_wstr(computer_name, 32)
    body[76:140] = fixed_wstr(user_name, 32)
    result = packet(MAGIC_LOGI, 0x10000, bytes(body))
    if len(result) != LOGI_SIZE:
        raise AssertionError('LOGI 长度错误')
    return result


def build_mess(recipient_ip: str, payload: bytes) -> bytes:
    socket.inet_aton(recipient_ip)
    return struct.pack('<III', MAGIC_MESS, 1, 1) + socket.inet_aton(recipient_ip) + payload


def split_mess(data: bytes) -> tuple[int, int, tuple[str, ...], bytes]:
    if len(data) < 12:
        raise ValueError('MESS 包头不足')
    magic, sender_id, count = struct.unpack_from('<III', data)
    if magic != MAGIC_MESS:
        raise ValueError('不是 MESS 包')
    header_len = 12 + count * 4
    if count > 64 or len(data) < header_len:
        raise ValueError('MESS 接收者列表无效')
    recipients = tuple(socket.inet_ntoa(data[12 + i * 4:16 + i * 4]) for i in range(count))
    return sender_id, count, recipients, data[header_len:]


def message_payload(msg_type: int, category: int = 0, subtype: int = 0,
                    rest: bytes = b'') -> bytes:
    return struct.pack('<IIII', 16 + len(rest), msg_type, category, subtype) + rest


def build_chat(teacher_ip: str, text: str) -> bytes:
    raw = text.encode('utf-16-le') + b'\x00\x00'
    payload = struct.pack('<IIII', 16 + len(raw), 0x800, 0, len(raw) // 2) + raw
    return build_mess(teacher_ip, payload)


def build_anno(hand_up: bool = False, blackscreen_flags: int = 0,
               student_flags: int = 0, student_demo: bool = False) -> bytes:
    state = [0] * 16
    state[0] = 0x04 if student_demo else 0
    state[1] = blackscreen_flags & 0xFFFFFFFF
    state[2] = (student_flags | (HAND_UP_FLAG if hand_up else 0)) & 0xFFFFFFFF
    result = struct.pack('<II', MAGIC_ANNO, 0x10000) + struct.pack('<16I', *state)
    if len(result) != 72:
        raise AssertionError('ANNO 长度错误')
    return result


def local_mac() -> bytes:
    raw = uuid.getnode()
    if raw & (1 << 40):
        return b'\x00' * 6
    return raw.to_bytes(6, 'big')


def machine_facts(computer_name: str | None = None, user_name: str | None = None) -> dict:
    try:
        user = user_name if user_name is not None else getpass.getuser()
    except Exception:
        user = user_name or 'student'
    system = platform.system() or 'Unknown'
    memory_mb = 0
    if system == 'Windows':
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                            ('total', ctypes.c_ulonglong), ('available', ctypes.c_ulonglong),
                            ('total_page', ctypes.c_ulonglong), ('available_page', ctypes.c_ulonglong),
                            ('total_virtual', ctypes.c_ulonglong), ('available_virtual', ctypes.c_ulonglong),
                            ('available_extended', ctypes.c_ulonglong)]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                memory_mb = status.total // (1024 * 1024)
        except (AttributeError, OSError, ValueError):
            pass
    if not memory_mb:
        try:
            pages = os.sysconf('SC_PHYS_PAGES')
            page_size = os.sysconf('SC_PAGE_SIZE')
            memory_mb = pages * page_size // (1024 * 1024)
        except (AttributeError, OSError, ValueError):
            pass
    cpu = platform.processor() or platform.machine() or 'Unknown'
    return {
        'name': computer_name or platform.node() or socket.gethostname() or 'STUDENT-SIM',
        'stu_id': 1,
        'mac': local_mac(),
        'user': user or 'student',
        'os': system,
        'osver': f'{platform.release()} {platform.version()}'.strip(),
        'cpu_vendor': platform.machine() or 'Unknown',
        'cpu_model': cpu,
        'mem': f'{memory_mb} MB' if memory_mb else 'Unknown',
    }


def build_system_info(teacher_ip: str, facts: dict) -> bytes:
    payload = bytearray(SYSTEM_INFO_SIZE)
    struct.pack_into('<IIII', payload, 0, SYSTEM_INFO_SIZE, 0, 0x800000, 5)
    payload[0x10:0x50] = fixed_wstr(str(facts['name']), 32)
    struct.pack_into('<I', payload, 0x50, int(facts.get('stu_id', 1)) & 0xFFFFFFFF)
    mac = bytes(facts.get('mac', b'\x00' * 6))
    payload[0x54:0x5A] = mac[:6].ljust(6, b'\x00')
    payload[0x5A:0x9A] = fixed_wstr(str(facts['user']), 32)
    payload[0x9A:0xDA] = fixed_wstr(str(facts['os']), 32)
    payload[0xDA:0x11A] = fixed_wstr(str(facts['osver']), 32)
    payload[0x21A:0x25A] = fixed_wstr(str(facts['cpu_vendor']), 32)
    payload[0x25A:0x2DA] = fixed_wstr(str(facts['cpu_model']), 64)
    payload[0x2DA:0x2FA] = fixed_wstr(str(facts['mem']), 16)
    return build_mess(teacher_ip, bytes(payload))


def encode_id_name_pairs(entries: Iterable[tuple[int, str]]) -> bytes:
    result = bytearray()
    for item_id, name in entries:
        if not 0 <= int(item_id) <= 0xFFFFFFFF:
            raise ValueError('条目 ID 超出 u32 范围')
        result += struct.pack('<I', int(item_id))
        result += name.encode('utf-16-le') + b'\x00\x00'
    return bytes(result)


def decode_id_name_pairs(raw: bytes) -> list[tuple[int, str]]:
    result = []
    pos = 0
    while pos + 6 <= len(raw):
        item_id = struct.unpack_from('<I', raw, pos)[0]
        pos += 4
        chars = bytearray()
        while pos + 2 <= len(raw) and raw[pos:pos + 2] != b'\x00\x00':
            chars += raw[pos:pos + 2]
            pos += 2
        if pos + 2 > len(raw):
            break
        result.append((item_id, chars.decode('utf-16-le', errors='replace')))
        pos += 2
    return result


def build_info_list(teacher_ip: str, subtype: int,
                    entries: Sequence[tuple[int, str]], max_chunk: int = 1000) -> list[bytes]:
    if subtype not in (6, 7):
        raise ValueError('信息列表 subtype 必须为 6 或 7')
    if not entries:
        raw = message_payload(0, 0x800000, subtype, struct.pack('<I', 1))
        return [build_mess(teacher_ip, raw)]
    packets = []
    chunk = bytearray()
    chunk_flag = 1
    for entry in entries:
        encoded = encode_id_name_pairs([entry])
        if chunk and len(chunk) + len(encoded) > max_chunk:
            raw = message_payload(0, 0x800000, subtype,
                                  struct.pack('<I', chunk_flag) + bytes(chunk))
            packets.append(build_mess(teacher_ip, raw))
            chunk.clear()
            chunk_flag = 0
        chunk += encoded
    raw = message_payload(0, 0x800000, subtype,
                          struct.pack('<I', chunk_flag) + bytes(chunk))
    packets.append(build_mess(teacher_ip, raw))
    return packets


def build_info_reply(teacher_ip: str, rtype: int, facts: dict,
                     windows: Sequence[tuple[int, str]] = (),
                     processes: Sequence[tuple[int, str]] = ()) -> list[bytes]:
    if rtype not in (0, 1, 2):
        raise ValueError(f'不支持的信息请求类型：{rtype}')
    packets = []
    if rtype == 0:
        packets.append(build_system_info(teacher_ip, facts))
    if rtype in (0, 1):
        packets.extend(build_info_list(teacher_ip, 6, windows))
    if rtype in (0, 2):
        packets.extend(build_info_list(teacher_ip, 7, processes))
    return packets


def build_submit_request(teacher_ip: str, directory: str,
                         file_list: str, file_count: int = 1,
                         total_size: int = 0,
                         transaction_guid: uuid.UUID | None = None,
                         student_id: int = 0) -> bytes:
    socket.inet_aton(teacher_ip)
    if not 0 <= file_count <= 0xFFFFFFFF:
        raise ValueError('文件数超出范围')
    if not 0 <= total_size <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError('文件总大小超出范围')
    if not 0 <= student_id <= 0xFFFFFFFF:
        raise ValueError('学生 ID 超出 u32 范围')
    transaction_guid = transaction_guid or uuid.uuid4()
    fields = (student_id, 1, 0, 0, 0,
              total_size & 0xFFFFFFFF, total_size >> 32, file_count)
    body = bytearray(0x284 - 28)
    struct.pack_into('<8I', body, 0, *fields)
    body[32:96] = fixed_wstr(directory, 32)
    body[96:616] = fixed_wstr(file_list, 260)
    return packet(MAGIC_QRMS, 0x10000, bytes(body), transaction_guid.bytes_le)


def build_submit_response(student_id: int, accept: int, arg2: int,
                          quota: int = 1, max_files: int = 0,
                          transaction_guid: uuid.UUID | None = None) -> bytes:
    values = (student_id, accept, arg2, quota & 0xFFFFFFFF,
              (quota >> 32) & 0xFFFFFFFF, max_files)
    if any(not 0 <= value <= 0xFFFFFFFF for value in values):
        raise ValueError('RRMS 字段超出 u32 范围')
    if not 0 <= quota <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError('RRMS 配额超出 u64 范围')
    transaction_guid = transaction_guid or uuid.uuid4()
    body = struct.pack('<6I', *values)
    result = packet(MAGIC_RRMS, 0x10000, body, transaction_guid.bytes_le)
    if len(result) != 52:
        raise AssertionError('RRMS 长度错误')
    return result


def parse_submit_response(data: bytes) -> dict:
    if len(data) != 52:
        raise ValueError(f'RRMS 总长必须为 52 字节，实际 {len(data)}')
    magic, version, declared = struct.unpack_from('<III', data)
    if magic != MAGIC_RRMS:
        raise ValueError(f'RRMS 魔数错误：0x{magic:08X}')
    if version != 0x10000:
        raise ValueError(f'RRMS 版本错误：0x{version:08X}')
    if declared != 0x18:
        raise ValueError(f'RRMS 声明负载长度必须为 0x18，实际 0x{declared:X}')
    fields = struct.unpack_from('<6I', data, 28)
    return {
        'transaction_guid': data[12:28].hex(),
        'student_id': fields[0],
        'accept': fields[1],
        'arg2': fields[2],
        'arg3': fields[3],
        'quota': fields[3] | fields[4] << 32,
        'max_files': fields[5],
        'fields': fields,
    }


def parse_submit_request(data: bytes) -> dict:
    if len(data) != 0x284 or struct.unpack_from('<I', data)[0] != MAGIC_QRMS:
        raise ValueError('QRMS 包长度或魔数错误')
    fields = struct.unpack_from('<8I', data, 28)
    return {
        'transaction_guid': data[12:28].hex(),
        'student_id': fields[0],
        'directory': decode_wstr(data[60:124]),
        'file_list': decode_wstr(data[124:644]),
        'file_count': fields[7],
        'total_size': fields[5] | fields[6] << 32,
        'fields': fields,
    }


def parse_lpnt(data: bytes) -> dict:
    if len(data) < 48 or struct.unpack_from('<I', data)[0] != MAGIC_LPNT:
        raise ValueError('LPNT 包长度或魔数错误')
    declared = struct.unpack_from('<I', data, 8)[0]
    if declared < 20 or len(data) < 28 + declared:
        raise ValueError('LPNT 策略长度无效')
    version, enabled, width, height, refresh = struct.unpack_from('<IIIII', data, 28)
    return {'version': version, 'enabled': bool(enabled), 'width': width,
            'height': height, 'refresh_seconds': refresh, 'declared_length': declared}


def parse_comd(data: bytes) -> tuple[int, int, bytes]:
    if len(data) < 44 or struct.unpack_from('<I', data)[0] != MAGIC_DMOC:
        raise ValueError('COMD 包长度或魔数错误')
    declared = struct.unpack_from('<I', data, 8)[0]
    if len(data) < 28 + declared or declared < 16:
        raise ValueError('COMD 声明长度无效')
    cmd_code, cmd_id, payload_len = struct.unpack_from('<III', data, 28)
    if payload_len > declared - 16 or len(data) < 44 + payload_len:
        raise ValueError('COMD 负载长度无效')
    return cmd_code, cmd_id, data[44:44 + payload_len]


def parse_dmoc(data: bytes) -> dict:
    if len(data) < 32 or struct.unpack_from('<I', data)[0] != MAGIC_DMOC:
        raise ValueError('DMOC 包长度或魔数错误')
    declared = struct.unpack_from('<I', data, 8)[0]
    if len(data) < 28 + declared:
        raise ValueError('DMOC 声明长度无效')
    source_ip = socket.inet_ntoa(data[32:36]) if declared >= 8 else ''
    return {'length': declared, 'source_ip': source_ip}


def utf16_after(raw: bytes, offset: int) -> str:
    return decode_wstr(raw[offset:])
