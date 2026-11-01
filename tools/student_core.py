"""学生模拟状态、命令解析和不依赖 GUI 的 UDP 客户端。"""
from __future__ import annotations

import logging
import os
import queue
import socket
import struct
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

try:
    from . import student_protocol as protocol
except ImportError:
    import student_protocol as protocol

LOGGER = logging.getLogger('student_sim')


@dataclass(frozen=True)
class StudentConfig:
    teacher_ip: str
    bind_ip: str
    channel: int = 1
    computer_name: str = 'STUDENT-SIM'
    user_name: str = 'student'
    main_port: int = protocol.MAIN_PORT
    session_port: int = 0
    execute: bool = False

    def __post_init__(self):
        socket.inet_aton(self.teacher_ip)
        socket.inet_aton(self.bind_ip)
        protocol.session_endpoint(self.channel)
        if not 0 < self.main_port <= 65535:
            raise ValueError('主端口必须在 1 到 65535 之间')
        if not 0 <= self.session_port <= 65535:
            raise ValueError('会话端口必须在 0 到 65535 之间')
        if self.teacher_ip == self.bind_ip:
            raise ValueError(
                '教师 IP 与学生绑定 IP 相同：教师端会忽略自身 IP，且固定端口会冲突。'
                '请使用另一台机器/虚拟机，或为学生配置独立 IP。'
            )

    @property
    def multicast_group(self) -> str:
        return protocol.session_endpoint(self.channel)[0]

    @property
    def session_port_or_default(self) -> int:
        return self.session_port or protocol.session_endpoint(self.channel)[1]


@dataclass(frozen=True)
class PendingSubmission:
    transaction_guid: str
    student_id: int
    file_count: int
    total_size: int


@dataclass
class StudentState:
    online: bool = False
    login_replies: set[int] = field(default_factory=set)
    blackscreen: bool = False
    blackscreen_text: str = ''
    lock_requested: bool = False
    hand_up: bool = False
    preview_enabled: bool = False
    preview_version: int = 0
    screen_broadcast: bool = False
    student_demo: bool = False
    remote_view: bool = False
    remote_control: bool = False
    pending_submission: PendingSubmission | None = None
    submission_status: str = 'idle'
    submission_detail: str = '尚未发送文件提交请求'
    last_teacher_packet: float = 0.0

    def status_lines(self, config: StudentConfig, execute: bool) -> list[str]:
        pending = self.pending_submission
        pending_text = (f'{pending.file_count} 个文件，{pending.total_size} 字节，'
                        f'GUID {pending.transaction_guid}') if pending else '无'
        return [
            f"状态：{'在线' if self.online else '离线/等待登录'}",
            f'教师：{config.teacher_ip}（主 {config.main_port}，会话 {config.session_port_or_default}）',
            f'学生：{config.bind_ip}，频道 {config.channel}，组播 {config.multicast_group}',
            f'黑屏：{"是（仅提示）" if self.blackscreen else "否"}；举手：{"是" if self.hand_up else "否"}',
            f'广播：{"是" if self.screen_broadcast else "否"}；演示：{"是（仅提示）" if self.student_demo else "否"}；'
            f'观看：{"是" if self.remote_view else "否"}；远控请求：{"是（不执行）" if self.remote_control else "否"}',
            f'文件提交：{self.submission_status}；{self.submission_detail}',
            f'待回复请求：{pending_text}',
            f'动作模式：{"受限白名单" if execute else "观察（全部仅记录）"}',
        ]


