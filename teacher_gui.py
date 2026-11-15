import logging
import os
import sys
import time
from functools import partial

from PyQt6.QtCore import (
    QDateTime, QItemSelectionModel, QObject, QRectF, QSize, Qt, QThread, QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSlider, QSpinBox,
    QSplitter, QStackedWidget, QFileDialog, QInputDialog,
    QTabWidget, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

import app_config
import gui_events

CHANNEL_FROM_ENV = 'TEACHER_CHANNEL' in os.environ
SUBMISSION_PORT_FROM_ENV = app_config.has_explicit_submission_port()
if not CHANNEL_FROM_ENV:
    os.environ['TEACHER_CHANNEL'] = str(app_config.load_channel())

import teacher_sim as core


INK = '#20252e'
MUTED = '#6b7482'
BORDER = '#d2d9e2'
SHELL = '#eef1f5'
PANEL = '#ffffff'
ACCENT = '#2b7cd3'
ACCENT_SOFT = '#e7f1fc'
DANGER = '#c0392b'
SUCCESS = '#177245'

TOOLBAR_ITEMS = (
    ('屏幕广播', 'broadcast', 'experimental'),
    ('学生演示', 'demo', 'experimental'),
    ('网络影院', 'cinema', 'unavailable'),
    ('视频直播', 'live', 'unavailable'),
    ('共享白板', 'whiteboard', 'unavailable'),
    ('监控', 'monitor', 'ready'),
    ('远程命令', 'command', 'ready'),
    ('讨论', 'discuss', 'unavailable'),
    ('分组教学', 'group', 'unavailable'),
    ('考试', 'exam', 'unavailable'),
    ('调查', 'survey', 'unavailable'),
    ('抢答竞赛', 'contest', 'unavailable'),
    ('文件分发', 'distribute', 'unavailable'),
    ('文件收集', 'collect', 'ready'),
)

STARTUP_WARNINGS = []
RUNNING_WORKERS = []


def load_ui_fonts():
    if getattr(sys, 'frozen', False):
        folder = os.path.join(sys._MEIPASS, 'fonts')
        loaded = False
        for filename in ('NotoSansSC.ttf', 'CascadiaMono.ttf'):
            path = os.path.join(folder, filename)
            if os.path.isfile(path):
                loaded = QFontDatabase.addApplicationFont(path) != -1 or loaded
        if loaded:
            return
    fonts_dir = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
    for filename in ('msyh.ttc', 'simhei.ttf', 'simsun.ttc', 'segoeui.ttf'):
        path = os.path.join(fonts_dir, filename)
        if os.path.isfile(path):
            QFontDatabase.addApplicationFont(path)


def icon(name, color=ACCENT, size=24):
    image = QPixmap(size, size)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.7, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.scale(size / 24.0, size / 24.0)

    def line(x1, y1, x2, y2):
        painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def rect(x, y, w, h, radius=2):
        painter.drawRoundedRect(QRectF(x, y, w, h), radius, radius)

    def ellipse(x, y, w, h):
        painter.drawEllipse(QRectF(x, y, w, h))

    def triangle(points):
        path = QPainterPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        path.closeSubpath()
        painter.drawPath(path)

    if name == 'grid':
        for x, y in ((3, 3), (14, 3), (3, 14), (14, 14)):
            rect(x, y, 7, 7, 1)
    elif name == 'list':
        for y in (5, 11, 17):
            rect(4, y, 16, 2.4, 1)
    elif name == 'details':
        rect(3, 4, 18, 16, 2)
        line(3, 9, 21, 9)
        line(9, 9, 9, 20)
        line(12, 13, 19, 13)
        line(12, 17, 17, 17)
    elif name == 'file':
        path = QPainterPath()
        path.moveTo(5, 2)
        path.lineTo(14, 2)
        path.lineTo(19, 7)
        path.lineTo(19, 22)
        path.lineTo(5, 22)
        path.closeSubpath()
        painter.drawPath(path)
        line(14, 2, 14, 7)
        line(14, 7, 19, 7)
    elif name == 'log':
        rect(4, 3, 16, 18, 2)
        for y in (8, 12, 16):
            line(7, y, 17, y)
    elif name == 'classroom':
        rect(3, 5, 18, 15, 2)
        line(3, 10, 21, 10)
        line(9, 10, 9, 20)
        ellipse(13, 12, 4, 4)
    elif name == 'settings':
        ellipse(8, 8, 8, 8)
        for angle in range(0, 360, 45):
            import math
            x1 = 12 + 7 * math.cos(math.radians(angle))
            y1 = 12 + 7 * math.sin(math.radians(angle))
            x2 = 12 + 10 * math.cos(math.radians(angle))
            y2 = 12 + 10 * math.sin(math.radians(angle))
            line(x1, y1, x2, y2)
    elif name == 'help':
        ellipse(3, 3, 18, 18)
        painter.drawArc(QRectF(8, 6, 8, 8), 190 * 16, 250 * 16)
        line(12, 13, 12, 16)
        ellipse(11.2, 17.5, 1.6, 1.6)
    elif name == 'broadcast':
        rect(2, 4, 20, 13, 2)
        line(12, 17, 12, 21)
        line(8, 21, 16, 21)
        triangle(((9, 8), (9, 14), (15, 11)))
    elif name == 'demo':
        ellipse(3, 4, 7, 7)
        rect(2, 14, 20, 7, 2)
        line(16, 17, 20, 17)
        ellipse(12, 5, 4, 4)
    elif name == 'cinema':
        ellipse(3, 4, 18, 16)
        ellipse(7, 8, 3, 3)
        ellipse(14, 8, 3, 3)
        ellipse(7, 13, 3, 3)
        ellipse(14, 13, 3, 3)
    elif name == 'live':
        ellipse(4, 5, 12, 12)
        line(16, 9, 22, 5)
        line(16, 13, 22, 17)
        rect(16, 5, 6, 12, 1)
    elif name == 'whiteboard':
        rect(2, 3, 20, 14, 2)
        line(12, 17, 12, 21)
        line(8, 21, 16, 21)
        line(6, 13, 10, 8)
        line(10, 8, 14, 12)
        line(14, 12, 18, 7)
    elif name == 'monitor' or name == 'eye':
        path = QPainterPath()
        path.moveTo(2, 12)
        path.quadTo(12, 1, 22, 12)
        path.quadTo(12, 23, 2, 12)
        painter.drawPath(path)
        ellipse(9, 9, 6, 6)
    elif name == 'command':
        rect(2.5, 4, 19, 16, 2)
        line(6, 9, 9, 12)
        line(9, 12, 6, 15)
        line(12, 16, 18, 16)
    elif name == 'discuss':
        painter.drawRoundedRect(QRectF(2, 4, 15, 11), 3, 3)
        line(6, 15, 4, 19)
        line(4, 19, 9, 15)
        painter.drawRoundedRect(QRectF(11, 10, 11, 9), 3, 3)
        line(19, 19, 21, 22)
        line(21, 22, 16, 19)
    elif name == 'group':
        for x in (3, 10, 17):
            ellipse(x, 4, 5, 5)
            rect(x - 1, 11, 7, 8, 2)
    elif name == 'exam' or name == 'survey':
        rect(4, 3, 16, 19, 2)
        line(8, 9, 16, 9)
        line(8, 13, 16, 13)
        line(8, 17, 13, 17)
        line(6, 6, 7, 7)
        line(7, 7, 9, 5)
    elif name == 'contest':
        ellipse(7, 3, 10, 10)
        line(9, 13, 7, 21)
        line(15, 13, 17, 21)
        line(5, 21, 19, 21)
        line(7, 3, 4, 8)
        line(17, 3, 20, 8)
    elif name == 'distribute':
        path = QPainterPath()
        path.moveTo(5, 2)
        path.lineTo(13, 2)
        path.lineTo(18, 7)
        path.lineTo(18, 12)
        path.lineTo(5, 12)
        path.closeSubpath()
        painter.drawPath(path)
        line(13, 2, 13, 7)
        line(13, 7, 18, 7)
        line(4, 17, 20, 17)
        triangle(((16, 14), (21, 17), (16, 20)))
    elif name == 'collect':
        path = QPainterPath()
        path.moveTo(5, 2)
        path.lineTo(13, 2)
        path.lineTo(18, 7)
        path.lineTo(18, 12)
        path.lineTo(5, 12)
        path.closeSubpath()
        painter.drawPath(path)
        line(13, 2, 13, 7)
        line(13, 7, 18, 7)
        line(20, 17, 4, 17)
        triangle(((8, 14), (3, 17), (8, 20)))
    elif name == 'lock':
        rect(4, 10, 16, 11, 2)
        painter.drawArc(QRectF(7, 2, 10, 12), 0, 180 * 16)
        line(12, 14, 12, 17)
    elif name == 'unlock':
        rect(4, 10, 16, 11, 2)
        painter.drawArc(QRectF(7, 2, 10, 12), 25 * 16, 135 * 16)
        line(12, 14, 12, 17)
    elif name == 'auto':
        ellipse(3, 3, 18, 18)
        triangle(((10, 7), (10, 17), (17, 12)))
    elif name == 'block':
        ellipse(3, 3, 18, 18)
        line(7, 7, 17, 17)
    elif name == 'volume':
        rect(3, 9, 5, 6, 1)
        triangle(((8, 9), (12, 5), (12, 19), (8, 15)))
        painter.drawArc(QRectF(13, 7, 7, 10), 290 * 16, 140 * 16)
    elif name == 'play':
        triangle(((7, 4), (19, 12), (7, 20)))
    elif name == 'stop':
        rect(5, 5, 14, 14, 2)
    elif name == 'power':
        painter.drawArc(QRectF(4, 5, 16, 16), 130 * 16, 280 * 16)
        line(12, 2, 12, 12)
    elif name == 'refresh':
        path = QPainterPath()
        path.moveTo(20, 7)
        path.quadTo(17, 2, 11, 4)
        path.quadTo(4, 5, 4, 12)
        path.quadTo(4, 20, 12, 20)
        path.quadTo(17, 20, 19, 16)
        painter.drawPath(path)
        line(20, 2, 20, 7)
        line(20, 7, 15, 7)
    elif name == 'search':
        ellipse(3, 3, 13, 13)
        line(14, 14, 21, 21)
    elif name == 'send':
        path = QPainterPath()
        path.moveTo(3, 3)
        path.lineTo(21, 12)
        path.lineTo(3, 21)
        path.lineTo(7, 12)
        path.closeSubpath()
        painter.drawPath(path)
        line(7, 12, 21, 12)
    elif name == 'chat' or name == 'message':
        painter.drawRoundedRect(QRectF(3, 4, 18, 15), 3, 3)
        line(7, 19, 5, 22)
        line(5, 22, 12, 19)
        line(8, 10, 16, 10)
        line(8, 14, 13, 14)
    elif name == 'cursor':
        path = QPainterPath()
        path.moveTo(5, 2)
        path.lineTo(19, 12)
        path.lineTo(12, 13)
        path.lineTo(9, 21)
        path.closeSubpath()
        painter.drawPath(path)
    elif name == 'terminal' or name == 'devices':
        rect(2.5, 3.5, 19, 17, 2)
        line(6, 8, 9, 11)
        line(9, 11, 6, 14)
        line(12, 15, 18, 15)
    elif name == 'sort':
        line(6, 4, 6, 20)
        triangle(((9, 7), (14, 7), (11.5, 11)))
        line(6, 20, 18, 20)
        triangle(((12, 13), (17, 13), (14.5, 17)))
    elif name == 'zoomin':
        ellipse(3, 3, 13, 13)
        line(14, 14, 21, 21)
        line(6, 9.5, 12, 9.5)
        line(9, 6.5, 9, 12.5)
    elif name == 'zoomout':
        ellipse(3, 3, 13, 13)
        line(14, 14, 21, 21)
        line(6, 9.5, 12, 9.5)
    elif name == 'info':
        ellipse(3, 3, 18, 18)
        line(12, 10, 12, 17)
        ellipse(11.2, 6.5, 1.6, 1.6)
    elif name == 'pin':
        rect(4, 4, 16, 12, 2)
        line(8, 16, 6, 22)
        line(16, 16, 18, 22)
        line(6, 22, 18, 22)
    elif name == 'users':
        ellipse(4, 3, 6, 6)
        rect(2, 11, 10, 8, 2)
        ellipse(15, 3, 6, 6)
        rect(13, 11, 10, 8, 2)
    elif name == 'clock':
        ellipse(3, 3, 18, 18)
        line(12, 6, 12, 12)
        line(12, 12, 16, 15)
    elif name == 'more':
        painter.setBrush(QColor(color))
        for x in (5, 12, 19):
            ellipse(x - 1.4, 10.6, 2.8, 2.8)
    else:
        rect(4, 4, 16, 16, 3)
        line(8, 12, 16, 12)
    painter.end()
    return QIcon(image)


class UiBridge(QObject):
    preview = pyqtSignal(str, object)
    log = pyqtSignal(str, int)
    chat = pyqtSignal(str, str)
    classroom = pyqtSignal(object)
    submission = pyqtSignal(object)


class CardScrollArea(QScrollArea):
    def __init__(self, layout_changed):
        super().__init__()
        self.layout_changed = layout_changed

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout_changed()


class PreviewWidget(QWidget):
    def __init__(self, empty_text='等待预览', parent=None):
        super().__init__(parent)
        self.pixmap = None
        self.empty_text = empty_text
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_pixmap(self, pixmap):
        self.pixmap = QPixmap(pixmap) if pixmap else None
        self.update()

    def clear_image(self):
        self.pixmap = None
        self.update()

    def set_image(self, image):
        self.set_pixmap(to_pixmap(image))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor('#20262f'))
        if not self.pixmap or self.pixmap.isNull():
            painter.setPen(QColor('#8c97a5'))
            painter.setFont(QFont('Microsoft YaHei UI', 10))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            return
        scaled = self.pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap((self.width() - scaled.width()) // 2,
                           (self.height() - scaled.height()) // 2, scaled)
        painter.end()


def to_pixmap(image):
    if image is None:
        return None
    if isinstance(image, QPixmap):
        return QPixmap(image)
    if isinstance(image, QImage):
        return QPixmap.fromImage(image)
    rgb = image.convert('RGB')
    data = rgb.tobytes('raw', 'RGB')
    qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3,
                    QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimage)


def restyle(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class StudentCard(QFrame):
    def __init__(self, ip, select_callback, double_callback, action_callback, menu_builder):
        super().__init__()
        self.ip = ip
        self.select_callback = select_callback
        self.double_callback = double_callback
        self.action_callback = action_callback
        self.menu_builder = menu_builder
        self.setObjectName('studentCard')
        self.setProperty('selected', False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.preview = PreviewWidget('等待预览')
        self.preview.setFixedHeight(132)
        self.preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.preview)
        body = QWidget()
        body.setObjectName('cardBody')
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 8, 10, 9)
        body_layout.setSpacing(4)
        title_row = QHBoxLayout()
        self.name = QLabel(ip)
        self.name.setObjectName('cardName')
        title_row.addWidget(self.name)
        title_row.addStretch()
        self.live = QLabel('● 在线')
        self.live.setObjectName('liveLabel')
        title_row.addWidget(self.live)
        body_layout.addLayout(title_row)
        self.address = QLabel(ip)
        self.address.setObjectName('cardAddress')
        body_layout.addWidget(self.address)
        actions = QHBoxLayout()
        actions.setSpacing(5)
        self.view_button = QPushButton('观看')
        self.view_button.setObjectName('cardAction')
        self.view_button.clicked.connect(partial(action_callback, 'view', ip))
        actions.addWidget(self.view_button)
        for text, action in (('预览', 'preview'), ('远控', 'control'), ('消息', 'chat'), ('管理', 'details')):
            button = QPushButton(text)
            button.setObjectName('cardAction')
            button.clicked.connect(partial(action_callback, action, ip))
            actions.addWidget(button)
        body_layout.addLayout(actions)
        layout.addWidget(body)
        for label in (self.name, self.live, self.address):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def apply_scale(self, scale):
        self.setMinimumWidth(int(210 * scale))
        self.preview.setFixedHeight(int(132 * scale))

    def mousePressEvent(self, event):
        self.select_callback(self.ip)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.double_callback(self.ip)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = self.menu_builder(self.ip)
        if menu is not None:
            self.select_callback(self.ip)
            menu.exec(event.globalPos())

    def apply_pixmap(self, pixmap):
        self.preview.set_pixmap(pixmap)

    def update_student(self, student):
        info = student.get('info', {})
        name = info.get('name') or '未命名终端'
        user = info.get('user')
        self.name.setText(name)
        self.name.setToolTip(name)
        self.address.setText(f'{self.ip}  /  {user}' if user else self.ip)
        hand_up = student.get('anno_state', {}).get('hand_up', False)
        has_submit = (student.get('submit_request') or {}).get('status') == 'pending'
        signal_only = bool(student.get('signal_only') or
                           student.get('status') == 'signal_only')
        if has_submit:
            label = '▲ 文件提交'
        elif hand_up:
            label = '▲ 举手'
        elif signal_only:
            label = '○ 有信号/未登录'
        else:
            label = '● 在线'
        self.live.setText(label)
        self.live.setProperty('alert', hand_up or has_submit)
        restyle(self.live)

    def set_selected(self, selected):
        self.setProperty('selected', bool(selected))
        restyle(self)

    def set_viewing(self, viewing):
        self.view_button.setText('停止观看' if viewing else '观看')
        self.view_button.setProperty('viewing', bool(viewing))
        restyle(self.view_button)


