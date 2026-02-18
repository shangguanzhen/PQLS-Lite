from __future__ import annotations

"""student/student_gui.py

学生端：课程库管理 + 字幕/问题列表 + VLC 嵌入式播放。

⚠️ 重要约束：
1) UI 布局与播放器功能不做结构性改动（仅在逻辑层接入语义检索 + 修复导入线程）。
2) 课程包必须通过 manifest 严格校验后才能导入（方案 B：manifest + 校验，不做签名）。

新增（本次修复重点）：
- 导入课程包：校验 + 复制放入 QThread，避免 UI 卡死；
- 进度条：导入过程实时更新；
- 导入完成：自动刷新课程列表并切换到新课程，右侧列表即时显示。
"""

import os
import sys
import json
import shutil
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QMessageBox,
    QTextEdit, QListWidget, QListWidgetItem, QComboBox,
    QGroupBox, QProgressBar, QCheckBox, QFrame, QLineEdit,
    QSlider, QStyle
)


APP_NAME = "PQLS"
CFG_NAME = "student_config.json"
MAX_SHOW = 800  # 防卡 UI：右侧最多显示 N 条


# -----------------------
# 配置：记住课程库目录
# -----------------------
def _appdata_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cfg_path() -> Path:
    return _appdata_dir() / CFG_NAME


def load_cfg() -> dict:
    p = _cfg_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cfg(cfg: dict):
    _cfg_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def default_library_dir() -> Path:
    up = os.environ.get("USERPROFILE")
    if up:
        desk = Path(up) / "Desktop"
        if desk.exists():
            return desk / "PQLS_Courses"
    return Path.home() / "Desktop" / "PQLS_Courses"


def get_library_dir() -> Path | None:
    cfg = load_cfg()
    v = cfg.get("library_dir")
    if not v:
        return None
    p = Path(v)
    return p if p.exists() else None


def set_library_dir(p: Path):
    cfg = load_cfg()
    cfg["library_dir"] = str(Path(p).resolve())
    save_cfg(cfg)


# -----------------------
# manifest 严格校验（方案B）
# -----------------------
def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_manifest(course_dir: Path) -> dict:
    mp = course_dir / "manifest.json"
    if not mp.exists():
        raise RuntimeError("manifest.json 不存在")
    return json.loads(mp.read_text(encoding="utf-8"))


def validate_course_dir_strict(course_dir: Path, progress_cb=None) -> tuple[bool, str]:
    """严格校验课程包：
    - 允许 teacher v1 manifest（不强制 schema 字段），只要 files 列表可用。
    - 逐文件校验 size + sha256。
    """
    try:
        m = load_manifest(course_dir)

        # 兼容：旧 teacher manifest 没有 schema
        mv = m.get("manifest_version")
        if mv is not None and int(mv) <= 0:
            return False, "manifest_version 非法"

        files = m.get("files", [])
        if not isinstance(files, list) or not files:
            return False, "manifest.files 为空或格式错误"

        total = len(files)
        for i, item in enumerate(files, start=1):
            rel = item.get("path")
            size = item.get("size")
            sha = item.get("sha256")
            if not rel or size is None or not sha:
                return False, "manifest.files 项缺字段"

            fp = course_dir / rel
            if not fp.exists():
                return False, f"缺失文件：{rel}"

            real_size = fp.stat().st_size
            if int(real_size) != int(size):
                return False, f"文件大小不一致：{rel}"

            real_sha = sha256_file(fp)
            if real_sha.lower() != str(sha).lower():
                return False, f"哈希不一致：{rel}"

            if progress_cb:
                progress_cb(i, total, f"校验：{rel}")

        # 快速存在性检查
        layout = m.get("layout") or {}
        qdb = layout.get("questions_db") or "questions.db"
        cdb = layout.get("course_db") or "course.db"
        if not (course_dir / qdb).exists():
            return False, f"缺少 questions.db：{qdb}"
        if not (course_dir / cdb).exists():
            return False, f"缺少 course.db：{cdb}"
        seg_dir = layout.get("segments_dir") or "segments"
        if not (course_dir / seg_dir).exists():
            return False, f"缺少 segments 目录：{seg_dir}"

        return True, "OK"
    except Exception as e:
        return False, f"manifest 校验异常：{e}"


def list_courses(library_dir: Path) -> list[Path]:
    if not library_dir.exists():
        return []
    items: list[Path] = []
    for p in library_dir.iterdir():
        if not p.is_dir():
            continue
        if (p / "manifest.json").exists() and (p / "questions.db").exists():
            items.append(p)
    items.sort(key=lambda x: x.name)
    return items


def _safe_course_name(src_course_dir: Path) -> str:
    try:
        m = load_manifest(src_course_dir)
        course_name = (m.get("course_name") or src_course_dir.name).strip() or src_course_dir.name
    except Exception:
        course_name = src_course_dir.name
    return course_name