class StudentMachine:
    """纯状态机；网络发送通过回调注入，自检不需要 socket。"""

    def __init__(self, config: StudentConfig,
                 sender: Callable[[str, bytes, str], None] | None = None,
                 event_handler: Callable[[str, str], None] | None = None,
                 facts: dict | None = None,
                 windows: Iterable[tuple[int, str]] = (),
                 processes: Iterable[tuple[int, str]] = ()):
        self.config = config
        self.sender = sender or (lambda kind, data, via: None)
        self.event_handler = event_handler or (lambda kind, text: None)
        self.state = StudentState()
        self.facts = facts or protocol.machine_facts(config.computer_name, config.user_name)
        self.windows = list(windows) or [(0x10010, '模拟学生端'), (0x10020, '课堂窗口')]
        self.processes = list(processes) or [(os.getpid(), Path(os.sys.executable).name)]
        self._reply_log = []
        self._last_submission_guid = ''

    def event(self, kind: str, text: str) -> None:
        LOGGER.info('[%s] %s', kind, text)
        self.event_handler(kind, text)

    def send(self, kind: str, data: bytes, via: str = 'session') -> None:
        self.sender(kind, data, via)

    def login(self) -> None:
        self.send('LOGI', protocol.build_logi(
            self.config.bind_ip, self.config.computer_name,
            self.config.user_name, self.config.channel,
            self.facts.get('stu_id', 1)))
        self.event('登录', f'已发送 LOGI -> {self.config.teacher_ip}:{self.config.session_port_or_default}')

    def set_hand_up(self, enabled: bool) -> None:
        self.state.hand_up = bool(enabled)
        self.send('ANNO', protocol.build_anno(
            self.state.hand_up, 0x20 if self.state.blackscreen else 0))
        self.event('举手', '已举手' if enabled else '已取消举手')

    def send_chat(self, text: str) -> None:
        if not text.strip():
            raise ValueError('聊天内容不能为空')
        self.send('MESS', protocol.build_chat(self.config.teacher_ip, text))
        self.event('聊天发送', text)

    def submit_files(self, paths: Iterable[str]) -> None:
        files = [Path(path).expanduser() for path in paths]
        if not files:
            raise ValueError('至少选择一个文件')
        for path in files:
            if not path.is_file():
                raise ValueError(f'不是可提交的文件：{path}')
        total_size = sum(path.stat().st_size for path in files)
        directory = str(files[0].resolve().parent)
        file_list = '|'.join(path.name for path in files)
        student_id = self.facts.get('stu_id', 1)
        data = protocol.build_submit_request(
            self.config.teacher_ip, directory, file_list, len(files), total_size,
            student_id=student_id)
        pending = PendingSubmission(data[12:28].hex(), student_id, len(files), total_size)
        self.send('QRMS', data, 'main')
        self.state.pending_submission = pending
        self.state.submission_status = 'pending'
        self.state.submission_detail = '等待教师 RRMS 回复；不会发送文件内容'
        self._last_submission_guid = pending.transaction_guid
        self.event('文件提交', f'已发送 QRMS 请求：{len(files)} 个文件，{total_size} 字节；'
                              f'GUID={pending.transaction_guid}；{file_list}')

    def handle_rrms(self, data: bytes, source_ip: str = '') -> None:
        if source_ip != self.config.teacher_ip:
            self.event('忽略', f'RRMS 来源不是教师：{source_ip or "未知"}')
            return
        try:
            response = protocol.parse_submit_response(data)
        except ValueError as exc:
            self.event('忽略', f'RRMS 格式无效：{exc}')
            return
        guid = response['transaction_guid']
        pending = self.state.pending_submission
        if pending is None and guid == self._last_submission_guid:
            self.event('文件提交', f'收到重复 RRMS，保持 {self.state.submission_status}；不重复处理')
            return
        if pending is None:
            self.event('忽略', f'RRMS 没有匹配的待处理请求：GUID={guid}')
            return
        if guid != pending.transaction_guid:
            self.event('忽略', f'RRMS GUID 不匹配：收到 {guid}，'
                              f'等待 {pending.transaction_guid}')
            return
        if response['student_id'] != pending.student_id:
            self.event('忽略', f"RRMS 学生 ID 不匹配：收到 {response['student_id']}，"
                              f'等待 {pending.student_id}')
            return
        self.state.pending_submission = None
        approved = bool(response['accept'] and response['arg2'] and response['arg3'])
        if approved:
            self.state.submission_status = 'approved'
            self.state.submission_detail = '教师已接受，MiniMedia 上传未实现；不会发送文件内容'
        else:
            self.state.submission_status = 'rejected'
            if response['accept'] and not response['arg2']:
                self.state.submission_detail = (
                    f"教师按配额/文件数限制拒绝：arg2=0，配额={response['quota']} 字节，"
                    f"最大文件数={response['max_files']}；不会发送文件内容")
            else:
                self.state.submission_detail = (
                    f"教师拒绝提交：accept={response['accept']}，arg2={response['arg2']}，"
                    f"arg3={response['arg3']}；不会发送文件内容")
        self.event('文件提交', self.state.submission_detail)

    def answer_info(self, rtype: int) -> int:
        packets = protocol.build_info_reply(
            self.config.teacher_ip, rtype, self.facts, self.windows, self.processes)
        for data in packets:
            self.send('MESS', data)
        self.event('信息上报', f'rtype={rtype}，已回送 {len(packets)} 个 MESS 包')
        return len(packets)

    def observe_only(self, action: str, detail: str = '') -> None:
        suffix = f'：{detail}' if detail else ''
        self.event('仅提示', f'{action}{suffix}（不会执行）')

    def safe_open_url(self, url: str) -> bool:
        if not self.config.execute:
            self.observe_only('打开网页', url)
            return False
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
            self.observe_only('拒绝非 HTTP/HTTPS 地址', url)
            return False
        webbrowser.open(url, new=2)
        self.event('白名单执行', f'已请求系统浏览器打开：{url}')
        return True

    def safe_run_program(self, path: str, args: str, show: int) -> bool:
        if not self.config.execute:
            self.observe_only('远程运行', f'"{path}" {args}'.strip())
            return False
        allowed = {
            'notepad.exe': Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'notepad.exe',
            'calc.exe': Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'calc.exe',
        }
        executable = allowed.get(Path(path).name.lower())
        requested = Path(path)
        if (os.name != 'nt' or executable is None or not executable.is_file()
                or (requested.is_absolute() and requested.resolve() != executable.resolve())):
            self.observe_only('拒绝非白名单程序', path)
            return False
        if args.strip():
            self.observe_only('拒绝带参数的远程运行', args)
            return False
        subprocess.Popen([str(executable)], close_fds=True)
        self.event('白名单执行', f'已启动：{executable.name}')
        return True

    def handle_mess(self, data: bytes, source_ip: str = '') -> None:
        _, _, recipients, payload = protocol.split_mess(data)
        if recipients and self.config.bind_ip not in recipients and '0.0.0.0' not in recipients:
            self.event('忽略', f'MESS 接收者不包括本机：{recipients}')
            return
        if len(payload) < 12:
            self.observe_only('过短的 MESS', f'{len(payload)} 字节')
            return
        declared, msg_type, category = struct.unpack_from('<III', payload)
        subtype = struct.unpack_from('<I', payload, 12)[0] if len(payload) >= 16 else 0
        if declared < 12 or declared > len(payload):
            self.observe_only('MESS 声明长度无效', f'declared={declared}, actual={len(payload)}')
            return
        if msg_type in (0x1000, 0x8000):
            first = msg_type not in self.state.login_replies
            self.state.login_replies.add(msg_type)
            self.state.online = True
            self.state.last_teacher_packet = time.monotonic()
            self.event('登录回执', f'MESS type=0x{msg_type:04X}，学生在线')
            if first and msg_type == 0x8000:
                self.answer_info(0)
            return
        if msg_type == 0x800:
            text = protocol.decode_wstr(payload[16:declared])
            self.event('教师聊天', text)
            return
        if msg_type == 0x100000:
            if subtype in (0, 1, 2):
                self.answer_info(subtype)
            elif subtype in (3, 4):
                target = struct.unpack_from('<II', payload, 16) if len(payload) >= 24 else (0, 0)
                self.observe_only('结束应用程序' if subtype == 3 else '结束进程',
                                  f'hwnd=0x{target[0]:08X}, pid={target[1]}')
            else:
                self.observe_only('未知信息通道命令', f'subtype={subtype}')
            return
        if msg_type == 0x20:
            flags = struct.unpack_from('<I', payload, 8)[0]
            self.state.blackscreen = bool(flags & 0x80000000) and not bool(flags & 0x10000000)
            self.state.lock_requested = self.state.blackscreen and bool(
                len(payload) >= 16 and struct.unpack_from('<I', payload, 12)[0])
            self.state.blackscreen_text = ''
            if self.state.blackscreen and len(payload) >= 28 and struct.unpack_from('<I', payload, 24)[0]:
                self.state.blackscreen_text = protocol.decode_wstr(payload[36:declared])
            detail = self.state.blackscreen_text
            if self.state.lock_requested:
                detail = (detail + '；' if detail else '') + '教师要求锁键鼠（不执行）'
            self.event('黑屏提示' if self.state.blackscreen else '黑屏解除', detail or '仅更新模拟状态')
            self.send('ANNO', protocol.build_anno(
                self.state.hand_up, 0x20 if self.state.blackscreen else 0))
            return
        if msg_type == 8 and payload[12:16] == b'MCMD':
            self._handle_remote_control(payload)
            return
        if len(payload) >= 24 and payload[20:24] == struct.pack('<I', 4):
            flags = struct.unpack_from('<I', payload, 24)[0] if len(payload) >= 28 else 0
            self.state.student_demo = not bool(flags & 0x10000000)
            self.send('ANNO', protocol.build_anno(
                self.state.hand_up, student_demo=self.state.student_demo))
            self.event('学生演示', '语音启动请求（仅提示，不连接或广播）'
                       if self.state.student_demo else '语音控制停止；无屏幕媒体')
            return
        if msg_type == 0:
            if not subtype and not (category & 0x0FFFFFFF):
                self.state.remote_view = False
                self.state.student_demo = False
                self.event('媒体会话', '通用停止（远程观看/学生演示）')
                return
            feature = subtype or (category & 0x0FFFFFFF)
            for feature_id, attribute, label in (
                    (0, 'remote_view', '远程观看'), (1, 'screen_broadcast', '屏幕广播'),
                    (4, 'student_demo', '学生演示'), (8, 'remote_view', '远程观看')):
                if feature == feature_id:
                    setattr(self.state, attribute, False)
                    self.event(label, '停止')
                    return
            self.observe_only('未知媒体停止', f'feature={feature}')
            return
        if msg_type in (1, 4) or (msg_type == 8 and (subtype in (1, 4, 8) or not subtype)):
            feature = subtype if msg_type == 8 and subtype else msg_type
            enabled = not bool(category & 0x10000000)
            if feature == 1:
                self.state.screen_broadcast = enabled
                self.event('屏幕广播', '开始请求（仅提示，无视频流）' if enabled else '停止')
            elif feature == 4:
                self.state.student_demo = enabled
                self.send('ANNO', protocol.build_anno(self.state.hand_up, student_demo=enabled))
                self.event('学生演示', '语音启动请求（仅提示，不连接或广播）' if enabled else '停止')
            else:
                self.state.remote_view = enabled
                self.event('远程观看', '开始请求（仅提示，不开放 TCP 屏幕服务）' if enabled else '停止')
            return
        self.observe_only('未识别 MESS', f'type=0x{msg_type:X}, category=0x{category:X}, subtype={subtype}')

    def _handle_remote_control(self, payload: bytes) -> None:
        if len(payload) < 20:
            self.observe_only('无效远控请求')
            return
        mode = struct.unpack_from('<I', payload, 16)[0]
        port = struct.unpack_from('<H', payload, 24)[0] if len(payload) >= 26 else 0
        self.state.remote_control = mode in (0, 2)
        self.observe_only('远程控制请求' if self.state.remote_control else '远程控制停止',
                          f'mode={mode}, UDP={port}')

    def handle_comd(self, data: bytes) -> None:
        try:
            cmd_code, _, payload = protocol.parse_comd(data)
        except ValueError:
            self.event('控制信息', f'收到 DMOC/COMD，共 {len(data)} 字节')
            return
        if cmd_code != 0x80000010 or len(payload) < 12:
            self.observe_only('COMD 命令', f'code=0x{cmd_code:08X}, {len(payload)} 字节')
            return
        category, _, command = struct.unpack_from('<III', payload)
        command_id = command & 0x0FFFFFFF
        if category != 0x200:
            self.observe_only('COMD 非应用命令', f'category=0x{category:X}, command=0x{command:X}')
            return
        if command_id == 0x0F and len(payload) >= 852:
            path = protocol.decode_wstr(payload[20:532])
            args = protocol.decode_wstr(payload[532:852])
            show = struct.unpack_from('<I', payload, 852)[0] if len(payload) >= 856 else 0
            self.safe_run_program(path, args, show)
        elif command_id == 0x18:
            self.safe_open_url(protocol.decode_wstr(payload[16:]))
        elif command_id in (0x13, 0x14):
            self.observe_only('重启' if command_id == 0x13 else '关机',
                              f'cmd=0x{command:08X}；模拟器保持运行')
        elif command_id == 6:
            lock = bool(len(payload) >= 16 and struct.unpack_from('<I', payload, 12)[0])
            self.state.lock_requested = lock
            self.observe_only('黑屏/锁屏控制', f'lock={lock}；不会锁定输入或屏幕')
        else:
            self.observe_only('其他应用命令', f'cmd=0x{command:08X}')

    def handle_packet(self, data: bytes, via: str, source_ip: str = '') -> None:
        if len(data) < 4:
            self.observe_only('短包', f'{via}: {len(data)} 字节')
            return
        magic = struct.unpack_from('<I', data)[0]
        if source_ip == self.config.teacher_ip:
            self.state.last_teacher_packet = time.monotonic()
        if magic == protocol.MAGIC_MESS:
            self.handle_mess(data, source_ip)
        elif magic == protocol.MAGIC_RRMS:
            self.handle_rrms(data, source_ip)
        elif magic == protocol.MAGIC_LPNT:
            policy = protocol.parse_lpnt(data)
            self.state.preview_enabled = policy['enabled']
            self.state.preview_version = policy['version']
            self.event('缩略图策略',
                       f"version={policy['version']}, enabled={policy['enabled']}, "
                       f"{policy['width']}x{policy['height']}；不回传图像")
        elif magic == protocol.MAGIC_DMOC:
            self.handle_comd(data)
        else:
            self.event('其他报文', f'{via}: magic=0x{magic:08X}, {len(data)} 字节')


