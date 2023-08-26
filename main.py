import ctypes
import json
import os
import shutil
import sys
import threading
import time
import traceback
from datetime import datetime
from queue import Queue
from typing import Callable, Any

import keyboard
import pyautogui
from PIL import Image
from PyQt5 import Qt as pyqt5Qt
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence, QTextCursor, QIcon
from PyQt5.QtWidgets import QApplication, QCheckBox, QDialog, QDesktopWidget, QFileDialog, QHBoxLayout, \
    QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPushButton, QSlider, QTextEdit, QVBoxLayout, QWidget
from fpdf import FPDF
from plyer import notification

if sys.platform == "win32":
    # 修复PyQt5任务栏图标
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("myappid")

# qt_material must import after PyQt5
import qt_material

CURRENT_PATH = os.path.abspath(__file__)
WORKDIR = os.getcwd()
DATA_DIR = os.path.join(WORKDIR, "data")
CONFIG_DIR = os.path.join(DATA_DIR, "config")
ICON_PATH = r".\QScreenCatcherIcon.ico"
NAME = "QScreenCatcher"
VERSION = 'v0.6'
intro = f"Welcome to use {NAME} {VERSION}\n欢迎使用{NAME} {VERSION}"
user_help = ("Press \"{main.shortcuts_keys[0]}\" to Screenshot in catching  捕捉模式中按\"{main.shortcuts_keys[0]}\"截图 \n"
             "Press \"ESC\" for 1s to stop catching  捕捉模式中长按\"ESC\"1秒停止捕捉")


def get_attr(_obj: object, attr_name: str) -> Any:
    return eval(f"{attr_name}", _obj.__dict__)


def set_attr(_obj: object, attr_name: str, value: Any) -> Any:
    return exec(f"_obj.{attr_name}=value", {"_obj": _obj, "value": value})


# wrapper class  装饰器类
class Threaded:
    daemon = True

    class Thread(threading.Thread):
        def __init__(self, target, args, kwargs, daemon=False):
            self.result = None
            self.target = target
            self.args = args
            self.kwargs = kwargs
            super().__init__(target=target, args=args, kwargs=kwargs, daemon=daemon)

        def run(self) -> None:
            self.result = self.target(*self.args, **self.kwargs)

    class ThreadedResult(object):
        def __init__(self, thread):
            self.thread: Threaded.Thread = thread
            self.thread.start()

        def __call__(self):
            return self.result

        def __repr__(self):
            return self.result

        def __int__(self):
            return int(self.result)

        def __float__(self):
            return float(self.result)

        def __str__(self):
            return str(self.result)

        def __bytes__(self):
            return bytes(self.result)

        @property
        def result(self):
            return self.thread.result

    def __init__(self, func, warp=False):  # 接受函数
        if warp:
            self.func: Callable = lambda *args, **kwargs: func(*args, **kwargs)
        else:
            self.func: Callable = func

    def __call__(self, *func_args, **func_kwargs):  # 返回函数
        thread = self.Thread(target=self.func, args=func_args, kwargs=func_kwargs, daemon=self.daemon)
        return self.ThreadedResult(thread=thread)


