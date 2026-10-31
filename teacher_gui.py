import logging
import os
import sys
from functools import partial

from PyQt6.QtCore import QObject, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget,
    QTabWidget, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

import gui_events
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
    painter.end()
    return QIcon(image)


class UiBridge(QObject):
    preview = pyqtSignal(str, object)
    log = pyqtSignal(str, int)


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
        live = QLabel('●  ONLINE')
        live.setObjectName('liveLabel')
        title_row.addWidget(live)
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('JIYU CONTROL — Classroom Console')
        self.resize(1500, 940)
        self.setMinimumSize(1160, 760)
        self.cards = {}
        self.current_ip = None
        self.shutting_down = False
        self.bridge = UiBridge()
        self.bridge.preview.connect(self.set_preview)
        self.bridge.log.connect(self.append_log)
        gui_events.preview_events.connect(self.bridge.preview.emit)
        gui_events.log_events.connect(self.bridge.log.emit)
        self.build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_students)
        self.timer.start(800)
        self.refresh_students()
        self.append_log(f'教师端在线 · {core.ip} · 频道 {core.CHANNEL_ID}', logging.INFO)

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
        channel.setToolTip(f'当前频道 {core.CHANNEL_ID}')
        layout.addWidget(channel)
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
        self.info_text = QPlainTextEdit()
        self.info_text.setReadOnly(True)
        self.device_tabs.addTab(self.info_text, '设备')
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
            ('远程控制', 'cursor', lambda: self.selected(self.start_control)),
            ('发送消息', 'message', lambda: self.selected(self.chat_dialog)),
            ('黑屏安静', 'lock', lambda: self.selected(self.blackscreen_dialog)),
            ('解除黑屏', 'unlock', lambda: self.selected(core.send_unlock)),
            ('远程运行', 'play', lambda: self.selected(self.run_dialog)),
            ('打开网页', 'settings', lambda: self.selected(self.url_dialog)),
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
        protocol = QLabel('JIYU V6.0   ·   UDP 4705 / 5512   ·   TCP 4806')
        protocol.setObjectName('monoMuted')
        layout.addWidget(protocol)
        return bar

    def change_page(self, index):
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
            button.setIcon(icon(('grid', 'devices', 'message', 'terminal')[i],
                                CYAN if i == index else '#8290a4', 23))
        self.page_title.setText(('课堂工作台', '终端管理', '消息中心', '事件日志')[index])

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
        self.online_stat.setText(f'{len(current):02d} ONLINE')
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
        self.info_text.setPlainText('\n'.join(
            f'{label}：{self.current_ip if key is None else info.get(key, "待上报")}'
            for label, key in labels) if self.current_ip else '请先从左侧选择终端。')
        self.fill_id_name_table(self.process_table, student.get('processes', []), False)
        self.fill_id_name_table(self.window_table, student.get('windows', []), True)

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
        self.run_action(core.send_chat, self.current_ip, text)
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
        gui_events.preview_events.disconnect(self.bridge.preview.emit)
        gui_events.log_events.disconnect(self.bridge.log.emit)
        core.shutdown()
        event.accept()


STYLE = '''
* { font-family: "Noto Sans SC", "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; }
QMainWindow, QWidget { background: #0b111b; color: #dce4ee; }
QFrame#rail { background: #080d15; border-right: 1px solid #1b2635; }
QFrame#rail QLabel { background: transparent; }
QLabel#logo { background: #63e6d4; color: #081310; border-radius: 10px; font-size: 25px; font-weight: 900; min-height: 44px; max-height: 44px; }
QPushButton#railButton { background: transparent; border: 0; border-radius: 10px; }
QPushButton#railButton:hover { background: #142131; }
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
