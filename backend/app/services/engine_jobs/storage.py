"""Transactional job/attempt state. Artifacts are committed separately and reconciled."""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

from tivelo_contracts.base import canonical_bytes

from .models import JobPlan, stages

TERMINAL = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
ACTIVE = frozenset({"queued", "running", "publishing", "cancelling"})

# Windows + WAL + 多进程下的 sqlite 竞态:
# engine worker 是 spawn 出来的独立进程, 父进程(uvicorn/pytest)同时在 drain 状态,
# 两边频繁开连接、取写锁。当一个进程正在 checkpoint 时, 另一个进程会**短暂**把库
# 判为只读, 抛 "attempt to write a readonly database" —— 不是文件权限问题, 也不是
# 永久损坏, 退避重试即可(实测 6 进程 x 600 次并发调用, 每进程撞 2~8 次, 全部自愈)。
# 这类错误一旦冒出去, 会被 worker 兜成 ENGINE_EXECUTION_FAILED, 表现为"任务失败但
# 看不到原因", 所以必须在存储层吃掉。
_TRANSIENT_SQLITE_MARKERS = (
    "readonly",
    "database is locked",
    "database table is locked",
    "disk i/o error",
)
_WRITE_ATTEMPTS = 6
_WRITE_BACKOFF_SECONDS = 0.03


def _transient_sqlite_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_SQLITE_MARKERS)


def connect_with_retry(database) -> sqlite3.Connection:
    """建立连接; `PRAGMA synchronous` 也会撞上瞬时只读, 同样退避重连。

    供 JobStore / ScheduleStore 等所有"会被多个进程同时打开"的库共用。
    """
    for attempt in range(_WRITE_ATTEMPTS):
        candidate = None
        try:
            candidate = sqlite3.connect(database, timeout=30, isolation_level=None)
            candidate.execute("PRAGMA synchronous=FULL")
            return candidate
        except sqlite3.OperationalError as exc:
            if candidate is not None:
                with suppress(Exception):
                    candidate.close()
            if not _transient_sqlite_error(exc) or attempt == _WRITE_ATTEMPTS - 1:
                raise
            time.sleep(_WRITE_BACKOFF_SECONDS * (2**attempt))
    raise AssertionError("unreachable")


def acquire_write_with_retry(database) -> sqlite3.Connection:
    """建立连接并取到写锁。

    readonly 是**连接级**判定(WAL 的 -shm 访问失败后, 该连接就一直认为库只读),
    对着同一条连接重试 BEGIN 不会自愈 —— 必须丢弃连接重来。这是与"锁忙"最大的
    区别, 也是这里单独抽出一个函数的原因。
    """
    for attempt in range(_WRITE_ATTEMPTS):
        connection = None
        try:
            connection = connect_with_retry(database)
            connection.execute("BEGIN IMMEDIATE")
            return connection
        except sqlite3.OperationalError as exc:
            if connection is not None:
                with suppress(Exception):
                    connection.close()
            if not _transient_sqlite_error(exc) or attempt == _WRITE_ATTEMPTS - 1:
                raise
            time.sleep(_WRITE_BACKOFF_SECONDS * (2**attempt))
    raise AssertionError("unreachable")


class JobError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def now():
    return datetime.now(UTC).isoformat()


