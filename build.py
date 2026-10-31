import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
WORK = ROOT / '.build'
OUTPUT = ROOT / 'build'
APP_NAME = 'JiYuControl'


def run(command):
    print('+', ' '.join(map(str, command)), flush=True)
    subprocess.run([str(part) for part in command], cwd=ROOT, check=True)


def build():
    parser = argparse.ArgumentParser(description='构建免 Python 环境的 JiYu Control 目录版程序')
    parser.add_argument('--skip-deps', action='store_true', help='跳过依赖安装')
    parser.add_argument('--onefile', action='store_true', help='兼容旧流程；不推荐，启动时需要解压')
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('独立 Windows EXE 需要在 Windows 上构建。')
    if not args.skip_deps:
        run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', 'pyinstaller>=6.0,<7'])

    import imageio_ffmpeg

    ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
    font_candidates = (
        Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'NotoSansSC-VF.ttf',
        Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'msyh.ttc',
    )
    font = next((path for path in font_candidates if path.is_file()), None)
    if font is None:
        raise SystemExit('未找到中文字体。请安装 Noto Sans SC 或微软雅黑后重新构建。')

    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir()

    assets = WORK / 'assets'
    (assets / 'fonts').mkdir(parents=True)
    bundled_ffmpeg = assets / 'ffmpeg.exe'
    bundled_font = assets / 'fonts' / 'NotoSansSC.ttf'
    shutil.copy2(ffmpeg, bundled_ffmpeg)
    shutil.copy2(font, bundled_font)

    mode = '--onefile' if args.onefile else '--onedir'
    separator = ';' if os.name == 'nt' else ':'
    run([
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--clean', mode, '--windowed',
        '--name', APP_NAME,
        '--distpath', OUTPUT,
        '--workpath', WORK / 'work',
        '--specpath', WORK,
        '--paths', ROOT,
        '--add-binary', f'{bundled_ffmpeg}{separator}.',
        '--add-data', f'{bundled_font}{separator}fonts',
        '--hidden-import', 'PIL.ImageTk',
        '--exclude-module', 'cv2',
        '--exclude-module', 'numpy',
        'teacher_gui.py',
    ])
    spec = WORK / f'{APP_NAME}.spec'
    spec_text = spec.read_text(encoding='utf-8')
    spec_text = spec_text.replace(
        'pyz = PYZ(a.pure)',
        "a.binaries = [item for item in a.binaries if 'imageio_ffmpeg' not in item[0]]\n"
        "a.datas = [item for item in a.datas if 'imageio_ffmpeg' not in item[0]]\n"
        'pyz = PYZ(a.pure)',
    )
    spec.write_text(spec_text, encoding='utf-8')
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
         '--distpath', OUTPUT, '--workpath', WORK / 'final', spec])

    executable = (OUTPUT / f'{APP_NAME}.exe' if args.onefile
                  else OUTPUT / APP_NAME / f'{APP_NAME}.exe')
    if not executable.is_file():
        raise SystemExit('构建结束但没有找到 EXE。')
    archive = None
    if not args.onefile:
        archive = shutil.make_archive(str(OUTPUT / APP_NAME), 'zip', OUTPUT, APP_NAME)
    print(f'\n构建完成：{executable}')
    if archive:
        print(f'便携压缩包：{archive}')
        print('运行方式：解压整个目录后启动 JiYuControl.exe，无需 Python、pip 或独立 FFmpeg。')
    else:
        print('目标机器无需 Python、pip 或独立 FFmpeg；单文件启动时需要解压。')


if __name__ == '__main__':
    build()
