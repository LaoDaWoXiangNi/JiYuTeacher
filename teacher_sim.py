#!/usr/bin/env python3
"""极域V6.0教师端 - 逐字节匹配真实抓包，带调试日志。

运行后会弹出两个窗口：
- 主窗口：显示命令提示符 teacher>，用于输入操作命令。
- 日志窗口：PowerShell 实时 tail teacher_sim.log。
"""
import socket, struct, threading, time, random, sys, os, uuid, colorsys, ipaddress
import logging, logging.handlers
import queue
import json
import re
import app_config
import gui_events
from classroom_store import ClassroomStore
from PIL import Image, ImageOps
import io
import subprocess

APP_DIR = os.path.dirname(sys.executable if getattr(sys, 'frozen', False)
                           else os.path.abspath(__file__))
LOG_DIR = os.path.abspath(os.environ.get('TEACHER_LOG_DIR') or APP_DIR)
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, 'teacher_sim.log')
SESSION_STATE_PATH = os.path.abspath(
    os.environ.get('TEACHER_SESSION_STATE')
    or os.path.join(LOG_DIR, 'teacher_network_state.json'))
REMOTE_VIEW_DIR = os.path.join(APP_DIR, 'teacher_remote_view')
SUBMISSION_DIR = os.path.join(APP_DIR, 'submissions')
SUBMISSION_MAX_BYTES = 64 * 1024 * 1024

# 默认文件日志级别：INFO 已足够，DEBUG 太占空间。
# 运行中可用 debug on/off 切换。
FILE_LOG_LEVEL = logging.INFO


def get_file_handler():
    """返回当前的文件日志 handler（不存在返回 None）。"""
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.handlers.RotatingFileHandler):
            return h
    return None


def set_file_log_level(level):
    """切换文件日志级别并持久化到全局变量。"""
    global FILE_LOG_LEVEL
    FILE_LOG_LEVEL = level
    fh = get_file_handler()
    if fh:
        fh.setLevel(level)


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # 允许 DEBUG 通过，由 handler 决定是否写入
    if logger.handlers:
        logger.handlers.clear()

    fh = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=10*1024*1024, backupCount=3, encoding='utf-8'
    )
    fh.setLevel(FILE_LOG_LEVEL)
    fmt = logging.Formatter(
        '%(asctime)s.%(msecs)03d [%(levelname)-8s] [%(threadName)-12s] %(filename)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 日志由独立窗口实时显示，主窗口只保留命令交互，所以不再输出到 stdout。
    # 如需在控制台也看日志，可取消下面注释。
    # ch = logging.StreamHandler(sys.stdout)
    # ch.setLevel(logging.INFO)
    # ch.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    # logger.addHandler(ch)

    logger.info('日志系统初始化完成，级别=%s，log 文件：%s',
                logging.getLevelName(FILE_LOG_LEVEL), LOG_PATH)
    try:
        from gui_events import install_log_bridge
        install_log_bridge(logger)
    except ImportError:
        pass
    return logger


def spawn_log_window():
    """在独立的命令行窗口中实时跟踪日志文件。"""
    # 确保日志文件已存在，避免 PowerShell Get-Content 报错。
    if not os.path.exists(LOG_PATH):
        open(LOG_PATH, 'a', encoding='utf-8').close()

    # 强制 PowerShell 控制台使用 UTF-8，避免中文日志乱码。
    ps_cmd = (
        f'chcp 65001 | Out-Null; '
        f'[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; '
        f'Get-Content -Path "{LOG_PATH}" -Wait -Tail 50 -Encoding UTF8'
    )
    try:
        subprocess.Popen(
            ['start', 'powershell', '-NoExit', '-Command', ps_cmd],
            shell=True,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print('[启动] 已打开实时日志窗口（PowerShell 跟踪 log，UTF-8）')
    except Exception as e:
        print(f'[启动] 打开日志窗口失败：{e}')


logger = setup_logging()

MCAST, PORT = '224.50.50.42', 4705
SESSION_MCAST_PREFIX = '225.2'
SESSION_BASE_PORT = 5000
SESSION_PORT_STRIDE = 0x200
TGUID = uuid.UUID('{F96A6D19-5B29-46B9-AB95-8A143ECDDC26}')

oonc_seq = 0
cmd_seq = 0

MAGIC_NAMES = {
    0x434E4F4F: 'OONC',
    0x434E414E: 'NANC',
    0x434E4143: 'CANC',
    0x41434157: 'WACA',
    0x544E5253: 'SRNT',
    0x434F4D44: 'DMOC',
    0x544E504C: 'LPNT',
    0x4143414B: 'KACA',
    0x434D5254: 'TRMC',
    0x544E5254: 'TRNT',
    0x544E4544: 'DENT',
    0x544E414C: 'LANT',
    0x4F4E4E41: 'ANNO',
    0x49474F4C: 'LOGI',
    0x4F474F4C: 'LOGO',
    0x5353454D: 'MESS',
    0x434E5154: 'TQNC',
    0x54584E46: 'FNXT',
    0x54585254: 'TRXT',
}

# 日常广播类魔数，不必逐条记录 hexdump
ROUTINE_MAGICS = {0x434E4F4F, 0x434E414E, 0x434E4143, 0x4F4E4E41}
CLIENT_PACKET_MAGICS = {0x434E5154, 0x54584E46, 0x54585254}

students = {}
previews = {}
completed_preview_frames = {}
preview_policy_versions = {}
preview_confirmed_versions = {}
preview_command_acks = {}
preview_published_at = {}
preview_image_cache = {}
preview_last_errors = {}
remote_views = {}
remote_controls = {}
screen_broadcasts = {}
student_demos = {}
remote_view_failures = {}
remote_view_last_error = {}
remote_state_lock = threading.RLock()
state_lock = threading.RLock()
network_lock = threading.RLock()
thread_lock = threading.RLock()
shutdown_lock = threading.RLock()
session_state_lock = threading.RLock()
network_stop_event = threading.Event()
background_threads = {}
last_status = {}
running = False
network_started = False
network_sockets_closed = True
network_error = None
# None=未退出；stopping=退出流程执行中；done=已完成。用于 shutdown 幂等。
shutdown_stage = None
single_instance_mutex = None
single_instance_locked = False
exclusive_addruse = False
sock = None
sock2 = None
session_id = None
generation = 0
SELECTED_NETWORK = None
_network_selection_cache = None
SUBMISSION_PORT = 0
submission_server = None
submission_listen_port = None
submission_lock = threading.RLock()
submission_transactions = {}
submission_active_uploads = {}
submission_receipts = {}
submission_receipt_sequence = 0

classroom_store = ClassroomStore()
try:
    classroom_active_class = classroom_store.get_active_class()
except Exception as error:
    classroom_active_class = None
    logger.error('[Classroom] 启动读取当前班级失败 path=%s error=%s',
                 classroom_store.path, error, exc_info=True)
classroom_observer = None
classroom_observer_lock = threading.RLock()
classroom_write_queue = queue.Queue()
classroom_write_thread = None
classroom_checked_in = set()
classroom_lock = threading.RLock()
classroom_shutdown = False


def _sleep_or_stop(seconds):
    return network_stop_event.wait(seconds)


def _start_managed_thread(name, target, args=()):
    with thread_lock:
        existing = background_threads.get(name)
        if existing is not None and existing.is_alive():
            return existing
        if existing is not None:
            background_threads.pop(name, None)
        thread = threading.Thread(target=target, name=name, args=args, daemon=True)
        background_threads[name] = thread
        try:
            thread.start()
        except Exception as error:
            background_threads.pop(name, None)
            logger.error('[Threads] %s 启动失败：%s', name, error, exc_info=True)
            return None
        return thread


def _join_thread(thread, timeout):
    if thread is None or not hasattr(thread, 'join'):
        return True
    try:
        alive = thread.is_alive()
    except Exception:
        alive = False
    if not alive:
        return True
    if thread is threading.current_thread():
        return False
    try:
        thread.join(max(0.0, timeout))
    except (RuntimeError, OSError) as error:
        logger.debug('[Threads] join 跳过：%s', error)
        return False
    try:
        return not thread.is_alive()
    except Exception:
        return True


def _join_background_threads():
    deadline = time.monotonic() + THREAD_JOIN_TIMEOUT
    with thread_lock:
        threads = list(background_threads.items())
    joined, alive = [], []
    for name, thread in threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            alive.append(name)
            continue
        if _join_thread(thread, remaining):
            joined.append(name)
        else:
            alive.append(name)
    with thread_lock:
        for name in joined:
            background_threads.pop(name, None)
    logger.info('[Threads] 有界 join 完成 joined=%s alive=%s timeout=%.2fs',
                joined, alive, THREAD_JOIN_TIMEOUT)
    return not alive


def _mark_student_seen(sip, source, via='unknown', logged_in=False):
    if not sip or sip == ip:
        return None
    now = time.time()
    with state_lock:
        entry = students.get(sip)
        if entry is None:
            entry = {
                'logged_in': False,
                'signal_only': True,
                'first_seen': now,
                'last_seen': now,
                'sources': set(),
            }
            students[sip] = entry
            logger.info('[Students] 发现信号源 %s via=%s source=%s', sip, via, source)
        entry['last_seen'] = now
        entry.setdefault('sources', set()).add(source)
        if logged_in:
            entry['logged_in'] = True
            entry['signal_only'] = False
            entry['logged_in_at'] = now
        elif not entry.get('logged_in'):
            entry['signal_only'] = True
        return dict(entry)


def _clear_student_runtime_state(sip):
    with state_lock:
        students.pop(sip, None)
        previews.pop(sip, None)
        completed_preview_frames.pop(sip, None)
        preview_policy_versions.pop(sip, None)
        preview_confirmed_versions.pop(sip, None)
        preview_command_acks.pop(sip, None)
        preview_published_at.pop(sip, None)
        preview_image_cache.pop(sip, None)
        preview_last_errors.pop(sip, None)
        remote_view_failures.pop(sip, None)
        remote_view_last_error.pop(sip, None)
        screen_broadcasts.pop(sip, None)
        student_demos.pop(sip, None)
        submission_transactions.pop(sip, None)
        for key in [key for key in last_status if key[0] == sip]:
            last_status.pop(key, None)
        timer = blackscreen_timers.pop(sip, None)
    return timer


def _handle_student_logout(sip, via='unknown'):
    timer = _clear_student_runtime_state(sip)
    if timer is not None:
        timer.cancel()
    with remote_state_lock:
        had_view = sip in remote_views
        had_control = sip in remote_controls
    if had_view:
        stop_remote_view(sip, notify=True)
    if had_control:
        stop_remote_control(sip, notify=True)
    logger.info('[LOGO] %s via=%s 已清理学生/预览/观看状态', sip, via)


def get_students_snapshot():
    with state_lock:
        snapshot = []
        for sip, entry in students.items():
            item = {
                'ip': sip,
                'logged_in': bool(entry.get('logged_in')),
                'signal_only': not bool(entry.get('logged_in')),
                'status': 'logged_in' if entry.get('logged_in') else 'signal_only',
                'first_seen': entry.get('first_seen'),
                'last_seen': entry.get('last_seen'),
                'last_seen_age': max(0.0, time.time() - (entry.get('last_seen') or 0)),
                'sources': sorted(entry.get('sources', ())),
                'info': dict(entry.get('info', {})),
                'mac': entry.get('info', {}).get('mac', ''),
                'anno_state': dict(entry.get('anno_state', {})),
            }
            snapshot.append(item)
    snapshot.sort(key=lambda item: item['last_seen'] or 0, reverse=True)
    return snapshot


def _drain_classroom_queue():
    while True:
        try:
            classroom_write_queue.get_nowait()
        except queue.Empty:
            break
        else:
            classroom_write_queue.task_done()


def _bounded_queue_join():
    deadline = time.monotonic() + CLASSROOM_JOIN_TIMEOUT
    while classroom_write_queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.01)
    remaining = classroom_write_queue.unfinished_tasks
    if remaining:
        logger.warning('[Classroom] 写盘队列 join 超时 unfinished=%d timeout=%.2fs',
                       remaining, CLASSROOM_JOIN_TIMEOUT)
        _drain_classroom_queue()
    return remaining == 0


def _reset_classroom_writer_for_restart():
    global classroom_shutdown, classroom_write_thread
    with classroom_lock:
        needs_reset = (classroom_shutdown or classroom_write_thread is None
                       or not classroom_write_thread.is_alive())
        if needs_reset:
            classroom_shutdown = False
            classroom_write_thread = None
            classroom_checked_in.clear()
    if needs_reset:
        _drain_classroom_queue()


def _next_preview_policy_versions(sip, count=1):
    if count < 1:
        raise ValueError('LPNT 版本数量必须大于 0')
    with state_lock:
        current = preview_policy_versions.get(sip, PREVIEW_POLICY_BASE)
        if not isinstance(current, int) or current < PREVIEW_POLICY_BASE:
            current = PREVIEW_POLICY_BASE
        versions = list(range(current + 1, current + count + 1))
        preview_policy_versions[sip] = versions[-1]
        return versions


def _send_lpnt(sip, version, enabled, label):
    packet = build_lpnt(version, enabled)
    ok = _send_main(packet, (sip, PORT), f'{label}/LPNT')
    logger.info('[Preview] %s LPNT -> %s version=%d enabled=%s ok=%s',
                label, sip, version, enabled, ok)
    return ok


def _send_dmoc(sip, label):
    packet = build_dmoc()
    ok = _send_main(packet, (sip, PORT), f'{label}/DMOC')
    logger.debug('[Preview] %s DMOC -> %s ok=%s', label, sip, ok)
    return ok


def _send_preview_policy(sip, enabled, label, count=1):
    versions = _next_preview_policy_versions(sip, count)
    results = []
    for index, version in enumerate(versions):
        state = enabled if count == 1 else (False if index == 0 else True)
        results.append(_send_lpnt(sip, version, state, label))
    results.append(_send_dmoc(sip, label))
    logger.info('[Preview] %s -> %s versions=%s enabled=%s sent=%s',
                label, sip, versions, enabled, all(results))
    return all(results)


def _ensure_preview_keepalive(sip):
    return _start_managed_thread(
        f'preview-keepalive-{sip}', keep_alive_preview, (sip,))


def _preview_missing_ranges(state):
    total = state['total']
    intervals = []
    for offset, length in state.get('received', {}).items():
        start = max(0, min(total, offset))
        end = max(start, min(total, offset + length))
        if end > start:
            intervals.append((start, end))
    intervals.sort()
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    missing = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            missing.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < total:
        missing.append((cursor, total))
    return missing


def _preview_missing_parts(state):
    """把按实际 offset 计算的缺失字节区间映射为 SRNT 的 0 基 uint16 分片号。"""
    parts = []
    for start, end in _preview_missing_ranges(state):
        first = start // 1024
        last = (end - 1) // 1024
        for index in range(first, last + 1):
            if index > 0xFFFF:
                return parts
            if index not in parts:
                parts.append(index)
            if len(parts) >= PREVIEW_MAX_MISSING_PARTS:
                return parts
    return parts


def _expire_preview_frames():
    now = time.monotonic()
    expired = []
    with state_lock:
        for sip, state in list(previews.items()):
            last_at = state.get('last_fragment_at', now)
            if now - last_at > PREVIEW_FRAME_TTL:
                previews.pop(sip, None)
                preview_last_errors[sip] = '预览帧 TTL 超时'
                expired.append(sip)
    for sip in expired:
        logger.info('[Preview] %s 重组帧 TTL 超时 ttl=%.2fs', sip, PREVIEW_FRAME_TTL)
    return expired


def get_preview_status(sip=None):
    _expire_preview_frames()
    with state_lock:
        frames = {}
        for student_ip, state in previews.items():
            if sip is not None and student_ip != sip:
                continue
            missing_ranges = _preview_missing_ranges(state)
            frames[student_ip] = {
                'frame_seq': state.get('frame_seq'),
                'total': state.get('total'),
                'got': state.get('got', 0),
                'received_offsets': sorted(state.get('received', {})),
                'missing_ranges': [list(item) for item in missing_ranges],
                'missing_offsets': [item[0] for item in missing_ranges],
                'missing_parts': _preview_missing_parts(state),
                'last_fragment_at': state.get('last_fragment_at'),
                'age_seconds': max(0.0, time.monotonic() - (state.get('last_fragment_at') or time.monotonic())),
                'ttl_seconds': PREVIEW_FRAME_TTL,
                'published': False,
                'last_error': state.get('last_error'),
                'publish_attempts': state.get('publish_attempts', 0),
            }
        expected = dict(preview_policy_versions)
        confirmed = dict(preview_confirmed_versions)
        acks = {key: dict(value) for key, value in preview_command_acks.items()}
        pending = {
            key: value for key, value in expected.items()
            if confirmed.get(key) != value
        }
        result = {
            'frames': frames,
            'published': dict(completed_preview_frames),
            'published_at': dict(preview_published_at),
            'policy_versions': expected,
            'expected_versions': expected,
            'confirmed_versions': confirmed,
            'pending_versions': pending,
            'command_acks': acks,
            'last_errors': dict(preview_last_errors),
            'cached_image_ips': sorted(preview_image_cache),
            'ttl_seconds': PREVIEW_FRAME_TTL,
        }
    if sip is not None:
        result['frames'] = frames.get(sip)
        result['published'] = completed_preview_frames.get(sip)
        result['policy_version'] = expected.get(sip, PREVIEW_POLICY_BASE)
        result['expected_version'] = expected.get(sip, PREVIEW_POLICY_BASE)
        result['confirmed_version'] = confirmed.get(sip)
        result['command_ack_count'] = acks.get(sip, {}).get('count', 0)
        result['policy_pending'] = sip in pending
        result['cached_image'] = sip in preview_image_cache
    return result


def get_preview_image(sip):
    with state_lock:
        image = preview_image_cache.get(sip)
        return image.copy() if image is not None else None


def _set_view_error(sip, reason):
    with remote_state_lock:
        remote_view_last_error[sip] = reason


def get_view_state(sip):
    with remote_state_lock:
        session = remote_views.get(sip)
        failure_time = remote_view_failures.get(sip)
        remaining = 0.0
        if failure_time is not None:
            remaining = max(0.0, VIEW_FAILURE_COOLDOWN - (time.monotonic() - failure_time))
        return {
            'active': session is not None and not session.stop_event.is_set(),
            'connected': bool(session and session.connected_event.is_set()),
            'cooldown_remaining': remaining,
            'cooldown_seconds': VIEW_FAILURE_COOLDOWN,
            'reason': remote_view_last_error.get(sip),
            'port': session.port if session is not None else None,
        }


def _mac_text_to_bytes(text):
    try:
        parts = str(text).replace(':', '-').split('-')
        if len(parts) != 6:
            return None
        return bytes(int(part, 16) for part in parts)
    except (TypeError, ValueError):
        return None


def _client_mac_index():
    with state_lock:
        index = {}
        for student_ip, entry in students.items():
            raw = _mac_text_to_bytes(entry.get('info', {}).get('mac', ''))
            if raw is not None:
                index[raw] = student_ip
        return index


def _handle_client_packet(mag, d, sip, via):
    """只识别/记录 TQNC/FNXT/TRXT；不回复、不伪造退出包。"""
    name = MAGIC_NAMES.get(mag, f'0x{mag:08X}')
    _mark_student_seen(sip, name, via)
    guid = d[12:28].hex() if len(d) >= 28 else ''
    if mag == 0x434E5154:  # TQNC
        channel_value = (struct.unpack('<I', d[28:32])[0]
                         if len(d) >= 32 else None)
        logger.info('[ClientPacket] TQNC from %s via=%s len=%d channel=%s guid=%s；'
                    '只记录频道退出通知，不回包', sip, via, len(d), channel_value, guid)
        return True
    if mag == 0x54584E46:  # FNXT
        declared_len = (struct.unpack('<I', d[8:12])[0]
                        if len(d) >= 12 else None)
        count = struct.unpack('<I', d[32:36])[0] if len(d) >= 36 else 0
        count = min(count, 1000)
        ids_start = 36
        ids_end = ids_start + 6 * count
        visible = d[ids_start:min(ids_end, len(d))]
        full_ids = [visible[i:i + 6] for i in range(0, len(visible) - 5, 6)]
        missing_ids = max(0, count - len(full_ids))
        unknown_tail = d[ids_end:ids_end + 6].hex() if len(d) >= ids_end + 6 else ''
        expected_len = ids_end + 6
        index = _client_mac_index()
        matches = [
            (i, raw.hex('-').upper(), index[raw])
            for i, raw in enumerate(full_ids) if raw in index
        ]
        logger.info('[ClientPacket] FNXT from %s via=%s len=%d declared_len=%s '
                    'guid=%s n=%d visible_ids=%d missing_ids=%d unknown_tail=%s '
                    'expected_len=%d matches=%s；6字节ID=MESS type5 payload+0x54 MAC；'
                    '目的封装/尾部6字节未证实，不伪造/不回包',
                    sip, via, len(d), declared_len, guid, count, len(full_ids),
                    missing_ids, unknown_tail, expected_len, matches)
        return True
    if mag == 0x54585254:  # TRXT
        client_id = d[32:38] if len(d) >= 38 else b''
        matched_ip = _client_mac_index().get(bytes(client_id)) if client_id else None
        logger.info('[ClientPacket] TRXT from %s via=%s len=%d guid=%s '
                    'client_id=%s matched_ip=%s；只记录退出确认，不回包',
                    sip, via, len(d), guid, client_id.hex('-') if client_id else '',
                    matched_ip)
        return True
    return False


def _handle_trmc(d, sip, via):
    """TRMC 是 DMOC 命令回执；只记录，不回 LPNT/DMOC。"""
    _mark_student_seen(sip, 'TRMC', via)
    client_id = (struct.unpack('<I', d[28:32])[0]
                 if len(d) >= 32 else None)
    with state_lock:
        entry = preview_command_acks.setdefault(sip, {'count': 0, 'last_seen': 0.0})
        entry['count'] += 1
        entry['last_seen'] = time.time()
        count = entry['count']
    logger.info('[Preview] TRMC from %s via=%s client_id=%s count=%d；'
                'DMOC 命令回执，不回 LPNT/DMOC', sip, via, client_id, count)
    return True


def _handle_trnt(d, sip, via):
    """TRNT 携带学生已确认 policy version；仅在期望版本不同时重发同一个期望版本。

    不递增版本：每个 LPNT 都会换来一个 TRNT，若每次不匹配都 +1，就会形成
    LPNT/TRNT 版本无限升级；官方 UpdatePolicy 是重发 context+0x04 的当前期望版本。
    """
    _mark_student_seen(sip, 'TRNT', via)
    if len(d) < 36:
        logger.warning('[Preview] TRNT 包过短 from %s via=%s len=%d', sip, via, len(d))
        return False
    confirmed = struct.unpack('<I', d[32:36])[0]
    with state_lock:
        preview_confirmed_versions[sip] = confirmed
        expected = preview_policy_versions.get(sip, PREVIEW_POLICY_BASE)
    if confirmed == expected:
        logger.info('[Preview] TRNT %s via=%s confirmed=%d expected=%d；策略已确认，不重发',
                    sip, via, confirmed, expected)
        return True
    ok = _send_lpnt(sip, expected, True, 'TRNT mismatch')
    logger.info('[Preview] TRNT %s via=%s confirmed=%d expected=%d -> '
                '重发期望版本 LPNT version=%d ok=%s（不递增版本、不回 DMOC）',
                sip, via, confirmed, expected, expected, ok)
    return ok


def bind_classroom_observer(callback):
    """注册班级变化回调；回调在 GUI 事件或写盘线程中收到轻量事件。"""
    if not callable(callback):
        raise TypeError('班级 observer 必须可调用')
    global classroom_observer
    with classroom_observer_lock:
        classroom_observer = callback


def unbind_classroom_observer(callback=None):
    global classroom_observer
    with classroom_observer_lock:
        if callback is None or callback is classroom_observer:
            classroom_observer = None


def _classroom_notify(event):
    with classroom_observer_lock:
        callback = classroom_observer
    if callback is None:
        return
    try:
        callback(event)
    except Exception as error:
        logger.error('[Classroom] observer 处理失败 event=%s error=%s',
                     event.get('kind'), error, exc_info=True)


def _checkout_all_now():
    with classroom_lock:
        targets = list(classroom_checked_in)
        classroom_checked_in.clear()
    if not targets:
        return
    grouped = {}
    for class_name, student_key in targets:
        grouped.setdefault(class_name, []).append(student_key)
    for class_name, keys in grouped.items():
        try:
            classroom_store.check_out_students(class_name, keys)
            for student_key in keys:
                logger.info('[Classroom] 退出签退 class=%s student_key=%s',
                            class_name, student_key)
        except Exception as error:
            logger.error('[Classroom] 退出签退失败 class=%s students=%s error=%s',
                         class_name, keys, error, exc_info=True)
            _classroom_notify({'kind': 'error', 'operation': '退出签退',
                               'class_name': class_name, 'error': error})
    logger.info('[Classroom] 本次运行签退完成 count=%d', len(targets))


def _classroom_writer():
    while True:
        item = classroom_write_queue.get()
        try:
            if item is None:
                _checkout_all_now()
                break
            action, event = item
            try:
                result = action()
                event['result'] = result
                if event['kind'] == 'student_info':
                    if result is None:
                        logger.info('[Classroom] 忽略未导入学生 ip=%s', event['ip'])
                    else:
                        with classroom_lock:
                            if result['checked_in']:
                                classroom_checked_in.add(
                                    (event['class_name'], result['student_key']))
                        logger.info('[Classroom] 学生信息已更新 class=%s ip=%s '
                                    'student_key=%s check_in=%s', event['class_name'],
                                    event['ip'], result['student_key'],
                                    result['checked_in'])
                _classroom_notify(event)
            except Exception as error:
                event['error'] = error
                logger.error('[Classroom] 数据操作失败 kind=%s class=%s ip=%s '
                             'student_key=%s error=%s', event['kind'],
                             event.get('class_name'), event.get('ip'),
                             event.get('student_key'), error, exc_info=True)
                _classroom_notify(event)
        finally:
            classroom_write_queue.task_done()


def _start_classroom_writer():
    global classroom_write_thread
    with classroom_lock:
        if classroom_write_thread is None or not classroom_write_thread.is_alive():
            classroom_write_thread = threading.Thread(
                target=_classroom_writer, name='classroom-writer', daemon=True)
            classroom_write_thread.start()


def _queue_classroom_write(action, event):
    if classroom_shutdown:
        logger.error('[Classroom] 程序正在退出，拒绝新数据操作 kind=%s', event['kind'])
        return False
    _start_classroom_writer()
    classroom_write_queue.put((action, event))
    return True


def set_active_class(class_name):
    classroom_store.set_active_class(class_name)
    global classroom_active_class
    with classroom_lock:
        classroom_active_class = class_name
    logger.info('[Classroom] 当前班级已切换 class=%s', class_name)
    return class_name


def handle_classroom_student_info(sip, info):
    with classroom_lock:
        if classroom_shutdown:
            return False
        class_name = classroom_active_class
        if not class_name:
            return False
        event = {'kind': 'student_info', 'class_name': class_name, 'ip': sip,
                 'student_key': None}
        name = info.get('name', '')
        user = info.get('user', '')
        action = lambda: classroom_store.report_student_online(
            class_name, sip, name, user)
        return _queue_classroom_write(action, event)


def import_online_students():
    """返回需要 GUI 导入的在线学生；不会由网络 handler 自动建档。"""
    result = []
    for sip, student in list(students.items()):
        info = student.get('info', {})
        result.append({'ip': sip, 'computer_name': info.get('name', ''),
                       'user_name': info.get('user', '')})
    return result


def hexdump(data, width=16):
    if data is None:
        return '<None>'
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i+width]
        hex_part = ' '.join(f'{b:02x}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f'{i:04x}  {hex_part:<{width*3}} {ascii_part}')
    return '\n'.join(lines)


def magic_name(mag):
    return MAGIC_NAMES.get(mag, f'UNKNOWN(0x{mag:08X})')


def is_interesting(d, sip):
    """判断是否值得记录的数据包：非本机、非日常广播、或未知类型。"""
    if sip == ip:
        return False
    if len(d) < 4:
        return True
    mag = struct.unpack('<I', d[:4])[0]
    return mag not in ROUTINE_MAGICS


def _prefix_from_netmask(mask):
    try:
        values = [int(part) for part in mask.split('.')]
    except (AttributeError, ValueError):
        return None
    if len(values) != 4 or any(not 0 <= value <= 255 for value in values):
        return None
    bits = ''.join(f'{value:08b}' for value in values)
    if '01' in bits:
        return None
    return bits.count('1')


BENCHMARK_NETWORK = ipaddress.ip_network('198.18.0.0/15')
IPV4_PATTERN = re.compile(r'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)')


def _usable_ipv4(value):
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (addr.version == 4
            and not addr.is_loopback
            and not addr.is_link_local
            and not addr.is_multicast
            and not addr.is_unspecified
            and addr not in BENCHMARK_NETWORK)


def _decode_console(raw):
    for encoding in ('mbcs', 'utf-8', 'gbk'):
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode('ascii', 'replace')


def _ipconfig_candidates():
    """解析 ipconfig 枚举 (网卡名, 地址, 前缀, 是否有默认网关)。

    PowerShell 首次调用 NetworkInterface 在本机需要数秒，而 ipconfig 是原生
    命令，通常百毫秒级，因此优先使用它。
    """
    try:
        completed = subprocess.run(
            ['ipconfig'],
            capture_output=True,
            timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning('ipconfig 枚举网卡失败：%s', e)
        return []
    text = _decode_console(completed.stdout or b'')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    candidates = []
    alias = ''
    pending_alias = None
    for block in re.split(r'\n[ \t]*\n', text):
        lines = [line for line in block.split('\n') if line.strip()]
        if not lines:
            continue
        # 中文 ipconfig 会在适配器标题与属性之间插一个空行，标题因此单独
        # 成为一个块，需要留给下一个块使用；属性块的首行是“连接特定的
        # DNS 后缀”，不能再当成标题。
        if len(lines) == 1 and ':' in lines[0] and not IPV4_PATTERN.search(lines[0]):
            pending_alias = lines[0].rsplit(':', 1)[0].strip()
            continue
        if (pending_alias is None and len(lines) > 1
                and ':' in lines[0] and not IPV4_PATTERN.search(lines[0])):
            alias = lines[0].rsplit(':', 1)[0].strip()
            lines = lines[1:]
        elif pending_alias is not None:
            alias = pending_alias
        pending_alias = None
        address = None
        prefix = None
        gateway = False
        for line in lines:
            if ':' not in line:
                continue
            for token in IPV4_PATTERN.findall(line.rsplit(':', 1)[-1]):
                token_prefix = _prefix_from_netmask(token)
                if token_prefix is not None and address is not None and prefix is None:
                    prefix = token_prefix
                elif prefix is not None:
                    gateway = True
                else:
                    if address is not None:
                        candidates.append((alias, address, prefix, gateway))
                        gateway = False
                    address, prefix = token, None
        if address is not None:
            candidates.append((alias, address, prefix, gateway))
    return candidates


def _powershell_candidates():
    ps_script = (
        "$ErrorActionPreference='Stop'; "
        "foreach($nic in [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) { "
        "if($nic.OperationalStatus -ne [System.Net.NetworkInformation.OperationalStatus]::Up) { continue }; "
        "$props=$nic.GetIPProperties(); $gateway=$false; "
        "foreach($gw in $props.GatewayAddresses) { "
        "if($gw.Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) { "
        "$gateway=$true; break } }; "
        "foreach($addr in $props.UnicastAddresses) { "
        "if($addr.Address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { continue }; "
        "\"{0}`t{1}`t{2}`t{3}\" -f "
        "$addr.Address.IPAddressToString,$nic.Name,$gateway,$addr.PrefixLength } }"
    )
    try:
        completed = subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps_script],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning('枚举 Windows 网卡失败：%s', e)
        return []
    candidates = []
    for line in (completed.stdout or '').splitlines():
        parts = line.strip().split('\t')
        if len(parts) != 4:
            continue
        address, alias, has_gateway, prefix_text = parts
        try:
            prefix = int(prefix_text)
        except ValueError:
            continue
        candidates.append((alias, address, prefix, has_gateway.lower() == 'true'))
    return candidates


def _choose_ipv4_candidate(candidates, peer_address, wanted_network):
    """按默认网关、私有网段、学生端同网段的优先级挑选本机地址。"""
    scored = []
    for order, (alias, address_text, prefix, gateway) in enumerate(candidates):
        if not _usable_ipv4(address_text):
            continue
        address = ipaddress.ip_address(address_text)
        if wanted_network and address not in wanted_network:
            continue
        network = None
        if prefix is not None:
            try:
                network = ipaddress.ip_network(
                    f'{address_text}/{prefix}', strict=False)
            except ValueError:
                network = None
        score = 100 if gateway else 0
        score += 20 if address.is_private else 0
        # 同分时优先/24 及更大的常规局域网，避免选中 VPN/TUN 的 /30 地址。
        score += 5 if network is not None and network.prefixlen <= 24 else 0
        if peer_address is not None and network is not None and peer_address in network:
            score += 1000
        scored.append((score, order, address_text, alias, network, gateway))
    if not scored:
        return None
    return max(scored, key=lambda item: (item[0], -item[1]))


def get_ip():
    global _network_selection_cache
    key = tuple(os.environ.get(name, '') for name in (
        'TEACHER_IP', 'TEACHER_PEER_IP', 'TEACHER_NETWORK'))
    if _network_selection_cache and _network_selection_cache[2] == key:
        return _network_selection_cache[0]
    selected = _get_ip_uncached()
    _network_selection_cache = (selected, SELECTED_NETWORK, key)
    return selected


def _get_ip_uncached():
    global SELECTED_NETWORK
    SELECTED_NETWORK = None
    override = os.environ.get('TEACHER_IP', '').strip()
    peer_hint = os.environ.get('TEACHER_PEER_IP', '').strip()
    network_hint = os.environ.get('TEACHER_NETWORK', '').strip()

    peer_address = None
    if peer_hint:
        try:
            peer_address = ipaddress.ip_address(peer_hint)
            if (peer_address.version != 4 or peer_address.is_unspecified
                    or peer_address.is_multicast):
                raise ValueError('必须是普通 IPv4 地址')
        except Exception as e:
            raise ValueError(f'TEACHER_PEER_IP 不是有效 IPv4 地址：{peer_hint}（{e}）') from e

    wanted_network = None
    if network_hint:
        try:
            wanted_network = ipaddress.ip_network(network_hint, strict=False)
            if wanted_network.version != 4:
                raise ValueError('必须是 IPv4 网段')
        except ValueError as e:
            raise ValueError(f'TEACHER_NETWORK 不是有效 IPv4 网段：{network_hint}') from e

    if override:
        if not _usable_ipv4(override):
            raise ValueError(f'TEACHER_IP 不是可用的 IPv4 地址：{override}')
        override_address = ipaddress.ip_address(override)
        if wanted_network and override_address not in wanted_network:
            raise ValueError(
                f'TEACHER_IP={override} 不属于 TEACHER_NETWORK={wanted_network}'
            )
        SELECTED_NETWORK = wanted_network
        logger.info('使用 TEACHER_IP 指定地址：%s', override)
        return override

    # 官方逻辑枚举所有本机 IPv4，并不会按网卡名称排除虚拟接口。这里同样
    # 保留全部可用地址；可通过 TEACHER_NETWORK 选择所需网段。
    candidates = []
    if os.name == 'nt':
        candidates = _ipconfig_candidates()
        if not candidates:
            logger.info('ipconfig 未枚举到地址，回退 PowerShell 枚举')
            candidates = _powershell_candidates()
    chosen = _choose_ipv4_candidate(candidates, peer_address, wanted_network)
    if chosen is not None:
        _, _, selected, alias, selected_network, _ = chosen
        logger.info('可用 IPv4 候选：%s', '; '.join(
            f'{address}/{prefix if prefix is not None else "?"}'
            f'（{name}，默认网关={has_gateway}）'
            for name, address, prefix, has_gateway in candidates
            if _usable_ipv4(address)))
        SELECTED_NETWORK = selected_network
        if peer_address and selected_network and peer_address in selected_network:
            logger.info('按 TEACHER_PEER_IP=%s 的直连网段选择地址：%s（%s，网段=%s）',
                        peer_hint, selected, alias, selected_network)
        else:
            logger.info('自动选择局域网地址：%s（%s，网段=%s）',
                        selected, alias, selected_network)
            if peer_address:
                logger.warning(
                    'TEACHER_PEER_IP=%s 不在所选直连网段 %s；组播发现通常不会跨越路由器',
                    peer_hint, selected_network)
        return selected
    if wanted_network and candidates:
        raise RuntimeError(f'没有找到属于 TEACHER_NETWORK={wanted_network} 的本机地址')

    # UDP connect 只查询本机路由，不会真正向目标发送数据。优先探测
    # 指定同端，其次探测本程序使用的组播路由；外网地址只作最后尝试。
    # 这样在只有局域网、没有默认网关时也能正常启动。
    route_targets = []
    if peer_hint:
        route_targets.append((peer_hint, PORT, 'TEACHER_PEER_IP'))
    route_targets.extend([
        (MCAST, PORT, '组播'),
        ('8.8.8.8', 80, '默认路由'),
    ])
    route_errors = []
    for route_target, route_port, route_name in route_targets:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((route_target, route_port))
            selected = s.getsockname()[0]
            if not _usable_ipv4(selected):
                raise RuntimeError(f'得到不可用地址 {selected}')
            if wanted_network and ipaddress.ip_address(selected) not in wanted_network:
                raise RuntimeError(
                    f'地址 {selected} 不属于 TEACHER_NETWORK={wanted_network}'
                )
            SELECTED_NETWORK = wanted_network
            logger.info('通过%s路由选择地址：%s', route_name, selected)
            return selected
        except OSError as e:
            route_errors.append(f'{route_name} {route_target}: {e}')
            logger.warning('%s路由探测失败：%s', route_name, e)
        except RuntimeError as e:
            route_errors.append(f'{route_name} {route_target}: {e}')
            logger.warning('%s路由探测忽略：%s', route_name, e)
        finally:
            s.close()

    # 极端情况下 Windows 网卡枚举和路由查询都可能失败，再从
    # 主机名解析结果中选一个可用局域网地址。
    hostname_candidates = []
    try:
        for info in socket.getaddrinfo(
                socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM):
            candidate = info[4][0]
            if candidate not in hostname_candidates and _usable_ipv4(candidate):
                hostname_candidates.append(candidate)
    except OSError as e:
        logger.warning('主机名 IPv4 解析失败：%s', e)

    if wanted_network:
        hostname_candidates = [
            candidate for candidate in hostname_candidates
            if ipaddress.ip_address(candidate) in wanted_network
        ]
    if hostname_candidates:
        selected = hostname_candidates[0]
        SELECTED_NETWORK = wanted_network
        logger.info('通过主机名解析选择局域网地址：%s（候选=%s）',
                    selected, ', '.join(hostname_candidates))
        return selected

    detail = '; '.join(route_errors) or '未找到可用 IPv4 地址'
    raise RuntimeError(
        f'无法自动选择本机局域网 IP（{detail}）。'
        '请设置 TEACHER_IP，例如：'
        'set TEACHER_IP=192.168.52.132'
    )


def _initial_network_selection():
    global ip, SELECTED_NETWORK
    try:
        ip = get_ip()
    except Exception as error:
        ip = os.environ.get('TEACHER_IP', '').strip() or '0.0.0.0'
        try:
            SELECTED_NETWORK = ipaddress.ip_network(
                os.environ.get('TEACHER_NETWORK', '').strip(), strict=False)
        except ValueError:
            SELECTED_NETWORK = None
        logger.warning('导入期网络选择失败，将在 start_network() 重试：%s', error)


_initial_network_selection()


def get_channel_id():
    from app_config import load_channel
    raw = os.environ.get('TEACHER_CHANNEL', str(load_channel())).strip()
    try:
        channel = int(raw, 0)
    except ValueError as e:
        raise ValueError(f'TEACHER_CHANNEL 不是有效整数：{raw}') from e
    if not 1 <= channel <= 32:
        raise ValueError('TEACHER_CHANNEL 必须在 1 到 32 之间')
    return channel


CHANNEL_ID = get_channel_id()
SINGLE_INSTANCE_MUTEX_NAME = (
    os.environ.get('TEACHER_MUTEX_NAME')
    or f'Local\\JiYuTeacher-Network-{CHANNEL_ID}')
SUBMISSION_PORT = app_config.load_submission_port()
logger.info('文件接收配置：port=%d directory=%s（0 表示仅审批，不监听）',
            SUBMISSION_PORT, SUBMISSION_DIR)


def get_env_int(name, default, minimum=0, maximum=0xFFFF):
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw, 0)
    except ValueError as e:
        raise ValueError(f'{name} 不是有效整数：{raw}') from e
    if not minimum <= value <= maximum:
        raise ValueError(f'{name} 必须在 {minimum} 到 {maximum} 之间')
    return value


