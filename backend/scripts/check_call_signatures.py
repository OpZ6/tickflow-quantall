"""跨模块调用签名检查（上游同步后的静默 TypeError 哨兵）。

为什么需要它
------------
上游把模块搬家 / 拆分 / 抽进 `packages/` 时，常出现"函数签名在 A 处新增必填
参数，B 处的调用点没跟上"。这类问题 git 不会报冲突（两边改的不是同一行），
`tsc`/`ruff`/`compileall` 也都不报，只在真跑到那条路径时抛
`TypeError: missing required positional argument`；而引擎侧还会把异常吞成
`ENGINE_EXECUTION_FAILED`（只透错误码、不透堆栈），表现为"任务失败但看不到原因"。

用法
----
    cd backend && .venv/Scripts/python.exe scripts/check_call_signatures.py

退出码 0 = 无问题；1 = 有可疑调用点（逐条打印 file:line / 缺的参数 / 定义位置）。

判定口径
--------
- 只检查能静态解析到模块的调用：`from mod import name -> name(...)`、
  `import mod -> mod.name(...)`
- 跳过含 `*args` / `**kwargs` 的调用（无法静态判断，避免误报）
- 同名但不同模块的函数不会互相误判（按 import 解析作用域）
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND / "app"


def module_name(path: Path) -> str:
    rel = path.relative_to(BACKEND).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def collect(paths: list[Path]):
    defs: dict[tuple[str, str], tuple[int, list[str], int]] = {}
    trees: dict[Path, ast.Module] = {}
    for path in paths:
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        trees[path] = tree
        mod = module_name(path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                positional = [a.arg for a in args.posonlyargs + args.args]
                defaults = len(args.defaults)
                required = positional[: len(positional) - defaults]
                defs[(mod, node.name)] = (node.lineno, positional, len(required))
    return defs, trees


def find_problems(defs, trees) -> list[str]:
    problems: list[str] = []
    for path, tree in trees.items():
        imported: dict[str, tuple[str, str]] = {}
        modules: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                for a in node.names:
                    if a.name != "*":
                        imported[a.asname or a.name] = (node.module, a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        modules[a.asname] = a.name
                    else:
                        head = a.name.split(".")[0]
                        modules[head] = head
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if any(isinstance(x, ast.Starred) for x in node.args):
                continue
            if any(k.arg is None for k in node.keywords):
                continue
            if isinstance(node.func, ast.Name):
                hit = imported.get(node.func.id)
                if not hit:
                    continue
                mod, sym = hit
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                base = modules.get(node.func.value.id)
                if not base:
                    continue
                mod, sym = base, node.func.attr
            else:
                continue
            info = defs.get((mod, sym))
            if not info:
                continue
            def_line, positional, required = info
            given = {k.arg for k in node.keywords}
            missing = [p for p in positional[:required][len(node.args):] if p not in given]
            if missing:
                problems.append(
                    f"{path.relative_to(BACKEND)}:{node.lineno}  {sym}()  缺 {missing}"
                    f"   定义于 {mod}:{def_line}"
                )
    return sorted(problems)


def main() -> int:
    paths = sorted(ROOT.rglob("*.py"))
    if not paths:
        print(f"未找到 Python 源文件: {ROOT}")
        return 1
    defs, trees = collect(paths)
    problems = find_problems(defs, trees)
    for line in problems:
        print(line)
    print(f"\n检查 {len(trees)} 个文件 / {len(defs)} 个函数定义，可疑调用点 {len(problems)} 处")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
