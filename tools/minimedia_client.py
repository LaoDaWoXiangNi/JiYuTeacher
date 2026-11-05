"""独立 MiniMedia 实验上传客户端。

可由命令行显式运行；student_sim 默认不导入或调用本模块，仅在用户
显式开启上传开关与端口后才按需调用。端口没有默认值。
"""

import argparse
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import minimedia_protocol as protocol


CHUNK_SIZE = 16 * 1024
MAX_RESPONSE = 64 * 1024
SEQUENCE = 1


class FrameReader:
    """按 12 字节头分帧，处理 TCP 拆包/粘包并限制单帧长度。"""

    def __init__(self, connection, maximum=MAX_RESPONSE):
        self.connection = connection
        self.maximum = maximum
        self.buffer = bytearray()

    def read(self):
        while len(self.buffer) < protocol.HEADER.size:
            chunk = self.connection.recv(4096)
            if not chunk:
                return None
            self.buffer.extend(chunk)
        _, _, length = protocol.HEADER.unpack_from(self.buffer)
        if length > self.maximum:
            raise ValueError(f'MiniMedia 响应帧超过长度限制：{length} > {self.maximum}')
        total = protocol.HEADER.size + length
        while len(self.buffer) < total:
            chunk = self.connection.recv(4096)
            if not chunk:
                return None
            self.buffer.extend(chunk)
        packet = bytes(self.buffer[:total])
        del self.buffer[:total]
        return protocol.decode_frame(packet)


def _read_trfd(reader, sequence):
    packet = reader.read()
    if packet is None:
        raise OSError('等待 TRFD 时连接被关闭')
    version, magic, body = packet
    if version != protocol.VERSION or magic != protocol.TRFD:
        raise ValueError(
            f'期望 TRFD，收到 version=0x{version:08X} magic=0x{magic:08X}')
    response = protocol.parse_upload_response(body)
    if response['sequence'] != sequence:
        raise ValueError(f"TRFD 序号不匹配：{response['sequence']} != {sequence}")
    if response['status'] != 0:
        raise OSError(f"服务端拒绝文件信息：status={response['status']}")
    return response


def upload_file(host, port, path, option=protocol.VERSION, timeout=10):
    source = Path(path).resolve()
    if not source.is_file():
        raise ValueError(f'上传文件不存在或不是普通文件：{source}')
    size = source.stat().st_size
    print(f'上传目标：{host}:{port}', flush=True)
    print(f'本地文件：{source}', flush=True)
    print(f'文件大小：{size} 字节', flush=True)

    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        connection.sendall(protocol.worb(option))
        connection.sendall(protocol.upload_info(SEQUENCE, source.name, size))
        _read_trfd(FrameReader(connection), SEQUENCE)

        sent = 0
        with source.open('rb') as stream:
            while True:
                data = stream.read(CHUNK_SIZE)
                connection.sendall(protocol.upload_data(SEQUENCE, data, final=False))
                if not data:
                    break
                sent += len(data)
        # 不等待、不读取任何 BFPU 回包或完成应答；结束帧发出后直接关闭连接。

    print(f'已发送 {sent} 字节数据及零长度结束帧；未等待完成应答', flush=True)
    return sent


def _port(value):
    try:
        port = int(value, 10)
    except ValueError:
        raise argparse.ArgumentTypeError(f'端口必须是整数：{value}')
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError('端口必须在 1 到 65535 之间')
    return port


def _option(value):
    try:
        return int(value, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(f'option 必须是整数：{value}')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='独立 MiniMedia 实验上传工具（端口必须显式配置；模拟端默认关闭上传）')
    parser.add_argument('--host', required=True, help='MiniMedia 服务端 IP')
    parser.add_argument('--port', required=True, type=_port,
                        help='MiniMedia 服务端端口，无默认值')
    parser.add_argument('--option', type=_option, default=protocol.VERSION,
                        help='WORB 首包 option，默认 0x10000')
    parser.add_argument('--timeout', type=float, default=10,
                        help='连接与读超时秒数，默认 10')
    parser.add_argument('file', help='用户显式选择的本地文件')
    args = parser.parse_args(argv)

    try:
        upload_file(args.host, args.port, args.file,
                    option=args.option, timeout=args.timeout)
    except (OSError, ValueError) as error:
        print(f'上传失败：{error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