def get_env_float(name, default, minimum=0.01, maximum=3600.0):
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as e:
        raise ValueError(f'{name} 不是有效浮点数：{raw}') from e
    if not minimum <= value <= maximum:
        raise ValueError(f'{name} 必须在 {minimum} 到 {maximum} 之间')
    return value


# V6 的连续桌面观看走 TCP/UMSP；4806 是原版默认通信端口。
TCP_COMM_MODE = get_env_int('TEACHER_TCP_MODE', 1, 0, 1)
TCP_COMM_PORT = get_env_int('TEACHER_TCP_PORT', 4806, 1, 0xFFFF)
# 远控接收端口位于学生机上。0 表示每次从动态端口段随机选择，避免和
# 学生端自身服务或上一次异常退出残留的接收线程争用固定端口。
CONTROL_PORT = get_env_int('TEACHER_CONTROL_PORT', 0, 0, 0xFFFF)
# 官方协议：0=Share（双方可操作），1=Monitor，2=Control Student（额外锁定学生输入）。
# 官方 control 分支会先初始化输入 Hook；默认使用 mode=2，确保键盘模拟路径已初始化。
# 如需保留学生端本地输入，可显式设置 TEACHER_CONTROL_MODE=0。
CONTROL_MODE = get_env_int('TEACHER_CONTROL_MODE', 2, 0, 2)
REMOTE_CONTROL_ENABLED = os.environ.get('TEACHER_ENABLE_REMOTE_CONTROL', '1').strip() != '0'
VIEW_START_DELAY = get_env_int('TEACHER_VIEW_START_DELAY_MS', 0, 0, 10000) / 1000.0
VIEW_FAILURE_COOLDOWN = get_env_int('TEACHER_VIEW_COOLDOWN', 60, 5, 3600)
REMOTE_VIEW_DIR = os.path.join(LOG_DIR, 'teacher_remote_view')
SOCKET_TIMEOUT = get_env_float('TEACHER_SOCKET_TIMEOUT', 0.5, 0.01, 30.0)
THREAD_JOIN_TIMEOUT = get_env_float('TEACHER_THREAD_JOIN_TIMEOUT', 2.0, 0.05, 30.0)
CLASSROOM_JOIN_TIMEOUT = get_env_float('TEACHER_CLASSROOM_JOIN_TIMEOUT', 1.0, 0.05, 30.0)
REMOTE_VIEW_JOIN_TIMEOUT = get_env_float('TEACHER_REMOTE_VIEW_JOIN_TIMEOUT', 1.0, 0.05, 30.0)
REMOTE_VIEW_IDLE_TIMEOUT = get_env_float('TEACHER_VIEW_IDLE_TIMEOUT', 30.0, 0.05, 3600.0)
ANNOUNCE_INFO_CYCLES = get_env_int('TEACHER_ANNOUNCE_INFO_CYCLES', 10, 1, 10000)
PREVIEW_POLICY_BASE = 3
PREVIEW_FRAME_TTL = get_env_float('TEACHER_PREVIEW_TTL', 10.0, 0.05, 3600.0)
PREVIEW_MAX_MISSING_PARTS = 512
ERROR_ALREADY_EXISTS = 183


def get_session_endpoint(channel):
    """按教师端公式计算频道对应的会话组播地址和 UDP 端口。"""
    return (f'{SESSION_MCAST_PREFIX}.{channel + 1}.1',
            SESSION_BASE_PORT + channel * SESSION_PORT_STRIDE)


SMCAST, SPORT = get_session_endpoint(CHANNEL_ID)
VIEW_LOCAL_PORT = get_env_int('TEACHER_VIEW_LOCAL_PORT', SPORT, 1, 0xFFFF)
VIEW_PEER_PORT = get_env_int('TEACHER_VIEW_PEER_PORT', SPORT, 1, 0xFFFF)
DIRECT_PEER_IP = os.environ.get('TEACHER_PEER_IP', '').strip() or None

def build_announce_targets(group, port):
    """同时生成组播、本网段广播和可选定向发现目标。"""
    targets = []

    def add(host):
        host_text = str(host)
        target = (host_text, port)
        if host_text != ip and target not in targets:
            targets.append(target)

    add(group)

    # VMware NAT 和仅主机网络都是独立二层网段。组播被虚拟交换
    # 机过滤时，子网广播仍能到达同一 VMnet 的宿主机或其他虚拟机。
    if (SELECTED_NETWORK is not None
            and ip is not None
            and SELECTED_NETWORK.prefixlen <= 30
            and ipaddress.ip_address(ip).is_private):
        add(SELECTED_NETWORK.broadcast_address)

        # VMware 默认把 VMnet 宿主虚拟网卡放在网段第一个可用
        # 地址。单播补发可覆盖宿主端防火墙放行单播但限制组播/广播的情况。
        host_candidate = SELECTED_NETWORK.network_address + 1
        add(host_candidate)

    if DIRECT_PEER_IP:
        add(DIRECT_PEER_IP)
    return targets


MAIN_ANNOUNCE_TARGETS = build_announce_targets(MCAST, PORT)
SESSION_ANNOUNCE_TARGETS = build_announce_targets(SMCAST, SPORT)

def _load_session_state():
    try:
        with open(SESSION_STATE_PATH, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        return (max(0, int(data.get('generation', 0))),
                max(0, int(data.get('oonc_seq', 0))))
    except (OSError, ValueError, TypeError, AttributeError) as error:
        logger.debug('[Session] 读取跨重启状态失败 path=%s error=%s',
                     SESSION_STATE_PATH, error)
        return 0, 0


def _write_session_state_locked():
    data = {
        'generation': generation,
        'oonc_seq': oonc_seq,
        'session_id': session_id,
        'pid': os.getpid(),
        'updated_at': time.time(),
    }
    directory = os.path.dirname(SESSION_STATE_PATH)
    temporary = f'{SESSION_STATE_PATH}.{os.getpid()}.tmp'
    try:
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(temporary, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(data, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, SESSION_STATE_PATH)
        return True
    except OSError as error:
        try:
            os.remove(temporary)
        except OSError:
            pass
        # 状态文件只是跨重启顺延用；写失败不能阻断启动或退出。
        logger.warning('[Session] 保存跨重启状态失败 path=%s error=%s',
                       SESSION_STATE_PATH, error)
        return False


def _save_session_state():
    with session_state_lock:
        return _write_session_state_locked()


def _acquire_single_instance_mutex():
    if os.name != 'nt':
        return None, True
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                         wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX_NAME)
        if not handle:
            logger.error('[Network] 创建单实例 Mutex 失败 error=%s',
                         ctypes.get_last_error())
            return None, False
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            logger.error('[Network] 已有教师端实例持有 Mutex=%s，拒绝重复绑定端口',
                         SINGLE_INSTANCE_MUTEX_NAME)
            return None, False
        return (kernel32, handle), True
    except Exception as error:
        logger.error('[Network] 单实例 Mutex 初始化失败：%s', error, exc_info=True)
        return None, False


def _release_single_instance_mutex():
    global single_instance_mutex, single_instance_locked
    with network_lock:
        handle_info = single_instance_mutex
        single_instance_mutex = None
        single_instance_locked = False
    if handle_info is None:
        return
    kernel32, handle = handle_info
    try:
        kernel32.CloseHandle(handle)
        logger.info('[Network] 单实例 Mutex 已释放 name=%s',
                    SINGLE_INSTANCE_MUTEX_NAME)
    except Exception as error:
        logger.warning('[Network] 释放单实例 Mutex 失败：%s', error)


def _create_network_socket(group, port, bind_ip):
    network_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    exclusive = getattr(socket, 'SO_EXCLUSIVEADDRUSE', None)
    exclusive_applied = False
    if os.name == 'nt' and exclusive is not None:
        network_socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        exclusive_applied = True
    else:
        network_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    network_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    network_socket.bind((bind_ip, port))
    network_socket.setsockopt(
        socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
        struct.pack('4s4s', socket.inet_aton(group), socket.inet_aton(bind_ip)))
    network_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                              socket.inet_aton(bind_ip))
    network_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)
    network_socket.settimeout(SOCKET_TIMEOUT)
    logger.info('[Network] socket 就绪 bind=%s:%d group=%s:%d timeout=%.2fs exclusive=%s',
                bind_ip, port, group, port, SOCKET_TIMEOUT, exclusive_applied)
    return network_socket, exclusive_applied


def _close_network_sockets():
    global sock, sock2, network_sockets_closed, network_started
    with network_lock:
        sockets = (sock, sock2)
        network_sockets_closed = True
        network_started = False
        sock = None
        sock2 = None
    for network_socket in sockets:
        if network_socket is None:
            continue
        try:
            network_socket.close()
        except OSError as error:
            logger.debug('[Network] socket close 忽略：%s', error)
    logger.info('[Network] socket 已关闭 main=%s session=%s',
                sockets[0] is not None, sockets[1] is not None)


def _send_packet(out_sock, packet, target, label, allow_when_stopped=False):
    with network_lock:
        current_socket = out_sock
        closed = network_sockets_closed
        started = network_started
        stopped = network_stop_event.is_set()
    if closed or not started or current_socket is None:
        logger.warning('[Network] socket 不可用，拒绝发送 label=%s target=%s closed=%s started=%s',
                       label, target, closed, started)
        return False
    if stopped and not allow_when_stopped:
        logger.debug('[Network] 已停止，跳过发送 label=%s target=%s', label, target)
        return False
    try:
        current_socket.sendto(packet, target)
        return True
    except OSError as error:
        logger.error('[Network] 发送失败 label=%s target=%s error=%s',
                     label, target, error)
        return False


def _send_main(packet, target, label, allow_when_stopped=False):
    return _send_packet(sock, packet, target, label, allow_when_stopped)


def _send_session(packet, target, label, allow_when_stopped=False):
    return _send_packet(sock2, packet, target, label, allow_when_stopped)


