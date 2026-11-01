import copy
import csv
import ipaddress
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone

from app_config import config_path


SCHEMA_VERSION = 1


class ClassroomStoreError(Exception):
    """班级数据操作失败。"""


class StorageError(ClassroomStoreError):
    """存储文件不可读、不可写或内容无效。"""


class NotFoundError(ClassroomStoreError):
    """指定的数据不存在。"""


class DuplicateError(ClassroomStoreError):
    """名称或学生键已存在。"""


class ValidationError(ClassroomStoreError, ValueError):
    """输入或数据约束校验失败。"""


class _PathLock:
    locks = {}
    guard = threading.Lock()

    def __new__(cls, path):
        with cls.guard:
            return cls.locks.setdefault(path, threading.RLock())


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f'{label} 必须是非空字符串')
    return value.strip()


def _optional_text(value, label):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValidationError(f'{label} 必须是字符串')
    return value.strip()


def _ip(value):
    value = _text(value, 'IP')
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise ValidationError(f'IP 格式无效：{value!r}') from error
    return address.compressed


def _student_key(value):
    value = _text(value, 'student_key')
    if any(character.isspace() for character in value) or '\x00' in value:
        raise ValidationError('student_key 不能包含空白字符')
    return value


def _new_document():
    return {'schema_version': SCHEMA_VERSION, 'classes': {}, 'active_class': None}


def _new_class(name):
    return {'name': name, 'students': {}, 'groups': {}, 'attendance': {}}


def _active_class(document):
    active_class = document.get('active_class')
    if active_class is None:
        return None
    if (not isinstance(active_class, str) or not active_class.strip()
            or active_class not in document['classes']):
        raise StorageError('班级数据 active_class 必须引用已有班级或为 null')
    return active_class


