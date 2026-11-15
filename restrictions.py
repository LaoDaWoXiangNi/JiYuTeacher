#!/usr/bin/env python3
"""极域电子教室 V6.0「行为限制」命令的 payload 编解码（纯 Python，无 Qt 依赖）。

命令形式：COMD 事件 0x80000010，内层 category=0x200、command_id=0x17，
内层 payload 固定 32 字节、小端序：

    +0x00 category=0x200   +0x04 flags=0   +0x08 command=0x17
    +0x0c App   +0x10 Web   +0x14 U 盘   +0x18 光驱   +0x1c 打印

取值语义（证据：temp/policy-enums-findings.md，StudentMain.exe 反汇编）：

* **U 盘 / 光驱**（+0x14 / +0x18）：0=Free 开放、1=Readonly 只读、
  2=NoExecute 禁止执行、3=Block 完全禁止；>3 落 default 分支，学生端 no-op。
* **打印**（+0x1c）：0=UNRESTRICTED 不限制、2=Block All 全部禁止；
  1/3/>3 学生端 no-op，语义未知。
* **App / Web**（+0x0c / +0x10）：学生端**不校验、不解释**，只做
  “与旧值比较 → 保存 → 广播给教师端 → 若变化则重取策略文件”。
  0 是默认/复位值，1/2/3 的语义未验证。

本模块只负责字节编解码，不做任何 IO。模拟学生端对控制类命令一律
“只记录、不执行”，所以这里也不会产生任何真实限制动作。
"""

import struct
import sys

try:  # 控制台默认代码页不是 UTF-8 时避免自测输出乱码
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:  # noqa: BLE001 - 某些嵌入式解释器不支持 reconfigure
    pass

__all__ = [
    'CATEGORY', 'COMMAND', 'PAYLOAD_SIZE',
    'USB_STATES', 'CD_STATES', 'PRINT_STATES', 'APP_STATES',
    'build_restriction_payload', 'parse_restriction_payload',
    'describe_restrictions', 'is_noop',
]

CATEGORY = 0x200
COMMAND = 0x17
PAYLOAD_SIZE = 32

#: U 盘策略：0..3 已由 StudentMain.exe fcn.0043A700 的跳转表证实
USB_STATES = {
    0: 'Free / 开放',
    1: 'Readonly / 只读',
    2: 'NoExecute / 禁止执行',
    3: 'Block / 完全禁止',
}

#: 光驱策略：0..3 已由 StudentMain.exe fcn.0043A7D0 的跳转表证实
CD_STATES = {
    0: 'Free / 开放',
    1: 'Readonly / 只读',
    2: 'NoExecute / 禁止执行',
    3: 'Block / 完全禁止',
}

#: 打印策略：只有 0 与 2 已由 StudentMain.exe fcn.00441400 证实
PRINT_STATES = {
    0: 'UNRESTRICTED / 不限制',
    2: 'Block All / 全部禁止',
}

#: App / Web 策略：学生端只保存不解释，1/2/3 语义未知
APP_STATES = {
    0: '默认值 0（语义未验证）',
    1: '值 1（语义未验证）',
    2: '值 2（语义未验证）',
    3: '值 3（语义未验证）',
}

_FIELDS = ('app', 'web', 'usb', 'cd', 'printer')


def _check_dword(name, value):
    """App/Web 用：必须是 int（bool 也算越界），0..0xFFFFFFFF。"""
    if type(value) is not int:
        raise ValueError(f'{name} 策略必须是整数，收到 {value!r}')
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f'{name} 策略必须是 0..0xFFFFFFFF 的 32 位值，收到 {value!r}')
    return value


def build_restriction_payload(app=0, web=0, usb=0, cd=0, printer=0):
    """构造 32 字节行为限制 payload（小端）。

    越界值抛中文 ``ValueError``。``printer`` 只接受 0 或 2，因为学生端
    对 1/3/>3 是 no-op（不写共享内存、不触发事件）。
    """
    _check_dword('App', app)
    _check_dword('Web', web)
    if type(usb) is not int or not 0 <= usb <= 3:
        raise ValueError(f'U 盘策略必须是 0..3 的整数，收到 {usb!r}')
    if type(cd) is not int or not 0 <= cd <= 3:
        raise ValueError(f'光驱策略必须是 0..3 的整数，收到 {cd!r}')
    if type(printer) is not int or printer not in PRINT_STATES:
        raise ValueError(
            f'打印策略只接受 0 或 2（学生端对其它值 no-op），收到 {printer!r}')
    payload = struct.pack('<IIIIIIII', CATEGORY, 0, COMMAND,
                          app, web, usb, cd, printer)
    assert len(payload) == PAYLOAD_SIZE, '行为限制 payload 长度错误'
    return payload


