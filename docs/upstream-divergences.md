# 与上游 v0.4.1 的语义分歧登记表

> 用途：下次同步时，如果冲突/失败出现在下表的任何一处，**先确认它是不是"故意的"**，
> 不要当 bug 去修，也不要把上游写法直接盖回来。
>
> 表内每一处都在对应测试函数上打了 `# LOCAL-DIVERGENCE: <原因>` 标记，
> 用 `grep -rn "LOCAL-DIVERGENCE" backend/tests` 可列出全部。

## 一、真正的行为分歧（5 类，9 个用例）

| # | 分歧点 | 上游行为 | 本地行为 | 为什么本地这么定 | 锁定用例 |
|---|---|---|---|---|---|
| 1 | 入场信号过期规则 | T+1 开盘若无 bar，信号**顺延**到下一根可用 bar（`entry=[0,0,1]`） | 下一交易日无 bar 即**作废**（`entry=[0,1,0]`） | 顺延等于用未来信息填补停牌，会制造不可成交的交易 | `backtest/test_market_matrix.py::test_open_t_plus_one_signal_expires_when_next_market_session_bar_is_missing` |
| 2 | 停牌占位与缺 bar | 只有真实缺 bar 才算吃掉信号 | **缺失 bar 与停牌占位（volume=0）都算** | 两种形态对撮合是一回事，不能只处理一种 | `backtest/test_market_matrix.py::test_missing_bar_and_suspension_placeholder_both_consume_entry_signal` |
| 3 | 日K中间空洞的修补方式 | 当作"增量补新日期"（`new_dates_only=True`、`symbols=None`） | 当作**向后延伸**重建，滚动指标从一致的历史重算 | 只补空洞会让空洞之后的滚动指标（MA/N 日新高）继续用断裂历史 | `test_enriched_partial_partition.py::test_pruned_interior_date_is_rebuilt_without_new_daily_or_factors` |
| 4 | 日K全量失败时的返回 | 静默返回 `written=0`（调用方以为成功） | **fail-closed**：抛 `RuntimeError("日K同步失败")`，同时 `failed_out` 仍透出失败标的 | "显示成功实则全空"会把问题推迟到下游，排查代价极高 | `test_kline_sync_failed_out.py::test_accepts_failed_out_and_surfaces_failed_symbols` |
| 5 | 实时行情的记录字段 | 记录只有原始字段 | 每条实时记录额外带 `source` 字段 | 多源优先级链下要能追溯这条行情来自哪个源 | `test_custom_provider_indices.py::test_custom_provider_without_indices_protocol_is_silent` 等 3 条 |
| 6 | 分钟回补天数上限 | 30 天 | **1095 天** | 本地需要长区间分钟回补做形态验证 | `test_minute_range_api.py::test_sync_minute_single_rejects_invalid_days` |

> 第 4 条是**本地比上游更严格**，不存在"上游更好"的可能；合并时若上游改了这块，
> 用本地的 fail-closed 语义去适配，而不是回退。

## 二、非分歧（只是本地整理，合并时可直接取上游）

这些文件与上游有 diff，但**不是语义分歧**，纯粹是本地把写法整理得更稳。
下次冲突时优先取上游，再补回整理：

| 文件 | 本地做了什么 |
|---|---|
| `backtest/test_matrix_strategy.py` | 把硬编码 `"v*-*"` 换成 `f"v{_DIRECT_MATRIX_LOADER_VERSION}-*"`，缓存版本号变化时断言不再假失败 |
| `test_screener_etf.py` | 上游锁死 `len(matrix_strategies) == 25`，本地改为只校验契约不校验数量（策略会持续增加） |
| `test_capability_augment.py` / `test_capability_matrix.py` | 桩函数签名随本地 API 调整 |
| `test_abnormal_moves.py` / `test_atomic_write_retry.py` / `test_regime_builder.py` / `test_strategy_required_history.py` / `test_enriched_range_warming_guard.py` / `test_enriched_partial_partition.py` | 仅 import 位置整理，断言未变 |
| `test_custom_depth_provider.py` / `test_ext_pull_auth.py` / `test_minute_timezone_contract.py` / `test_price_limits.py` / `test_repository_index.py` / `test_legacy_upgrade_degrade.py` | 夹具/桩数据的形状调整，断言未变 |

## 三、跨平台稳定性加固（上游实现，本地必须保住）

这几处**不是语义分歧**，是上游在 Linux 上没暴露、Windows 上会直接把节点打挂的实现细节。
合并时如果上游重写了这些文件，**必须把加固重新贴回去**，否则引擎作业会重新变成"随机失败"。

| 文件 | 上游写法 | 本地加固 | 为什么 | 验证方式 |
|---|---|---|---|---|
| `app/services/engine_jobs/storage.py` | 每次 `JobStore()` 都 `BEGIN IMMEDIATE` 重跑整套 DDL；`sqlite3.OperationalError` 直接向上抛 | ①`user_version==1` 时只读探测后直接返回，不再取写锁；②连接与写锁遇 `readonly/locked` 时**丢弃连接重连**并退避重试（readonly 是连接级判定，对同一连接重试无效） | engine worker 是每个节点 spawn 一个进程，父进程同时 drain 状态；多进程同一瞬间抢写锁，Windows + WAL 下会把库短暂判为只读，异常冒到 worker 被兜成 `ENGINE_EXECUTION_FAILED` | `backend/scripts/diag_jobstore_race.py` 8 进程 × 500 轮 × 读写 = 4000 次调用零错误；`test_engine_extension_fields.py` 2 条最重用例由 `1 failed` 变为 `2 passed` |
| `app/services/engine_jobs/worker.py` | `except` 里 `traceback` 硬编码空串；`finally` 里直接 `os._exit(0)` | ①`TF_WORKER_FAULTHANDLER=<path>` 时把完整栈与 faulthandler 现场落盘（默认行为不变，仍不向 IPC/API 泄露异常文本）；②`os._exit` 前 `watcher.join(timeout=2)` | 崩溃只有 `ENGINE_EXECUTION_FAILED` 六个字时完全无法排查；watcher 线程每 0.5s 停在 psutil 原生调用里，直接 `os._exit` 会在 Windows 上触发 access violation（退出码 3221225477），manager 据此误判节点异常 | faulthandler 实测抓到 `storage.py:93` 的真实栈；修复后崩溃点收敛到退出路径，节点状态判定恢复正常 |

**排障开关用法**（不设即完全不影响生产路径）：

```bash
TF_WORKER_FAULTHANDLER=D:/tmp/worker.log .venv/Scripts/python.exe -m pytest tests/test_engine_jobs.py
# 引擎作业报"失败但无原因"时，先开这个再复现，栈就落在 D:/tmp/worker.log
```

---

## 四、怎么用这张表

1. 同步前：`grep -rn "LOCAL-DIVERGENCE" backend/tests` 拿到全部锚点
2. 合并中出现冲突：先查本表，命中 → 保住本地语义，再让上游的新增断言适配
3. 合并后跑测试：本表列出的用例若失败 → 说明本地语义被覆盖了，按"本地行为"列修正实现
4. 新增分歧：**同时**更新本表 + 在用例上打 `# LOCAL-DIVERGENCE` 标记，否则下次没人记得