class ClassroomStore:
    """线程安全的班级、分组和签到 JSON 数据层。"""

    def __init__(self, path=None):
        self.path = os.path.abspath(os.fspath(
            path or os.path.join(os.path.dirname(config_path()), 'classrooms.json')))
        self._lock = _PathLock(self.path)

    def _load(self):
        try:
            with open(self.path, encoding='utf-8') as source:
                document = json.load(source)
        except FileNotFoundError:
            return _new_document()
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise StorageError(f'无法读取班级数据 {self.path}：{error}') from error
        if not isinstance(document, dict):
            raise StorageError('班级数据根节点必须是 JSON 对象')
        if document.get('schema_version') != SCHEMA_VERSION:
            raise StorageError('班级数据 schema_version 无效或不受支持')
        if not isinstance(document.get('classes'), dict):
            raise StorageError('班级数据 classes 必须是 JSON 对象')
        for name, classroom in document['classes'].items():
            self._validate_class(name, classroom)
        _active_class(document)
        return document

    def _validate_class(self, name, classroom):
        _text(name, '班级名称')
        if not isinstance(classroom, dict) or classroom.get('name') != name:
            raise StorageError(f'班级 {name!r} 的名称或结构无效')
        if (not isinstance(classroom.get('students'), dict)
                or not isinstance(classroom.get('groups'), dict)
                or not isinstance(classroom.get('attendance'), dict)):
            raise StorageError(f'班级 {name!r} 缺少有效的学生、分组或签到数据')
        for key, student in classroom['students'].items():
            if not isinstance(student, dict):
                raise StorageError(f'学生 {key!r} 的结构无效')
            if (set(student) != {'student_key', 'ip', 'computer_name', 'user_name'}
                    or student.get('student_key') != key):
                raise StorageError(f'学生 {key!r} 的字段无效')
            _student_key(key)
            _ip(student['ip'])
            _optional_text(student['computer_name'], 'computer_name')
            _optional_text(student['user_name'], 'user_name')
        for group_name, group in classroom['groups'].items():
            self._validate_group(group_name, group, classroom['students'])
        for key, record in classroom['attendance'].items():
            _student_key(key)
            if not isinstance(record, dict) or set(record) != {
                    'check_in_count', 'check_out_count', 'last_check_in',
                    'last_check_out', 'online'}:
                raise StorageError(f'签到记录 {key!r} 的字段无效')
            for field in ('check_in_count', 'check_out_count'):
                if type(record[field]) is not int or record[field] < 0:
                    raise StorageError(f'签到记录 {key!r} 的 {field} 无效')
            if type(record['online']) is not bool:
                raise StorageError(f'签到记录 {key!r} 的 online 无效')
            for field in ('last_check_in', 'last_check_out'):
                value = record[field]
                if value is not None:
                    try:
                        datetime.fromisoformat(value)
                    except (TypeError, ValueError) as error:
                        raise StorageError(f'签到记录 {key!r} 的 {field} 无效') from error

    def _validate_group(self, name, group, students):
        _text(name, '分组名称')
        if (not isinstance(group, dict)
                or set(group) != {'name', 'members', 'leader'}
                or group.get('name') != name
                or not isinstance(group.get('members'), list)):
            raise StorageError(f'分组 {name!r} 的结构无效')
        if len(set(group['members'])) != len(group['members']):
            raise StorageError(f'分组 {name!r} 包含重复成员')
        for key in group['members']:
            if key not in students:
                raise StorageError(f'分组 {name!r} 引用了不存在的学生 {key!r}')
        leader = group['leader']
        if leader is not None and leader not in group['members']:
            raise StorageError(f'分组 {name!r} 的 leader 必须是组成员')

    def _save(self, document):
        directory = os.path.dirname(self.path)
        basename = os.path.basename(self.path)
        descriptor = None
        temporary_path = None
        try:
            os.makedirs(directory, exist_ok=True)
            descriptor, temporary_path = tempfile.mkstemp(
                prefix=f'.{basename}.', suffix='.tmp', dir=directory)
            with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as target:
                descriptor = None
                json.dump(document, target, ensure_ascii=False, indent=2)
                target.write('\n')
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        except (OSError, TypeError, ValueError) as error:
            raise StorageError(f'无法保存班级数据 {self.path}：{error}') from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_path is not None:
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass

    def _reload(self):
        with self._lock:
            return copy.deepcopy(self._load())

    def _mutate(self, callback):
        with self._lock:
            document = self._load()
            result = callback(document)
            self._save(document)
            return copy.deepcopy(result)

    def _class(self, document, class_name):
        class_name = _text(class_name, '班级名称')
        try:
            return class_name, document['classes'][class_name]
        except KeyError as error:
            raise NotFoundError(f'班级不存在：{class_name!r}') from error

    def _student(self, classroom, student_key):
        student_key = _student_key(student_key)
        try:
            return student_key, classroom['students'][student_key]
        except KeyError as error:
            raise NotFoundError(f'学生不存在：{student_key!r}') from error

    def _student_for_ip(self, classroom, value):
        value = _ip(value)
        matches = [item for item in classroom['students'].items()
                   if item[1]['ip'] == value]
        if not matches:
            return None
        if len(matches) > 1:
            raise ValidationError(f'班级内 IP 重复，无法唯一匹配学生：{value}')
        return matches[0]

    def _group(self, classroom, group_name):
        group_name = _text(group_name, '分组名称')
        try:
            return group_name, classroom['groups'][group_name]
        except KeyError as error:
            raise NotFoundError(f'分组不存在：{group_name!r}') from error

    def _unique_name(self, mapping, name, label, current=None):
        name = _text(name, label)
        if name != current and name in mapping:
            raise DuplicateError(f'{label}已存在：{name!r}')
        return name

    def snapshot(self):
        """返回完整数据的独立副本，跨实例调用时重新读取文件。"""
        return self._reload()

    def list_classes(self):
        return list(self._load()['classes'])

    def get_class(self, class_name):
        with self._lock:
            _, classroom = self._class(self._load(), class_name)
            return copy.deepcopy(classroom)

    def get_active_class(self):
        with self._lock:
            return _active_class(self._load())

    def set_active_class(self, class_name):
        if class_name is not None:
            class_name = _text(class_name, '班级名称')

        def update(document):
            if class_name is not None:
                self._class(document, class_name)
            document['active_class'] = class_name
            return class_name

        return self._mutate(update)

    def create_class(self, name):
        name = _text(name, '班级名称')

        def create(document):
            self._unique_name(document['classes'], name, '班级名称')
            document['classes'][name] = _new_class(name)
            return document['classes'][name]

        return self._mutate(create)

    def rename_class(self, old_name, new_name):
        old_name = _text(old_name, '班级名称')
        new_name = _text(new_name, '班级名称')

        def rename(document):
            _, classroom = self._class(document, old_name)
            self._unique_name(document['classes'], new_name, '班级名称', old_name)
            if new_name != old_name:
                del document['classes'][old_name]
                classroom['name'] = new_name
                document['classes'][new_name] = classroom
            return classroom

        return self._mutate(rename)

    def delete_class(self, class_name):
        class_name = _text(class_name, '班级名称')

        def delete(document):
            self._class(document, class_name)
            del document['classes'][class_name]
            if document.get('active_class') == class_name:
                document['active_class'] = None

        self._mutate(delete)

    def add_student(self, class_name, ip, computer_name='', user_name='',
                    student_key=None):
        student = {
            'student_key': _student_key(student_key) if student_key is not None
            else uuid.uuid4().hex,
            'ip': _ip(ip),
            'computer_name': _optional_text(computer_name, 'computer_name'),
            'user_name': _optional_text(user_name, 'user_name'),
        }

        def add(document):
            _, classroom = self._class(document, class_name)
            if student['student_key'] in classroom['students']:
                raise DuplicateError(f"学生已存在：{student['student_key']!r}")
            if self._student_for_ip(classroom, student['ip']) is not None:
                raise DuplicateError(f"班级内 IP 已存在：{student['ip']}")
            classroom['students'][student['student_key']] = student
            return student

        return self._mutate(add)

    def update_student(self, class_name, student_key, ip=None,
                       computer_name=None, user_name=None):
        def update(document):
            _, classroom = self._class(document, class_name)
            _, student = self._student(classroom, student_key)
            if ip is not None:
                student['ip'] = _ip(ip)
                match = self._student_for_ip(classroom, student['ip'])
                if match is not None and match[0] != student_key:
                    raise DuplicateError(f"班级内 IP 已存在：{student['ip']}")
            if computer_name is not None:
                student['computer_name'] = _optional_text(
                    computer_name, 'computer_name')
            if user_name is not None:
                student['user_name'] = _optional_text(user_name, 'user_name')
            return student

        return self._mutate(update)

    def remove_student(self, class_name, student_key):
        student_key = _student_key(student_key)

        def remove(document):
            _, classroom = self._class(document, class_name)
            self._student(classroom, student_key)
            del classroom['students'][student_key]
            for group in classroom['groups'].values():
                if student_key in group['members']:
                    group['members'].remove(student_key)
                if group['leader'] == student_key:
                    group['leader'] = None

        self._mutate(remove)

    def create_group(self, class_name, name, members=None, leader=None):
        name = _text(name, '分组名称')
        members = [] if members is None else list(members)

        def create(document):
            _, classroom = self._class(document, class_name)
            self._unique_name(classroom['groups'], name, '分组名称')
            group = {'name': name, 'members': members, 'leader': leader}
            self._check_group(group, classroom['students'])
            classroom['groups'][name] = group
            return group

        return self._mutate(create)

    def rename_group(self, class_name, old_name, new_name):
        old_name = _text(old_name, '分组名称')
        new_name = _text(new_name, '分组名称')

        def rename(document):
            _, classroom = self._class(document, class_name)
            _, group = self._group(classroom, old_name)
            self._unique_name(classroom['groups'], new_name, '分组名称', old_name)
            if new_name != old_name:
                del classroom['groups'][old_name]
                group['name'] = new_name
                classroom['groups'][new_name] = group
            return group

        return self._mutate(rename)

    def delete_group(self, class_name, name):
        name = _text(name, '分组名称')

        def delete(document):
            _, classroom = self._class(document, class_name)
            self._group(classroom, name)
            del classroom['groups'][name]

        self._mutate(delete)

    def set_group_members(self, class_name, group_name, members):
        members = list(members)

        def update(document):
            _, classroom = self._class(document, class_name)
            _, group = self._group(classroom, group_name)
            group['members'] = members
            self._check_group(group, classroom['students'])
            return group

        return self._mutate(update)

    def add_group_member(self, class_name, group_name, student_key):
        student_key = _student_key(student_key)

        def add(document):
            _, classroom = self._class(document, class_name)
            _, group = self._group(classroom, group_name)
            self._student(classroom, student_key)
            if student_key in group['members']:
                raise DuplicateError(f'学生已在分组中：{student_key!r}')
            group['members'].append(student_key)
            return group

        return self._mutate(add)

    def remove_group_member(self, class_name, group_name, student_key):
        def remove(document):
            _, classroom = self._class(document, class_name)
            _, group = self._group(classroom, group_name)
            if student_key not in group['members']:
                raise NotFoundError(f'学生不在分组中：{student_key!r}')
            group['members'].remove(student_key)
            if group['leader'] == student_key:
                group['leader'] = None
            return group

        return self._mutate(remove)

    def set_group_leader(self, class_name, group_name, student_key):
        if student_key is not None:
            student_key = _student_key(student_key)

        def update(document):
            _, classroom = self._class(document, class_name)
            _, group = self._group(classroom, group_name)
            if student_key is not None:
                self._student(classroom, student_key)
                if student_key not in group['members']:
                    raise ValidationError('leader 必须属于该分组')
            group['leader'] = student_key
            return group

        return self._mutate(update)

    def _check_group(self, group, students):
        if len(set(group['members'])) != len(group['members']):
            raise ValidationError('分组成员不能重复')
        for key in group['members']:
            if key not in students:
                raise NotFoundError(f'学生不存在：{key!r}')
        if group['leader'] is not None and group['leader'] not in group['members']:
            raise ValidationError('leader 必须属于该分组')

    def _attendance(self, classroom, student_key):
        student_key, _ = self._student(classroom, student_key)
        return classroom['attendance'].setdefault(student_key, {
            'check_in_count': 0,
            'check_out_count': 0,
            'last_check_in': None,
            'last_check_out': None,
            'online': False,
        })

    @staticmethod
    def _timestamp(value):
        if value is None:
            return datetime.now(timezone.utc).isoformat()
        if not isinstance(value, datetime):
            raise ValidationError('签到时间必须是 datetime')
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValidationError('签到时间必须包含时区')
        return value.isoformat()

    def report_student_online(self, class_name, ip, computer_name='', user_name='',
                              when=None):
        """更新已导入学生的信息，并仅在未在线到在线时原子签到。"""
        ip = _ip(ip)
        computer_name = _optional_text(computer_name, 'computer_name')
        user_name = _optional_text(user_name, 'user_name')
        when = self._timestamp(when)

        def update(document):
            _, classroom = self._class(document, class_name)
            match = self._student_for_ip(classroom, ip)
            if match is None:
                return None
            student_key, student = match
            student['computer_name'] = computer_name
            student['user_name'] = user_name
            record = self._attendance(classroom, student_key)
            checked_in = not record['online']
            if checked_in:
                record['check_in_count'] += 1
                record['last_check_in'] = when
                record['online'] = True
            return {'student_key': student_key, 'checked_in': checked_in,
                    'student': student, 'attendance': record}

        return self._mutate(update)

    def check_in(self, class_name, student_key, when=None):
        when = self._timestamp(when)

        def update(document):
            _, classroom = self._class(document, class_name)
            record = self._attendance(classroom, student_key)
            record['check_in_count'] += 1
            record['last_check_in'] = when
            record['online'] = True
            return record

        return self._mutate(update)

    def check_out(self, class_name, student_key, when=None):
        when = self._timestamp(when)

        def update(document):
            _, classroom = self._class(document, class_name)
            record = self._attendance(classroom, student_key)
            record['check_out_count'] += 1
            record['last_check_out'] = when
            record['online'] = False
            return record

        return self._mutate(update)

    def check_out_students(self, class_name, student_keys, when=None):
        """签退本次已签到的学生；已离线记录不重复计数。"""
        student_keys = list(student_keys)
        when = self._timestamp(when)

        def update(document):
            _, classroom = self._class(document, class_name)
            result = {}
            for student_key in student_keys:
                record = self._attendance(classroom, student_key)
                if record['online']:
                    record['check_out_count'] += 1
                    record['last_check_out'] = when
                    record['online'] = False
                result[student_key] = record
            return result

        return self._mutate(update)

    def get_attendance(self, class_name, student_key=None):
        with self._lock:
            _, classroom = self._class(self._load(), class_name)
            if student_key is not None:
                student_key, _ = self._student(classroom, student_key)
                return copy.deepcopy(classroom['attendance'].get(student_key, {
                    'check_in_count': 0,
                    'check_out_count': 0,
                    'last_check_in': None,
                    'last_check_out': None,
                    'online': False,
                }))
            result = {key: copy.deepcopy(record)
                      for key, record in classroom['attendance'].items()}
            for key in classroom['students']:
                result.setdefault(key, {
                    'check_in_count': 0,
                    'check_out_count': 0,
                    'last_check_in': None,
                    'last_check_out': None,
                    'online': False,
                })
            return result

    def attendance_stats(self, class_name):
        with self._lock:
            _, classroom = self._class(self._load(), class_name)
            records = list(classroom['attendance'].values())
            return {
                'students': len(classroom['students']),
                'online': sum(record['online'] for record in records),
                'check_ins': sum(record['check_in_count'] for record in records),
                'check_outs': sum(record['check_out_count'] for record in records),
            }

    def export_attendance_csv(self, class_name, destination=None, utf8_bom=False):
        """返回签到 CSV；指定 destination 时也原子写入该文件。"""
        import io

        with self._lock:
            _, classroom = self._class(self._load(), class_name)
            students = list(classroom['students'].items())
            attendance = copy.deepcopy(classroom['attendance'])
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow([
            'student_key', 'ip', 'computer_name', 'user_name',
            'check_in_count', 'check_out_count', 'last_check_in',
            'last_check_out', 'online',
        ])
        for key, student in students:
            record = attendance.get(key, {
                'check_in_count': 0, 'check_out_count': 0,
                'last_check_in': None, 'last_check_out': None, 'online': False,
            })
            writer.writerow([
                key, student['ip'], student['computer_name'], student['user_name'],
                record['check_in_count'], record['check_out_count'],
                record['last_check_in'] or '', record['last_check_out'] or '',
                'true' if record['online'] else 'false',
            ])
        text = output.getvalue()
        if destination is not None:
            destination = os.path.abspath(os.fspath(destination))
            descriptor = None
            temporary_path = None
            try:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                descriptor, temporary_path = tempfile.mkstemp(
                    prefix=f'.{os.path.basename(destination)}.', suffix='.tmp',
                    dir=os.path.dirname(destination))
                with os.fdopen(descriptor, 'wb') as target:
                    descriptor = None
                    target.write(text.encode('utf-8-sig' if utf8_bom else 'utf-8'))
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temporary_path, destination)
                temporary_path = None
            except OSError as error:
                raise StorageError(f'无法导出签到 CSV {destination}：{error}') from error
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                if temporary_path is not None:
                    try:
                        os.remove(temporary_path)
                    except OSError:
                        pass
        return ('\ufeff' if utf8_bom else '') + text
