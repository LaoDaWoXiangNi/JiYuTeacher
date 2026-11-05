#!/usr/bin/env python3
"""极域 V6 模拟学生端：默认观察模式，CLI 或可选 PyQt6 GUI。"""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shlex
import socket
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import student_protocol as protocol
    from student_core import StudentConfig, StudentMachine, UdpStudentClient
    from student_selftest import run_self_test
else:
    from . import student_protocol as protocol
    from .student_core import StudentConfig, StudentMachine, UdpStudentClient
    from .student_selftest import run_self_test

APP_DIR = Path(__file__).resolve().parent
LOG_PATH = APP_DIR / 'student_sim.log'
LOGGER = logging.getLogger('student_sim')


def setup_logging(verbose=False):
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.handlers.clear()
    formatter = logging.Formatter('%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s',
                                  datefmt='%Y-%m-%d %H:%M:%S')
    file_handler = RotatingFileHandler(LOG_PATH, maxBytes=2 * 1024 * 1024,
                                       backupCount=2, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(formatter)
    LOGGER.addHandler(console)


def detect_bind_ip(teacher_ip):
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((teacher_ip, protocol.MAIN_PORT))
        return probe.getsockname()[0]
    except OSError as exc:
        raise ValueError(f'无法自动选择到教师 {teacher_ip} 的网卡，请指定 --bind-ip：{exc}') from exc
    finally:
        probe.close()


def build_parser():
    parser = argparse.ArgumentParser(
        description='极域 V6 模拟学生端（默认只观察，不执行教师控制动作）',
        epilog='同机同 IP 不能联调：教师端固定忽略自身 IP。推荐不同机器/VM，或为学生使用独立 IP。')
    parser.add_argument('--teacher-ip', help='教师端 IPv4 地址；网络运行时必填')
    parser.add_argument('--bind-ip', help='学生本机 IPv4；默认根据到教师的路由选择')
    parser.add_argument('--channel', type=int, default=1, help='频道 1..32（默认 1）')
    parser.add_argument('--computer-name', default=platform_name(), help='上报的计算机名')
    parser.add_argument('--user-name', default=safe_user_name(), help='上报的登录用户名')
    parser.add_argument('--main-port', type=int, default=protocol.MAIN_PORT,
                        help='教师主 UDP 端口及学生监听端口（默认 4705）')
    parser.add_argument('--session-port', type=int, default=0,
                        help='覆盖频道会话端口；默认按频道计算')
    parser.add_argument('--execute', action='store_true',
                        help='仅允许 HTTP/HTTPS 与 Windows 白名单程序；危险动作仍不执行')
    parser.add_argument('--submission-port', type=int, default=0,
                        help='教师 MiniMedia 上传 TCP 端口；0 表示禁用上传（默认 0）')
    parser.add_argument('--upload-on-approve', action='store_true',
                        help='RRMS 严格批准后逐个上传所选文件；需同时指定 --submission-port')
    parser.add_argument('--cli', action='store_true', help='强制命令行界面')
    parser.add_argument('--gui', action='store_true', help='强制图形界面（需要 PyQt6）')
    parser.add_argument('--self-test', action='store_true', help='无网络协议/状态自检后退出')
    parser.add_argument('--verbose', action='store_true', help='控制台输出调试日志')
    return parser


def platform_name():
    return os.environ.get('COMPUTERNAME') or socket.gethostname() or 'STUDENT-SIM'


def safe_user_name():
    try:
        return getpass.getuser()
    except Exception:
        return 'student'


def status_text(machine):
    return '\n'.join(machine.state.status_lines(machine.config, machine.config.execute))


def make_config(args):
    if not args.teacher_ip:
        raise ValueError('请指定 --teacher-ip；自检可使用 --self-test，不需要网络')
    try:
        teacher_ip = str(ipaddress.IPv4Address(args.teacher_ip))
        bind_ip = str(ipaddress.IPv4Address(args.bind_ip)) if args.bind_ip else detect_bind_ip(teacher_ip)
    except ipaddress.AddressValueError as exc:
        raise ValueError(f'IPv4 地址无效：{exc}') from exc
    return StudentConfig(teacher_ip, bind_ip, args.channel, args.computer_name,
                         args.user_name, args.main_port, args.session_port, args.execute,
                         upload_port=args.submission_port,
                         upload_on_approve=args.upload_on_approve)


CLI_HELP = '''命令：
  chat <文本>             发送 MESS type=0x800 聊天
  handup / handdown       举手 / 取消举手（ANNO 72 字节）
  submit <文件> [...]     发送 QRMS 并等待 RRMS；仅在启用上传且严格批准后上传所选文件
  info [0|1|2]           主动上报全部/窗口/进程信息
  status                 显示当前模拟状态
  login                  立即发送 LOGI（后台也会周期保活）
  help                   显示帮助
  quit                   退出
'''


def run_cli(config):
    machine = StudentMachine(config)
    client = UdpStudentClient(machine)
    client.start()
    print(f'日志：{LOG_PATH}')
    print(CLI_HELP)
    try:
        while True:
            for kind, text in client.drain_events():
                print(f'[{kind}] {text}')
            try:
                line = input('student> ').strip()
            except EOFError:
                break
            if not line:
                continue
            for kind, text in client.drain_events():
                print(f'[{kind}] {text}')
            try:
                parts = shlex.split(line)
                command, args = parts[0].lower(), parts[1:]
                if command in ('quit', 'exit'):
                    break
                if command == 'help':
                    print(CLI_HELP)
                elif command == 'status':
                    print(status_text(machine))
                elif command == 'login':
                    machine.login()
                elif command == 'chat':
                    machine.send_chat(line.partition(' ')[2])
                elif command == 'handup':
                    machine.set_hand_up(True)
                elif command == 'handdown':
                    machine.set_hand_up(False)
                elif command == 'submit':
                    machine.submit_files(args)
                elif command == 'info':
                    rtype = int(args[0], 0) if args else 0
                    machine.answer_info(rtype)
                else:
                    print('未知命令，输入 help 查看帮助。')
            except (ValueError, OSError, RuntimeError) as exc:
                print(f'操作失败：{exc}')
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
        print('模拟学生端已退出。')
    return 0


def run_gui(config):
    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import (
            QApplication, QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
            QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
            QVBoxLayout, QWidget,
        )
    except ImportError as exc:
        raise RuntimeError('GUI 需要 PyQt6；请安装项目 requirements.txt，或使用 --cli。') from exc

    machine = StudentMachine(config)
    client = UdpStudentClient(machine)
    app = QApplication.instance() or QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle(f'模拟学生端 - {config.computer_name}（频道 {config.channel}）')
    window.resize(850, 680)
    central = QWidget()
    layout = QVBoxLayout(central)
    warning = QLabel('观察/受限模式：黑屏、锁屏、远控、关机、重启、杀进程始终只提示，绝不执行。')
    warning.setWordWrap(True)
    warning.setStyleSheet('color: #a33; font-weight: bold; padding: 6px;')
    layout.addWidget(warning)
    status = QLabel()
    status.setTextInteractionFlags(status.textInteractionFlags())
    status.setWordWrap(True)
    status.setText(status_text(machine))
    layout.addWidget(status)
    timeline = QPlainTextEdit()
    timeline.setReadOnly(True)
    timeline.setPlaceholderText('教师命令、登录回执和 UI 操作时间线')
    layout.addWidget(timeline, 1)

    chat_row = QHBoxLayout()
    chat_edit = QLineEdit()
    chat_edit.setPlaceholderText('发送给教师的聊天内容')
    chat_button = QPushButton('发送聊天')
    chat_row.addWidget(chat_edit, 1)
    chat_row.addWidget(chat_button)
    layout.addLayout(chat_row)
    buttons = QHBoxLayout()
    hand_button = QPushButton('举手')
    info_button = QPushButton('上报信息')
    submit_button = QPushButton('提交文件请求')
    login_button = QPushButton('重新登录')
    for button in (hand_button, info_button, submit_button, login_button):
        buttons.addWidget(button)
    layout.addLayout(buttons)

    def record(kind, text):
        timeline.appendPlainText(f'{time.strftime("%H:%M:%S")} [{kind}] {text}')
        LOGGER.info('[UI/%s] %s', kind, text)
        status.setText(status_text(machine))

    def perform(action):
        try:
            action()
        except (ValueError, OSError, RuntimeError) as exc:
            record('操作失败', str(exc))
            QMessageBox.warning(window, '操作失败', str(exc))

    def send_chat():
        text = chat_edit.text()
        perform(lambda: machine.send_chat(text))
        chat_edit.clear()

    def toggle_hand():
        perform(lambda: machine.set_hand_up(not machine.state.hand_up))
        hand_button.setText('取消举手' if machine.state.hand_up else '举手')

    def submit():
        caption = ('选择要提交的文件（严格批准后上传）' if config.upload_enabled
                   else '选择要提交的文件（只发送请求）')
        paths, _ = QFileDialog.getOpenFileNames(window, caption)
        if paths:
            perform(lambda: machine.submit_files(paths))

    chat_button.clicked.connect(send_chat)
    chat_edit.returnPressed.connect(send_chat)
    hand_button.clicked.connect(toggle_hand)
    info_button.clicked.connect(lambda: perform(lambda: machine.answer_info(0)))
    submit_button.clicked.connect(submit)
    login_button.clicked.connect(lambda: perform(machine.login))
    window.setCentralWidget(central)

    timer = QTimer(window)
    timer.timeout.connect(lambda: [record(kind, text) for kind, text in client.drain_events()])
    timer.start(100)
    try:
        client.start()
    except Exception:
        client.close()
        raise
    record('界面', f'已启动；日志 {LOG_PATH}')
    window.show()
    try:
        return app.exec()
    finally:
        client.close()


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cli and args.gui:
        parser.error('--cli 与 --gui 不能同时使用')
    if args.self_test:
        return run_self_test()
    setup_logging(args.verbose)
    try:
        config = make_config(args)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        if args.cli:
            return run_cli(config)
        return run_gui(config)
    except (OSError, RuntimeError) as exc:
        LOGGER.error('%s', exc)
        print(f'启动失败：{exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
