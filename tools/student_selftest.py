"""内置无网络自检，不创建测试框架文件，也不导入教师端。"""
from __future__ import annotations

import struct
import traceback
import uuid
from unittest import mock

try:
    from . import student_protocol as protocol
    from . import student_core
except ImportError:
    import student_protocol as protocol
    import student_core

StudentConfig = student_core.StudentConfig
StudentMachine = student_core.StudentMachine


FACTS = {
    'name': '自检计算机', 'stu_id': 42, 'mac': bytes.fromhex('001122334455'),
    'user': '自检用户', 'os': 'TestOS', 'osver': '1.0',
    'cpu_vendor': 'TestCPU', 'cpu_model': 'Virtual Processor', 'mem': '1024 MB',
}


def make_machine(execute=False):
    sent = []
    events = []
    config = StudentConfig('192.0.2.10', '192.0.2.20', 1,
                           '自检计算机', '自检用户', execute=execute)
    machine = StudentMachine(config, lambda kind, data, via: sent.append((kind, data, via)),
                             lambda kind, text: events.append((kind, text)), FACTS,
                             [(0x1234, '窗口一')], [(321, 'demo.exe')])
    return machine, sent, events


def teacher_mess(student_ip, msg_type, category=0, rest=b''):
    payload = struct.pack('<III', 12 + len(rest), msg_type, category) + rest
    return protocol.build_mess(student_ip, payload)


def app_packet(command, extra):
    payload = struct.pack('<III', 0x200, 0, command) + extra
    inner = struct.pack('<IIII', 0x80000010, 7, len(payload), 0) + payload
    return struct.pack('<III', protocol.MAGIC_DMOC, 0x10000, len(inner)) + uuid.uuid4().bytes_le + inner