class UdpStudentClient:
    def __init__(self, machine: StudentMachine):
        self.machine = machine
        self.config = machine.config
        self.events = queue.Queue()
        self.main_socket: socket.socket | None = None
        self.session_socket: socket.socket | None = None
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self._send_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._heartbeat = 5.0
        machine.sender = self.send
        machine.event_handler = lambda kind, text: self.events.put((kind, text))

    def _make_socket(self, port: int, multicast_group: str | None = None) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind((self.config.bind_ip, port))
            sock.settimeout(0.25)
            if multicast_group:
                membership = socket.inet_aton(multicast_group) + socket.inet_aton(self.config.bind_ip)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                                socket.inet_aton(self.config.bind_ip))
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)
            return sock
        except Exception:
            sock.close()
            raise

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.main_socket is not None:
                return
            self.stop_event = threading.Event()
            try:
                self.main_socket = self._make_socket(self.config.main_port, protocol.MAIN_MCAST)
                self.session_socket = self._make_socket(
                    self.config.session_port_or_default, self.config.multicast_group)
            except OSError as exc:
                self.close()
                raise OSError(
                    f'无法绑定学生 UDP {self.config.bind_ip}:{self.config.main_port}/'
                    f'{self.config.session_port_or_default}：{exc}。'
                    '教师与学生同机同 IP 不受支持，请使用不同机器/VM或独立 IP。'
                ) from exc
            stop_event = self.stop_event
            for name, sock in (('main', self.main_socket), ('session', self.session_socket)):
                thread = threading.Thread(target=self._receive_loop, args=(name, sock, stop_event),
                                          name=f'student-{name}', daemon=True)
                thread.start()
                self.threads.append(thread)
            heartbeat = threading.Thread(target=self._heartbeat_loop, args=(stop_event,),
                                         name='student-heartbeat', daemon=True)
            heartbeat.start()
            self.threads.append(heartbeat)
            self.machine.event('启动',
                               f"监听 {self.config.bind_ip}:{self.config.main_port} + "
                               f"{self.config.session_port_or_default}；教师 {self.config.teacher_ip}")
            if self.config.bind_ip in ('127.0.0.1', '0.0.0.0'):
                self.machine.event('警告', '教师按 UDP 来源 IP 记录学生；环回/通配绑定不能用于同机联调。')
            try:
                self.machine.login()
            except Exception:
                self.close()
                raise

    def send(self, kind: str, data: bytes, via: str = 'session') -> None:
        with self._send_lock:
            sock = self.main_socket if via == 'main' else self.session_socket
            if sock is None:
                raise RuntimeError('学生客户端尚未启动')
            port = self.config.main_port if via == 'main' else self.config.session_port_or_default
            sock.sendto(data, (self.config.teacher_ip, port))
        self.machine.event('发送', f'{kind} -> {self.config.teacher_ip}:{port}，{len(data)} 字节')

    def _receive_loop(self, via: str, sock: socket.socket, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                data, address = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self.machine.handle_packet(data, via, address[0])
            except Exception as exc:
                LOGGER.exception('处理 %s 包失败', via)
                self.machine.observe_only('报文处理失败', f'{via}: {exc}')

    def _heartbeat_loop(self, stop_event: threading.Event) -> None:
        while not stop_event.wait(self._heartbeat):
            try:
                self.machine.login()
            except (OSError, RuntimeError) as exc:
                if not stop_event.is_set():
                    self.machine.event('网络错误', f'保活发送失败：{exc}')

    def close(self) -> None:
        with self._lifecycle_lock:
            self.stop_event.set()
            sockets = (self.main_socket, self.session_socket)
            threads = self.threads
            self.main_socket = None
            self.session_socket = None
            self.threads = []
            self.machine.state.online = False
            self.machine.state.login_replies.clear()
        for sock in sockets:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        current = threading.current_thread()
        for thread in threads:
            if thread is not current:
                thread.join(timeout=1.0)
                if thread.is_alive():
                    LOGGER.warning('线程未在关闭超时内退出：%s', thread.name)

    def drain_events(self):
        while True:
            try:
                yield self.events.get_nowait()
            except queue.Empty:
                return