class Worker(QThread):
    completed = pyqtSignal(str, str, object, object)

    def __init__(self, operation, target, fn, args=(), parent=None):
        super().__init__(parent)
        self.operation = operation
        self.target = target
        self.fn = fn
        self.args = args
        self.on_done = None
        self.report_result = True

    def run(self):
        try:
            result = self.fn(*self.args)
        except Exception as error:
            self.completed.emit(self.operation, self.target, None, error)
        else:
            self.completed.emit(self.operation, self.target, result, None)


class TextCommandDialog(QDialog):
    def __init__(self, title, fields, parent=None, confirm_text='执行'):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        heading = QLabel(title)
        heading.setObjectName('dialogTitle')
        layout.addWidget(heading)
        form = QFormLayout()
        form.setSpacing(12)
        self.inputs = {}
        for key, label, value, placeholder in fields:
            editor = QLineEdit(value)
            editor.setPlaceholderText(placeholder)
            form.addRow(label, editor)
            self.inputs[key] = editor
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        confirm = buttons.addButton(confirm_text, QDialogButtonBox.ButtonRole.AcceptRole)
        confirm.setObjectName('accentButton')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {key: editor.text().strip() for key, editor in self.inputs.items()}


class ChannelSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('频道与接收设置')
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        heading = QLabel('频道与接收设置')
        heading.setObjectName('dialogTitle')
        layout.addWidget(heading)
        form = QFormLayout()
        self.channel_input = QSpinBox()
        self.channel_input.setRange(1, 32)
        self.channel_input.setValue(app_config.load_channel())
        self.channel_input.setAccessibleName('下次启动使用的频道')
        form.addRow('频道（1–32）', self.channel_input)
        self.submission_port_input = QSpinBox()
        self.submission_port_input.setRange(0, 65535)
        self.submission_port_input.setValue(app_config.load_submission_port())
        self.submission_port_input.setAccessibleName('下次启动使用的文件接收端口')
        form.addRow('文件接收端口（0 禁用）', self.submission_port_input)
        layout.addLayout(form)
        service = core.submission_service_info()
        current = QLabel(
            f'当前运行频道：{core.CHANNEL_ID}；当前文件接收端口：'
            f'{service["configured_port"]}（服务'
            f'{"已启动" if service["running"] else "尚未启动"}）。保存后重启教师端生效。')
        current.setObjectName('muted')
        current.setWordWrap(True)
        layout.addWidget(current)
        hint = QLabel('端口 1–65535 只作为本项目独立模拟工具的本地监听端口；'
                      '尚未确认官方学生端的默认文件提交端口。0 仅发送 RRMS 审批。')
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        env_notes = []
        if CHANNEL_FROM_ENV:
            env_notes.append('检测到 TEACHER_CHANNEL 环境变量；其值优先于此处保存的配置。')
        if SUBMISSION_PORT_FROM_ENV:
            env_notes.append('检测到 TEACHER_SUBMISSION_PORT 环境变量；其值优先于配置文件和本次保存值。')
        if env_notes:
            note = QLabel('\n'.join(env_notes))
            note.setObjectName('warning')
            note.setWordWrap(True)
            layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        save = buttons.addButton('保存', QDialogButtonBox.ButtonRole.AcceptRole)
        save.setObjectName('accentButton')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class StudentDemoDialog(QDialog):
    def __init__(self, students, parent=None):
        super().__init__(parent)
        self.setWindowTitle('学生演示')
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        heading = QLabel('学生的计算机屏幕将广播给以下学生。请选择一列要接收演示的学生')
        heading.setObjectName('dialogTitle')
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.scopes = []
        for text in ('向所有学生演示', '向选定的学生演示', '向选定的组演示'):
            radio = QRadioButton(text)
            layout.addWidget(radio)
            self.scopes.append(radio)
        self.scopes[0].setChecked(True)
        layout.addWidget(QLabel('可用的学生或组：'))
        self.student_list = QListWidget()
        for ip, student in sorted(students.items()):
            name = student.get('info', {}).get('name') or ip
            item = QListWidgetItem(f'{name} · {ip}')
            item.setData(Qt.ItemDataRole.UserRole, ip)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.student_list.addItem(item)
        layout.addWidget(self.student_list, 1)
        self.select_all = QCheckBox('全选(S)')
        self.select_all.stateChanged.connect(self._select_all)
        layout.addWidget(self.select_all)
        notice = QLabel('当前核心仅有 feature 4 语音启停控制包的静态证据；'
                        '屏幕分发、按学生/组选择接收者、媒体监看均未实现。')
        notice.setObjectName('warning')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _select_all(self, state):
        checked = Qt.CheckState.Checked if state else Qt.CheckState.Unchecked
        for row in range(self.student_list.count()):
            self.student_list.item(row).setCheckState(checked)

    def scope(self):
        for index, radio in enumerate(self.scopes):
            if radio.isChecked():
                return index
        return 0

    def selected_ips(self):
        return [self.student_list.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(self.student_list.count())
                if self.student_list.item(row).checkState() == Qt.CheckState.Checked]


