# JiYu Studio

极域电子教室 V6.0 的第三方教师端实现。使用 Python 处理网络协议，使用 PyQt6 提供原生桌面界面，无需 Electron、浏览器或独立前端服务。

本项目基于已有的 CLI 协议研究成果改编，当前阶段重点是桌面交互，不代表已经覆盖官方教师端全部功能。后续协议分析仍在继续。

## 界面与功能

- 课堂总览：在线学生、计算机名称、实时缩略图、搜索与全班预览。
- 学生信号：解析学生端 ANNO 状态块，显示举手状态与人数，并保留状态标志供诊断。
- 文件提交监测：识别 QRMS 请求，显示事务 GUID、目录、文件列表和总大小；暂不自动接受或接收文件。
- 学生管理：设备信息、进程列表、窗口列表。
- 远程操作：连续观看、远程控制、黑屏与解锁、消息、远程运行、打开网页。
- 屏幕广播：支持 feature 1 启停协议与状态管理；媒体推流尚未完成，启动按钮不代表学生端已显示画面。
- 进程与窗口管理：按已上报的 PID 或窗口句柄发送结束命令。
- 电源操作：关机、重启，支持倒计时提示；执行前二次确认。
- 日志：在界面中查看协议事件和错误，可切换 DEBUG 文件日志。

CLI 入口保留，便于协议调试。

## 环境

- Windows 10/11。
- Python 3.10 或更高版本。
- 学生端与本机位于同一局域网，UDP 组播或广播可达。
- 已允许 Python 通过 Windows 防火墙。

连续 H.264 观看依赖 `imageio-ffmpeg` 提供的 FFmpeg。远程控制沿用原实现的独立显示窗口，键盘兼容性仍是实验状态。

## 安装与启动

建议在虚拟环境中安装依赖：

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python teacher_gui.py
```

也可以直接在已有 Python 环境中运行：

```bash
python -m pip install -r requirements.txt
python teacher_gui.py
```

启动 GUI 时会绑定协议端口并发送教师端发现宣告。仅进行界面开发时，可设置 `QT_QPA_PLATFORM=offscreen` 做离屏验证，不要把离屏测试当成协议实机验证。

## 一键构建独立 EXE

```bash
python build.py
```

脚本自动安装构建依赖，默认生成目录版：

```text
build/JiYuControl/JiYuControl.exe
build/JiYuControl.zip
```

目录已包含 Python 运行时、Qt、Pillow、Tk、中文字体和 FFmpeg。将 ZIP 解压到目标 Windows x64 机器后，运行目录内的 EXE 即可，不需要安装 Python、pip 或独立解码器。请保留整个程序目录，不要只复制 EXE。

目录版不需要在每次启动时解压，启动性能优于单文件。已安装全部依赖时可用 `python build.py --skip-deps` 加速后续构建；`python build.py --onefile` 仍提供兼容的单文件构建。

构建目录与中间文件不进入 Git。

原 CLI：

```bash
python teacher_sim.py
```

CLI 输入 `help` 查看完整命令。

## 网络配置

默认监听：

| 通道 | 地址 | 用途 |
| --- | --- | --- |
| 主通道 | `224.50.50.42:4705/UDP` | 发现、控制、缩略图 |
| 会话通道 | 按频道计算，频道 1 为 `225.2.2.1:5512/UDP` | 登录、消息、信息上报 |
| 连续观看 | 学生端 `4806/TCP` | UMSP channel 10 桌面流 |

自动选错网卡时，可在启动前指定：

```powershell
$env:TEACHER_IP = "192.168.1.10"
$env:TEACHER_CHANNEL = "1"
python teacher_gui.py
```

常用可选环境变量：

| 变量 | 作用 |
| --- | --- |
| `TEACHER_IP` | 指定本机 IPv4 地址 |
| `TEACHER_PEER_IP` | 指定学生机提示地址，辅助选择直连网卡 |
| `TEACHER_NETWORK` | 限定本机网段，例如 `192.168.1.0/24` |
| `TEACHER_CHANNEL` | 频道，范围 1–32 |
| `TEACHER_NAME` | 教师显示名称 |
| `TEACHER_TCP_PORT` | 连续观看端口，默认 4806 |
| `TEACHER_CONTROL_MODE` | 远控模式，默认 2；0 为 Share |
| `TEACHER_SAVE_PREVIEWS` | 设为 1 时将最新修复预览保存到桌面 |

运行日志写入程序所在目录的 `teacher_sim.log`，包含网络协议事件及 `[UI]` 操作记录。日志采用 UTF-8，单份最大 10 MiB，自动保留三份轮转备份，启动时不会清空历史记录。连续观看输出位于同级 `teacher_remote_view` 目录。

## 使用注意

1. 先确认学生出现在课堂总览，再请求信息或预览。
2. 连续观看前建议用 CLI 的 `view_probe <IP>` 检查 TCP 端口。
3. 远控依赖已建立的观看通道；键盘输入尚未在所有 Windows 会话上验证。
4. 黑屏设为 0 秒时需手动解除；退出程序不会代替你验证学生端已恢复。
5. 结束进程、关机与重启没有可靠的结果回执，应刷新信息或通过其他方式核实。

## 项目结构

```text
teacher_gui.py    Qt 桌面界面
teacher_sim.py    协议实现、网络收发、观看与远控、CLI
gui_events.py     后端到 GUI 的轻量事件桥接
build.py          一键构建独立 EXE
requirements.txt  Python 依赖
temp/             本地分析材料，不进入 Git
```

## 当前边界

- 已保留原项目已实现的 V6.0 登录、保活、消息、缩略图、黑屏、信息上报、进程/窗口和远程命令路径。
- 连续观看和远程控制仍依赖原实现与学生端编码器状态；本阶段没有重新逆向这些协议。
- 尚未声称支持官方教师端的全部事件、信号、广播教学、文件分发、考试等功能。
- 没有真实学生端的环境只能验证界面与代码路径，不能证明网络兼容性。

## 逆向分析材料

本地样本与分析输出放入 `temp/`，该目录已被 Git 忽略。只进行静态提取和分析，不执行安装程序或样本本体。

## 免责声明

本项目是独立第三方实现，与极域电子教室官方无关，仅供协议学习、互操作研究和教学演示。请仅在你负责且获明确授权的设备和网络中使用。远程观看、输入控制、结束进程和电源操作可能影响他人工作与数据；使用者应自行评估并承担使用本软件及 AI 生成代码所产生的全部责任。

## 许可证

MIT，见 [LICENSE](LICENSE)。
