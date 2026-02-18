from __future__ import annotations

import os
import sys
import sqlite3
import traceback
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QPushButton,
    QFrame,
    QSlider,
    QStyle,
    QMessageBox,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtGui import QFont

import vlc


# =========================
# 防闪退：写日志（exe里特别重要）
# =========================
def app_root_dir() -> Path:
    """
    打包后：返回 exe 所在目录
    开发时：返回本文件所在目录的上一级（保持你原来的相对结构习惯）
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def log_file_path() -> Path:
    # 日志放在 exe 同级更直观
    return app_root_dir() / "student_app_error.log"


def install_global_exception_hook():
    def _hook(exctype, value, tb):
        try:
            with open(log_file_path(), "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 80 + "\n")
                f.write("Unhandled exception:\n")
                f.write("".join(traceback.format_exception(exctype, value, tb)))
        except Exception:
            pass
        # 同时弹窗提示（不改变 UI，只是错误提示）
        try:
            QMessageBox.critical(None, "程序错误", f"发生未处理异常：{value}\n\n已写入日志：{log_file_path()}")
        except Exception:
            pass

    sys.excepthook = _hook


# =========================
# VLC 初始化（尽量稳）
# =========================
def ensure_vlc_path():
    """
    确保能找到 VLC 的 DLL（Windows 常见问题）。
    你已安装：C:\\Program Files\\VideoLAN\\VLC
    """
    if sys.platform.startswith("win"):
        vlc_dir = r"C:\Program Files\VideoLAN\VLC"
        if os.path.isdir(vlc_dir):
            try:
                os.add_dll_directory(vlc_dir)
            except Exception:
                pass
            if vlc_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = vlc_dir + os.pathsep + os.environ.get("PATH", "")


def find_courses_root() -> Path | None:
    """
    打包后优先从 exe 同级寻找：
      1) ./data/courses
      2) ./courses
    开发时兼容：
      3) (this_file/../..)/data/courses  （你原来的结构）
    """
    root = app_root_dir()

    candidates = [
        root / "data" / "courses",
        root / "courses",
    ]

    # 开发模式兜底（保留你原来写法）
    dev_base = Path(__file__).resolve().parents[1]
    candidates.append(dev_base / "data" / "courses")

    for p in candidates:
        if p.exists() and p.is_dir():
            return p
    return None


def load_questions(course_dir: Path):
    db_path = course_dir / "questions.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT question, segment_file FROM questions")
    rows = cur.fetchall()
    conn.close()
    return rows


class StudentApp(QWidget):

    def __init__(self, course_dir: Path):
        super().__init__()

        self.course_dir = course_dir
        self.questions = load_questions(course_dir)

        # VLC
        ensure_vlc_path()
        self.vlc_instance = vlc.Instance("--no-video-title-show", "--quiet")
        self.vlc_player = self.vlc_instance.media_player_new()

        # 状态
        self._current_video: Path | None = None
        self._dragging_slider = False

        self.init_ui()
        self.init_vlc_output()
        self.init_vlc_timers()

    # ================= UI（外观不动） =================
    def init_ui(self):
        self.setWindowTitle("教学内容索引引擎 - 学生端")
        self.resize(1200, 700)
        
        # 设置整体窗口样式
        self.setStyleSheet("""
            QWidget {
                background-color: #f5f7fa;
                font-family: "Microsoft YaHei", "微软雅黑", Arial, sans-serif;
            }
        """)

        main_layout = QHBoxLayout()
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # ================= 左侧区域 =================
        left_widget = QFrame()
        left_widget.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 12px;
                padding: 20px;
            }
        """)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(15)

        # 标题标签
        self.chat_label = QLabel("💬 请输入您的问题")
        self.chat_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self.chat_label.setStyleSheet("""
            QLabel {
                color: #2c3e50;
                padding: 8px;
                background-color: transparent;
            }
        """)

        # 输入框
        self.input_box = QTextEdit()
        self.input_box.setFixedHeight(120)
        self.input_box.setPlaceholderText("在这里输入关键词搜索相关问题...")
        self.input_box.setStyleSheet("""
            QTextEdit {
                border: 2px solid #e1e8ed;
                border-radius: 8px;
                padding: 12px;
                font-size: 13px;
                background-color: #ffffff;
                color: #2c3e50;
            }
            QTextEdit:focus {
                border: 2px solid #3498db;
                background-color: #ffffff;
            }
        """)

        # 发送按钮
        self.send_button = QPushButton("🔍 搜索问题")
        self.send_button.setFixedHeight(45)
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3498db, stop:1 #2980b9);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #5dade2, stop:1 #3498db);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2980b9, stop:1 #21618c);
            }
        """)

        # 系统反馈
        self.system_feedback = QLabel("👋 欢迎使用！输入关键词开始搜索")
        self.system_feedback.setWordWrap(True)
        self.system_feedback.setStyleSheet("""
            QLabel {
                color: #7f8c8d;
                font-size: 12px;
                padding: 12px;
                background-color: #ecf0f1;
                border-radius: 6px;
                border-left: 4px solid #3498db;
            }
        """)

        left_layout.addWidget(self.chat_label)
        left_layout.addWidget(self.input_box)
        left_layout.addWidget(self.send_button)
        left_layout.addWidget(self.system_feedback)
        left_layout.addStretch()

        # ================= 右侧区域 =================
        right_widget = QFrame()
        right_widget.setStyleSheet("""
            QFrame {
                background-color: transparent;
            }
        """)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setSpacing(15)

        # 问题列表标签
        list_label = QLabel("📋 搜索结果（双击播放相关视频）")
        list_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        list_label.setStyleSheet("""
            QLabel {
                color: #2c3e50;
                padding: 8px 12px;
                background-color: white;
                border-radius: 8px;
            }
        """)

        # 问题列表
        self.result_list = QListWidget()
        self.result_list.setFixedHeight(200)
        self.result_list.setStyleSheet("""
            QListWidget {
                border: 2px solid #e1e8ed;
                border-radius: 8px;
                background-color: white;
                padding: 8px;
                font-size: 13px;
                outline: none;
            }
            QListWidget::item {
                padding: 12px;
                border-radius: 6px;
                margin: 3px 0px;
                color: #2c3e50;
            }
            QListWidget::item:hover {
                background-color: #ebf5fb;
                color: #2980b9;
            }
            QListWidget::item:selected {
                background-color: #3498db;
                color: white;
                border: none;
            }
        """)

        # 视频区域标签
        video_label = QLabel("🎥 视频播放区")
        video_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        video_label.setStyleSheet("""
            QLabel {
                color: #2c3e50;
                padding: 8px 12px;
                background-color: white;
                border-radius: 8px;
            }
        """)

        # 视频区域容器
        video_frame = QFrame()
        video_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border: 2px solid #34495e;
                border-radius: 12px;
            }
        """)
        video_layout = QVBoxLayout(video_frame)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(0)

        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("""
            QVideoWidget {
                background-color: #000000;
            }
        """)
        video_layout.addWidget(self.video_widget)

        # ================= 播放控制条 =================
        controls_frame = QFrame()
        controls_frame.setStyleSheet("""
            QFrame {
                background-color: #2c3e50;
                border-bottom-left-radius: 10px;
                border-bottom-right-radius: 10px;
                padding: 8px 12px;
            }
        """)
        controls_layout = QVBoxLayout(controls_frame)
        controls_layout.setSpacing(8)
        controls_layout.setContentsMargins(8, 8, 8, 8)

        # 进度条
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self.set_position)
        self.position_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: none;
                height: 6px;
                background: #34495e;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #3498db;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: white;
                border: 2px solid #3498db;
                width: 16px;
                height: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #3498db;
            }
        """)

        # 控制按钮行
        button_layout = QHBoxLayout()
        
        # 播放/暂停按钮
        self.play_button = QPushButton()
        self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_button.clicked.connect(self.play_pause)
        self.play_button.setFixedSize(36, 36)
        self.play_button.setCursor(Qt.PointingHandCursor)
        self.play_button.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                border: none;
                border-radius: 18px;
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #5dade2;
            }
            QPushButton:pressed {
                background-color: #2980b9;
            }
        """)

        # 停止按钮
        self.stop_button = QPushButton()
        self.stop_button.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.stop_button.clicked.connect(self.stop_video)
        self.stop_button.setFixedSize(32, 32)
        self.stop_button.setCursor(Qt.PointingHandCursor)
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #34495e;
                border: none;
                border-radius: 16px;
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #4a5f7f;
            }
            QPushButton:pressed {
                background-color: #2c3e50;
            }
        """)

        # 时间标签
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setStyleSheet("""
            QLabel {
                color: #ecf0f1;
                font-size: 12px;
                padding: 0px 10px;
                background-color: transparent;
            }
        """)

        # 音量图标
        volume_icon = QLabel("🔊")
        volume_icon.setStyleSheet("""
            QLabel {
                font-size: 16px;
                padding: 0px 5px;
                background-color: transparent;
            }
        """)

        # 音量滑块
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self.set_volume)
        self.volume_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: none;
                height: 4px;
                background: #34495e;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #27ae60;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: white;
                border: 2px solid #27ae60;
                width: 12px;
                height: 12px;
                margin: -5px 0;
                border-radius: 6px;
            }
        """)

        button_layout.addWidget(self.play_button)
        button_layout.addWidget(self.stop_button)
        button_layout.addWidget(self.time_label)
        button_layout.addStretch()
        button_layout.addWidget(volume_icon)
        button_layout.addWidget(self.volume_slider)

        controls_layout.addWidget(self.position_slider)
        controls_layout.addLayout(button_layout)

        video_layout.addWidget(controls_frame)

        right_layout.addWidget(list_label)
        right_layout.addWidget(self.result_list)
        right_layout.addWidget(video_label)
        right_layout.addWidget(video_frame, 1)

        main_layout.addWidget(left_widget, 2)
        main_layout.addWidget(right_widget, 5)

        self.setLayout(main_layout)

        # 初始加载
        self.refresh_list("")
        self.set_volume(70)

        # 事件绑定
        self.send_button.clicked.connect(self.on_send_clicked)
        self.result_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.video_widget.mouseDoubleClickEvent = self.toggle_fullscreen

        # 实时筛选（不动 UI）
        self.input_box.textChanged.connect(self.on_text_changed)

    # ================= VLC 绑定与定时同步 =================
    def init_vlc_output(self):
        wid = int(self.video_widget.winId())
        if sys.platform.startswith("win"):
            self.vlc_player.set_hwnd(wid)
        elif sys.platform.startswith("linux"):
            self.vlc_player.set_xwindow(wid)
        elif sys.platform == "darwin":
            self.vlc_player.set_nsobject(wid)

    def init_vlc_timers(self):
        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(200)
        self.ui_timer.timeout.connect(self.sync_ui_from_vlc)
        self.ui_timer.start()

    def sync_ui_from_vlc(self):
        if self._dragging_slider:
            return

        try:
            length = self.vlc_player.get_length()
            time_ms = self.vlc_player.get_time()

            if not length or length <= 0:
                self.position_slider.setRange(0, 0)
                self.time_label.setText("00:00 / 00:00")
                return

            if time_ms is None or time_ms < 0:
                time_ms = 0

            self.position_slider.setRange(0, length)
            self.position_slider.setValue(time_ms)

            current = self.format_time(time_ms)
            total = self.format_time(length)
            self.time_label.setText(f"{current} / {total}")

            if self.vlc_player.is_playing():
                self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
            else:
                self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        except Exception:
            pass

    # ================= 搜索 =================
    def refresh_list(self, keyword: str):
        self.result_list.clear()
        keyword = keyword.strip()

        count = 0
        for question, segment in self.questions:
            if keyword == "" or keyword in question:
                item = QListWidgetItem(question)
                item.setData(Qt.UserRole, segment)
                self.result_list.addItem(item)
                count += 1
        return count

    def on_text_changed(self):
        text = self.input_box.toPlainText().strip()
        count = self.refresh_list(text)
        if count == 0:
            self.system_feedback.setText("❌ 未找到相关问题，请尝试其他关键词")
            self.system_feedback.setStyleSheet("""
                QLabel {
                    color: #e74c3c;
                    font-size: 12px;
                    padding: 12px;
                    background-color: #fadbd8;
                    border-radius: 6px;
                    border-left: 4px solid #e74c3c;
                }
            """)
        else:
            self.system_feedback.setText(f"✅ 实时筛选：{count} 个结果（可双击播放）")
            self.system_feedback.setStyleSheet("""
                QLabel {
                    color: #27ae60;
                    font-size: 12px;
                    padding: 12px;
                    background-color: #d5f4e6;
                    border-radius: 6px;
                    border-left: 4px solid #27ae60;
                }
            """)

    def on_send_clicked(self):
        text = self.input_box.toPlainText().strip()
        count = self.refresh_list(text)

        if count == 0:
            self.system_feedback.setText("❌ 未找到相关问题，请尝试其他关键词")
            self.system_feedback.setStyleSheet("""
                QLabel {
                    color: #e74c3c;
                    font-size: 12px;
                    padding: 12px;
                    background-color: #fadbd8;
                    border-radius: 6px;
                    border-left: 4px solid #e74c3c;
                }
            """)
        else:
            self.system_feedback.setText(f"✅ 找到 {count} 个相关问题，双击查看视频")
            self.system_feedback.setStyleSheet("""
                QLabel {
                    color: #27ae60;
                    font-size: 12px;
                    padding: 12px;
                    background-color: #d5f4e6;
                    border-radius: 6px;
                    border-left: 4px solid #27ae60;
                }
            """)

    # ================= 播放 =================
    def on_item_double_clicked(self, item: QListWidgetItem):
        segment = item.data(Qt.UserRole)
        video_path = self.course_dir / "segments" / segment
        self._current_video = video_path

        if video_path.exists():
            media = self.vlc_instance.media_new(str(video_path))
            self.vlc_player.set_media(media)
            self.vlc_player.play()
            self.system_feedback.setText(f"▶️ 正在播放：{item.text()}")
            self.system_feedback.setStyleSheet("""
                QLabel {
                    color: #8e44ad;
                    font-size: 12px;
                    padding: 12px;
                    background-color: #ebdef0;
                    border-radius: 6px;
                    border-left: 4px solid #8e44ad;
                }
            """)
        else:
            self.system_feedback.setText("❌ 视频文件不存在，请检查 segments 目录")
            self.system_feedback.setStyleSheet("""
                QLabel {
                    color: #e74c3c;
                    font-size: 12px;
                    padding: 12px;
                    background-color: #fadbd8;
                    border-radius: 6px;
                    border-left: 4px solid #e74c3c;
                }
            """)

    def toggle_fullscreen(self, event):
        if self.video_widget.isFullScreen():
            self.video_widget.setFullScreen(False)
        else:
            self.video_widget.setFullScreen(True)

    def play_pause(self):
        try:
            if self.vlc_player.is_playing():
                self.vlc_player.pause()
            else:
                if self.vlc_player.get_media() is None and self._current_video and self._current_video.exists():
                    media = self.vlc_instance.media_new(str(self._current_video))
                    self.vlc_player.set_media(media)
                self.vlc_player.play()
        except Exception:
            pass

    def stop_video(self):
        try:
            self.vlc_player.stop()
        except Exception:
            pass

    def set_position(self, position):
        try:
            self._dragging_slider = True
            self.vlc_player.set_time(int(position))
        finally:
            self._dragging_slider = False

    def set_volume(self, volume):
        try:
            self.vlc_player.audio_set_volume(int(volume))
        except Exception:
            pass

    def format_time(self, milliseconds):
        seconds = int(milliseconds) // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def closeEvent(self, event):
        try:
            self.vlc_player.stop()
        except Exception:
            pass
        super().closeEvent(event)