class JobStore:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.root = self.data_dir
        for name in ("research", "engine"):
            self.root /= name
            if self.root.is_symlink():
                raise JobError("UNSAFE_PATH", "任务目录不能包含符号链接")
            self.root.mkdir(parents=True, exist_ok=True)
        for name in ("inputs", "jobs", "owner"):
            self.path(name).mkdir(exist_ok=True)
        self.database = self.path("jobs.sqlite3")
        with self.connection() as probe:
            version = probe.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise JobError("SCHEMA_UNSUPPORTED", "任务索引版本高于当前程序")
        # 已初始化的库: 只读探测后就返回。原来每次构造都重跑整套 DDL + 写锁,
        # 而 engine worker 是每个节点 spawn 一个进程、父进程同时在读写 —— 多个
        # 进程在同一瞬间抢 BEGIN IMMEDIATE, 就会出现"读写竞态把库判成只读"。
        # 把 DDL 收敛到"首次建库"这一条路径, 争用面直接消失。
        if version == 1:
            return
        # journal_mode 必须在事务外切换, 所以先单独设, 再取写锁建表。
        with self.connection() as setup:
            setup.execute("PRAGMA journal_mode=WAL")
        connection = self._acquire_write()
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                "id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, "
                "plan BLOB NOT NULL, state TEXT NOT NULL)"
            )
            # A downgraded worker must never take a job whose input format it cannot read.
            connection.execute(
                "CREATE TABLE IF NOT EXISTS pinned_jobs (id TEXT PRIMARY KEY, "
                "request_key TEXT UNIQUE NOT NULL, plan BLOB NOT NULL, state TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE VIEW IF NOT EXISTS job_catalog AS "
                "SELECT *,0 AS pinned FROM jobs UNION ALL SELECT *,1 AS pinned FROM pinned_jobs"
            )
            connection.execute(
                "CREATE TRIGGER IF NOT EXISTS pinned_job_reservations BEFORE INSERT ON jobs "
                "WHEN EXISTS(SELECT 1 FROM pinned_jobs) BEGIN "
                "SELECT CASE WHEN EXISTS(SELECT 1 FROM pinned_jobs WHERE request_key=NEW.request_key) "
                "THEN RAISE(ABORT,'job key reserved') WHEN (SELECT count(*) FROM job_catalog "
                "WHERE json_extract(state,'$.status') IN ('queued','running','publishing','cancelling'))>=128 "
                "THEN RAISE(ABORT,'job capacity') END; END"
            )
            connection.execute("PRAGMA user_version=1")
            connection.commit()
        finally:
            connection.close()

    def path(self, relative, *nested):
        from pydantic import TypeAdapter
        from tivelo_contracts.base import RelativePath

        validate = TypeAdapter(RelativePath).validate_python
        path = self.root
        if path.is_symlink():
            raise JobError("UNSAFE_PATH", "任务目录不能是符号链接")
        # Validate each independently declared path, including nested archive entries.
        for fragment in (relative, *nested):
            for part in validate(str(fragment)).split("/"):
                path /= part
                if path.is_symlink():
                    raise JobError("UNSAFE_PATH", "任务路径不能包含符号链接")
        return path

    def _connect(self):
        return connect_with_retry(self.database)

    def _acquire_write(self):
        return acquire_write_with_retry(self.database)

    @contextmanager
    def write(self):
        """写事务上下文: 取写锁(带重连重试), 退出时关闭连接。

        外部模块(price_variants / schedules)需要自己 BEGIN IMMEDIATE 时统一走这里,
        避免每处各抄一份重试逻辑。
        """
        connection = self._acquire_write()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def connection(self):
        # Connections are short lived and never shared across executor threads.
        self.path("jobs.sqlite3")
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, job_id):
        connection = self._acquire_write()
        try:
            row = connection.execute(
                "SELECT state,pinned FROM job_catalog WHERE id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise JobError("NOT_FOUND", "研究任务不存在")
            state = json.loads(row[0])
            try:
                yield state
                state["updated_at"] = now()
                table = "pinned_jobs" if row[1] else "jobs"
                connection.execute(
                    f"UPDATE {table} SET state=? WHERE id=?", (json.dumps(state), job_id)
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        finally:
            connection.close()

    def create(self, plan):
        payload = canonical_bytes(plan)
        if len(payload) > 4 * 1024**2:
            raise JobError("RESOURCE_LIMIT", "研究任务计划超过大小限制")
        identity = plan.plan_id
        created = now()
        state = {
            "job_id": identity,
            "plan_id": identity,
            "status": "queued",
            "created_at": created,
            "updated_at": created,
            "cancel_requested": False,
            "nodes": {
                name: {"status": "queued", "attempts": [], "artifact": None}
                for name in stages(plan)
            },
            "artifact": None,
        }
        connection = self._acquire_write()
        try:
            row = connection.execute(
                "SELECT id,plan,state FROM job_catalog WHERE request_key=?",
                (plan.request.idempotency_key,),
            ).fetchone()
            if row is not None:
                if bytes(row[1]) != payload:
                    raise JobError("DATA_CONFLICT", "相同请求键已绑定其他输入，请创建新请求")
                return json.loads(row[2])
            count = connection.execute(
                "SELECT count(*) FROM job_catalog WHERE json_extract(state,'$.status') IN ('queued','running','publishing','cancelling')"
            ).fetchone()[0]
            if count >= 128:
                raise JobError("RESOURCE_LIMIT", "研究任务等待队列已满")
            table = "pinned_jobs" if plan.plan_version == "1.5" else "jobs"
            connection.execute(
                f"INSERT INTO {table} VALUES (?,?,?,?)",
                (
                    identity,
                    plan.request.idempotency_key,
                    payload,
                    json.dumps(state),
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return state

    def get(self, job_id):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT state FROM job_catalog WHERE id=?", (job_id,)
            ).fetchone()
        if row is None:
            raise JobError("NOT_FOUND", "研究任务不存在")
        return json.loads(row[0])

    def plan(self, job_id):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT plan FROM job_catalog WHERE id=?", (job_id,)
            ).fetchone()
        if row is None:
            raise JobError("NOT_FOUND", "研究任务不存在")
        plan = JobPlan.model_validate_json(row[0])
        if plan.plan_id != job_id:
            raise JobError("ARTIFACT_CORRUPT", "研究计划指纹不一致")
        return plan

    def find_request(self, key):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT id FROM job_catalog WHERE request_key=?", (key,)
            ).fetchone()
        return None if row is None else self.plan(row[0])

    def list(self, *, limit=100, active=False):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid job list limit")
        with self.connection() as connection:
            # JSON filtering prevents a long history from hiding queued work.
            condition = (
                "WHERE json_extract(state,'$.status') IN ('queued','running','publishing','cancelling')"
                if active
                else ""
            )
            rows = connection.execute(
                f"SELECT state FROM job_catalog {condition} ORDER BY json_extract(state,'$.created_at') DESC, id LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def active_ids(self):
        # Dispatch overlap checks need identities, not every node's attempt history.
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id FROM job_catalog WHERE json_extract(state,'$.status') "
                "IN ('queued','running','publishing','cancelling') LIMIT 128"
            ).fetchall()
        return [row[0] for row in rows]

    def begin(self, job_id, node_id):
        plan = self.plan(job_id)
        _, _, dependencies = stages(plan)[node_id]
        with self.transaction(job_id) as state:
            node = state["nodes"][node_id]
            if (
                state["status"] not in ACTIVE
                or state["cancel_requested"]
                or node["status"] != "queued"
            ):
                raise JobError("STATE_CONFLICT", "研究节点当前不能执行")
            if any(state["nodes"][parent]["status"] != "succeeded" for parent in dependencies):
                raise JobError("STATE_CONFLICT", "研究节点的上游尚未成功")
            if len(node["attempts"]) >= plan.request.budget.max_attempts:
                raise JobError("RESOURCE_LIMIT", "研究节点重试次数已用完")
            attempt = {
                "number": len(node["attempts"]) + 1,
                "token": uuid.uuid4().hex,
                "status": "running",
                "started_at": now(),
                "finished_at": None,
                "progress": None,
                "error": None,
                "artifact": None,
            }
            node["attempts"].append(attempt)
            node["status"] = "running"
            state["status"] = "running"
        return attempt

    def current(self, job_id, node_id, token):
        state = self.get(job_id)
        node = state["nodes"][node_id]
        if (
            not node["attempts"]
            or node["attempts"][-1]["token"] != token
            or node["status"] not in {"running", "publishing", "cancelling"}
        ):
            raise JobError("STALE_ATTEMPT", "任务尝试已失效")
        return state, node["attempts"][-1]

    def progress(self, job_id, node_id, token, message):
        clean = {key: message[key] for key in ("done", "total", "phase") if key in message}
        if len(json.dumps(clean)) > 2048:
            return
        with self.transaction(job_id) as state:
            node = state["nodes"][node_id]
            attempt = node["attempts"][-1]
            if attempt["token"] != token or node["status"] not in {
                "running",
                "publishing",
                "cancelling",
            }:
                return
            attempt["progress"] = clean
            if clean.get("phase") == "publishing" and not state["cancel_requested"]:
                node["status"] = attempt["status"] = state["status"] = "publishing"

    def record_source_failure(self, job_id, node_id, token, error):
        with self.transaction(job_id) as state:
            node = state["nodes"][node_id]
            if not node["attempts"] or node["status"] != "running" or state["cancel_requested"]:
                return
            attempt = node["attempts"][-1]
            if attempt["token"] != token:
                return
            code = error.code.value
            if attempt.get("pending_error") in (None, "WORKER_INTERRUPTED", code):
                attempt["pending_error"] = code
                attempt["pending_source_error"] = {
                    "code": code,
                    "source_issues": [issue.model_dump(mode="json") for issue in error.issues],
                }

    def finish(self, job_id, node_id, token, status, *, artifact=None, error=None, metrics=None):
        if status not in TERMINAL:
            raise ValueError("invalid terminal status")
        with self.transaction(job_id) as state:
            node = state["nodes"][node_id]
            attempt = node["attempts"][-1]
            if attempt["token"] != token or node["status"] in TERMINAL:
                raise JobError("STALE_ATTEMPT", "任务尝试已失效")
            if status == "succeeded" and artifact is None:
                raise JobError("ARTIFACT_CORRUPT", "成功节点必须有已验证制品")
            node["status"] = attempt["status"] = status
            node["artifact"] = attempt["artifact"] = artifact
            source_error = attempt.pop("pending_source_error", None)
            if source_error and attempt.get("pending_error") == source_error["code"]:
                del attempt["pending_error"]
            if (
                source_error
                and status == "failed"
                and error
                and error["code"] == source_error["code"]
            ):
                error = {**error, "source_issues": source_error["source_issues"]}
            attempt["finished_at"], attempt["error"] = now(), error
            if metrics is not None:
                attempt["worker"] = metrics
            # The job is completed only after its final manifest is committed.
            state["status"] = "running" if status == "succeeded" else status

    def cancel(self, job_id):
        with self.transaction(job_id) as state:
            if state["status"] in TERMINAL:
                return state
            state["cancel_requested"] = True
            running = False
            for node in state["nodes"].values():
                if node["status"] == "queued":
                    node["status"] = "cancelled"
                elif node["status"] in {"running", "publishing", "cancelling"}:
                    running = True
            if all(node["status"] == "succeeded" for node in state["nodes"].values()):
                state["status"] = "publishing"
            else:
                state["status"] = "cancelling" if running else "cancelled"
        return self.get(job_id)

    def retry(self, job_id):
        plan = self.plan(job_id)
        with self.transaction(job_id) as state:
            if state["status"] not in {"failed", "cancelled", "interrupted"}:
                raise JobError("STATE_CONFLICT", "只有失败、取消或中断的任务可以重试")
            for node in state["nodes"].values():
                if node["status"] == "succeeded":
                    continue
                if len(node["attempts"]) >= plan.request.budget.max_attempts:
                    raise JobError("RESOURCE_LIMIT", "研究节点重试次数已用完")
                node["status"], node["artifact"] = "queued", None
            state["status"], state["cancel_requested"] = "queued", False
            state.pop("error", None)
        return self.get(job_id)

    def attempt_directory(self, job_id, node_id, number):
        # IDs are read from the validated plan, never interpolated from URL input.
        if (
            node_id not in stages(self.plan(job_id))
            or type(number) is not int
            or not 1 <= number <= 10
        ):
            raise JobError("STATE_CONFLICT", "无效的任务尝试")
        return self.path(f"jobs/{job_id}/{node_id}/{number}")