def _resolve_target_dir(library_dir: Path, course_name: str) -> Path:
    target = library_dir / course_name
    if target.exists():
        n = 2
        while True:
            t2 = library_dir / f"{course_name} ({n})"
            if not t2.exists():
                return t2
            n += 1
    return target


def _copytree_with_progress(src: Path, dst: Path, progress_cb=None):
    """自己实现 copytree：可进度更新、可避免 copytree 大目录假死。"""
    src = Path(src)
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    for p in src.rglob("*"):
        if p.is_file():
            files.append(p)

    total = max(len(files), 1)
    for i, f in enumerate(files, start=1):
        rel = f.relative_to(src)
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(f), str(out))

        if progress_cb:
            progress_cb(i, total, f"复制：{rel.as_posix()}")


# -----------------------
# questions.db 读取
# -----------------------
def load_questions_items(course_dir: Path) -> list[tuple[str, str, int]]:
    db = course_dir / "questions.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    try:
        cur.execute("SELECT q, segment_filename, segment_idx FROM questions ORDER BY id ASC")
        rows = cur.fetchall()
        return [((r[0] or "").strip(), (r[1] or "").strip(), int(r[2]) if r[2] is not None else -1) for r in rows]
    finally:
        conn.close()


# -----------------------
# 语义检索：延迟加载（不影响 UI/播放器）
# -----------------------
def _nlp_root() -> Path:
    return Path(__file__).resolve().parent / "nlp"


def _index_dir_default() -> Path:
    return _nlp_root() / "index"


class _SemanticEngine:
    """轻量封装：只有在需要时才加载 index。"""

    def __init__(self):
        self._ready = False
        self._err: str | None = None
        self._search = None
        self._index_dir = _index_dir_default()

    def set_index_dir(self, p: Path):
        self._index_dir = Path(p)
        self._ready = False
        self._err = None
        self._search = None

    def ensure_loaded(self) -> bool:
        if self._ready and self._search is not None:
            return True
        try:
            if not self._index_dir.exists():
                self._err = f"未找到语义索引目录：{self._index_dir}"
                return False

            # 兼容两种启动方式：python student_gui.py（cwd=student）或从根目录启动
            try:
                from student.nlp.search import SemanticSearcher  # type: ignore
            except Exception:
                from nlp.search import SemanticSearcher  # type: ignore

            self._search = SemanticSearcher(self._index_dir)
            self._ready = True
            self._err = None
            return True
        except Exception as e:
            self._err = str(e)
            self._ready = False
            self._search = None
            return False

    def last_error(self) -> str | None:
        return self._err

    def query(self, text: str, topk: int, course_name: str | None = None) -> list[dict]:
        if not self.ensure_loaded():
            return []
        assert self._search is not None
        return self._search.search(text, topk=topk, course_name=course_name)