def get_network_status():
    with network_lock:
        status = {
            'running': running,
            'network_started': network_started,
            'network_sockets_closed': network_sockets_closed,
            'network_stopped': network_stop_event.is_set(),
            'ip': ip,
            'bind_ip': ip,
            'channel_id': CHANNEL_ID,
            'main_multicast': f'{MCAST}:{PORT}',
            'session_multicast': f'{SMCAST}:{SPORT}',
            'main_targets': list(MAIN_ANNOUNCE_TARGETS),
            'session_targets': list(SESSION_ANNOUNCE_TARGETS),
            'selected_network': str(SELECTED_NETWORK) if SELECTED_NETWORK else None,
            'session_id': session_id,
            'pid': os.getpid(),
            'generation': generation,
            'oonc_seq': oonc_seq,
            'single_instance_mutex': single_instance_locked,
            'mutex_name': SINGLE_INSTANCE_MUTEX_NAME,
            'exclusive_addruse': exclusive_addruse,
            'socket_timeout': SOCKET_TIMEOUT,
            'thread_join_timeout': THREAD_JOIN_TIMEOUT,
            'announce_info_cycles': ANNOUNCE_INFO_CYCLES,
            'shutdown_stage': shutdown_stage,
            'session_state_path': SESSION_STATE_PATH,
            'error': network_error,
        }
    with thread_lock:
        status['threads'] = {
            name: bool(thread.is_alive())
            for name, thread in background_threads.items()
        }
    status['threads_alive'] = sorted(
        name for name, alive in status['threads'].items() if alive)
    return status


def start_network():
    """显式创建/绑定两个 UDP socket；重复调用不会重复绑定。返回 bool。"""
    global ip, SELECTED_NETWORK, sock, sock2, network_started
    global network_sockets_closed, network_error, single_instance_mutex
    global single_instance_locked, exclusive_addruse, session_id
    global generation, oonc_seq, shutdown_stage
    with network_lock:
        if (network_started and not network_sockets_closed
                and sock is not None and sock2 is not None):
            logger.debug('[Network] 已启动，幂等返回 session_id=%s', session_id)
            return True
        if network_started:
            _close_network_sockets()
        # 允许 shutdown 后在同一进程内重启（GUI 重开/测试复用）。
        shutdown_stage = None
        mutex_info, mutex_ok = _acquire_single_instance_mutex()
        if not mutex_ok:
            network_error = '单实例 Mutex 已被占用或创建失败'
            return False
        single_instance_mutex = mutex_info
        single_instance_locked = True
        try:
            ip = get_ip()
        except Exception as error:
            network_error = f'选择网络失败：{error}'
            _release_single_instance_mutex()
            logger.error('[Network] 选择网络失败：%s', error, exc_info=True)
            return False
        MAIN_ANNOUNCE_TARGETS[:] = build_announce_targets(MCAST, PORT)
        SESSION_ANNOUNCE_TARGETS[:] = build_announce_targets(SMCAST, SPORT)
        previous_generation, previous_oonc_seq = _load_session_state()
        with session_state_lock:
            generation = previous_generation + 1
            oonc_seq = max(previous_oonc_seq, oonc_seq) + 1
            session_id = f'{time.time_ns()}-{os.getpid()}-{uuid.uuid4().hex[:8]}'
            _write_session_state_locked()
        network_stop_event.clear()
        network_error = None
        try:
            main_socket, exclusive_applied = _create_network_socket(MCAST, PORT, ip)
            session_socket, _ = _create_network_socket(SMCAST, SPORT, ip)
        except Exception as error:
            try:
                if 'main_socket' in locals():
                    main_socket.close()
            except OSError:
                pass
            _close_network_sockets()
            _release_single_instance_mutex()
            network_error = f'socket 初始化失败：{error}'
            logger.error('[Network] socket 初始化失败：%s', error, exc_info=True)
            return False
        sock, sock2 = main_socket, session_socket
        exclusive_addruse = exclusive_applied
        network_sockets_closed = False
        network_started = True
        _save_session_state()
        logger.info('[Network] session_id=%s pid=%d generation=%d oonc_seq=%d '
                    'ip=%s channel=%d mutex=%s exclusive=%s',
                    session_id, os.getpid(), generation, oonc_seq, ip, CHANNEL_ID,
                    SINGLE_INSTANCE_MUTEX_NAME, exclusive_addruse)
        logger.info('Teacher %s channel=%d started on %s:%d + %s:%d',
                    ip, CHANNEL_ID, MCAST, PORT, SMCAST, SPORT)
        logger.info('发现宣告已启用：NANC（普通频道）+ CANC（自动连接）')
        logger.info('主发现目标：%s', ', '.join(
            f'{host}:{port}' for host, port in MAIN_ANNOUNCE_TARGETS))
        logger.info('会话发现目标：%s', ', '.join(
            f'{host}:{port}' for host, port in SESSION_ANNOUNCE_TARGETS))
        if SELECTED_NETWORK is None:
            logger.warning('未获取到所选网卡的子网掩码，未启用自动子网广播；'
                           '可设置 TEACHER_NETWORK，例如 192.168.52.0/24')
        return True


def send_to_targets(out_sock, packet, targets, label, allow_when_stopped=False):
    """向一组宣告目标发送同一数据包；返回 (成功数, 失败数)，不抛瞬时错误。"""
    sent = 0
    failures = 0
    if network_stop_event.is_set() and not allow_when_stopped:
        return 0, 0
    for target in targets:
        if network_stop_event.is_set() and not allow_when_stopped:
            break
        if _send_packet(out_sock, packet, target, label, allow_when_stopped):
            sent += 1
        else:
            failures += 1
    if failures:
        logger.warning('[%s] 发包目标失败 sent=%d failed=%d', label, sent, failures)
    return sent, failures


def oonc():
    global oonc_seq
    with session_state_lock:
        oonc_seq += 1
        seq = oonc_seq
        if seq % ANNOUNCE_INFO_CYCLES == 0:
            _write_session_state_locked()
    pkt = (struct.pack('<II', 0x434E4F4F, 0x10000)
           + struct.pack('<I', 16)
           + TGUID.bytes_le
           + socket.inet_aton(ip)
           + struct.pack('<III', 1, 1, seq))
    return pkt


def get_teacher_name_field():
    name = os.environ.get('TEACHER_NAME', '1')[:31] or '1'
    nw = (name + '\x00').encode('utf-16-le')
    name_chars = len(nw) // 2 - 1
    return nw, name_chars


def nanc():
    """构造普通频道选择模式使用的教师宣告。"""
    nw, name_chars = get_teacher_name_field()
    af = (name_chars << 17) | CHANNEL_ID
    body = struct.pack('<I', af) + socket.inet_aton(ip) + nw
    declared_length = 11 + name_chars * 2
    body += b'\x00' * (declared_length - len(body))
    return (struct.pack('<III', 0x434E414E, 0x10000, len(body))
            + TGUID.bytes_le
            + body)


def canc():
    """构造自动连接模式使用的教师宣告。"""
    nw, name_chars = get_teacher_name_field()
    af = (name_chars << 17) | CHANNEL_ID
    channel_mask = 1 << (CHANNEL_ID - 1)
    body = (struct.pack('<I', af)
            + socket.inet_aton(ip)
            + struct.pack('<II', channel_mask, 1)
            + nw)
    if len(body) > 84:
        raise ValueError('TEACHER_NAME 编码后超过 CANC 负载上限')
    body += b'\x00' * (84 - len(body))
    return (struct.pack('<III', 0x434E4143, 0x10000, len(body))
            + TGUID.bytes_le
            + body)


def waca(sip):
    return (struct.pack('<III', 0x41434157, 0x10000, 8)
            + TGUID.bytes_le
            + socket.inet_aton(ip)
            + struct.pack('<I', CHANNEL_ID))


def request_preview(sip):
    """提交一次 LPNT 策略变更；不是立即截图命令，版本从统一状态单调递增。"""
    with state_lock:
        previews.pop(sip, None)
        completed_preview_frames.pop(sip, None)
        preview_last_errors.pop(sip, None)
    ok = _send_preview_policy(sip, True, 'PolicyChange', count=2)
    _ensure_preview_keepalive(sip)
    logger.info('[Preview] 策略变更 -> %s ok=%s version=%d；等待同版本 TRNT 与定时器出帧',
                sip, ok, preview_policy_versions.get(sip, PREVIEW_POLICY_BASE))
    return ok


def request_all_previews():
    """后台非阻塞地向当前快照内所有学生请求预览；返回是否成功调度。"""
    targets = [item['ip'] for item in get_students_snapshot()]
    if not targets:
        logger.info('[Preview] 全班请求跳过：当前无学生快照')
        return False
    if not network_started or network_sockets_closed:
        logger.warning('[Preview] 全班请求失败：网络尚未启动')
        return False
    if not running or network_stop_event.is_set():
        logger.warning('[Preview] 全班请求失败：后台线程未运行或正在退出')
        return False

    def worker():
        sent = 0
        for student_ip in targets:
            if not running or network_stop_event.is_set():
                break
            if request_preview(student_ip):
                sent += 1
            if _sleep_or_stop(0.05):
                break
        logger.info('[Preview] 全班请求完成 requested=%d sent=%d',
                    len(targets), sent)

    thread = _start_managed_thread('request-all-previews', worker)
    if thread is None:
        return False
    logger.info('[Preview] 全班请求已提交后台线程 targets=%d', len(targets))
    return True


def build_mess_packet(sip, payload):
    """构造单接收者 MESS；recipient IP 使用协议中的原始网络序字节。"""
    socket.inet_aton(sip)
    return (struct.pack('<III', 0x5353454D, 1, 1)
            + socket.inet_aton(sip)
            + payload)


def build_command_transaction(payload):
    """构造 CCommandTransaction 使用的 COMD 外层。"""
    if len(payload) > 0x800:
        raise ValueError('CCommandTransaction payload 不能超过 2048 字节')
    packet = (struct.pack('<III', 0x434F4D44, 0x10000,
                          len(payload) + 13)
              + uuid.uuid4().bytes_le
              + struct.pack('<I', 20000)
              + socket.inet_aton(ip)
              + struct.pack('<I', len(payload))
              + payload
              + b'\x00')
    if len(packet) != len(payload) + 41:
        raise AssertionError('COMD 命令事务长度错误')
    return packet


def build_remote_view_payload(sip):
    """构造远程观看 feature 8 的 617 字节内部负载。"""
    params = bytearray(604)
    struct.pack_into('<I', params, 0, 0)  # RemoteWithVoice
    params[4:8] = socket.inet_aton(ip)
    # 这里是教师会话/桌面监控端点，不是学生端的 TCP 服务端口 4806。
    struct.pack_into('<H', params, 8, VIEW_LOCAL_PORT)
    params[10:14] = socket.inet_aton(ip)
    struct.pack_into('<H', params, 14, VIEW_PEER_PORT)
    struct.pack_into('<IIIIIIII', params, 36,
                     1,      # NetworkType
                     1,      # ShowMonitorControlMessage
                     20480,  # MaxSendSpeed
                     1,      # RepairMode
                     1440,   # MaxPacketSize
                     25,     # FrameLimit
                     75,     # CaptureQuality
                     1)      # TcpCommMode
    params[68:72] = socket.inet_aton(sip)
    struct.pack_into('<III', params, 72, 5, 12, 16)
    payload = struct.pack('<III', 617, 8, 0x80000000) + params + b'\x00'
    if len(payload) != 617:
        raise AssertionError(f'feature 8 长度错误：{len(payload)}')
    return payload


def build_remote_view_stop_payload():
    return struct.pack('<III', 13, 0, 0) + b'\x00'


def send_remote_view_feature(sip, enabled=True):
    payload = (build_remote_view_payload(sip) if enabled
               else build_remote_view_stop_payload())
    packet = build_mess_packet(sip, payload)
    ok = _send_session(packet, (sip, SPORT),
                       f'RemoteView feature {"start" if enabled else "stop"}',
                       allow_when_stopped=True)
    logger.info('[RemoteView] feature %s -> %s:%d, payload=%d, mess=%d, ok=%s',
                'start' if enabled else 'stop', sip, SPORT,
                len(payload), len(packet), ok)
    return ok


def build_screen_broadcast_payload(sip):
    params = bytearray(build_remote_view_payload(sip)[12:-1])
    params[0:4] = b'\x00' * 4  # 第一版只广播视频，不启用学生音频回传。
    params[8:10] = b'\x00' * 2
    payload = struct.pack('<III', 617, 1, 0x80000000) + params + b'\x00'
    if len(payload) != 617:
        raise AssertionError('feature 1 广播参数长度错误')
    return payload


def start_screen_broadcast(sip):
    if not _check_student(sip, 'broadcast <学生IP>'):
        return False
    payload = build_screen_broadcast_payload(sip)
    ok = _send_session(build_mess_packet(sip, payload), (sip, SPORT),
                       'Broadcast feature 1 start')
    if ok:
        screen_broadcasts[sip] = {'started_at': time.time(), 'streaming': False}
    logger.info('[Broadcast] feature 1 启动包 -> %s ok=%s；等待媒体推流实现', sip, ok)
    return ok


def stop_screen_broadcast(sip):
    if not _check_student(sip, 'broadcast_stop <学生IP>'):
        return False
    packet = build_mess_packet(sip, struct.pack('<III', 13, 1, 0) + b'\x00')
    ok = _send_session(packet, (sip, SPORT), 'Broadcast feature 1 stop',
                       allow_when_stopped=True)
    if ok:
        screen_broadcasts.pop(sip, None)
    logger.info('[Broadcast] feature 1 停止包 -> %s ok=%s', sip, ok)
    return ok


def build_student_demo_payload(port):
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError('实验性语音监听端口必须在 1 到 65535 之间')
    payload = (struct.pack('<IIIIIII', 35, 1, 0, 7, 0, 4, 0)
               + socket.inet_aton(ip) + struct.pack('<H', port) + b'\x00')
    if len(payload) != 35:
        raise AssertionError('feature 4 学生演示最小控制包长度错误')
    return payload


def start_student_demo(source_ip, port=None):
    if not _check_student(source_ip, 'demo <演示学生IP>'):
        return False
    if port is None:
        raw_port = os.environ.get('TEACHER_DEMO_VOICE_PORT', '').strip()
        if not raw_port:
            raise ValueError('请提供实验性语音监听端口；屏幕演示尚未实现')
        try:
            port = int(raw_port, 0)
        except ValueError as error:
            raise ValueError('TEACHER_DEMO_VOICE_PORT 必须是有效端口') from error
    if student_demos:
        raise ValueError('已有学生演示进行中，请先停止')
    if source_ip in screen_broadcasts:
        raise ValueError('请先停止该学生的教师屏幕广播')
    payload = build_student_demo_payload(port)
    ok = _send_session(build_mess_packet(source_ip, payload),
                       (source_ip, SPORT), 'Demo feature 4 start')
    if ok:
        student_demos[source_ip] = {
            'recipients': [source_ip], 'monitoring': False,
            'port': port, 'started_at': time.time(), 'scope': 'voice-control'}
    logger.info('[Demo] feature 4 语音启动控制 -> %s port=%d ok=%s；屏幕分发与监看尚未实现',
                source_ip, port, ok)
    return ok


def stop_student_demo(source_ip=None):
    if source_ip is None:
        if len(student_demos) != 1:
            raise ValueError('请指定要停止的演示学生')
        source_ip = next(iter(student_demos))
    state = student_demos.get(source_ip)
    if state is None:
        raise ValueError('该学生没有进行中的演示')
    payload = struct.pack('<IIIIIII', 29, 1, 0, 0, 0, 4, 0x10000000) + b'\x00'
    failed = []
    for recipient in state['recipients']:
        if not _send_session(build_mess_packet(recipient, payload),
                             (recipient, SPORT), 'Demo feature 4 stop',
                             allow_when_stopped=True):
            failed.append(recipient)
    if failed:
        logger.error('[Demo] feature 4 停止包发送失败 recipients=%s', failed)
        return False
    student_demos.pop(source_ip, None)
    logger.info('[Demo] feature 4 语音停止控制已发送 source=%s recipients=%s',
                source_ip, state['recipients'])
    return True


# 抢答 / 随堂小考 / 快速测评的模块启停：StudentMain 在 MESS 内层 payload
# +0x14 取 feature、+0x18 取 flags（0x10000000=停止），见 temp/quiz-findings.md
# §4.1 的反汇编表。这里只发启停控制面：题目、评分、奖励的数据面未闭合，
# 不构造 DMCQ/KLBQ/AAPR 等命令包。
MODULE_FEATURE_RESPONSE = 0x80000
MODULE_FEATURE_QUIZ = 0x400000
MODULE_FEATURE_INSTANT = 0x4000000
MODULE_FEATURES = {
    'response': (MODULE_FEATURE_RESPONSE, '抢答竞赛'),
    'quiz': (MODULE_FEATURE_QUIZ, '随堂小考'),
    'instant': (MODULE_FEATURE_INSTANT, '快速测评'),
}
active_module_features = {}   # feature -> {'since': ts}


def build_module_feature_payload(feature, enabled):
    """构造模块启停的 MESS 内层 payload（结构性复用 feature 4 的布局）。"""
    if feature not in (MODULE_FEATURE_RESPONSE, MODULE_FEATURE_QUIZ,
                       MODULE_FEATURE_INSTANT):
        raise ValueError(f'不支持的模块 feature=0x{feature:X}')
    flags = 0 if enabled else 0x10000000
    payload = struct.pack('<IIIIIII', 29, 1, 0, 0, 0, feature, flags) + b'\x00'
    if len(payload) != 29:
        raise AssertionError('模块启停 payload 长度错误')
    return payload


def send_module_feature(module, enabled, recipients=None):
    """向学生单播模块启停包；module 取 response / quiz / instant。

    只发送已证实的 feature/停止位，不带任何题目或媒体参数。学生端是否
    创建客户端、以及后续交互均未实机验证。
    """
    if module not in MODULE_FEATURES:
        raise ValueError(f'未知模块：{module}')
    feature, name = MODULE_FEATURES[module]
    if recipients is None:
        recipients = list(students)
    elif isinstance(recipients, str):
        recipients = [recipients]
    recipients = [sip for sip in dict.fromkeys(recipients) if sip in students]
    if not recipients:
        logger.warning('[模块] %s %s：没有可发送的在线学生', name,
                       '启动' if enabled else '停止')
        return {'ok': False, 'reason': '没有可发送的在线学生',
                'sent': 0, 'failed': []}
    payload = build_module_feature_payload(feature, enabled)
    state_text = 'start' if enabled else 'stop'
    sent, failed = [], []
    for sip in recipients:
        label = f'{name} feature 0x{feature:X} {state_text}'
        if _send_session(build_mess_packet(sip, payload), (sip, SPORT), label,
                         allow_when_stopped=not enabled):
            sent.append(sip)
        else:
            failed.append(sip)
    if enabled and sent:
        active_module_features[feature] = {'since': time.time(),
                                           'recipients': sent}
    elif not enabled:
        active_module_features.pop(feature, None)
    logger.info('[模块] %s %s -> %d 台成功，%d 台失败%s',
                name, '启动' if enabled else '停止', len(sent), len(failed),
                f'，失败={failed}' if failed else '')
    return {'ok': bool(sent) and not failed, 'sent': len(sent),
            'failed': failed, 'feature': f'0x{feature:X}'}


# 行为限制：COMD 事件 0x80000010 / category=0x200 / command_id=0x17。
# 取值语义见 temp/policy-enums-findings.md：
#   U 盘/光驱 +0x14/+0x18 只有 0..3 已证实（Free/Readonly/NoExecute/Block），
#   打印 +0x1c 只有 0（不限制）与 2（全部禁止）已证实，1/3 学生端 no-op；
#   App +0x0c / Web +0x10 学生端不校验不解释，1/2/3 语义未知。
# 学生端收到后只做“比较→保存→广播→调策略函数”，没有任何结果回执。
BEHAVIOR_RESTRICTION_GUID = 'f96a6d195b2946b9ab958a143ecddc26'


def send_behavior_restrictions(recipients, app=0, web=0, usb=0, cd=0, printer=0):
    """下发行为限制（COMD 0x80000010 / category=0x200 / command_id=0x17）。

    内层 payload 32 字节，逐学生单播到主通道端口：
      +0x00 category=0x200  +0x04 flags=0  +0x08 command=0x17
      +0x0c App  +0x10 Web  +0x14 U 盘  +0x18 光驱  +0x1c 打印
    与关机包一致，外层 COMD 的 payload 末尾再补 4 字节 NUL。

    recipients 可以是单个 IP 字符串或 IP 列表；未登录的 IP 会被过滤掉。
    restrictions 模块采用惰性导入：文件缺失时本函数返回失败结果，而不是让
    整个进程在 import 阶段起不来。
    """
    try:
        import restrictions
    except Exception as error:  # pragma: no cover - 只在模块缺失/损坏时触发
        logger.error('[行为限制] restrictions 模块不可用，拒绝发送：%s', error)
        return {'ok': False, 'reason': f'restrictions 模块不可用：{error}',
                'sent': 0, 'failed': [], 'skipped': [], 'summary': '未发送'}
    payload = restrictions.build_restriction_payload(
        app=app, web=web, usb=usb, cd=cd, printer=printer)
    summary = restrictions.describe_restrictions({
        'app': app, 'web': web, 'usb': usb, 'cd': cd, 'printer': printer})
    if recipients is None:
        requested = list(students)
    elif isinstance(recipients, str):
        requested = [recipients]
    else:
        requested = list(recipients)
    requested = list(dict.fromkeys(requested))
    targets = [sip for sip in requested if sip in students]
    skipped = [sip for sip in requested if sip not in students]
    if skipped:
        logger.warning('[行为限制] 跳过未登录学生 %s', skipped)
    if not targets:
        logger.warning('[行为限制] 没有可发送的在线学生 policy=%s', summary)
        return {'ok': False, 'reason': '没有可发送的在线学生', 'sent': 0,
                'failed': [], 'skipped': skipped, 'summary': summary}
    pkt = build_comd_command_ex(0x80000010, payload + b'\x00' * 4,
                               BEHAVIOR_RESTRICTION_GUID)
    sent, failed = [], []
    for sip in targets:
        if _send_main(pkt, (sip, PORT), 'BehaviorRestriction COMD 0x17'):
            sent.append(sip)
        else:
            failed.append(sip)
    logger.info('[行为限制] %s -> %d 台成功，%d 台失败%s%s', summary,
                len(sent), len(failed),
                f'，失败={failed}' if failed else '',
                f'，跳过={skipped}' if skipped else '')
    return {'ok': bool(sent) and not failed, 'sent': len(sent),
            'failed': failed, 'skipped': skipped, 'summary': summary,
            'payload_size': len(payload)}