def _state_text(name, value):
    """把单个策略值渲染成中文；未定义值不抛异常，标 no-op。"""
    table = {'usb': USB_STATES, 'cd': CD_STATES, 'printer': PRINT_STATES}
    if name in table:
        states = table[name]
        if value in states:
            return states[value]
        return f'{value}（学生端 no-op，语义未知）'
    if type(value) is int and 0 <= value <= 0xFFFFFFFF:
        return f'{value}（语义未验证）'
    return f'{value!r}（非法值）'


def _values(values=None, kwargs=None):
    """把 dict 与关键字合并成五个整数字段，缺省按 0。"""
    merged = {name: 0 for name in _FIELDS}
    if isinstance(values, dict):
        for name in _FIELDS:
            if name in values:
                merged[name] = values[name]
    elif values is not None:
        raise ValueError(f'values 必须是 dict，收到 {type(values).__name__}')
    if kwargs:
        for name in _FIELDS:
            if name in kwargs:
                merged[name] = kwargs[name]
    return merged


def _describe(merged):
    """一行中文摘要，字段顺序固定，便于日志 grep。"""
    return '，'.join((
        f'U盘={_state_text("usb", merged["usb"])}',
        f'光驱={_state_text("cd", merged["cd"])}',
        f'打印={_state_text("printer", merged["printer"])}',
        f'App={_state_text("app", merged["app"])}',
        f'Web={_state_text("web", merged["web"])}',
    ))


def describe_restrictions(values=None, **kwargs):
    """把五项策略渲染成一行中文。

    ``values`` 可以是 dict（``{'usb': 1}``），也可以直接给关键字
    （``describe_restrictions(usb=1)``）；两者同时出现时关键字优先。
    越界值不抛异常，写成“（学生端 no-op，语义未知）”。
    """
    return _describe(_values(values, kwargs))


def is_noop(values=None, **kwargs):
    """五项全为 0 时返回 True：这条命令不会对学生机产生任何实际改变。

    只有 App/Web/U 盘/光驱/打印全部为 0 才算 no-op（= 恢复默认）。
    """
    merged = _values(values, kwargs)
    return all(merged[name] == 0 for name in _FIELDS)


def parse_restriction_payload(payload):
    """解析内层 payload，返回 dict。

    长度 < 32 抛中文 ``ValueError``；超过 32 字节时只解析前 32 字节
    （真实 COMD 包尾部会补 4 字节 NUL，必须容忍）。

    返回字段：category/flags/command/app/web/usb/cd/printer 以及
    ``verified``（逐项 bool；App/Web 恒为 False，因为学生端不解释）、
    ``known``（包头三项是否全部符合预期）、``noop_fields``（学生端会
    忽略的字段名）、``summary``（一行中文）。
    """
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ValueError(f'payload 必须是 bytes，收到 {type(payload).__name__}')
    data = bytes(payload)
    if len(data) < PAYLOAD_SIZE:
        raise ValueError(
            f'行为限制 payload 至少需要 {PAYLOAD_SIZE} 字节，实际 {len(data)} 字节')
    fields = struct.unpack_from('<8I', data, 0)
    category, flags, command = fields[0], fields[1], fields[2]
    app, web, usb, cd, printer = fields[3], fields[4], fields[5], fields[6], fields[7]
    verified = {
        'category': category == CATEGORY,
        'flags': flags == 0,
        'command': command == COMMAND,
        'usb': usb in USB_STATES,
        'cd': cd in CD_STATES,
        'printer': printer in PRINT_STATES,
        'app': False,   # 学生端不校验不解释，永远无法验证语义
        'web': False,
    }
    noop_fields = [name for name in ('usb', 'cd', 'printer')
                   if not verified[name]]
    merged = {'app': app, 'web': web, 'usb': usb, 'cd': cd, 'printer': printer}
    return {
        'category': category,
        'flags': flags,
        'command': command,
        'app': app,
        'web': web,
        'usb': usb,
        'cd': cd,
        'printer': printer,
        'verified': verified,
        'known': bool(verified['category'] and verified['flags']
                      and verified['command']),
        'noop_fields': noop_fields,
        'summary': _describe(merged),
    }


# ------------------------------------------------------------------ 自测


