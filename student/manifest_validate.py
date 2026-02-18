# student/manifest_validate.py
from __future__ import annotations
import json
import hashlib
from pathlib import Path

class ManifestError(RuntimeError):
    pass

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
        raise ManifestError("manifest.json 不存在")
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except Exception as e:
        raise ManifestError(f"manifest.json 解析失败：{e}")

def validate_course_dir(course_dir: Path) -> tuple[bool, str]:
    """
    严格校验：
    - manifest.json 必须存在且可解析
    - manifest.files 列表中每个文件：存在、size 一致、sha256 一致
    """
    course_dir = Path(course_dir)
    try:
        m = load_manifest(course_dir)
        files = m.get("files", [])
        if not isinstance(files, list) or not files:
            return False, "manifest.files 为空或格式错误"

        for item in files:
            rel = item.get("path")
            size = item.get("size")
            sha = item.get("sha256")

            if not rel or size is None or not sha:
                return False, f"manifest.files 项缺字段：{item}"

            fp = course_dir / rel
            if not fp.exists():
                return False, f"缺失文件：{rel}"

            real_size = fp.stat().st_size
            if int(real_size) != int(size):
                return False, f"文件大小不一致：{rel} (manifest={size}, real={real_size})"

            real_sha = sha256_file(fp)
            if real_sha.lower() != str(sha).lower():
                return False, f"哈希不一致：{rel}"

        return True, "OK"
    except ManifestError as e:
        return False, str(e)
    except Exception as e:
        return False, f"校验异常：{e}"