class RemoteViewSession:
    """V6 TCP/UMSP channel 10 接收器及 libTDDesk2 桌面帧重组器。"""

    UMSP_VERSION = 0x10000
    UMSP_SELECT_MAGIC = 0x4F434853  # wire: SHCO
    UMSP_DATA_MAGIC = 0x43504B54    # wire: TKPC (代码常量名 TCPK)
    DESK_CHANNEL = 10
    MAX_FRAME_SIZE = 0x241800

    def __init__(self, sip, port):
        self.sip = sip
        self.port = port
        self.base_name = sip.replace('.', '_')
        self.stop_event = threading.Event()
        self.connected_event = threading.Event()
        self.conn = None
        self.thread = None
        self.thread_name = f'view-{self.base_name}-{id(self):x}'
        self.fragments = {}
        self.frame_count = 0
        self.control_record_count = 0
        self.remote_cursor = None
        self.remote_cursor_version = 0
        self.local_cursor = None
        self.local_cursor_version = 0
        self.last_local_cursor_at = 0.0
        self.last_cursor_log = 0.0
        self.player = None
        self.player_format = None
        self.player_kind = None
        self.player_size = None
        self.viewer_thread = None
        self.player_unavailable = False
        self.interactive_requested = False
        self.dump_stream = os.environ.get('TEACHER_VIEW_DUMP', '0').strip() == '1'
        self.session_tag = time.strftime('%Y%m%d-%H%M%S')

    def start(self):
        self.thread = _start_managed_thread(self.thread_name, self.run)
        return self.thread is not None

    def stop(self):
        self.stop_event.set()
        conn = self.conn
        if conn is not None:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except (OSError, AttributeError):
                pass
            try:
                conn.close()
            except (OSError, AttributeError):
                pass
            self.conn = None
        self._stop_player()
        _join_thread(self.thread, REMOTE_VIEW_JOIN_TIMEOUT)
        _join_thread(self.viewer_thread, REMOTE_VIEW_JOIN_TIMEOUT)

    def enable_interactive_player(self):
        """立即退出纯播放窗口，下一帧改用带输入绑定的内嵌窗口。"""
        self.interactive_requested = True
        if self.player_kind in ('ffplay', 'opencv-h264'):
            self._stop_player()

    def _connect(self):
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(2.5)
        try:
            conn.bind((ip, 0))
            conn.connect((self.sip, self.port))
            hello = struct.pack('<IIIII', self.UMSP_VERSION,
                                self.UMSP_SELECT_MAGIC, 8, 1,
                                self.DESK_CHANNEL)
            conn.sendall(hello)
            conn.settimeout(1.0)
            self.conn = conn
            self.connected_event.set()
            with remote_state_lock:
                remote_view_failures.pop(self.sip, None)
                remote_view_last_error.pop(self.sip, None)
            logger.info('[RemoteView] TCP 已连接 %s:%d，SHCO channel=%d',
                        self.sip, self.port, self.DESK_CHANNEL)
            return conn
        except OSError as error:
            conn.close()
            with remote_state_lock:
                remote_view_failures[self.sip] = time.monotonic()
                remote_view_last_error[self.sip] = f'TCP 连接失败：{error}'
            raise

    def run(self):
        try:
            # 立即订阅 channel 10，避免错过编码器最初的 SPS/PPS/IDR。
            if self.stop_event.wait(VIEW_START_DELAY):
                return
            conn = self._connect()
            stream = bytearray()
            last_data_at = time.monotonic()
            while (running and not self.stop_event.is_set()
                   and not network_stop_event.is_set()):
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    if (time.monotonic() - last_data_at
                            > REMOTE_VIEW_IDLE_TIMEOUT):
                        raise TimeoutError(
                            f'{REMOTE_VIEW_IDLE_TIMEOUT:.2f}s 内未收到桌面数据')
                    if self.stop_event.is_set() or network_stop_event.is_set():
                        break
                    continue
                if not chunk:
                    raise ConnectionError('学生端关闭 TCP 连接')
                last_data_at = time.monotonic()
                stream.extend(chunk)
                while len(stream) >= 12:
                    version, magic, payload_len = struct.unpack_from('<III', stream)
                    if payload_len > self.MAX_FRAME_SIZE + 0x10000:
                        raise ValueError(f'UMSP payload 过大：{payload_len}')
                    packet_len = 12 + payload_len
                    if len(stream) < packet_len:
                        break
                    payload = bytes(stream[12:packet_len])
                    del stream[:packet_len]
                    if version != self.UMSP_VERSION:
                        logger.warning('[RemoteView] UMSP version=%#x（预期 %#x）',
                                       version, self.UMSP_VERSION)
                    if magic != self.UMSP_DATA_MAGIC:
                        logger.debug('[RemoteView] 忽略 UMSP magic=%#x len=%d',
                                     magic, payload_len)
                        continue
                    if len(payload) < 4:
                        logger.warning('[RemoteView] TCPK payload 过短：%d', len(payload))
                        continue
                    channel = struct.unpack_from('<I', payload)[0]
                    if channel == self.DESK_CHANNEL:
                        self._handle_fragment(payload[4:])
                    else:
                        logger.debug('[RemoteView] 忽略 channel=%d len=%d',
                                     channel, len(payload) - 4)
        except Exception as error:
            if not self.stop_event.is_set():
                reason = f'接收结束：{error}'
                _set_view_error(self.sip, reason)
                logger.error('[RemoteView] %s %s', self.sip, reason, exc_info=True)
                if not send_remote_view_feature(self.sip, False):
                    logger.warning('[RemoteView] %s 失败清理包未送达', self.sip)
        finally:
            self.stop()
            with remote_state_lock:
                if remote_views.get(self.sip) is self:
                    remote_views.pop(self.sip, None)
            logger.info('[RemoteView] %s 会话退出，共完成 %d 帧',
                        self.sip, self.frame_count)

    def _handle_fragment(self, data):
        if len(data) < 12:
            logger.warning('[RemoteView] 桌面分片过短：%d', len(data))
            return
        frame_seq, offset, total = struct.unpack_from('<III', data)
        fragment = data[12:]
        if not 1 <= total <= self.MAX_FRAME_SIZE:
            logger.warning('[RemoteView] 非法桌面帧大小：seq=%d total=%d',
                           frame_seq, total)
            return
        if offset > total or len(fragment) > total - offset:
            logger.warning('[RemoteView] 非法分片：seq=%d off=%d len=%d total=%d',
                           frame_seq, offset, len(fragment), total)
            return
        state = self.fragments.get(frame_seq)
        if state is None or state['total'] != total:
            state = {
                'total': total,
                'data': bytearray(total),
                'seen': bytearray(total),
                'received': 0,
            }
            self.fragments[frame_seq] = state
            if len(self.fragments) > 4:
                oldest = next(iter(self.fragments))
                if oldest != frame_seq:
                    self.fragments.pop(oldest, None)
        end = offset + len(fragment)
        new_bytes = len(fragment) - sum(state['seen'][offset:end])
        state['data'][offset:end] = fragment
        state['seen'][offset:end] = b'\x01' * len(fragment)
        state['received'] += new_bytes
        if state['received'] == total:
            record = bytes(state['data'])
            self.fragments.pop(frame_seq, None)
            self._handle_record(frame_seq, record)

    def _handle_record(self, frame_seq, record):
        if len(record) < 64:
            self.control_record_count += 1
            if len(record) >= 16 and record[:4] == b'SPUC':
                record_size, timestamp, packed_position = struct.unpack_from(
                    '<III', record, 4
                )
                cursor = (packed_position & 0xFFFF,
                          (packed_position >> 16) & 0xFFFF)
                if record_size == 16 and cursor != self.remote_cursor:
                    self.remote_cursor = cursor
                    self.remote_cursor_version += 1
                    with remote_state_lock:
                        control_active = self.sip in remote_controls
                    now = time.monotonic()
                    if control_active and now - self.last_cursor_log >= 0.1:
                        self.last_cursor_log = now
                        logger.info('[RemoteControl] 学生端光标 -> %s (%d,%d) ts=%d',
                                    self.sip, cursor[0], cursor[1], timestamp)
            if self.control_record_count == 1 or self.control_record_count % 100 == 0:
                logger.info('[RemoteView] 控制记录 count=%d seq=%d len=%d data=%s',
                            self.control_record_count, frame_seq, len(record),
                            record.hex(' '))
            return
        magic, declared_size, timestamp = struct.unpack_from('<III', record)
        encoded_rect = struct.unpack_from('<iiii', record, 12)
        visible_rect = struct.unpack_from('<iiii', record, 28)
        frame_type = struct.unpack_from('<I', record, 44)[0]
        payload = record[64:]
        width = abs(encoded_rect[2] - encoded_rect[0])
        height = abs(encoded_rect[3] - encoded_rect[1])
        visible_width = abs(visible_rect[2] - visible_rect[0])
        visible_height = abs(visible_rect[3] - visible_rect[1])
        if not width or not height:
            width = visible_width
            height = visible_height
        if not 0 < visible_width <= width:
            visible_width = width
        if not 0 < visible_height <= height:
            visible_height = height
        self.frame_count += 1
        os.makedirs(REMOTE_VIEW_DIR, exist_ok=True)

        if magic == 0x46524848:  # wire HHRF, H.264 Annex-B
            self._write_player('h264', payload, width, height,
                               visible_width, visible_height)
            if self.dump_stream or self.player_unavailable:
                path = os.path.join(REMOTE_VIEW_DIR,
                                    f'remote_{self.base_name}_{self.session_tag}.h264')
                with open(path, 'ab') as f:
                    f.write(payload)
            codec = 'H264'
        elif magic == 0x46524A48:  # wire HJRF, JPEG
            soi = payload.find(b'\xff\xd8')
            jpeg = payload[soi:] if soi >= 0 else payload
            path = os.path.join(REMOTE_VIEW_DIR,
                                f'remote_{self.base_name}_latest.jpg')
            with open(path, 'wb') as f:
                f.write(jpeg)
            self._write_player('mjpeg', jpeg, width, height,
                               visible_width, visible_height)
            codec = 'JPEG'
        elif magic == 0x46524D48:  # wire HMRF, legacy
            path = os.path.join(REMOTE_VIEW_DIR,
                                f'remote_{self.base_name}_latest.hmrf')
            with open(path, 'wb') as f:
                f.write(record)
            codec = 'HMRF'
        else:
            logger.warning('[RemoteView] 未知桌面记录 magic=%#x seq=%d len=%d',
                           magic, frame_seq, len(record))
            return

        if self.frame_count == 1 or self.frame_count % 100 == 0:
            logger.info('[RemoteView] %s %s frame=%d seq=%d type=%d '
                        'record=%d declared=%d ts=%d encoded=%s visible=%s',
                        self.sip, codec, self.frame_count, frame_seq, frame_type,
                        len(record), declared_size, timestamp,
                        encoded_rect, visible_rect)

    def _write_player(self, fmt, data, width, height,
                      visible_width=None, visible_height=None):
        if not data or self.player_unavailable:
            return
        output_width = visible_width or width
        output_height = visible_height or height
        wanted_size = (output_width, output_height)
        video_filter = ('shuffleplanes=0:2:1:3,'
                        f'crop={output_width}:{output_height}:0:0')
        if (self.player is None or self.player_format != fmt
                or (self.player_kind == 'opencv-h264'
                    and self.player_size != wanted_size)
                or (self.player_kind == 'pillow-h264'
                    and self.player_size != wanted_size)):
            self._stop_player()
            # H.264 从首帧开始固定使用内嵌窗口。观看切换到控制时复用同一个
            # 解码器，避免在码流中途重启而错过 SPS/PPS/IDR 后永久黑屏。
            if not self._start_opencv_player(
                    fmt, width, height, output_width, output_height,
                    interactive=(fmt == 'h264')):
                self.player_unavailable = True
                logger.warning('[RemoteView] 实时播放器不可用；帧保存在 %s',
                               REMOTE_VIEW_DIR)
                return
        if self.player_kind == 'opencv-jpeg':
            try:
                import cv2
                import numpy as np
                frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8),
                                     cv2.IMREAD_COLOR)
                if frame is not None:
                    cv2.imshow(f'学生屏幕 {self.sip}', frame)
                    cv2.waitKey(1)
            except Exception as e:
                logger.warning('[RemoteView] OpenCV JPEG 显示失败：%s', e)
                self.player_unavailable = True
            return
        try:
            self.player.stdin.write(data)
            self.player.stdin.flush()
        except (BrokenPipeError, OSError, AttributeError):
            logger.warning('[RemoteView] 视频解码器管道已关闭，停止播放器重启')
            self.player_unavailable = True
            self._stop_player()

    def _start_opencv_player(self, fmt, width, height,
                             output_width=None, output_height=None,
                             interactive=False):
        try:
            output_width = output_width or width
            output_height = output_height or height
            if fmt == 'mjpeg':
                import cv2  # noqa: F401
                self.player = 'opencv-jpeg'
                self.player_format = fmt
                self.player_kind = 'opencv-jpeg'
                self.player_size = (output_width, output_height)
                logger.info('[RemoteView] 使用 OpenCV 显示 JPEG：%s', self.sip)
                return True
            if width <= 0 or height <= 0:
                raise ValueError(f'无效画面尺寸 {width}x{height}')
            import imageio_ffmpeg
            if getattr(sys, 'frozen', False):
                ffmpeg = os.path.join(sys._MEIPASS, 'ffmpeg.exe')
            else:
                ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            try:
                if interactive:
                    raise ImportError('远控模式使用内嵌窗口')
                import cv2  # noqa: F401
                pixel_format = 'bgr24'
                player_kind = 'opencv-h264'
                reader = self._opencv_h264_reader
                display_name = 'OpenCV'
            except ImportError:
                import tkinter  # noqa: F401
                from PIL import ImageTk  # noqa: F401
                pixel_format = 'rgb24'
                player_kind = 'pillow-h264'
                reader = self._pillow_h264_reader
                display_name = 'Pillow/Tkinter'
            self.player = subprocess.Popen(
                [ffmpeg, '-loglevel', 'error', '-flags', 'low_delay',
                 '-threads', '1',
                 '-probesize', '32', '-analyzeduration', '0',
                 '-f', 'h264', '-i', 'pipe:0',
                 '-an', '-vf',
                 f'shuffleplanes=0:2:1:3,'
                 f'crop={output_width}:{output_height}:0:0',
                 '-f', 'rawvideo', '-pix_fmt', pixel_format, 'pipe:1'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            self.player_format = fmt
            self.player_kind = player_kind
            self.player_size = (output_width, output_height)
            player = self.player
            self.viewer_thread = threading.Thread(
                target=reader,
                args=(player, output_width, output_height),
                name=f'view-ui-{self.base_name}', daemon=True,
            )
            self.viewer_thread.start()
            threading.Thread(
                target=self._ffmpeg_stderr_reader,
                args=(player,), name=f'view-ffmpeg-{self.base_name}', daemon=True,
            ).start()
            logger.info('[RemoteView] 使用 bundled FFmpeg + %s 显示 H264：%s '
                        'encoded=%dx%d visible=%dx%d', display_name, self.sip,
                        width, height, output_width, output_height)
            return True
        except Exception as e:
            logger.warning('[RemoteView] OpenCV/FFmpeg 播放器启动失败：%s', e,
                           exc_info=True)
            self.player = None
            self.player_kind = None
            return False

    def _ffmpeg_stderr_reader(self, player):
        count = 0
        try:
            while player is self.player and player.stderr:
                raw = player.stderr.readline()
                if not raw:
                    return
                count += 1
                if count <= 20 or count % 100 == 0:
                    message = raw.decode('utf-8', errors='replace').strip()
                    if message:
                        logger.warning('[RemoteView] FFmpeg：%s', message)
        except (OSError, AttributeError):
            pass

    def _pillow_h264_reader(self, player, width, height):
        frame_size = width * height * 3
        root = None
        closed = threading.Event()
        try:
            import queue
            import tkinter as tk
            from PIL import ImageDraw, ImageTk
            frames = queue.Queue(maxsize=1)
            reader_done = threading.Event()

            def read_decoded_frames():
                try:
                    while not self.stop_event.is_set() and player is self.player:
                        chunks = bytearray()
                        while len(chunks) < frame_size:
                            chunk = player.stdout.read(frame_size - len(chunks))
                            if not chunk:
                                return
                            chunks.extend(chunk)
                        try:
                            frames.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            frames.put_nowait(bytes(chunks))
                        except queue.Full:
                            pass
                finally:
                    reader_done.set()

            root = tk.Tk()
            label = tk.Label(root, text='正在等待视频画面...', width=60,
                             height=20, borderwidth=0, highlightthickness=0,
                             padx=0, pady=0, takefocus=True,
                             bg='black', fg='white', cursor='none')
            label.pack()
            root.protocol('WM_DELETE_WINDOW', closed.set)
            last_move_time = [0.0]
            last_control_state = [None]
            displayed_image_size = [None]
            blocked_gui_keys = {0x12, 0x5B, 0x5C}  # Alt、左/右 Windows 键

            def control_active():
                with remote_state_lock:
                    return self.sip in remote_controls

            def normalized_mouse(event):
                image_size = displayed_image_size[0]
                if image_size is None:
                    image_size = (label.winfo_width(), label.winfo_height())
                image_width = max(1, image_size[0] - 1)
                image_height = max(1, image_size[1] - 1)
                x = min(max(event.x, 0), image_width)
                y = min(max(event.y, 0), image_height)
                normalized_x = round(x * 65535 / image_width)
                normalized_y = round(y * 65535 / image_height)
                source_x = round(normalized_x * max(0, width - 1) / 65535)
                source_y = round(normalized_y * max(0, height - 1) / 65535)
                return normalized_x, normalized_y, source_x, source_y

            def focus_control_window():
                try:
                    root.lift()
                    root.focus_force()
                    label.focus_set()
                except tk.TclError:
                    pass

            def mouse_event(action, event, data=0):
                if not control_active():
                    return None
                try:
                    x, y, source_x, source_y = normalized_mouse(event)
                    self.local_cursor = (source_x, source_y)
                    self.local_cursor_version += 1
                    self.last_local_cursor_at = time.monotonic()
                    send_remote_mouse(self.sip, action, x, y, data)
                    if action.endswith('down'):
                        focus_control_window()
                except Exception as e:
                    logger.warning('[RemoteControl] 窗口鼠标事件失败：%s', e)
                return 'break'

            def mouse_move(event):
                if not control_active():
                    return None
                now = time.monotonic()
                if now - last_move_time[0] < 1 / 120:
                    return 'break'
                last_move_time[0] = now
                return mouse_event('move', event)

            def mouse_wheel(event):
                return mouse_event('wheel', event, int(event.delta or 0))

            extended_keys = {
                'Left', 'Right', 'Up', 'Down', 'Home', 'End', 'Prior',
                'Next', 'Insert', 'Delete', 'Control_R', 'Alt_R',
                'KP_Enter', 'Num_Lock', 'Print', 'Cancel',
            }

            def key_event(event, key_up):
                if not control_active():
                    return None
                try:
                    virtual_key = int(event.keycode) & 0xFFFF
                    if virtual_key in blocked_gui_keys:
                        logger.info('[RemoteControl] 已拦截系统修饰键 vk=%#x',
                                    virtual_key)
                        return 'break'
                    logger.info('[RemoteControl] 窗口按键 %s keysym=%s '
                                'keycode=%#x',
                                'up' if key_up else 'down', event.keysym,
                                virtual_key)
                    send_remote_key(self.sip, virtual_key, key_up=key_up,
                                    extended=event.keysym in extended_keys)
                except Exception as e:
                    logger.warning('[RemoteControl] 窗口键盘事件失败：%s', e)
                return 'break'

            # Tk 会被 Windows 输入法吞掉部分字母键（尤其是中文输入法状态下）。
            # 远控时安装低级键盘钩子，直接使用系统提供的 VK/扫描码/按键状态。
            keyboard_hook_handle = [None]
            keyboard_hook_callback = [None]

            def install_keyboard_hook():
                if os.name != 'nt' or keyboard_hook_handle[0] is not None:
                    return
                try:
                    import ctypes
                    from ctypes import wintypes
                    user32 = ctypes.windll.user32
                    kernel32 = ctypes.windll.kernel32
                    WH_KEYBOARD_LL = 13
                    WM_KEYDOWN = 0x0100
                    WM_KEYUP = 0x0101
                    WM_SYSKEYDOWN = 0x0104
                    WM_SYSKEYUP = 0x0105
                    LLKHF_EXTENDED = 0x01
                    LLKHF_INJECTED = 0x10

                    class KBDLLHOOKSTRUCT(ctypes.Structure):
                        _fields_ = [
                            ('vkCode', wintypes.DWORD),
                            ('scanCode', wintypes.DWORD),
                            ('flags', wintypes.DWORD),
                            ('time', wintypes.DWORD),
                            ('dwExtraInfo', ctypes.c_void_p),
                        ]

                    callback_type = ctypes.WINFUNCTYPE(
                        ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM,
                        wintypes.LPARAM)

                    def keyboard_hook_proc(code, message, lparam):
                        try:
                            if code >= 0 and control_active():
                                info = ctypes.cast(
                                    lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)
                                ).contents
                                if not (info.flags & LLKHF_INJECTED):
                                    vk = int(info.vkCode) & 0xFFFF
                                    key_up = message in (WM_KEYUP, WM_SYSKEYUP)
                                    if vk in blocked_gui_keys:
                                        logger.info(
                                            '[RemoteControl] 全局钩子拦截系统键 vk=%#x',
                                            vk)
                                        return 1
                                    scan = int(info.scanCode) & 0xFFFF
                                    extended = bool(info.flags & LLKHF_EXTENDED)
                                    logger.info(
                                        '[RemoteControl] 全局按键 %s vk=%#x scan=%#x flags=%#x',
                                        'up' if key_up else 'down', vk, scan,
                                        int(info.flags))
                                    send_remote_key(
                                        self.sip, vk, key_up=key_up,
                                        scan_code=(scan or None), extended=extended)
                                    return 1
                        except Exception as e:
                            logger.warning('[RemoteControl] 全局键盘钩子失败：%s', e)
                        return user32.CallNextHookEx(
                            keyboard_hook_handle[0], code, message, lparam)

                    callback = callback_type(keyboard_hook_proc)
                    handle = user32.SetWindowsHookExW(
                        WH_KEYBOARD_LL, callback,
                        kernel32.GetModuleHandleW(None), 0)
                    if not handle:
                        raise ctypes.WinError()
                    keyboard_hook_callback[0] = callback
                    keyboard_hook_handle[0] = handle
                    logger.info('[RemoteControl] Windows 全局键盘钩子已启用')
                except Exception as e:
                    logger.warning('[RemoteControl] Windows 全局键盘钩子不可用：%s', e)

            def uninstall_keyboard_hook():
                handle = keyboard_hook_handle[0]
                if handle is None:
                    return
                try:
                    import ctypes
                    ctypes.windll.user32.UnhookWindowsHookEx(handle)
                except Exception as e:
                    logger.debug('[RemoteControl] 卸载全局键盘钩子失败：%s', e)
                finally:
                    keyboard_hook_handle[0] = None
                    keyboard_hook_callback[0] = None

            label.bind('<Motion>', mouse_move)
            label.bind('<ButtonPress-1>',
                       lambda e: mouse_event('leftdown', e))
            label.bind('<ButtonRelease-1>',
                       lambda e: mouse_event('leftup', e))
            label.bind('<ButtonPress-2>',
                       lambda e: mouse_event('middledown', e))
            label.bind('<ButtonRelease-2>',
                       lambda e: mouse_event('middleup', e))
            label.bind('<ButtonPress-3>',
                       lambda e: mouse_event('rightdown', e))
            label.bind('<ButtonRelease-3>',
                       lambda e: mouse_event('rightup', e))
            label.bind('<MouseWheel>', mouse_wheel)
            root.bind_all('<KeyPress>', lambda e: key_event(e, False))
            root.bind_all('<KeyRelease>', lambda e: key_event(e, True))
            root.update_idletasks()
            root.update()
            threading.Thread(
                target=read_decoded_frames,
                name=f'view-decode-{self.base_name}', daemon=True,
            ).start()
            waiting_since = time.monotonic()
            warned = False
            base_frame = None
            displayed_cursor_version = -1
            while (not self.stop_event.is_set() and not closed.is_set()
                   and player is self.player):
                try:
                    raw_frame = frames.get_nowait()
                except queue.Empty:
                    raw_frame = None
                if raw_frame is not None:
                    base_frame = Image.frombytes('RGB', (width, height), raw_frame)
                    waiting_since = time.monotonic()
                current_control_state = control_active()
                predicted_cursor_active = (
                    current_control_state and self.local_cursor is not None
                    and time.monotonic() - self.last_local_cursor_at < 0.18
                )
                cursor_version = (self.remote_cursor_version,
                                  self.local_cursor_version,
                                  predicted_cursor_active)
                if (base_frame is not None
                        and (raw_frame is not None
                             or cursor_version != displayed_cursor_version)):
                    frame = base_frame.copy()
                    cursor = (self.local_cursor if predicted_cursor_active
                              else self.remote_cursor)
                    if cursor is not None:
                        cursor_x = min(max(cursor[0], 0), width - 1)
                        cursor_y = min(max(cursor[1], 0), height - 1)
                        arm = max(8, min(width, height) // 60)
                        draw = ImageDraw.Draw(frame)
                        lines = [
                            (cursor_x - arm, cursor_y, cursor_x + arm, cursor_y),
                            (cursor_x, cursor_y - arm, cursor_x, cursor_y + arm),
                        ]
                        for line in lines:
                            draw.line(line, fill='black', width=5)
                            draw.line(line, fill='white', width=2)
                    screen_w = max(320, root.winfo_screenwidth() - 80)
                    screen_h = max(240, root.winfo_screenheight() - 120)
                    resampling = getattr(Image, 'Resampling', Image)
                    frame.thumbnail((screen_w, screen_h), resampling.LANCZOS)
                    displayed_image_size[0] = frame.size
                    photo = ImageTk.PhotoImage(frame)
                    label.configure(image=photo, text='', width=0, height=0)
                    label.image = photo
                    displayed_cursor_version = cursor_version
                elif (not warned and time.monotonic() - waiting_since >= 5):
                    warned = True
                    logger.warning('[RemoteView] FFmpeg 5 秒内未输出画面，窗口将继续等待；请查看随后 FFmpeg 日志')
                if current_control_state != last_control_state[0]:
                    title = ('远程控制' if current_control_state else '学生屏幕')
                    root.title(f'{title} {self.sip}')
                    if current_control_state:
                        install_keyboard_hook()
                        root.after_idle(focus_control_window)
                    else:
                        uninstall_keyboard_hook()
                    last_control_state[0] = current_control_state
                root.update_idletasks()
                root.update()
                if reader_done.is_set() and frames.empty():
                    label.configure(text='视频解码器已停止，请查看日志', image='',
                                    width=60, height=20)
                time.sleep(0.015)
        except Exception as e:
            if not self.stop_event.is_set():
                logger.warning('[RemoteView] Pillow/Tkinter 显示线程退出：%s', e)
        finally:
            try:
                uninstall_keyboard_hook()
            except UnboundLocalError:
                pass
            if closed.is_set():
                self.player_unavailable = True
                with remote_state_lock:
                    control_was_active = self.sip in remote_controls
                if control_was_active:
                    try:
                        stop_remote_control(self.sip)
                    except OSError as e:
                        logger.warning('[RemoteControl] 关闭窗口时停止远控失败：%s', e)
            if player is self.player:
                try:
                    player.terminate()
                except OSError:
                    pass
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    def _opencv_h264_reader(self, player, width, height):
        frame_size = width * height * 3
        window_name = f'学生屏幕 {self.sip}'
        try:
            import cv2
            import numpy as np
            while not self.stop_event.is_set() and player is self.player:
                chunks = bytearray()
                while len(chunks) < frame_size:
                    chunk = player.stdout.read(frame_size - len(chunks))
                    if not chunk:
                        return
                    chunks.extend(chunk)
                frame = np.frombuffer(chunks, dtype=np.uint8).reshape(
                    (height, width, 3)
                )
                cv2.imshow(window_name, frame)
                cv2.waitKey(1)
        except Exception as e:
            if not self.stop_event.is_set():
                logger.warning('[RemoteView] H264 显示线程退出：%s', e)
        finally:
            try:
                cv2.destroyWindow(window_name)
            except Exception:
                pass

    def _stop_player(self):
        player, self.player = self.player, None
        self.player_format = None
        kind, self.player_kind = self.player_kind, None
        self.player_size = None
        if player is None:
            return
        if kind == 'opencv-jpeg':
            try:
                import cv2
                cv2.destroyWindow(f'学生屏幕 {self.sip}')
            except Exception:
                pass
            return
        try:
            if player.stdin:
                player.stdin.close()
        except OSError:
            pass
        try:
            player.terminate()
        except OSError:
            pass


def probe_remote_view(sip, port=TCP_COMM_PORT, timeout=1.5):
    """仅探测学生端 TCP 服务是否监听；不发送 feature 8 或 SHCO。"""
    socket.inet_aton(sip)
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(timeout)
    try:
        probe.bind((ip, 0))
        error = probe.connect_ex((sip, port))
        if error == 0:
            return True, None
        return False, f'TCP connect_ex={error}'
    except OSError as e:
        return False, str(e)
    finally:
        probe.close()


def start_remote_view(sip, port=TCP_COMM_PORT, probe=False):
    if not network_started or not running:
        reason = '网络尚未启动或后台线程未运行'
        _set_view_error(sip, reason)
        logger.warning('[RemoteView] 拒绝启动 %s：%s', sip, reason)
        return False
    if not _check_student(sip, 'view <学生IP> [TCP端口]'):
        _set_view_error(sip, '学生未登录或不在快照中')
        return False
    with remote_state_lock:
        failure_time = remote_view_failures.get(sip)
        if failure_time is not None:
            remaining = VIEW_FAILURE_COOLDOWN - (time.monotonic() - failure_time)
            if remaining > 0:
                reason = f'失败冷却中，剩余 {remaining:.1f} 秒'
                _set_view_error(sip, reason)
                logger.warning('[RemoteView] 拒绝启动 %s：%s', sip, reason)
                return False
            remote_view_failures.pop(sip, None)
        if remote_views.get(sip):
            reason = '已有观看会话'
            _set_view_error(sip, reason)
            logger.warning('[RemoteView] 拒绝启动 %s：%s', sip, reason)
            return False
    if probe:
        reachable, detail = probe_remote_view(sip, port)
        if not reachable:
            reason = f'TCP 探测失败：{detail}'
            _set_view_error(sip, reason)
            logger.warning('[RemoteView] 拒绝启动 %s：%s', sip, reason)
            return False
    with remote_state_lock:
        session = RemoteViewSession(sip, port)
        remote_views[sip] = session
    if not send_remote_view_feature(sip, True):
        with remote_state_lock:
            if remote_views.get(sip) is session:
                remote_views.pop(sip, None)
            remote_view_failures[sip] = time.monotonic()
            remote_view_last_error[sip] = 'feature start 发送失败'
        session.stop()
        return False
    if not session.start():
        with remote_state_lock:
            if remote_views.get(sip) is session:
                remote_views.pop(sip, None)
            remote_view_failures[sip] = time.monotonic()
            remote_view_last_error[sip] = '观看线程启动失败'
        session.stop()
        send_remote_view_feature(sip, False)
        return False
    with remote_state_lock:
        remote_view_last_error.pop(sip, None)
    logger.info('[RemoteView] 已启动 %s:%d（未做 connect+close 探测）', sip, port)
    return True


def stop_remote_view(sip, notify=True):
    with remote_state_lock:
        session = remote_views.pop(sip, None)
        remote_view_failures.pop(sip, None)
        remote_view_last_error.pop(sip, None)
    if session is not None:
        try:
            session.stop()
        except Exception as error:
            logger.warning('[RemoteView] 停止本地会话失败 %s：%s', sip, error)
    ok = True
    if notify:
        ok = send_remote_view_feature(sip, False)
    logger.info('[RemoteView] stop -> %s（本地会话=%s，notify=%s，ok=%s）',
                sip, session is not None, notify, ok)
    return ok


def toggle_remote_view(sip, port=TCP_COMM_PORT, probe=False):
    state = get_view_state(sip)
    if state['active']:
        ok = stop_remote_view(sip, notify=True)
        return {
            'ok': ok,
            'active': get_view_state(sip)['active'],
            'action': 'stopped',
            'reason': None if ok else '停止包未送达',
            'cooldown_remaining': 0.0,
        }
    ok = start_remote_view(sip, port, probe=probe)
    state = get_view_state(sip)
    return {
        'ok': ok,
        'active': state['active'],
        'action': 'started' if ok else 'start',
        'reason': None if ok else state['reason'],
        'cooldown_remaining': state['cooldown_remaining'],
    }


def build_remote_control_payload(sip, mode, port):
    """构造 MCMD；mode 0/2 开始远控，mode 1 停止。"""
    payload = bytearray(53)
    struct.pack_into('<III', payload, 0, 53, 8, 0)
    payload[12:16] = b'MCMD'
    struct.pack_into('<I', payload, 16, mode)
    payload[20:24] = socket.inet_aton(sip)
    struct.pack_into('<H', payload, 24, port)
    return bytes(payload)


def choose_remote_control_port():
    """选择学生端模拟输入线程的 UDP 监听端口。"""
    if CONTROL_PORT:
        return CONTROL_PORT
    return random.SystemRandom().randint(49152, 65535)


def start_remote_control(sip, port=None):
    if not REMOTE_CONTROL_ENABLED:
        logger.warning('[RemoteControl] 已禁用，拒绝启动 %s', sip)
        return False
    if not _check_student(sip, 'control <学生IP> [UDP端口]'):
        return False
    with remote_state_lock:
        session = remote_views.get(sip)
    if session is None or not session.connected_event.is_set():
        logger.warning('[RemoteControl] 未发送 MCMD：%s 屏幕 TCP 通道尚未连接', sip)
        return False
    if port is None:
        port = choose_remote_control_port()
    if not 1 <= port <= 0xFFFF:
        raise ValueError('远控 UDP 端口必须在 1..65535')
    # mode 0 和 2 都会在学生端调用 BeginSimulate；mode 2 还会先执行
    # 官方 control 分支的输入 Hook 初始化和本地输入锁定。
    mode = CONTROL_MODE
    if mode == 1:
        raise ValueError('TEACHER_CONTROL_MODE=1 是仅观看模式，不能用于 control')
    packet = build_command_transaction(
        build_remote_control_payload(sip, mode, port))
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.bind((ip, 0))
    with remote_state_lock:
        old = remote_controls.pop(sip, None)
        if old:
            try:
                old['sock'].close()
            except OSError:
                pass
        remote_controls[sip] = {
            'port': port,
            'sock': sender,
            'input_count': 0,
            'ready_at': time.monotonic() + 0.35,
        }
    if not _send_main(packet, (sip, PORT), 'RemoteControl MCMD start'):
        with remote_state_lock:
            if remote_controls.get(sip, {}).get('sock') is sender:
                remote_controls.pop(sip, None)
        try:
            sender.close()
        except OSError:
            pass
        return False
    mode_name = 'Share' if mode == 0 else 'Control Student'
    logger.info('[RemoteControl] COMD/MCMD mode=%d (%s) -> %s:%d，输入端点=%s:%d',
                mode, mode_name, sip, PORT, sip, port)
    return port


def stop_remote_control(sip, notify=True):
    with remote_state_lock:
        state = remote_controls.pop(sip, None)
    port = state['port'] if state else (CONTROL_PORT or 0)
    if state:
        try:
            state['sock'].close()
        except OSError as error:
            logger.debug('[RemoteControl] 关闭输入 socket 忽略：%s', error)
    ok = True
    if notify:
        packet = build_command_transaction(
            build_remote_control_payload(sip, 1, port))
        ok = _send_main(packet, (sip, PORT), 'RemoteControl MCMD stop',
                        allow_when_stopped=True)
    logger.info('[RemoteControl] stop -> %s:%d notify=%s ok=%s',
                sip, port, notify, ok)
    return ok


def send_remote_input(sip, kind, payload):
    if len(payload) != 20:
        raise ValueError('远控输入 payload 必须是 20 字节')
    with remote_state_lock:
        state = remote_controls.get(sip)
    if not state:
        logger.warning('[RemoteControl] %s 尚未 control，忽略输入', sip)
        return False
    startup_delay = state['ready_at'] - time.monotonic()
    if startup_delay > 0:
        time.sleep(startup_delay)
    packet = struct.pack('<II', 0x2321347C, kind) + payload
    try:
        state['sock'].sendto(packet, (sip, state['port']))
    except OSError as error:
        logger.error('[RemoteControl] input 发送失败 -> %s:%d error=%s',
                     sip, state['port'], error)
        return False
    with remote_state_lock:
        state['input_count'] += 1
        input_count = state['input_count']
    if kind == 16 or input_count <= 8 or input_count % 100 == 0:
        logger.info('[RemoteControl] input #%d kind=%d -> %s:%d data=%s',
                    input_count, kind, sip, state['port'], packet.hex(' '))
    else:
        logger.debug('[RemoteControl] input #%d kind=%d -> %s:%d\n%s',
                     input_count, kind, sip, state['port'], hexdump(packet))
    return True


MOUSE_MESSAGES = {
    'move': 0x0200,
    'leftdown': 0x0201,
    'leftup': 0x0202,
    'rightdown': 0x0204,
    'rightup': 0x0205,
    'middledown': 0x0207,
    'middleup': 0x0208,
    'wheel': 0x020A,
}


def send_remote_mouse(sip, action, x, y, data=0, swapped=0):
    action = action.lower()
    if action not in MOUSE_MESSAGES:
        raise ValueError('鼠标动作应为 ' + '/'.join(MOUSE_MESSAGES))
    if not 0 <= x <= 65535 or not 0 <= y <= 65535:
        raise ValueError('鼠标坐标必须在 0..65535')
    payload = struct.pack('<IIIII', MOUSE_MESSAGES[action], x, y,
                          data & 0xFFFFFFFF, swapped & 0xFFFFFFFF)
    sent = send_remote_input(sip, 1, payload)
    if sent and action != 'move':
        logger.info('[RemoteControl] mouse %s -> %s (%d,%d) data=%d',
                    action, sip, x, y, data)
    return sent


def send_remote_key(sip, virtual_key, key_up=False, scan_code=None,
                    extended=False):
    if not 0 <= virtual_key <= 0xFFFF:
        raise ValueError('虚拟键码必须在 0..0xFFFF')
    if scan_code is None:
        try:
            import ctypes
            scan_code = ctypes.windll.user32.MapVirtualKeyW(virtual_key, 0)
        except Exception:
            scan_code = virtual_key
    flags = (1 if extended else 0) | (0x80 if key_up else 0)
    payload = struct.pack('<HHI', scan_code & 0xFFFF,
                          virtual_key & 0xFFFF, flags) + b'\x00' * 12
    return send_remote_input(sip, 16, payload)


def send_chat(sip, text):
    """向已登录学生发送聊天消息（MESS，payload type=0x800）。"""
    if sip not in students:
        logger.warning('[命令] 学生 %s 未登录，拒绝发送聊天消息', sip)
        return False
    try:
        text_utf16 = text.encode('utf-16-le') + b'\x00\x00'
        # [12..15] 经测试应设为 UTF-16 码元数（含结尾空字符），否则学生端可能只显示第一个字。
        wchar_count = len(text_utf16) // 2
        payload = (struct.pack('<I', 16 + len(text_utf16))
                   + struct.pack('<I', 0x800)
                   + struct.pack('<I', 0)
                   + struct.pack('<I', wchar_count)
                   + text_utf16)
        mess = (struct.pack('<II', 0x5353454D, 1)
                + struct.pack('<I', 1)
                + socket.inet_aton(sip)
                + payload)
        ok = _send_session(mess, (sip, SPORT), 'Chat MESS')
        logger.info('[命令] 发送聊天消息 -> %s: %s ok=%s', sip, text, ok)
        return ok
    except Exception as error:
        logger.error('[命令] 发送聊天消息失败：%s', error, exc_info=True)
        return False


def request_info(sip, rtype=0):
    """请求学生上报信息（MESS，payload type=0x100000）。

    rtype（学生端 sub_445670 的分支条件）：
           0=全部（type 5 系统信息 + type 6 窗口列表 + type 7 进程列表）
           1=type 6 窗口/应用程序列表（hwnd+标题，分片）
           2=type 7 进程列表（pid+exe名，分片）
    学生端入口: sub_44CA70 [payload+4]==0x100000 → sub_445670。
    """
    if sip not in students:
        logger.warning('[Info] 学生 %s 未登录，拒绝请求信息', sip)
        return False
    try:
        payload = (struct.pack('<I', 16)
                   + struct.pack('<I', 0x100000)
                   + struct.pack('<I', 0)
                   + struct.pack('<I', rtype))
        mess = (struct.pack('<II', 0x5353454D, 1)
                + struct.pack('<I', 1)
                + socket.inet_aton(sip)
                + payload)
        ok = _send_session(mess, (sip, SPORT), 'Info MESS')
        logger.info('[Info] 信息请求 rtype=%d -> %s:%d ok=%s', rtype, sip, SPORT, ok)
        return ok
    except Exception as error:
        logger.error('[Info] 发送信息请求失败：%s', error, exc_info=True)
        return False


def send_kill(sip, pid=None, hwnd=None, force=1):
    """结束进程 / 结束应用程序（MESS，0x100000 通道，学生端 sub_445670 type 4/3）。

    pid  → type 4（按进程结束）；hwnd → type 3（按窗口结束应用程序）。
    force=1: TerminateProcess 强杀；force=0: 先给主窗口发 WM_CLOSE（温和结束）。
    学生端 fire-and-forget 无确认包；杀完重新 info 刷新列表验证结果。
    """
    if sip not in students:
        logger.warning('[命令] 学生 %s 未登录，拒绝结束命令', sip)
        return False
    if pid is None and hwnd is None:
        logger.warning('[命令] 需要 pid 或 hwnd')
        return False
    try:
        rtype = 4 if pid is not None else 3
        payload = (struct.pack('<I', 24) + struct.pack('<I', 0x100000)
                   + struct.pack('<I', 0) + struct.pack('<I', rtype)
                   + struct.pack('<I', hwnd or 0) + struct.pack('<I', pid or 0)
                   + struct.pack('<I', force))
        mess = (struct.pack('<II', 0x5353454D, 1) + struct.pack('<I', 1)
                + socket.inet_aton(sip) + payload)
        kind = f'进程 pid={pid}' if rtype == 4 else f'应用窗口 hwnd=0x{hwnd:08X}'
        ok = _send_session(mess, (sip, SPORT), 'Kill MESS')
        logger.info('[命令] 结束%s -> %s force=%d ok=%s', kind, sip, force, ok)
        return ok
    except Exception as error:
        logger.error('[命令] 发送结束命令失败：%s', error, exc_info=True)
        return False


def send_open_url(sip, url):
    """打开网页/文件（COMD 应用命令，cmdId 0x18，sub_44A490 case 0x18）。

    学生端执行 ShellExecuteW(0, "open", url, ...)：网址走默认浏览器；
    也可以传学生机上的文件路径，按扩展名关联程序打开（.txt/.jpg 等）。
    """
    if sip not in students:
        logger.warning('[命令] 学生 %s 未登录，拒绝打开命令', sip)
        return False
    try:
        payload = (struct.pack('<I', 0x200) + struct.pack('<I', 0)
                   + struct.pack('<I', 0x18) + struct.pack('<I', 0)
                   + url.encode('utf-16-le') + b'\x00\x00'
                   + b'\x00' * 4)
        pkt = build_comd_command_ex(0x80000010, payload,
                                    'f96a6d195b2946b9ab958a143ecddc26')
        ok = _send_main(pkt, (sip, PORT), 'OpenURL COMD')
        logger.info('[命令] 打开网页/文件 -> %s: %s ok=%s', sip, url, ok)
        return ok
    except Exception as error:
        logger.error('[命令] 发送打开命令失败：%s', error, exc_info=True)
        return False


def send_run_program(sip, path, args='', show=0, fallback=1):
    """远程运行程序（COMD 应用命令，cmdId 0x0F，case 0x0F → sub_432CB0）。

    学生端执行 CreateProcessW("\"path\" args")（服务态用 CreateProcessAsUser）。
    path 必须是学生机上的绝对路径；show: 0=正常 1=最小化 2=最大化；
    fallback=1 时启动失败会在系统目录查找同名程序重试一次。
    """
    if sip not in students:
        logger.warning('[命令] 学生 %s 未登录，拒绝运行命令', sip)
        return False
    try:
        body = struct.pack('<I', 0x0F) + struct.pack('<I', fallback)
        body += path.encode('utf-16-le')[:510].ljust(512, b'\x00')
        body += args.encode('utf-16-le')[:318].ljust(320, b'\x00')
        body += struct.pack('<I', show)
        payload = (struct.pack('<I', 0x200) + struct.pack('<I', 0)
                   + body + b'\x00' * 4)
        pkt = build_comd_command_ex(0x80000010, payload,
                                    'f96a6d195b2946b9ab958a143ecddc26')
        ok = _send_main(pkt, (sip, PORT), 'RunProgram COMD')
        logger.info('[命令] 远程运行 -> %s: "%s" %s show=%d ok=%s',
                    sip, path, args, show, ok)
        return ok
    except Exception as error:
        logger.error('[命令] 发送运行命令失败：%s', error, exc_info=True)
        return False


def _parse_id_name_pairs(buf):
    """解析 {u32 id, wchar name\0} 序列（type 6 窗口列表 / type 7 进程列表的条目）。

    学生端条目格式（sub_445670）：id(4) + name(UTF-16LE) + \\x00\\x00，
    每条 6 + 2*len(name) 字节。返回 [(id, name), ...]，容错截断。
    """
    entries = []
    pos, end = 0, len(buf)
    while pos + 6 <= end:
        rid = struct.unpack('<I', buf[pos:pos + 4])[0]
        chars = bytearray()
        p = pos + 4
        while p + 2 <= end and buf[p:p + 2] != b'\x00\x00':
            chars += buf[p:p + 2]
            p += 2
        name = bytes(chars).decode('utf-16-le', errors='ignore')
        entries.append((rid, name))
        pos = p + 2
    return entries


def _parse_student_info(payload, sip):
    """解析 type 5 学生信息结构体（自 payload 起，含 12 字节消息头）。

    布局（学生端 sub_445670 填充，均为 UTF-16LE 定长字段）：
      +0x0C  DWORD 5            +0x10  计算机名[32]   +0x50  学生ID u32
      +0x54  MAC[6]             +0x5A  登录用户[32]   +0x9A  OS名称[32]
      +0xDA  OS版本[64]         +0x21A CPU厂商[32]   +0x25A CPU型号[64]
      +0x2DA 内存 "xxxx MB"[16]
    """
    def wstr(off, maxlen):
        raw = payload[off:off + maxlen * 2]
        return raw.decode('utf-16-le', errors='ignore').split('\x00')[0]

    info = {
        'name': wstr(0x10, 32),
        'stu_id': struct.unpack('<I', payload[0x50:0x54])[0],
        'mac': '-'.join(f'{b:02X}' for b in payload[0x54:0x5A]),
        'user': wstr(0x5A, 32),
        'os': wstr(0x9A, 32),
        'osver': wstr(0xDA, 64),
        'cpu_vendor': wstr(0x21A, 32),
        'cpu_model': wstr(0x25A, 64),
        'mem': wstr(0x2DA, 16),
    }
    if sip in students:
        students[sip]['info'] = info
        handle_classroom_student_info(sip, info)
    return info


def build_comd_command(cmd_code, payload):
    """构造 COMD 命令包（Magic=0x434F4D44，即代码中的 DMOC）。"""
    global cmd_seq
    cmd_id = cmd_seq
    cmd_seq += 1
    inner = (struct.pack('<I', cmd_code)
             + struct.pack('<I', cmd_id)
             + struct.pack('<I', len(payload))
             + struct.pack('<I', 0)      # reserved
             + payload)
    return (struct.pack('<II', 0x434F4D44, 0x10000)
            + struct.pack('<I', len(inner))
            + bytes.fromhex('ce90fd383df5844c857fa35183c051f3')
            + inner)


def build_comd_command_ex(cmd_code, payload, guid_hex, extra_header=b''):
    """构造 COMD 命令包，可自定义 GUID 与 GUID 后的额外头。"""
    global cmd_seq
    cmd_id = cmd_seq
    cmd_seq += 1
    inner = (struct.pack('<I', cmd_code)
             + struct.pack('<I', cmd_id)
             + struct.pack('<I', len(payload))
             + struct.pack('<I', 0)
             + payload)
    return (struct.pack('<II', 0x434F4D44, 0x10000)
            + struct.pack('<I', len(extra_header) + len(inner))
            + bytes.fromhex(guid_hex)
            + extra_header
            + inner)


def build_blackscreen_mess_payload(lock_input=True, timeout=10, text=None, text_color=0x0000FFFF):
    """构造黑屏安静命令的 MESS payload。

    逐字节匹配真实抓包（教师端 sub_54C4E0，MESS type=0x20）。

    抓包验证结构（教师到当前频道对应的会话组播端点）：
      [0..3]  = 总长度 (基础 39 字节 + 可选文本)
      [4..7]  = 0x20 (黑屏)
      [8..11] = 0x80000000 (启动标志)
      [12..15]= lock_input (1=锁定键鼠)
      [16..19]= 0x01 (禁用学生端本地定时器，由教师端负责超时解锁)
      [20..23]= timeout (超时秒数, 0=永久；供协议字段保持一致)
      [24..27]= has_text (0/1)
      [28..31]= text_color (Windows COLORREF: 0x00BBGGRR)
      [32..35]= 0x00000000 (field_5)
      [36..38]= 0xA00520 (padding, 仅 has_text=0 时)
      [36..]  = UTF-16LE 文本 (has_text=1 时)

    text_color 默认值 0x0000FFFF = 黄色 (R=255,G=255,B=0)，匹配真实教师端。
    要白色用 0x00FFFFFF，红色用 0x000000FF。
    """
    has_text = 1 if text else 0
    text_utf16 = b''
    if has_text:
        text_utf16 = (text.encode('utf-16-le') + b'\x00\x00') if text else b''

    total_len = 39 + len(text_utf16)  # 基础 39 字节

    payload = struct.pack('<I', total_len)               # [0] 总长
    payload += struct.pack('<I', 0x20)                    # [4] 黑屏
    payload += struct.pack('<I', 0x80000000)              # [8] 启动标志
    payload += struct.pack('<I', 1 if lock_input else 0)  # [12] 锁定输入
    payload += struct.pack('<I', 1)                       # [16] 不启用学生端本地定时器
    payload += struct.pack('<I', timeout)                 # [20] 超时
    payload += struct.pack('<I', has_text)                # [24] 有自定义文字
    payload += struct.pack('<I', text_color)              # [28] 文字颜色 (0x00BBGGRR)
    payload += struct.pack('<I', 0)                       # [32] field_5
    if has_text:
        payload += text_utf16                             # [36+] UTF-16LE 文本
    else:
        payload += b'\xa0\x05\x20'                        # [36..38] padding (来自真实抓包)
    return payload


# 跟踪各学生的自动解锁定时器，方便手动解锁时取消
blackscreen_timers = {}   # sip -> threading.Timer


def _send_comd_blackscreen_lock(sip, timeout=10):
    """补发 COMD case 6 黑屏锁定命令，兼容只处理该路径的学生端。

    学生端反编译确认：case 6 的 lock_input=0 仅表示“不新加锁”，并
    不是解锁命令。这里因此只发送 lock_input=1。timer_flag=1 禁用
    学生端本地定时器，统一由 blackscreen_timers 负责超时解锁，避免
    永久黑屏被 COMD 中固定的 10 秒定时器提前解除。
    """
    payload = struct.pack('<I', 0x200)        # subcmd
    payload += struct.pack('<I', 0)            # flags
    payload += struct.pack('<I', 6)            # case 6 = 黑屏/锁键鼠
    payload += struct.pack('<I', 1)            # lock_input=1
    payload += struct.pack('<I', 1)            # 禁用学生端本地定时器
    payload += struct.pack('<I', timeout)       # 与 MESS timeout 保持一致
    payload += struct.pack('<I', 0)            # has_text
    payload += b'\x00' * 8                    # padding
    pkt = build_comd_command_ex(0x80000010, payload, 'f96a6d195b2946b9ab958a143ecddc26')
    ok = _send_main(pkt, (sip, PORT), 'BlackScreen COMD case6')
    logger.info('[锁键鼠] COMD case6 lock=1 timer_flag=1 timeout=%d -> %s:%d ok=%s',
                timeout, sip, PORT, ok)
    return ok


def send_blackscreen(sip, lock_input=True, timeout=10, text=None):
    """向已登录学生发送黑屏安静命令。

    MESS 协议 → 当前频道对应的会话组播端点（黑屏窗口、bit 0x20 状态，
                  lock_input 非零时也会直接锁定键鼠）
    COMD 协议 → 学生单播 :4705（锁定兼容补包，sub_44A490 case 6）

    超时由教师端主动发解锁包实现——先发 flags=0x80000000（锁），
    时间到再发 flags=0x90000000（解）。
    """
    if sip not in students:
        logger.warning('[命令] 学生 %s 未登录，拒绝黑屏命令', sip)
        return False
    try:
        payload = build_blackscreen_mess_payload(lock_input, timeout, text)
        mess = (struct.pack('<II', 0x5353454D, 1)
                + struct.pack('<I', 1)
                + socket.inet_aton(sip)
                + payload)
        ok = _send_session(mess, (SMCAST, SPORT), 'BlackScreen MESS')
        if lock_input:
            ok = _send_comd_blackscreen_lock(sip, timeout=timeout) and ok
        if sip in blackscreen_timers:
            blackscreen_timers[sip].cancel()
            del blackscreen_timers[sip]
        if timeout > 0:
            timeout_str = f'{timeout}秒后自动解锁'
            timer = threading.Timer(timeout, _auto_unlock, args=(sip,))
            timer.daemon = True
            timer.start()
            blackscreen_timers[sip] = timer
        else:
            timeout_str = '永久（需手动 unlock）'
        logger.info('[命令] 黑屏安静 -> %s lock=%s timeout=%s text=%s ok=%s',
                    sip, lock_input, timeout_str, text, ok)
        return ok
    except Exception as error:
        logger.error('[命令] 发送黑屏安静失败：%s', error, exc_info=True)
        return False


def _auto_unlock(sip):
    """定时器回调：到了超时时间自动解锁。"""
    if sip in blackscreen_timers:
        del blackscreen_timers[sip]
    if sip in students:
        logger.info('[AutoUnlock] 超时自动解锁 %s', sip)
        return _do_unlock(sip)
    logger.info('[AutoUnlock] %s 已下线，跳过', sip)
    return False


def _do_unlock(sip):
    """通过 MESS 停止标志关闭黑屏并解除键鼠锁。"""
    try:
        payload = (struct.pack('<I', 0x0D)
                   + struct.pack('<I', 0x20)
                   + struct.pack('<I', 0x90000000)
                   + b'\x01')
        mess = (struct.pack('<II', 0x5353454D, 1)
                + struct.pack('<I', 1)
                + socket.inet_aton(sip)
                + payload)
        ok = _send_session(mess, (SMCAST, SPORT), 'Unblack MESS',
                           allow_when_stopped=True)
        logger.info('[解锁] MESS -> %s:%d 目标=%s ok=%s', SMCAST, SPORT, sip, ok)
        return ok
    except Exception as error:
        logger.error('[解锁] 发送失败：%s', error, exc_info=True)
        return False


def send_unlock(sip):
    """向已登录学生发送 MESS 黑屏停止/解锁命令。"""
    if sip not in students:
        logger.warning('[命令] 学生 %s 未登录，拒绝解锁', sip)
        return False
    if sip in blackscreen_timers:
        blackscreen_timers[sip].cancel()
        del blackscreen_timers[sip]
    ok = _do_unlock(sip)
    logger.info('[命令] 解锁 -> %s ok=%s', sip, ok)
    return ok


def send_shutdown(sip, reboot=False, delay=0, force=True, text=None):
    """关机/重启学生机（COMD 0x80000010，category=0x200 → sub_44A490）。

    cmdId: 0x14=关机，0x13=重启，|0x10000000=强制（跳过学生端倒计时气泡）。
    delay>0 且非 force 时，学生端弹倒计时气泡（(delay+1)*1000ms，文本取 text）。
    执行端为学生端目录下 Shutdown.exe：关机=-nb，重启=-b，force=-f/-nf，
    执行后学生端进程自杀退出。

    注意：payload 末尾必须多补 4 字节——学生端按包内 len 从 body+0xC 复制，
    会从 reserved 字段开始算，吃掉 payload 尾部 4 字节。
    """
    if sip not in students:
        logger.warning('[命令] 学生 %s 未登录，拒绝关机/重启', sip)
        return False
    try:
        cmd = (0x13 if reboot else 0x14) | (0x10000000 if force else 0)
        payload = struct.pack('<I', 0x200)
        payload += struct.pack('<I', 0)
        payload += struct.pack('<I', cmd)
        payload += struct.pack('<I', delay)
        payload += b'\x00' * 8
        if text:
            payload += text.encode('utf-16-le') + b'\x00\x00'
        payload += b'\x00' * 4
        pkt = build_comd_command_ex(0x80000010, payload,
                                    'f96a6d195b2946b9ab958a143ecddc26')
        action = '重启' if reboot else '关机'
        ok = _send_main(pkt, (sip, PORT), f'{action} COMD')
        mode = '强制立即' if force else (f'倒计时{delay}秒' if delay > 0 else '立即')
        logger.info('[命令] %s -> %s cmd=0x%08X delay=%d mode=%s text=%s ok=%s',
                    action, sip, cmd, delay, mode, text, ok)
        return ok
    except Exception as error:
        logger.error('[命令] 发送关机/重启失败：%s', error, exc_info=True)
        return False




REMOTE_SETTING_CATEGORY = 0x4000
REMOTE_CHANNEL_SUBCASE = 7
REMOTE_CHANNEL_SETTINGS_SIZE = 12
REMOTE_CHANNEL_GUID = 'f96a6d195b2946b9ab958a143ecddc26'


def build_remote_channel_settings_payload(channel, auto_login):
    """构造 COMD category=0x4000 / subcase 7 实验性远程频道设置的内层 payload。

    偏移相对 COMD 内层 payload（外层包 +0x2c）：
      +0x00 category=0x4000   +0x04 flags=0   +0x08 subcase=7   +0x0c length=12
      +0x10 settings: +0x00 未知(0)  +0x04 AutoLogin  +0x08 ChannelId
      +0x1c 尾部 4 字节 NUL（接收端按包内 len 复制时会从 reserved 起吃掉 4 字节）
    length 的语义未知，subcase 7 不使用它，这里只按 settings 长度填 12；
    flags 其余位、settings +0x00 以及其它 subcase 的布局均未证实。
    """
    if type(channel) is not int or not 1 <= channel <= 32:
        raise ValueError('远程频道必须是 1 到 32 的整数')
    if type(auto_login) is not int or auto_login not in (0, 1):
        raise ValueError('AutoLogin 必须是 0 或 1')
    settings = struct.pack('<III', 0, auto_login, channel)
    payload = (struct.pack('<IIII', REMOTE_SETTING_CATEGORY, 0,
                           REMOTE_CHANNEL_SUBCASE, len(settings))
               + settings
               + b'\x00' * 4)
    if len(settings) != REMOTE_CHANNEL_SETTINGS_SIZE or len(payload) != 32:
        raise AssertionError('远程频道设置 payload 长度错误')
    return payload


def send_remote_channel_settings(sip, channel, auto_login):
    """向已登录学生单播实验性远程频道设置（COMD 0x4000 / subcase 7）。

    仅发送控制面：不改变教师端自身运行频道（CHANNEL_ID / SMCAST / SPORT），
    也没有结果回执。学生端是否写入注册表、是否需要重启或重连、以及官方
    教师端兼容性均未实机验证。
    """
    payload = build_remote_channel_settings_payload(channel, auto_login)
    if not _check_student(sip, 'setchannel <学生IP> <1..32> [0|1]'):
        return False
    packet = build_comd_command_ex(0x80000010, payload, REMOTE_CHANNEL_GUID)
    ok = _send_main(packet, (sip, PORT), 'RemoteChannelSettings COMD')
    logger.info(
        '[RemoteSetting] 实验性控制面 COMD category=0x4000 subcase=7 -> %s:%d '
        'channel=%d auto_login=%d length=%d settings=%d payload=%d packet=%d ok=%s；'
        'length 语义未知（subcase 7 不使用）；不改变教师端自身运行频道；'
        '学生端注册表写入与重启/重连效果未实机验证，官方兼容性未验证，无结果回执',
        sip, PORT, channel, auto_login, REMOTE_CHANNEL_SETTINGS_SIZE,
        REMOTE_CHANNEL_SETTINGS_SIZE, len(payload), len(packet), ok)
    return ok


def build_dmoc():
    """构造 DMOC 包（教师端控制信息）。"""
    cg = bytes.fromhex('ce90fd383df5844c857fa35183c051f3')
    dd = b'\x20\x4e\x00\x00' + socket.inet_aton(ip) + b'\x35\x00\x00\x00\x35\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x80'
    dd += bytes.fromhex('e10202331e16e102023421160000a046000020419a99993fa0052000')
    dd += b'\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x3d\x00'
    return struct.pack('<II', 0x434F4D44, 0x10000) + struct.pack('<I', len(dd)) + cg + dd


def build_lpnt(policy_version=3, enabled=True, width=80, height=60, refresh_seconds=5):
    """构造缩略图策略包：版本、启用标志、宽、高、刷新秒数。"""
    lg = bytes.fromhex('aa3a8dbe2b906645908ea29526218540')
    policy = struct.pack('<IIIII', policy_version, int(enabled),
                         width, height, refresh_seconds)
    return struct.pack('<III', 0x544E504C, 0x10000, len(policy)) + lg + policy


def build_srnt(frame_seq, complete=True, missing_parts=()):
    """构造学生端实际接收的 SRNT 帧确认/重传请求。"""
    lg = bytes.fromhex('aa3a8dbe2b906645908ea29526218540')
    if missing_parts is None:
        payload = struct.pack('<III', frame_seq, 0, 0xFFFFFFFF)
    else:
        missing_parts = tuple(missing_parts)
        payload = struct.pack('<III', frame_seq, int(complete), len(missing_parts))
        if missing_parts:
            payload += struct.pack(f'<{len(missing_parts)}H', *missing_parts)
    # DLL 要求 payload 至少 14 字节；最后两个字节不参与解析。
    payload += b'\x00\x00'
    return struct.pack('<III', 0x544E5253, 0x10000, len(payload)) + lg + payload


def keep_alive_preview(sip):
    """等待策略确认或完整帧发布；不再周期性发送 LPNT/DMOC。"""
    logger.info('[KeepAlive] 启动 %s（等待 TRNT/完整帧，不周期性回包）', sip)
    # 记录“已为哪个期望版本做过 TTL 补发”；新的策略变更会把 expected 推进，
    # 从而自动重新武装一次，而不是整个进程只补发一次。
    resent_version = None
    while (running and not network_stop_event.is_set()
           and sip in students):
        # 先读状态再清理过期帧，否则 TTL 分支永远拿不到 last_fragment_at。
        with state_lock:
            expected = preview_policy_versions.get(sip, PREVIEW_POLICY_BASE)
            confirmed = preview_confirmed_versions.get(sip)
            published = sip in completed_preview_frames
            frame_state = previews.get(sip)
            last_fragment_at = (frame_state or {}).get('last_fragment_at')
        if published:
            logger.info('[KeepAlive] %s 完整帧已发布，停止', sip)
            break
        if confirmed == expected:
            logger.info('[KeepAlive] %s 策略已确认 version=%d，停止（不重复 LPNT/DMOC）',
                        sip, expected)
            break
        if (resent_version != expected
                and frame_state is not None and last_fragment_at is not None
                and time.monotonic() - last_fragment_at > PREVIEW_FRAME_TTL):
            resent_version = expected
            version = _next_preview_policy_versions(sip, 1)[0]
            _send_lpnt(sip, version, True, 'KeepAlive TTL')
            logger.info('[KeepAlive] %s 重组 TTL 超时，为期望版本 %d 补发一次 '
                        'LPNT version=%d', sip, resent_version, version)
        _expire_preview_frames()
        if _sleep_or_stop(0.55):
            break
    logger.info('[KeepAlive] %s 退出 published=%s confirmed=%s expected=%s',
                sip, sip in completed_preview_frames,
                preview_confirmed_versions.get(sip),
                preview_policy_versions.get(sip, PREVIEW_POLICY_BASE))


def handle_tnal(d, sip):
    """接收 LANT 预览缩略图片段并拼成 JPEG，只有发布成功才算完成。"""
    logger.debug('[LANT] RECV from %s, len=%d\n%s', sip, len(d), hexdump(d[:256]))

    if len(d) < 48:
        logger.warning('[TNAL] 包太短：%d 字节 from %s', len(d), sip)
        return

    try:
        frame_seq = struct.unpack('<I', d[32:36])[0]
        total = struct.unpack('<I', d[36:40])[0]
        offset = struct.unpack('<I', d[40:44])[0]
        frag_len = struct.unpack('<I', d[44:48])[0]
    except struct.error as error:
        logger.error('[TNAL] 解包失败 from %s：%s', sip, error, exc_info=True)
        return

    frag = d[48:48+frag_len]
    logger.debug('[LANT] %s frame=%d total=%d offset=%d frag_len=%d',
                 sip, frame_seq, total, offset, frag_len)

    if not frag or total == 0 or offset >= total:
        logger.warning('[LANT] 非法片段 frame=%d total=%d offset=%d from %s',
                       frame_seq, total, offset, sip)
        return

    _expire_preview_frames()
    with state_lock:
        state = previews.get(sip)
        if state is None or state['frame_seq'] != frame_seq or state['total'] != total:
            logger.info('[Preview] %s 新建帧 frame=%d total=%d source=LANT',
                        sip, frame_seq, total)
            completed_preview_frames.pop(sip, None)
            preview_last_errors.pop(sip, None)
            state = {
                'frame_seq': frame_seq,
                'total': total,
                'buf': bytearray(total),
                'got': 0,
                'received': {},
                'last_fragment_at': time.monotonic(),
                'publish_attempts': 0,
                'published': False,
            }
            previews[sip] = state
            _ensure_preview_keepalive(sip)
        state['last_fragment_at'] = time.monotonic()
        end = min(offset + len(frag), total)
        written = end - offset
        if written <= 0:
            logger.warning('[LANT] 非法写入 offset=%d end=%d from %s', offset, end, sip)
            return
        state['buf'][offset:end] = frag[:written]
        previous = state['received'].get(offset, 0)
        state['received'][offset] = max(previous, written)
        state['got'] += max(0, written - previous)
        missing = _preview_missing_parts(state)
        logger.info('[Preview] %s frame=%d 分片 offset=%d len=%d got=%d/%d '
                    'missing_offsets=%d last_fragment_at=%.3f',
                    sip, frame_seq, offset, written, state['got'], total,
                    len(missing), state['last_fragment_at'])
        complete = state['got'] >= total
        image_bytes = bytes(state['buf']) if complete else None
        attempts = state['publish_attempts']

    if not complete or attempts >= 3:
        return

    with state_lock:
        state['publish_attempts'] = attempts + 1
    try:
        # 极域学生端 JPEG 是 bottom-up DIB + 仅色度反相（Cb/Cr 反相，Y 不变）。
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        ycbcr = img.convert('YCbCr')
        y, cb, cr = ycbcr.split()
        img = Image.merge('YCbCr', (y, ImageOps.invert(cb),
                                    ImageOps.invert(cr))).convert('RGB')
        if os.environ.get('TEACHER_SAVE_PREVIEWS', '0') == '1':
            path = os.path.join(LOG_DIR, f'preview_{sip.replace(".", "_")}_latest.jpg')
            img.save(path, 'JPEG', quality=95)
            logger.info('[Preview] 已保存修复图 %s', path)
        published = img.copy()
        gui_events.preview_events.publish(sip, published.copy())
    except Exception as error:
        reason = f'图像解码/发布失败：{error}'
        with state_lock:
            state['last_error'] = reason
            preview_last_errors[sip] = reason
        logger.error('[Preview] %s frame=%d %s；不标记完成，请求重传',
                     sip, frame_seq, reason, exc_info=True)
        _send_main(build_srnt(frame_seq, complete=False, missing_parts=None),
                   (sip, PORT), 'Preview SRNT retry all')
        return

    with state_lock:
        completed_preview_frames[sip] = frame_seq
        preview_published_at[sip] = time.time()
        preview_image_cache[sip] = published
        preview_last_errors.pop(sip, None)
        previews.pop(sip, None)
    logger.info('[Preview] %s frame=%d 接收完成并已发布 total=%d cached=%s',
                sip, frame_seq, total, True)



def handle_mess(d, sip, sp, via='unknown'):
    """解析学生端发来的 MESS 消息包（聊天/提示类）。"""
    # 任何 MESS 来源都算在线信号，畸形包也要刷新 last_seen。
    _mark_student_seen(sip, 'MESS', via)
    if len(d) < 12:
        logger.warning('[MESS] 包过短（%d 字节）from %s:%d via %s', len(d), sip, sp, via)
        return

    try:
        magic, sender_id, rcpt_count = struct.unpack('<III', d[:12])
        if rcpt_count > 64:
            logger.warning('[MESS] 接收者数量无效 from %s:%d (rcpt_count=%d)', sip, sp, rcpt_count)
            return
        header_len = 12 + 4 * rcpt_count
        if len(d) < header_len:
            logger.warning('[MESS] 头长度不足 from %s:%d (rcpt_count=%d)', sip, sp, rcpt_count)
            return
        payload = d[header_len:]
    except struct.error as e:
        logger.error('[MESS] 解包失败 from %s:%d：%s', sip, sp, e)
        return

    logger.info('[MESS] RECV from %s:%d via %s, sender_id=0x%08X, rcpt_count=%d, payload_len=%d',
                sip, sp, via, sender_id, rcpt_count, len(payload))
    logger.debug('[MESS] payload hex\n%s', hexdump(payload[:256]))

    text = None
    msg_kind = 'unknown'
    # 去重键：区分消息类别/子类型，避免交替消息绕过相邻去重
    dedupe_key = None
    msg_type = struct.unpack('<I', payload[4:8])[0] if len(payload) >= 8 else 0
    category = struct.unpack('<I', payload[8:12])[0] if len(payload) >= 12 else 0
    subtype = struct.unpack('<I', payload[12:16])[0] if len(payload) >= 16 else 0

    # IDA 中聊天消息负载结构：
    # [0..3]=总长, [4..7]=0x800, [8..11]=0, [12..15]=1, [16..]=UTF-16-LE 字符串
    if len(payload) >= 16 and msg_type == 0x800:
        dedupe_key = 'chat'
        try:
            raw = payload[16:].rstrip(b'\x00')
            if len(raw) % 2:
                raw = raw[:-1]
            text = raw.decode('utf-16-le')
            msg_kind = 'chat'
        except Exception as e:
            logger.debug('[MESS] 聊天消息 UTF-16-LE 解码失败：%s', e)

    elif len(payload) >= 24 and msg_type == 0:
        dedupe_key = f'{category:#010x}/{subtype}'
        extra = struct.unpack('<I', payload[20:24])[0]
        if category == 0x800000:
            # 信息上报（request_info 0x100000 的回复）：
            # [12..15]: 5=系统信息 6=窗口列表(分片) 7=进程列表(分片)
            if subtype == 5:
                if len(payload) >= 0x2E0:
                    try:
                        info = _parse_student_info(payload, sip)
                        text = (f"[学生信息] 计算机名={info['name']} 用户={info['user']} "
                                f"MAC={info['mac']} OS={info['os']} {info['osver']} "
                                f"CPU={info['cpu_vendor']}/{info['cpu_model']} 内存={info['mem']}")
                        msg_kind = 'status'
                    except Exception as e:
                        logger.debug('[MESS] 学生信息解析失败：%s', e)
                else:
                    logger.debug('[MESS] type 5 学生信息长度不足: %d', len(payload))
            elif subtype in (6, 7):
                # [16..19]=分片标志(1=首片), [20..]={u32 id, wchar name\0} 序列
                # type 6=窗口/应用程序列表(hwnd+标题), type 7=进程列表(pid+exe名)
                chunk_flag = struct.unpack('<I', payload[16:20])[0]
                entries = _parse_id_name_pairs(payload[20:])
                store_key = 'windows' if subtype == 6 else 'processes'
                with state_lock:
                    entry = students.get(sip)
                    if entry is not None:
                        if chunk_flag == 1 or store_key not in entry:
                            entry[store_key] = []
                        existing = entry[store_key]
                        seen = set(existing)
                        for item in entries:
                            if item not in seen:
                                seen.add(item)
                                existing.append(item)
                        total = len(existing)
                    else:
                        total = len(entries)
                kind = '窗口' if subtype == 6 else '进程'
                names = '，'.join(n for _, n in entries[:6])
                text = (f'[{kind}列表{"首片" if chunk_flag == 1 else "续片"}] '
                        f'本片 {len(entries)} 个，累计 {total} 个：{names}'
                        + ('…' if len(entries) > 6 else ''))
                msg_kind = 'status'
                logger.debug('[MESS] %s列表完整分片: %s', kind,
                             '，'.join(f'{p}:{n}' for p, n in entries))
            else:
                logger.debug('[MESS] 未知信息上报子类型 %d', subtype)
        else:
            # 状态消息（category=3 等）：
            # [12..15]=子类型, [16..19]=字符串最大长度, [20..23]=PID/计数/额外数据, [24..]=UTF-16-LE 字符串
            if subtype == 6:
                try:
                    raw = payload[24:].rstrip(b'\x00')
                    if len(raw) % 2:
                        raw = raw[:-1]
                    title = raw.decode('utf-16-le')
                    text = f'[窗口标题] {title}'
                    msg_kind = 'status'
                except Exception as e:
                    logger.debug('[MESS] 窗口标题解码失败：%s', e)
            elif subtype == 7:
                # sub_43B080：调用 Wlanapi 获取可用 WiFi 网络数量，-1 表示检测失败
                count = extra if extra != 0xFFFFFFFF else -1
                text = f'[WiFi可用网络数量] {count}'
                msg_kind = 'status'
            elif subtype == 1:
                text = f'[IE/浏览器URL信息] extra=0x{extra:08X}'
                msg_kind = 'status'
            elif subtype == 0:
                text = f'[窗口标题清空/PID=0x{extra:08X}]'
                msg_kind = 'status'
            elif subtype == 3:
                text = '[系统性能/进程信息]'
                msg_kind = 'status'
            else:
                logger.debug('[MESS] 未知状态子类型 %d (category=%#x)', subtype, category)

    if text:
        if msg_kind == 'chat':
            logger.info('[MESS] 来自 %s:%d 的聊天消息：%s', sip, sp, text)
            gui_events.chat_events.publish(sip, text)
        elif last_status.get((sip, dedupe_key)) == text:
            # 内容无变化的同类消息（周期性窗口标题/WiFi/列表分片）只记 DEBUG
            logger.debug('[MESS] 来自 %s:%d 的状态消息(重复)：%s', sip, sp, text)
        else:
            last_status[(sip, dedupe_key)] = text
            logger.info('[MESS] 来自 %s:%d 的状态消息：%s', sip, sp, text)
    else:
        key = f'<未解析 type=0x{msg_type:08X} len={len(payload)}>'
        if last_status.get((sip, key)) == payload[:64]:
            logger.debug('[MESS] 来自 %s:%d 的消息无法解析文本(重复)', sip, sp)
        else:
            last_status[(sip, key)] = payload[:64]
            logger.info('[MESS] 来自 %s:%d 的消息无法解析文本，payload_len=%d, msg_type=0x%08X',
                        sip, sp, len(payload), msg_type)


def broadcast():
    logger.info('[Broadcast] 启动 session_id=%s generation=%d', session_id, generation)
    first_cycle = True
    cycle = 0
    total_oonc = total_nanc = total_canc = 0
    total_failures = 0
    while running and not network_stop_event.is_set():
        cycle += 1
        try:
            oonc_packet = oonc()
            oonc_sent, oonc_failed = send_to_targets(
                sock, oonc_packet, MAIN_ANNOUNCE_TARGETS, 'OONC')
            normal_packet = nanc()
            auto_packet = canc()
            nanc_sent, nanc_failed = send_to_targets(
                sock, normal_packet, MAIN_ANNOUNCE_TARGETS, 'NANC')
            canc_sent, canc_failed = send_to_targets(
                sock, auto_packet, MAIN_ANNOUNCE_TARGETS, 'CANC')
            total_oonc += oonc_sent
            total_nanc += nanc_sent
            total_canc += canc_sent
            total_failures += oonc_failed + nanc_failed + canc_failed
            if first_cycle:
                targets = ', '.join(f'{host}:{port}'
                                    for host, port in MAIN_ANNOUNCE_TARGETS)
                logger.info(
                    '[Broadcast] 首轮发送完成：OONC len=%d sent=%d；'
                    'NANC len=%d sent=%d；CANC len=%d mask=0x%08X sent=%d；'
                    'targets=%s',
                    len(oonc_packet), oonc_sent, len(normal_packet), nanc_sent,
                    len(auto_packet), 1 << (CHANNEL_ID - 1), canc_sent, targets)
                first_cycle = False
            if cycle % ANNOUNCE_INFO_CYCLES == 0:
                logger.info(
                    '[Broadcast] 发包计数 cycles=%d OONC=%d NANC=%d CANC=%d '
                    'failures=%d generation=%d oonc_seq=%d session_id=%s',
                    cycle, total_oonc, total_nanc, total_canc, total_failures,
                    generation, oonc_seq, session_id)
        except Exception as error:
            total_failures += 1
            logger.warning('[Broadcast] 瞬时发送错误，继续下一轮：%s', error)
        if _sleep_or_stop(0.5):
            break
    logger.info('[Broadcast] 退出 cycles=%d OONC=%d NANC=%d CANC=%d failures=%d',
                cycle, total_oonc, total_nanc, total_canc, total_failures)


def session_anno():
    logger.info('[Session] 广播线程启动 session_id=%s generation=%d',
                session_id, generation)
    first_cycle = True
    cycle = 0
    total_type1 = total_type2 = total_failures = 0
    while running and not network_stop_event.is_set():
        cycle += 1
        try:
            pkt1 = struct.pack('<II', 0x4F4E4E41, 1)
            type1_sent, type1_failed = send_to_targets(
                sock2, pkt1, SESSION_ANNOUNCE_TARGETS, 'ANNO(type1)')
            pkt2 = (struct.pack('<III', 0x4F4E4E41, 1, 1)
                    + b'\x00'*8
                    + socket.inet_aton(ip)
                    + struct.pack('<I', 0x0D5AD030)
                    + b'\x00'*4
                    + struct.pack('<I', 0x0D5AD030)
                    + struct.pack('<I', 1)
                    + b'\x00'*32)
            type2_sent, type2_failed = send_to_targets(
                sock2, pkt2, SESSION_ANNOUNCE_TARGETS, 'ANNO(type2)')
            total_type1 += type1_sent
            total_type2 += type2_sent
            total_failures += type1_failed + type2_failed
            if first_cycle:
                targets = ', '.join(f'{host}:{port}'
                                    for host, port in SESSION_ANNOUNCE_TARGETS)
                logger.info(
                    '[Session] 首轮发送完成：ANNO(type1) len=%d sent=%d；'
                    'ANNO(type2) len=%d sent=%d；targets=%s',
                    len(pkt1), type1_sent, len(pkt2), type2_sent, targets)
                first_cycle = False
            if cycle % ANNOUNCE_INFO_CYCLES == 0:
                logger.info(
                    '[Session] 发包计数 cycles=%d ANNO1=%d ANNO2=%d '
                    'failures=%d generation=%d oonc_seq=%d session_id=%s',
                    cycle, total_type1, total_type2, total_failures,
                    generation, oonc_seq, session_id)
        except Exception as error:
            total_failures += 1
            logger.warning('[Session] 瞬时广播错误，继续下一轮：%s', error)
        if _sleep_or_stop(0.5):
            break
    logger.info('[Session] 广播线程退出 cycles=%d ANNO1=%d ANNO2=%d failures=%d',
                cycle, total_type1, total_type2, total_failures)


def build_session_reply(recipient_ip, msg_type):
    """构造教师端会话回复，目标地址同时写入 MESS 接收者字段。"""
    if msg_type == 0x1000:
        payload = struct.pack('<III', 0x0D, 0x1000, 0)
        payload += b'\x00'
    elif msg_type == 0x8000:
        # 连续桌面观看需要 TCPMode=1；均可通过环境变量覆盖。
        # 尾部状态值来自已验证样本；总长度严格保持 0x1B。
        payload = struct.pack('<III', 0x1B, 0x8000, 0)
        payload += struct.pack('<IH', TCP_COMM_MODE, TCP_COMM_PORT)
        payload += b'\x00' * 4
        payload += struct.pack('<I', 0x270034B0)
        payload += b'\x00'
    else:
        raise ValueError(f'不支持的会话回复类型：0x{msg_type:08X}')

    if len(payload) != struct.unpack_from('<I', payload)[0]:
        raise AssertionError('会话回复的声明长度与实际长度不一致')
    return (struct.pack('<III', 0x5353454D, 1, 1)
            + socket.inet_aton(recipient_ip)
            + payload)


def handle_student_anno(d, sip, via='unknown'):
    """解析学生端单播的 64 字节课堂状态块（0x41A590 / 0x43D870）。"""
    _mark_student_seen(sip, 'ANNO', via)
    if len(d) != 72:
        return False
    fields = struct.unpack_from('<16I', d, 8)
    state = {
        'blackscreen_flags': fields[1],
        'student_flags': fields[2],
        'hand_up': bool(fields[2] & 0x100000),
        'student_demo': bool(fields[0] & 0x04),
        'raw': fields,
    }
    with state_lock:
        entry = students.get(sip)
        if entry is None:
            return False
        previous = entry.get('anno_state')
        entry['anno_state'] = state
    if previous != state:
        logger.info('[StudentState] %s via=%s hand_up=%s flags=%#010x lock=%#010x raw=%s',
                    sip, via, state['hand_up'], state['student_flags'],
                    state['blackscreen_flags'], ' '.join(f'{v:08x}' for v in fields))
    return True


def session_recv():
    logger.info('[SessionRecv] 启动')
    while running and not network_stop_event.is_set():
        if sock2 is None:
            break
        try:
            d, a = sock2.recvfrom(4096)
            sip, sp = a

            # 忽略本机发出的 ANNO 回包
            if sip == ip:
                continue

            if len(d) < 4:
                logger.warning('[SessionRecv] 包过短（%d 字节）from %s:%d', len(d), sip, sp)
                continue

            mag = struct.unpack('<I', d[:4])[0]

            if mag == 0x49474F4C:  # LOGI
                with state_lock:
                    entry = students.get(sip)
                    already_logged_in = bool(entry and entry.get('logged_in'))
                _mark_student_seen(sip, 'LOGI', 'SessionRecv', logged_in=True)
                with state_lock:
                    preserved_mac = students.get(sip, {}).get('info', {}).get('mac', '')
                log = logger.debug if already_logged_in else logger.info
                log('[Login] %s 保留已有 info/mac=%s', sip, preserved_mac or '-')
                log('[SessionRecv] LOGI from %s:%d%s', sip, sp,
                    '（周期重复）' if already_logged_in else '')

                mess1 = build_session_reply(sip, 0x1000)
                if not _send_session(mess1, (sip, SPORT), 'SessionReply 0x1000'):
                    logger.warning('[SessionRecv] 0x1000 回复未送达 %s', sip)
                log('[MESS] type 0x1000 -> %s:%d, len=%d', sip, SPORT, len(mess1))
                if _sleep_or_stop(0.05):
                    break

                mess2 = build_session_reply(sip, 0x8000)
                if not _send_session(mess2, (sip, SPORT), 'SessionReply 0x8000'):
                    logger.warning('[SessionRecv] 0x8000 回复未送达 %s', sip)
                log('[MESS] type 0x8000 -> %s:%d, len=%d', sip, SPORT, len(mess2))
                if _sleep_or_stop(0.05):
                    break

                if already_logged_in:
                    continue

                _send_preview_policy(sip, True, 'LOGI', count=2)
                logger.info('[Login] %s 登录成功，students=%s', sip, list(students.keys()))
                request_info(sip)
                _ensure_preview_keepalive(sip)

            elif mag == 0x5353454D:  # MESS
                handle_mess(d, sip, sp, 'SessionRecv')

            elif mag == 0x4F4E4E41:  # ANNO
                handle_student_anno(d, sip, 'SessionRecv')

            elif mag == 0x4F474F4C:  # LOGO
                logger.info('[SessionRecv] %s from %s:%d', magic_name(mag), sip, sp)
                _handle_student_logout(sip, 'SessionRecv')

            elif mag == 0x434D5254:  # TRMC
                _handle_trmc(d, sip, 'SessionRecv')

            elif mag == 0x544E5254:  # TRNT
                _handle_trnt(d, sip, 'SessionRecv')

            elif mag in CLIENT_PACKET_MAGICS:
                _handle_client_packet(mag, d, sip, 'SessionRecv')

            elif mag not in ROUTINE_MAGICS:
                logger.warning(
                    '[SessionRecv] 未认证/非登录包 %s from %s:%d, len=%d\n%s',
                    magic_name(mag), sip, sp, len(d), hexdump(d[:256]))

        except socket.timeout:
            if network_stop_event.is_set():
                break
            continue
        except Exception as error:
            if running and not network_stop_event.is_set():
                logger.error('[SessionRecv] 异常：%s', error, exc_info=True)
            else:
                break
    logger.info('[SessionRecv] 退出')


def build_rrms(request, accept):
    """构造 QRMS 对应的 52 字节 RRMS 审批包。"""
    if not isinstance(request, dict):
        raise ValueError('RRMS 需要 QRMS 请求字典')
    try:
        transaction_guid = bytes.fromhex(request['transaction_guid'])
        student_id = request['fields'][0]
        total_size = request['total_size']
        file_count = request['file_count']
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError('QRMS 请求缺少 RRMS 所需字段') from error
    if len(transaction_guid) != 16:
        raise ValueError('QRMS 事务 GUID 必须是 16 字节')
    values = (student_id, 1 if accept else 0, 1, total_size, file_count)
    limits = (0xFFFFFFFF, 1, 1, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFF)
    if any(not isinstance(value, int) or isinstance(value, bool)
           or not 0 <= value <= maximum
           for value, maximum in zip(values, limits)):
        raise ValueError('RRMS 字段超出协议范围')
    quota_low = total_size & 0xFFFFFFFF
    quota_high = total_size >> 32
    packet = (struct.pack('<III', 0x534D5252, 0x10000, 0x18)
              + transaction_guid
              + struct.pack('<6I', student_id, 1 if accept else 0, 1,
                            quota_low, quota_high, file_count))
    if len(packet) != 52:
        raise AssertionError('RRMS 长度错误')
    return packet


def handle_submit_request(d, sip):
    """解析 QRMS 文件提交请求（LibBaseTrans 0x100031B0）。"""
    if len(d) != 0x284 or sip not in students:
        return False
    transaction_guid = d[12:28].hex()
    fields = struct.unpack_from('<8I', d, 28)
    directory = d[60:124].decode('utf-16-le', errors='replace').split('\x00')[0]
    file_list = d[124:644].decode('utf-16-le', errors='replace').split('\x00')[0]
    total_size = fields[5] | (fields[6] << 32)
    request = {
        'transaction_guid': transaction_guid,
        'directory': directory,
        'file_list': file_list,
        'file_count': fields[7],
        'total_size': total_size,
        'fields': fields,
        'student_id': fields[0],
        'status': 'pending',
    }
    previous = students[sip].get('submit_request')
    students[sip]['submit_request'] = request
    logger.info('[FileSubmit] %s guid=%s files=%d bytes=%d directory=%s list=%s fields=%s '
                'status=pending replaces=%s',
                sip, transaction_guid, fields[7], total_size, directory, file_list, fields,
                previous['transaction_guid'] if previous else 'none')
    return True


def _submission_detail(details, *names, default=''):
    for name in names:
        value = details.get(name)
        if value is not None:
            return value
    return default


def _submission_number(details, *names):
    for name in names:
        value = details.get(name)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value, 0)
            except ValueError:
                pass
    return 0


def _submission_address(address):
    if isinstance(address, (tuple, list)):
        host = str(address[0]) if address else '-'
        try:
            port = int(address[1]) if len(address) > 1 else None
        except (TypeError, ValueError):
            port = None
        return host, port
    text = str(address or '-')
    if text.count(':') == 1:
        host, separator, port_text = text.rpartition(':')
        if separator:
            try:
                return host, int(port_text)
            except ValueError:
                pass
    return text, None


def _safe_submission_component(value):
    allowed = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-')
    return ''.join(char if char in allowed else '_'
                   for char in str(value))[:64] or 'unknown'


def _submission_root():
    return os.path.realpath(SUBMISSION_DIR)


def submission_service_info():
    """返回当前文件接收服务配置，供界面显示。"""
    with submission_lock:
        return {
            'configured_port': SUBMISSION_PORT,
            'listen_port': submission_listen_port,
            'directory': _submission_root(),
            'running': submission_server is not None,
        }


def get_submission_receipts(sip):
    """返回指定学生最近完成的本地接收记录副本。"""
    with submission_lock:
        return list(submission_receipts.get(sip, ()))


def _publish_submission_event(event):
    try:
        gui_events.submission_events.publish(event)
    except Exception as error:
        logger.warning('[FileSubmit][MiniMedia] GUI 事件桥接失败 kind=%s student=%s error=%s',
                       event.get('kind'), event.get('student_ip'), error, exc_info=True)


def _register_submission_upload(kind, student_ip, client_port, name, details):
    normalized_name = (name or '').casefold()
    identity = (student_ip, client_port or 0)
    with submission_lock:
        if kind == 'started':
            conflict = None
            if normalized_name:
                for key in submission_active_uploads:
                    if (key[2] == normalized_name
                            and (key[0], key[1]) != identity):
                        conflict = key
                        break
            if conflict is not None:
                raise ValueError(f'同名文件正在接收，拒绝覆盖：{name}')
            transaction = submission_transactions.get(student_ip)
            submission_active_uploads[identity + (normalized_name,)] = {
                'name': name,
                'transaction': transaction,
                'size': _submission_number(details, 'size', 'total_size'),
            }
            return transaction
        if kind in ('completed', 'error'):
            matching = [key for key in submission_active_uploads
                        if key[0] == identity[0] and key[1] == identity[1]]
            transaction = None
            for key in matching:
                active = submission_active_uploads.pop(key, None)
                if active:
                    transaction = active.get('transaction')
            return transaction or submission_transactions.get(student_ip)
        return submission_transactions.get(student_ip)


def _next_submission_directory(student_ip, transaction, suffix):
    if transaction and transaction.get('directory'):
        return transaction['directory']
    stamp = time.strftime('%Y%m%d-%H%M%S')
    guid = _safe_submission_component(
        (transaction or {}).get('transaction_guid', 'unassigned'))[:16]
    return os.path.join(_submission_root(), _safe_submission_component(student_ip),
                        f'{stamp}-{guid}-{suffix}')


def _submission_unique_path(directory, name):
    filename = os.path.basename(str(name).replace('\\', '/')) or 'received.bin'
    if filename in ('', '.', '..'):
        filename = 'received.bin'
    stem, extension = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    index = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f'{stem}_{index}{extension}')
        index += 1
    return candidate