class PushButton(QPushButton):
    def __init__(self, text: str, parent, *args, add_space=True, tooltips=True, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.add_space = add_space
        self.setText(text)
        if tooltips:
            self.setToolTip(text)

    def setText(self, text: str) -> None:
        if self.add_space:
            text = text.replace(' ', ' ' * 2)
        super().setText(text)


class Main:
    def __init__(self):
        self.pdf_default_extension = ".pdf"
        self.pdf_filetypes = "PDF Files (*.pdf)"
        self.img_create_dir_path = DATA_DIR
        self.catching_state = False
        self.save_img_dir_path = None
        # 定义快捷键和对应的回调函数
        self.shortcuts_keys = ['v']  # settable
        self.shortcuts_callbacks = [self.screenshot]
        self.stop_shortcut = "Esc"
        # Screenshot Notification
        self.screenshot_notification_enable = True
        # img quality in pdf
        self.img_quality: int = 85  # settable
        self.img_quality_max: int = 100
        self.img_quality_min: int = 10
        self.img_quality_step: int = 1
        self.pdf_to_clipboard = True
        self.save_pdf_dir_path = None
        self.pdf_save_name = None
        self.pdf_save_path = None
        self.key_listener_thread = None
        self.stop_listener_thread = None
        self.screenshot_thread = None
        # theme
        self.app_theme: (None, str) = "dark_lightgreen"  # settable
        self.app_theme_list: list[str] = ["None"] + list(qt_material.list_themes())
        self.main_ui: ScreenCatcherGUI = ScreenCatcherGUI(self)
        self.setting_manager = SettingsManager(self.main_ui, self)
        self.main_ui.show()
        self.set_theme()

    def main_init(self):
        self.catching_state = False
        self.save_img_dir_path = None
        self.save_pdf_dir_path = None
        self.pdf_save_name = None
        self.pdf_save_path = None
        self.key_listener_thread = None
        self.stop_listener_thread = None
        self.screenshot_thread = None

    @staticmethod
    def current_time_str(year=True, month=True, day=True, hour=True, minute=True, second=True, microsecond=True) -> str:
        now = datetime.now()

        components = []
        if year:
            components.append(f"{now.year}")
        if month:
            components.append(f"{now.month:02d}")
        if day:
            components.append(f"{now.day:02d}")
        if hour:
            components.append(f"{now.hour:02d}")
        if minute:
            components.append(f"{now.minute:02d}")
        if second:
            components.append(f"{now.second:02d}")
        if microsecond:
            components.append(f"{now.microsecond}")

        formatted_time = ".".join(components)
        return formatted_time

    @property
    def user_help(self):
        return user_help.format(main=self)

    @property
    def img_extension(self):
        if self.img_quality < 95:
            return ".jpg"
        else:
            return ".png"

    def has_img_with_extension(self, extension: str, dir_path: str = None):
        if dir_path is None:
            dir_path = self.save_img_dir_path
        if not os.path.isdir(dir_path):
            raise ValueError(f"Path\"{dir_path}\" no found")
        for filename in os.listdir(dir_path):
            if filename.endswith(extension):
                return True
        return False

    def set_pdf_path(self, pdf_path=None, pdf_dir_path=None, pdf_name=None):
        if pdf_path is not None:
            # 如果用户没有输入文件后缀名，则自动添加 .pdf 后缀
            if not pdf_path.endswith(".pdf"):
                pdf_path += ".pdf"
            # 获取所选文件夹路径和文件名
            pdf_dir_path, pdf_name = os.path.split(pdf_path)
        elif pdf_dir_path is not None and pdf_name is not None:
            if not pdf_name.endswith(".pdf"):
                pdf_name += ".pdf"
            pdf_path = os.path.join(pdf_dir_path, pdf_name)
        else:
            return None
        self.pdf_save_path, self.pdf_save_name, self.save_pdf_dir_path = pdf_path, pdf_name, pdf_dir_path
        return pdf_path

    def ask_save_path_and_name(self, default_name: str, default_extension: str = None,
                               filetypes: str = None) -> (str, None):
        if default_extension is None:
            default_extension = self.pdf_default_extension
        if filetypes is None:
            filetypes = self.pdf_filetypes
        file_path, _ = QFileDialog.getSaveFileName(None, "Save File", default_name, filetypes, default_extension)

        if file_path:
            # 如果用户没有输入文件后缀名，则自动添加 .pdf 后缀
            if not file_path.endswith(".pdf"):
                file_path += ".pdf"
            # 获取所选文件夹路径和文件名
            save_dir_path, save_name = os.path.split(file_path)
            self.pdf_save_path, self.pdf_save_name, self.save_pdf_dir_path = file_path, save_name, save_dir_path
            return file_path
        else:
            return None

    def screenshot(self, save_dir_path: str = None, save_img_name: str = None):
        if save_dir_path is None:
            save_dir_path = self.save_img_dir_path
        if save_img_name is None:
            save_img_name = self.current_time_str()
        save_img_path = os.path.join(save_dir_path, save_img_name + self.img_extension)

        @Threaded
        def screenshot_and_save():
            img: Image.Image = pyautogui.screenshot()
            output(f"Screenshot \"{save_img_name + self.img_extension}\"")
            if self.screenshot_notification_enable:
                self.main_ui.show_notification(
                    message=f"Screenshot \"{save_img_name + self.img_extension}\"",
                    title="",
                )
            if self.img_extension == ".jpg":
                img.save(save_img_path, quality=self.img_quality, optimize=True)
            elif self.img_extension == ".png":
                img.save(save_img_path)
            output(f"Save screenshot to \"{save_img_path}\"")
            return img

        self.screenshot_thread = screenshot_and_save()
        return self.screenshot_thread

    def save_img_as_pdf(self, img_dir_path: str, pdf_save_path: str = None):
        if pdf_save_path is None:
            pdf_save_path: str = os.path.join(img_dir_path, f"{self.current_time_str()}{self.pdf_default_extension}")
        pdf = FPDF(unit="pt")
        pdf.set_auto_page_break(False)  # 自动分页设为False
        image_list = list(os.listdir(img_dir_path))
        for img_name in image_list:
            if not img_name.endswith(self.img_extension):
                continue
            try:
                img_path = os.path.join(img_dir_path, img_name)
                img = Image.open(img_path)
                width, height = img.size
                # noinspection PyTypeChecker
                pdf.add_page(format=(width, height))
                pdf.image(img, x=0, y=0, w=width, h=height)  # 指定宽高
            except Exception:
                output(traceback.format_exc())
        pdf.output(pdf_save_path)

    @Threaded
    def key_listener(self):
        try:
            keys = self.shortcuts_keys
            callbacks_list: list = self.shortcuts_callbacks
            callbacks_state: list = [False] * len(callbacks_list)
            output("key_listener ON")
            while True:
                if not self.catching_state:
                    output("key_listener OFF")
                    return
                index = 0
                for key, callback in zip(keys, callbacks_list):
                    if keyboard.is_pressed(key):
                        if callbacks_state[index] is False:
                            callbacks_state[index] = True
                            callback()
                    elif callbacks_state[index] is True:
                        callbacks_state[index] = False
                    index += 1
        except Exception:
            print(traceback.format_exc())

    @Threaded
    def stop_listener(self, stop_shortcut: str = None, press_time: int = 1):
        if stop_shortcut is None:
            stop_shortcut = self.stop_shortcut
        # 长按 press_time 秒后触发回调函数
        esc_pressed_time = 0
        while True:
            if not self.catching_state:
                return
            if keyboard.is_pressed(stop_shortcut):
                if esc_pressed_time == 0:
                    esc_pressed_time = time.time()
                elif time.time() - esc_pressed_time >= press_time:
                    break
            else:
                esc_pressed_time = 0
        self.catching_stop(check_stop_listener=False)

    def create_tem_img_dir(self, name: str = None, path: str = None):
        if name is None:
            name = self.current_time_str()
        if path is None:
            path = self.img_create_dir_path
        new_tem_dir_path = os.path.join(path, name)
        os.makedirs(new_tem_dir_path)
        output(f"New temporary dir of img is created at \"{new_tem_dir_path}\"")
        return new_tem_dir_path

    def select_pdf_save_path(self):
        pdf_save_path = self.ask_save_path_and_name(self.current_time_str())
        if pdf_save_path:
            self.pdf_save_path = pdf_save_path
            output(f"PDF is going to save at \"{pdf_save_path}\"")
            self.main_ui.update_path_line()
        return self.pdf_save_path

    def catching_start(self) -> bool:
        if self.catching_state:
            output('Warning: Already in catching!')
            return False
        if self.pdf_save_path is None:
            self.select_pdf_save_path()
        if self.pdf_save_path is None:
            return False
        self.save_img_dir_path = self.create_tem_img_dir()
        self.catching_state = True
        output("Catching start")
        # 启动键盘监听线程
        self.key_listener_thread: Threaded.ThreadedResult = self.key_listener(self)
        self.stop_listener_thread: Threaded.ThreadedResult = self.stop_listener(self)
        return True

    def catching_stop(self, check_key_listener=True, check_stop_listener=True, check_screenshot=True) -> bool:
        if self.catching_state is False:
            output('Warning: No current catching!')
            return False
        self.catching_state = False
        if self.key_listener_thread is not None and check_key_listener:
            self.key_listener_thread.thread.join(15)
        if self.stop_listener_thread is not None and check_stop_listener:
            self.stop_listener_thread.thread.join(15)
        if self.screenshot_thread is not None and check_screenshot:
            self.screenshot_thread.thread.join(15)
        output('Stop catching')
        if self.has_img_with_extension(self.img_extension):
            self.save_pdf()
            if self.pdf_to_clipboard:
                self.copy_file_to_clipboard()
        else:
            output(f"Saving: No img file found in \"{self.save_img_dir_path}\"")
            output("No PDF saved")
        self.main_init()
        self.main_ui.update_path_line()
        return True

    def save_pdf(self, img_dir_path: str = None, pdf_save_path: str = None):
        if img_dir_path is None:
            img_dir_path = self.save_img_dir_path
        if pdf_save_path is None:
            pdf_save_path = self.pdf_save_path
        original_pdf_save_path = os.path.join(self.save_img_dir_path, self.current_time_str() + ".pdf")
        self.save_img_as_pdf(img_dir_path=img_dir_path, pdf_save_path=original_pdf_save_path)
        output(f"PDF\"{original_pdf_save_path}\" saved")
        shutil.copy(original_pdf_save_path, pdf_save_path)
        output(f"PDF\"{pdf_save_path}\" saved")

    def copy_file_to_clipboard(self, file_path: str = None):
        if file_path is None:
            file_path = self.pdf_save_path
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"\"{file_path}\" no found")
        clipboard = QApplication.clipboard()
        url_list = [pyqt5Qt.QUrl.fromLocalFile(file_path)]
        mime_data = pyqt5Qt.QMimeData()
        mime_data.setUrls(url_list)
        clipboard.setMimeData(mime_data)
        output(f"PDF\"{file_path}\" copy to clipboard")

    def set_theme(self, theme=None):
        if theme is None:
            if self.app_theme is None or self.app_theme == "None":
                theme = None
            else:
                theme = f"{self.app_theme}.xml"
        qt_material.apply_stylesheet(app=app, theme=theme)

    def output(self, _str, print_time=True, precis_time=False) -> bool:
        if print_time:
            _time = self.current_time_str(year=precis_time, month=precis_time, day=precis_time, microsecond=precis_time)
            _str = f"[{_time}]{_str}"
        try:
            return self.main_ui.output(_str)
        except Exception:
            return False

    def exit(self):
        self.main_ui.exit()
        app.quit()

    def restart(self):
        self.exit()
        os.system(rf".\{NAME}.exe")


