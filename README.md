# PQLS-Lite
系统=离线课程包：字幕切片 + 全库搜索 + 播放
# PQLS-Lite

PQLS-Lite is an offline “course pack” workflow for learning from long videos:
**Teacher** cuts video into searchable segments with subtitles → exports a **Course Pack** → **Student** imports packs and searches across courses, then plays the matched segment.

## Screenshots

### Teacher (课程包制作端)
![Teacher GUI](docs/screenshots/teacher.png)

### Student (学习端)
![Student GUI](docs/screenshots/student.png)


PQLS-Lite 是一个离线“课程包”工作流：
**教师端**把“视频+字幕”切成可检索的小片段并导出课程包 → **学生端**导入多个课程包并全库搜索，点击即播放对应片段。

---

## Features / 特性

- Teacher-side course pack export (video segments + SQLite DB + manifest validation)
- Student-side import multiple course packs, global search, click-to-play
- Optional semantic search (Instructor-XL) as an enhancement module
- Offline-first, works well for classrooms / LAN / low-network environments

---

## Course Pack Structure / 课程包结构

<course_name>/
segments/
source/
course.db
questions.db
manifest.json
.pqls_meta.json (optional)

Student imports **only** valid course packs (manifest validation).

---

## Dependencies / 依赖

- Windows 10/11 + Python 3.10
- ffmpeg/ffprobe/ffplay under project root `bin/`
- VLC player installed (student-side embedded playback)

---

## Quick Start / 快速开始

### Teacher / 教师端
1) Put ffmpeg binaries into `bin/`
2) Run teacher GUI:

```powershell
cd teacher
python teacher_gui.py
Student / 学生端

Run student GUI:

cd student
python student_gui.py


First run will ask to choose a Course Library folder (e.g. Desktop\PQLS_Courses).
Index Rebuild / 索引重建（逻辑说明）

Index is a reproducible cache built from course packs.
After importing new course packs, rebuild the index to include new content in semantic search.

(Implementation is provided under student/nlp/.)
License

MIT (or your choice)


保存关闭。

---

## 提交 README 并推送（两行）
```powershell
git add README.md
git commit -m "docs: add README"
git push