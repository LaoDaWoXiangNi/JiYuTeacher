import logging
import os
import sys
from functools import partial

os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QFrame, QGraphicsDropShadowEffect, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QStyle, QTabWidget,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

import gui_events
import teacher_sim as core


class UiBridge(QObject):
    preview = pyqtSignal(str, object)
    log = pyqtSignal(str, int)


class FlowLayout(QGridLayout):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setHorizontalSpacing(18)
        self.setVerticalSpacing(18)

    def relayout(self, width):
        count = self.count()
        if not count:
            return
        columns = max(1, min(4, width // 330))
        for index in range(count):
            item = self.takeAt(0)
            self.addWidget(item.widget(), index // columns, index % columns)
        for column in range(columns):
            self.setColumnStretch(column, 1)


class StudentCard(QFrame):
    def __init__(self, ip, selected_callback, action_callback):
        super().__init__()
        self.ip = ip
        self.selected_callback = selected_callback
        self.action_callback = action_callback
        self.setObjectName('studentCard')
        self.setMinimumWidth(290)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.status = QLabel('●')
        self.status.setObjectName('onlineDot')
        self.name = QLabel(ip)
        self.name.setObjectName('cardTitle')
        self.address = QLabel(ip)
        self.address.setObjectName('muted')
        top.addWidget(self.status)
        top.addWidget(self.name)
        top.addStretch()
        top.addWidget(self.address)
        layout.addLayout(top)

        self.screen = QLabel('等待屏幕预览')
        self.screen.setObjectName('preview')
        self.screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen.setMinimumHeight(168)
        self.pixmap = None
        layout.addWidget(self.screen)

        self.detail = QLabel('正在获取设备信息…')
        self.detail.setObjectName('muted')
        layout.addWidget(self.detail)

        actions = QHBoxLayout()
        for text, action in (('观看', 'view'), ('远控', 'control'), ('消息', 'chat'), ('更多', 'details')):
            button = QPushButton(text)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(partial(action_callback, action, ip))
            actions.addWidget(button)
        layout.addLayout(actions)

    def update_student(self, student):
        info = student.get('info', {})
        self.name.setText(info.get('name') or self.ip)
        user = info.get('user', '未知用户')
        system = info.get('os', '系统信息待上报')
        self.detail.setText(f'{user}  ·  {system}')

    def set_preview(self, image):
        if isinstance(image, QImage):
            self.pixmap = QPixmap.fromImage(image)
        else:
            rgb = image.convert('RGB')
            data = rgb.tobytes('raw', 'RGB')
            qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3,
                            QImage.Format.Format_RGB888).copy()
            self.pixmap = QPixmap.fromImage(qimage)
        self.update_preview()

    def update_preview(self):
        if self.pixmap:
            self.screen.setPixmap(self.pixmap.scaled(
                self.screen.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_preview()


class TextCommandDialog(QDialog):
    def __init__(self, title, fields, parent=None, confirm_text='发送'):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.inputs = {}
        for key, label, value, placeholder in fields:
            editor = QLineEdit(value)
            editor.setPlaceholderText(placeholder)
            form.addRow(label, editor)
            self.inputs[key] = editor
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        confirm = buttons.addButton(confirm_text, QDialogButtonBox.ButtonRole.AcceptRole)
        confirm.setObjectName('primaryButton')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {key: editor.text().strip() for key, editor in self.inputs.items()}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('JiYu Studio · 极域教师端')
        self.resize(1440, 900)
        self.setMinimumSize(1120, 720)
        self.cards = {}
        self.last_previews = {}
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
        self.timer.start(750)
        self.refresh_students()
        self.append_log(f'教师端在线 · {core.ip} · 频道 {core.CHANNEL_ID}', logging.INFO)

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        nav = QFrame()
        nav.setObjectName('sidebar')
        nav.setFixedWidth(210)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(18, 28, 18, 22)
        nav_layout.setSpacing(8)
        brand = QLabel('JIYU / STUDIO')
        brand.setObjectName('brand')
        subtitle = QLabel('课堂连接，清晰可见')
        subtitle.setObjectName('muted')
        nav_layout.addWidget(brand)
        nav_layout.addWidget(subtitle)
        nav_layout.addSpacing(30)
        self.nav_buttons = []
        for index, text in enumerate(('课堂总览', '学生管理', '消息中心', '运行日志')):
            button = QPushButton(text)
            button.setObjectName('navButton')
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(partial(self.change_page, index))
            nav_layout.addWidget(button)
            self.nav_buttons.append(button)
        self.nav_buttons[0].setChecked(True)
        nav_layout.addStretch()
        version = QLabel('V6.0 协议兼容\nPython · Qt 原生桌面')
        version.setObjectName('muted')
        nav_layout.addWidget(version)
        shell.addWidget(nav)

        content = QFrame()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 24, 32, 24)
        content_layout.setSpacing(20)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        self.page_title = QLabel('课堂总览')
        self.page_title.setObjectName('pageTitle')
        self.page_subtitle = QLabel('实时掌握课堂状态与学生屏幕')
        self.page_subtitle.setObjectName('muted')
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        header.addLayout(titles)
        header.addStretch()
        self.connection = QLabel(f'● 在线  {core.ip}')
        self.connection.setObjectName('connection')
        header.addWidget(self.connection)
        content_layout.addLayout(header)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.create_dashboard())
        self.pages.addWidget(self.create_management())
        self.pages.addWidget(self.create_messages())
        self.pages.addWidget(self.create_logs())
        content_layout.addWidget(self.pages, 1)
        shell.addWidget(content, 1)

    def create_dashboard(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        stats = QHBoxLayout()
        self.online_stat = self.stat_card('在线学生', '0', '等待学生端接入')
        self.channel_stat = self.stat_card('当前频道', str(core.CHANNEL_ID), f'{core.SMCAST}:{core.SPORT}')
        self.view_stat = self.stat_card('观看会话', '0', 'TCP / UMSP')
        for card in (self.online_stat, self.channel_stat, self.view_stat):
            stats.addWidget(card)
        layout.addLayout(stats)
        toolbar = QHBoxLayout()
        title = QLabel('学生屏幕')
        title.setObjectName('sectionTitle')
        toolbar.addWidget(title)
        toolbar.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索名称或 IP')
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(230)
        self.search.textChanged.connect(self.arrange_cards)
        toolbar.addWidget(self.search)
        refresh = QPushButton('刷新全部预览')
        refresh.setObjectName('primaryButton')
        refresh.clicked.connect(self.refresh_all_previews)
        toolbar.addWidget(refresh)
        more = QToolButton()
        more.setText('全班操作')
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(more)
        menu.addAction('全班黑屏', partial(self.blackscreen_dialog, None))
        menu.addAction('解除全班黑屏', self.unlock_all)
        menu.addSeparator()
        menu.addAction('刷新全班设备信息', self.refresh_all_info)
        more.setMenu(menu)
        toolbar.addWidget(more)
        layout.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_widget = QWidget()
        self.cards_layout = FlowLayout(self.cards_widget)
        self.scroll.setWidget(self.cards_widget)
        layout.addWidget(self.scroll, 1)
        self.empty = QLabel('尚未发现学生端\n\n请确认学生机与教师机处于同一网络，并允许 UDP 组播。')
        self.empty.setObjectName('emptyState')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cards_layout.addWidget(self.empty, 0, 0)
        return page

    def stat_card(self, label, value, hint):
        card = QFrame()
        card.setObjectName('statCard')
        box = QVBoxLayout(card)
        name = QLabel(label)
        name.setObjectName('muted')
        number = QLabel(value)
        number.setObjectName('statValue')
        note = QLabel(hint)
        note.setObjectName('muted')
        box.addWidget(name)
        box.addWidget(number)
        box.addWidget(note)
        card.value_label = number
        return card

    def create_management(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter()
        self.student_table = QTableWidget(0, 5)
        self.student_table.setHorizontalHeaderLabels(('计算机', 'IP 地址', '登录用户', '操作系统', '内存'))
        self.student_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.student_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.student_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.student_table.verticalHeader().setVisible(False)
        self.student_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.student_table.itemSelectionChanged.connect(self.select_table_student)
        splitter.addWidget(self.student_table)

        side = QWidget()
        side.setMinimumWidth(330)
        box = QVBoxLayout(side)
        box.setContentsMargins(12, 0, 0, 0)
        self.selected_label = QLabel('选择一名学生')
        self.selected_label.setObjectName('sectionTitle')
        box.addWidget(self.selected_label)
        self.device_tabs = QTabWidget()
        self.info_text = QPlainTextEdit()
        self.info_text.setReadOnly(True)
        self.device_tabs.addTab(self.info_text, '设备信息')
        self.process_table = self.id_name_table(('PID', '进程名称'))
        self.device_tabs.addTab(self.process_table, '进程')
        self.window_table = self.id_name_table(('句柄', '窗口标题'))
        self.device_tabs.addTab(self.window_table, '窗口')
        box.addWidget(self.device_tabs, 1)

        controls = QGridLayout()
        actions = (
            ('刷新信息', lambda: self.selected(core.request_info)),
            ('请求预览', lambda: self.selected(core.request_preview)),
            ('连续观看', lambda: self.selected(self.start_view)),
            ('远程控制', lambda: self.selected(self.start_control)),
            ('发送消息', lambda: self.selected(self.chat_dialog)),
            ('黑屏安静', lambda: self.selected(self.blackscreen_dialog)),
            ('解除黑屏', lambda: self.selected(core.send_unlock)),
            ('远程运行', lambda: self.selected(self.run_dialog)),
            ('打开网页', lambda: self.selected(self.url_dialog)),
            ('结束进程', self.kill_selected_process),
            ('关闭窗口', self.close_selected_window),
            ('关机 / 重启', lambda: self.selected(self.power_dialog)),
        )
        for index, (text, callback) in enumerate(actions):
            button = QPushButton(text)
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
        layout.setContentsMargins(0, 0, 0, 0)
        self.message_students = QListWidget()
        self.message_students.setMaximumWidth(260)
        self.message_students.itemClicked.connect(lambda item: self.select_student(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.message_students)
        right = QVBoxLayout()
        self.chat_target = QLabel('选择收件学生')
        self.chat_target.setObjectName('sectionTitle')
        right.addWidget(self.chat_target)
        self.chat_input = QPlainTextEdit()
        self.chat_input.setPlaceholderText('输入要发送到学生端的消息…')
        right.addWidget(self.chat_input, 1)
        send = QPushButton('发送消息')
        send.setObjectName('primaryButton')
        send.clicked.connect(self.send_current_message)
        right.addWidget(send, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(right, 1)
        return page

    def create_logs(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        tools.addWidget(QLabel(f'日志文件：{core.LOG_PATH}'))
        tools.addStretch()
        self.debug_toggle = QCheckBox('记录 DEBUG 协议详情')
        self.debug_toggle.toggled.connect(lambda enabled: core.set_file_log_level(logging.DEBUG if enabled else logging.INFO))
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

    def change_page(self, index):
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
        titles = (
            ('课堂总览', '实时掌握课堂状态与学生屏幕'),
            ('学生管理', '设备信息、应用进程与远程操作'),
            ('消息中心', '与课堂中的学生保持沟通'),
            ('运行日志', '协议事件、错误与连接诊断'),
        )
        self.page_title.setText(titles[index][0])
        self.page_subtitle.setText(titles[index][1])

    def refresh_students(self):
        known = set(self.cards)
        current = set(core.students)
        for ip in known - current:
            self.cards_layout.removeWidget(self.cards[ip])
            self.cards[ip].deleteLater()
            del self.cards[ip]
        for ip in sorted(current):
            if ip not in self.cards:
                self.cards[ip] = StudentCard(ip, self.select_student, self.card_action)
            self.cards[ip].update_student(core.students[ip])
        if self.current_ip not in current:
            self.current_ip = next(iter(sorted(current)), None)
        self.online_stat.value_label.setText(str(len(current)))
        self.view_stat.value_label.setText(str(len(core.remote_views)))
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
        width = max(320, self.scroll.viewport().width())
        columns = max(1, min(4, width // 330))
        for index, card in enumerate(visible):
            self.cards_layout.addWidget(card, index // columns, index % columns,
                                        Qt.AlignmentFlag.AlignTop)
        for column in range(columns):
            self.cards_layout.setColumnStretch(column, 1)
        self.cards_layout.setRowStretch((len(visible) + columns - 1) // columns, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'cards_layout'):
            self.arrange_cards()

    def refresh_student_table(self):
        selected = self.current_ip
        students = sorted(core.students.items())
        self.student_table.setRowCount(len(students))
        self.message_students.clear()
        for row, (ip, student) in enumerate(students):
            info = student.get('info', {})
            values = (info.get('name', '未命名设备'), ip, info.get('user', '—'),
                      info.get('os', '—'), info.get('mem', '—'))
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, ip)
                self.student_table.setItem(row, column, item)
                if ip == selected:
                    item.setSelected(True)
            entry = QListWidgetItem(f"{info.get('name') or ip}\n{ip}")
            entry.setData(Qt.ItemDataRole.UserRole, ip)
            self.message_students.addItem(entry)
        self.update_selected_details()

    def select_table_student(self):
        row = self.student_table.currentRow()
        item = self.student_table.item(row, 1)
        if item:
            self.select_student(item.text(), refresh=False)

    def select_student(self, ip, refresh=True):
        if ip not in core.students:
            return
        self.current_ip = ip
        self.chat_target.setText(f'发送至 {ip}')
        if refresh:
            self.refresh_student_table()
        else:
            self.update_selected_details()

    def update_selected_details(self):
        student = core.students.get(self.current_ip, {})
        info = student.get('info', {})
        self.selected_label.setText(info.get('name') or self.current_ip or '选择一名学生')
        labels = (
            ('计算机名称', 'name'), ('IP 地址', None), ('登录用户', 'user'),
            ('MAC 地址', 'mac'), ('学生 ID', 'stu_id'), ('操作系统', 'os'),
            ('系统版本', 'osver'), ('CPU 厂商', 'cpu_vendor'),
            ('CPU 型号', 'cpu_model'), ('内存', 'mem'),
        )
        self.info_text.setPlainText('\n'.join(
            f'{label}：{self.current_ip if key is None else info.get(key, "待上报")}'
            for label, key in labels
        ) if self.current_ip else '请先从左侧选择学生。')
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
            QMessageBox.information(self, '尚未选择学生', '请先选择一名在线学生。')
            return
        self.run_action(callback, self.current_ip)

    def run_action(self, callback, *args):
        try:
            callback(*args)
        except Exception as error:
            core.logger.exception('GUI 操作失败')
            QMessageBox.critical(self, '操作失败', str(error))

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
        self.last_previews[ip] = image
        if ip in self.cards:
            self.cards[ip].set_preview(image)

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
            QMessageBox.information(self, '尚未选择学生', '请先选择收件学生。')
            return
        self.run_action(core.send_chat, self.current_ip, text)
        self.chat_input.clear()

    def blackscreen_dialog(self, ip):
        target = ip or self.current_ip or '全班在线学生'
        dialog = QDialog(self)
        dialog.setWindowTitle(f'黑屏安静 · {target}')
        dialog.setMinimumWidth(430)
        layout = QVBoxLayout(dialog)
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
            self.run_action(core.send_blackscreen, student_ip, lock.isChecked(), timeout.value(), text.text() or None)

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
        row = table.currentRow()
        item = table.item(row, 0)
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
        dialog = QDialog(self)
        dialog.setWindowTitle(f'电源操作 · {ip}')
        layout = QVBoxLayout(dialog)
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


def load_styles(app):
    app.setStyleSheet('''
        * { font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; }
        QMainWindow, QWidget { background: #f4f6fa; color: #172033; }
        QFrame#sidebar { background: #111a2e; }
        QFrame#sidebar QLabel { background: transparent; }
        QLabel#brand { color: #ffffff; font-size: 20px; font-weight: 800; letter-spacing: 2px; }
        QFrame#sidebar QLabel#muted { color: #8c99b2; }
        QPushButton#navButton { background: transparent; color: #aebbd0; border: 0; border-radius: 9px; padding: 13px 16px; text-align: left; font-weight: 600; }
        QPushButton#navButton:hover { background: #1b2942; color: white; }
        QPushButton#navButton:checked { background: #315efb; color: white; }
        QLabel#pageTitle { font-size: 27px; font-weight: 750; color: #111a2e; }
        QLabel#sectionTitle { font-size: 17px; font-weight: 700; }
        QLabel#muted { color: #778298; }
        QLabel#connection { background: #e3f7ee; color: #16774b; border-radius: 14px; padding: 7px 13px; font-weight: 600; }
        QLabel#onlineDot { color: #24b47e; }
        QLabel#warning { color: #b85c13; background: #fff4df; padding: 10px; border-radius: 6px; }
        QFrame#statCard, QFrame#studentCard { background: white; border: 1px solid #e5e9f1; border-radius: 13px; }
        QFrame#statCard { padding: 8px; }
        QLabel#statValue { font-size: 28px; font-weight: 750; color: #1e3160; }
        QLabel#cardTitle { font-size: 15px; font-weight: 700; }
        QLabel#preview { background: #e9edf4; color: #8c98aa; border-radius: 8px; }
        QLabel#emptyState { color: #8995a8; font-size: 15px; padding: 90px; }
        QPushButton { background: #ffffff; border: 1px solid #dfe4ed; border-radius: 7px; padding: 8px 13px; }
        QPushButton:hover { background: #eef2ff; border-color: #aebcff; }
        QPushButton:pressed { background: #dfe6ff; }
        QPushButton#primaryButton { background: #315efb; color: white; border: 1px solid #315efb; font-weight: 600; }
        QPushButton#primaryButton:hover { background: #244bd6; }
        QPushButton#dangerButton { background: #d94b52; color: white; border-color: #d94b52; }
        QLineEdit, QPlainTextEdit, QListWidget, QTableWidget, QComboBox, QSpinBox { background: white; border: 1px solid #dfe4ed; border-radius: 7px; padding: 6px; selection-background-color: #315efb; }
        QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #6685f5; }
        QTableWidget { gridline-color: #edf0f5; }
        QHeaderView::section { background: #f8f9fc; color: #69758b; border: 0; border-bottom: 1px solid #e4e8f0; padding: 9px; font-weight: 600; }
        QTabWidget::pane { border: 1px solid #e0e5ee; background: white; border-radius: 7px; }
        QTabBar::tab { padding: 9px 15px; color: #657188; }
        QTabBar::tab:selected { color: #315efb; font-weight: 700; }
        QPlainTextEdit#logView { background: #111827; color: #c8d3e7; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px; }
        QScrollArea { background: transparent; }
        QScrollBar:vertical { background: transparent; width: 9px; }
        QScrollBar::handle:vertical { background: #c8cfdb; border-radius: 4px; min-height: 30px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QToolTip { background: #172033; color: white; border: 0; padding: 5px; }
        QDialog { background: #f7f8fb; }
    ''')


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('JiYu Studio')
    app.setStyle('Fusion')
    load_styles(app)
    window = MainWindow()
    window.show()
    core.start_background_threads()
    exit_code = app.exec()
    if not window.shutting_down:
        core.shutdown()
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
