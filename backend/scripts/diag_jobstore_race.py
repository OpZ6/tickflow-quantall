"""复现 / 回归验证 JobStore 的多进程 sqlite 竞态。

背景: engine worker 是每个节点 spawn 出来的独立进程, 父进程同时在 drain 状态,
两边频繁 open 连接、取写锁。Windows + WAL 下 sqlite 会把库**短暂**判为只读,
抛 `attempt to write a readonly database`; 这个异常冒到 worker 里会被兜成
`ENGINE_EXECUTION_FAILED`, 表现为"研究任务失败但看不到原因"。

修复见 `app/services/engine_jobs/storage.py`:
  - `user_version==1` 时只读探测后直接返回, 不再每次取写锁重跑 DDL
  - 连接/写锁遇到 readonly 时丢弃连接重连(不是对同一连接重试)+ 退避

用法(在 backend 目录):
    .venv/Scripts/python.exe scripts/diag_jobstore_race.py
    PROCS=8 ROUNDS=500 .venv/Scripts/python.exe scripts/diag_jobstore_race.py

退出码: 0 = 无竞态错误; 1 = 出现残留错误(说明加固被上游覆盖了)。
"""

from __future__ import annotations

import multiprocessing as mp
import os
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.engine_jobs.storage import JobStore  # noqa: E402

ROUNDS = int(os.environ.get("ROUNDS", "300"))
PROCS = int(os.environ.get("PROCS", "6"))


def hammer(data_dir: str, proc_id: int, result_queue) -> None:
    errors: list[str] = []
    try:
        store = JobStore(data_dir)
        for i in range(ROUNDS):
            try:
                # 读路径(不该取写锁)
                with store.connection() as conn:
                    conn.execute("SELECT count(*) FROM jobs").fetchone()
                # 写路径(create/update 的实际路径)
                conn = store._acquire_write()
                try:
                    conn.execute("ROLLBACK")
                finally:
                    conn.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"[p{proc_id} r{i}] {type(exc).__name__}: {exc}")
                if len(errors) >= 3:
                    break
    except Exception:  # noqa: BLE001
        errors.append(f"[p{proc_id} init] {traceback.format_exc()[-400:]}")
    result_queue.put(errors)


def main() -> int:
    data_dir = tempfile.mkdtemp(prefix="jobstore-race-")
    JobStore(data_dir)  # 先建库, 让并发进程都走"已初始化"路径
    queue: mp.Queue = mp.Queue()
    workers = [mp.Process(target=hammer, args=(data_dir, i, queue)) for i in range(PROCS)]
    for worker in workers:
        worker.start()
    all_errors: list[str] = []
    for _ in workers:
        all_errors.extend(queue.get())
    for worker in workers:
        worker.join()

    calls = PROCS * ROUNDS * 2
    print(f"procs={PROCS} rounds={ROUNDS} calls={calls}")
    if all_errors:
        print(f"FAILED - {len(all_errors)} errors")
        for error in all_errors[:8]:
            print(" ", error)
        return 1
    print("OK - no readonly / lock errors")
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