class ClassroomPanel(QWidget):
    def __init__(self, parent=None, reporter=None):
        super().__init__(parent)
        self.classroom_data = None
        self._last_error = None
        self.report_status = reporter or (lambda *args, **kwargs: None)
        self.build_ui()

    def wrap(self, operation, callback):
        def handler(*_signal_args):
            self._last_error = None
            self.report_status(operation, '本机', '执行中…', ok=True)
            try:
                callback()
            except Exception as error:
                self.report_status(operation, '本机', f'异常：{error}', ok=False)
            else:
                if self._last_error is None:
                    self.report_status(operation, '本机',
                                       '已执行（详见班级管理状态）', ok=True)
        return handler

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        toolbar = QHBoxLayout()
        self.class_selector = QComboBox()
        self.class_selector.setEditable(True)
        self.class_selector.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.class_selector.setMinimumWidth(220)
        self.class_selector.setPlaceholderText('选择班级，或输入名称后新建')
        self.class_selector.activated.connect(self.wrap('切换班级', self.select_active_class))
        toolbar.addWidget(self.class_selector)
        for text, callback in (
                ('新建班级', self.create_classroom_class),
                ('导入在线学生', self.import_classroom_students),
                ('导出签到 CSV', self.export_classroom_csv)):
            button = QPushButton(text)
            button.clicked.connect(self.wrap(text, callback))
            toolbar.addWidget(button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.classroom_stats = QLabel('尚未选择班级')
        self.classroom_stats.setObjectName('counter')
        layout.addWidget(self.classroom_stats)
        self.classroom_status = QLabel('自动签到仅处理当前班级已导入的学生。')
        self.classroom_status.setObjectName('muted')
        self.classroom_status.setWordWrap(True)
        layout.addWidget(self.classroom_status)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        group_panel = QFrame()
        group_panel.setObjectName('panel')
        group_layout = QVBoxLayout(group_panel)
        group_layout.setContentsMargins(0, 0, 0, 10)
        caption = QLabel('分组与成员')
        caption.setObjectName('panelCaption')
        group_layout.addWidget(caption)
        self.group_table = QTableWidget(0, 3)
        self.group_table.setHorizontalHeaderLabels(('分组', '人数', '组长'))
        self.group_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.group_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.group_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.group_table.verticalHeader().setVisible(False)
        self.group_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.group_table.itemSelectionChanged.connect(self.refresh_group_details)
        group_layout.addWidget(self.group_table)
        group_buttons = QHBoxLayout()
        for text, callback in (
                ('新建', self.create_classroom_group),
                ('重命名', self.rename_classroom_group),
                ('删除', self.delete_classroom_group)):
            button = QPushButton(text)
            button.clicked.connect(self.wrap(f'分组：{text}', callback))
            group_buttons.addWidget(button)
        group_layout.addLayout(group_buttons)
        self.group_member_list = QListWidget()
        self.group_member_list.setMaximumHeight(150)
        group_layout.addWidget(self.group_member_list)
        self.group_student_selector = QComboBox()
        group_layout.addWidget(self.group_student_selector)
        member_buttons = QHBoxLayout()
        for text, callback in (
                ('添加成员', self.add_classroom_member),
                ('移除成员', self.remove_classroom_member),
                ('设为组长', self.set_classroom_leader)):
            button = QPushButton(text)
            button.clicked.connect(self.wrap(f'分组成员：{text}', callback))
            member_buttons.addWidget(button)
        group_layout.addLayout(member_buttons)
        splitter.addWidget(group_panel)
        attendance_panel = QFrame()
        attendance_panel.setObjectName('panel')
        attendance_layout = QVBoxLayout(attendance_panel)
        attendance_layout.setContentsMargins(0, 0, 0, 0)
        attendance_caption = QLabel('签到记录')
        attendance_caption.setObjectName('panelCaption')
        attendance_layout.addWidget(attendance_caption)
        self.attendance_table = QTableWidget(0, 8)
        self.attendance_table.setHorizontalHeaderLabels(
            ('计算机', 'IP / 用户', '签到', '签退', '最近签到', '最近签退', '状态', '分组'))
        self.attendance_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.attendance_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.attendance_table.verticalHeader().setVisible(False)
        self.attendance_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.attendance_table.horizontalHeader().setStretchLastSection(True)
        self.attendance_table.setAlternatingRowColors(True)
        attendance_layout.addWidget(self.attendance_table)
        splitter.addWidget(attendance_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes((330, 700))
        layout.addWidget(splitter, 1)
        self.refresh_classroom()

    def error(self, operation, error):
        core.logger.error('[UI] %s失败：%s', operation, error,
                          exc_info=(type(error), error, error.__traceback__))
        self._last_error = error
        self.classroom_status.setText(f'{operation}失败：{error}')
        self.report_status(operation, '本机', f'失败：{error}', ok=False)
        QMessageBox.critical(self, operation, str(error))

    def require_classroom(self):
        name = core.classroom_active_class
        if not name:
            QMessageBox.information(self, '尚未选择班级', '请先选择或新建一个班级。')
        return name

    def refresh_classroom(self):
        try:
            names = core.classroom_store.list_classes()
            active = core.classroom_active_class
            self.class_selector.blockSignals(True)
            self.class_selector.clear()
            self.class_selector.addItems(names)
            self.class_selector.setCurrentText(active or '')
            self.class_selector.blockSignals(False)
            self.classroom_data = (core.classroom_store.get_class(active)
                                   if active in names else None)
            self.refresh_classroom_tables()
        except Exception as error:
            self.classroom_data = None
            self.classroom_status.setText(f'读取班级数据失败：{error}')
            core.logger.error('[UI] 读取班级数据失败：%s', error, exc_info=True)

    def refresh_classroom_tables(self):
        classroom = self.classroom_data
        if classroom is None:
            self.classroom_stats.setText('尚未选择班级')
            self.group_table.setRowCount(0)
            self.attendance_table.setRowCount(0)
            self.refresh_group_details()
            return
        attendance = classroom['attendance']
        students = classroom['students']
        self.classroom_stats.setText(
            f"{len(students)} 学生   {sum(r['online'] for r in attendance.values())} 在线   "
            f"{sum(r['check_in_count'] for r in attendance.values())} 签到   "
            f"{sum(r['check_out_count'] for r in attendance.values())} 签退")
        previous_group = self.selected_classroom_group(show_warning=False)
        self.group_table.blockSignals(True)
        self.group_table.setRowCount(len(classroom['groups']))
        selected_row = -1
        for row, (name, group) in enumerate(classroom['groups'].items()):
            leader = students.get(group['leader'], {}).get('computer_name', '—')
            for column, value in enumerate((name, len(group['members']), leader or '—')):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.group_table.setItem(row, column, item)
                if name == previous_group:
                    selected_row = row
        self.group_table.blockSignals(False)
        if selected_row >= 0:
            self.group_table.selectRow(selected_row)
        self.refresh_group_details()
        self.attendance_table.blockSignals(True)
        self.attendance_table.setRowCount(len(students))
        for row, (key, student) in enumerate(students.items()):
            record = attendance.get(key, {})
            groups = [name for name, group in classroom['groups'].items()
                      if key in group['members']]
            values = (
                student['computer_name'] or '未命名终端',
                f"{student['ip']} / {student['user_name'] or '—'}",
                record.get('check_in_count', 0), record.get('check_out_count', 0),
                self.format_attendance_time(record.get('last_check_in')),
                self.format_attendance_time(record.get('last_check_out')),
                '在线' if record.get('online') else '离线', '、'.join(groups) or '—',
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.attendance_table.setItem(row, column, item)
        self.attendance_table.blockSignals(False)

    @staticmethod
    def format_attendance_time(value):
        if not value:
            return '—'
        parsed = QDateTime.fromString(value, Qt.DateFormat.ISODate)
        return (parsed.toLocalTime().toString('yyyy-MM-dd HH:mm:ss')
                if parsed.isValid() else value)

    def select_active_class(self, *_signal_args):
        name = self.class_selector.currentText().strip()
        if name not in core.classroom_store.list_classes():
            return
        try:
            core.set_active_class(name)
            self.classroom_status.setText(f'当前班级：{name}')
            self.refresh_classroom()
        except Exception as error:
            self.error('切换班级', error)

    def create_classroom_class(self):
        name = self.class_selector.currentText().strip()
        try:
            core.classroom_store.create_class(name)
            core.set_active_class(name)
            self.classroom_status.setText(f'已创建并选择班级：{name}')
            self.refresh_classroom()
        except Exception as error:
            self.error('新建班级', error)

    def import_classroom_students(self):
        name = self.require_classroom()
        if not name:
            return
        classroom = core.classroom_store.get_class(name)
        existing = {student['ip'] for student in classroom['students'].values()}
        imported = []
        errors = []
        for student in core.import_online_students():
            if student['ip'] in existing:
                continue
            try:
                core.classroom_store.add_student(name, **student)
                imported.append(student)
            except Exception as error:
                errors.append(f"{student['ip']}：{error}")
                core.logger.error('[UI] 导入学生失败 class=%s ip=%s error=%s',
                                  name, student['ip'], error, exc_info=True)
        for student in imported:
            core.handle_classroom_student_info(
                student['ip'], {'name': student['computer_name'],
                                'user': student['user_name']})
        self.refresh_classroom()
        self.classroom_status.setText(f'已导入 {len(imported)} 名学生，跳过已有学生。')
        if errors:
            QMessageBox.critical(self, '部分学生导入失败', '\n'.join(errors))

    def export_classroom_csv(self):
        name = self.require_classroom()
        if not name:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '导出签到 CSV', f'{name}_签到.csv', 'CSV 文件 (*.csv)')
        if not path:
            return
        try:
            core.classroom_store.export_attendance_csv(name, path, utf8_bom=True)
            self.classroom_status.setText(f'签到 CSV 已导出：{path}')
            QMessageBox.information(self, '导出完成', f'签到记录已保存到：\n{path}')
        except Exception as error:
            self.error('导出签到 CSV', error)

    def selected_classroom_group(self, show_warning=True):
        item = self.group_table.item(self.group_table.currentRow(), 0)
        name = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not name and show_warning:
            QMessageBox.information(self, '尚未选择分组', '请先选择一个分组。')
        return name

    def selected_classroom_member(self, show_warning=True):
        item = self.group_member_list.currentItem()
        key = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not key and show_warning:
            QMessageBox.information(self, '尚未选择成员', '请先在分组成员列表中选择学生。')
        return key

    def refresh_group_details(self):
        self.group_member_list.clear()
        self.group_student_selector.clear()
        classroom = self.classroom_data
        name = self.selected_classroom_group(show_warning=False)
        if classroom is None or name not in classroom['groups']:
            return
        group = classroom['groups'][name]
        for key in group['members']:
            student = classroom['students'][key]
            suffix = '（组长）' if key == group['leader'] else ''
            item = QListWidgetItem(
                f"{student['computer_name'] or key} · {student['ip']}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.group_member_list.addItem(item)
        for key, student in classroom['students'].items():
            if key not in group['members']:
                self.group_student_selector.addItem(
                    f"{student['computer_name'] or key} · {student['ip']}", key)

    def create_classroom_group(self):
        name = self.require_classroom()
        if not name:
            return
        group_name, accepted = QInputDialog.getText(self, '新建分组', '分组名称：')
        if not accepted:
            return
        try:
            core.classroom_store.create_group(name, group_name)
            self.refresh_classroom()
        except Exception as error:
            self.error('新建分组', error)

    def rename_classroom_group(self):
        name = self.require_classroom()
        group_name = self.selected_classroom_group()
        if not name or not group_name:
            return
        new_name, accepted = QInputDialog.getText(
            self, '重命名分组', '新名称：', text=group_name)
        if not accepted:
            return
        try:
            core.classroom_store.rename_group(name, group_name, new_name)
            self.refresh_classroom()
        except Exception as error:
            self.error('重命名分组', error)

    def delete_classroom_group(self):
        name = self.require_classroom()
        group_name = self.selected_classroom_group()
        if not name or not group_name:
            return
        if QMessageBox.question(self, '删除分组',
                                f'确定删除分组“{group_name}”吗？') != QMessageBox.StandardButton.Yes:
            return
        try:
            core.classroom_store.delete_group(name, group_name)
            self.refresh_classroom()
        except Exception as error:
            self.error('删除分组', error)

    def add_classroom_member(self):
        name = self.require_classroom()
        group_name = self.selected_classroom_group()
        key = self.group_student_selector.currentData()
        if not name or not group_name:
            return
        if key is None:
            QMessageBox.information(self, '没有可添加学生', '该班级学生均已在当前分组中。')
            return
        try:
            core.classroom_store.add_group_member(name, group_name, key)
            self.refresh_classroom()
        except Exception as error:
            self.error('添加分组成员', error)

    def remove_classroom_member(self):
        name = self.require_classroom()
        group_name = self.selected_classroom_group()
        key = self.selected_classroom_member()
        if not name or not group_name or not key:
            return
        try:
            core.classroom_store.remove_group_member(name, group_name, key)
            self.refresh_classroom()
        except Exception as error:
            self.error('移除分组成员', error)

    def set_classroom_leader(self):
        name = self.require_classroom()
        group_name = self.selected_classroom_group()
        key = self.selected_classroom_member()
        if not name or not group_name or not key:
            return
        try:
            core.classroom_store.set_group_leader(name, group_name, key)
            self.refresh_classroom()
        except Exception as error:
            self.error('指定组长', error)


class ClassroomDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('管理班级')
        self.resize(1080, 660)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.panel = ClassroomPanel(self, reporter=getattr(parent, 'report_operation', None))
        layout.addWidget(self.panel, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('极域课堂管理系统 · 教师端')
        self.resize(1480, 900)
        self.setMinimumSize(1120, 700)
        self.cards = {}
        self.preview_cache = {}
        self.current_ip = None
        self.snapshot = {}
        self.table_rows = None
        self.cards_signature = None
        self.locked_columns = None
        self.message_signature = None
        self.detail_cache = None
        self.shutting_down = False
        self.submission_events_by_ip = {}
        self.missing_methods = set()
        self.workers = []
        self.view_locked = False
        self.view_pending = set()
        self.sort_mode = 'name'
        self.card_scale = 1.0
        self.classroom_dialog = None
        self.bridge = UiBridge()
        self.bridge.preview.connect(self.set_preview)
        self.bridge.log.connect(self.append_log)
        self.bridge.chat.connect(self.append_chat)
        self.bridge.classroom.connect(self.classroom_changed)
        self.bridge.submission.connect(self.submission_changed)
        bind = getattr(core, 'bind_classroom_observer', None)
        if bind:
            bind(self.bridge.classroom.emit)
        else:
            self.note_missing('bind_classroom_observer')
        self.event_callbacks = (
            (gui_events.preview_events, self.bridge.preview.emit),
            (gui_events.log_events, self.bridge.log.emit),
            (gui_events.chat_events, self.bridge.chat.emit),
            (gui_events.submission_events, self.bridge.submission.emit),
        )
        for channel, callback in self.event_callbacks:
            channel.connect(callback)
        self.build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_students)
        self.timer.start(800)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.tick)
        self.clock_timer.start(1000)
        self.refresh_students()
        self.restore_previews()
        self.tick()
        for warning in STARTUP_WARNINGS:
            self.report_operation('启动检查', '本机', warning, ok=False)
        core.logger.info('教师端界面已启动 · %s · 频道 %d', core.ip, core.CHANNEL_ID)

    # ---------- core 契约安全降级 ----------

    def note_missing(self, name):
        if name in self.missing_methods:
            return
        self.missing_methods.add(name)
        message = (f'core.{name} 不可用：已降级到现有接口，相关功能受限'
                   f'（请确认 core 版本与 GUI 契约一致）')
        core.logger.warning('[UI] %s', message)
        self.append_event(message)

    def core_call(self, name, *args, default=None):
        fn = getattr(core, name, None)
        if fn is None:
            self.note_missing(name)
            return default
        return fn(*args)

    def students_snapshot(self):
        fn = getattr(core, 'get_students_snapshot', None)
        if fn is None:
            self.note_missing('get_students_snapshot')
        result = {}
        lock = getattr(core, 'state_lock', None)
        if lock is not None:
            lock.acquire()
        try:
            for ip, entry in list(getattr(core, 'students', {}).items()):
                result[ip] = dict(entry)
        finally:
            if lock is not None:
                lock.release()
        if fn is None:
            return result
        try:
            snapshot = fn()
        except Exception as error:
            self.report_operation('读取学生快照', '本机', f'异常：{error}', ok=False)
            return result
        if isinstance(snapshot, dict):
            entries = snapshot.items()
        elif isinstance(snapshot, (list, tuple)):
            entries = ((item.get('ip'), item) for item in snapshot
                       if isinstance(item, dict))
        else:
            self.report_operation('读取学生快照', '本机',
                                  f'快照类型 {type(snapshot).__name__} 非预期，已回退 students',
                                  ok=False)
            return result
        for ip, entry in entries:
            if not ip:
                continue
            merged = dict(result.get(ip, {}))
            merged.update(entry)
            result[ip] = merged
        return result

    def view_state(self, ip):
        fn = getattr(core, 'get_view_state', None)
        if fn is None:
            self.note_missing('get_view_state')
            return ip in getattr(core, 'remote_views', {})
        try:
            return self.normalize_view_state(fn(ip), ip)
        except Exception as error:
            self.report_operation('查询观看状态', ip, f'异常：{error}', ok=False)
            return ip in getattr(core, 'remote_views', {})

    def normalize_view_state(self, state, ip):
        if state is None:
            return ip in getattr(core, 'remote_views', {})
        if isinstance(state, bool):
            return state
        if isinstance(state, (int, float)):
            return bool(state)
        if isinstance(state, str):
            return state.strip().lower() in (
                'active', 'viewing', 'watching', 'running', 'started', 'on',
                'connected', 'true', 'yes', '1')
        if isinstance(state, dict):
            for key in ('active', 'viewing', 'watching', 'enabled', 'running', 'connected'):
                if key in state:
                    return bool(state[key])
            for key in ('state', 'status'):
                if key in state:
                    return self.normalize_view_state(state[key], ip)
        for key in ('active', 'viewing', 'watching', 'enabled', 'connected'):
            if hasattr(state, key):
                return bool(getattr(state, key))
        return ip in getattr(core, 'remote_views', {})

    # ---------- 界面搭建 ----------

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        shell = QVBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self.create_toolbar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.create_view_rail())
        body.addWidget(self.create_center(), 1)
        body.addWidget(self.create_sidebar())
        shell.addLayout(body, 1)
        shell.addWidget(self.create_statusbar())
        self.update_view_buttons()

    def create_toolbar(self):
        bar = QFrame()
        bar.setObjectName('topToolbar')
        bar.setFixedHeight(88)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 10, 4)
        layout.setSpacing(2)
        self.toolbar_buttons = {}
        for index, (label, glyph, state) in enumerate(TOOLBAR_ITEMS):
            gray = '#9aa5b2' if state == 'unavailable' else '#2b6cb0'
            button = QToolButton()
            button.setObjectName('mainTool')
            button.setAccessibleName(label)
            button.setIcon(icon(glyph, gray, 30))
            button.setIconSize(QSize(30, 30))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            menu = self.tool_menu(label, state, button)
            button.setText(label)
            if menu is not None:
                button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
                button.setMenu(menu)
            button.setFixedSize(76, 74)
            button.setProperty('unavailable', state == 'unavailable')
            button.setProperty('experimental', state == 'experimental')
            button.setToolTip(self.tool_tip(label, state))
            button.setAccessibleDescription(self.tool_tip(label, state))
            button.clicked.connect(partial(self.tool_clicked, label, state))
            restyle(button)
            layout.addWidget(button)
            self.toolbar_buttons[label] = button
            if index in (4, 7, 11):
                separator = QFrame()
                separator.setObjectName('toolSeparator')
                separator.setFixedWidth(1)
                layout.addWidget(separator)
        layout.addStretch()
        for label, glyph, callback in (
                ('频道设置', 'settings', self.channel_settings),
                ('帮助', 'help', self.help_dialog)):
            button = QToolButton()
            button.setObjectName('windowTool')
            button.setAccessibleName(label)
            button.setIcon(icon(glyph, '#5a6573', 22))
            button.setIconSize(QSize(22, 22))
            button.setToolTip(label)
            button.setFixedSize(34, 34)
            button.clicked.connect(callback)
            layout.addWidget(button)
        return bar

    @staticmethod
    def tool_tip(label, state):
        if state == 'unavailable':
            return f'{label}：尚未实现（仅有静态证据/未实现），点击后显示说明'
        if state == 'experimental':
            return f'{label}：仅有静态证据的实验性控制包，媒体/完整流程未实现'
        return f'{label}：已接入核心命令，点击执行，下拉箭头查看更多'

    def tool_menu(self, label, state, parent=None):
        entries = {
            '屏幕广播': (('开始广播（选中学生）', self.toggle_broadcast),
                       ('停止全班广播', self.stop_all_broadcasts),),
            '学生演示': (('演示设置…', self.student_demo_dialog),
                       ('停止学生演示', self.stop_student_demo),),
            '监控': (('刷新全部预览', self.refresh_all_previews),
                   ('刷新全班设备信息', self.refresh_all_info),
                   ('请求选中学生预览', lambda: self.selected('request_preview')),
                   ('连续观看 / 停止观看', lambda: self.toggle_view(self.current_ip)),
                   ('探测观看通道', lambda: self.selected('probe_view')),),
            '远程命令': (('刷新设备信息', lambda: self.selected('request_info')),
                     ('发送消息', lambda: self.chat_dialog(self.current_ip)),
                     ('远程控制', lambda: self.selected('control')),
                     ('黑屏安静', lambda: self.blackscreen_dialog(self.current_ip)),
                     ('解除黑屏', lambda: self.selected('send_unlock')),
                     ('远程运行', lambda: self.selected('run_program')),
                     ('打开网页', lambda: self.selected('open_url')),
                     ('结束进程', self.kill_selected_process),
                     ('关闭窗口', self.close_selected_window),
                     ('关机 / 重启', lambda: self.selected('power')),
                     ('远程频道实验控制', self.remote_channel_dialog),
                     ('频道与接收设置…', self.channel_settings),),
            '文件收集': (('切换到文件收集视图', self.show_collect_view),
                     ('接受选中提交', lambda: self.review_submit_request(True)),
                     ('全部接受', lambda: self.review_all_submit_requests(True)),
                     ('拒绝选中提交', lambda: self.review_submit_request(False)),
                     ('全部拒绝', lambda: self.review_all_submit_requests(False)),),
        }.get(label, ())
        if not entries:
            return None
        menu = QMenu(label, parent)
        for text, callback in entries:
            menu.addAction(text, callback)
        return menu

    def tool_clicked(self, label, state):
        if state == 'unavailable':
            self.report_operation(label, '—', '仅有静态证据/未实现', ok=False)
            QMessageBox.information(
                self, label,
                f'「{label}」尚未实现（仅有静态证据/未实现）。\n\n'
                '当前项目仅有该功能的静态界面/协议证据，'
                '没有可执行的教师端实现，因此不会假装可用。')
            return
        handlers = {
            '屏幕广播': self.toggle_broadcast,
            '学生演示': self.student_demo_dialog,
            '监控': self.refresh_all_previews,
            '远程命令': self.show_detail_view,
            '文件收集': self.show_collect_view,
        }
        handler = handlers.get(label)
        if handler:
            handler()
        else:
            self.report_operation(label, '—', '未绑定操作', ok=False)

    def create_view_rail(self):
        rail = QFrame()
        rail.setObjectName('viewRail')
        rail.setFixedWidth(46)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(6)
        self.rail_buttons = []
        items = (
            (0, 'grid', '缩略图视图'), (1, 'list', '列表视图'),
            (2, 'details', '详细信息'), (3, 'collect', '文件收集'),
            (4, 'log', '事件日志'), (5, 'classroom', '班级管理'),
        )
        for index, glyph, tooltip in items:
            button = QPushButton(icon(glyph, '#5d6b7c', 22), '')
            button.setObjectName('railButton')
            button.setAccessibleName(tooltip)
            button.setToolTip(tooltip)
            button.setCheckable(True)
            button.setFixedSize(36, 36)
            button.clicked.connect(partial(self.change_view, index))
            layout.addWidget(button)
            self.rail_buttons.append(button)
        self.rail_buttons[0].setChecked(True)
        layout.addStretch()
        gear = QPushButton(icon('settings', '#5d6b7c', 20), '')
        gear.setObjectName('railButton')
        gear.setAccessibleName('频道与接收设置')
        gear.setToolTip('频道与接收设置（重启生效）')
        gear.setFixedSize(36, 36)
        gear.clicked.connect(self.channel_settings)
        layout.addWidget(gear)
        return rail

    def create_center(self):
        center = QFrame()
        center.setObjectName('centerArea')
        layout = QVBoxLayout(center)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)
        tabs = QFrame()
        tabs.setObjectName('memberTabs')
        tab_layout = QHBoxLayout(tabs)
        tab_layout.setContentsMargins(6, 3, 6, 3)
        tab_layout.setSpacing(6)
        self.member_tab = QLabel('● 所有成员')
        self.member_tab.setObjectName('memberTab')
        tab_layout.addWidget(self.member_tab)
        add = QPushButton('+')
        add.setObjectName('tabAdd')
        add.setAccessibleName('新建分组')
        add.setToolTip('新建分组（班级管理）')
        add.setFixedSize(24, 24)
        add.clicked.connect(self.open_classroom)
        tab_layout.addWidget(add)
        tab_layout.addStretch()
        self.member_count = QLabel('0 名成员')
        self.member_count.setObjectName('muted')
        tab_layout.addWidget(self.member_count)
        for glyph, tooltip, callback in (
                ('users', '成员', self.show_grid_view),
                ('group', '分组', self.open_classroom),
                ('refresh', '刷新', self.refresh_all_previews),
                ('send', '导出', self.show_collect_view)):
            button = QPushButton(icon(glyph, '#6b7787', 16), '')
            button.setObjectName('tabIcon')
            button.setAccessibleName(tooltip)
            button.setToolTip(tooltip)
            button.setFixedSize(26, 24)
            button.clicked.connect(callback)
            tab_layout.addWidget(button)
        layout.addWidget(tabs)
        self.views = QStackedWidget()
        self.views.addWidget(self.create_grid_view())
        self.views.addWidget(self.create_list_view())
        self.views.addWidget(self.create_detail_view())
        self.views.addWidget(self.create_collect_view())
        self.views.addWidget(self.create_log_view())
        self.views.addWidget(self.create_classroom_view())
        layout.addWidget(self.views, 1)
        layout.addWidget(self.create_center_bottom())
        return center

    def create_grid_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        tools = QHBoxLayout()
        search = QLineEdit()
        search.setObjectName('searchField')
        search.setPlaceholderText('搜索终端 / IP')
        search.setClearButtonEnabled(True)
        search.setFixedWidth(210)
        search.textChanged.connect(lambda: self.arrange_cards(force=True))
        self.search = search
        tools.addWidget(search)
        tools.addStretch()
        refresh = QPushButton(icon('refresh', INK, 15), '刷新预览')
        refresh.setObjectName('smallButton')
        refresh.clicked.connect(self.refresh_all_previews)
        tools.addWidget(refresh)
        layout.addLayout(tools)
        self.scroll = CardScrollArea(lambda: self.arrange_cards(force=False))
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_widget = QWidget()
        self.cards_widget.setObjectName('cardsWidget')
        self.cards_layout = QGridLayout(self.cards_widget)
        self.cards_layout.setContentsMargins(6, 6, 6, 6)
        self.cards_layout.setSpacing(10)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.cards_widget)
        layout.addWidget(self.scroll, 1)
        self.empty = QWidget()
        self.empty.setObjectName('emptyState')
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_text = QLabel('等待终端接入')
        empty_text.setObjectName('emptyTitle')
        empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint = QLabel('学生端上线后，屏幕缩略图将出现在这里\n'
                            '检查局域网、UDP 组播与 Windows 防火墙设置')
        empty_hint.setObjectName('muted')
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_text)
        empty_layout.addWidget(empty_hint)
        self.cards_layout.addWidget(self.empty, 0, 0)
        return page

    def create_list_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        hint = QLabel('成员列表 · 单击选中，双击观看，右键更多命令')
        hint.setObjectName('muted')
        layout.addWidget(hint)
        self.student_table = QTableWidget(0, 5)
        self.student_table.setHorizontalHeaderLabels(
            ('学生姓名 / IP', '用户', '系统', '内存', '状态'))
        self.student_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.student_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.student_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.student_table.setAlternatingRowColors(True)
        self.student_table.verticalHeader().setVisible(False)
        self.student_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.student_table.itemSelectionChanged.connect(self.select_table_student)
        self.student_table.doubleClicked.connect(
            lambda: self.toggle_view(self.current_ip))
        self.student_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.student_table.customContextMenuRequested.connect(self.list_context_menu)
        layout.addWidget(self.student_table, 1)
        return page

    def create_detail_view(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        left = QFrame()
        left.setObjectName('panel')
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 10, 10)
        self.selected_label = QLabel('选择一台终端')
        self.selected_label.setObjectName('sectionTitle')
        left_layout.addWidget(self.selected_label)
        self.device_tabs = QTabWidget()
        device_page = QWidget()
        device_layout = QVBoxLayout(device_page)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.setSpacing(6)
        self.info_text = QPlainTextEdit()
        self.info_text.setReadOnly(True)
        device_layout.addWidget(self.info_text, 1)
        self.submit_controls = QWidget()
        submit_layout = QHBoxLayout(self.submit_controls)
        submit_layout.setContentsMargins(0, 0, 0, 0)
        self.accept_submit_button = QPushButton('接受文件提交')
        self.accept_submit_button.setObjectName('accentButton')
        self.accept_submit_button.clicked.connect(lambda: self.review_submit_request(True))
        self.reject_submit_button = QPushButton('拒绝文件提交')
        self.reject_submit_button.clicked.connect(lambda: self.review_submit_request(False))
        submit_layout.addWidget(self.accept_submit_button)
        submit_layout.addWidget(self.reject_submit_button)
        device_layout.addWidget(self.submit_controls)
        self.submit_controls.hide()
        self.submission_status_label = QLabel('')
        self.submission_status_label.setObjectName('muted')
        self.submission_status_label.setWordWrap(True)
        self.submission_status_label.hide()
        device_layout.addWidget(self.submission_status_label)
        self.device_tabs.addTab(device_page, '设备信息')
        self.process_table = self.id_name_table(('PID', '进程名称'))
        self.device_tabs.addTab(self.process_table, '进程')
        self.window_table = self.id_name_table(('句柄', '窗口标题'))
        self.device_tabs.addTab(self.window_table, '窗口')
        left_layout.addWidget(self.device_tabs, 1)
        layout.addWidget(left, 1)
        right = QFrame()
        right.setObjectName('panel')
        right.setFixedWidth(250)
        box = QVBoxLayout(right)
        box.setContentsMargins(10, 10, 10, 10)
        box.addWidget(QLabel('常用远程命令'))
        actions = (
            ('刷新信息', lambda: self.selected('request_info')),
            ('请求预览', lambda: self.selected('request_preview')),
            ('连续观看', lambda: self.toggle_view(self.current_ip)),
            ('屏幕广播', self.toggle_broadcast),
            ('学生演示', self.student_demo_dialog),
            ('远程控制', lambda: self.selected('control')),
            ('发送消息', lambda: self.chat_dialog(self.current_ip)),
            ('黑屏安静', lambda: self.blackscreen_dialog(self.current_ip)),
            ('解除黑屏', lambda: self.selected('send_unlock')),
            ('远程运行', lambda: self.selected('run_program')),
            ('打开网页', lambda: self.selected('open_url')),
            ('远程频道', self.remote_channel_dialog),
            ('结束进程', self.kill_selected_process),
            ('关闭窗口', self.close_selected_window),
            ('关机 / 重启', lambda: self.selected('power')),
        )
        for text, callback in actions:
            button = QPushButton(text)
            button.setObjectName('smallButton')
            button.clicked.connect(callback)
            box.addWidget(button)
        box.addStretch()
        layout.addWidget(right)
        return page

    def id_name_table(self, headers):
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        return table

    def create_collect_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.collect_status_table = QTableWidget(0, 5)
        self.collect_status_table.setHorizontalHeaderLabels(
            ('学生姓名', '策略', '状态', '文件名', '进度'))
        self.collect_status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.collect_status_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.collect_status_table.verticalHeader().setVisible(False)
        self.collect_status_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.collect_status_table.setAlternatingRowColors(True)
        layout.addWidget(self.collect_status_table, 1)
        caption = QLabel('文件提交请求（QRMS / RRMS 审批）')
        caption.setObjectName('panelCaption')
        layout.addWidget(caption)
        request_row = QHBoxLayout()
        self.submit_request_table = QTableWidget(0, 5)
        self.submit_request_table.setHorizontalHeaderLabels(
            ('学生姓名', '大小', '文件总数', '请求时间', '文件名'))
        self.submit_request_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.submit_request_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.submit_request_table.verticalHeader().setVisible(False)
        self.submit_request_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.submit_request_table.itemSelectionChanged.connect(self.select_submit_request_row)
        request_row.addWidget(self.submit_request_table, 1)
        buttons = QVBoxLayout()
        for text, callback in (
                ('接受', lambda: self.review_submit_request(True)),
                ('全部接受', lambda: self.review_all_submit_requests(True)),
                ('拒绝', lambda: self.review_submit_request(False)),
                ('全部拒绝', lambda: self.review_all_submit_requests(False))):
            button = QPushButton(text)
            button.setObjectName('smallButton')
            button.setAccessibleName(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch()
        request_row.addLayout(buttons)
        layout.addLayout(request_row, 1)
        footer = QHBoxLayout()
        footer.addStretch()
        for text, callback in (
                ('打开已提交的文件', self.open_submission_folder),
                ('设置提交的文件夹', self.channel_settings)):
            button = QPushButton(text)
            button.setObjectName('smallButton')
            button.clicked.connect(callback)
            footer.addWidget(button)
        layout.addLayout(footer)
        return page

    def create_log_view(self):
        page = QFrame()
        page.setObjectName('panel')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        tools = QHBoxLayout()
        path = QLabel(f'日志文件：{core.LOG_PATH}')
        path.setObjectName('muted')
        tools.addWidget(path)
        tools.addStretch()
        self.debug_toggle = QCheckBox('DEBUG 协议详情（只影响文件日志，不影响界面事件/消息显示）')
        self.debug_toggle.setAccessibleName('DEBUG 文件日志开关')
        self.debug_toggle.toggled.connect(self.set_debug_logging)
        tools.addWidget(self.debug_toggle)
        clear = QPushButton('清空显示')
        clear.setObjectName('smallButton')
        clear.clicked.connect(self.clear_log_display)
        tools.addWidget(clear)
        layout.addLayout(tools)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(3000)
        self.log_text.setObjectName('logView')
        layout.addWidget(self.log_text, 1)
        return page

    def create_classroom_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.embedded_classroom = ClassroomPanel(reporter=self.report_operation)
        layout.addWidget(self.embedded_classroom, 1)
        return page

    def create_center_bottom(self):
        bar = QFrame()
        bar.setObjectName('centerBottom')
        bar.setFixedHeight(36)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)
        self.lock_button = QPushButton(icon('pin', '#3b6da8', 15), '锁定视图')
        self.lock_button.setObjectName('flatTool')
        self.lock_button.setCheckable(True)
        self.lock_button.toggled.connect(self.toggle_lock_view)
        layout.addWidget(self.lock_button)
        sort = QToolButton()
        sort.setObjectName('flatTool')
        sort.setAccessibleName('排序')
        sort.setText('排序')
        sort.setIcon(icon('sort', '#3b6da8', 15))
        sort.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        sort.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        sort_menu = QMenu(sort)
        for text, mode in (('按名称', 'name'), ('按 IP', 'ip'), ('按状态', 'status')):
            sort_menu.addAction(text, partial(self.set_sort_mode, mode))
        sort.setMenu(sort_menu)
        layout.addWidget(sort)
        info = QPushButton(icon('info', '#3b6da8', 15), '信息')
        info.setObjectName('flatTool')
        info.clicked.connect(self.show_detail_view)
        layout.addWidget(info)
        for text, glyph, delta in (('缩小', 'zoomout', -0.1), ('放大', 'zoomin', 0.1)):
            button = QPushButton(icon(glyph, '#3b6da8', 15), text)
            button.setObjectName('flatTool')
            button.setAccessibleName(text)
            button.clicked.connect(partial(self.zoom_cards, delta))
            layout.addWidget(button)
        layout.addStretch()
        self.view_mode_label = QLabel('缩略图视图')
        self.view_mode_label.setObjectName('muted')
        layout.addWidget(self.view_mode_label)
        return bar

    def create_sidebar(self):
        side = QFrame()
        side.setObjectName('sidePanel')
        side.setFixedWidth(286)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)
        quick = QGridLayout()
        quick.setSpacing(5)
        black = QPushButton(icon('lock', '#c0392b', 16), '黑屏安静')
        black.setObjectName('quickButton')
        black.setAccessibleName('黑屏安静')
        black.clicked.connect(lambda: self.blackscreen_dialog(None, all_students=True))
        quick.addWidget(black, 0, 0)
        unlock = QPushButton(icon('unlock', '#177245', 16), '取消黑屏安静')
        unlock.setObjectName('quickButton')
        unlock.setAccessibleName('取消黑屏安静')
        unlock.clicked.connect(self.unlock_all)
        quick.addWidget(unlock, 0, 1)
        self.auto_connect = QPushButton(icon('auto', '#7b8794', 16), '自动连接')
        self.auto_connect.setObjectName('quickButton')
        self.auto_connect.setAccessibleName('自动连接')
        self.auto_connect.setCheckable(True)
        self.auto_connect.setToolTip('未实现：core 未提供对应接口')
        self.auto_connect.clicked.connect(self.toggle_auto_connect)
        quick.addWidget(self.auto_connect, 1, 0)
        manage = QToolButton()
        manage.setObjectName('quickButton')
        manage.setAccessibleName('管理班级')
        manage.setText('管理班级')
        manage.setIcon(icon('classroom', '#2b6cb0', 16))
        manage.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        manage.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        manage.setFixedHeight(30)
        manage_menu = QMenu(manage)
        manage_menu.addAction('打开班级管理', self.open_classroom)
        manage_menu.addAction('导入在线学生', self.import_online_students)
        manage_menu.addAction('导出签到 CSV', self.export_attendance_csv)
        manage.setMenu(manage_menu)
        manage.clicked.connect(self.open_classroom)
        quick.addWidget(manage, 1, 1)
        layout.addLayout(quick)
        self.side_tabs = QTabWidget()
        self.side_tabs.setObjectName('sideTabs')
        events = QWidget()
        event_layout = QVBoxLayout(events)
        event_layout.setContentsMargins(4, 4, 4, 4)
        self.event_log = QPlainTextEdit()
        self.event_log.setReadOnly(True)
        self.event_log.setMaximumBlockCount(2000)
        self.event_log.setPlaceholderText('事件将显示在这里')
        event_layout.addWidget(self.event_log)
        self.side_tabs.addTab(events, '事件')
        messages = QWidget()
        message_layout = QVBoxLayout(messages)
        message_layout.setContentsMargins(4, 4, 4, 4)
        message_layout.setSpacing(4)
        self.message_students = QComboBox()
        self.message_students.setAccessibleName('收件终端')
        self.message_students.currentIndexChanged.connect(self.select_message_student)
        message_layout.addWidget(self.message_students)
        self.chat_history = QPlainTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setMaximumBlockCount(3000)
        self.chat_history.setPlaceholderText('暂无聊天记录')
        message_layout.addWidget(self.chat_history, 1)
        self.chat_input = QPlainTextEdit()
        self.chat_input.setPlaceholderText('输入消息内容…')
        self.chat_input.setFixedHeight(64)
        message_layout.addWidget(self.chat_input)
        send = QPushButton(icon('send', '#ffffff', 15), '发送消息')
        send.setObjectName('accentButton')
        send.setAccessibleName('发送消息')
        send.clicked.connect(self.send_current_message)
        message_layout.addWidget(send)
        self.side_tabs.addTab(messages, '消息')
        layout.addWidget(self.side_tabs, 1)
        preview_label = QLabel('选中学生预览')
        preview_label.setObjectName('panelCaption')
        layout.addWidget(preview_label)
        self.big_preview = PreviewWidget('未选中学生 / 暂无预览')
        self.big_preview.setFixedHeight(150)
        layout.addWidget(self.big_preview)
        self.side_selected = QLabel('未选中学生')
        self.side_selected.setObjectName('sideSelected')
        layout.addWidget(self.side_selected)
        self.side_info = QLabel('—')
        self.side_info.setObjectName('muted')
        self.side_info.setWordWrap(True)
        layout.addWidget(self.side_info)
        preview_buttons = QHBoxLayout()
        self.side_view_button = QPushButton('观看')
        self.side_view_button.setObjectName('accentButton')
        self.side_view_button.setAccessibleName('连续观看')
        self.side_view_button.clicked.connect(lambda: self.toggle_view(self.current_ip))
        preview_buttons.addWidget(self.side_view_button)
        self.block_button = QPushButton(icon('block', '#c0392b', 15), '阻止')
        self.block_button.setObjectName('smallButton')
        self.block_button.setAccessibleName('阻止')
        self.block_button.setCheckable(True)
        self.block_button.setToolTip('未实现：core 未提供对应接口')
        self.block_button.clicked.connect(self.toggle_block)
        preview_buttons.addWidget(self.block_button)
        layout.addLayout(preview_buttons)
        volume = QGridLayout()
        volume.setSpacing(3)
        self.volume_slider_1 = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider_2 = QSlider(Qt.Orientation.Horizontal)
        for slider, row in ((self.volume_slider_1, 0), (self.volume_slider_2, 1)):
            slider.setRange(0, 100)
            slider.setValue(70 if row == 0 else 30)
            slider.valueChanged.connect(partial(self.volume_changed, row + 1))
            volume.addWidget(self.icon_label('volume'), row, 0)
            volume.addWidget(slider, row, 1)
        layout.addLayout(volume)
        foot = QHBoxLayout()
        self.side_online = QLabel('在线 00/00')
        self.side_online.setObjectName('muted')
        self.side_online.setAccessibleName('在线人数')
        foot.addWidget(self.side_online)
        foot.addStretch()
        self.side_clock = QLabel('--:--')
        self.side_clock.setObjectName('muted')
        self.side_clock.setAccessibleName('时间')
        foot.addWidget(self.side_clock)
        layout.addLayout(foot)
        return side

    def create_statusbar(self):
        bar = QFrame()
        bar.setObjectName('statusBar')
        bar.setFixedHeight(34)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(12)
        self.last_action_label = QLabel('最近操作：— | 目标：— | 结果：等待操作 | —')
        self.last_action_label.setObjectName('lastAction')
        self.last_action_label.setAccessibleName('最近操作结果')
        self.last_action_label.setProperty('error', False)
        layout.addWidget(self.last_action_label, 1)
        self.channel_status_label = QLabel('频道 —')
        self.channel_status_label.setObjectName('statusField')
        self.channel_status_label.setAccessibleName('频道')
        layout.addWidget(self.channel_status_label)
        self.ip_status_label = QLabel('本机 —')
        self.ip_status_label.setObjectName('statusField')
        self.ip_status_label.setAccessibleName('本机 IP')
        layout.addWidget(self.ip_status_label)
        self.network_status_label = QLabel('网络 —')
        self.network_status_label.setObjectName('statusField')
        self.network_status_label.setAccessibleName('网络状态')
        layout.addWidget(self.network_status_label)
        self.online_status_label = QLabel('在线 00')
        self.online_status_label.setObjectName('statusField')
        self.online_status_label.setAccessibleName('在线人数')
        layout.addWidget(self.online_status_label)
        self.status_time_label = QLabel('--:--:--')
        self.status_time_label.setObjectName('statusField')
        self.status_time_label.setAccessibleName('时间')
        layout.addWidget(self.status_time_label)
        return bar

    def icon_label(self, name):
        label = QLabel()
        label.setPixmap(icon(name, '#6b7787', 16).pixmap(16, 16))
        return label

    # ---------- 视图切换与底部工具 ----------

    def change_view(self, index):
        self.views.setCurrentIndex(index)
        for i, button in enumerate(self.rail_buttons):
            button.setChecked(i == index)
        self.view_mode_label.setText(
            ('缩略图视图', '列表视图', '详细信息', '文件收集', '事件日志', '班级管理')[index])
        if index == 5:
            self.embedded_classroom.refresh_classroom()
        self.report_operation('切换视图', '本机', self.view_mode_label.text(), ok=True)

    def show_grid_view(self):
        self.change_view(0)

    def show_detail_view(self):
        self.change_view(2)

    def show_collect_view(self):
        self.change_view(3)

    def toggle_lock_view(self, checked):
        self.view_locked = bool(checked)
        self.locked_columns = self.card_columns() if checked else None
        self.report_operation('锁定视图', '本机',
                              '已锁定：卡片布局不再随窗口变化重排' if checked
                              else '已解锁：卡片布局随窗口变化重排', ok=True)
        self.arrange_cards(force=True)

    def set_sort_mode(self, mode):
        self.sort_mode = mode
        self.report_operation('排序', '本机', f'已按{mode}排序', ok=True)
        self.arrange_cards(force=True)

    def zoom_cards(self, delta):
        self.card_scale = max(0.7, min(1.5, round(self.card_scale + delta, 2)))
        for card in self.cards.values():
            card.apply_scale(self.card_scale)
        self.arrange_cards(force=True)
        self.report_operation('缩放', '本机', f'缩略图比例 {self.card_scale:.1f}×', ok=True)

    def toggle_auto_connect(self, checked):
        self.auto_connect.setChecked(False)
        self.report_operation('自动连接', '—', '未实现：core 未提供对应接口，未发送任何命令', ok=False)
        QMessageBox.information(self, '自动连接',
                                '「自动连接」尚未实现：core 没有对应协议接口，'
                                '仅有静态界面证据，不会假装可用。')

    def toggle_block(self, checked):
        self.block_button.setChecked(False)
        self.report_operation('阻止', '—', '未实现：core 未提供对应接口，未发送任何命令', ok=False)
        QMessageBox.information(self, '阻止',
                                '「阻止」尚未实现：core 没有对应协议接口，'
                                '仅有静态界面证据，不会假装可用。')

    def volume_changed(self, number, value):
        self.report_operation(f'音量滑杆 {number}', '本机',
                              f'仅界面数值 {value}（未实现学生端音量控制）', ok=False)

    def clear_log_display(self):
        self.log_text.clear()
        self.report_operation('清空日志显示', core.LOG_PATH,
                              '已清空界面日志；文件日志不受影响', ok=True)

    def set_debug_logging(self, enabled):
        level = logging.DEBUG if enabled else logging.INFO
        fn = getattr(core, 'set_file_log_level', None)
        if fn is None:
            self.note_missing('set_file_log_level')
            self.report_operation('DEBUG 文件日志', '本机', '接口缺失，未改变日志级别', ok=False)
            return
        fn(level)
        self.report_operation('DEBUG 文件日志', core.LOG_PATH,
                              f'文件日志级别={logging.getLevelName(level)}；'
                              '只影响写入文件的内容，不影响界面事件/消息显示', ok=True)

    def help_dialog(self):
        self.report_operation('帮助', '本机', '已打开功能说明', ok=True)
        unavailable = '、'.join(label for label, _, state in TOOLBAR_ITEMS
                               if state == 'unavailable')
        QMessageBox.information(
            self, '功能说明',
            '极域课堂管理系统 · 教师端（浅色官方布局）\n\n'
            '已接入核心：监控、远程命令、文件收集（QRMS/RRMS 审批）、'
            '黑屏安静/解除、频道与接收设置、班级管理、消息中心、事件日志。\n\n'
            '仅有静态证据（实验性）：屏幕广播、学生演示（feature 1 / feature 4 '
            '控制包，无媒体流）。\n\n'
            f'未实现（界面已置灰，点击会说明）：{unavailable}、自动连接、阻止、音量控制。\n\n'
            'DEBUG 勾选框只影响 teacher_sim.log 文件日志级别。')

    # ---------- 操作反馈 ----------

    def report_operation(self, operation, target, result, ok=True):
        stamp = time.strftime('%H:%M:%S')
        self.last_action_label.setText(
            f'最近操作：{operation} | 实际目标：{target or "—"} | 结果：{result} | {stamp}')
        self.last_action_label.setProperty('error', not ok)
        restyle(self.last_action_label)
        self.append_event(f'[{stamp}] {operation} / {target or "—"} / {result}')

    def append_event(self, text):
        if hasattr(self, 'event_log'):
            self.event_log.appendPlainText(text)

    def run_action(self, operation, callback, *args, target=None, alert=True, reason=None):
        if target is None:
            target = (args[0] if args and isinstance(args[0], str)
                      else (self.current_ip or '全班'))
        self.report_operation(operation, target, '执行中…', ok=True)
        self.last_action_label.repaint()
        try:
            fn = callback if callable(callback) else getattr(core, callback, None)
            if fn is None:
                raise AttributeError(f'core.{callback} 不存在：无法执行（core 版本不匹配）')
            result = fn(*args)
        except Exception as error:
            message = f'异常 {type(error).__name__}：{error}'
            core.logger.exception('[UI] 操作失败 action=%s target=%s error=%s',
                                  operation, target, error)
            self.report_operation(operation, target, message, ok=False)
            if alert:
                QMessageBox.critical(self, f'{operation}失败',
                                     f'操作：{operation}\n实际目标：{target}\n\n{message}')
            return False
        if result is False:
            message = reason or 'core 返回 False：命令未发送、被拒绝或目标不可用'
            core.logger.warning('[UI] 操作被拒绝 action=%s target=%s reason=%s',
                                operation, target, message)
            self.report_operation(operation, target, message, ok=False)
            return False
        if isinstance(result, dict) and result.get('ok') is False:
            message = (reason or result.get('reason')
                       or 'core 返回 ok=False：命令未生效')
            core.logger.warning('[UI] 操作未生效 action=%s target=%s result=%r',
                                operation, target, result)
            self.report_operation(operation, target, message, ok=False)
            return False
        if result is None:
            self.report_operation(operation, target, '命令已提交，无结果回执', ok=True)
            return None
        if isinstance(result, dict):
            text = '已执行：' + '，'.join(f'{k}={v}' for k, v in list(result.items())[:6])
        elif isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
            text = ('成功' if result[0] else '失败') + (
                f'：{result[1]}' if result[1] else '')
        else:
            text = f'已执行（回执：{result!r}）'
        self.report_operation(operation, target, text, ok=True)
        return result

    def start_worker(self, operation, target, fn, *args, on_done=None,
                     report_result=True):
        target = target or self.current_ip or '全班'
        worker = Worker(operation, target, fn, args, self)
        worker.on_done = on_done
        worker.report_result = report_result
        self.workers.append(worker)
        worker.completed.connect(partial(self.worker_done, worker),
                                 Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(partial(self.worker_finished, worker),
                                Qt.ConnectionType.QueuedConnection)
        self.report_operation(operation, target, '已提交后台任务…', ok=True)
        worker.start()
        return worker

    def worker_done(self, worker, operation, target, result, error):
        if worker.report_result:
            if error is not None:
                self.report_operation(operation, target,
                                      f'异常 {type(error).__name__}：{error}', ok=False)
            elif isinstance(result, dict) and result.get('ok') is not None:
                if result.get('ok'):
                    self.report_operation(
                        operation, target,
                        '完成：' + '，'.join(f'{k}={v}' for k, v
                                           in list(result.items())[:5]), ok=True)
                else:
                    self.report_operation(
                        operation, target,
                        '失败：' + str(result.get('reason') or 'core 返回 ok=False'),
                        ok=False)
            elif isinstance(result, tuple) and len(result) == 2 \
                    and isinstance(result[0], bool):
                self.report_operation(
                    operation, target,
                    ('成功' if result[0] else '失败')
                    + (f'：{result[1]}' if result[1] else ''), ok=result[0])
            elif result is False:
                self.report_operation(operation, target,
                                      '后台任务返回 False：未完成', ok=False)
            elif result is None:
                self.report_operation(operation, target, '命令已提交，无结果回执', ok=True)
            else:
                self.report_operation(operation, target, f'完成（回执：{result!r}）', ok=True)
        if worker.on_done:
            try:
                worker.on_done(result, error)
            except Exception as callback_error:
                core.logger.exception('[UI] 后台回调失败：%s', callback_error)

    def worker_finished(self, worker):
        if worker in self.workers:
            self.workers.remove(worker)
        worker.deleteLater()

    # ---------- 学生数据 / 选择稳定性 ----------

    def refresh_students(self):
        snapshot = self.students_snapshot()
        self.snapshot = snapshot
        current = set(snapshot)
        for ip in set(self.cards) - current:
            card = self.cards.pop(ip)
            card.hide()
            self.cards_layout.removeWidget(card)
            card.deleteLater()
        for ip in sorted(current):
            if ip not in self.cards:
                card = StudentCard(ip, self.select_student,
                                   lambda student_ip: self.toggle_view(student_ip),
                                   self.card_action, self.card_menu)
                card.apply_scale(self.card_scale)
                card.apply_pixmap(self.ensure_preview(ip))
                self.cards[ip] = card
            card = self.cards[ip]
            card.update_student(snapshot[ip])
            card.set_selected(ip == self.current_ip)
            card.set_viewing(self.view_state(ip))
        if self.current_ip not in current:
            self.current_ip = None
            self.big_preview.clear_image()
        self.member_count.setText(f'{len(current)} 名成员')
        self.online_status_label.setText(f'在线 {len(current):02d}')
        self.side_online.setText(f'在线 {len(current):02d}/{len(current):02d}')
        self.refresh_student_table(snapshot)
        self.refresh_collect_tables(snapshot)
        self.update_selected_details(snapshot)
        self.update_view_buttons()
        self.arrange_cards(force=False)

    def card_columns(self):
        width = max(300, self.scroll.viewport().width() - 12)
        return max(1, min(5, width // int(230 * self.card_scale + 10)))

    def arrange_cards(self, force=False):
        if not hasattr(self, 'cards_layout'):
            return
        query = getattr(self, 'search', None)
        needle = query.text().strip().lower() if query else ''
        visible = []
        for ip, card in self.cards.items():
            match = not needle or needle in ip.lower() or needle in card.name.text().lower()
            card.setVisible(match)
            if match:
                visible.append(card)
        if self.sort_mode == 'ip':
            visible.sort(key=lambda card: card.ip)
        elif self.sort_mode == 'status':
            visible.sort(key=lambda card: (not self.view_state(card.ip), card.ip))
        else:
            visible.sort(key=lambda card: (card.name.text(), card.ip))
        members = tuple(card.ip for card in visible)
        columns = (self.locked_columns if self.view_locked and self.locked_columns
                   else self.card_columns())
        signature = (members, columns, self.sort_mode)
        if not force and signature == self.cards_signature:
            return
        if not force and self.view_locked and self.cards_signature is not None \
                and members == self.cards_signature[0]:
            return
        self.cards_signature = signature
        while self.cards_layout.count():
            self.cards_layout.takeAt(0)
        if not visible:
            self.cards_layout.addWidget(self.empty, 0, 0)
            self.empty.setVisible(True)
            return
        self.empty.setVisible(False)
        for column in range(8):
            self.cards_layout.setColumnStretch(column, 0)
        for column in range(columns):
            self.cards_layout.setColumnStretch(column, 1)
        for index, card in enumerate(visible):
            self.cards_layout.addWidget(card, index // columns, index % columns,
                                        Qt.AlignmentFlag.AlignTop)
            card.setVisible(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.view_locked:
            self.arrange_cards(force=False)

    def student_table_rows(self, snapshot):
        rows = []
        for ip, student in sorted(snapshot.items()):
            info = student.get('info', {}) or {}
            anno = student.get('anno_state', {}) or {}
            submit = student.get('submit_request') or {}
            state = ('待审批' if submit.get('status') == 'pending'
                     else ('举手' if anno.get('hand_up') else '在线'))
            rows.append((ip,
                         f"{info.get('name') or '未命名终端'}  /  {ip}",
                         str(info.get('user', '—')), str(info.get('os', '—')),
                         str(info.get('mem', '—')), state))
        return tuple(rows)

    def refresh_student_table(self, snapshot=None):
        snapshot = snapshot if snapshot is not None else self.students_snapshot()
        table = self.student_table
        rows = self.student_table_rows(snapshot)
        if rows != self.table_rows:
            self.table_rows = rows
            table.blockSignals(True)
            table.setUpdatesEnabled(False)
            try:
                table.setRowCount(len(rows))
                for row, values in enumerate(rows):
                    ip = values[0]
                    for column, value in enumerate(values[1:]):
                        item = QTableWidgetItem(value)
                        item.setData(Qt.ItemDataRole.UserRole, ip)
                        table.setItem(row, column, item)
            finally:
                table.setUpdatesEnabled(True)
                table.blockSignals(False)
        self.select_table_row(self.current_ip)
        self.refresh_message_students(snapshot)

    def select_table_row(self, ip):
        table = self.student_table
        selection = table.selectionModel()
        if selection is None:
            return
        blocked = table.blockSignals(True)
        try:
            selection.clearSelection()
            if not ip:
                return
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == ip:
                    index = table.model().index(row, 0)
                    selection.select(
                        index, QItemSelectionModel.SelectionFlag.Select |
                        QItemSelectionModel.SelectionFlag.Rows)
                    table.setCurrentIndex(index)
                    return
        finally:
            table.blockSignals(blocked)

    def refresh_message_students(self, snapshot):
        signature = tuple((ip, student.get('info', {}).get('name') or ip)
                          for ip, student in sorted(snapshot.items()))
        if signature == self.message_signature:
            return
        self.message_signature = signature
        combo = self.message_students
        combo.blockSignals(True)
        combo.clear()
        combo.addItem('选择收件终端', None)
        for ip, name in signature:
            combo.addItem(f'{name} · {ip}', ip)
        if self.current_ip:
            index = combo.findData(self.current_ip)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def select_table_student(self):
        items = self.student_table.selectedItems()
        if not items:
            return
        ip = items[0].data(Qt.ItemDataRole.UserRole)
        if ip:
            self.select_student(ip, refresh=False)

    def select_message_student(self, index):
        ip = self.message_students.itemData(index)
        if ip:
            self.select_student(ip, refresh=False)

    def select_student(self, ip, refresh=True):
        snapshot = self.snapshot or self.students_snapshot()
        if ip not in self.cards and ip not in snapshot:
            return
        self.current_ip = ip
        for card_ip, card in self.cards.items():
            card.set_selected(card_ip == ip)
        self.big_preview.set_pixmap(self.ensure_preview(ip))
        if refresh:
            self.select_table_row(ip)
        self.update_selected_details(snapshot)
        self.update_view_buttons()
        card = self.cards.get(ip)
        if card is not None and card.isVisible():
            self.scroll.ensureWidgetVisible(card)

    def update_selected_details(self, snapshot=None):
        snapshot = snapshot if snapshot is not None else self.students_snapshot()
        student = snapshot.get(self.current_ip, {})
        info = student.get('info', {})
        name = info.get('name') or self.current_ip or '选择一台终端'
        self.selected_label.setText(name)
        self.side_selected.setText(name if self.current_ip else '未选中学生')
        self.side_info.setText(
            f'{self.current_ip or "—"}  /  {info.get("user") or "—"}' if self.current_ip else '—')
        labels = (
            ('计算机名称', 'name'), ('IP 地址', None), ('登录用户', 'user'),
            ('MAC 地址', 'mac'), ('学生 ID', 'stu_id'), ('操作系统', 'os'),
            ('系统版本', 'osver'), ('CPU 厂商', 'cpu_vendor'),
            ('CPU 型号', 'cpu_model'), ('内存', 'mem'),
        )
        anno = student.get('anno_state', {})
        status = (f'举手：{"是" if anno.get("hand_up") else "否"}\n'
                  f'语音演示位：{"是（无屏幕媒体）" if anno.get("student_demo") else "否"}\n'
                  f'学生状态：0x{anno.get("student_flags", 0):08X}\n'
                  f'黑屏状态：0x{anno.get("blackscreen_flags", 0):08X}')
        submit = student.get('submit_request')
        submit_status = submit.get('status') if submit else None
        if submit:
            state_text = {
                'pending': '待审批（可接受或拒绝）',
                'approved': '已接受（RRMS 审批完成）',
                'rejected': '已拒绝（RRMS 审批完成）',
            }.get(submit_status, submit_status)
            status += (f'\n文件提交：{submit["file_count"]} 个文件，{submit["total_size"]} 字节\n'
                       f'目录：{submit["directory"]}\n'
                       f'列表：{submit["file_list"]}\n'
                       f'事务：{submit["transaction_guid"]}\n'
                       f'审批状态：{state_text}')
            if submit.get('submission_port'):
                status += (f'\n接收服务：{core.ip}:{submit["submission_port"]}\n'
                           f'事务接收目录：{submit.get("submission_directory")}')
        try:
            service = core.submission_service_info()
            if service['configured_port']:
                status += (f'\n文件接收端口：{service["configured_port"]}'
                           f'（{"已监听" if service["running"] else "接受时启动"}）'
                           f'  根目录：{service["directory"]}')
            else:
                status += '\n文件接收端口：0（禁用）；RRMS 接受仅完成审批'
        except Exception as error:
            status += f'\n文件接收服务信息不可用：{error}'
        try:
            receipts = (core.get_submission_receipts(self.current_ip)
                        if self.current_ip else [])
            if receipts:
                last = receipts[-1]
                status += (f'\n最近接收完成：{last["file"]}，{last["bytes"]} 字节\n'
                           f'接收路径：{last["path"]}')
        except Exception as error:
            status += f'\n接收回执不可用：{error}'
        text = (('\n'.join(
            f'{label}：{self.current_ip if key is None else info.get(key, "待上报")}'
            for label, key in labels) + '\n' + status) if self.current_ip
            else '请先从缩略图或列表中选择终端。')
        if text != self.detail_cache:
            self.detail_cache = text
            position = self.info_text.verticalScrollBar().value()
            self.info_text.setPlainText(text)
            self.info_text.verticalScrollBar().setValue(position)
        self.submit_controls.setVisible(bool(submit))
        pending = submit_status == 'pending'
        self.accept_submit_button.setEnabled(pending)
        self.reject_submit_button.setEnabled(pending)
        self.fill_id_name_table(self.process_table, student.get('processes', []), False)
        self.fill_id_name_table(self.window_table, student.get('windows', []), True)
        self.refresh_submission_event()
        if self.current_ip in self.cards:
            self.cards[self.current_ip].update_student(student)

    def submission_changed(self, event):
        if not isinstance(event, dict):
            return
        student_ip = event.get('student_ip', '-')
        summary = (f"事件：{event.get('kind', '-')}\n"
                   f"文件：{event.get('file', '-')}\n"
                   f"字节：{event.get('bytes', 0)} / {event.get('size', 0)}\n"
                   f"路径：{event.get('path', '-')}\n"
                   f"错误：{event.get('error', '-')}")
        self.submission_events_by_ip[student_ip] = summary
        self.append_event(f'[{time.strftime("%H:%M:%S")}] 文件接收 · {student_ip}\n{summary}')
        self.chat_history.appendPlainText(
            f'[{time.strftime("%H:%M:%S")}] 文件接收 · {student_ip}\n{summary}')
        if student_ip == self.current_ip:
            self.refresh_submission_event()

    def refresh_submission_event(self):
        if not hasattr(self, 'submission_status_label'):
            return
        summary = self.submission_events_by_ip.get(self.current_ip)
        self.submission_status_label.setText(f'最新文件接收事件\n{summary}' if summary else '')
        self.submission_status_label.setVisible(bool(summary))

    def fill_id_name_table(self, table, rows, hexadecimal):
        signature = (tuple(rows), hexadecimal)
        if getattr(table, '_ui_signature', None) == signature:
            return
        table._ui_signature = signature
        table.blockSignals(True)
        table.setRowCount(len(rows))
        for row, (identifier, name) in enumerate(rows):
            value = f'0x{identifier:08X}' if hexadecimal else str(identifier)
            table.setItem(row, 0, QTableWidgetItem(value))
            table.setItem(row, 1, QTableWidgetItem(name))
        table.blockSignals(False)

    def refresh_collect_tables(self, snapshot=None):
        snapshot = snapshot if snapshot is not None else self.students_snapshot()
        status_table = self.collect_status_table
        status_table.blockSignals(True)
        status_table.setRowCount(len(snapshot))
        for row, (ip, student) in enumerate(sorted(snapshot.items())):
            info = student.get('info', {})
            submit = student.get('submit_request') or {}
            state = {'pending': '待审批', 'approved': '已接受',
                     'rejected': '已拒绝'}.get(submit.get('status'), '暂无请求')
            values = (info.get('name') or ip,
                      '允许提交' if submit else '—', state,
                      submit.get('file_list') or '—',
                      '—' if not submit else ('0%' if state == '待审批' else '100%'))
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, ip)
                status_table.setItem(row, column, item)
        status_table.blockSignals(False)
        pending = [(ip, s['submit_request']) for ip, s in sorted(snapshot.items())
                   if s.get('submit_request')]
        request_table = self.submit_request_table
        request_table.blockSignals(True)
        request_table.setRowCount(len(pending))
        for row, (ip, submit) in enumerate(pending):
            info = snapshot[ip].get('info', {})
            values = (info.get('name') or ip, submit.get('total_size', 0),
                      submit.get('file_count', 0),
                      time.strftime('%H:%M:%S', time.localtime(submit.get('time', time.time()))),
                      submit.get('file_list') or '—')
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, ip)
                request_table.setItem(row, column, item)
        request_table.blockSignals(False)

    def select_submit_request_row(self):
        items = self.submit_request_table.selectedItems()
        if not items:
            return
        ip = items[0].data(Qt.ItemDataRole.UserRole)
        if ip:
            self.select_student(ip, refresh=False)

    # ---------- 预览缓存 ----------

    def ensure_preview(self, ip):
        if ip in self.preview_cache:
            return self.preview_cache[ip]
        getter = getattr(core, 'get_preview_image', None)
        if getter is None:
            return None
        try:
            image = getter(ip)
        except Exception as error:
            core.logger.warning('[UI] 读取 %s 的 core 预览缓存失败：%s', ip, error)
            return None
        if image is None:
            return None
        self.set_preview(ip, image, report=False)
        return self.preview_cache.get(ip)

    def set_preview(self, ip, image, report=True):
        try:
            pixmap = to_pixmap(image)
        except Exception as error:
            core.logger.warning('[UI] %s 预览图像解码失败：%s', ip, error)
            self.append_event(f'[{time.strftime("%H:%M:%S")}] 预览图像 / {ip} / 解码失败：{error}')
            return
        if pixmap is None:
            return
        self.preview_cache[ip] = pixmap
        card = self.cards.get(ip)
        if card is not None:
            card.apply_pixmap(pixmap)
        if ip == self.current_ip:
            self.big_preview.set_pixmap(pixmap)
        if report:
            self.append_event(
                f'[{time.strftime("%H:%M:%S")}] 接收预览 / {ip} / '
                '已缓存并应用为该卡片最后一张预览图')

    def restore_previews(self):
        getter = getattr(core, 'get_preview_image', None)
        if getter is None:
            self.note_missing('get_preview_image')
            return 0
        ips = set(self.students_snapshot())
        status_fn = getattr(core, 'get_preview_status', None)
        if status_fn is not None:
            try:
                status = status_fn()
            except Exception as error:
                core.logger.warning('[UI] 读取预览状态失败：%s', error)
                status = None
            if isinstance(status, dict):
                ips.update(status.get('cached_image_ips') or ())
        restored = 0
        for ip in sorted(ips):
            if ip in self.preview_cache:
                continue
            if self.ensure_preview(ip) is not None:
                restored += 1
        if restored:
            self.append_event(
                f'[{time.strftime("%H:%M:%S")}] 恢复预览缓存 / 全班 / '
                f'已从 core 取回 {restored} 张早到预览图')
        return restored

    # ---------- 观看开关 ----------

    def update_view_buttons(self):
        viewing = bool(self.current_ip and self.view_state(self.current_ip))
        text = '停止观看' if viewing else '观看'
        self.side_view_button.setText(text)
        self.side_view_button.setProperty('viewing', viewing)
        self.side_view_button.setToolTip(f'{text}：{self.current_ip or "未选中终端"}')
        restyle(self.side_view_button)

    def view_reason(self, ip):
        fn = getattr(core, 'get_view_state', None)
        if fn is None:
            return None
        try:
            state = fn(ip)
        except Exception:
            return None
        if not isinstance(state, dict):
            return None
        parts = []
        if state.get('reason'):
            parts.append(str(state['reason']))
        if state.get('cooldown_remaining'):
            parts.append(f'失败冷却剩余 {state["cooldown_remaining"]:.0f} 秒')
        return '；'.join(parts) or None

    def toggle_view(self, ip):
        if not ip:
            self.report_operation('连续观看', '—', '尚未选择终端', ok=False)
            QMessageBox.information(self, '尚未选择终端', '请先选择一台在线终端。')
            return False
        if ip in self.view_pending:
            self.report_operation('连续观看', ip,
                                  '上一次切换尚未完成，本次未重复发送', ok=False)
            return False
        before = self.view_state(ip)
        toggle = getattr(core, 'toggle_remote_view', None)
        operation = '连续观看'
        if toggle is None:
            self.note_missing('toggle_remote_view')
            fallback_name = 'stop_remote_view' if before else 'start_remote_view'
            toggle = getattr(core, fallback_name, None)
            if toggle is None:
                self.report_operation('连续观看', ip,
                                      f'core 缺少 toggle_remote_view() 与 {fallback_name}()，无法执行',
                                      ok=False)
                return False
            operation = f'连续观看（降级 {fallback_name}）'
        self.view_pending.add(ip)
        self.start_worker(operation, ip, toggle, ip, report_result=False,
                          on_done=partial(self.view_toggled, ip, before))
        return None

    def view_toggled(self, ip, before, result, error):
        self.view_pending.discard(ip)
        after = self.view_state(ip)
        card = self.cards.get(ip)
        if card is not None:
            card.set_viewing(after)
        self.update_view_buttons()
        if error is not None:
            self.report_operation('连续观看', ip,
                                  f'异常 {type(error).__name__}：{error}', ok=False)
            return
        if isinstance(result, dict) and result.get('ok') is False:
            reason = result.get('reason') or self.view_reason(ip) or '核心拒绝切换'
            self.report_operation('连续观看', ip,
                                  f'失败：{reason}（当前{"观看中" if after else "未观看"}）',
                                  ok=False)
            return
        if result is False:
            reason = self.view_reason(ip) or 'core 返回 False'
            self.report_operation('连续观看', ip,
                                  f'失败：{reason}（当前{"观看中" if after else "未观看"}）',
                                  ok=False)
            return
        if after and not before:
            connection = ''
            fn = getattr(core, 'get_view_state', None)
            state = None
            if fn is not None:
                try:
                    state = fn(ip)
                except Exception:
                    state = None
            if isinstance(state, dict):
                connection = '，屏幕通道已连接' if state.get('connected') else '，屏幕通道连接中'
            self.report_operation('连续观看', ip, f'观看中{connection}', ok=True)
            return
        if before and not after:
            self.report_operation('连续观看', ip, '已停止观看', ok=True)
            return
        detail = self.view_reason(ip)
        self.report_operation('连续观看', ip,
                              '切换未生效：' + (detail or '核心未改变观看状态')
                              + f'（当前{"观看中" if after else "未观看"}）', ok=False)

    # ---------- 卡片交互 ----------

    def card_action(self, action, ip):
        self.select_student(ip)
        handlers = {
            'view': self.toggle_view,
            'preview': lambda student_ip: self.run_action(
                '请求预览', 'request_preview', student_ip, target=student_ip),
            'control': lambda student_ip: self.start_control(student_ip),
            'chat': self.chat_dialog,
            'details': lambda student_ip: self.show_detail_view(),
        }
        handler = handlers.get(action)
        if handler:
            handler(ip)
        else:
            self.report_operation('卡片操作', ip, f'未知操作 {action}', ok=False)

    def card_menu(self, ip):
        menu = QMenu(f'终端 {ip}')
        entries = (
            ('观看 / 停止观看', lambda: self.toggle_view(ip)),
            ('请求预览', lambda: self.run_action('请求预览', 'request_preview', ip, target=ip)),
            ('刷新设备信息', lambda: self.run_action('刷新信息', 'request_info', ip, target=ip)),
            ('发送消息', lambda: self.chat_dialog(ip)),
            ('远程控制', lambda: self.start_control(ip)),
            ('探测观看通道', lambda: self.probe_view(ip)),
            ('黑屏安静', lambda: self.blackscreen_dialog(ip)),
            ('解除黑屏', lambda: self.run_action('解除黑屏', 'send_unlock', ip, target=ip)),
            ('远程运行', lambda: self.run_dialog(ip)),
            ('打开网页', lambda: self.url_dialog(ip)),
            ('关机 / 重启', lambda: self.power_dialog(ip)),
            ('远程频道实验控制', lambda: self.remote_channel_dialog(ip)),
            ('频道与接收设置', self.channel_settings),
        )
        for text, callback in entries:
            menu.addAction(text, callback)
        return menu

    def list_context_menu(self, position):
        item = self.student_table.itemAt(position)
        ip = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not ip:
            return
        self.select_student(ip)
        menu = self.card_menu(ip)
        menu.exec(self.student_table.viewport().mapToGlobal(position))

    # ---------- 远程命令 ----------

    def selected(self, action):
        if not self.current_ip:
            self.report_operation(action, '—', '尚未选择终端', ok=False)
            QMessageBox.information(self, '尚未选择终端', '请先选择一台在线终端。')
            return
        ip = self.current_ip
        simple = {
            'request_preview': ('请求预览', 'request_preview', (ip,)),
            'request_info': ('刷新设备信息', 'request_info', (ip,)),
            'send_unlock': ('解除黑屏', 'send_unlock', (ip,)),
        }
        if action in simple:
            operation, name, args = simple[action]
            self.run_action(operation, name, *args, target=ip)
        elif action == 'control':
            self.start_control(ip)
        elif action == 'probe_view':
            self.probe_view(ip)
        elif action == 'run_program':
            self.run_dialog(ip)
        elif action == 'open_url':
            self.url_dialog(ip)
        elif action == 'power':
            self.power_dialog(ip)
        else:
            self.report_operation(action, ip, '未绑定操作', ok=False)

    def refresh_all_previews(self):
        fn = getattr(core, 'request_all_previews', None)
        if fn is None:
            self.note_missing('request_all_previews')
            def fallback():
                for ip in list(self.students_snapshot()):
                    core.request_preview(ip)
                    time.sleep(0.02)
                return len(self.students_snapshot())
            fn = fallback
        return self.start_worker('刷新全部预览', '全班', fn)

    def refresh_all_info(self):
        return self.start_worker('刷新全班设备信息', '全班', lambda: [
            core.request_info(ip) for ip in list(self.students_snapshot())])

    def start_control(self, ip):
        if not ip:
            self.report_operation('远程控制', '—', '尚未选择终端', ok=False)
            return
        fn = getattr(core, 'cmd_control', None)
        if fn is not None:
            self.start_worker('远程控制', ip, fn, [ip], report_result=False,
                              on_done=partial(self.control_finished, ip))
            return
        fallback = getattr(core, 'start_remote_control', None)
        if fallback is None:
            self.report_operation('远程控制', ip,
                                  'core 缺少 cmd_control/start_remote_control', ok=False)
            return
        self.start_worker('远程控制', ip, fallback, ip, report_result=False,
                          on_done=partial(self.control_finished, ip))

    def control_finished(self, ip, result, error):
        if error is not None:
            self.report_operation('远程控制', ip,
                                  f'异常 {type(error).__name__}：{error}', ok=False)
            return
        state = (getattr(core, 'remote_controls', {}) or {}).get(ip)
        if state:
            self.report_operation('远程控制', ip,
                                  f'远控已启动，输入端口 {state.get("port")}', ok=True)
            return
        if result:
            self.report_operation('远程控制', ip, f'已启动（回执：{result!r}）', ok=True)
            return
        reason = self.view_reason(ip)
        self.report_operation(
            '远程控制', ip,
            '未建立远控会话：需先让该学生的屏幕通道连通后再试'
            + (f'（{reason}）' if reason else ''), ok=False)

    def probe_view(self, ip):
        if not ip:
            self.report_operation('探测观看通道', '—', '尚未选择终端', ok=False)
            return
        fn = getattr(core, 'probe_remote_view', None)
        if fn is None:
            self.report_operation('探测观看通道', ip,
                                  'core 缺少 probe_remote_view()', ok=False)
            return
        self.start_worker('探测观看通道', ip, fn, ip)

    def toggle_broadcast(self):
        ip = self.current_ip
        if not ip:
            self.report_operation('屏幕广播', '—', '尚未选择广播目标', ok=False)
            QMessageBox.information(self, '尚未选择终端', '请先选择广播目标。')
            return
        if ip in getattr(core, 'screen_broadcasts', {}):
            result = self.run_action('停止屏幕广播', 'stop_screen_broadcast', ip, target=ip)
        else:
            result = self.run_action('启动屏幕广播', 'start_screen_broadcast', ip, target=ip)
        if result is not False:
            QMessageBox.information(
                self, '屏幕广播（实验性）',
                f'已向 {ip} 发送 feature 1 启动/停止参数包。\n\n'
                '仅有静态协议证据：当前版本尚未推送屏幕媒体流，'
                '这不代表学生端已经显示画面。')

    def stop_all_broadcasts(self):
        ips = list(getattr(core, 'screen_broadcasts', {}))
        if not ips:
            self.report_operation('停止全班广播', '全班', '没有进行中的广播', ok=True)
            return
        for ip in ips:
            self.run_action('停止屏幕广播', 'stop_screen_broadcast', ip,
                            target=ip, alert=False)

    def student_demo_dialog(self):
        snapshot = self.students_snapshot()
        dialog = StudentDemoDialog(snapshot, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.report_operation('学生演示', '—', '已取消', ok=True)
            return
        scope = dialog.scope()
        selected = dialog.selected_ips()
        source = self.current_ip or (selected[0] if selected else None)
        if not source:
            self.report_operation('学生演示', '—', '未选择演示学生', ok=False)
            QMessageBox.information(self, '尚未选择演示学生', '请先选择一台终端作为演示学生。')
            return
        if scope != 0 or len(selected) > 1:
            self.report_operation('学生演示', source,
                                  '按学生/组选择接收者未实现，仅发送实验性语音控制包', ok=False)
        port_text = os.environ.get('TEACHER_DEMO_VOICE_PORT', '9000')
        try:
            port = int(port_text, 0)
        except ValueError:
            port = 9000
        detail = ('将向演示学生发送 feature 4 最小语音启停控制包。\n'
                  '屏幕分发、按学生/组演示与媒体监看均未实现（仅有静态证据）。')
        if QMessageBox.question(self, '实验性学生演示控制',
                                f'演示学生：{source}\n\n{detail}') != QMessageBox.StandardButton.Yes:
            self.report_operation('学生演示', source, '已取消', ok=True)
            return
        result = self.run_action('学生演示', 'start_student_demo', source, port, target=source)
        if result is not False:
            QMessageBox.information(self, '实验性控制包已发送',
                                    '仅语音启停控制有静态证据；不代表学生屏幕已广播。')

    def stop_student_demo(self):
        demos = list(getattr(core, 'student_demos', {}))
        if not demos:
            self.report_operation('停止学生演示', '全班', '没有进行中的演示', ok=True)
            return
        for ip in demos:
            self.run_action('停止学生演示', 'stop_student_demo', ip, target=ip, alert=False)

    def chat_dialog(self, ip=None):
        if ip:
            self.select_student(ip, refresh=False)
        self.side_tabs.setCurrentIndex(1)
        self.chat_input.setFocus()
        self.report_operation('打开消息中心', ip or self.current_ip or '—',
                              '已切换到右侧「消息」标签', ok=True)

    def send_current_message(self):
        text = self.chat_input.toPlainText().strip()
        if not text:
            self.report_operation('发送消息', self.current_ip or '—', '消息内容为空', ok=False)
            return
        if not self.current_ip:
            self.report_operation('发送消息', '—', '尚未选择收件终端', ok=False)
            QMessageBox.information(self, '尚未选择终端', '请先选择收件终端。')
            return
        result = self.run_action('发送消息', 'send_chat', self.current_ip, text,
                                 target=self.current_ip)
        if result is not False:
            self.append_chat(self.current_ip, text, outgoing=True)
            self.chat_input.clear()

    def blackscreen_dialog(self, ip=None, all_students=False):
        dialog = QDialog(self)
        dialog.setWindowTitle('黑屏安静')
        dialog.setMinimumWidth(430)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 18)
        targets = (list(self.students_snapshot()) if all_students else
                   [ip or self.current_ip] if (ip or self.current_ip) else
                   list(self.students_snapshot()))
        title = QLabel(f'黑屏安静  /  {"全班" if all_students else (targets[0] if targets else "无目标")}')
        title.setObjectName('dialogTitle')
        layout.addWidget(title)
        form = QFormLayout()
        timeout = QSpinBox()
        timeout.setRange(0, 86400)
        timeout.setValue(10)
        timeout.setSuffix(' 秒（0 = 持续）')
        text = QLineEdit('请保持安静')
        lock = QCheckBox('同时锁定键盘和鼠标')
        lock.setChecked(True)
        form.addRow('持续时间', timeout)
        form.addRow('提示文字', text)
        form.addRow('', lock)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        confirm = buttons.addButton('发送黑屏命令', QDialogButtonBox.ButtonRole.AcceptRole)
        confirm.setObjectName('dangerButton')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.report_operation('黑屏安静', '全班' if all_students else (ip or '—'),
                                  '已取消', ok=True)
            return
        if not targets:
            self.report_operation('黑屏安静', '全班', '没有在线终端', ok=False)
            return
        for student_ip in targets:
            self.run_action('黑屏安静', 'send_blackscreen', student_ip,
                            lock.isChecked(), timeout.value(), text.text() or None,
                            target=student_ip, alert=False)

    def unlock_all(self):
        targets = list(self.students_snapshot())
        if not targets:
            self.report_operation('取消黑屏安静', '全班', '没有在线终端', ok=False)
            return
        for ip in targets:
            self.run_action('取消黑屏安静', 'send_unlock', ip, target=ip, alert=False)

    def run_dialog(self, ip=None):
        ip = ip or self.current_ip
        if not ip:
            self.report_operation('远程运行', '—', '尚未选择终端', ok=False)
            return
        dialog = TextCommandDialog('远程运行程序', (
            ('path', '程序路径', r'C:\Windows\notepad.exe', '学生机上的绝对路径'),
            ('args', '启动参数', '', '可选'),
        ), self, '运行')
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.values()
            if values['path']:
                self.run_action('远程运行', 'send_run_program', ip,
                                values['path'], values['args'], target=ip)
            else:
                self.report_operation('远程运行', ip, '程序路径为空', ok=False)
        else:
            self.report_operation('远程运行', ip, '已取消', ok=True)

    def url_dialog(self, ip=None):
        ip = ip or self.current_ip
        if not ip:
            self.report_operation('打开网页', '—', '尚未选择终端', ok=False)
            return
        dialog = TextCommandDialog('打开网页或文件', (
            ('url', '网址 / 路径', 'https://', '将在学生机上打开'),
        ), self, '打开')
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.values()['url']:
            self.run_action('打开网页', 'send_open_url', ip, dialog.values()['url'],
                            target=ip)
        else:
            self.report_operation('打开网页', ip, '已取消或网址为空', ok=False)

    def selected_row_target(self, table, hexadecimal=False):
        items = table.selectedItems()
        if not items:
            self.report_operation('选择目标', self.current_ip or '—',
                                  '请先在列表中选择一个目标', ok=False)
            QMessageBox.information(self, '尚未选择目标',
                                    '请先刷新信息并在列表中选择一个目标。')
            return None
        return int(items[0].text(), 16 if hexadecimal else 10)

    def kill_selected_process(self):
        if not self.current_ip:
            return
        pid = self.selected_row_target(self.process_table)
        if pid is not None and self.confirm('结束进程',
                                            f'确定结束 {self.current_ip} 的进程 PID {pid} 吗？'):
            self.run_action('结束进程', 'send_kill', self.current_ip, pid, None, 1,
                            target=self.current_ip)
            QTimer.singleShot(800, lambda: self.run_action(
                '刷新设备信息', 'request_info', self.current_ip, 2,
                target=self.current_ip, alert=False))

    def close_selected_window(self):
        if not self.current_ip:
            return
        hwnd = self.selected_row_target(self.window_table, True)
        if hwnd is not None and self.confirm('关闭窗口', '确定向所选窗口发送关闭命令吗？'):
            self.run_action('关闭窗口', 'send_kill', self.current_ip, None, hwnd, 0,
                            target=self.current_ip)
            QTimer.singleShot(800, lambda: self.run_action(
                '刷新设备信息', 'request_info', self.current_ip, 1,
                target=self.current_ip, alert=False))

    def power_dialog(self, ip=None):
        ip = ip or self.current_ip
        if not ip:
            self.report_operation('电源操作', '—', '尚未选择终端', ok=False)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('电源操作')
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 18)
        title = QLabel(f'电源操作  /  {ip}')
        title.setObjectName('dialogTitle')
        layout.addWidget(title)
        form = QFormLayout()
        operation = QComboBox()
        operation.addItems(('关机', '重启'))
        delay = QSpinBox()
        delay.setRange(0, 3600)
        delay.setSuffix(' 秒（0 = 立即强制）')
        text = QLineEdit('请保存当前工作')
        form.addRow('操作', operation)
        form.addRow('倒计时', delay)
        form.addRow('提示文字', text)
        layout.addLayout(form)
        warning = QLabel('此操作会中断学生机上的工作，请提前通知并确认。')
        warning.setObjectName('warning')
        warning.setWordWrap(True)
        layout.addWidget(warning)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        confirm = buttons.addButton('确认执行', QDialogButtonBox.ButtonRole.AcceptRole)
        confirm.setObjectName('dangerButton')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.run_action('电源操作', 'send_shutdown', ip,
                            operation.currentIndex() == 1, delay.value(),
                            delay.value() == 0, text.text() or None, target=ip)
        else:
            self.report_operation('电源操作', ip, '已取消', ok=True)

    def remote_channel_dialog(self, ip=None):
        ip = ip or self.current_ip
        if not ip:
            self.report_operation('远程频道', '—', '尚未选择终端', ok=False)
            QMessageBox.information(self, '尚未选择终端', '请先选择一台在线终端。')
            return
        channel, accepted = QInputDialog.getInt(
            self, '实验性远程频道设置', '学生端频道（1–32）：',
            core.CHANNEL_ID, 1, 32)
        if not accepted:
            self.report_operation('远程频道', ip, '已取消频道输入', ok=True)
            return
        login_box = QMessageBox(self)
        login_box.setWindowTitle('自动登录选择')
        login_box.setText(f'终端：{ip}\n目标频道：{channel}\n\n是否写入 AutoLogin=1（自动登录）？')
        login_box.setInformativeText(
            '实验性控制面：只发送 COMD category=0x4000 / subcase 7 设置包，'
            '不改变教师端自身运行频道。注册表写入、重启/重连风险及兼容性均未实机验证。')
        enable = login_box.addButton('启用自动登录（1）', QMessageBox.ButtonRole.YesRole)
        disable = login_box.addButton('不启用自动登录（0）', QMessageBox.ButtonRole.NoRole)
        cancel = login_box.addButton('取消', QMessageBox.ButtonRole.RejectRole)
        login_box.setDefaultButton(cancel)
        login_box.exec()
        clicked = login_box.clickedButton()
        if clicked is enable:
            auto_login = 1
        elif clicked is disable:
            auto_login = 0
        else:
            self.report_operation('远程频道', ip, '已取消自动登录选择', ok=True)
            return
        detail = (f'终端：{ip}\n目标频道：{channel}\nAutoLogin：{auto_login}\n\n'
                  '只向该学生单播 COMD category=0x4000 / subcase 7 远程设置包，'
                  '不改变教师端自身运行频道；没有结果回执，效果未实机验证。')
        if not self.confirm('二次确认 · 远程频道', detail):
            self.report_operation('远程频道', ip, '已取消二次确认', ok=True)
            return
        result = self.run_action('远程频道实验控制', 'send_remote_channel_settings',
                                 ip, channel, auto_login, target=ip)
        if result is not False:
            QMessageBox.information(
                self, '实验性控制包已发送',
                f'已向 {ip} 单播远程频道设置（频道 {channel}，AutoLogin {auto_login}）。\n\n'
                '注册表写入、频道切换与重启/重连效果均未实机验证；'
                '教师端自身运行频道未改变。')

    # ---------- QRMS / RRMS 审批 ----------

    def review_submit_request(self, accept):
        ip = self.current_ip
        request = self.students_snapshot().get(ip, {}).get('submit_request')
        if request is None:
            self.report_operation('文件提交审批', ip or '—', '所选终端没有文件提交请求', ok=False)
            QMessageBox.information(self, '无法审批', '所选终端没有文件提交请求。')
            return
        if request.get('status') != 'pending':
            self.report_operation('文件提交审批', ip,
                                  f"重复审批被阻止（状态 {request.get('status')}）", ok=False)
            self.update_selected_details()
            QMessageBox.information(
                self, '无法重复审批',
                f'{ip} 的文件提交请求已处理，未重复发送 RRMS。')
            return
        action = '接受' if accept else '拒绝'
        try:
            service = core.submission_service_info()
        except Exception:
            service = {'configured_port': 0, 'running': False, 'directory': '—'}
        detail = (f'RRMS 接受前会启动或复用 {core.ip}:{service["configured_port"]} 的'
                  f'本地接收服务，文件保存到 {service["directory"]} 下的独立事务目录。\n'
                  '只有本项目独立模拟工具向该端口发送 MiniMedia 帧时才会接收真实内容；'
                  'RRMS 本身不含文件内容。') if accept and service['configured_port'] else (
            ('当前文件接收端口为 0（禁用）：本次只发送 RRMS 接受审批，不接收文件内容。'
             if accept else '仅发送 RRMS 拒绝审批，不会启动接收服务。'))
        if not self.confirm(f'{action}文件提交',
                            f'终端：{ip}\n文件数：{request["file_count"]}\n\n{detail}'):
            self.report_operation('文件提交审批', ip, '已取消确认', ok=True)
            return
        result = self.run_action(f'RRMS {action}审批', 'respond_submit_request',
                                 ip, accept, target=ip)
        self.update_selected_details()
        if result is False:
            return
        QMessageBox.information(
            self, 'RRMS 审批已发送',
            f'已向 {ip} 发送 RRMS {action}审批。\n\n'
            '这只是审批结果，不是文件上传或传输完成。')

    def review_all_submit_requests(self, accept):
        pending = [ip for ip, student in self.students_snapshot().items()
                   if (student.get('submit_request') or {}).get('status') == 'pending']
        if not pending:
            self.report_operation('全部审批', '全班', '没有待审批的文件提交请求', ok=True)
            return
        action = '接受' if accept else '拒绝'
        if not self.confirm(f'全部{action}',
                            f'将向 {len(pending)} 个终端发送 RRMS {action}审批，确定继续吗？'):
            self.report_operation('全部审批', '全班', '已取消', ok=True)
            return
        for ip in pending:
            self.run_action(f'RRMS 全部{action}', 'respond_submit_request', ip, accept,
                            target=ip, alert=False)
        self.update_selected_details()

    def open_submission_folder(self):
        try:
            service = core.submission_service_info()
            folder = service.get('directory') or core.SUBMISSION_DIR
        except Exception:
            folder = getattr(core, 'SUBMISSION_DIR', '.')
        self.report_operation('打开已提交的文件', folder,
                              '接收目录：' + folder, ok=True)
        if os.path.isdir(folder):
            os.startfile(folder)
        else:
            QMessageBox.information(self, '接收目录',
                                    f'目录尚不存在：{folder}\n接受文件提交并接收文件后才会创建。')

    # ---------- 设置 / 班级 ----------

    def channel_settings(self):
        dialog = ChannelSettingsDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.report_operation('频道与接收设置', '本机', '已取消', ok=True)
            return
        self.save_channel_settings(dialog.channel_input.value(),
                                   dialog.submission_port_input.value())

    def save_channel_settings(self, channel, submission_port, show_dialog=True):
        path = app_config.config_path()
        try:
            app_config.save_settings(channel, submission_port, path)
        except (OSError, ValueError) as error:
            core.logger.error('[UI] 保存频道/文件接收端口失败 path=%s error=%s', path, error)
            self.report_operation('保存设置', path, f'无法写入配置：{error}', ok=False)
            QMessageBox.critical(self, '保存失败', f'无法写入配置：\n{error}')
            return False
        message = (f'已将下次启动频道保存为 {channel}，文件接收端口保存为 {submission_port}。\n'
                   f'当前运行频道仍为 {core.CHANNEL_ID}，文件接收端口仍为 '
                   f'{core.SUBMISSION_PORT}；重启教师端后生效。')
        core.logger.info('[UI] 设置已保存：下次启动频道=%d，文件接收端口=%d；path=%s',
                         channel, submission_port, path)
        self.report_operation('保存设置', path,
                              f'频道 {channel} / 端口 {submission_port} 已保存（重启生效）',
                              ok=True)
        if show_dialog:
            QMessageBox.information(self, '设置已保存', message)
        return True

    def open_classroom(self):
        if self.classroom_dialog is None:
            self.classroom_dialog = ClassroomDialog(self)
        self.classroom_dialog.panel.refresh_classroom()
        self.classroom_dialog.show()
        self.classroom_dialog.raise_()
        self.report_operation('管理班级', '本机', '已打开班级管理窗口', ok=True)

    def import_online_students(self):
        self.open_classroom()
        self.classroom_dialog.panel.import_classroom_students()

    def export_attendance_csv(self):
        self.open_classroom()
        self.classroom_dialog.panel.export_classroom_csv()

    def classroom_changed(self, event):
        if event.get('error') is not None:
            message = f'自动班级数据操作失败：{event["error"]}'
            self.report_operation('班级数据', '本机', message, ok=False)
        elif event.get('kind') == 'student_info':
            result = event.get('result')
            if result is not None:
                self.append_event(
                    f"{event['ip']} 信息已更新" +
                    ('，本次签到成功。' if result['checked_in'] else '，无需重复签到。'))
        if self.classroom_dialog is not None and self.classroom_dialog.isVisible():
            self.classroom_dialog.panel.refresh_classroom()
        if hasattr(self, 'embedded_classroom'):
            self.embedded_classroom.refresh_classroom()

    # ---------- 事件 / 消息 / 时钟 ----------

    def append_log(self, text, level):
        if hasattr(self, 'log_text'):
            self.log_text.appendPlainText(text)
        self.append_event(text)

    def append_chat(self, ip, text, outgoing=False):
        name = self.students_snapshot().get(ip, {}).get('info', {}).get('name') or ip
        direction = '教师' if outgoing else '学生'
        message = f'[{time.strftime("%H:%M:%S")}] {direction} · {name} ({ip})\n{text}'
        self.chat_history.appendPlainText(message)
        scrollbar = self.chat_history.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.append_event(message.replace('\n', ' / '))

    def tick(self):
        now = time.strftime('%H:%M:%S')
        self.status_time_label.setText(now)
        self.side_clock.setText(now[:5])
        channel = getattr(core, 'CHANNEL_ID', '?')
        self.channel_status_label.setText(f'频道 {channel:02d}' if isinstance(channel, int)
                                          else f'频道 {channel}')
        self.ip_status_label.setText(f'本机 {getattr(core, "ip", "?")}')
        status = self.core_call('get_network_status', default=None)
        if status is None:
            self.network_status_label.setText('网络 状态接口缺失')
        elif isinstance(status, dict):
            summary = ' / '.join(f'{key}={value}' for key, value in list(status.items())[:3])
            self.network_status_label.setText(f'网络 {summary}')
        else:
            self.network_status_label.setText(f'网络 {status}')
        preview = self.core_call('get_preview_status', default=None)
        if preview is None:
            self.setToolTip('预览状态接口缺失（已降级）')
        elif isinstance(preview, dict):
            self.setToolTip('预览状态：' + '，'.join(
                f'{key}={value}' for key, value in list(preview.items())[:6]))

    def confirm(self, title, text):
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    def closeEvent(self, event):
        if self.shutting_down:
            event.accept()
            return
        active = bool(getattr(core, 'remote_views', {}) or
                      getattr(core, 'remote_controls', {}) or
                      getattr(core, 'blackscreen_timers', {}))
        if active and not self.confirm('退出教师端',
                                       '仍有观看、远控或黑屏任务。确定停止本地会话并退出吗？'):
            event.ignore()
            return
        self.shutting_down = True
        self.timer.stop()
        self.clock_timer.stop()
        unbind = getattr(core, 'unbind_classroom_observer', None)
        if unbind:
            unbind(self.bridge.classroom.emit)
        else:
            self.note_missing('unbind_classroom_observer')
        for channel, callback in self.event_callbacks:
            channel.disconnect(callback)
        deadline = time.monotonic() + 3.0
        for worker in list(self.workers):
            remaining = max(0.05, deadline - time.monotonic())
            if not worker.wait(int(remaining * 1000)):
                core.logger.warning('[UI] 退出时后台任务 %s 仍在运行，保留引用避免线程对象被回收',
                                    worker.operation)
                RUNNING_WORKERS.append(worker)
        self.workers.clear()
        try:
            fn = getattr(core, 'shutdown', None)
            if fn is None:
                raise AttributeError('core.shutdown 不存在：无法释放网络端口与后台线程')
            fn()
            self.append_event('core.shutdown() 已执行：网络与后台线程已释放')
            core.logger.info('[UI] 关闭清理完成')
        except Exception as error:
            core.logger.exception('[UI] shutdown 失败：%s', error)
            QMessageBox.critical(self, '关闭清理失败', f'core.shutdown() 失败：\n{error}')
        if self.classroom_dialog is not None:
            self.classroom_dialog.close()
        event.accept()


STYLE = '''
* { font-family: "Microsoft YaHei UI", "Noto Sans SC", "Segoe UI", sans-serif;
    font-size: 12px; color: #20252e; }
QMainWindow, QWidget { background: #eef1f5; }
QFrame#topToolbar { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
    stop:0 #ffffff, stop:1 #e9edf3); border-bottom: 1px solid #c9d2dd; }
QToolButton#mainTool { background: transparent; border: 1px solid transparent;
    border-radius: 4px; padding: 3px 2px 2px 2px; color: #25313f; font-size: 11px; }
QToolButton#mainTool:hover { background: #e3f0ff; border: 1px solid #a9c9ef; }
QToolButton#mainTool:pressed { background: #cfe4fb; }
QToolButton#mainTool::menu-indicator { subcontrol-position: top right; width: 8px; height: 8px; }
QToolButton#mainTool::menu-button { background: transparent; border: none; width: 12px; }
QToolButton#mainTool::menu-button:hover { background: #e3f0ff; }
QToolButton#mainTool::menu-button:pressed { background: #cfe4fb; }
QToolButton#mainTool[unavailable="true"] { color: #9aa5b2; }
QToolButton#mainTool[experimental="true"] { color: #4a5a70; }
QToolButton#windowTool { background: transparent; border: 1px solid transparent;
    border-radius: 4px; }
QToolButton#windowTool:hover { background: #dde9f8; border: 1px solid #a9c9ef; }
QFrame#toolSeparator { background: #cbd4df; margin: 8px 4px; }
QFrame#viewRail { background: #e3e8ef; border-right: 1px solid #cbd4df; }
QPushButton#railButton { background: transparent; border: 1px solid transparent;
    border-radius: 4px; }
QPushButton#railButton:hover { background: #d4e3f7; }
QPushButton#railButton:checked { background: #d3e6ff; border: 1px solid #8fb8ea;
    border-left: 3px solid #2b7cd3; }
QFrame#centerArea { background: #f4f6f9; }
QFrame#memberTabs { background: #e7edf4; border: 1px solid #c9d2dd;
    border-top-left-radius: 4px; border-top-right-radius: 4px; }
QLabel#memberTab { background: #ffffff; border: 1px solid #c9d2dd;
    border-bottom: 2px solid #2b7cd3; padding: 5px 14px; font-weight: 700;
    color: #1d4f87; }
QPushButton#tabAdd, QPushButton#tabIcon { background: transparent;
    border: 1px solid transparent; padding: 0; }
QPushButton#tabAdd:hover, QPushButton#tabIcon:hover { background: #d6e6fa;
    border: 1px solid #a9c9ef; }
QWidget#cardsWidget { background: #ffffff; }
QWidget#emptyState { background: #ffffff; }
QLabel#emptyTitle { font-size: 19px; font-weight: 700; color: #9fb0c4; }
QFrame#studentCard { background: #ffffff; border: 1px solid #cdd6e1;
    border-radius: 4px; }
QFrame#studentCard:hover { border: 1px solid #7fb0e6; }
QFrame#studentCard[selected="true"] { border: 2px solid #2b7cd3; }
QWidget#cardBody { background: #ffffff; border-top: 1px solid #e3e8ef; }
QLabel#cardName { font-size: 13px; font-weight: 700; color: #1f2c3b; }
QLabel#cardAddress { font-size: 11px; color: #7b8794; }
QLabel#liveLabel { color: #177245; font-size: 11px; font-weight: 600; }
QLabel#liveLabel[alert="true"] { color: #c0392b; }
QPushButton#cardAction { background: #f4f7fb; border: 1px solid #cfd8e3;
    border-radius: 3px; padding: 4px 5px; font-size: 11px; color: #33465e; }
QPushButton#cardAction:hover { background: #e4f0ff; border-color: #8fb8ea; }
QPushButton#cardAction[viewing="true"] { background: #2b7cd3; color: #ffffff;
    border-color: #2b7cd3; }
QFrame#centerBottom { background: #e7edf4; border-top: 1px solid #c9d2dd; }
QPushButton#flatTool, QToolButton#flatTool { background: transparent;
    border: 1px solid transparent; border-radius: 3px; padding: 4px 8px;
    color: #2b4f7d; }
QPushButton#flatTool:hover, QToolButton#flatTool:hover { background: #d6e6fa;
    border: 1px solid #a9c9ef; }
QPushButton#flatTool:checked { background: #cfe0f7; border: 1px solid #8fb8ea; }
QFrame#sidePanel { background: #f2f5f9; border-left: 1px solid #c9d2dd; }
QPushButton#quickButton, QToolButton#quickButton { background: #ffffff;
    border: 1px solid #cbd5e1; border-radius: 3px; padding: 5px 6px;
    text-align: left; color: #25313f; }
QPushButton#quickButton:hover, QToolButton#quickButton:hover { background: #e6f1ff;
    border-color: #8fb8ea; }
QTabWidget#sideTabs::pane { border: 1px solid #cbd5e1; background: #ffffff; }
QTabBar::tab { background: #e6ebf2; color: #4b5868; padding: 6px 18px;
    border: 1px solid #cbd5e1; border-bottom: none; }
QTabBar::tab:selected { background: #ffffff; color: #1d4f87; font-weight: 700;
    border-bottom: 2px solid #2b7cd3; }
QLabel#sideSelected { font-weight: 700; color: #1d4f87; }
QFrame#statusBar { background: #e4e9f0; border-top: 1px solid #c6d0dc; }
QLabel#lastAction { color: #25313f; }
QLabel#lastAction[error="true"] { color: #c0392b; font-weight: 700; }
QLabel#statusField { color: #4b5868; }
QLabel#muted, QLabel#monoMuted { color: #6b7482; }
QLabel#sectionTitle { font-size: 16px; font-weight: 700; color: #1f2c3b; }
QLabel#dialogTitle { font-size: 16px; font-weight: 700; color: #1d4f87;
    padding-bottom: 8px; }
QLabel#panelCaption { font-size: 12px; font-weight: 700; color: #3b4a5e; }
QLabel#counter { color: #1d4f87; font-weight: 700; }
QLabel#warning { color: #8a4b00; background: #fff3dd; border: 1px solid #f0d3a0;
    padding: 7px; border-radius: 3px; }
QFrame#panel { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; }
QPushButton { background: #ffffff; color: #25313f; border: 1px solid #c3cedb;
    border-radius: 3px; padding: 6px 10px; }
QPushButton:hover { background: #e8f2ff; border-color: #8fb8ea; }
QPushButton:pressed { background: #d3e5fb; }
QPushButton:disabled { color: #9aa5b2; background: #f2f4f7; }
QPushButton#smallButton { padding: 4px 8px; font-size: 11px; }
QPushButton#accentButton { background: #2b7cd3; color: #ffffff;
    border: 1px solid #2b7cd3; font-weight: 700; }
QPushButton#accentButton:hover { background: #3b8ce3; }
QPushButton#dangerButton { background: #c0392b; color: #ffffff;
    border: 1px solid #c0392b; }
QLineEdit, QPlainTextEdit, QListWidget, QTableWidget, QComboBox, QSpinBox {
    background: #ffffff; color: #20252e; border: 1px solid #c3cedb;
    border-radius: 3px; padding: 5px;
    selection-background-color: #cfe2fb; selection-color: #102f52; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #2b7cd3; }
QLineEdit#searchField { background: #ffffff; }
QTableWidget { border: 1px solid #cbd5e1; gridline-color: #e3e8ef;
    alternate-background-color: #f7f9fc; }
QTableWidget::item { padding: 5px; }
QTableWidget::item:selected { background: #cfe2fb; color: #102f52; }
QHeaderView::section { background: #eaf0f7; color: #4b5868; border: none;
    border-right: 1px solid #d7dfe9; border-bottom: 1px solid #c9d2dd;
    padding: 7px; font-weight: 700; }
QListWidget::item { padding: 6px; }
QListWidget::item:selected { background: #cfe2fb; color: #102f52; }
QTabWidget::pane { border: 1px solid #cbd5e1; background: #ffffff; }
QPlainTextEdit#logView { background: #fbfcfe; color: #3b4a5e;
    font-family: "Consolas", monospace; font-size: 11px; }
QCheckBox { spacing: 6px; }
QRadioButton { spacing: 6px; }
QSlider::groove:horizontal { background: #d5dee9; height: 5px; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #2b7cd3; border-radius: 2px; }
QSlider::handle:horizontal { background: #ffffff; border: 1px solid #7c93ad;
    width: 12px; margin: -5px 0; border-radius: 6px; }
QMenu { background: #ffffff; color: #20252e; border: 1px solid #c3cedb; padding: 4px; }
QMenu::item { padding: 7px 24px; border-radius: 3px; }
QMenu::item:selected { background: #e2effd; }
QMenu::item:disabled { color: #9aa5b2; }
QDialog { background: #f2f5f9; }
QToolTip { background: #ffffff; color: #20252e; border: 1px solid #a9bdd4;
    padding: 5px; }
QScrollBar:vertical { background: transparent; width: 9px; }
QScrollBar::handle:vertical { background: #b9c6d6; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
'''


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('极域课堂管理系统 · 教师端')
    app.setStyle('Fusion')
    load_ui_fonts()
    app.setStyleSheet(STYLE)

    starter = getattr(core, 'start_network', None)
    if starter is None:
        STARTUP_WARNINGS.append(
            'core.start_network() 不存在：未由 GUI 初始化网络（core 版本不匹配）')
    else:
        try:
            started = starter()
            detail = ''
            status_fn = getattr(core, 'get_network_status', None)
            if status_fn:
                try:
                    status = status_fn()
                    detail = str(status.get('error') or '') if isinstance(status, dict) else ''
                    if isinstance(status, dict) and status.get('network_started') is False:
                        started = False
                except Exception:
                    pass
            if started is False:
                raise RuntimeError(detail or 'start_network() 返回 False，网络未启动')
        except Exception as error:
            message = (f'无法启动教师端网络：{type(error).__name__}: {error}\n\n'
                       '请检查 UDP 4705/会话端口占用、单实例互斥、网卡选择与 Windows 防火墙。')
            core.logger.exception('[UI] 网络启动失败：%s', error)
            QMessageBox.critical(None, '网络启动失败', message)
            return 1

    window = MainWindow()
    window.show()

    thread_starter = getattr(core, 'start_background_threads', None)
    if thread_starter is None:
        window.report_operation('启动后台线程', '本机',
                                'core.start_background_threads() 不存在：后台线程未启动', ok=False)
    else:
        try:
            thread_starter()
            window.report_operation('启动后台线程', '本机', '4 个后台线程已启动', ok=True)
        except Exception as error:
            core.logger.exception('[UI] 后台线程启动失败：%s', error)
            window.report_operation('启动后台线程', '本机',
                                    f'异常：{error}', ok=False)
            QMessageBox.critical(window, '后台线程启动失败',
                                 f'core.start_background_threads() 失败：\n{error}')

    exit_code = app.exec()
    if not window.shutting_down:
        shutdown = getattr(core, 'shutdown', None)
        if shutdown:
            shutdown()
        else:
            core.logger.error('[UI] core.shutdown 缺失，无法释放端口')
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