# -----------------------
# 导入线程：避免主线程卡死 + 进度条实时更新
# -----------------------
class ImportWorker(QThread):
    sig_progress = pyqtSignal(int, str)      # pct, msg
    sig_done = pyqtSignal(bool, str, str)    # ok, reason, new_path_or_empty

    def __init__(self, src_dir: Path, library_dir: Path):
        super().__init__()
        self.src_dir = Path(src_dir)
        self.library_dir = Path(library_dir)

    def run(self):
        try:
            self.library_dir.mkdir(parents=True, exist_ok=True)

            # 1) manifest 严格校验：0~60%
            def _p1(i, total, msg):
                pct = int((i / max(total, 1)) * 60)
                self.sig_progress.emit(pct, msg)

            self.sig_progress.emit(0, "开始校验课程包…")
            ok, reason = validate_course_dir_strict(self.src_dir, progress_cb=_p1)
            if not ok:
                self.sig_done.emit(False, reason, "")
                return

            # 2) 确定目标目录
            course_name = _safe_course_name(self.src_dir)
            target = _resolve_target_dir(self.library_dir, course_name)

            # 3) 复制：60~98%
            def _p2(i, total, msg):
                pct = 60 + int((i / max(total, 1)) * 38)
                self.sig_progress.emit(pct, msg)

            self.sig_progress.emit(60, "开始复制到课程库…")
            _copytree_with_progress(self.src_dir, target, progress_cb=_p2)

            # 4) 写 meta：98~100
            meta = {
                "course_name": target.name,
                "imported_at": datetime.now().isoformat(timespec="seconds"),
                "imported_from": str(self.src_dir.resolve()),
                "validated": True,
            }
            (target / ".pqls_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            self.sig_progress.emit(100, "导入完成")
            self.sig_done.emit(True, "OK", str(target.resolve()))
        except Exception as e:
            self.sig_done.emit(False, f"导入异常：{e}", "")


# ==========================================================
# GUI
# ==========================================================
class StudentApp(QWidget):
    def __init__(self):
        super().__init__()

        self.library_dir = self._ensure_library_dir()
        self.course_dirs: list[Path] = []
        self.current_course_dir: Path | None = None

        self.items: list[tuple[str, str, int]] = []
        self.global_index: list[tuple[str, Path, str, str, str]] = []

        self.semantic = _SemanticEngine()

        self.vlc_ok = False
        self.vlc_instance = None
        self.vlc_player = None
        self._is_dragging_slider = False

        self._import_worker: ImportWorker | None = None

        self._build_ui()
        self._init_vlc()
        self.refresh_courses(preserve_selection=False, auto_select=True)

    def _ensure_library_dir(self) -> Path:
        lib = get_library_dir()
        if lib is None:
            lib = default_library_dir()
            lib.mkdir(parents=True, exist_ok=True)
            set_library_dir(lib)
        else:
            lib.mkdir(parents=True, exist_ok=True)
        return lib

    # ---------------- VLC ----------------
    def _init_vlc(self):
        try:
            os.environ["VLC_VERBOSE"] = "-1"
            import vlc  # type: ignore

            self.vlc_instance = vlc.Instance("--quiet", "--no-video-title-show", "--no-osd", "--no-stats")
            self.vlc_player = self.vlc_instance.media_player_new()
            self.vlc_ok = True
            self.log("VLC 播放器初始化成功（嵌入式播放）")
        except Exception as e:
            self.vlc_ok = False
            self.vlc_instance = None
            self.vlc_player = None
            self.log(f"VLC 初始化失败：{e}")

        self.timer_ui = QTimer(self)
        self.timer_ui.timeout.connect(self._tick_player_ui)

    def _ensure_vlc_ready_or_hint(self) -> bool:
        if self.vlc_ok and self.vlc_player is not None:
            return True
        QMessageBox.information(
            self,
            "提示",
            "未检测到 VLC Python 依赖或 VLC 本体。\n\n"
            "请先安装 VLC 播放器，然后在 venv_student 中安装 python-vlc：\n"
            "pip install python-vlc",
        )
        return False

    def _vlc_attach_to_widget(self):
        if not self._ensure_vlc_ready_or_hint():
            return
        wid = int(self.vlc_container.winId())
        try:
            if sys.platform.startswith("win"):
                self.vlc_player.set_hwnd(wid)
            elif sys.platform.startswith("linux"):
                self.vlc_player.set_xwindow(wid)
            elif sys.platform.startswith("darwin"):
                self.vlc_player.set_nsobject(wid)
        except Exception as e:
            self.log(f"VLC 绑定窗口失败：{e}")

    def _vlc_play_file(self, path: Path):
        if not self._ensure_vlc_ready_or_hint():
            return
        if not path.exists():
            QMessageBox.warning(self, "播放失败", f"文件不存在：\n{path}")
            return
        self._vlc_attach_to_widget()
        try:
            m = self.vlc_instance.media_new(str(path))
            self.vlc_player.set_media(m)
            self.vlc_player.play()
            self.timer_ui.start(250)
        except Exception as e:
            QMessageBox.warning(self, "播放失败", str(e))

    def _vlc_pause_toggle(self):
        if not self._ensure_vlc_ready_or_hint():
            return
        try:
            if self.vlc_player.is_playing():
                self.vlc_player.pause()
                self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            else:
                self.vlc_player.play()
                self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        except Exception:
            pass

    def _vlc_stop(self):
        if self.vlc_player is None:
            return
        try:
            self.vlc_player.stop()
        except Exception:
            pass
        self.timer_ui.stop()
        self.slider_pos.setRange(0, 0)
        self.slider_pos.setValue(0)
        self.lbl_time.setText("00:00 / 00:00")
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def _vlc_get_duration_ms(self) -> int:
        try:
            d = int(self.vlc_player.get_length())
            return max(d, 0)
        except Exception:
            return 0

    def _vlc_get_position_ms(self) -> int:
        try:
            t = int(self.vlc_player.get_time())
            return max(t, 0)
        except Exception:
            return 0

    def _vlc_set_position_ms(self, ms: int):
        try:
            self.vlc_player.set_time(int(ms))
        except Exception:
            pass

    # ---------------- UI ----------------
    def _build_ui(self):
        # UI 样式保持原结构（不改布局）
        C_BG = "#F4F7FA"
        C_PANEL = "#FFFFFF"
        C_BORDER = "#D8E1EA"
        C_TEXT = "#2C3E50"
        C_TEXT2 = "#6B7B8C"
        C_ACCENT = "#2E86DE"
        C_ACCENT2 = "#54A0FF"
        C_ACCENT3 = "#1E5FA8"
        C_ROW_H = "#EAF3FF"
        C_VIDEO_BG = "#000000"
        C_CTRL_BG = "#1F2D3A"

        self.setWindowTitle("课程问答播放器 · 学生端")
        self.resize(1200, 700)

        self.setStyleSheet(f"""
            QWidget {{
                background: {C_BG};
                font-family: Microsoft YaHei;
            }}
        """)

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(16)

        left = QFrame()
        left.setObjectName("leftPanel")
        left.setStyleSheet("QFrame#leftPanel { background: transparent; }")
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(12)

        title_bar = QFrame()
        title_bar.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C_ACCENT}, stop:1 {C_ACCENT2});
                border-radius: 14px;
                padding: 14px;
            }}
        """)
        tb_l = QHBoxLayout(title_bar)
        tb_l.setContentsMargins(18, 10, 18, 10)
        lbl_title = QLabel("🎓  PQLS 学生端")
        lbl_title.setStyleSheet("color:white; font-size:16px; font-weight:bold;")
        tb_l.addWidget(lbl_title)
        tb_l.addStretch(1)

        mg = QGroupBox("📚  课程管理")
        mg.setStyleSheet(f"""
            QGroupBox {{
                background: {C_PANEL};
                border: 1px solid {C_BORDER};
                border-radius: 14px;
                margin-top: 12px;
                padding: 12px;
                font-weight: bold;
                color: {C_TEXT};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
        """)
        mg_l = QVBoxLayout(mg)
        mg_l.setContentsMargins(14, 20, 14, 14)
        mg_l.setSpacing(10)

        self.lbl_lib = QLabel(f"课程库：{self.library_dir}")
        self.lbl_lib.setStyleSheet(f"color:{C_TEXT2}; font-size:12px;")
        self.lbl_lib.setWordWrap(True)

        self.combo_course = QComboBox()
        self.combo_course.setFixedHeight(34)
        self.combo_course.setStyleSheet(f"""
            QComboBox {{
                border: 1.5px solid {C_BORDER};
                border-radius: 10px;
                padding: 4px 10px;
                background: white;
                color: {C_TEXT};
                font-size: 13px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                border: 1px solid {C_BORDER};
                background: white;
                selection-background-color: {C_ROW_H};
                selection-color: {C_TEXT};
            }}
        """)
        self.combo_course.currentIndexChanged.connect(self.on_course_changed)

        def _make_btn(text: str) -> QPushButton:
            b = QPushButton(text)
            b.setFixedHeight(34)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: #F2F4F7;
                    border: 1px solid {C_BORDER};
                    border-radius: 10px;
                    color: {C_TEXT};
                    font-size: 12px;
                    padding: 0 10px;
                }}
                QPushButton:hover {{ background: {C_ROW_H}; border-color: {C_ACCENT2}; }}
                QPushButton:pressed {{ background: #DDEBFF; }}
            """)
            return b

        btn_row1 = QHBoxLayout(); btn_row1.setSpacing(8)
        self.btn_set_lib = _make_btn("⚙  设置库")
        self.btn_import = _make_btn("⬇  导入课程")
        self.btn_refresh = _make_btn("↻ 刷新")
        self.btn_set_lib.clicked.connect(self.choose_library_dir)
        self.btn_import.clicked.connect(self.import_course_ui)
        self.btn_refresh.clicked.connect(lambda: self.refresh_courses(preserve_selection=True, auto_select=False))
        btn_row1.addWidget(self.btn_set_lib); btn_row1.addWidget(self.btn_import); btn_row1.addWidget(self.btn_refresh)

        btn_row2 = QHBoxLayout(); btn_row2.setSpacing(8)
        self.btn_delete = _make_btn("🗑  删除课程")
        self.btn_open = _make_btn("📁  打开库")
        self.btn_delete.clicked.connect(self.delete_current_course)
        self.btn_open.clicked.connect(self.open_library_folder)
        btn_row2.addWidget(self.btn_delete); btn_row2.addWidget(self.btn_open)

        self.chk_global = QCheckBox("🌐  全库搜索（跨课程）")
        self.chk_global.setStyleSheet(f"""
            QCheckBox {{ color: {C_TEXT}; font-size: 12px; padding: 4px 6px; }}
            QCheckBox::indicator {{ width: 16px; height: 16px; }}
        """)
        self.chk_global.stateChanged.connect(self.refresh_suggestions)

        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.progress.setFixedHeight(18); self.progress.setTextVisible(False)
        self.progress.setStyleSheet(f"""
            QProgressBar {{ background: #E9EEF3; border: 1px solid {C_BORDER}; border-radius: 9px; }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {C_ACCENT}, stop:1 {C_ACCENT2});
                border-radius: 9px;
            }}
        """)

        self.lbl_status = QLabel("状态：就绪")
        self.lbl_status.setStyleSheet(f"color:{C_TEXT2}; font-size:12px;")

        self.log_box = QTextEdit(); self.log_box.setReadOnly(True); self.log_box.setFixedHeight(95)
        self.log_box.setStyleSheet(f"""
            QTextEdit {{ border: 1px solid {C_BORDER}; border-radius: 10px; padding: 8px; background: #F8FAFB; color: {C_TEXT2}; }}
        """)

        lbl_current = QLabel("当前课程")
        lbl_current.setStyleSheet(f"color:{C_TEXT2}; font-size:11px; font-weight:bold;")

        mg_l.addWidget(self.lbl_lib)
        mg_l.addWidget(lbl_current)
        mg_l.addWidget(self.combo_course)
        mg_l.addLayout(btn_row1)
        mg_l.addLayout(btn_row2)
        mg_l.addWidget(self.chk_global)
        mg_l.addWidget(self.progress)
        mg_l.addWidget(self.lbl_status)
        mg_l.addWidget(self.log_box)

        lbl_search = QLabel("🔎  关键词搜索")
        lbl_search.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        lbl_search.setStyleSheet(f"color:{C_ACCENT3};")

        self.edit_kw = QLineEdit(); self.edit_kw.setPlaceholderText("输入关键词，右侧列表即时筛选…")
        self.edit_kw.setFixedHeight(38)
        self.edit_kw.setStyleSheet(f"""
            QLineEdit {{ border: 2px solid {C_BORDER}; border-radius: 10px; padding: 0 14px; font-size: 13px; background: white; color: {C_TEXT}; }}
            QLineEdit:focus {{ border-color: {C_ACCENT}; background: #F0F7FF; }}
        """)
        self.edit_kw.textChanged.connect(self.refresh_suggestions)

        self.lbl_hint = QLabel("💡  双击右侧条目即可播放对应视频片段")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet(f"""
            color: {C_TEXT2}; font-size: 12px; padding: 10px 12px;
            background: #EBF5FB; border-radius: 8px; border-left: 4px solid {C_ACCENT};
        """)

        left_l.addWidget(title_bar)
        left_l.addWidget(mg)
        left_l.addWidget(lbl_search)
        left_l.addWidget(self.edit_kw)
        left_l.addWidget(self.lbl_hint)
        left_l.addStretch()

        right = QFrame(); right.setObjectName("rightPanel")
        right.setStyleSheet("QFrame#rightPanel { background: transparent; }")
        right_l = QVBoxLayout(right); right_l.setContentsMargins(0, 0, 0, 0); right_l.setSpacing(12)

        list_title = QFrame(); list_title.setStyleSheet(f"QFrame {{ background: {C_PANEL}; border-radius: 10px; border: 1px solid {C_BORDER}; }}")
        lt_l = QHBoxLayout(list_title); lt_l.setContentsMargins(14, 8, 14, 8)
        lbl_lt = QLabel("📋  字幕 / 问题列表"); lbl_lt.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        lbl_lt.setStyleSheet(f"color:{C_TEXT}; background:transparent;")
        lbl_lt_hint = QLabel("输入关键词即时筛选  ·  双击播放")
        lbl_lt_hint.setStyleSheet(f"color:{C_TEXT2}; font-size:11px; background:transparent;")
        lt_l.addWidget(lbl_lt); lt_l.addStretch(); lt_l.addWidget(lbl_lt_hint)

        self.list_items = QListWidget(); self.list_items.setFixedHeight(260)
        self.list_items.setStyleSheet(f"""
            QListWidget {{ border: 1.5px solid {C_BORDER}; border-radius: 10px; background: {C_PANEL}; padding: 6px; font-size: 13px; outline: none; }}
            QListWidget::item {{ padding: 9px 14px; border-radius: 7px; margin: 2px 0; color: {C_TEXT}; }}
            QListWidget::item:hover {{ background: #EAF3FF; color: #2E86DE; }}
            QListWidget::item:selected {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2E86DE, stop:1 #54A0FF); color: white; border: none; }}
            QListWidget::item:selected:hover {{ background: #54A0FF; }}
        """)
        self.list_items.itemDoubleClicked.connect(self.on_item_double_clicked)

        video_title = QFrame(); video_title.setStyleSheet(f"QFrame {{ background: {C_PANEL}; border-radius: 10px; border: 1px solid {C_BORDER}; }}")
        vt_l = QHBoxLayout(video_title); vt_l.setContentsMargins(14, 8, 14, 8)
        lbl_vt = QLabel("🎬  视频播放区"); lbl_vt.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        lbl_vt.setStyleSheet(f"color:{C_TEXT}; background:transparent;")
        lbl_vt_hint = QLabel("VLC 嵌入式  ·  双击列表项播放")
        lbl_vt_hint.setStyleSheet(f"color:{C_TEXT2}; font-size:11px; background:transparent;")
        vt_l.addWidget(lbl_vt); vt_l.addStretch(); vt_l.addWidget(lbl_vt_hint)

        video_frame = QFrame(); video_frame.setStyleSheet(f"QFrame {{ background: {C_VIDEO_BG}; border: 2px solid #2C3E50; border-radius: 14px; }}")
        vf_l = QVBoxLayout(video_frame); vf_l.setContentsMargins(0, 0, 0, 0); vf_l.setSpacing(0)

        self.vlc_container = QFrame(); self.vlc_container.setStyleSheet(f"QFrame {{ background:{C_VIDEO_BG}; border:none; }}")
        vf_l.addWidget(self.vlc_container, 1)
        sep = QFrame(); sep.setFixedHeight(1); sep.setStyleSheet("background:#2C3E50;"); vf_l.addWidget(sep)

        controls = QFrame(); controls.setStyleSheet(f"QFrame {{ background: {C_CTRL_BG}; border-bottom-left-radius: 12px; border-bottom-right-radius: 12px; }}")
        cl = QVBoxLayout(controls); cl.setContentsMargins(14, 10, 14, 10); cl.setSpacing(8)

        self.slider_pos = QSlider(Qt.Horizontal); self.slider_pos.setRange(0, 0); self.slider_pos.setFixedHeight(20)
        self.slider_pos.sliderPressed.connect(lambda: setattr(self, "_is_dragging_slider", True))
        self.slider_pos.sliderReleased.connect(self._on_slider_released)
        self.slider_pos.sliderMoved.connect(self._on_slider_moved)
        self.slider_pos.setStyleSheet(f"""
            QSlider::groove:horizontal {{ border: none; height: 5px; background: #2C4A6E; border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2E86DE, stop:1 #54A0FF); border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: white; border: 2px solid #2E86DE; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
            QSlider::handle:horizontal:hover {{ background: #54A0FF; border-color: white; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }}
        """)

        row = QHBoxLayout(); row.setSpacing(10)

        self.btn_play = QPushButton(); self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_play.setFixedSize(38, 38); self.btn_play.clicked.connect(self._vlc_pause_toggle)
        self.btn_play.setCursor(Qt.PointingHandCursor); self.btn_play.setToolTip("播放 / 暂停")
        self.btn_play.setStyleSheet(f"""
            QPushButton {{ background: #2E86DE; border: none; border-radius: 19px; padding: 6px; }}
            QPushButton:hover {{ background: #54A0FF; }}
            QPushButton:pressed {{ background: #1E5FA8; }}
        """)

        self.btn_stop = QPushButton(); self.btn_stop.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.btn_stop.setFixedSize(32, 32); self.btn_stop.clicked.connect(self._vlc_stop)
        self.btn_stop.setCursor(Qt.PointingHandCursor); self.btn_stop.setToolTip("停止")
        self.btn_stop.setStyleSheet("""
            QPushButton { background: #2C4A6E; border: none; border-radius: 16px; padding: 5px; }
            QPushButton:hover { background: #3A6491; }
            QPushButton:pressed { background: #1E3352; }
        """)

        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setStyleSheet("color: #BDC3C7; font-size: 12px; font-family: Consolas, monospace; padding: 0 12px;")

        row.addWidget(self.btn_play); row.addWidget(self.btn_stop); row.addWidget(self.lbl_time); row.addStretch()

        cl.addWidget(self.slider_pos); cl.addLayout(row)
        vf_l.addWidget(controls)

        right_l.addWidget(list_title)
        right_l.addWidget(self.list_items)
        right_l.addWidget(video_title)
        right_l.addWidget(video_frame, 1)

        root.addWidget(left, 2)
        root.addWidget(right, 5)

        self.set_search_enabled(False)

    # ---------------- utils ----------------
    def log(self, msg: str):
        t = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{t}] {msg}")

    def set_search_enabled(self, enabled: bool):
        self.edit_kw.setEnabled(enabled)
        self.list_items.setEnabled(enabled)

    def _set_busy(self, busy: bool, status: str = ""):
        # 不改 UI，只是禁用按钮，避免导入时重复点击导致线程冲突
        self.btn_import.setEnabled(not busy)
        self.btn_set_lib.setEnabled(not busy)
        self.btn_refresh.setEnabled(not busy)
        self.btn_delete.setEnabled(not busy)
        self.btn_open.setEnabled(not busy)
        self.combo_course.setEnabled(not busy and bool(self.course_dirs))
        if status:
            self.lbl_status.setText(status)

    # ---------------- course ops ----------------
    def choose_library_dir(self):
        chosen = QFileDialog.getExistingDirectory(self, "选择课程库目录（用于存放导入的课程包）", str(self.library_dir))
        if not chosen:
            return
        self.library_dir = Path(chosen).resolve()
        self.library_dir.mkdir(parents=True, exist_ok=True)
        set_library_dir(self.library_dir)
        self.lbl_lib.setText(f"课程库：{self.library_dir}")
        self.log(f"已设置课程库：{self.library_dir}")
        self.refresh_courses(preserve_selection=False, auto_select=True)

    def open_library_folder(self):
        try:
            self.library_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.library_dir))
            self.log("已打开课程库文件夹")
        except Exception as e:
            QMessageBox.warning(self, "打开失败", f"无法打开课程库文件夹：{e}")

    def delete_current_course(self):
        if not self.current_course_dir or not self.current_course_dir.exists():
            QMessageBox.information(self, "提示", "当前没有选中的课程可删除。")
            return
        course_name = self.current_course_dir.name
        r = QMessageBox.question(self, "确认删除", f"将删除课程：{course_name}\n\n删除后不可恢复，是否继续？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self._vlc_stop()
        try:
            shutil.rmtree(self.current_course_dir)
            self.log(f"已删除课程：{course_name}")
        except Exception as e:
            QMessageBox.warning(self, "删除失败", f"删除课程失败：{e}\n\n请先停止播放再试。")
            self.log(f"删除失败：{e}")
            return
        self.refresh_courses(preserve_selection=False, auto_select=True)

    def rebuild_global_index(self):
        idx = []
        for cd in self.course_dirs:
            course_name = cd.name
            items = load_questions_items(cd)
            for q, seg, _ in items:
                if not q:
                    continue
                idx.append((course_name, cd, q, seg, q.lower()))
        self.global_index = idx
        self.log(f"全库索引已构建：课程 {len(self.course_dirs)} 个，条目 {len(self.global_index)} 条")

    def refresh_courses(self, preserve_selection: bool, auto_select: bool):
        cur_name = self.current_course_dir.name if (preserve_selection and self.current_course_dir) else None
        cur_path = str(self.current_course_dir.resolve()) if (preserve_selection and self.current_course_dir) else None

        self.combo_course.blockSignals(True)
        self.combo_course.clear()
        self.course_dirs = list_courses(self.library_dir)

        if not self.course_dirs:
            self.combo_course.addItem("（暂无课程，请导入）", None)
            self.combo_course.setEnabled(False)
            self.current_course_dir = None
            self.items = []
            self.global_index = []
            self.list_items.clear()
            self.set_search_enabled(False)
            self.combo_course.blockSignals(False)
            return

        self.combo_course.setEnabled(True)
        for cd in self.course_dirs:
            self.combo_course.addItem(cd.name, cd)
        self.combo_course.blockSignals(False)

        self.rebuild_global_index()

        target_index = None
        if cur_path:
            for i in range(self.combo_course.count()):
                cd = self.combo_course.itemData(i)
                if cd is None:
                    continue
                if str(Path(cd).resolve()) == cur_path:
                    target_index = i
                    break
        if target_index is None and cur_name:
            n1 = cur_name.strip()
            for i in range(self.combo_course.count()):
                if self.combo_course.itemText(i).strip() == n1:
                    target_index = i
                    break
        if target_index is None:
            target_index = 0 if auto_select else max(self.combo_course.currentIndex(), 0)

        self.combo_course.setCurrentIndex(target_index)
        self.on_course_changed(target_index)

    def on_course_changed(self, i: int):
        cd = self.combo_course.itemData(i)
        if cd is None:
            return
        self._vlc_stop()
        self.current_course_dir = Path(cd)
        self.items = load_questions_items(self.current_course_dir)
        self.log(f"切换课程：{self.current_course_dir.name}｜条目：{len(self.items)}")
        self.set_search_enabled(True)
        self.edit_kw.blockSignals(True)
        self.edit_kw.setText("")
        self.edit_kw.blockSignals(False)
        self.refresh_suggestions()

    def import_course_ui(self):
        if self._import_worker and self._import_worker.isRunning():
            QMessageBox.information(self, "提示", "正在导入中，请稍候完成。")
            return

        src = QFileDialog.getExistingDirectory(self, "选择教师端导出的课程包目录（包含 manifest.json）", str(self.library_dir))
        if not src:
            return

        src_dir = Path(src)
        self.log(f"开始导入课程包：{src_dir}")

        self.progress.setValue(0)
        self.lbl_status.setText("状态：正在导入…")
        self._set_busy(True, status="状态：正在导入…")

        worker = ImportWorker(src_dir, self.library_dir)
        self._import_worker = worker

        def _on_progress(pct: int, msg: str):
            self.progress.setValue(max(0, min(100, pct)))
            if msg:
                self.lbl_status.setText(f"状态：{msg}")

        def _on_done(ok: bool, reason: str, new_path_str: str):
            self._set_busy(False, status="状态：就绪")
            if not ok:
                QMessageBox.warning(self, "导入失败", reason)
                self.log(f"导入失败：{reason}")
                self.progress.setValue(0)
                return

            new_path = Path(new_path_str) if new_path_str else None
            self.log(f"导入成功：{new_path}")
            self.progress.setValue(100)
            self.lbl_status.setText("状态：导入完成")

            # 刷新课程列表并切到新课程（右侧立即出现）
            self.refresh_courses(preserve_selection=False, auto_select=False)
            if new_path:
                target_index = 0
                for i in range(self.combo_course.count()):
                    cd = self.combo_course.itemData(i)
                    if cd is None:
                        continue
                    if str(Path(cd).resolve()) == str(new_path.resolve()):
                        target_index = i
                        break
                self.combo_course.setCurrentIndex(target_index)
                self.on_course_changed(target_index)
                self.refresh_suggestions()

        worker.sig_progress.connect(_on_progress)
        worker.sig_done.connect(_on_done)
        worker.start()

    # ---------------- search ----------------
    @staticmethod
    def _normalize_query(q: str) -> str:
        q = (q or "").strip().lower()
        for ch in ["的", "了", "啊", "呢", "呀", "嘛", "吧", "么"]:
            q = q.replace(ch, "")
        q = " ".join(q.split())
        return q

    def refresh_suggestions(self):
        raw = (self.edit_kw.text() or "").strip()
        kw = self._normalize_query(raw)
        self.list_items.clear()

        scope_course_name = None if self.chk_global.isChecked() else (self.current_course_dir.name if self.current_course_dir else None)

        if not kw:
            show = 0
            if self.chk_global.isChecked():
                for course_name, cd, q, seg, _ in self.global_index:
                    it = QListWidgetItem(f"[{course_name}] {q}")
                    it.setData(Qt.UserRole, (str(cd), seg))
                    self.list_items.addItem(it)
                    show += 1
                    if show >= MAX_SHOW:
                        break
                return
            if not self.current_course_dir:
                return
            for q, seg, _ in self.items:
                if not q:
                    continue
                it = QListWidgetItem(q)
                it.setData(Qt.UserRole, (str(self.current_course_dir), seg))
                self.list_items.addItem(it)
                show += 1
                if show >= MAX_SHOW:
                    break
            return

        # 语义优先（可用则 topK，否则回退关键词）
        sem_results: list[dict] = []
        try:
            sem_results = self.semantic.query(raw, topk=min(MAX_SHOW, 200), course_name=scope_course_name)
        except Exception:
            sem_results = []
        if sem_results:
            for r in sem_results:
                course_name = r.get("course_name") or ""
                q = r.get("q") or ""
                seg = r.get("seg") or ""
                cd = r.get("course_dir") or ""
                title = f"[{course_name}] {q}" if self.chk_global.isChecked() else q
                it = QListWidgetItem(title)
                it.setData(Qt.UserRole, (str(cd), seg))
                self.list_items.addItem(it)
            return

        # 回退关键词
        show = 0
        if self.chk_global.isChecked():
            for course_name, cd, q, seg, ql in self.global_index:
                if kw and kw not in self._normalize_query(ql):
                    continue
                it = QListWidgetItem(f"[{course_name}] {q}")
                it.setData(Qt.UserRole, (str(cd), seg))
                self.list_items.addItem(it)
                show += 1
                if show >= MAX_SHOW:
                    break
            return
        if not self.current_course_dir:
            return
        for q, seg, _ in self.items:
            if not q:
                continue
            if kw and kw not in self._normalize_query(q):
                continue
            it = QListWidgetItem(q)
            it.setData(Qt.UserRole, (str(self.current_course_dir), seg))
            self.list_items.addItem(it)
            show += 1
            if show >= MAX_SHOW:
                break

    def on_item_double_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if not data:
            return
        course_dir_str, seg = data
        course_dir = Path(course_dir_str)
        video_path = course_dir / "segments" / seg
        self._vlc_play_file(video_path)

    # ---------------- player ui ----------------
    def _on_slider_released(self):
        self._is_dragging_slider = False
        self._vlc_set_position_ms(self.slider_pos.value())

    def _on_slider_moved(self, v):
        if self._is_dragging_slider:
            self.lbl_time.setText(f"{self._fmt(v)} / {self._fmt(self.slider_pos.maximum())}")

    def _tick_player_ui(self):
        if not (self.vlc_ok and self.vlc_player is not None):
            return
        dur = self._vlc_get_duration_ms()
        pos = self._vlc_get_position_ms()
        if dur > 0:
            self.slider_pos.setRange(0, dur)
        if not self._is_dragging_slider:
            self.slider_pos.setValue(pos)
        self.lbl_time.setText(f"{self._fmt(pos)} / {self._fmt(dur)}")

    @staticmethod
    def _fmt(ms: int) -> str:
        s = (ms // 1000) if ms else 0
        m = s // 60
        s = s % 60
        return f"{m:02d}:{s:02d}"


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = StudentApp()
    w.show()
    sys.exit(app.exec_())
