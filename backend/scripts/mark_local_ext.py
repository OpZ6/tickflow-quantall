"""LOCAL-EXT 标记工具

给"本地改过、上游也有"的文件标出本地增强区块，让下次上游同步一眼看到
"哪些块是我的"，不用通读全文件。

设计要点（踩过的坑都在这里）
------------------------------
1. **自洽基线**：不依赖 `git diff` 的行号（HEAD 里已含标记，行号会错位），
   改为「先剥离标记取出干净文本 → 用 difflib 与 `git show <base>:<file>` 比较」。
   因此可以反复运行，结果幂等。
2. **只有 Python 插内联标记**：JSX 属性区里的 `//` 不是注释，插进去会破坏结构
   （已验证会插到 `aria-label` 与 `onClick` 之间）。TS/TSX 只进清单。
3. **只保证"插入点"安全**：标记插在区块首行之前、末行之后，只要这两处不在
   多行字符串里就安全；区块内部夹文档字符串没问题。
4. 每块插完都 `ast.parse` 校验，不合法就跳过（宁缺勿错）。

用法
----
    python backend/scripts/mark_local_ext.py            # 写入
    LOCAL_EXT_GAP=25 python backend/scripts/... --dry    # 试算区块数
"""

from __future__ import annotations

import ast
import difflib
import io
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path

BASE = os.environ.get("LOCAL_EXT_BASE", "v0.4.1")
REPO_ROOT = Path(__file__).resolve().parents[2]
GAP = int(os.environ.get("LOCAL_EXT_GAP", "40"))
TARGET_PREFIXES = ("backend/app/", "packages/", "frontend/src/")

PY_BEGIN = "# >>> LOCAL-EXT 本地增强, 上游同步时保护"
PY_END = "# <<< LOCAL-EXT"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    ).stdout


def base_text(path: str) -> str:
    return git("show", f"{BASE}:{path}")


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


def strip_markers(text: str) -> str:
    return "".join(
        ln
        for ln in text.splitlines(keepends=True)
        if not ln.lstrip().startswith((PY_BEGIN, PY_END))
    )


def added_ranges(clean: str, base: str) -> list[tuple[int, int]]:
    """干净文本里相对上游"新增/替换"的行区间（1-based，闭区间）。"""
    matcher = difflib.SequenceMatcher(None, base.splitlines(), clean.splitlines(), autojunk=False)
    ranges = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace") and j2 > j1:
            ranges.append((j1 + 1, j2))
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
    covered: set[int] = set()
    extra = getattr(tokenize, "FSTRING_MIDDLE", -1)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.STRING or tok.type == extra:
                covered.update(range(tok.start[0], tok.end[0] + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return covered


def safe_span(start: int, end: int, covered: set[int]) -> tuple[int, int] | None:
    first = next((ln for ln in range(start, end + 1) if ln not in covered), None)
    last = next((ln for ln in range(end, start - 1, -1) if ln not in covered), None)
    if first is None or last is None or last < first:
        return None
    return first, last


def mark_python(path: Path) -> tuple[int, list[str]]:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    clean = strip_markers(raw.decode("utf-8-sig"))
    base = base_text(path.as_posix())
    if not base:
        return 0, []

    lines = clean.splitlines(keepends=True)
    covered = string_lines(clean)
    skipped: list[str] = []
    targets: list[tuple[int, int]] = []
    for start, end in merge_ranges(added_ranges(clean, base)):
        span = safe_span(start, end, covered)
        if span:
            targets.append(span)
        else:
            skipped.append(f"{path}:{start}-{end} (整段落在字符串内)")

    marked = 0
    for start, end in reversed(sorted(targets)):
        if end > len(lines):
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
        lines = candidate
        marked += 1

    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + "".join(lines).encode("utf-8"))
    return marked, skipped


def main() -> int:
    os.chdir(REPO_ROOT)
    dry = "--dry" in sys.argv
    manifest: list[tuple[str, int, int]] = []
    hits = files = 0
    skipped_all: list[str] = []

    for name in modified_code_files():
        path = Path(name)
        if not path.exists():
            continue
        raw = path.read_bytes().decode("utf-8-sig")
        base = base_text(name)
        if not base:
            continue
        ranges = merge_ranges(added_ranges(strip_markers(raw), base))
        manifest.append((name, len(ranges), sum(b - a + 1 for a, b in ranges)))
        if path.suffix != ".py":
            continue
        if dry:
            hits += len(ranges)
            files += 1
            continue
        n, skipped = mark_python(path)
        skipped_all.extend(skipped)
        if n:
            hits += n
            files += 1

    if not dry:
        out = [
            "# 本地增强分布图（LOCAL-EXT 清单）",
            "",
            f"> 基线：上游 `{BASE}`。由 `backend/scripts/mark_local_ext.py` 生成，",
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

    print(f"\n{'[dry] ' if dry else ''}Python 标记: {files} 文件 / {hits} 区块")
    if skipped_all:
        print(f"跳过 {len(skipped_all)} 处:")
        for item in skipped_all[:10]:
            print("   ", item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
