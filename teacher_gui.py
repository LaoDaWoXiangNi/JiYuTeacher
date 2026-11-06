import logging
import os
import sys
import time
from functools import partial

from PyQt6.QtCore import QObject, QRectF, QSize, Qt, QTimer, QDateTime, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget,
    QFileDialog, QInputDialog,
    QTabWidget, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

import app_config
import gui_events

CHANNEL_FROM_ENV = 'TEACHER_CHANNEL' in os.environ
SUBMISSION_PORT_FROM_ENV = app_config.has_explicit_submission_port()
if not CHANNEL_FROM_ENV:
    os.environ['TEACHER_CHANNEL'] = str(app_config.load_channel())

import teacher_sim as core


CYAN = '#63e6d4'
INK = '#090e17'
PANEL = '#101722'
MUTED = '#7f8c9f'


def load_ui_fonts():
    if getattr(sys, 'frozen', False):
        folder = os.path.join(sys._MEIPASS, 'fonts')
        for filename in ('NotoSansSC.ttf', 'CascadiaMono.ttf'):
            path = os.path.join(folder, filename)
            if os.path.isfile(path):
                QFontDatabase.addApplicationFont(path)


def icon(name, color=CYAN, size=20):
    image = QPixmap(size, size)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.65, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    scale = size / 24
    painter.scale(scale, scale)

    def line(x1, y1, x2, y2):
        painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def rect(x, y, w, h, radius=2):
        painter.drawRoundedRect(QRectF(x, y, w, h), radius, radius)

    if name == 'grid':
        for x, y in ((3, 3), (14, 3), (3, 14), (14, 14)):
            rect(x, y, 7, 7, 1)
    elif name == 'monitor':
        rect(2.5, 3.5, 19, 13)
        line(12, 17, 12, 21)
        line(8, 21, 16, 21)
    elif name == 'devices':
        rect(2, 4, 14, 11)
        line(6, 19, 13, 19)
        line(9, 15, 9, 19)
        rect(16, 8, 6, 12, 1)
    elif name == 'message':
        painter.drawRoundedRect(QRectF(3, 4, 18, 15), 3, 3)
        line(7, 19, 5, 22)
        line(5, 22, 12, 19)
        line(8, 10, 16, 10)
        line(8, 14, 13, 14)
    elif name == 'terminal':
        rect(2.5, 3.5, 19, 17)
        line(6, 8, 9, 11)
        line(9, 11, 6, 14)
        line(12, 15, 18, 15)
    elif name == 'eye':
        path = QPainterPath()
        path.moveTo(2, 12)
        path.quadTo(12, 1, 22, 12)
        path.quadTo(12, 23, 2, 12)
        painter.drawPath(path)
        painter.drawEllipse(QRectF(9, 9, 6, 6))
    elif name == 'cursor':
        path = QPainterPath()
        path.moveTo(5, 2)
        path.lineTo(19, 12)
        path.lineTo(12, 13)
        path.lineTo(9, 21)
        path.closeSubpath()
        painter.drawPath(path)
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
    elif name == 'lock':
        rect(4, 10, 16, 11, 2)
        painter.drawArc(QRectF(7, 2, 10, 12), 0, 180 * 16)
        line(12, 14, 12, 17)
    elif name == 'unlock':
        rect(4, 10, 16, 11, 2)
        painter.drawArc(QRectF(7, 2, 10, 12), 25 * 16, 135 * 16)
        line(12, 14, 12, 17)
    elif name == 'play':
        path = QPainterPath()
        path.moveTo(7, 4)
        path.lineTo(19, 12)
        path.lineTo(7, 20)
        path.closeSubpath()
        painter.drawPath(path)
    elif name == 'power':
        painter.drawArc(QRectF(4, 5, 16, 16), 130 * 16, 280 * 16)
        line(12, 2, 12, 12)
    elif name == 'search':
        painter.drawEllipse(QRectF(3, 3, 13, 13))
        line(14, 14, 21, 21)
    elif name == 'more':
        painter.setBrush(QColor(color))
        for x in (5, 12, 19):
            painter.drawEllipse(QRectF(x - 1.4, 10.6, 2.8, 2.8))
    elif name == 'send':
        path = QPainterPath()
        path.moveTo(3, 3)
        path.lineTo(21, 12)
        path.lineTo(3, 21)
        path.lineTo(7, 12)
        path.closeSubpath()
        painter.drawPath(path)
        line(7, 12, 21, 12)
    elif name == 'settings':
        rect(3, 4, 18, 16)
        line(3, 9, 21, 9)
        for x in (7, 12, 17):
            painter.drawEllipse(QRectF(x - 1, 5.5, 2, 2))
    elif name == 'classroom':
        rect(3, 4, 18, 16)
        line(3, 9, 21, 9)
        line(8, 9, 8, 20)
        painter.drawEllipse(QRectF(10, 11, 4, 4))
        line(10, 18, 16, 18)
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
    def __init__(self):
        super().__init__()
        self.pixmap = None
        self.setMinimumHeight(148)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_image(self, image):
        if isinstance(image, QImage):
            self.pixmap = QPixmap.fromImage(image)
        else:
            rgb = image.convert('RGB')
            data = rgb.tobytes('raw', 'RGB')
            qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3,
                            QImage.Format.Format_RGB888).copy()
            self.pixmap = QPixmap.fromImage(qimage)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor('#080d14'))
        if not self.pixmap:
            painter.setPen(QColor('#354154'))
            painter.setFont(QFont('Segoe UI', 10))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'NO SIGNAL')
            painter.setPen(QColor('#283446'))
            for x in range(0, self.width(), 32):
                painter.drawLine(x, 0, x, self.height())
            for y in range(0, self.height(), 32):
                painter.drawLine(0, y, self.width(), y)
            return
        scaled = self.pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap((self.width() - scaled.width()) // 2,
                           (self.height() - scaled.height()) // 2, scaled)


class StudentCard(QFrame):
    def __init__(self, ip, select_callback, action_callback):
        super().__init__()
        self.ip = ip
        self.select_callback = select_callback
        self.setObjectName('studentCard')
        self.setProperty('selected', False)
        self.setMinimumWidth(270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.preview = PreviewWidget()
        self.preview.setFixedHeight(174)
        layout.addWidget(self.preview)
        body = QVBoxLayout()
        body.setContentsMargins(15, 13, 15, 13)
        body.setSpacing(5)
        title_row = QHBoxLayout()
        self.name = QLabel(ip)
        self.name.setObjectName('cardName')
        title_row.addWidget(self.name)
        title_row.addStretch()
        self.live = QLabel('●  ONLINE')
        self.live.setObjectName('liveLabel')
        title_row.addWidget(self.live)
        body.addLayout(title_row)
        self.address = QLabel(ip)
        self.address.setObjectName('monoMuted')
        body.addWidget(self.address)
        actions = QHBoxLayout()
        actions.setSpacing(7)
        for text, glyph, action in (
            ('观看', 'eye', 'view'), ('远控', 'cursor', 'control'),
            ('消息', 'message', 'chat'), ('管理', 'devices', 'details'),
        ):
            button = QPushButton(icon(glyph, '#9eacbd', 16), text)
            button.setObjectName('cardAction')
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(partial(action_callback, action, ip))
            actions.addWidget(button)
        body.addSpacing(6)
        body.addLayout(actions)
        layout.addLayout(body)

    def mousePressEvent(self, event):
        self.select_callback(self.ip)
        super().mousePressEvent(event)

    def update_student(self, student):
        info = student.get('info', {})
        name = info.get('name') or '未命名终端'
        user = info.get('user')
        self.name.setText(name)
        self.name.setToolTip(name)
        self.address.setText(f'{self.ip}  /  {user}' if user else self.ip)
        hand_up = student.get('anno_state', {}).get('hand_up', False)
        has_submit = student.get('submit_request', {}).get('status') == 'pending'
        self.live.setText('▲  FILE SUBMIT' if has_submit else
                          ('▲  HAND UP' if hand_up else '●  ONLINE'))
        self.live.setProperty('handUp', hand_up or has_submit)
        self.live.style().unpolish(self.live)
        self.live.style().polish(self.live)

    def set_selected(self, selected):
        self.setProperty('selected', selected)
        self.style().unpolish(self)
        self.style().polish(self)


class TextCommandDialog(QDialog):
    def __init__(self, title, fields, parent=None, confirm_text='执行'):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        heading = QLabel(title)
        heading.setObjectName('dialogTitle')
        layout.addWidget(heading)
        form = QFormLayout()
        form.setSpacing(14)
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
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
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
            env_note = QLabel('\n'.join(env_notes))
            env_note.setObjectName('warning')
            env_note.setWordWrap(True)
            layout.addWidget(env_note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        save = buttons.addButton('保存', QDialogButtonBox.ButtonRole.AcceptRole)
        save.setObjectName('accentButton')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('JIYU CONTROL — Classroom Console')
        self.resize(1500, 940)
        self.setMinimumSize(1160, 760)
        self.cards = {}
        self.current_ip = None
        self.shutting_down = False
        self.submission_events_by_ip = {}
        self.bridge = UiBridge()
        self.bridge.preview.connect(self.set_preview)
        self.bridge.log.connect(self.append_log)
        self.bridge.chat.connect(self.append_chat)
        self.bridge.classroom.connect(self.classroom_changed)
        self.bridge.submission.connect(self.submission_changed)
        core.bind_classroom_observer(self.bridge.classroom.emit)
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
        self.refresh_students()
        self.refresh_classroom()
        core.logger.info('教师端在线 · %s · 频道 %d', core.ip, core.CHANNEL_ID)

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self.create_sidebar())
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.create_header())
        self.pages = QStackedWidget()
        self.pages.addWidget(self.create_dashboard())
        self.pages.addWidget(self.create_management())
        self.pages.addWidget(self.create_messages())
        self.pages.addWidget(self.create_logs())
        self.pages.addWidget(self.create_classroom())
        body.addWidget(self.pages, 1)
        body.addWidget(self.create_statusbar())
        shell.addLayout(body, 1)

    def create_sidebar(self):
        side = QFrame()
        side.setObjectName('rail')
        side.setFixedWidth(78)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(10, 24, 10, 20)
        layout.setSpacing(12)
        logo = QLabel('J')
        logo.setObjectName('logo')
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)
        layout.addSpacing(28)
        self.nav_buttons = []
        for index, glyph, tooltip in (
            (0, 'grid', '课堂'), (1, 'devices', '终端'),
            (2, 'message', '消息'), (3, 'terminal', '日志'),
            (4, 'classroom', '班级'),
        ):
            button = QPushButton(icon(glyph, '#8290a4', 23), '')
            button.setObjectName('railButton')
            button.setToolTip(tooltip)
            button.setCheckable(True)
            button.setFixedSize(56, 52)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(partial(self.change_page, index))
            layout.addWidget(button)
            self.nav_buttons.append(button)
        self.nav_buttons[0].setChecked(True)
        layout.addStretch()
        channel = QLabel(f'{core.CHANNEL_ID:02d}')
        channel.setObjectName('channelBadge')
        channel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        channel.setToolTip(f'当前运行频道 {core.CHANNEL_ID}')
        layout.addWidget(channel)
        settings = QPushButton(icon('settings', '#8290a4', 18), '')
        settings.setObjectName('channelSettings')
        settings.setToolTip('频道与文件接收设置（重启生效）')
        settings.setAccessibleName('频道与接收设置')
        settings.setAccessibleDescription(
            '配置下次启动使用的教师端频道和文件接收端口，端口范围 0 到 65535')
        settings.setFixedSize(56, 38)
        settings.setCursor(Qt.CursorShape.PointingHandCursor)
        settings.clicked.connect(self.channel_settings)
        layout.addWidget(settings)
        return side

    def create_header(self):
        header = QFrame()
        header.setObjectName('topbar')
        header.setFixedHeight(88)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(30, 0, 30, 0)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        eyebrow = QLabel('CLASSROOM  /  LIVE CONTROL')
        eyebrow.setObjectName('eyebrow')
        self.page_title = QLabel('课堂工作台')
        self.page_title.setObjectName('pageTitle')
        title_box.addWidget(eyebrow)
        title_box.addWidget(self.page_title)
        layout.addLayout(title_box)
        layout.addStretch()
        network = QLabel(f'CHANNEL {core.CHANNEL_ID:02d}   /   {core.ip}')
        network.setObjectName('monoMuted')
        layout.addWidget(network)
        layout.addSpacing(24)
        online = QLabel('●  SERVICE ONLINE')
        online.setObjectName('serviceOnline')
        layout.addWidget(online)
        return header

    def create_dashboard(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 24, 30, 20)
        layout.setSpacing(20)
        toolbar = QHBoxLayout()
        title = QLabel('实时屏幕')
        title.setObjectName('sectionTitle')
        toolbar.addWidget(title)
        self.screen_count = QLabel('00 DEVICES')
        self.screen_count.setObjectName('counter')
        toolbar.addWidget(self.screen_count)
        toolbar.addStretch()
        search_box = QFrame()
        search_box.setObjectName('searchBox')
        search_layout = QHBoxLayout(search_box)
        search_layout.setContentsMargins(10, 0, 5, 0)
        search_layout.addWidget(self.icon_label('search'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索终端 / IP')
        self.search.setFrame(False)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.arrange_cards)
        search_layout.addWidget(self.search)
        search_box.setFixedWidth(225)
        toolbar.addWidget(search_box)
        refresh = QPushButton(icon('refresh', INK, 17), '刷新预览')
        refresh.setObjectName('accentButton')
        refresh.clicked.connect(self.refresh_all_previews)
        toolbar.addWidget(refresh)
        more = QToolButton()
        more.setIcon(icon('more', '#a2afc0', 20))
        more.setToolTip('全班操作')
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction('全班黑屏', partial(self.blackscreen_dialog, None))
        menu.addAction('解除全班黑屏', self.unlock_all)
        menu.addSeparator()
        menu.addAction('刷新全班设备信息', self.refresh_all_info)
        more.setMenu(menu)
        toolbar.addWidget(more)
        layout.addLayout(toolbar)
        self.scroll = CardScrollArea(self.arrange_cards)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_widget = QWidget()
        self.cards_layout = QGridLayout(self.cards_widget)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(18)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.cards_widget)
        layout.addWidget(self.scroll, 1)
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon = QLabel()
        empty_icon.setPixmap(icon('monitor', '#344258', 58).pixmap(58, 58))
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_text = QLabel('等待终端接入')
        empty_text.setObjectName('emptyTitle')
        empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint = QLabel('学生端上线后，屏幕将自动出现在这里\n检查局域网、UDP 组播与 Windows 防火墙设置')
        empty_hint.setObjectName('muted')
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_icon)
        empty_layout.addWidget(empty_text)
        empty_layout.addWidget(empty_hint)
        self.cards_layout.addWidget(self.empty, 0, 0)
        return page

    def icon_label(self, name):
        label = QLabel()
        label.setPixmap(icon(name, '#718096', 17).pixmap(17, 17))
        return label

    def create_management(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 24, 30, 24)
        splitter = QSplitter()
        left = QFrame()
        left.setObjectName('panel')
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        caption = QLabel('在线终端')
        caption.setObjectName('panelCaption')
        left_layout.addWidget(caption)
        self.student_table = QTableWidget(0, 4)
        self.student_table.setHorizontalHeaderLabels(('计算机 / IP', '用户', '系统', '内存'))
        self.student_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.student_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.student_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.student_table.verticalHeader().setVisible(False)
        self.student_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.student_table.itemSelectionChanged.connect(self.select_table_student)
        left_layout.addWidget(self.student_table)
        splitter.addWidget(left)
        side = QFrame()
        side.setObjectName('panel')
        side.setMinimumWidth(370)
        side.setMaximumWidth(470)
        box = QVBoxLayout(side)
        box.setContentsMargins(18, 18, 18, 18)
        self.selected_label = QLabel('选择一台终端')
        self.selected_label.setObjectName('sectionTitle')
        box.addWidget(self.selected_label)
        self.device_tabs = QTabWidget()
        device_page = QWidget()
        device_layout = QVBoxLayout(device_page)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.setSpacing(0)
        self.info_text = QPlainTextEdit()
        self.info_text.setReadOnly(True)
        device_layout.addWidget(self.info_text, 1)
        self.submit_controls = QWidget()
        submit_layout = QHBoxLayout(self.submit_controls)
        submit_layout.setContentsMargins(8, 8, 8, 8)
        submit_layout.setSpacing(8)
        self.accept_submit_button = QPushButton('接受文件提交')
        self.accept_submit_button.clicked.connect(
            lambda: self.review_submit_request(True))
        self.reject_submit_button = QPushButton('拒绝文件提交')
        self.reject_submit_button.clicked.connect(
            lambda: self.review_submit_request(False))
        submit_layout.addWidget(self.accept_submit_button)
        submit_layout.addWidget(self.reject_submit_button)
        device_layout.addWidget(self.submit_controls)
        self.submit_controls.hide()
        self.submission_status_label = QLabel('')
        self.submission_status_label.setObjectName('muted')
        self.submission_status_label.setWordWrap(True)
        self.submission_status_label.hide()
        device_layout.addWidget(self.submission_status_label)
        self.device_tabs.addTab(device_page, '设备')
        self.process_table = self.id_name_table(('PID', '进程名称'))
        self.device_tabs.addTab(self.process_table, '进程')
        self.window_table = self.id_name_table(('句柄', '窗口标题'))
        self.device_tabs.addTab(self.window_table, '窗口')
        box.addWidget(self.device_tabs, 1)
        controls = QGridLayout()
        controls.setSpacing(8)
        actions = (
            ('刷新信息', 'refresh', lambda: self.selected(core.request_info)),
            ('请求预览', 'monitor', lambda: self.selected(core.request_preview)),
            ('连续观看', 'eye', lambda: self.selected(self.start_view)),
            ('屏幕广播', 'monitor', self.toggle_broadcast),
            ('学生演示', 'devices', self.toggle_student_demo),
            ('远程控制', 'cursor', lambda: self.selected(self.start_control)),
            ('发送消息', 'message', lambda: self.selected(self.chat_dialog)),
            ('黑屏安静', 'lock', lambda: self.selected(self.blackscreen_dialog)),
            ('解除黑屏', 'unlock', lambda: self.selected(core.send_unlock)),
            ('远程运行', 'play', lambda: self.selected(self.run_dialog)),
            ('打开网页', 'settings', lambda: self.selected(self.url_dialog)),
            ('远程频道', 'settings', self.remote_channel_dialog),
            ('结束进程', 'terminal', self.kill_selected_process),
            ('关闭窗口', 'devices', self.close_selected_window),
            ('关机 / 重启', 'power', lambda: self.selected(self.power_dialog)),
        )
        for index, (text, glyph, callback) in enumerate(actions):
            button = QPushButton(icon(glyph, '#91a0b5', 16), text)
            button.clicked.connect(callback)
            controls.addWidget(button, index // 2, index % 2)
        box.addLayout(controls)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 1)
        layout.addWidget(splitter)
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

    def create_messages(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(18)
        recipients = QFrame()
        recipients.setObjectName('panel')
        recipients.setMaximumWidth(310)
        recipients_layout = QVBoxLayout(recipients)
        label = QLabel('收件终端')
        label.setObjectName('panelCaption')
        recipients_layout.addWidget(label)
        self.message_students = QListWidget()
        self.message_students.itemClicked.connect(
            lambda item: self.select_student(item.data(Qt.ItemDataRole.UserRole)))
        recipients_layout.addWidget(self.message_students)
        layout.addWidget(recipients)
        composer = QFrame()
        composer.setObjectName('panel')
        right = QVBoxLayout(composer)
        right.setContentsMargins(24, 22, 24, 22)
        overline = QLabel('DIRECT MESSAGE')
        overline.setObjectName('eyebrow')
        right.addWidget(overline)
        self.chat_target = QLabel('选择收件终端')
        self.chat_target.setObjectName('dialogTitle')
        right.addWidget(self.chat_target)
        self.chat_history = QPlainTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setMaximumBlockCount(3000)
        self.chat_history.setObjectName('chatHistory')
        self.chat_history.setPlaceholderText('暂无聊天记录')
        right.addWidget(self.chat_history, 1)
        self.chat_input = QPlainTextEdit()
        self.chat_input.setPlaceholderText('输入消息内容…\n\n消息将通过 MESS 会话通道发送到所选终端。')
        right.addWidget(self.chat_input, 1)
        send = QPushButton(icon('send', INK, 17), '发送消息')
        send.setObjectName('accentButton')
        send.clicked.connect(self.send_current_message)
        right.addWidget(send, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(composer, 1)
        return page

    def create_logs(self):
        page = QFrame()
        page.setObjectName('logPage')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 24, 30, 24)
        tools = QHBoxLayout()
        path = QLabel(core.LOG_PATH)
        path.setObjectName('monoMuted')
        tools.addWidget(path)
        tools.addStretch()
        self.debug_toggle = QCheckBox('DEBUG 协议详情')
        self.debug_toggle.toggled.connect(lambda enabled: core.set_file_log_level(
            logging.DEBUG if enabled else logging.INFO))
        tools.addWidget(self.debug_toggle)
        clear = QPushButton('清空显示')
        clear.clicked.connect(lambda: self.log_text.clear())
        tools.addWidget(clear)
        layout.addLayout(tools)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(3000)
        self.log_text.setObjectName('logView')
        layout.addWidget(self.log_text)
        return page

    def create_classroom(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(14)
        toolbar = QHBoxLayout()
        self.class_selector = QComboBox()
        self.class_selector.setEditable(True)
        self.class_selector.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.class_selector.setMinimumWidth(240)
        self.class_selector.setPlaceholderText('选择班级，或输入名称后新建')
        self.class_selector.activated.connect(self.select_active_class)
        toolbar.addWidget(self.class_selector)
        for text, callback in (
                ('新建班级', self.create_classroom_class),
                ('导入在线学生', self.import_classroom_students),
                ('导出签到 CSV', self.export_classroom_csv)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.classroom_stats = QLabel('尚未选择班级')
        self.classroom_stats.setObjectName('counter')
        layout.addWidget(self.classroom_stats, 0, Qt.AlignmentFlag.AlignLeft)
        self.classroom_status = QLabel('自动签到仅处理当前班级已导入的学生。')
        self.classroom_status.setObjectName('muted')
        layout.addWidget(self.classroom_status)
        splitter = QSplitter()
        group_panel = QFrame()
        group_panel.setObjectName('panel')
        group_layout = QVBoxLayout(group_panel)
        group_layout.setContentsMargins(0, 0, 0, 12)
        group_caption = QLabel('分组与成员')
        group_caption.setObjectName('panelCaption')
        group_layout.addWidget(group_caption)
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
            button.clicked.connect(callback)
            group_buttons.addWidget(button)
        group_layout.addLayout(group_buttons)
        self.group_member_list = QListWidget()
        self.group_member_list.setMaximumHeight(170)
        group_layout.addWidget(self.group_member_list)
        self.group_student_selector = QComboBox()
        group_layout.addWidget(self.group_student_selector)
        member_buttons = QHBoxLayout()
        for text, callback in (
                ('添加成员', self.add_classroom_member),
                ('移除成员', self.remove_classroom_member),
                ('设为组长', self.set_classroom_leader)):
            button = QPushButton(text)
            button.clicked.connect(callback)
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
        splitter.setSizes((390, 760))
        layout.addWidget(splitter, 1)
        return page

    def classroom_error(self, operation, error):
        core.logger.error('[UI] %s失败：%s', operation, error,
                          exc_info=(type(error), error, error.__traceback__))
        self.classroom_status.setText(f'{operation}失败：{error}')
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
            if self.isVisible():
                QMessageBox.critical(self, '读取班级数据失败', str(error))

    def classroom_changed(self, event):
        if event.get('error') is not None:
            self.classroom_error('自动班级数据操作', event['error'])
        elif event.get('kind') == 'student_info':
            result = event.get('result')
            if result is not None:
                self.classroom_status.setText(
                    f"{event['ip']} 信息已更新" +
                    ('，本次签到成功。' if result['checked_in'] else '，无需重复签到。'))
        self.refresh_classroom()

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
        if selected_row >= 0:
            self.group_table.selectRow(selected_row)
        self.refresh_group_details()
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

    @staticmethod
    def format_attendance_time(value):
        if not value:
            return '—'
        parsed = QDateTime.fromString(value, Qt.DateFormat.ISODate)
        return (parsed.toLocalTime().toString('yyyy-MM-dd HH:mm:ss')
                if parsed.isValid() else value)

    def select_active_class(self):
        name = self.class_selector.currentText().strip()
        if name not in core.classroom_store.list_classes():
            return
        try:
            core.set_active_class(name)
            self.classroom_status.setText(f'当前班级：{name}')
            self.refresh_classroom()
        except Exception as error:
            self.classroom_error('切换班级', error)

    def create_classroom_class(self):
        name = self.class_selector.currentText().strip()
        try:
            core.classroom_store.create_class(name)
            core.set_active_class(name)
            self.classroom_status.setText(f'已创建并选择班级：{name}')
            self.refresh_classroom()
        except Exception as error:
            self.classroom_error('新建班级', error)

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
        if imported:
            QMessageBox.information(
                self, '导入完成', f'已导入 {len(imported)} 名学生。\n'
                '已根据当前在线信息触发签到，后续重复上报不会重复计数。')
        else:
            QMessageBox.information(self, '没有新学生', '没有可导入的新在线学生。')
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
            core.logger.info('[UI] 签到 CSV 已导出 class=%s path=%s', name, path)
            QMessageBox.information(self, '导出完成', f'签到记录已保存到：\n{path}')
        except Exception as error:
            self.classroom_error('导出签到 CSV', error)

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
            matches = self.group_table.findItems(
                group_name.strip(), Qt.MatchFlag.MatchExactly)
            if matches:
                self.group_table.selectRow(matches[0].row())
        except Exception as error:
            self.classroom_error('新建分组', error)

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
            self.classroom_error('重命名分组', error)

    def delete_classroom_group(self):
        name = self.require_classroom()
        group_name = self.selected_classroom_group()
        if not name or not group_name:
            return
        if not self.confirm('删除分组', f'确定删除分组“{group_name}”吗？班级学生会保留。'):
            return
        try:
            core.classroom_store.delete_group(name, group_name)
            self.refresh_classroom()
        except Exception as error:
            self.classroom_error('删除分组', error)

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
            self.classroom_error('添加分组成员', error)

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
            self.classroom_error('移除分组成员', error)

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
            self.classroom_error('指定组长', error)

    def create_statusbar(self):
        bar = QFrame()
        bar.setObjectName('statusbar')
        bar.setFixedHeight(38)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(28, 0, 28, 0)
        self.online_stat = QLabel('00 ONLINE')
        self.online_stat.setObjectName('statusStrong')
        layout.addWidget(self.online_stat)
        separator = QLabel('/')
        separator.setObjectName('muted')
        layout.addWidget(separator)
        self.view_stat = QLabel('00 STREAMS')
        self.view_stat.setObjectName('monoMuted')
        layout.addWidget(self.view_stat)
        layout.addStretch()
        protocol = QLabel(
            f'JIYU V6.0   ·   UDP {core.PORT} / {core.SPORT}   ·   TCP 4806   ·   '
            f'FILE {core.SUBMISSION_PORT or "OFF"}')
        protocol.setObjectName('monoMuted')
        layout.addWidget(protocol)
        return bar

    def change_page(self, index):
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
            button.setIcon(icon(('grid', 'devices', 'message', 'terminal', 'classroom')[i],
                                CYAN if i == index else '#8290a4', 23))
        self.page_title.setText(('课堂工作台', '终端管理', '消息中心', '事件日志', '班级管理')[index])
        if index == 4:
            self.refresh_classroom()

    def channel_settings(self):
        dialog = ChannelSettingsDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        channel = dialog.channel_input.value()
        submission_port = dialog.submission_port_input.value()
        path = app_config.config_path()
        try:
            app_config.save_settings(channel, submission_port, path)
        except OSError as error:
            core.logger.error('[UI] 保存频道/文件接收端口失败 path=%s error=%s',
                              path, error)
            QMessageBox.critical(self, '保存失败', f'无法写入配置：\n{error}')
            return
        core.logger.info('[UI] 设置已保存：下次启动频道=%d，文件接收端口=%d；'
                         '当前频道=%d，当前端口=%d，path=%s',
                         channel, submission_port, core.CHANNEL_ID,
                         core.SUBMISSION_PORT, path)
        message = (f'已将下次启动频道保存为 {channel}，文件接收端口保存为 {submission_port}。\n'
                   f'当前运行频道仍为 {core.CHANNEL_ID}，文件接收端口仍为 '
                   f'{core.SUBMISSION_PORT}；重启教师端后生效。')
        if submission_port == 0:
            message += '\n\n端口 0 表示禁用文件接收，RRMS 接受仍只完成审批。'
        else:
            message += ('\n\n该端口仅用于本项目独立模拟工具联调，未确认官方学生端端口；'
                        '重启后首次接受文件提交时才会惰性启动监听。')
        if CHANNEL_FROM_ENV:
            message += '\n\n当前存在 TEACHER_CHANNEL 环境变量，启动时将优先使用该变量。'
        if SUBMISSION_PORT_FROM_ENV:
            message += ('\n当前存在 TEACHER_SUBMISSION_PORT 环境变量，启动时将优先使用该变量；'
                        '配置文件中的端口不会覆盖它。')
        QMessageBox.information(self, '设置已保存', message)

    def refresh_students(self):
        current = set(core.students)
        for ip in set(self.cards) - current:
            self.cards_layout.removeWidget(self.cards[ip])
            self.cards[ip].deleteLater()
            del self.cards[ip]
        for ip in sorted(current):
            if ip not in self.cards:
                self.cards[ip] = StudentCard(ip, self.select_student, self.card_action)
            self.cards[ip].update_student(core.students[ip])
            self.cards[ip].set_selected(ip == self.current_ip)
        if self.current_ip not in current:
            self.current_ip = next(iter(sorted(current)), None)
        hand_up_count = sum(student.get('anno_state', {}).get('hand_up', False)
                            for student in core.students.values())
        self.online_stat.setText(f'{len(current):02d} ONLINE / {hand_up_count:02d} HAND UP')
        self.view_stat.setText(f'{len(core.remote_views):02d} STREAMS')
        self.screen_count.setText(f'{len(current):02d} DEVICES')
        self.refresh_student_table()
        self.arrange_cards()

    def arrange_cards(self):
        query = self.search.text().strip().lower()
        visible = []
        for ip, card in self.cards.items():
            match = not query or query in ip.lower() or query in card.name.text().lower()
            card.setVisible(match)
            if match:
                visible.append(card)
        self.empty.setVisible(not visible)
        while self.cards_layout.count():
            self.cards_layout.takeAt(0)
        if not visible:
            self.cards_layout.addWidget(self.empty, 0, 0)
            return
        width = max(300, self.scroll.viewport().width())
        columns = max(1, min(4, (width + 18) // 330))
        for index, card in enumerate(visible):
            self.cards_layout.addWidget(card, index // columns, index % columns,
                                        Qt.AlignmentFlag.AlignTop)
        for column in range(columns):
            self.cards_layout.setColumnStretch(column, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'cards_layout'):
            self.arrange_cards()

    def refresh_student_table(self):
        students = sorted(core.students.items())
        self.student_table.setUpdatesEnabled(False)
        self.student_table.setRowCount(len(students))
        self.message_students.clear()
        for row, (ip, student) in enumerate(students):
            info = student.get('info', {})
            values = (f"{info.get('name') or '未命名终端'}\n{ip}", info.get('user', '—'),
                      info.get('os', '—'), info.get('mem', '—'))
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, ip)
                self.student_table.setItem(row, column, item)
                if ip == self.current_ip:
                    item.setSelected(True)
            entry = QListWidgetItem(icon('monitor', '#8b9bb0', 19),
                                    f"{info.get('name') or ip}\n{ip}")
            entry.setData(Qt.ItemDataRole.UserRole, ip)
            self.message_students.addItem(entry)
        self.student_table.setUpdatesEnabled(True)
        self.update_selected_details()

    def select_table_student(self):
        item = self.student_table.item(self.student_table.currentRow(), 0)
        if item:
            self.select_student(item.data(Qt.ItemDataRole.UserRole), refresh=False)

    def select_student(self, ip, refresh=True):
        if ip not in core.students:
            return
        self.current_ip = ip
        for card_ip, card in self.cards.items():
            card.set_selected(card_ip == ip)
        self.chat_target.setText(f'发送至 {ip}')
        if refresh:
            self.refresh_student_table()
        else:
            self.update_selected_details()

    def update_selected_details(self):
        student = core.students.get(self.current_ip, {})
        info = student.get('info', {})
        self.selected_label.setText(info.get('name') or self.current_ip or '选择一台终端')
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
                           f'事务接收目录：{submit.get("submission_directory")}'
                           '\n（仅对本项目独立模拟工具有效，未验证原版学生端）')
        service = core.submission_service_info()
        if service['configured_port']:
            status += (f'\n文件接收端口：{service["configured_port"]}'
                       f'（{"已监听" if service["running"] else "接受时启动"}）'
                       f'  根目录：{service["directory"]}')
        else:
            status += '\n文件接收端口：0（禁用）；RRMS 接受仅完成审批，不接收文件内容'
        receipts = core.get_submission_receipts(self.current_ip) if self.current_ip else []
        if receipts:
            last = receipts[-1]
            status += (f'\n最近接收完成：{last["file"]}，{last["bytes"]} 字节\n'
                       f'接收路径：{last["path"]}')
        self.info_text.setPlainText(('\n'.join(
            f'{label}：{self.current_ip if key is None else info.get(key, "待上报")}'
            for label, key in labels) + '\n' + status) if self.current_ip else '请先从左侧选择终端。')
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
        if hasattr(self, 'chat_history'):
            self.chat_history.appendPlainText(
                f'[{time.strftime("%H:%M:%S")}] 文件接收 · {student_ip}\n{summary}')
            scrollbar = self.chat_history.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        if student_ip == self.current_ip:
            self.refresh_submission_event()

    def refresh_submission_event(self):
        if not hasattr(self, 'submission_status_label'):
            return
        summary = self.submission_events_by_ip.get(self.current_ip)
        self.submission_status_label.setText(f'最新文件接收事件\n{summary}' if summary else '')
        self.submission_status_label.setVisible(bool(summary))

    def review_submit_request(self, accept):
        ip = self.current_ip
        request = core.students.get(ip, {}).get('submit_request')
        if request is None:
            core.logger.warning('[UI] 文件提交审批取消 target=%s reason=没有请求', ip)
            QMessageBox.information(self, '无法审批', '所选终端没有文件提交请求。')
            return
        if request.get('status') != 'pending':
            core.logger.warning('[UI] 文件提交审批取消 target=%s guid=%s reason=重复审批',
                                ip, request['transaction_guid'])
            self.update_selected_details()
            QMessageBox.information(
                self, '无法重复审批',
                f'{ip} 的文件提交请求已处理，状态为 {request.get("status")}，未重复发送 RRMS。')
            return
        action = '接受' if accept else '拒绝'
        service = core.submission_service_info()
        if accept and service['configured_port']:
            detail = (f'RRMS 接受前会启动或复用 {core.ip}:{service["configured_port"]} 的'
                      f'本地接收服务，文件保存到 {service["directory"]} 下的独立事务目录。\n'
                      '只有使用本项目独立模拟工具向该端口发送 MiniMedia 帧时才会接收真实内容；'
                      'RRMS 本身不含文件内容。\n'
                      '官方学生端端口与兼容性尚未确认，本次操作不代表原版实机兼容。')
        elif accept:
            detail = ('当前文件接收端口为 0（禁用）：本次只发送 RRMS 接受审批，'
                      '不启动接收服务，也不会接收真实文件内容。\n'
                      '可在“频道与接收设置”中填写 1–65535 并重启教师端后再启用接收。')
        else:
            detail = '仅发送 RRMS 拒绝审批，不会启动接收服务，也不会接收文件内容。'
        core.logger.info('[UI] 文件提交审批确认 target=%s guid=%s action=%s port=%d',
                         ip, request['transaction_guid'], action,
                         service['configured_port'])
        if not self.confirm(f'{action}文件提交',
                            f'终端：{ip}\n文件数：{request["file_count"]}\n\n{detail}'):
            core.logger.info('[UI] 文件提交审批已取消 target=%s action=%s', ip, action)
            return
        result = self.run_action(core.respond_submit_request, ip, accept)
        self.update_selected_details()
        if result is False:
            return
        message = (f'已向 {ip} 发送 RRMS {action}审批。当前状态：{result["status"]}。\n\n'
                   '这只是审批结果，不是文件上传或传输完成。')
        if accept and result.get('submission_port'):
            message += (f'\n接收服务：{core.ip}:{result["submission_port"]}；'
                        f'事务目录：{result.get("submission_directory")}。\n'
                        '仅独立模拟工具按该端口上传后，消息中心和设备详情才会显示'
                        '接收路径与字节数；不代表已与原版学生端实机兼容。')
        elif accept:
            message += '\n未配置接收端口，本次没有传输或接收任何文件。'
        core.logger.info('[UI] 文件提交审批完成 target=%s guid=%s status=%s port=%d',
                         ip, result['transaction_guid'], result['status'],
                         result.get('submission_port', 0))
        QMessageBox.information(self, 'RRMS 审批已发送', message)

    def fill_id_name_table(self, table, rows, hexadecimal):
        table.setRowCount(len(rows))
        for row, (identifier, name) in enumerate(rows):
            value = f'0x{identifier:08X}' if hexadecimal else str(identifier)
            table.setItem(row, 0, QTableWidgetItem(value))
            table.setItem(row, 1, QTableWidgetItem(name))

    def selected(self, callback):
        if not self.current_ip:
            QMessageBox.information(self, '尚未选择终端', '请先选择一台在线终端。')
            return
        self.run_action(callback, self.current_ip)

    def run_action(self, callback, *args):
        operation = getattr(callback, '__name__', str(callback))
        core.logger.info('[UI] 操作发起 action=%s target=%s args=%s',
                         operation, self.current_ip, repr(args))
        try:
            result = callback(*args)
            if result is False:
                core.logger.warning('[UI] 操作被拒绝或未完成 action=%s target=%s',
                                    operation, self.current_ip)
            else:
                core.logger.info('[UI] 操作已提交 action=%s target=%s result=%s',
                                 operation, self.current_ip, repr(result))
            return result
        except Exception as error:
            core.logger.exception('[UI] 操作失败 action=%s target=%s error=%s',
                                  operation, self.current_ip, error)
            QMessageBox.critical(self, '操作失败', str(error))
            return False

    def toggle_broadcast(self):
        if not self.current_ip:
            QMessageBox.information(self, '尚未选择终端', '请先选择广播目标。')
            return
        ip = self.current_ip
        if ip in core.screen_broadcasts:
            self.run_action(core.stop_screen_broadcast, ip)
        else:
            started = self.run_action(core.start_screen_broadcast, ip)
            if started:
                QMessageBox.information(
                    self, '广播启动包已发送',
                    '学生端已收到 feature 1 启动参数。\n'
                    '当前版本尚未推送屏幕媒体流，这不代表学生端已经显示画面。')

    def toggle_student_demo(self):
        if not self.current_ip:
            QMessageBox.information(self, '尚未选择终端', '请先选择演示学生。')
            return
        source_ip = self.current_ip
        if source_ip in core.student_demos:
            self.run_action(core.stop_student_demo, source_ip)
            return
        default_port = os.environ.get('TEACHER_DEMO_VOICE_PORT', '9000')
        port, accepted = QInputDialog.getInt(self, '实验性语音控制', '语音监听端口（1–65535）：',
                                             int(default_port), 1, 65535)
        if not accepted:
            return
        detail = ('将向演示学生发送 feature 4 最小语音启停控制包。\n'
                  '地址和端口取值尚未实机确认；屏幕分发与媒体监看尚未实现。')
        if not self.confirm('实验性学生演示控制', f'演示学生：{source_ip}\n\n{detail}'):
            return
        core.logger.info('[UI] 实验性 feature 4 语音启停 source=%s port=%d', source_ip, port)
        if self.run_action(core.start_student_demo, source_ip, port):
            QMessageBox.information(self, '实验性控制包已发送',
                                    '仅语音启停控制有静态证据；不代表学生屏幕已广播。')

    def remote_channel_dialog(self):
        ip = self.current_ip
        if not ip:
            QMessageBox.information(self, '尚未选择终端', '请先选择一台在线终端。')
            return
        channel, accepted = QInputDialog.getInt(
            self, '实验性远程频道设置', '学生端频道（1–32）：',
            core.CHANNEL_ID, 1, 32)
        if not accepted:
            core.logger.info('[UI] 远程频道设置取消 target=%s reason=频道输入取消', ip)
            return
        login_box = QMessageBox(self)
        login_box.setWindowTitle('自动登录选择')
        login_box.setText(f'终端：{ip}\n目标频道：{channel}\n\n是否写入 AutoLogin=1（自动登录）？')
        login_box.setInformativeText(
            '实验性控制面：只发送 COMD category=0x4000 / subcase 7 设置包，'
            '不改变教师端自身运行频道。学生端注册表写入、重启/重连风险及'
            '官方教师端兼容性均未实机验证。')
        enable_button = login_box.addButton('启用自动登录（1）',
                                            QMessageBox.ButtonRole.YesRole)
        disable_button = login_box.addButton('不启用自动登录（0）',
                                             QMessageBox.ButtonRole.NoRole)
        cancel_button = login_box.addButton('取消', QMessageBox.ButtonRole.RejectRole)
        login_box.setDefaultButton(cancel_button)
        login_box.exec()
        clicked = login_box.clickedButton()
        if clicked is enable_button:
            auto_login = 1
        elif clicked is disable_button:
            auto_login = 0
        else:
            core.logger.info('[UI] 远程频道设置取消 target=%s channel=%d '
                             'reason=自动登录选择取消', ip, channel)
            return
        detail = (f'终端：{ip}\n目标频道：{channel}\nAutoLogin：{auto_login}\n\n'
                  '这是实验性控制面：只向该学生单播 COMD category=0x4000 / subcase 7 '
                  '远程设置包，不改变教师端自身运行频道。\n'
                  '学生端可能需要重启或重连后生效，并有掉线风险；注册表写入、'
                  '实际频道切换与官方教师端兼容性均未实机验证，也没有结果回执。')
        if not self.confirm('二次确认 · 远程频道', detail):
            core.logger.info('[UI] 远程频道设置取消 target=%s channel=%d '
                             'auto_login=%d reason=二次确认取消',
                             ip, channel, auto_login)
            return
        core.logger.info('[UI] 远程频道设置发起 target=%s channel=%d auto_login=%d '
                         '（实验性控制面，教师端自身频道不变）', ip, channel, auto_login)
        if self.run_action(core.send_remote_channel_settings, ip, channel,
                           auto_login) is not False:
            QMessageBox.information(
                self, '实验性控制包已发送',
                f'已向 {ip} 单播远程频道设置（频道 {channel}，AutoLogin {auto_login}）。\n\n'
                '只发送了控制面：学生端注册表写入、频道切换与重启/重连效果均未实机验证，'
                '官方教师端兼容性未验证。教师端自身运行频道未改变。')

    def card_action(self, action, ip):
        self.select_student(ip)
        if action == 'details':
            self.change_page(1)
        elif action == 'chat':
            self.chat_dialog(ip)
        elif action == 'view':
            self.start_view(ip)
        elif action == 'control':
            self.start_control(ip)

    def set_preview(self, ip, image):
        if ip in self.cards:
            self.cards[ip].preview.set_image(image)

    def append_log(self, text, level):
        if hasattr(self, 'log_text'):
            self.log_text.appendPlainText(text)

    def append_chat(self, ip, text, outgoing=False):
        name = core.students.get(ip, {}).get('info', {}).get('name') or ip
        direction = '教师' if outgoing else '学生'
        self.chat_history.appendPlainText(
            f'[{time.strftime("%H:%M:%S")}] {direction} · {name} ({ip})\n{text}')
        scrollbar = self.chat_history.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def refresh_all_previews(self):
        for ip in list(core.students):
            self.run_action(core.request_preview, ip)

    def refresh_all_info(self):
        for ip in list(core.students):
            self.run_action(core.request_info, ip)

    def start_view(self, ip):
        self.run_action(core.cmd_view, [ip])

    def start_control(self, ip):
        self.run_action(core.cmd_control, [ip])

    def chat_dialog(self, ip):
        self.select_student(ip)
        self.change_page(2)
        self.chat_input.setFocus()

    def send_current_message(self):
        text = self.chat_input.toPlainText().strip()
        if not text:
            return
        if not self.current_ip:
            QMessageBox.information(self, '尚未选择终端', '请先选择收件终端。')
            return
        result = self.run_action(core.send_chat, self.current_ip, text)
        if result is not False:
            self.append_chat(self.current_ip, text, outgoing=True)
            self.chat_input.clear()

    def blackscreen_dialog(self, ip):
        dialog = QDialog(self)
        dialog.setWindowTitle('黑屏安静')
        dialog.setMinimumWidth(450)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(26, 24, 26, 24)
        title = QLabel(f'黑屏安静  /  {ip or self.current_ip or "全班"}')
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
            return
        targets = list(core.students) if ip is None and self.current_ip is None else [ip or self.current_ip]
        for student_ip in targets:
            self.run_action(core.send_blackscreen, student_ip, lock.isChecked(),
                            timeout.value(), text.text() or None)

    def unlock_all(self):
        for ip in list(core.students):
            self.run_action(core.send_unlock, ip)

    def run_dialog(self, ip):
        dialog = TextCommandDialog('远程运行程序', (
            ('path', '程序路径', r'C:\Windows\notepad.exe', '学生机上的绝对路径'),
            ('args', '启动参数', '', '可选'),
        ), self, '运行')
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.values()
            if values['path']:
                self.run_action(core.send_run_program, ip, values['path'], values['args'])

    def url_dialog(self, ip):
        dialog = TextCommandDialog('打开网页或文件', (
            ('url', '网址 / 路径', 'https://', '将在学生机上打开'),
        ), self, '打开')
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.values()['url']:
            self.run_action(core.send_open_url, ip, dialog.values()['url'])

    def selected_row_target(self, table, hexadecimal=False):
        item = table.item(table.currentRow(), 0)
        if item is None:
            QMessageBox.information(self, '尚未选择目标', '请先刷新信息并在列表中选择一个目标。')
            return None
        return int(item.text(), 16 if hexadecimal else 10)

    def kill_selected_process(self):
        if not self.current_ip:
            return
        pid = self.selected_row_target(self.process_table)
        if pid is not None and self.confirm('结束进程', f'确定结束 {self.current_ip} 的进程 PID {pid} 吗？'):
            self.run_action(core.send_kill, self.current_ip, pid, None, 1)
            QTimer.singleShot(800, lambda: self.run_action(core.request_info, self.current_ip, 2))

    def close_selected_window(self):
        if not self.current_ip:
            return
        hwnd = self.selected_row_target(self.window_table, True)
        if hwnd is not None and self.confirm('关闭窗口', '确定向所选窗口发送关闭命令吗？'):
            self.run_action(core.send_kill, self.current_ip, None, hwnd, 0)
            QTimer.singleShot(800, lambda: self.run_action(core.request_info, self.current_ip, 1))

    def power_dialog(self, ip):
        core.logger.info('[UI] 打开电源操作确认 target=%s', ip)
        dialog = QDialog(self)
        dialog.setWindowTitle('电源操作')
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(26, 24, 26, 24)
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
            self.run_action(core.send_shutdown, ip, operation.currentIndex() == 1,
                            delay.value(), delay.value() == 0, text.text() or None)

    def confirm(self, title, text):
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    def closeEvent(self, event):
        if self.shutting_down:
            event.accept()
            return
        active = bool(core.remote_views or core.remote_controls or core.blackscreen_timers)
        if active and not self.confirm('退出教师端', '仍有观看、远控或黑屏任务。确定停止本地会话并退出吗？'):
            event.ignore()
            return
        self.shutting_down = True
        self.timer.stop()
        core.unbind_classroom_observer(self.bridge.classroom.emit)
        for channel, callback in self.event_callbacks:
            channel.disconnect(callback)
        core.shutdown()
        event.accept()


STYLE = '''
* { font-family: "Noto Sans SC", "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; }
QMainWindow, QWidget { background: #0b111b; color: #dce4ee; }
QFrame#rail { background: #080d15; border-right: 1px solid #1b2635; }
QFrame#rail QLabel { background: transparent; }
QLabel#logo { background: #63e6d4; color: #081310; border-radius: 10px; font-size: 25px; font-weight: 900; min-height: 44px; max-height: 44px; }
QPushButton#railButton { background: transparent; border: 0; border-radius: 10px; }
QPushButton#railButton:hover, QPushButton#channelSettings:hover { background: #142131; }
QPushButton#channelSettings { background: transparent; border: 0; padding: 0; }
QPushButton#railButton:checked { background: #173432; border-left: 2px solid #63e6d4; }
QLabel#channelBadge { color: #63e6d4; border: 1px solid #28534f; border-radius: 8px; padding: 8px 0; font-family: "Cascadia Mono", monospace; font-weight: 700; }
QFrame#topbar { background: #0e151f; border-bottom: 1px solid #1c2735; }
QFrame#topbar QLabel, QFrame#statusbar QLabel, QFrame#rail QLabel { background: transparent; }
QLabel#eyebrow { color: #63e6d4; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QLabel#pageTitle { color: #f1f5fa; font-size: 23px; font-weight: 700; }
QLabel#serviceOnline { color: #63e6d4; font-size: 11px; font-weight: 700; }
QLabel#sectionTitle { font-size: 18px; font-weight: 700; color: #eef3f8; }
QLabel#dialogTitle { font-size: 20px; font-weight: 700; color: #eef3f8; padding-bottom: 10px; }
QLabel#counter { color: #8290a4; background: #141e2b; border: 1px solid #233043; border-radius: 5px; padding: 4px 8px; font-family: "Cascadia Mono", monospace; font-size: 10px; }
QLabel#muted, QLabel#monoMuted { color: #7f8c9f; }
QLabel#monoMuted { font-family: "Cascadia Mono", "Consolas", monospace; font-size: 11px; }
QFrame#searchBox { background: #111a26; border: 1px solid #253247; border-radius: 7px; }
QFrame#searchBox QLabel { background: transparent; }
QFrame#searchBox QLineEdit { background: transparent; border: 0; padding: 8px 4px; }
QFrame#studentCard { background: #111a26; border: 1px solid #253043; border-radius: 10px; }
QFrame#studentCard:hover { border: 1px solid #426176; }
QFrame#studentCard[selected="true"] { border: 1px solid #63e6d4; }
QFrame#studentCard PreviewWidget { background: #080d14; border-top-left-radius: 9px; border-top-right-radius: 9px; }
QLabel#cardName { font-size: 14px; font-weight: 700; color: #e4ebf3; }
QLabel#liveLabel { color: #63e6d4; font-size: 9px; font-weight: 700; }
QLabel#liveLabel[handUp="true"] { color: #f3bd65; font-size: 10px; }
QLabel#emptyTitle { font-size: 21px; font-weight: 700; color: #c1ccda; }
QFrame#panel { background: #0e1621; border: 1px solid #202d3d; border-radius: 9px; }
QLabel#panelCaption { font-size: 14px; font-weight: 700; padding: 16px; background: transparent; }
QPushButton { background: #172231; color: #b8c5d5; border: 1px solid #2a394d; border-radius: 6px; padding: 8px 12px; }
QPushButton:hover { background: #203043; border-color: #496079; color: #eef5fc; }
QPushButton:pressed { background: #0f1824; }
QPushButton#cardAction { background: transparent; border-color: #28374a; padding: 6px 7px; font-size: 11px; }
QPushButton#cardAction:hover { background: #1b2a3b; border-color: #47647a; }
QPushButton#accentButton { background: #63e6d4; color: #081512; border: 1px solid #63e6d4; font-weight: 700; }
QPushButton#accentButton:hover { background: #8bf2e4; border-color: #8bf2e4; color: #081512; }
QPushButton#dangerButton { background: #d75b66; color: white; border-color: #d75b66; }
QLineEdit, QPlainTextEdit, QListWidget, QTableWidget, QComboBox, QSpinBox { background: #0c141f; color: #d4deea; border: 1px solid #263549; border-radius: 6px; padding: 7px; selection-background-color: #24514e; selection-color: #eafffb; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #4b9d93; }
QTableWidget { border: 0; border-top: 1px solid #202d3d; border-radius: 0; gridline-color: #1d2a3a; alternate-background-color: #111c28; }
QTableWidget::item { padding: 9px; border-bottom: 1px solid #1b2735; }
QTableWidget::item:selected { background: #173432; color: #bff8ef; }
QHeaderView::section { background: #111b28; color: #8291a5; border: 0; border-bottom: 1px solid #253449; padding: 10px; font-weight: 600; }
QListWidget::item { padding: 12px; border-bottom: 1px solid #1b2939; }
QListWidget::item:selected { background: #173432; color: #bff8ef; }
QTabWidget::pane { border: 1px solid #253347; background: #0c141f; border-radius: 6px; }
QTabBar::tab { background: transparent; padding: 10px 16px; color: #7e8da1; }
QTabBar::tab:selected { color: #63e6d4; border-bottom: 2px solid #63e6d4; }
QPlainTextEdit#logView { background: #080d15; color: #a9bacd; border-color: #202e40; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px; }
QFrame#statusbar { background: #080e16; border-top: 1px solid #1d2938; }
QLabel#statusStrong { color: #63e6d4; font-family: "Cascadia Mono", monospace; font-size: 11px; font-weight: 700; }
QLabel#warning { color: #efbc78; background: #2b241a; padding: 10px; border-radius: 6px; }
QScrollArea { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #344357; border-radius: 4px; min-height: 35px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QMenu { background: #121d2a; color: #d7e1ed; border: 1px solid #304158; padding: 5px; }
QMenu::item { padding: 8px 24px; border-radius: 4px; }
QMenu::item:selected { background: #21433f; }
QCheckBox { spacing: 8px; }
QDialog { background: #0e1621; }
QToolTip { background: #1d2b3b; color: #e4edf7; border: 1px solid #364b63; padding: 5px; }
'''


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('JIYU CONTROL')
    app.setStyle('Fusion')
    load_ui_fonts()
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    core.start_background_threads()
    exit_code = app.exec()
    if not window.shutting_down:
        core.shutdown()
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