def _archive_submission_file(student_ip, name, source_path, transaction, byte_count, size):
    global submission_receipt_sequence
    final_path = source_path
    if source_path:
        try:
            root = os.path.normcase(_submission_root())
            absolute_source = os.path.normcase(os.path.realpath(source_path))
            if os.path.commonpath((root, absolute_source)) != root:
                raise ValueError(f'接收文件不在 submissions 根目录：{source_path}')
            if os.path.isfile(source_path):
                with submission_lock:
                    submission_receipt_sequence += 1
                    sequence = submission_receipt_sequence
                directory = _next_submission_directory(
                    student_ip, transaction, f'{sequence:06d}')
                os.makedirs(directory, exist_ok=True)
                target = _submission_unique_path(directory, name or os.path.basename(source_path))
                os.replace(source_path, target)
                final_path = target
        except Exception as error:
            logger.error('[FileSubmit][MiniMedia] 接收文件归档失败 student=%s file=%s '
                         'source=%s error=%s', student_ip, name, source_path, error,
                         exc_info=True)
            return final_path, str(error)
    with submission_lock:
        submission_receipt_sequence += 1
        sequence = submission_receipt_sequence
        receipt = {
            'sequence': sequence,
            'student_ip': student_ip,
            'file': name,
            'path': final_path,
            'bytes': byte_count,
            'size': size,
            'transaction_guid': (transaction or {}).get('transaction_guid', ''),
        }
        entries = submission_receipts.setdefault(student_ip, [])
        entries.append(receipt)
        del entries[:-20]
    return final_path, None


