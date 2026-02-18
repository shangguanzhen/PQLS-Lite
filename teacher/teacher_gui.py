import sys
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, font, ttk
import os

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from teacher.organize import (
    create_run,
    copy_to_source,
    build_segments,
    export_course_package,   # ✅ 新增：导出课程包（含 manifest）
)

COLORS = {
    "primary": "#E67E22",
    "primary_hover": "#D35400",
    "primary_light": "#F39C12",
    "secondary": "#34495E",
    "secondary_light": "#5D6D7E",
    "bg_main": "#F8F9FA",
    "bg_card": "#FFFFFF",
    "bg_input": "#FFFFFF",
    "text_dark": "#2C3E50",
    "text_light": "#7F8C8D",
    "text_white": "#FFFFFF",
    "border": "#E0E0E0",
    "border_focus": "#E67E22",
}


def get_desktop_dir() -> Path:
    """
    Windows 桌面路径（稳妥写法）
    优先 USERPROFILE/Desktop，其次 Path.home()/Desktop
    """
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        p = Path(userprofile) / "Desktop"
        if p.exists():
            return p
    p2 = Path.home() / "Desktop"
    return p2


class TeacherApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("教师端 · 课程资料整理工具")
        self.geometry("1000x650")
        self.resizable(False, False)
        self.configure(bg=COLORS["bg_main"])

        self.video_path = tk.StringVar()
        self.subtitle_path = tk.StringVar()

        # ✅ 输出目录：课程包导出根目录（默认桌面 PQLS_Courses）
        default_export_root = get_desktop_dir() / "PQLS_Courses"
        default_export_root.mkdir(parents=True, exist_ok=True)
        self.output_dir = tk.StringVar(value=str(default_export_root))

        self.progress_var = tk.IntVar(value=0)

        self._init_fonts()
        self._build_ui()

    def _init_fonts(self):
        self.font_title = font.Font(family="Microsoft YaHei UI", size=11, weight="bold")
        self.font_normal = font.Font(family="Microsoft YaHei UI", size=10)
        self.font_small = font.Font(family="Microsoft YaHei UI", size=9)
        self.font_button = font.Font(family="Microsoft YaHei UI", size=10, weight="bold")

    # =========================
    # UI 构建
    # =========================

    def _build_ui(self):
        main = tk.Frame(self, bg=COLORS["bg_main"])
        main.pack(fill="both", expand=True, padx=20, pady=20)

        self._create_file_section(main)
        self._create_action_section(main)
        self._create_bottom_section(main)

    def _create_file_section(self, parent):
        card = tk.Frame(parent, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        card.pack(fill="x", pady=(0, 15))

        inner = tk.Frame(card, bg=COLORS["bg_card"])
        inner.pack(fill="both", padx=20, pady=18)

        self._file_row(inner, 0, "📹 视频文件", self.video_path, self.select_video)
        self._file_row(inner, 1, "📝 字幕文件", self.subtitle_path, self.select_subtitle)
        self._file_row(inner, 2, "📦 导出目录", self.output_dir, self.select_output_dir)

        # 小提示
        tip = tk.Label(
            inner,
            text="提示：导出目录为“课程包输出根目录”（默认桌面 PQLS_Courses）。整理完成后会自动生成：课程名/segments/source/*.db/manifest.json",
            font=self.font_small,
            bg=COLORS["bg_card"],
            fg=COLORS["text_light"]
        )
        tip.grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def _file_row(self, parent, row, label, var, cmd):
        tk.Label(
            parent, text=label, font=self.font_normal, width=12, anchor="w",
            bg=COLORS["bg_card"], fg=COLORS["text_dark"]
        ).grid(row=row, column=0, padx=(0, 15), sticky="w")

        entry = tk.Entry(parent, textvariable=var, font=self.font_normal)
        entry.grid(row=row, column=1, sticky="ew", ipady=5, padx=(0, 10))

        tk.Button(parent, text="选择", width=8, command=cmd).grid(row=row, column=2)
        parent.grid_columnconfigure(1, weight=1)

    def _create_action_section(self, parent):
        frame = tk.Frame(parent, bg=COLORS["bg_main"])
        frame.pack(fill="x")

        self.start_button = tk.Button(
            frame, text="🚀 开始整理并导出课程包",
            font=self.font_button,
            bg=COLORS["primary"], fg=COLORS["text_white"],
            height=2, command=self.start_organize
        )
        self.start_button.pack(pady=(0, 6), ipadx=40)

        self.progress_bar = ttk.Progressbar(
            frame, orient="horizontal",
            length=420, mode="determinate",
            maximum=100, variable=self.progress_var
        )
        self.progress_bar.pack()

    def _create_bottom_section(self, parent):
        paned = tk.PanedWindow(
            parent,
            orient=tk.HORIZONTAL,
            sashwidth=6,
            sashrelief="raised",
            bg=COLORS["bg_main"]
        )
        paned.pack(fill="both", expand=True, pady=10)

        # ===== 左侧：日志 =====
        log_outer = tk.Frame(paned, bg=COLORS["bg_main"])

        log_header = tk.Frame(log_outer, bg=COLORS["bg_card"], height=36)
        log_header.pack(fill="x")
        log_header.pack_propagate(False)

        tk.Label(
            log_header,
            text="📋 运行日志",
            font=self.font_title,
            bg=COLORS["bg_card"],
            fg=COLORS["text_dark"]
        ).pack(side="left", padx=12, pady=6)

        log_body = tk.Frame(
            log_outer,
            bg=COLORS["bg_card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1
        )
        log_body.pack(fill="both", expand=True)

        self.log_box = scrolledtext.ScrolledText(
            log_body,
            font=self.font_small,
            bg="#FAFAFA",
            fg=COLORS["text_dark"],
            state="disabled",
            wrap="word",
            relief="flat",
            borderwidth=0
        )
        self.log_box.pack(fill="both", expand=True, padx=1, pady=1)

        # ===== 右侧：预览（导出后的 segments 列表）=====
        preview_outer = tk.Frame(paned, bg=COLORS["bg_main"])

        preview_header = tk.Frame(preview_outer, bg=COLORS["bg_card"], height=36)
        preview_header.pack(fill="x")
        preview_header.pack_propagate(False)

        tk.Label(
            preview_header,
            text="🎬 生成片段（导出课程包）",
            font=self.font_title,
            bg=COLORS["bg_card"],
            fg=COLORS["text_dark"]
        ).pack(side="left", padx=12, pady=6)

        preview_body = tk.Frame(
            preview_outer,
            bg=COLORS["bg_card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1
        )
        preview_body.pack(fill="both", expand=True)

        self.segment_list = tk.Listbox(
            preview_body,
            font=self.font_small,
            bg=COLORS["bg_card"],
            fg=COLORS["text_dark"],
            relief="flat",
            borderwidth=0,
            selectbackground=COLORS["primary_light"],
            selectforeground=COLORS["text_white"],
            activestyle="none"
        )
        self.segment_list.pack(fill="both", expand=True, padx=1, pady=1)

        paned.add(log_outer, minsize=300)
        paned.add(preview_outer, minsize=300)

    # =========================
    # 文件选择
    # =========================

    def select_video(self):
        p = filedialog.askopenfilename(filetypes=[("视频文件", "*.mp4 *.mkv *.avi")])
        if p:
            self.video_path.set(p)

    def select_subtitle(self):
        p = filedialog.askopenfilename(filetypes=[("字幕文件", "*.srt *.vtt")])
        if p:
            self.subtitle_path.set(p)

    def select_output_dir(self):
        p = filedialog.askdirectory(title="选择课程包导出根目录")
        if p:
            self.output_dir.set(p)

    # =========================
    # 核心流程
    # =========================

    def start_organize(self):
        if not self.video_path.get() or not self.subtitle_path.get():
            messagebox.showwarning("提示", "请先选择视频和字幕")
            return

        export_root = Path(self.output_dir.get()).expanduser()
        try:
            export_root.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("错误", f"导出目录不可用：{e}")
            return

        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", tk.END)
        self.log_box.configure(state="disabled")

        self.progress_var.set(0)
        self.segment_list.delete(0, tk.END)
        self.start_button.config(state="disabled")

        threading.Thread(target=self._run_organize, daemon=True).start()

    def _run_organize(self):
        try:
            video_in = Path(self.video_path.get())
            subtitle_in = Path(self.subtitle_path.get())
            export_root = Path(self.output_dir.get())

            # 课程名默认用视频名（去扩展名）
            course_name = video_in.stem

            self.log("创建整理批次（run）...")
            # ✅ run 继续走默认 data/runs，避免用户桌面产生中间碎片
            ctx = create_run(base_dir=None)
            self.log(f"run_id: {ctx.run_id}")
            self.log(f"run_dir: {ctx.run_dir}")

            self.log("拷贝源文件...")
            video, subtitle = copy_to_source(ctx, str(video_in), str(subtitle_in))

            self.log("开始按字幕切分视频...")
            build_segments(ctx, video, subtitle, progress_callback=self.update_progress)

            self.log("切分完成，开始导出课程包（含 manifest）...")
            out_dir = export_course_package(ctx, course_name=course_name, export_root=export_root)

            self.log("导出完成 ✔")
            self.log(f"课程包目录：{out_dir}")
            self.log(f"manifest.json：{out_dir / 'manifest.json'}")

            # 右侧列表展示导出后的 segments
            seg_dir = out_dir / "segments"
            for seg in sorted(seg_dir.glob("*.mp4")):
                self.segment_list.insert(tk.END, seg.name)

            messagebox.showinfo("完成", f"课程包已导出：\n{out_dir}")

        except Exception as e:
            self.log(f"❌ 错误：{e}")
            messagebox.showerror("错误", str(e))

        finally:
            self.after(0, self.start_button.config, {"state": "normal"})

    def update_progress(self, cur, total):
        self.after(0, self.progress_var.set, int(cur / total * 100))

    # =========================
    # 日志
    # =========================

    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert(tk.END, msg + "\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state="disabled")


if __name__ == "__main__":
    TeacherApp().mainloop()
