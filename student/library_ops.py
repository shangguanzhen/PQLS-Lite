# student/library_ops.py
from __future__ import annotations
from pathlib import Path
import shutil
import json

from student.manifest_validate import validate_course_dir, load_manifest

def _safe_name(name: str) -> str:
    bad = '\\/:*?"<>|'
    for ch in bad:
        name = name.replace(ch, "")
    return name.strip() or "course"

def import_course_to_library(course_dir: Path, library_dir: Path) -> tuple[bool, str, Path | None]:
    """
    course_dir: 教师端导出的课程包目录（含 manifest.json）
    library_dir: 学生端课程库根目录
    返回：成功/失败、原因、导入后的课程目录
    """
    course_dir = Path(course_dir)
    library_dir = Path(library_dir)
    library_dir.mkdir(parents=True, exist_ok=True)

    ok, reason = validate_course_dir(course_dir)
    if not ok:
        return False, f"导入拒绝：{reason}", None

    m = load_manifest(course_dir)
    course_name = _safe_name(m.get("course_name") or course_dir.name)

    target = library_dir / course_name
    # 避免覆盖：重名则追加 (2)(3)...
    if target.exists():
        n = 2
        while True:
            t2 = library_dir / f"{course_name} ({n})"
            if not t2.exists():
                target = t2
                break
            n += 1

    shutil.copytree(course_dir, target)

    # 写一个本地标记：已校验通过（方便启动时快速列出）
    meta = {
        "course_name": course_name,
        "imported_from": str(course_dir.resolve()),
        "validated": True,
    }
    (target / ".pqls_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return True, "OK", target

def list_courses(library_dir: Path) -> list[Path]:
    """
    扫描课程库目录下的课程（包含 manifest.json 的子目录）
    """
    library_dir = Path(library_dir)
    if not library_dir.exists():
        return []
    out = []
    for p in sorted(library_dir.iterdir()):
        if p.is_dir() and (p / "manifest.json").exists():
            out.append(p)
    return out