def pick_first_course_dir(courses_root: Path) -> Path | None:
    try:
        for p in courses_root.iterdir():
            if p.is_dir():
                return p
    except Exception:
        return None
    return None


if __name__ == "__main__":
    install_global_exception_hook()

    # ✅ 先构建 QApplication（关键修复点）
    app = QApplication(sys.argv)

    courses_root = find_courses_root()
    if courses_root is None:
        # 现在可以安全弹窗
        QMessageBox.critical(
            None,
            "未找到课程目录",
            "找不到课程目录：\n\n"
            "请把老师的课程文件夹放到【exe同级】的以下任一位置：\n"
            "1) data\\courses\\课程名\\\n"
            "2) courses\\课程名\\\n\n"
            "示例：\n"
            "StudentApp.exe\n"
            "data\\courses\\机械制图_测试课\\(course.db/questions.db/segments...)\n"
        )
        sys.exit(1)

    course_dir = pick_first_course_dir(courses_root)
    if course_dir is None:
        QMessageBox.critical(
            None,
            "课程目录为空",
            f"已找到课程根目录：\n{courses_root}\n\n但里面没有课程子目录。请确认已复制课程文件夹。"
        )
        sys.exit(1)

    window = StudentApp(course_dir)
    window.show()
    sys.exit(app.exec_())