class KeySequenceEdit(QKeySequenceEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.line_edit_child = self.findChild(QLineEdit, "qt_keysequenceedit_lineedit")

    def keyPressEvent(self, event):
        try:
            super().keyPressEvent(event)
            # noinspection PyUnresolvedReferences
            seq_string = self.keySequence().toString(QKeySequence.NativeText)
            if seq_string:
                last_seq = seq_string.split(",")[-1].strip()
                self.setKeySequence(QKeySequence(last_seq))
                # Update the cached QLineEdit child object if it's available
                if self.line_edit_child:
                    # noinspection PyUnresolvedReferences
                    self.line_edit_child.setText(last_seq)

                # noinspection PyUnresolvedReferences
                # Emit editingFinished signal
                self.editingFinished.emit()
        except Exception:
            output(traceback.format_exc())


class KeyRecorder(QWidget):
    def __init__(self, parent, default_key=None):
        # parent = None
        super().__init__()
        self.parent = parent
        self.default_key = default_key
        # noinspection PyArgumentList
        self.keysequenceedit = KeySequenceEdit(self)
        # noinspection PyArgumentList
        button = QPushButton("Reset", self.parent, clicked=self.reset)
        layout = QHBoxLayout(self)
        layout.addWidget(self.keysequenceedit)
        layout.addWidget(button)
        if default_key is not None:
            self.keysequenceedit.setKeySequence(default_key)

    def reset(self):
        self.keysequenceedit.setKeySequence(self.default_key)

    # noinspection PyUnresolvedReferences
    def get_shortcut(self) -> str:
        sequence = self.keysequenceedit.keySequence()
        seq_string = sequence.toString(QKeySequence.NativeText)
        return seq_string


class SettingSlider(QWidget):
    def __init__(self, parent, default_value: int, _max: int, _min: int, _step: int = None, tick_interval: int = None,
                 slider_width: int = None, line_width: int = None):
        super().__init__()
        self.parent = parent
        if default_value is None:
            self.value: int = _max
        else:
            self.value: int = default_value
        self.value_max = _max
        self.value_min = _min
        self.value_step = _step
        layout = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        if slider_width is None:
            self.slider.setFixedWidth(_max - _min)
        else:
            self.slider.setFixedWidth(slider_width)
        self.slider.setTickPosition(QSlider.NoTicks)
        self.slider.setMaximum(_max)
        self.slider.setMinimum(_min)
        if _step is not None:
            self.slider.setSingleStep(_step)
        if tick_interval is not None:
            self.slider.setTickInterval(tick_interval)
        self.slider.valueChanged.connect(self.update_value_from_silder)
        self.line = QLineEdit(self)
        if line_width is None:
            self.line.setFixedWidth(len(str(_max)) * 16 + 1)
        else:
            self.line.setFixedWidth(line_width)
        self.line.editingFinished.connect(self.update_value_from_line)
        layout.addWidget(self.slider)
        layout.addWidget(self.line)
        self.update()
        self.setLayout(layout)

    def update_value_from_silder(self):
        self.value = self.slider.value()
        self.value_check()
        self.update()

    def update_value_from_line(self):
        try:
            self.value = int(self.line.text())
            self.value_check()
        except Exception as e:
            output(e)
        self.update()

    def value_check(self):
        if self.value < self.value_min:
            self.value = self.value_min
        elif self.value > self.value_max:
            self.value = self.value_max
        self.update()

    def get_value(self):
        return self.value

    def update(self) -> None:
        super().update()
        self.slider.setValue(self.value)
        self.line.setText(str(self.value))


class SettingCheckBox(QCheckBox):
    def __init__(self, text, parent=None, default_value=False):
        super().__init__(text)
        self.parent = parent
        self.setChecked(default_value)

    def get_value(self):
        return self.isChecked()


class SettingsContainer(dict):
    class SettingPair(list):
        def __init__(self, key, value, value_get_callback: Callable = None):
            super().__init__([key, value])
            self._key_index = 0
            self._value_index = 1
            self.value_get_callback = value_get_callback

        @property
        def key(self):
            return self.__getitem__(self._key_index)

        @property
        def value(self):
            return self.__getitem__(self._value_index)

        def set_value(self, _new_value):
            self.__setitem__(self._value_index, _new_value)

    def __init__(self, *args, _dict: dict = None, **kwargs):
        super().__init__(*args, **kwargs)
        if _dict is not None:
            _dict = _dict.copy()
            for note in _dict:
                _dict[note] = self.SettingPair(_dict[note][0], _dict[note][1])
            self.update(_dict)

    def add(self, note: str, key: str, value=None):
        self[note] = self.SettingPair(key=key, value=value)

    def get(self, __key: str) -> SettingPair | None:
        return super().get(__key)

    def deepcopy(self):
        _new = self.__class__(_dict=self)
        return _new


class SettingsManager:
    CONFIG_PATH = os.path.join(CONFIG_DIR, f"config.json")

    def __init__(self, parent, main_instance: Main, load_settings=True):
        self.parent: ScreenCatcherGUI = parent
        self.main_instance = main_instance

        self.settings: SettingsContainer[str, SettingsContainer.SettingPair] = SettingsContainer()
        self.settings.add(note='Screenshot Shortcut', key='shortcuts_keys[0]')
        self.settings.add(note='Screenshot Notification', key='screenshot_notification_enable')
        self.settings.add(note='img Quality', key='img_quality')
        self.settings.add(note='Theme', key='app_theme')

        if load_settings:
            self.load_settings()

    def settings_filter(self, main_instance: Main = None) -> SettingsContainer:
        if main_instance is None:
            main_instance = self.main_instance
        for note in self.settings:
            setting_pair = self.settings.get(note)
            setting_pair.set_value(get_attr(main_instance, setting_pair.key))
        print(self.settings)
        return self.settings

    def load_settings(self, defaults_settings: dict = None, settings_path: str = None, main_instance: Main = None):
        """Load settings from file. If file doesn't exist, return default settings."""
        if settings_path is None:
            settings_path = self.CONFIG_PATH
        if main_instance is None:
            main_instance = self.main_instance
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r') as file:
                    file_settings: dict = json.load(file)
                    if set(self.settings.keys()) == set(file_settings.keys()):
                        file_settings = SettingsContainer(_dict=file_settings)
                        self.settings.update(file_settings)
                    else:
                        self.register_settings(defaults_settings)
            except Exception:
                output(traceback.format_exc())
                self.register_settings()
        else:
            self.register_settings(defaults_settings)
        for note in self.settings:
            setting_pair = self.settings.get(note)
            set_attr(_obj=main_instance, attr_name=setting_pair.key, value=setting_pair.value)

    def save_settings(self, settings, config_path: str = None):
        """Save settings to file."""
        if config_path is None:
            config_path = self.CONFIG_PATH
        os.makedirs(CONFIG_DIR, exist_ok=True)  # Ensure directory exists
        try:
            with open(config_path, 'w') as file:
                json.dump(settings, file)
        except Exception:
            output(traceback.format_exc())
            self.register_settings()

    def register_settings(self, defaults_settings: SettingsContainer = None):
        if defaults_settings is None:
            defaults_settings = self.settings_filter()
        self.save_settings(defaults_settings)
        self.settings.update(defaults_settings)

    def setting_dialog(self):
        return SettingsDialog(self.parent, self, self.settings)


class SettingsDialog(QDialog):
    def __init__(self, parent, setting_manager: SettingsManager, current_settings: SettingsContainer):
        super().__init__()
        # noinspection PyTypeChecker
        self.parent: ScreenCatcherGUI = parent
        self.setting_manager = setting_manager
        self.current_settings = current_settings
        self.new_settings = current_settings.deepcopy()
        self.setWindowTitle("Screen Catcher Settings")
        layout = QVBoxLayout()

        # ScreenshotShortcut Setting
        screenshot_shortcut_layout = QHBoxLayout()
        screenshot_shortcut_layout.addWidget(QLabel("Screenshot Shortcut: "))
        self.screenshot_shortcut_keyrecorder = KeyRecorder(
            parent=self,
            default_key=self.current_settings.get("Screenshot Shortcut").value
        )
        self.new_settings.get("Screenshot Shortcut").value_get_callback = (
            self.screenshot_shortcut_keyrecorder.get_shortcut)
        screenshot_shortcut_layout.addWidget(self.screenshot_shortcut_keyrecorder)
        screenshot_shortcut_layout.addStretch()
        layout.addLayout(screenshot_shortcut_layout)

        # img Quality Setting
        img_quality_layout = QHBoxLayout()
        img_quality_layout.addWidget(QLabel("img Quality: "))
        self.img_quality_slider = SettingSlider(
            parent=self,
            default_value=self.current_settings.get("img Quality").value,
            _max=self.setting_manager.main_instance.img_quality_max,
            _min=self.setting_manager.main_instance.img_quality_min,
            _step=self.setting_manager.main_instance.img_quality_step,
            tick_interval=True,
            slider_width=128,
            line_width=64
        )
        self.new_settings.get("img Quality").value_get_callback = (
            self.img_quality_slider.get_value)
        img_quality_layout.addWidget(self.img_quality_slider)
        img_quality_layout.addStretch()
        layout.addLayout(img_quality_layout)

        # Screenshot Notification setting
        screenshot_notification_layout = QHBoxLayout()
        self.screenshot_notification_checkbox = SettingCheckBox(
            text="Screenshot Notification",
            parent=self,
            default_value=self.current_settings.get("Screenshot Notification").value
        )
        self.new_settings.get("Screenshot Notification").value_get_callback = (
            self.screenshot_notification_checkbox.get_value)
        screenshot_notification_layout.addWidget(self.screenshot_notification_checkbox)
        screenshot_notification_layout.addStretch()
        layout.addLayout(screenshot_notification_layout)

        # apply button and cancel Button
        apply_cancel_layout = QHBoxLayout()
        self.apply_button = PushButton("Apply", self)
        self.apply_button.setFixedWidth(128)
        self.apply_button.clicked.connect(self.apply_settings)
        self.cancel_button = PushButton("Cancel", self)
        self.cancel_button.setFixedWidth(128)
        self.cancel_button.clicked.connect(self.reject)
        apply_cancel_layout.addStretch()
        apply_cancel_layout.addWidget(self.apply_button)
        apply_cancel_layout.addWidget(self.cancel_button)
        layout.addLayout(apply_cancel_layout)

        self.setLayout(layout)
        self.setWindowModality(Qt.ApplicationModal)
        self.show()
        self.exec_()

    def apply_settings(self):
        for note in self.new_settings:
            setting_pair = self.new_settings.get(note)
            value_callback = setting_pair.value_get_callback
            if callable(value_callback):
                setting_pair.set_value(value_callback())
        self.setting_manager.save_settings(self.new_settings)
        self.setting_manager.load_settings()
        self.accept()  # Close the dialog


class ScreenCatcherGUI(QWidget):
    def __init__(self, parent: Main):
        super().__init__()
        self.parent = parent
        self.window_size = 64
        self.window_width = self.window_size * 16
        self.window_height = self.window_size * 9
        self.line_font_size = 10
        self.line_font = self.font()
        self.line_font.setPointSize(self.line_font_size)
        self.button_font_size = 8
        self.button_font = self.font()
        self.button_font.setPointSize(self.button_font_size)
        # init ui
        layout = QVBoxLayout()

        # Output text box
        self.output_lines = QTextEdit(self)
        self.output_lines.setReadOnly(True)
        self.output_lines.setFontPointSize(self.line_font_size)
        self.output_lines.setLineWrapMode(QTextEdit.NoWrap)
        self.output_lines.textChanged.connect(self.output_lines_auto_cursor_move)
        layout.addWidget(self.output_lines)

        # Select-Save-Path button and Path-line edit
        path_layout = QHBoxLayout()
        self.path_button = PushButton('Select Save Path', self)
        self.path_button.setFont(self.button_font)
        self.path_button.setFixedWidth(256)
        self.path_button.clicked.connect(self.select_path)
        self.path_line = QLineEdit(self)
        self.path_line.setFont(self.line_font)
        self.path_line.textChanged.connect(self.save_path_changed)
        self.path_line.editingFinished.connect(self.on_path_line_editing_finished)
        path_layout.addWidget(self.path_button)
        path_layout.addWidget(self.path_line)
        layout.addLayout(path_layout)

        # Start/Stop button
        start_stop_exit_layout = QHBoxLayout()
        self.start_stop_button = PushButton('Start', self)
        self.start_stop_button.setFont(self.button_font)
        self.start_stop_button.clicked.connect(self.toggle_start_stop_button)
        self.start_stop_button.setCheckable(True)
        self.start_stop_button.setFixedWidth(192)
        self.start_stop_button_state = self.parent.catching_state
        # Settings button
        self.settings_button = PushButton('Settings', self)
        self.settings_button.setFont(self.button_font)
        self.settings_button.setFixedWidth(128)
        self.settings_button.clicked.connect(self.open_settings)
        # Exit button
        self.exit_button = PushButton('Exit', self)
        self.exit_button.setFont(self.button_font)
        self.exit_button.setFixedWidth(128)
        self.exit_button.clicked.connect(self.exit)
        start_stop_exit_layout.addWidget(self.start_stop_button)
        start_stop_exit_layout.addStretch()
        start_stop_exit_layout.addWidget(self.settings_button)
        start_stop_exit_layout.addWidget(self.exit_button)
        layout.addLayout(start_stop_exit_layout)

        self.setLayout(layout)
        self.setWindowTitle(f'ScreenCatcher-{VERSION}')
        self.resize(self.window_width, self.window_height)
        self.icon = QIcon(ICON_PATH)
        self.setWindowIcon(self.icon)
        self.setFocus()
        self.center()

        # self.setWindowOpacity(0.96)

        # Blur background
        # from BlurWindow.blurWindow import GlobalBlur
        # from PyQt5.QtCore import Qt
        # self.setAttribute(Qt.WA_TranslucentBackground)
        # self.output_lines.setAttribute(Qt.WA_TranslucentBackground)
        # GlobalBlur(self.winId(), Acrylic=False, Dark=True, QWidget=self)
        # self.setStyleSheet("background-color: rgba(0, 0, 0, 128)")

    def set_stay_ont_the_top(self, value=True, show=False):
        if value:
            self.setWindowFlags(Qt.WindowStaysOnTopHint)  # 置顶
        else:
            self.setWindowFlags(Qt.Widget)  # 取消置顶
        if show:
            self.show()

    def center(self):
        # 得到屏幕的尺寸
        screen = QDesktopWidget().screenGeometry()
        # 获取窗口尺寸
        size = self.geometry()
        # 计算居中窗口的左上角到屏幕左侧坐标的距离
        new_left = (screen.width() - size.width()) // 2
        # 计算居中窗口的左上角到屏幕上边坐标的距离
        new_top = (screen.height() - size.height()) // 2
        # 移动窗口, 因为move方法只接受整数，所以我们类型转换一下
        self.move(new_left, new_top)

    def output_lines_auto_cursor_move(self):
        self.output_lines.moveCursor(QTextCursor.End)
        self.output_lines.moveCursor(QTextCursor.StartOfLine)

    def update_start_stop_button_state(self):
        self.start_stop_button_state = self.parent.catching_state

    def update_start_stop_button(self):
        self.update_start_stop_button_state()
        if self.start_stop_button_state is False:
            self.start_stop_button.setText("Start")
            self.start_stop_button.setChecked(self.start_stop_button_state)
        else:
            self.start_stop_button.setText('Stop And Save')
            self.start_stop_button.setChecked(self.start_stop_button_state)
        self.start_stop_button.setToolTip(self.start_stop_button.text())

    def toggle_start_stop_button(self):
        if not self.start_stop_button.isChecked():
            self.parent.catching_stop()
        else:
            self.parent.catching_start()
            if self.parent.user_help not in self.output_lines.toPlainText():
                output(self.parent.user_help, print_time=False)
        self.update_start_stop_button()

    def update_path_line(self):
        self.path_line.setText(self.parent.pdf_save_path)

    def select_path(self):
        self.parent.select_pdf_save_path()

    def save_path_changed(self):
        new_path = self.path_line.text()
        if new_path == str():
            return
        new_pdf_dir_path = os.path.split(new_path)[0]
        if os.path.exists(new_pdf_dir_path):
            self.parent.set_pdf_path(new_path)
            self.update_path_line()
        else:
            output(f"PDF Save Path\"{new_pdf_dir_path}\" no found")

    def on_path_line_editing_finished(self):
        new_path = self.path_line.text()
        new_pdf_dir_path = os.path.split(new_path)[0]
        if os.path.exists(new_pdf_dir_path):
            self.save_path_changed()
            output(f"PDF Save Path change to \"{new_path}\"")

    def save_path_edit_finished(self):
        if not self.path_line.text() == self.parent.pdf_save_path:
            output(f"Path\"{self.path_line.text()}\" no found")
            self.select_path()

    def open_settings(self):
        if self.parent.catching_state:
            QMessageBox.warning(self, "ScreenCatcher", "You cannot change settings while catching")
        else:
            try:
                self.parent.setting_manager.setting_dialog()
            except Exception:
                output(traceback.format_exc())

    @staticmethod
    def show_notification(message: str, title: str, app_name: str = NAME, timeout: int = 5,
                          app_icon: str = ICON_PATH):
        notification.notify(
            title=title,
            message=message,
            app_name=app_name,
            timeout=timeout,
            app_icon=app_icon,
        )

    def output(self, _str) -> bool:
        try:
            self.output_lines.append(_str)
        except Exception:
            return False
        return True

    def exit(self):
        if self.parent.catching_state:
            _reply = QMessageBox.question(self, "ScreenCatcher",
                                          "The catching is not finished\nAre you sure to stop and save?")
            if _reply == QMessageBox.Yes:
                if not self.parent.catching_stop():
                    return
            else:
                return
        self.close()
        app.closeAllWindows()


def output(_str, print_time=True, precis_time=False):
    output_queue.put(dict(_str=_str, print_time=print_time, precis_time=precis_time))


@Threaded
def output_manager():
    while True:
        _dict: dict = output_queue.get()
        _str = _dict.get("_str")
        print_time = _dict.get("print_time")
        precis_time = _dict.get("precis_time")
        print(_str)
        try:
            main.output(_str, print_time=print_time, precis_time=precis_time)
        except Exception:
            print(traceback.format_exc())


if __name__ == '__main__':
    try:
        output_queue = Queue()
        app = QApplication(sys.argv)
        main = Main()
        output_manager()
        main.main_ui.set_stay_ont_the_top(value=True, show=True)
        output(intro, print_time=False)
        main.main_ui.set_stay_ont_the_top(value=False, show=True)
        return_code = app.exec_()
        if return_code != 0:
            print(traceback.format_exc())
        sys.exit(return_code)
    except Exception:
        output(traceback.format_exc())