def _submission_event(kind, address, details):
    """把 MiniMediaServer 的后台线程事件写入日志并桥接到 GUI 线程。"""
    event_kind = str(kind)
    try:
        event_details = dict(details or {})
    except (TypeError, ValueError):
        event_details = {'raw': repr(details)}
    student_ip, client_port = _submission_address(address)
    source_path = str(_submission_detail(event_details, 'path', 'target', 'destination'))
    name = str(_submission_detail(event_details, 'name', 'file', 'filename', 'file_name'))
    if not name and source_path:
        name = os.path.basename(source_path.replace('\\', '/'))
    size = _submission_number(event_details, 'size', 'total_size', 'bytes_total', 'total')
    byte_count = _submission_number(event_details, 'received', 'bytes', 'byte_count',
                                    'bytes_received')
    if event_kind in ('progress', 'completed') and not byte_count:
        byte_count = size
    error = str(_submission_detail(event_details, 'error', 'message', default=''))
    try:
        transaction = _register_submission_upload(
            event_kind, student_ip, client_port, name, event_details)
    except ValueError as conflict:
        logger.error('[FileSubmit][MiniMedia] kind=started student=%s address=%s file=%s '
                     'bytes=%d/%d path=%s error=%s',
                     student_ip, address, name or '-', byte_count, size,
                     source_path or '-', conflict)
        _publish_submission_event({
            'kind': 'error', 'student_ip': student_ip, 'address': str(address),
            'file': name or '-', 'path': source_path or '-', 'bytes': byte_count,
            'size': size, 'error': str(conflict), 'transaction_guid': '',
        })
        raise
    final_path = source_path
    if event_kind == 'completed':
        final_path, archive_error = _archive_submission_file(
            student_ip, name, source_path, transaction, byte_count, size)
        if archive_error:
            event_kind = 'error'
            error = error or archive_error
    event = {
        'kind': event_kind,
        'student_ip': student_ip,
        'address': str(address),
        'file': name or '-',
        'path': final_path or '-',
        'bytes': byte_count,
        'size': size,
        'error': error or '-',
        'transaction_guid': (transaction or {}).get('transaction_guid', ''),
    }
    if event_kind == 'error' or error:
        logger.error('[FileSubmit][MiniMedia] kind=%s student=%s address=%s file=%s '
                     'bytes=%d/%d path=%s error=%s',
                     event_kind, student_ip, address, event['file'], byte_count, size,
                     event['path'], event['error'])
    else:
        logger.info('[FileSubmit][MiniMedia] kind=%s student=%s address=%s file=%s '
                    'bytes=%d/%d path=%s error=%s',
                    event_kind, student_ip, address, event['file'], byte_count, size,
                    event['path'], event['error'])
    _publish_submission_event(event)


