"""LOCAL-EXT 标记工具（降债步骤 1）

目标: 让"下次上游同步"一眼看出哪些代码是本地的。

策略:
- Python: 在本地新增区块前后插入 `# >>> LOCAL-EXT` / `# <<< LOCAL-EXT`。
  每插一块都 ast.parse 校验, 并先用 tokenize 排除落在字符串/文档字符串里的区间
  (那样插进去会污染字符串内容却仍然能解析通过)。
- TS/TSX: **不插内联标记**。JSX 属性区里 `//` 不是注释, 会直接破坏结构;
  改为全部记进 docs/local-ext-map.md 清单。
"""

from __future__ import annotations

import ast
import io
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path

BASE = os.environ.get("LOCAL_EXT_BASE", "v0.4.1")
PY_BEGIN = "# >>> LOCAL-EXT 本地增强, 上游同步时保护"
PY_END = "# <<< LOCAL-EXT"
GAP = 10
TARGET_PREFIXES = ("backend/app/", "packages/", "frontend/src/")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    ).stdout


def modified_code_files() -> list[str]:
    out = []
    for line in git("diff", "--name-status", BASE, "HEAD").splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or parts[0] != "M":
            continue
        p = parts[-1]
        if p.startswith(TARGET_PREFIXES) and "__pycache__" not in p and p.endswith(
            (".py", ".ts", ".tsx")
        ):
            out.append(p)
    return out


def added_ranges(path: str) -> list[tuple[int, int]]:
    ranges = []
    for line in git("diff", "-U0", BASE, "HEAD", "--", path).splitlines():
        m = re.match(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", line)
        if not m:
            continue
        start, count = int(m.group(1)), int(m.group(2) or 1)
        if count > 0:
            ranges.append((start, start + count - 1))
    return ranges


def merge_ranges(ranges: list[tuple[int, int]], gap: int = GAP) -> list[tuple[int, int]]:
    if not ranges:
        return []
    merged = [list(ranges[0])]
    for start, end in ranges[1:]:
        if start - merged[-1][1] - 1 <= gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def string_lines(source: str) -> set[int]:
    """字符串字面量覆盖的所有行号（含三引号块）。"""
    covered: set[int] = set()
    extra = getattr(tokenize, "FSTRING_MIDDLE", -1)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.STRING or tok.type == extra:
                for ln in range(tok.start[0], tok.end[0] + 1):
                    covered.add(ln)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return covered


def read(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8-sig"), bom


def write(path: Path, text: str, bom: bool) -> None:
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))


def split_out_strings(start: int, end: int, covered: set[int]) -> list[tuple[int, int]]:
    """把 [start,end] 按"落在字符串里"的行切开, 返回可标记的子段。"""
    segments: list[tuple[int, int]] = []
    run_start: int | None = None
    for ln in range(start, end + 1):
        if ln in covered:
            if run_start is not None and ln - run_start >= 1:
                segments.append((run_start, ln - 1))
            run_start = None
        elif run_start is None:
            run_start = ln
    if run_start is not None and end - run_start + 1 >= 1:
        segments.append((run_start, end))
    return segments


def mark_python(path: Path) -> tuple[int, list[str]]:
    ranges = merge_ranges(added_ranges(str(path)))
    if not ranges:
        return 0, []
    text, bom = read(path)
    original = text
    skipped: list[str] = []
    marked = 0

    # 先按字符串边界切成可安全插入的子段, 再自下而上插标记。
    targets: list[tuple[int, int]] = []
    covered = string_lines(text)
    for start, end in ranges:
        segments = split_out_strings(start, end, covered)
        if segments:
            targets.extend(segments)
        else:
            skipped.append(f"{path}:{start}-{end} (整段在字符串内或过短)")

    for start, end in reversed(sorted(targets)):
        lines = text.splitlines(keepends=True)
        if end > len(lines):
            continue
        if PY_BEGIN in "".join(lines[start - 1:end]):
            continue
        indent = re.match(r"[ \t]*", lines[start - 1]).group(0)
        candidate = (
            lines[: start - 1]
            + [f"{indent}{PY_BEGIN}\n"]
            + lines[start - 1:end]
            + [f"{indent}{PY_END}\n"]
            + lines[end:]
        )
        try:
            ast.parse("".join(candidate))
        except SyntaxError:
            skipped.append(f"{path}:{start}-{end} (插入后语法不合法)")
            continue
        text = "".join(candidate)
        marked += 1
    if marked:
        write(path, text, bom)
    elif text != original:
        write(path, original, bom)
    return marked, skipped


def main() -> int:
    dry = "--dry" in sys.argv
    files = modified_code_files()
    py_hits = 0
    py_files = 0
    skipped_all: list[str] = []
    manifest: list[tuple[str, int, int]] = []

    for f in files:
        p = Path(f)
        if not p.exists():
            continue
        ranges = merge_ranges(added_ranges(f))
        manifest.append((f, len(ranges), sum(b - a + 1 for a, b in ranges)))
        if p.suffix != ".py":
            continue
        if dry:
            n = len(ranges)
        else:
            n, skipped = mark_python(p)
            skipped_all.extend(skipped)
        if n:
            py_hits += n
            py_files += 1

    if not dry:
        out = [
            "# 本地增强分布图（LOCAL-EXT 清单）",
            "",
            f"> 基线：上游 `{BASE}`。由 `git diff {BASE} HEAD` 自动生成，",
            "> 用于下次同步时快速定位「这个文件里哪些区块是我们的」。",
            ">",
            "> Python 文件已插入 `# >>> LOCAL-EXT` / `# <<< LOCAL-EXT` 内联标记；",
            "> TS/TSX **不插内联标记**（JSX 属性区里的 `//` 不是注释，会破坏结构），以本清单为准。",
            "",
            f"共 {len(manifest)} 个双方都改过的源码文件。",
            "",
            "| 文件 | 本地区块数 | 本地新增行 |",
            "|---|---|---|",
        ]
        for name, blocks, added in sorted(manifest, key=lambda x: -x[2]):
            out.append(f"| `{name}` | {blocks} | {added} |")
        out.append("")
        Path("docs/local-ext-map.md").write_text("\n".join(out), encoding="utf-8")
        print("已写入 docs/local-ext-map.md")

    print(f"\n{'[dry] ' if dry else ''}Python 标记: {py_files} 文件 / {py_hits} 区块")
    if skipped_all:
        print(f"跳过 {len(skipped_all)} 处:")
        for s in skipped_all[:20]:
            print("   ", s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
