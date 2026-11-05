"""内置无网络自检，不创建测试框架文件，也不导入教师端。"""
from __future__ import annotations

import inspect
import struct
import tempfile
import traceback
import uuid
from pathlib import Path
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


def make_machine(execute=False, **config_kwargs):
    sent = []
    events = []
    config = StudentConfig('192.0.2.10', '192.0.2.20', 1,
                           '自检计算机', '自检用户', execute=execute, **config_kwargs)
    machine = StudentMachine(config, lambda kind, data, via: sent.append((kind, data, via)),
                             lambda kind, text: events.append((kind, text)), FACTS,
                             [(0x1234, '窗口一')], [(321, 'demo.exe')])
    return machine, sent, events


def approve(machine, guid=None):
    if guid is None:
        pending = machine.state.pending_submission
        assert pending is not None
        guid = uuid.UUID(bytes_le=bytes.fromhex(pending.transaction_guid))
    response = protocol.build_submit_response(42, 1, 1, 1, transaction_guid=guid)
    machine.handle_packet(response, 'main', machine.config.teacher_ip)


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
                                             2, 0x100000005, guid, 42)
        assert len(data) == 0x284
        parsed = protocol.parse_submit_request(data)
        assert parsed['directory'] == r'C:\work'
        assert parsed['file_list'] == 'a.txt|b.txt'
        assert parsed['file_count'] == 2 and parsed['total_size'] == 0x100000005
        assert parsed['transaction_guid'] == guid.bytes_le.hex()
        assert parsed['student_id'] == 42

        response = protocol.build_submit_response(42, 1, 1, 0x100000005, 2, guid)
        assert len(response) == 52
        assert response[:4] == b'RRMS'
        assert struct.unpack_from('<III', response) == (protocol.MAGIC_RRMS, 0x10000, 0x18)
        assert response[12:28] == guid.bytes_le
        parsed_response = protocol.parse_submit_response(response)
        assert parsed_response['transaction_guid'] == guid.bytes_le.hex()
        assert parsed_response['student_id'] == 42
        assert parsed_response['fields'][1:4] == (1, 1, 5)
        assert parsed_response['quota'] == 0x100000005
        assert parsed_response['max_files'] == 2
        for invalid in (response[:-1], response + b'\x00'):
            try:
                protocol.parse_submit_response(invalid)
            except ValueError as exc:
                assert '52' in str(exc)
            else:
                raise AssertionError('RRMS 非法总长未被拒绝')
        for offset, value in ((0, protocol.MAGIC_QRMS), (4, 1), (8, 0x17)):
            invalid = bytearray(response)
            struct.pack_into('<I', invalid, offset, value)
            try:
                protocol.parse_submit_response(bytes(invalid))
            except ValueError:
                pass
            else:
                raise AssertionError(f'RRMS 非法头字段未被拒绝：offset={offset}')

    def submission_state():
        machine, sent, events = make_machine()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / 'first.txt'
            second = Path(directory) / 'second.txt'
            first.write_bytes(b'first')
            second.write_bytes(b'second!')
            machine.submit_files([str(first)])
            pending = machine.state.pending_submission
            assert pending is not None
            assert pending.student_id == 42 and pending.file_count == 1 and pending.total_size == 5
            assert pending.paths == (str(first.resolve()),)
            assert Path(pending.paths[0]).is_absolute()
            assert machine.state.submission_status == 'pending'
            assert sent[-1][0:3:2] == ('QRMS', 'main')
            request_guid = uuid.UUID(bytes_le=bytes.fromhex(pending.transaction_guid))
            approved = protocol.build_submit_response(42, 1, 1, 1,
                                                      transaction_guid=request_guid)
            machine.handle_packet(approved, 'main', '192.0.2.99')
            assert machine.state.submission_status == 'pending'
            machine.handle_packet(approved, 'main', machine.config.teacher_ip)
            assert machine.state.submission_status == 'approved'
            assert machine.state.pending_submission is None
            assert machine.state.submission_detail == '教师已接受；上传模式未启用，不会发送文件内容'
            assert len(sent) == 1
            machine.handle_packet(approved, 'main', machine.config.teacher_ip)
            assert len(sent) == 1
            assert any('重复 RRMS' in text for _, text in events)

            machine.submit_files([str(second)])
            pending = machine.state.pending_submission
            assert pending is not None and pending.total_size == 7
            current_guid = uuid.UUID(bytes_le=bytes.fromhex(pending.transaction_guid))
            assert current_guid != request_guid
            mismatch = protocol.build_submit_response(42, 1, 1, 1,
                                                      transaction_guid=request_guid)
            machine.handle_packet(mismatch, 'main', machine.config.teacher_ip)
            assert machine.state.submission_status == 'pending'
            assert any('GUID 不匹配' in text for _, text in events)
            wrong_id = protocol.build_submit_response(43, 1, 1, 1,
                                                      transaction_guid=current_guid)
            machine.handle_packet(wrong_id, 'main', machine.config.teacher_ip)
            assert machine.state.submission_status == 'pending'
            assert any('学生 ID 不匹配' in text for _, text in events)
            machine.handle_packet(approved[:-1], 'main', machine.config.teacher_ip)
            assert machine.state.submission_status == 'pending'
            assert any('格式无效' in text for _, text in events)

            rejected = protocol.build_submit_response(42, 1, 0, 1024, 3, current_guid)
            machine.handle_packet(rejected, 'main', machine.config.teacher_ip)
            assert machine.state.submission_status == 'rejected'
            assert 'arg2=0' in machine.state.submission_detail
            assert '配额=1024' in machine.state.submission_detail
            assert machine.state.pending_submission is None

            machine.submit_files([str(first)])
            current_guid = uuid.UUID(bytes_le=bytes.fromhex(
                machine.state.pending_submission.transaction_guid))
            for accept, arg2, arg3 in ((0, 1, 0), (1, 1, 0)):
                response = protocol.build_submit_response(42, accept, arg2, arg3,
                                                          transaction_guid=current_guid)
                machine.handle_packet(response, 'main', machine.config.teacher_ip)
                assert machine.state.submission_status == 'rejected'
                assert machine.state.pending_submission is None
                assert all(kind != 'RRMS' for kind, _, _ in sent)
                if accept:
                    break
                machine.submit_files([str(first)])
                current_guid = uuid.UUID(bytes_le=bytes.fromhex(
                    machine.state.pending_submission.transaction_guid))
        status = '\n'.join(machine.state.status_lines(machine.config, False))
        assert '文件提交：rejected' in status and '待回复请求：无' in status

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
        machine.handle_packet(teacher_mess(machine.config.bind_ip, 8, 0x80000000,
                                          struct.pack('<I', 4)), 'session', machine.config.teacher_ip)
        assert machine.state.screen_broadcast and machine.state.remote_view and machine.state.student_demo
        control = struct.pack('<III', 53, 8, 0) + b'MCMD' + struct.pack('<I', 2) + b'\x00' * 33
        machine.handle_packet(teacher_mess(machine.config.bind_ip, 8, 0, control[12:]),
                              'session', machine.config.teacher_ip)
        assert machine.state.remote_control
        assert any(kind == '仅提示' and '远程控制' in text for kind, text in events)
        machine.handle_packet(teacher_mess(machine.config.bind_ip, 0, 1, b'\x00'),
                              'session', machine.config.teacher_ip)
        machine.handle_packet(teacher_mess(machine.config.bind_ip, 0, 0, b'\x00'),
                              'session', machine.config.teacher_ip)
        machine.handle_packet(teacher_mess(machine.config.bind_ip, 0, 4, b'\x00'),
                              'session', machine.config.teacher_ip)
        for feature in (1, 4, 8):
            machine.handle_packet(teacher_mess(machine.config.bind_ip, feature, 0x80000000),
                                  'session', machine.config.teacher_ip)
            machine.handle_packet(teacher_mess(machine.config.bind_ip, feature, 0x10000000),
                                  'session', machine.config.teacher_ip)
        assert not machine.state.screen_broadcast and not machine.state.remote_view
        assert not machine.state.student_demo
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
        machine.event('文件提交', '时间线事件')
        assert list(client.drain_events()) == [('文件提交', '时间线事件')]
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

    def submission_paths_and_directory_rejected():
        machine, _, _ = make_machine()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / 'first.txt'
            second = Path(directory) / 'second.txt'
            first.write_bytes(b'first')
            second.write_bytes(b'second!')
            with mock.patch.object(student_core, 'upload_file') as upload:
                machine.submit_files([str(first), str(second)])
                pending = machine.state.pending_submission
                assert tuple(pending.paths) == (str(first.resolve()), str(second.resolve()))
                assert all(Path(path).is_absolute() for path in pending.paths)
                assert pending.file_count == 2 and pending.total_size == 12
                approve(machine)
                assert machine.state.submission_status == 'approved'
                assert machine.state.submission_detail == '教师已接受；上传模式未启用，不会发送文件内容'
                upload.assert_not_called()
            try:
                machine.submit_files([directory])
            except ValueError as exc:
                assert '不是可提交的文件' in str(exc)
            else:
                raise AssertionError('目录被当作可提交文件')
            assert machine.state.pending_submission is None

    def upload_gates():
        for port, flag in ((0, False), (12345, False), (0, True)):
            machine, _, _ = make_machine(upload_port=port, upload_on_approve=flag)
            assert not machine.config.upload_enabled
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / 'a.txt'
                target.write_bytes(b'a')
                with mock.patch.object(student_core, 'upload_file') as upload:
                    machine.submit_files([str(target)])
                    approve(machine)
                    assert machine.state.submission_status == 'approved'
                    upload.assert_not_called()
            status = '\n'.join(machine.state.status_lines(machine.config, False))
            assert '仅审批，不建立上传 TCP' in status

    def upload_on_approve_two_files():
        machine, sent, events = make_machine(upload_port=12345, upload_on_approve=True)
        assert machine.config.upload_enabled
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / 'first.txt'
            second = Path(directory) / 'second.txt'
            first.write_bytes(b'first')
            second.write_bytes(b'second!')
            with mock.patch.object(student_core, 'upload_file',
                                   side_effect=[5, 7]) as upload, \
                    mock.patch.object(student_core.subprocess, 'Popen') as popen, \
                    mock.patch.object(student_core.webbrowser, 'open') as browser:
                machine.submit_files([str(first), str(second)])
                guid = uuid.UUID(bytes_le=bytes.fromhex(
                    machine.state.pending_submission.transaction_guid))
                approve(machine, guid)
                assert machine.state.submission_status == 'uploaded'
                assert machine.state.pending_submission is None
                assert upload.call_args_list == [
                    mock.call('192.0.2.10', 12345, str(first.resolve())),
                    mock.call('192.0.2.10', 12345, str(second.resolve())),
                ]
                detail = machine.state.submission_detail
                assert '2/2' in detail and '12 字节' in detail
                assert str(first.resolve()) in detail and str(second.resolve()) in detail
                assert any('已上传' in text and first.name in text for _, text in events)
                assert any('已上传' in text and second.name in text for _, text in events)
                popen.assert_not_called()
                browser.assert_not_called()
                machine.handle_packet(
                    protocol.build_submit_response(42, 1, 1, 1, transaction_guid=guid),
                    'main', machine.config.teacher_ip)
                assert upload.call_count == 2
                assert machine.state.submission_status == 'uploaded'
                assert any('重复 RRMS' in text for _, text in events)
            assert len(sent) == 1 and sent[0][0] == 'QRMS'
            status = '\n'.join(machine.state.status_lines(machine.config, False))
            assert '上传模式：启用' in status and '192.0.2.10:12345' in status

    def guid_mismatch_no_upload():
        machine, _, events = make_machine(upload_port=12345, upload_on_approve=True)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'a.txt'
            target.write_bytes(b'a')
            with mock.patch.object(student_core, 'upload_file') as upload:
                machine.submit_files([str(target)])
                guid = uuid.UUID(bytes_le=bytes.fromhex(
                    machine.state.pending_submission.transaction_guid))
                wrong = protocol.build_submit_response(42, 1, 1, 1,
                                                       transaction_guid=uuid.uuid4())
                machine.handle_packet(wrong, 'main', machine.config.teacher_ip)
                assert machine.state.submission_status == 'pending'
                assert any('GUID 不匹配' in text for _, text in events)
                upload.assert_not_called()
                machine.handle_packet(
                    protocol.build_submit_response(42, 1, 1, 1, transaction_guid=guid),
                    'main', '192.0.2.99')
                machine.handle_packet(
                    protocol.build_submit_response(43, 1, 1, 1, transaction_guid=guid),
                    'main', machine.config.teacher_ip)
                machine.handle_packet(
                    protocol.build_submit_response(42, 1, 1, 1,
                                                   transaction_guid=guid)[:-1],
                    'main', machine.config.teacher_ip)
                assert machine.state.submission_status == 'pending'
                assert machine.state.pending_submission is not None
                upload.assert_not_called()
                approve(machine, guid)
                assert machine.state.submission_status == 'uploaded'
                assert upload.call_count == 1

    def rejected_no_upload():
        machine, _, _ = make_machine(upload_port=12345, upload_on_approve=True)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'a.txt'
            target.write_bytes(b'a')
            with mock.patch.object(student_core, 'upload_file') as upload:
                for accept, arg2, arg3 in ((0, 1, 1), (1, 0, 1), (1, 1, 0), (1, 0, 1024)):
                    machine.submit_files([str(target)])
                    guid = uuid.UUID(bytes_le=bytes.fromhex(
                        machine.state.pending_submission.transaction_guid))
                    response = protocol.build_submit_response(42, accept, arg2, arg3,
                                                              transaction_guid=guid)
                    machine.handle_packet(response, 'main', machine.config.teacher_ip)
                    assert machine.state.submission_status == 'rejected'
                    assert machine.state.pending_submission is None
                    assert '不会发送文件内容' in machine.state.submission_detail
                    upload.assert_not_called()

    def upload_failure_status():
        machine, _, events = make_machine(upload_port=12345, upload_on_approve=True)
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / 'first.txt'
            second = Path(directory) / 'second.txt'
            first.write_bytes(b'first')
            second.write_bytes(b'second!')
            with mock.patch.object(student_core, 'upload_file',
                                   side_effect=[5, OSError('模拟上传失败')]) as upload, \
                    mock.patch.object(student_core.subprocess, 'Popen') as popen, \
                    mock.patch.object(student_core.webbrowser, 'open') as browser:
                machine.submit_files([str(first), str(second)])
                approve(machine)
                assert machine.state.submission_status == 'upload_failed'
                assert upload.call_count == 2
                detail = machine.state.submission_detail
                assert '1/2' in detail and '12 字节' in detail
                assert '模拟上传失败' in detail
                assert str(first.resolve()) in detail and str(second.resolve()) in detail
                assert any('已上传' in text and first.name in text for _, text in events)
                assert any('上传失败' in text and second.name in text for _, text in events)
                popen.assert_not_called()
                browser.assert_not_called()
            with mock.patch.object(student_core, 'upload_file') as upload:
                machine.submit_files([str(first)])
                guid = uuid.UUID(bytes_le=bytes.fromhex(
                    machine.state.pending_submission.transaction_guid))
                machine.handle_packet(
                    protocol.build_submit_response(42, 1, 0, 1024, 3, transaction_guid=guid),
                    'main', machine.config.teacher_ip)
                assert machine.state.submission_status == 'rejected'
                assert 'arg2=0' in machine.state.submission_detail
                upload.assert_not_called()

    def upload_skips_non_files():
        machine, _, events = make_machine(upload_port=12345, upload_on_approve=True)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'a.txt'
            target.write_bytes(b'a')
            machine.submit_files([str(target)])
            target.unlink()
            target.mkdir()
            with mock.patch.object(student_core, 'upload_file') as upload:
                approve(machine)
                upload.assert_not_called()
                assert machine.state.submission_status == 'upload_failed'
                assert '路径不是文件' in machine.state.submission_detail
                assert any('上传跳过' in text for _, text in events)

    def upload_port_validation():
        for port in (-1, 65536, 99999):
            try:
                StudentConfig('192.0.2.10', '192.0.2.20', upload_port=port,
                              upload_on_approve=True)
            except ValueError as exc:
                assert '上传端口' in str(exc)
            else:
                raise AssertionError(f'非法上传端口 {port} 未被拒绝')
        for port in (0, 1, 65535):
            assert StudentConfig('192.0.2.10', '192.0.2.20', upload_port=port).upload_port == port
        assert not StudentConfig('192.0.2.10', '192.0.2.20').upload_enabled
        assert not StudentConfig('192.0.2.10', '192.0.2.20',
                                 upload_port=12345).upload_enabled
        assert not StudentConfig('192.0.2.10', '192.0.2.20',
                                 upload_on_approve=True).upload_enabled
        assert StudentConfig('192.0.2.10', '192.0.2.20',
                             upload_port=65535, upload_on_approve=True).upload_enabled

    def cli_gui_upload_options():
        try:
            from . import student_sim
        except ImportError:
            import student_sim
        parser = student_sim.build_parser()
        defaults = parser.parse_args(['--cli'])
        assert defaults.submission_port == 0 and defaults.upload_on_approve is False
        help_text = parser.format_help()
        assert '--submission-port' in help_text and '--upload-on-approve' in help_text
        args = parser.parse_args(['--gui', '--teacher-ip', '192.0.2.10',
                                  '--bind-ip', '192.0.2.20',
                                  '--submission-port', '12345', '--upload-on-approve'])
        config = student_sim.make_config(args)
        assert config.upload_port == 12345 and config.upload_on_approve is True
        assert config.upload_enabled
        text = student_sim.status_text(StudentMachine(config))
        assert '上传模式：启用' in text and '192.0.2.10:12345' in text
        plain = student_sim.make_config(parser.parse_args(
            ['--cli', '--teacher-ip', '192.0.2.10', '--bind-ip', '192.0.2.20']))
        assert plain.upload_port == 0 and not plain.upload_on_approve
        assert '上传模式：禁用' in student_sim.status_text(StudentMachine(plain))
        assert '上传' in student_sim.CLI_HELP
        assert 'status_text' in inspect.getsource(student_sim.run_cli)
        assert 'status_text' in inspect.getsource(student_sim.run_gui)
        for port in ('-1', '65536'):
            bad = parser.parse_args(['--cli', '--teacher-ip', '192.0.2.10',
                                     '--bind-ip', '192.0.2.20',
                                     '--submission-port', port])
            try:
                student_sim.make_config(bad)
            except ValueError as exc:
                assert '上传端口' in str(exc)
            else:
                raise AssertionError(f'CLI 非法端口 {port} 未被拒绝')

    for name, function in (
        ('报文构造与聊天/ANNO', packets), ('系统信息与列表分片', information),
        ('QRMS/RRMS 构造与严格解析', submission),
        ('文件提交状态/拒绝/校验/重复', submission_state),
        ('所选绝对路径与目录拒绝', submission_paths_and_directory_rejected),
        ('登录与信息请求状态', login_and_info),
        ('黑屏与解除状态', blackscreen), ('媒体/远控/LPNT 可见事件', media_and_control),
        ('危险动作即使 execute 也不执行', dangerous_actions), ('默认观察模式', observation_defaults),
        ('拒绝同机同 IP 配置', same_ip_rejected), ('无网络关闭与失败回滚', close_without_network),
        ('上传配置端口校验', upload_port_validation),
        ('默认禁用/仅审批不建立上传连接', upload_gates),
        ('批准后上传两个文件与重复回复', upload_on_approve_two_files),
        ('GUID/来源/ID 不匹配不上传', guid_mismatch_no_upload),
        ('拒绝提交不上传', rejected_no_upload),
        ('上传失败状态与拒绝逻辑不受影响', upload_failure_status),
        ('绝不上传目录或未选文件', upload_skips_non_files),
        ('CLI/GUI 上传参数与状态行', cli_gui_upload_options),
    ):
        check(name, function)
    print(f'自检结果：{sum(ok for _, ok, _ in checks)}/{len(checks)} 通过')
    return 1 if any(not ok for _, ok, _ in checks) else 0