def _ensure_submission_server():
    """按配置端口惰性启动唯一的 MiniMediaServer；0 表示不监听。"""
    global submission_server, submission_listen_port
    if not SUBMISSION_PORT:
        return 0
    with submission_lock:
        if submission_server is not None:
            if submission_listen_port != SUBMISSION_PORT:
                raise RuntimeError(
                    f'文件接收服务已在端口 {submission_listen_port} 运行；'
                    f'端口 {SUBMISSION_PORT} 需重启教师端后生效')
            return submission_listen_port
        from minimedia_server import MiniMediaServer
        directory = _submission_root()
        os.makedirs(directory, exist_ok=True)
        server = MiniMediaServer(ip, SUBMISSION_PORT, directory,
                                 event_handler=_submission_event,
                                 maximum=SUBMISSION_MAX_BYTES)
        try:
            actual_port = server.start()
        except Exception:
            try:
                server.close()
            except Exception:
                pass
            logger.exception('[FileSubmit][MiniMedia] 启动失败 bind=%s:%d directory=%s；'
                             '保留 pending', ip, SUBMISSION_PORT, directory)
            raise
        submission_server = server
        submission_listen_port = int(actual_port)
        logger.info('[FileSubmit][MiniMedia] 单服务已启动 bind=%s:%d directory=%s '
                    'maximum=%d；仅用于独立模拟工具联调',
                    ip, submission_listen_port, directory, SUBMISSION_MAX_BYTES)
        return submission_listen_port


def _prepare_submission_transaction(sip, request):
    global submission_receipt_sequence
    with submission_lock:
        submission_receipt_sequence += 1
        sequence = submission_receipt_sequence
        guid = _safe_submission_component(request.get('transaction_guid', 'unknown'))
        directory = os.path.join(
            _submission_root(), _safe_submission_component(sip),
            f'{time.strftime("%Y%m%d-%H%M%S")}-{guid[:12]}-{sequence:06d}')
        os.makedirs(directory, exist_ok=True)
        submission_transactions[sip] = {
            'student_ip': sip,
            'transaction_guid': request.get('transaction_guid', ''),
            'directory': directory,
            'created_at': time.time(),
        }
        return directory


def respond_submit_request(sip, accept):
    """对待审批 QRMS 启动接收服务（按需）并发送 RRMS；成功后才更新状态。"""
    request = students.get(sip, {}).get('submit_request')
    if request is None:
        raise ValueError(f'{sip} 没有文件提交请求')
    if request.get('status') != 'pending':
        raise ValueError(f'{sip} 的文件提交请求已审批，不能重复操作')
    packet = build_rrms(request, accept)
    listen_port = 0
    transaction_directory = None
    if accept and SUBMISSION_PORT:
        try:
            listen_port = _ensure_submission_server()
            transaction_directory = _prepare_submission_transaction(sip, request)
        except Exception as error:
            logger.exception('[FileSubmit] 接收服务未就绪 sip=%s guid=%s port=%d；保留 pending',
                             sip, request['transaction_guid'], SUBMISSION_PORT)
            raise RuntimeError(f'文件接收服务启动失败，RRMS 未发送：{error}') from error
    if not _send_main(packet, (sip, PORT), 'RRMS'):
        logger.error('[FileSubmit] RRMS 发送失败 sip=%s guid=%s accept=%s；保留 pending',
                     sip, request['transaction_guid'], bool(accept))
        raise OSError('RRMS 发送失败')
    request['status'] = 'approved' if accept else 'rejected'
    request['submission_port'] = listen_port if accept else 0
    request['submission_directory'] = transaction_directory if accept else None
    if listen_port:
        logger.info('[FileSubmit] RRMS -> %s:%d guid=%s status=%s student_id=%d '
                    'accept=%d arg2=1 arg3=1 quota=%d max_files=%d；'
                    '接收服务=%s:%d directory=%s（RRMS 本身不含文件内容）',
                    sip, PORT, request['transaction_guid'], request['status'],
                    request['student_id'], 1 if accept else 0,
                    request['total_size'], request['file_count'],
                    ip, listen_port, transaction_directory)
    else:
        logger.info('[FileSubmit] RRMS -> %s:%d guid=%s status=%s student_id=%d '
                    'accept=%d arg2=1 arg3=1 quota=%d max_files=%d；'
                    '未配置文件接收端口或已拒绝，仅完成审批',
                    sip, PORT, request['transaction_guid'], request['status'],
                    request['student_id'], 1 if accept else 0,
                    request['total_size'], request['file_count'])
    return request


def main_recv():
    logger.info('[MainRecv] 启动')
    while running and not network_stop_event.is_set():
        if sock is None:
            break
        try:
            d, a = sock.recvfrom(4096)
            sip, sp = a

            # 过滤本机广播
            if sip == ip:
                continue

            if len(d) < 4:
                logger.warning('[MainRecv] 包过短（%d 字节）from %s:%d', len(d), sip, sp)
                continue

            mag = struct.unpack('<I', d[:4])[0]

            # ANNO 虽属日常广播，但任意来源都要更新 last_seen。
            if mag == 0x4F4E4E41:
                handle_student_anno(d, sip, 'MainRecv')
                continue
            if mag in ROUTINE_MAGICS:
                continue

            if sip not in students:
                logger.warning('[MainRecv] 未登录学生 %s:%d 发送 %s',
                               sip, sp, magic_name(mag))

            if mag in (0x434D5254, 0x544E5254):
                logger.debug('[MainRecv] %s from %s:%d, len=%d',
                             magic_name(mag), sip, sp, len(d))
            else:
                logger.info('[MainRecv] %s from %s:%d, len=%d',
                            magic_name(mag), sip, sp, len(d))

            if mag == 0x4143414B:  # KACA
                logger.info('[MainRecv] KACA %s -> WACA', sip)
                _send_main(waca(sip), (sip, PORT), 'WACA')

            elif mag == 0x434D5254:  # TRMC
                _handle_trmc(d, sip, 'MainRecv')

            elif mag == 0x544E5254:  # TRNT
                _handle_trnt(d, sip, 'MainRecv')

            elif mag == 0x544E4544:  # DENT
                if len(d) < 40:
                    logger.warning('[MainRecv] DENT 包过短：%d from %s', len(d), sip)
                    continue
                frame_seq = struct.unpack('<I', d[36:40])[0]
                _expire_preview_frames()
                with state_lock:
                    state = previews.get(sip)
                    published_frame = completed_preview_frames.get(sip)
                if state and state['frame_seq'] == frame_seq:
                    missing = _preview_missing_parts(state)
                    missing_offsets = [item[0] for item in _preview_missing_ranges(state)]
                    pkt = build_srnt(frame_seq, complete=not missing,
                                     missing_parts=missing)
                    action = 'complete' if not missing else f'retry parts={missing}'
                    logger.info('[Preview] %s DENT frame=%d got=%d/%d '
                                'missing_offsets=%s missing_parts=%s -> SRNT %s',
                                sip, frame_seq, state['got'], state['total'],
                                missing_offsets, missing, action)
                elif published_frame == frame_seq:
                    pkt = build_srnt(frame_seq, complete=True)
                    action = 'complete'
                    logger.info('[Preview] %s DENT frame=%d -> SRNT complete（已发布）',
                                sip, frame_seq)
                else:
                    pkt = build_srnt(frame_seq, complete=False, missing_parts=None)
                    action = 'retry all'
                    logger.info('[Preview] %s DENT frame=%d -> SRNT retry all（无缓存帧）',
                                sip, frame_seq)
                _send_main(pkt, (sip, PORT), 'Preview SRNT')

            elif mag == 0x544E414C:  # LANT
                handle_tnal(d, sip)

            elif mag == 0x5353454D:  # MESS
                handle_mess(d, sip, sp, 'MainRecv')

            elif mag == 0x4F474F4C:  # LOGO
                logger.info('[MainRecv] %s from %s:%d', magic_name(mag), sip, sp)
                _handle_student_logout(sip, 'MainRecv')

            elif mag == 0x534D5251:  # QRMS
                handle_submit_request(d, sip)

            elif mag in CLIENT_PACKET_MAGICS:
                _handle_client_packet(mag, d, sip, 'MainRecv')

            else:
                logger.warning('[MainRecv] 未知包 %s from %s:%d, len=%d\n%s',
                               hex(mag), sip, sp, len(d), hexdump(d[:256]))

        except socket.timeout:
            if network_stop_event.is_set():
                break
            continue
        except Exception as error:
            if running and not network_stop_event.is_set():
                logger.error('[MainRecv] 异常：%s', error, exc_info=True)
            else:
                break
    logger.info('[MainRecv] 退出')


# -------------------- 命令行交互 --------------------

def _parse_lock_text(rest):
    """从 bs/bsperm/bsall 的原始剩余字符串解析 lock 标志和 text。

    rest 为 ip 之后的整段字符串（command_loop 以 maxsplit=2 切分）：
      '' / '0' / '1'       → 仅 lock 标志
      '0 消息' / '1 消息'  → lock + text
      '消息'               → lock=True + text
    """
    lock, text = True, None
    if rest:
        rest = rest.strip()
        if rest in ('0', '1'):
            lock = (rest == '1')
        elif rest[:2] in ('0 ', '1 '):
            lock = (rest[0] == '1')
            text = rest[2:].strip() or None
        else:
            text = rest
    return lock, text


def _parse_delay_text(rest):
    """解析 shutdown/reboot 的 '[倒计时秒数] [提示文字]'。

      ''          → (0, None)
      '30'        → (30, None)
      '30 请保存'  → (30, '请保存')
      '请保存'     → (0, '请保存')
    """
    delay, text = 0, None
    if rest:
        parts = rest.strip().split(maxsplit=1)
        if parts[0].isdigit():
            delay = int(parts[0])
            text = parts[1] if len(parts) > 1 else None
        else:
            text = rest.strip()
    return delay, text