def run_self_test() -> int:
    checks = []

    def check(name, function):
        try:
            function()
            checks.append((name, True, ''))
            print(f'[PASS] {name}')
        except Exception as exc:
            checks.append((name, False, str(exc)))
            print(f'[FAIL] {name}: {exc}')
            traceback.print_exc()

    def packets():
        assert protocol.session_endpoint(1) == ('225.2.2.1', 5512)
        assert protocol.session_endpoint(32) == ('225.2.33.1', 21384)
        login = protocol.build_logi('192.0.2.20', 'PC', 'User', 3, 42)
        assert len(login) == 0x300 and struct.unpack_from('<I', login)[0] == protocol.MAGIC_LOGI
        chat = protocol.build_chat('192.0.2.10', '你好')
        _, _, recipients, payload = protocol.split_mess(chat)
        assert recipients == ('192.0.2.10',)
        assert struct.unpack_from('<I', payload, 4)[0] == 0x800
        assert protocol.decode_wstr(payload[16:]) == '你好'
        anno = protocol.build_anno(True, 0x20)
        assert len(anno) == 72
        assert struct.unpack_from('<16I', anno, 8)[2] & protocol.HAND_UP_FLAG
        assert not struct.unpack_from('<16I', protocol.build_anno(False), 8)[2] & protocol.HAND_UP_FLAG

    def information():
        packets = protocol.build_info_reply('192.0.2.10', 0, FACTS,
                                           [(1, '甲'), (2, '乙')], [(9, 'p.exe')])
        assert len(packets) == 3
        _, _, _, system = protocol.split_mess(packets[0])
        assert len(system) == 0x2FA
        assert struct.unpack_from('<I', system, 4)[0] == 0
        assert struct.unpack_from('<I', system, 8)[0] == 0x800000
        assert struct.unpack_from('<I', system, 12)[0] == 5
        assert protocol.decode_wstr(system[0x10:0x50]) == '自检计算机'
        assert protocol.decode_wstr(system[0x5A:0x9A]) == '自检用户'
        assert system[0x54:0x5A] == bytes.fromhex('001122334455')
        assert struct.unpack_from('<I', system, 0x50)[0] == 42
        for packet, subtype in zip(packets[1:], (6, 7)):
            _, _, _, payload = protocol.split_mess(packet)
            assert struct.unpack_from('<I', payload, 12)[0] == subtype
            assert struct.unpack_from('<I', payload, 16)[0] == 1
            assert protocol.decode_id_name_pairs(payload[20:])
        many = [(index, 'x' * 80) for index in range(30)]
        chunks = protocol.build_info_list('192.0.2.10', 7, many, max_chunk=400)
        assert len(chunks) > 1
        decoded = []
        for index, packet in enumerate(chunks):
            _, _, _, payload = protocol.split_mess(packet)
            assert struct.unpack_from('<I', payload, 16)[0] == (1 if index == 0 else 0)
            decoded.extend(protocol.decode_id_name_pairs(payload[20:]))
        assert decoded == many

    def submission():
        guid = uuid.UUID('00112233-4455-6677-8899-aabbccddeeff')
        data = protocol.build_submit_request('192.0.2.10', r'C:\work', 'a.txt|b.txt',
                                             2, 0x100000005, guid)
        assert len(data) == 0x284
        parsed = protocol.parse_submit_request(data)
        assert parsed['directory'] == r'C:\work'
        assert parsed['file_list'] == 'a.txt|b.txt'
        assert parsed['file_count'] == 2 and parsed['total_size'] == 0x100000005
        assert parsed['transaction_guid'] == guid.bytes_le.hex()

    def login_and_info():
        machine, sent, events = make_machine()
        for msg_type in (0x1000, 0x8000):
            machine.handle_packet(teacher_mess(machine.config.bind_ip, msg_type), 'session',
                                  machine.config.teacher_ip)
        assert machine.state.online and machine.state.login_replies == {0x1000, 0x8000}
        info_packets = [item for item in sent if item[0] == 'MESS']
        assert len(info_packets) == 3
        sent.clear()
        request = protocol.build_mess(machine.config.bind_ip,
                                      protocol.message_payload(0x100000, 0, 1))
        machine.handle_packet(request, 'session', machine.config.teacher_ip)
        assert len(sent) == 1
        assert any(kind == '信息上报' for kind, _ in events)

    def blackscreen():
        machine, sent, _ = make_machine()
        rest = struct.pack('<IIIIII', 1, 1, 10, 1, 0xFFFF, 0) + '请安静'.encode('utf-16-le') + b'\x00\x00'
        data = teacher_mess(machine.config.bind_ip, 0x20, 0x80000000, rest)
        machine.handle_packet(data, 'session', machine.config.teacher_ip)
        assert machine.state.blackscreen and machine.state.lock_requested
        assert machine.state.blackscreen_text == '请安静'
        assert sent[-1][0] == 'ANNO'
        unlock = protocol.build_mess(machine.config.bind_ip,
                                    struct.pack('<III', 13, 0x20, 0x90000000) + b'\x01')
        machine.handle_packet(unlock, 'session', machine.config.teacher_ip)
        assert not machine.state.blackscreen and not machine.state.lock_requested

    def media_and_control():
        machine, _, events = make_machine(execute=True)
        machine.handle_packet(teacher_mess(machine.config.bind_ip, 8, 0x80000000,
                                          struct.pack('<I', 1)), 'session', machine.config.teacher_ip)
        machine.handle_packet(teacher_mess(machine.config.bind_ip, 8, 0x80000000,
                                          struct.pack('<I', 8)), 'session', machine.config.teacher_ip)
        assert machine.state.screen_broadcast and machine.state.remote_view
        control = struct.pack('<III', 53, 8, 0) + b'MCMD' + struct.pack('<I', 2) + b'\x00' * 33
        machine.handle_packet(teacher_mess(machine.config.bind_ip, 8, 0, control[12:]),
                              'session', machine.config.teacher_ip)
        assert machine.state.remote_control
        assert any(kind == '仅提示' and '远程控制' in text for kind, text in events)
        machine.handle_packet(teacher_mess(machine.config.bind_ip, 0, 1, b'\x00'),
                              'session', machine.config.teacher_ip)
        machine.handle_packet(teacher_mess(machine.config.bind_ip, 0, 0, b'\x00'),
                              'session', machine.config.teacher_ip)
        assert not machine.state.screen_broadcast and not machine.state.remote_view
        lpnt = struct.pack('<III', protocol.MAGIC_LPNT, 0x10000, 20) + protocol.LPNT_GUID
        lpnt += struct.pack('<IIIII', 3, 1, 80, 60, 5)
        machine.handle_packet(lpnt, 'main', machine.config.teacher_ip)
        assert machine.state.preview_enabled and machine.state.preview_version == 3

    def dangerous_actions():
        machine, _, events = make_machine(execute=True)
        with mock.patch.object(student_core.subprocess, 'Popen') as popen, \
                mock.patch.object(student_core.webbrowser, 'open') as browser:
            for command in (0x13, 0x14, 6):
                machine.handle_packet(app_packet(command, b'\x00' * 40), 'main', machine.config.teacher_ip)
            kill = protocol.build_mess(machine.config.bind_ip,
                                      protocol.message_payload(0x100000, 0, 4, b'\x00' * 12))
            machine.handle_packet(kill, 'session', machine.config.teacher_ip)
            machine.handle_packet(app_packet(0x18, 'file:///C:/Windows/System32/calc.exe'.encode('utf-16-le') + b'\x00\x00'),
                                  'main', machine.config.teacher_ip)
            machine.handle_packet(app_packet(0x0F, struct.pack('<I', 1) +
                                              r'C:\Windows\System32\cmd.exe'.encode('utf-16-le').ljust(512, b'\x00') +
                                              b'\x00' * 324), 'main', machine.config.teacher_ip)
            popen.assert_not_called()
            browser.assert_not_called()
        assert machine.state.online is False
        assert any('关机' in text for _, text in events)
        assert any('重启' in text for _, text in events)
        assert any('结束进程' in text for _, text in events)

    def observation_defaults():
        machine, _, _ = make_machine(execute=False)
        with mock.patch.object(student_core.subprocess, 'Popen') as popen, \
                mock.patch.object(student_core.webbrowser, 'open') as browser:
            assert not machine.safe_open_url('https://example.com')
            assert not machine.safe_run_program('notepad.exe', '', 0)
            popen.assert_not_called()
            browser.assert_not_called()

    def same_ip_rejected():
        try:
            StudentConfig('192.0.2.10', '192.0.2.10')
        except ValueError as exc:
            assert '忽略自身 IP' in str(exc)
        else:
            raise AssertionError('同 IP 配置未被拒绝')

    def close_without_network():
        machine, _, _ = make_machine()
        client = student_core.UdpStudentClient(machine)
        machine.state.online = True
        machine.state.login_replies = {0x1000, 0x8000}
        client.close()
        client.close()
        assert client.main_socket is None and client.session_socket is None
        assert not client.threads and not machine.state.online
        assert not machine.state.login_replies
        try:
            machine.login()
        except RuntimeError as exc:
            assert '尚未启动' in str(exc)
        else:
            raise AssertionError('关闭后仍可发送')

        old_stop = client.stop_event
        with mock.patch.object(client, '_make_socket') as make_socket, \
                mock.patch.object(client, 'close') as close:
            make_socket.side_effect = OSError('模拟发送失败')
            try:
                client.start()
            except OSError:
                pass
            else:
                raise AssertionError('启动失败未传播')
            close.assert_called_once()
            assert client.stop_event is not old_stop and not client.stop_event.is_set()

    for name, function in (
        ('报文构造与聊天/ANNO', packets), ('系统信息与列表分片', information),
        ('QRMS 文件提交请求', submission), ('登录与信息请求状态', login_and_info),
        ('黑屏与解除状态', blackscreen), ('媒体/远控/LPNT 可见事件', media_and_control),
        ('危险动作即使 execute 也不执行', dangerous_actions), ('默认观察模式', observation_defaults),
        ('拒绝同机同 IP 配置', same_ip_rejected), ('无网络关闭与失败回滚', close_without_network),
    ):
        check(name, function)
    print(f'自检结果：{sum(ok for _, ok, _ in checks)}/{len(checks)} 通过')
    return 1 if any(not ok for _, ok, _ in checks) else 0