def _self_test():
    checks = []

    def check(title, function):
        try:
            function()
        except AssertionError as error:
            checks.append((title, False, str(error) or '断言失败'))
        except Exception as error:  # noqa: BLE001
            checks.append((title, False, f'{type(error).__name__}: {error}'))
        else:
            checks.append((title, True, ''))

    def t_length():
        payload = build_restriction_payload()
        assert len(payload) == PAYLOAD_SIZE == 32, len(payload)

    def t_offsets():
        payload = build_restriction_payload(app=1, web=2, usb=3, cd=1, printer=2)
        got = struct.unpack('<8I', payload)
        want = (0x200, 0, 0x17, 1, 2, 3, 1, 2)
        assert got == want, got
        assert struct.unpack_from('<I', payload, 0x0c)[0] == 1     # App
        assert struct.unpack_from('<I', payload, 0x10)[0] == 2     # Web
        assert struct.unpack_from('<I', payload, 0x14)[0] == 3     # U 盘
        assert struct.unpack_from('<I', payload, 0x18)[0] == 1     # 光驱
        assert struct.unpack_from('<I', payload, 0x1c)[0] == 2     # 打印

    def t_roundtrip():
        values = {'app': 2, 'web': 1, 'usb': 1, 'cd': 0, 'printer': 2}
        parsed = parse_restriction_payload(build_restriction_payload(**values))
        for name, want in values.items():
            assert parsed[name] == want, (name, parsed[name], want)

    def t_bad_values():
        for kwargs in ({'usb': 4}, {'cd': -1}, {'usb': 999}, {'cd': None}):
            try:
                build_restriction_payload(**kwargs)
            except ValueError:
                continue
            raise AssertionError(f'{kwargs} 应当抛 ValueError')
        for printer in (1, 3, 4, -1):
            try:
                build_restriction_payload(printer=printer)
            except ValueError:
                continue
            raise AssertionError(f'printer={printer} 应当抛 ValueError')

    def t_bool_rejected():
        for kwargs in ({'app': True}, {'web': False}):
            try:
                build_restriction_payload(**kwargs)
            except ValueError:
                continue
            raise AssertionError(f'{kwargs} 的 bool 应被拒绝')

    def t_short_payload():
        try:
            parse_restriction_payload(b'\x00' * 20)
        except ValueError:
            return
        raise AssertionError('20 字节 payload 应当抛 ValueError')

    def t_tail_tolerated():
        payload = build_restriction_payload(usb=1)
        parsed = parse_restriction_payload(payload + b'\x00' * 4)
        assert parsed['usb'] == 1, parsed
        assert parsed['known'] is True, parsed

    def t_describe():
        text = describe_restrictions(usb=1, printer=2)
        assert '只读' in text, text
        assert '全部禁止' in text, text
        assert '未验证' in text or '语义未验证' in text, text
        bad = describe_restrictions({'printer': 1})
        assert 'no-op' in bad, bad

    def t_is_noop():
        assert is_noop() is True
        assert is_noop({}) is True
        assert is_noop(usb=1) is False
        assert is_noop(app=0, web=0, usb=0, cd=0, printer=0) is True

    def t_appweb_unverified():
        parsed = parse_restriction_payload(
            build_restriction_payload(app=0, web=0))
        assert parsed['verified']['app'] is False
        assert parsed['verified']['web'] is False
        assert parsed['verified']['usb'] is True
        assert parsed['verified']['printer'] is True
        assert parsed['noop_fields'] == [], parsed['noop_fields']

    def t_noop_fields_detected():
        raw = bytearray(build_restriction_payload())
        struct.pack_into('<I', raw, 0x14, 7)   # U 盘 >3：学生端走 default
        struct.pack_into('<I', raw, 0x1c, 1)   # 打印 1：学生端 no-op
        parsed = parse_restriction_payload(bytes(raw))
        assert parsed['noop_fields'] == ['usb', 'printer'], parsed['noop_fields']
        assert parsed['verified']['usb'] is False
        assert parsed['verified']['printer'] is False

    def t_packet_header_mismatch():
        payload = bytearray(build_restriction_payload())
        struct.pack_into('<I', payload, 0, 0x4000)
        parsed = parse_restriction_payload(bytes(payload))
        assert parsed['known'] is False
        assert parsed['verified']['category'] is False

    for title, function in (
            ('payload 长度 == 32', t_length),
            ('五个策略值偏移 +0x0c/+0x10/+0x14/+0x18/+0x1c', t_offsets),
            ('build/parse 往返一致', t_roundtrip),
            ('U 盘/光驱/打印越界抛中文 ValueError', t_bad_values),
            ('bool 不算 int，被拒绝', t_bool_rejected),
            ('不足 32 字节抛 ValueError', t_short_payload),
            ('容忍尾部补 4 字节 NUL', t_tail_tolerated),
            ('describe_restrictions 中文摘要', t_describe),
            ('is_noop 判定', t_is_noop),
            ('App/Web 恒为未验证', t_appweb_unverified),
            ('noop_fields 标出学生端会忽略的字段', t_noop_fields_detected),
            ('包头 category 不符时 known=False', t_packet_header_mismatch),
    ):
        check(title, function)

    passed = 0
    for index, (title, ok, detail) in enumerate(checks, 1):
        if ok:
            passed += 1
            print(f'PASS {index}-{title}')
        else:
            print(f'FAIL {index}-{title}：{detail}')
    print(f'{passed}/{len(checks)} PASS')
    return 0 if passed == len(checks) else 1


if __name__ == '__main__':
    sys.exit(_self_test())