def cmd_help():
    print('''可用命令：
  help / ?              显示帮助
  list / ls             列出已登录学生
  preview <ip>          请求指定学生的屏幕预览
  view_probe <ip> [port]  仅探测学生 TCP 观看端口，不发送观看请求
  view <ip> [port]      连续观看学生屏幕（V6 TCP/UMSP，默认 4806）
  view_stop <ip>        停止连续观看
  control <ip> [port]   打开交互式远程控制窗口（默认随机高位 UDP 端口）
  control_stop <ip>     停止远程控制
  mouse <ip> <动作> <x> <y> [data]  发送鼠标事件，坐标范围 0..65535
  key <ip> <vk> [press|down|up] [scan] [extended]  发送键盘事件
  all                   请求所有学生的屏幕预览
  msg <ip> <text>       向指定学生发送聊天消息
  info <ip> [0|1|2]     请求学生上报信息（0=全部 1=窗口列表 2=进程列表，登录后自动请求一次）
  ps <ip>               显示学生进程列表（先 info 请求过）
  wins <ip>             显示学生窗口列表（先 info 请求过）
  kill <ip> <pid|进程名> [f]   结束学生进程（f=1 强杀；f=0 先试 WM_CLOSE）
  closeapp <ip> <hwnd|标题关键字> [f]  结束学生应用程序（按窗口句柄或标题）
  openurl <ip> <网址|路径>   在学生机打开网页/文件（ShellExecute）
  run <ip> <路径> [参数] [show]  远程运行程序（show: 0=正常 1=最小化 2=最大化，路径含空格用引号）
  setchannel <ip> <1..32> [0|1]  实验性远程频道设置（COMD 0x4000/subcase 7；不改变教师端频道）
  blackscreen / bs <ip> [lock=1|0] [text]   向指定学生发送黑屏安静（默认锁键鼠，10秒自动解锁）
  bsperm / bsp <ip> [lock=1|0] [text]       向指定学生发送永久黑屏安静（需手动 unlock）
  unlock <ip>           解锁指定学生的黑屏/键盘鼠标锁
  bsall [lock=1|0] [text]  对所有已登录学生发送黑屏安静
  unlock_all            对所有已登录学生发送解锁
  shutdown / sd <ip> [秒] [text]   关闭指定学生机（不带秒数=立即强制；带秒数=倒计时提示）
  reboot / rb <ip> [秒] [text]     重启指定学生机（参数同 shutdown）
  debug on / off        切换文件日志级别（默认 INFO，on=DEBUG 会详细记录并占空间）
  exit / quit / q       退出程序

  例：
    bs 192.168.2.139              黑屏 + 锁键鼠，10秒自动解
    bs 192.168.2.139 0            只黑屏不锁键鼠
    bs 192.168.2.139 1 请认真听课  黑屏锁键鼠 + 自定义文字
    view_probe 192.168.2.139     先确认学生观看端口已监听
    view 192.168.2.139           打开连续屏幕观看窗口
    control 192.168.2.139        打开窗口并开始鼠标/键盘远控
    mouse 192.168.2.139 move 32768 32768
    key 192.168.2.139 0x41 press  按一次 A 键
    shutdown 192.168.2.139        立即强制关机
    reboot 192.168.2.139 30 请保存作业  倒计时30秒重启并显示提示文字
    setchannel 192.168.2.139 7 0   实验性远程频道设置：频道7，不启用自动登录

  远程频道设置是实验性控制面：只证实 subcase 7 的 AutoLogin / ChannelId 字段，
  length 与其它 subcase 未知；学生端注册表写入、重启/重连及官方兼容性未实机验证。''')


def cmd_list():
    if not students:
        print('[命令] 当前无学生登录')
        return
    print('[命令] 已登录学生：')
    for i, (sip, st) in enumerate(students.items(), 1):
        info = st.get('info')
        if info:
            print(f"  {i}. {sip}  {info['name']}  用户:{info['user']}  MAC:{info['mac']}")
            print(f"      OS:{info['os']} {info['osver']}  CPU:{info['cpu_model']}  内存:{info['mem']}")
        else:
            print(f'  {i}. {sip}  (信息未获取，用 info {sip} 请求)')


def cmd_info(args):
    if not args:
        print('[命令] 用法：info <学生IP> [0|1|2]  (0=全部 1=窗口列表 2=进程列表)')
        return
    sip = args[0]
    if sip not in students:
        print(f'[命令] 学生 {sip} 未登录')
        return
    rtype = 0
    if len(args) > 1 and args[1] in ('0', '1', '2'):
        rtype = int(args[1])
    request_info(sip, rtype)
    print(f'[命令] 已向 {sip} 请求信息(rtype={rtype})，结果见日志窗口')


def _check_student(sip, usage):
    """校验学生已登录;第一个参数不像 IP 时提示可能漏填了 IP。"""
    if sip in students:
        return True
    if '.' not in sip:
        logger.warning('[命令] "%s" 不是有效的学生 IP；用法:%s', sip, usage)
    else:
        logger.warning('[命令] 学生 %s 未登录或不在快照中', sip)
    return False


def _parse_run_args(rest):
    """解析 run 的 '<路径> [参数...] [show]'。路径含空格时用双引号包住。

    show 取末尾独立的 0/1/2（0=正常 1=最小化 2=最大化），其余原样作为程序参数。
    """
    rest = (rest or '').strip()
    if not rest:
        return '', '', 0
    if rest.startswith('"'):
        end = rest.find('"', 1)
        if end > 0:
            path, rest = rest[1:end], rest[end + 1:].strip()
        else:
            path, rest = rest[1:], ''
    else:
        parts = rest.split(maxsplit=1)
        path = parts[0]
        rest = parts[1] if len(parts) > 1 else ''
    show = 0
    if rest in ('0', '1', '2'):
        show, rest = int(rest), ''
    elif rest.endswith((' 0', ' 1', ' 2')):
        show, rest = int(rest[-1]), rest[:-2].rstrip()
    return path, rest, show


def _parse_target_force(rest):
    """'<target> [force]' → (target, force)。force 默认 1，仅识别末尾独立的 0/1。"""
    force = 1
    rest = (rest or '').strip()
    if rest.endswith(' 0'):
        force, rest = 0, rest[:-2].strip()
    elif rest.endswith(' 1'):
        force, rest = 1, rest[:-2].strip()
    return rest, force


def cmd_kill(args):
    """kill <ip> <pid|进程名> [force=1|0]——按 pid 或已建档进程名结束进程。"""
    if len(args) < 2:
        print('[命令] 用法：kill <学生IP> <pid|进程名> [force=1|0]')
        return
    sip = args[0]
    if not _check_student(sip, 'kill <学生IP> <pid|进程名> [force=1|0]'):
        return
    target, force = _parse_target_force(args[1])
    if not target:
        print('[命令] 用法：kill <学生IP> <pid|进程名> [force=1|0]')
        return
    if target.isdigit():
        send_kill(sip, pid=int(target), force=force)
        return
    # 按进程名：查已建档进程列表（info <ip> 2）
    procs = students[sip].get('processes')
    if not procs:
        print(f'[命令] 无 {sip} 的进程列表，先 info {sip} 2 请求')
        return
    matches = [(p, n) for p, n in procs if n.lower() == target.lower()]
    if not matches:  # 精确匹配不到再试包含匹配
        matches = [(p, n) for p, n in procs if target.lower() in n.lower()]
    if not matches:
        print(f'[命令] 进程列表中找不到 "{target}"，可先 info {sip} 2 刷新')
        return
    for pid, name in matches:
        send_kill(sip, pid=pid, force=force)
        time.sleep(0.03)
    print(f'[命令] 已对 {len(matches)} 个匹配进程发送结束命令（可用 info {sip} 2 验证）')


def cmd_closeapp(args):
    """closeapp <ip> <hwnd|标题关键字> [force=1|0]——按窗口结束应用程序。"""
    if len(args) < 2:
        print('[命令] 用法：closeapp <学生IP> <hwnd|窗口标题关键字> [force=1|0]')
        return
    sip = args[0]
    if not _check_student(sip, 'closeapp <学生IP> <hwnd|窗口标题关键字> [force=1|0]'):
        return
    target, force = _parse_target_force(args[1])
    if not target:
        print('[命令] 用法：closeapp <学生IP> <hwnd|窗口标题关键字> [force=1|0]')
        return
    try:
        hwnd = int(target, 0)  # 支持 0x 前缀或十进制
        send_kill(sip, hwnd=hwnd, force=force)
        return
    except ValueError:
        pass
    # 按标题关键字：查已建档窗口列表（info <ip> 1）
    wins = students[sip].get('windows')
    if not wins:
        print(f'[命令] 无 {sip} 的窗口列表，先 info {sip} 1 请求')
        return
    matches = [(h, t) for h, t in wins if target.lower() in t.lower()]
    if not matches:
        print(f'[命令] 窗口列表中找不到 "{target}"，可先 info {sip} 1 刷新')
        return
    if len(matches) > 1:
        print(f'[命令] 匹配到 {len(matches)} 个窗口，取第一个：')
        for h, t in matches[:5]:
            print(f'    0x{h:08X}  {t}')
    hwnd, title = matches[0]
    print(f'[命令] 匹配窗口：0x{hwnd:08X} {title}')
    send_kill(sip, hwnd=hwnd, force=force)


def cmd_ps(args):
    """显示已收集的进程列表（type 7，pid+exe名）。"""
    if not args:
        print('[命令] 用法：ps <学生IP>')
        return
    sip = args[0]
    procs = students.get(sip, {}).get('processes')
    if not procs:
        print(f'[命令] 无 {sip} 的进程列表（先 info {sip} 2 请求）')
        return
    print(f'[命令] {sip} 进程列表（{len(procs)} 个）：')
    for pid, name in procs:
        print(f'  {pid:>6}  {name}')


def cmd_wins(args):
    """显示已收集的窗口列表（type 6，hwnd+标题）。"""
    if not args:
        print('[命令] 用法：wins <学生IP>')
        return
    sip = args[0]
    wins = students.get(sip, {}).get('windows')
    if not wins:
        print(f'[命令] 无 {sip} 的窗口列表（先 info {sip} 1 请求）')
        return
    print(f'[命令] {sip} 窗口列表（{len(wins)} 个）：')
    for hwnd, title in wins:
        print(f'  0x{hwnd:08X}  {title}')


def cmd_preview(args):
    if not args:
        print('[命令] 用法：preview <学生IP>')
        return False
    sip = args[0]
    ok = request_preview(sip)
    print(f'[命令] 已向 {sip} 请求预览 ok={ok}')
    return ok


def cmd_view(args):
    if not args:
        print('[命令] 用法：view <学生IP> [TCP端口]')
        return {'ok': False, 'active': False, 'action': 'start',
                'reason': '缺少学生 IP', 'cooldown_remaining': 0.0}
    sip = args[0]
    try:
        port = int(args[1].strip(), 0) if len(args) > 1 else TCP_COMM_PORT
        if not 1 <= port <= 0xFFFF:
            raise ValueError('端口必须在 1..65535')
    except ValueError as error:
        result = {'ok': False, 'active': False, 'action': 'start',
                  'reason': f'参数错误：{error}', 'cooldown_remaining': 0.0}
        logger.warning('[观看] %s 参数错误：%s', sip, error)
        print(f'[观看] 参数错误：{error}')
        return result
    result = toggle_remote_view(sip, port)
    if result['ok']:
        if result['action'] == 'stopped':
            print(f'[观看] 已停止 {sip}')
        else:
            print(f'[观看] 已启动 {sip}:{port}，正在连接；画面由 ffplay 显示')
    else:
        logger.warning('[观看] %s 操作未成功：%s', sip, result['reason'])
        print(f'[观看] 操作未成功：{result["reason"]}')
    return result


def cmd_view_probe(args):
    if not args:
        print('[命令] 用法：view_probe <学生IP> [TCP端口]')
        return
    sip = args[0]
    try:
        port = int(args[1].strip(), 0) if len(args) > 1 else TCP_COMM_PORT
        if not 1 <= port <= 0xFFFF:
            raise ValueError('端口必须在 1..65535')
        if not _check_student(sip, 'view_probe <学生IP> [TCP端口]'):
            return
        reachable, detail = probe_remote_view(sip, port)
        if reachable:
            print(f'[观看] 探测成功：{sip}:{port} 正在监听，可以执行 view {sip}')
        else:
            print(f'[观看] 探测失败：{sip}:{port} 未监听（{detail}）；未发送观看请求')
    except (ValueError, OSError) as e:
        print(f'[观看] 探测参数错误：{e}')


def cmd_control(args):
    if not args:
        print('[命令] 用法：control <学生IP> [UDP端口]')
        return
    sip = args[0]
    try:
        port = int(args[1].strip(), 0) if len(args) > 1 else None
        if port is not None and not 1 <= port <= 0xFFFF:
            raise ValueError('端口必须在 1..65535')
        if not _check_student(sip, 'control <学生IP> [UDP端口]'):
            return
        with remote_state_lock:
            session = remote_views.get(sip)
        if session is None:
            if not start_remote_view(sip):
                print('[远控] 未发送 MCMD：观看通道尚未建立，避免学生端进入不完整的远控状态')
                return
            with remote_state_lock:
                session = remote_views.get(sip)
        if session is not None:
            session.enable_interactive_player()
        if session is None or not session.connected_event.wait(6.0):
            print('[远控] 未发送 MCMD：等待屏幕 TCP 通道超时，请先执行 view_probe 后重试')
            return
        selected_port = start_remote_control(sip, port)
        if selected_port:
            print(f'[远控] {sip}:{selected_port} 已启动；在远程控制窗口内可直接操作鼠标和键盘')
    except (ValueError, OSError) as e:
        print(f'[远控] 启动失败：{e}')


def cmd_mouse(args):
    if len(args) < 2:
        print('[命令] 用法：mouse <学生IP> <动作> <x> <y> [data]')
        return
    sip = args[0]
    parts = args[1].split()
    if len(parts) < 3:
        print('[命令] 用法：mouse <学生IP> <动作> <x> <y> [data]')
        return
    try:
        action = parts[0]
        x, y = int(parts[1], 0), int(parts[2], 0)
        data = int(parts[3], 0) if len(parts) > 3 else 0
        if send_remote_mouse(sip, action, x, y, data):
            print(f'[远控] mouse {action} -> {sip} ({x},{y})')
    except (ValueError, OSError) as e:
        print(f'[远控] 鼠标事件失败：{e}')


def cmd_key(args):
    if len(args) < 2:
        print('[命令] 用法：key <学生IP> <vk> [press|down|up] [scan] [extended=0|1]')
        return
    sip = args[0]
    parts = args[1].split()
    try:
        virtual_key = int(parts[0], 0)
        action = parts[1].lower() if len(parts) > 1 else 'press'
        if action not in ('press', 'down', 'up'):
            raise ValueError('动作必须是 press/down/up')
        scan_code = int(parts[2], 0) if len(parts) > 2 else None
        extended = bool(int(parts[3], 0)) if len(parts) > 3 else False
        if action in ('press', 'down'):
            if not send_remote_key(sip, virtual_key, False, scan_code, extended):
                return
        if action == 'press':
            time.sleep(0.03)
        if action in ('press', 'up'):
            if not send_remote_key(sip, virtual_key, True, scan_code, extended):
                return
        print(f'[远控] key vk=0x{virtual_key:02X} {action} -> {sip}')
    except (ValueError, OSError) as e:
        print(f'[远控] 键盘事件失败：{e}')


def cmd_all():
    if not request_all_previews():
        print('[命令] 当前无学生登录或网络未启动')
        return False
    print('[命令] 已后台提交全班预览请求')
    return True


def cmd_debug(args):
    if not args or args[0].lower() not in ('on', 'off'):
        print(f'[命令] 用法：debug on/off（当前文件日志级别：{logging.getLevelName(FILE_LOG_LEVEL)}）')
        return
    if args[0].lower() == 'on':
        set_file_log_level(logging.DEBUG)
        print('[命令] 已开启 DEBUG 日志（文件会变大）')
    else:
        set_file_log_level(logging.INFO)
        print('[命令] 已关闭 DEBUG 日志，仅保留 INFO 及以上')



def cmd_setchannel(args):
    """setchannel <学生IP> <1..32> [0|1]：实验性远程频道设置。"""
    usage = 'setchannel <学生IP> <1..32> [0|1]'
    fields = [value for part in args[1:] for value in str(part).split()]
    if not args or not 1 <= len(fields) <= 2:
        print(f'[命令] 用法：{usage}')
        return
    sip = args[0]
    try:
        channel = int(fields[0], 10)
        auto_login = int(fields[1], 10) if len(fields) > 1 else 0
        if send_remote_channel_settings(sip, channel, auto_login):
            print('[远程设置] 仅发送实验性控制面；学生端注册表写入、重启/重连'
                  '及官方兼容性未实机验证，教师端自身频道不变')
    except ValueError as error:
        print(f'[远程设置] 参数错误：{error}；用法：{usage}')
    except OSError as error:
        print(f'[远程设置] 发送失败：{error}')


def command_loop():
    global running
    print('教师端已启动，输入 help 查看命令')
    while running:
        try:
            line = input('teacher> ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split(maxsplit=2)
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ('help', '?', 'h'):
            cmd_help()
        elif cmd in ('list', 'ls', 'students'):
            cmd_list()
        elif cmd == 'preview':
            cmd_preview(args)
        elif cmd == 'view_probe':
            cmd_view_probe(args)
        elif cmd in ('view', 'watch'):
            cmd_view(args)
        elif cmd in ('view_stop', 'unview'):
            if not args:
                print('[命令] 用法：view_stop <学生IP>')
            else:
                stop_remote_view(args[0])
                print(f'[观看] 已停止 {args[0]}')
        elif cmd in ('control', 'ctrl'):
            cmd_control(args)
        elif cmd in ('control_stop', 'ctrl_stop'):
            if not args:
                print('[命令] 用法：control_stop <学生IP>')
            else:
                stop_remote_control(args[0])
                print(f'[远控] 已停止 {args[0]}')
        elif cmd == 'mouse':
            cmd_mouse(args)
        elif cmd == 'key':
            cmd_key(args)
        elif cmd == 'all':
            cmd_all()
        elif cmd == 'debug':
            cmd_debug(args)
        elif cmd == 'msg':
            if len(args) < 2:
                print('[命令] 用法：msg <学生IP> <消息内容>')
            else:
                send_chat(args[0], args[1])
        elif cmd == 'info':
            cmd_info(args)
        elif cmd == 'ps':
            cmd_ps(args)
        elif cmd == 'wins':
            cmd_wins(args)
        elif cmd == 'kill':
            cmd_kill(args)
        elif cmd == 'closeapp':
            cmd_closeapp(args)
        elif cmd in ('openurl', 'open'):
            if len(args) < 2:
                print('[命令] 用法：openurl <学生IP> <网址|文件路径>')
            elif _check_student(args[0], 'openurl <学生IP> <网址|文件路径>'):
                send_open_url(args[0], args[1])
        elif cmd == 'run':
            if len(args) < 2:
                print('[命令] 用法：run <学生IP> <程序路径> [参数...] [show=0|1|2]（路径含空格用双引号）')
            elif _check_student(args[0], 'run <学生IP> <程序路径> [参数] [show]'):
                path, pargs, show = _parse_run_args(args[1])
                if not path:
                    print('[命令] 用法：run <学生IP> <程序路径> [参数...] [show=0|1|2]')
                else:
                    send_run_program(args[0], path, pargs, show)
        elif cmd == 'setchannel':
            cmd_setchannel(args)
        elif cmd in ('blackscreen', 'bs'):
            if len(args) < 1:
                print('[命令] 用法：blackscreen <学生IP> [lock=1|0] [提示文字]')
            else:
                lock, text = _parse_lock_text(args[1] if len(args) > 1 else '')
                send_blackscreen(args[0], lock_input=lock, timeout=10, text=text)
        elif cmd in ('bsperm', 'bsp'):
            if len(args) < 1:
                print('[命令] 用法：bsperm <学生IP> [lock=1|0] [提示文字]')
            else:
                lock, text = _parse_lock_text(args[1] if len(args) > 1 else '')
                send_blackscreen(args[0], lock_input=lock, timeout=0, text=text)
        elif cmd == 'unlock':
            if len(args) < 1:
                print('[命令] 用法：unlock <学生IP>')
            else:
                send_unlock(args[0])
        elif cmd == 'bsall':
            if not students:
                print('[命令] 当前无学生登录')
            else:
                lock, text = _parse_lock_text(args[0] if args else '')
                for sip in list(students.keys()):
                    send_blackscreen(sip, lock_input=lock, timeout=10, text=text)
                    time.sleep(0.05)
        elif cmd == 'unlock_all':
            if not students:
                print('[命令] 当前无学生登录')
            else:
                for sip in list(students.keys()):
                    send_unlock(sip)
                    time.sleep(0.05)
        elif cmd in ('shutdown', 'sd'):
            if len(args) < 1:
                print('[命令] 用法：shutdown <学生IP> [倒计时秒数] [提示文字]')
            else:
                delay, text = _parse_delay_text(args[1] if len(args) > 1 else '')
                send_shutdown(args[0], reboot=False, delay=delay,
                              force=(delay == 0), text=text)
        elif cmd in ('reboot', 'rb'):
            if len(args) < 1:
                print('[命令] 用法：reboot <学生IP> [倒计时秒数] [提示文字]')
            else:
                delay, text = _parse_delay_text(args[1] if len(args) > 1 else '')
                send_shutdown(args[0], reboot=True, delay=delay,
                              force=(delay == 0), text=text)
        elif cmd in ('exit', 'quit', 'q'):
            break
        else:
            print(f'[命令] 未知命令：{cmd}，输入 help 查看帮助')


# -------------------- 启动 --------------------

def start_background_threads():
    """启动网络与 4 个后台线程；重复调用保持幂等，失败返回 False。

    start_network() 可重复调用（GUI 先调、这里再调也安全），导入模块不会 bind。
    """
    global running
    if not start_network():
        logger.error('[Threads] 网络未就绪，后台线程不启动 error=%s', network_error)
        return False
    with shutdown_lock:
        running = True
    _reset_classroom_writer_for_restart()
    logger.info('启动 4 个后台线程')
    started, failed = [], []
    for name, target in (
        ('broadcast', broadcast), ('session_anno', session_anno),
        ('session_recv', session_recv), ('main_recv', main_recv),
    ):
        thread = _start_managed_thread(name, target)
        if thread is None:
            failed.append(name)
        else:
            started.append(name)
    logger.info('[Threads] 后台线程启动完成 started=%s failed=%s running=%s '
                'session_id=%s generation=%d',
                started, failed, running, session_id, generation)
    return not failed


def shutdown():
    """停止网络与后台线程；重复调用直接返回 False。

    顺序：置停止标志 → 通知学生停止 feature/MCMD（allow_when_stopped）→
    有界 join 后台线程 → 关闭 socket → 释放单实例 Mutex。socket 只在线程
    停止后关闭，避免现场日志里的 WinError 10038 退出竞态。
    """
    global running, classroom_shutdown, submission_server, submission_listen_port
    global shutdown_stage
    with shutdown_lock:
        if shutdown_stage is not None:
            logger.debug('[Shutdown] 已执行或正在执行，忽略重复调用 stage=%s',
                         shutdown_stage)
            return False
        shutdown_stage = 'stopping'
        running = False
        network_stop_event.set()
    had_network = network_started and not network_sockets_closed
    logger.info('[Shutdown] 开始 session_id=%s network=%s students=%d previews=%d '
                'views=%d controls=%d',
                session_id, had_network, len(students), len(previews),
                len(remote_views), len(remote_controls))
    with submission_lock:
        server, submission_server = submission_server, None
        closed_port, submission_listen_port = submission_listen_port, None
    if server is not None:
        try:
            server.close()
            logger.info('[FileSubmit][MiniMedia] 接收服务已关闭 port=%s directory=%s',
                        closed_port, SUBMISSION_DIR)
        except Exception as error:
            logger.warning('[FileSubmit][MiniMedia] 关闭接收服务失败 port=%s error=%s',
                           closed_port, error, exc_info=True)
    with classroom_lock:
        if not classroom_shutdown:
            classroom_shutdown = True
            try:
                _start_classroom_writer()
                classroom_write_queue.put(None)
            except Exception as error:
                logger.warning('[Classroom] 退出时启动写盘收尾失败：%s', error)
    _bounded_queue_join()
    try:
        for timer in list(blackscreen_timers.values()):
            timer.cancel()
        blackscreen_timers.clear()
        # 退出时仍要发已证实的 feature/MCMD 停止包（notify=True），
        # 让丢掉 TCP/UDP 会话前学生端停止采集与远控接收。
        for sip in list(remote_views):
            try:
                stop_remote_view(sip, notify=True)
            except Exception as error:
                logger.warning('[Shutdown] 停止观看失败 %s：%s', sip, error)
        for sip in list(remote_controls):
            try:
                stop_remote_control(sip, notify=True)
            except Exception as error:
                logger.warning('[Shutdown] 停止远控失败 %s：%s', sip, error)
        for sip in list(screen_broadcasts):
            try:
                stop_screen_broadcast(sip)
            except Exception as error:
                logger.warning('[Broadcast] 退出时停止 %s 失败：%s', sip, error)
        for source_ip in list(student_demos):
            try:
                stop_student_demo(source_ip)
            except Exception as error:
                logger.warning('[Demo] 退出时停止 %s 失败：%s', source_ip, error)
    except Exception as error:
        logger.error('[Shutdown] 停止本地会话时异常：%s', error, exc_info=True)
    finally:
        joined = _join_background_threads()
        _close_network_sockets()
        _release_single_instance_mutex()
        logger.info('[Shutdown] 未发送 FNXT/TQNC/TRXT：目的封装、尾部 6 字节、'
                    'GUID 与 +0x1C 语义未证实，只解析记录、不构造')
        logger.info('程序退出。students=%s, previews=%s, threads_joined=%s',
                    list(students.keys()), list(previews.keys()), joined)
        with shutdown_lock:
            shutdown_stage = 'done'
    return True


if __name__ == '__main__':
    spawn_log_window()
    if not start_background_threads():
        logger.error('教师端启动失败：网络未就绪 error=%s', network_error)
        print(f'[启动] 网络启动失败：{network_error}')
        shutdown()
        raise SystemExit(1)
    try:
        command_loop()
    finally:
        shutdown()
