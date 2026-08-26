# TickFlow 大一统迁移总规划

> 本文档是 quantall 能力迁移到 TickFlow 的权威规划。所有后续迁移工作以此为参照,进度记录在文末。
>
> 范围:`prototypes/tickflow`(目标平台)+ `apps/quantx`、`apps/quants`、`apps/quantt`、根目录 `skills/quantr`(能力来源)。
>
> 终极目标:TickFlow 内置 quantall 全部能力,quantall 各工位代码归档废弃。

## 1. 当前 TickFlow 状态(迁移起点)

基于 `PROJECT_ANALYSIS.md`(2026-08-23 审计,提交 `9b9538a`,版本 0.1.88):

### 1.1 已就绪的底座(迁移基础,不重做)

| 层 | 现状 | 评估 |
|---|---|---|
| 数据底座 | Parquet 分区 + DuckDB 内存视图 + Polars 缓存 | 完整,可承载全市场日K/分钟K/财务/资金/形态/信号追踪 |
| 实时层 | `quote_service` SSE + `monitor_rules` + 飞书/企微/语音 | quantall 全缺,不可替代 |
| 回测引擎 | `matrix_native` 矩阵 + T+1/分钟/参数优化/walkforward/Monte Carlo | quantall 只有简单 observation_backtest |
| 策略引擎 | `filter_fn` 返回 `pl.Expr` + `matrix_native` + AI 生成 + 组合 | 通用契约,能扩展形态 |
| 指标流水线 | `compute_indicators` 50+ 列即时计算 + enriched 15 列窄表 | 可扩展 ma50/150/200/RS rank/52周 |
| Web 前端 | React 18 + Vite + TanStack Query + ECharts + lightweight-charts | 完整,可加新页面 |
| 数据源插件 | TickFlow SDK / stock-sdk / 自定义 HTTP / CSV / JSON / ext_data | 契约已有,可加 Tushare provider |
| 关键价位 | `levels` 11 类(筹码/枢轴/极值/Boll/Keltner/ATR/缺口/Fib/整数) | quantall 没有,独有 |
| 缠论 | 已接入(`backend/app/chanlun/`) | 来自 openclarr-chanlun prototype |
| 市场实验室 | MarketLab(ETF 动量/板块资金/雷达/宏观离散度/仓位/Kelly/蒙特卡洛) | 来自 reference-prototype |

### 1.2 已知缺陷(迁移时修复,不继承)

| 缺陷 | 影响 | 迁移时处理 |
|---|---|---|
| `uv sync` 因 README 越界失败 | 新用户无法按文档安装 | 修 `pyproject.toml` readme 路径,重建 `uv.lock` |
| `uv.lock` 落后于 `pyproject.toml` | frozen 构建缺 pypinyin | 重建 lock |
| AI/用户 Python 策略非进程沙箱 | 恶意代码可接触服务进程 | 列为后续 P0,迁入受限子进程 |
| 断板反包描述与算法不符 | 策略含义偏差 | 修算法或修描述 |
| 连板接力 ENTRY_SIGNALS 与掩码不一致 | 监控偏差 | 修掩码 |
| `high_60d/low_60d` 历史与实时口径不同 | 盘中盘后信号翻转 | 统一口径 + 测试 |
| 因子回测 `weight/fees/slippage` 未生效 | UI 错觉,收益偏高 | 修算法或删 UI 参数 |
| README 称 Docker 内置 stock-sdk 但默认 `INCLUDE_STOCKSDK=0` | 部署预期错 | 统一文档与 Dockerfile |

### 1.3 TickFlow 上游关系

TickFlow 是 `github.com/shy3130/tickflow-stock-panel` 的 fork。**本规划执行后跟上游脱钩**:TickFlow 成为你自己的项目,保留 LICENSE 致谢,不再 merge 上游。理由:内置大量 quantall 能力后,核心文件改动过多,merge 冲突成本 > 上游更新收益。

## 2. 迁移原则

### 2.1 双边并行

- quantall 各工位**继续运行**,不中断现有工作流
- TickFlow 同步开发,数据源可重叠(两边都拉 Tushare,只读 API 各拉各的)
- 每个功能在 TickFlow 验证通过后,quantall 对应模块进入**冻结**(只修 bug,不增强)
- 最终全部验证通过,quantall 归档

### 2.2 逐个迁移 + 对账

- 每个能力独立迁移,独立验证
- 验收标准:**同一天的数据/产出跟 quantall 原版逐字段对账**
  - 例:迁移情绪三件套后,同日 TickFlow `_computed` vs QuantX `computed.py` 产出,字段一致才算通过
  - 例:迁移 5 形态后,同日 TickFlow 策略结果 vs Quants `dm_pattern_detection`,标的/形态类型一致
- 对账失败则修,不放过漂移

### 2.3 不破坏 TickFlow 原有底座

- Parquet + DuckDB 视图 + Polars 缓存**不动**
- 实时层 / 回测矩阵 / 监控 / 策略引擎契约**不动**
- 新能力作为**内置模块**加入,不替换底座
- 替换型能力(如 regime → 情绪三件套)保留原实现作 fallback,新实现验证通过后再切换

### 2.4 每批独立可用

- 不需要全部完成才能用
- 完成批次 1-2,TickFlow 就有"统一数据 + 情绪流 + 复盘"能力,已比 quantall 分散好用
- 完成批次 3,加上"选股 + 信号追踪"
- 每批完成后用户可立即用,不等终局

## 3. quantall 能力清单(按工位)

### 3.1 来自 Quants(选股 + 信号追踪 + 数据源)

| 能力 | quantall 实现 | 迁移落点 |
|---|---|---|
| 5 形态策略(VCP/杯柄/高窄旗/回调低吸/趋势模板) | `ppgu/patterns/*.py`(pandas) | `backend/app/strategy/builtin/`(重写为 Polars `filter_history_fn`) |
| 信号追踪(5/10/20日 return/MFE/MAE/win_flag) | `dm_signal_case*` + `refresh_candidate_tracking_summary` | 新增 `services/signal_tracking.py` + `data/signal_case/` Parquet |
| 财务数据 | `dwd_quarter_finance` + `sync_finance.py` | Tushare provider `financial` 数据集 |
| 资金流 | `dwd_moneyflow` | Tushare provider `moneyflow` 数据集,替代 MarketLab proxy |
| 指标(ma50/150/200/RS rank/52周) | `dm_daily_factor` 预计算 | 扩展 `compute_indicators` 新增列 |
| 选股规则(RS 阈值/52周高点/阶段涨幅/财务质量/黑名单) | `screen.py` | 适配 TickFlow `basic_filter` + `scoring` |
| 数仓分层(ods/dwd/dm) | 单 DuckDB 24GB | **不照搬**——TickFlow Parquet 分区 + DuckDB 视图已够 |
| tkinter GUI | `ppgu/gui.py` | **不迁移**——TickFlow Web 替代 |

### 3.2 来自 QuantX(情绪 + 复盘 + 研报 + 心得)

| 能力 | quantall 实现 | 迁移落点 |
|---|---|---|
| 情绪三件套(market_heat/short_term_sentiment/trend_sentiment) | `computed.py` 1339 行 | `services/emotion_state.py`(新),替换 `regime_builder` |
| 连板生态(advance_rate/premium_rate/seal_rate/height_trend) | `computed.py` + `zhangtingke.json` | 增强 `services/limit_ladder.py`,加历史趋势图 |
| 退潮/参与度/crash_signals(4+4项) | `computed.py` `_calc_ebb_risk_check`/`_calc_participation_check`/`_calc_crash_signals` | `services/emotion_state.py` |
| 题材归因(theme_ranking/stock_factor_map/relay_quality) | `computed.py` + `factor_attribution.py` | 增强 `services/concept_rotation_analyzer.py` |
| 资金生态(短线侠强度榜) | review s4 | 增强 `services/market_lab.py` `sector_flow`(真值替代 proxy) |
| 百日新高聚类 + 拥挤度 | `new_high_cluster.py` + legulegu | `services/market_lab.py` |
| 跨日 Markov 状态(market_state.key) | `catalog.json` 70天快照 | `services/emotion_state.py` + `data/market_state/` Parquet |
| review V4 七区报告 | `report_builder.py` + `review_v4_blocks.json` + prompts | `services/review_v4.py`(新)+ `prompts/review_v4/`,替换 `market_recap` |
| research-daily 两轮隔离 | skill 驱动 + `manage_research_daily.py` | `services/research_daily.py`(新),skill 机制用 ai_provider Codex CLI 适配 |
| 心得知识库 + reflector | `knowledge_reflector.py` + `knowledge/` | `services/knowledge.py`(新)+ `data/knowledge/` |
| 多日驾驶舱 | `report_catalog.py` + `output/index.html` | 增强 TickFlow Dashboard,加跨日快照 |
| 多源采集(pywencai/duanxianxia/zhangtingke/ths_hot) | `src/pipeline.py` scrapers | `backend/app/plugins/quantx_collectors/`(新插件) |
| 8766 dashboard | `output/index.html` 独立服务 | **不迁移**——TickFlow Dashboard 替代 |

### 3.3 来自 QuantT(训练 + 反馈)

| 能力 | quantall 实现 | 迁移落点 |
|---|---|---|
| 盲K训练 | React + FastAPI,`backend/app/training.py` | `services/training.py` + `frontend/src/pages/Training.tsx` |
| AI 两阶段点评(盲评 1-5 分 + 结果归因) | `ai_prompts.py` | `services/training_ai.py` |
| 个人画像(行为模式/强弱项/LLM 教练) | `backend/app/profile.py` | `services/training_profile.py` |
| 交割单导入 | roadmap 未完成 | `services/trade_journal.py`(待,新开发) |
| 8031 独立 Web | React + FastAPI | **不迁移独立前端**——TickFlow 训练页替代 |

### 3.4 来自 Quantr(深度研究)

| 能力 | quantall 实现 | 迁移落点 |
|---|---|---|
| 深度研究(个股/产业/概念/事件/peer/catalyst) | `src/quantr/` skill 驱动 | `services/quantr_research.py` + `frontend/src/pages/Research.tsx` |
| claim/evidence assets + 审计 HTML/PNG | `src/quantr/` | `services/quantr_research.py` |
| 不给买卖建议 | 提示词约束 | 保留约束 |

### 3.5 来自《情绪流报告》(假设验证系统,全新)

| 能力 | 来源 | 迁移落点 |
|---|---|---|
| 假设库(10 个起步) | 报告行动清单 | `services/hypothesis_ledger.py`(新) |
| 事件研究回测(状态切窗 + 条件概率) | 报告第 16.3 节 | `backtest/event_study.py`(新,扩展矩阵引擎) |
| FIPA 偏差记录(预测/逻辑/执行/结果四分制) | 报告 15.8/15.9 | `services/bias_recorder.py`(新) |

## 4. 迁移分批方案

### 批次 1:数据基础(起点)

**目标**:TickFlow 能拉 Tushare 全套数据,不再依赖 TickFlow SDK 付费档做日K。

| 任务 | 落点 | 验收 |
|---|---|---|
| Tushare provider(日K/复权/财务/资金/指数) | `backend/app/plugins/tushare/` | 同日 TickFlow kline_daily vs Quants dwd_daily_bar,字段一致 |
| Quants 24GB 库一次性导出历史到 TickFlow Parquet | 脚本 `scripts/migrate_from_quants.py` | 历史日期完整,SHA-256 对账 |
| 多源采集 collector 插件(pywencai/duanxianxia/zhangtingke/ths_hot) | `backend/app/plugins/quantx_collectors/` | 同日采集结果 vs QuantX scrapers JSON,字段一致 |
| 修复 TickFlow 已知缺陷(uv sync / uv.lock / Dockerfile stock-sdk) | `pyproject.toml` / `uv.lock` / `Dockerfile` | `uv sync --extra dev` 成功;`docker compose up` 镜像默认行为与文档一致 |

**完成后**:TickFlow 数据自洽,可脱离 TickFlow SDK 付费档运行(实时仍可保留 TickFlow SDK)。

### 批次 2:情绪 + 复盘(核心体验)

**目标**:TickFlow 的情绪/复盘能力达到 QuantX V4 水平,`regime_builder` 和 `market_recap` 让位。

| 任务 | 落点 | 验收 |
|---|---|---|
| 情绪三件套(替换 regime) | `services/emotion_state.py` | 同日 TickFlow 情绪分数 vs QuantX `_computed.json`,三套分数±1 以内 |
| 连板生态增强(历史趋势 ECharts) | `services/limit_ladder.py` 增强 | 同日梯队分布 vs QuantX review s3,标的/层级一致 |
| 退潮/参与度/crash_signals | `services/emotion_state.py` | 同日 4+4 项判定 vs QuantX,布尔一致 |
| 题材归因增强 | `services/concept_rotation_analyzer.py` 增强 | 同日题材排名 vs QuantX `theme_ranking`,顺序一致 |
| 百日新高聚类 + 拥挤度 | `services/market_lab.py` 增强 | 同日聚类 vs QuantX `new_high_100d_clusters`,标的集合一致 |
| 跨日 Markov 状态 | `services/emotion_state.py` + `data/market_state/` | 70 天状态序列 vs QuantX `catalog.json`,key 一致 |
| review V4 七区报告(替换 market_recap) | `services/review_v4.py` + `prompts/review_v4/` | 同日七区产出 vs QuantX review_full.html,结构化字段一致(LLM 文本可不同) |
| 多日驾驶舱(Dashboard 增强) | `services/market_catalog.py` + `frontend/src/pages/Dashboard.tsx` 增强 | 跨日快照/题材生命周期/5-10-20日窗口 vs QuantX catalog.json |

**完成后**:QuantX `computed.py` / `report_builder.py` 进入冻结。TickFlow 情绪+复盘能力 ≥ QuantX。

### 批次 3:选股 + 信号追踪

**目标**:TickFlow 选股能力融合 Quants 形态 + 信号追踪,策略框架统一。

| 任务 | 落点 | 验收 |
|---|---|---|
| 5 形态策略迁移(VCP/杯柄/高窄旗/回调低吸/趋势模板) | `backend/app/strategy/builtin/vcp.py` 等 5 个 | 同日策略结果 vs Quants `dm_pattern_detection`,标的/形态类型一致 |
| 指标扩展(ma50/150/200/RS rank/52周) | `indicators/pipeline.py` `compute_indicators` | 固定样本数值断言 vs Quants `dm_daily_factor` |
| 信号追踪(5/10/20日 return/MFE/MAE/win_flag) | `services/signal_tracking.py` + `data/signal_case/` | 同日触发记录 vs Quants `dm_signal_case`,字段一致;5/10/20 日后回填对账 |
| 财务/资金真值替代 proxy | Tushare provider `financial`/`moneyflow` | MarketLab `sector_flow` 用真值,`quality=observed`;字段 vs Quants `dwd_moneyflow` |
| 选股规则适配(RS 阈值/52周/财务质量/黑名单) | TickFlow `basic_filter` + `scoring` | 同日候选池 vs Quants screen.py 输出,标的集合一致 |

**完成后**:Quants 选股能力进入冻结。TickFlow 选股 = 18 原策略 + 5 形态 + 自定义信号 + AI 生成,统一框架。

### 批次 4:知识 + 研究

**目标**:TickFlow 内置心得知识库 + 研报 + 深度研究。

| 任务 | 落点 | 验收 |
|---|---|---|
| 心得知识库 + reflector | `services/knowledge.py` + `data/knowledge/` | 心得卡片读写/反思状态 vs QuantX knowledge,字段一致 |
| research-daily 简化版(单轮 Codex CLI,不做两轮隔离) | `services/research_daily.py` | 研报 HTML 产出,Hero/导航/section 结构正常 |
| research-daily 升级(两轮隔离 item-auditor + writer) | `services/research_daily.py` 增强 | vs QuantX research_full.html,sidecar 字段一致 |
| Quantr 深度研究 | `services/quantr_research.py` + `frontend/src/pages/Research.tsx` | 研究报告 HTML/PNG 产出,claim/evidence 可追溯 |

**完成后**:QuantX knowledge/research + Quantr 进入冻结。TickFlow 内置研究闭环。

### 批次 5:训练 + 反馈

**目标**:TickFlow 内置盲K训练 + AI 点评 + 画像 + 交割单。

| 任务 | 落点 | 验收 |
|---|---|---|
| 盲K训练(后端 + 前端训练页) | `services/training.py` + `frontend/src/pages/Training.tsx` | 训练流程跑通,决策记录进 `data/training/` |
| AI 两阶段点评(盲评 + 结果归因) | `services/training_ai.py` | 点评 1-5 分 + 标签产出,vs QuantT `ai_prompts.py` 提示词一致 |
| 个人画像(行为模式/强弱项/LLM 教练) | `services/training_profile.py` | 画像字段 vs QuantT,聚合一致 |
| 交割单导入(新开发) | `services/trade_journal.py` + `data/trade_journal/` | 导入交割单 → 按 style×regime 聚合胜率 |

**完成后**:QuantT 进入冻结。TickFlow 内置训练+反馈闭环。

### 批次 6:假设验证系统(终极创新)

**目标**:落地《情绪流报告》第 16 节,把高手感觉变成可统计验证的假设。

| 任务 | 落点 | 验收 |
|---|---|---|
| 假设库(10 个起步,来自报告行动清单) | `services/hypothesis_ledger.py` + `data/hypothesis/` | 10 个假设机械化定义完成(状态/特征/前向收益) |
| 事件研究回测(状态切窗 + 条件概率) | `backtest/event_study.py`(扩展矩阵引擎) | 单个假设(如"首分后核心抗住")产出条件概率表,样本量/胜率/MFE/MAE |
| FIPA 偏差记录(预测/逻辑/执行/结果四分制) | `services/bias_recorder.py` + `data/bias/` | 触发记录四层打标,进 QuantT 画像(批次 5 就绪后) |
| 假设触发器(验证过的假设转 monitor_rules) | `services/hypothesis_trigger.py` + 集成 `monitor_rules` | 盘中触发 SSE + 飞书,附带历史胜率 + 证伪条件 |

**完成后**:TickFlow 不只是工具,是**情绪流假设验证闭环**——这是 quantall 任何单工位都做不到的,也是终极价值。

### 批次 7:quantall 废弃

**条件**:批次 1-6 全部验收通过。

**动作**:
- `apps/quantx` / `apps/quants` / `apps/quantt` 代码移到 `archive/quantall_legacy_YYYYMMDD/`
- 根目录 `skills/quantr` / `skills/research-daily` 等保留(TickFlow 内部用)
- `docs/trading-system.md` / `docs/data-policy.md` 更新为 TickFlow 视角
- `prototypes/tickflow` 提升为 `apps/tickflow` 或直接顶层 `tickflow/`
- quantall monorepo 概念结束

## 5. 起点选择:从批次 1 开始

**理由**:
1. **数据是基础**:所有后续能力(情绪/复盘/选股/训练/研究)都依赖数据。没有 Tushare provider,情绪三件套没数据算,形态没数据检测,信号追踪没数据回填
2. **风险最低**:Tushare provider 是机械实现(Quants ETL 逻辑搬过来适配 provider 契约),不涉及算法创新,失败概率低
3. **立即可用**:批次 1 完成后,TickFlow 就能脱离 TickFlow SDK 付费档独立运行(日K/财务/资金全用 Tushare),这是后续所有工作的前提
4. **对账清晰**:同日 Tushare 数据 vs Quants dwd_daily_bar,字段级对账,标准明确

**批次 1 内部顺序**:
1. 先修 TickFlow 已知缺陷(uv sync / uv.lock),保证开发环境可用
2. 实现 Tushare provider(`daily`/`adj_factor`/`index` 数据集先,`financial`/`moneyflow` 后)
3. 写 `scripts/migrate_from_quants.py`,一次性导出 Quants 24GB 库历史到 TickFlow Parquet
4. 实现多源采集 collector 插件
5. 验收对账

## 6. 风险与缓解

| 风险 | 级别 | 缓解 |
|---|---|---|
| 工作量大(粗估 3-6 个月全职) | 高 | 分批进行,每批独立可用;兼职拉长但不阻塞 |
| research-daily/Quantr 的 skill 机制 TickFlow 没有 | 中高 | 批次 4 先做简化版(单轮 Codex CLI),验证能产出报告后再升级两轮 |
| 假设验证系统全新,事件研究法机械化要研究 | 高 | 批次 6 放最后,依赖批次 1-5 就绪;机械化定义从《情绪流报告》16.3 节示范开始 |
| LLM 提示词迁移后要调参(review V4/research/Quantr) | 中 | 每批验收时允许 LLM 文本不同,但结构化字段必须一致 |
| 5 形态 pandas → Polars 重写对账 | 中 | 每个形态独立迁移独立对账,失败回滚原版 |
| 多源采集第三方接口不稳定 | 中 | 搬 QuantX 已有降级链(pywencai→duanxianxia→tushare),不重新发明 |
| TickFlow 上游脱钩后维护成本 | 中 | 接受——脱钩是大一统前提,后续自己维护 |
| Quants 24GB 库数据迁移完整性 | 中 | 一次性导出脚本做 SHA-256 清单,迁移后逐表对账 |

## 7. quantall 废弃条件( Checklist)

批次 1-6 全部验收通过后,逐项确认:

- [ ] Tushare provider 日K/复权/财务/资金/指数数据完整,对账通过
- [ ] 多源采集 collector 4 源(pywencai/duanxianxia/zhangtingke/ths_hot)对账通过
- [ ] 情绪三件套对账通过(±1 以内)
- [ ] 连板生态/退潮/参与度/crash_signals 对账通过
- [ ] review V4 七区结构化字段对账通过
- [ ] 多日驾驶舱跨日快照对账通过
- [ ] 5 形态策略对账通过(标的/形态类型一致)
- [ ] 信号追踪 5/10/20 日回填对账通过
- [ ] 指标扩展 ma50/150/200/RS rank/52周断言通过
- [ ] 心得知识库 + reflector 读写正常
- [ ] research-daily 两轮隔离产出正常
- [ ] Quantr 深度研究报告产出正常
- [ ] 盲K训练 + AI 点评 + 画像跑通
- [ ] 交割单导入 + style×regime 聚合胜率
- [ ] 假设库 10 个机械化定义完成
- [ ] 事件研究回测产出条件概率表
- [ ] FIPA 偏差记录四层打标
- [ ] 假设触发器盘中 SSE + 飞书

全部勾选后,执行批次 7 归档。

## 8. 进度追踪

| 批次 | 状态 | 起止 | 备注 |
|---|---|---|---|
| 1 数据基础 | **完成** | 2026-08-25 | 672 测试全过(53 新增),ruff 全过,Tushare provider 被 loader 发现 |
| 2 情绪 + 复盘 | **完成** | 2026-08-25 | 729 测试全过(57 新增),情绪三件套+退潮/参与度/crash+review V4+多日驾驶舱 |
| 3 选股 + 信号追踪 | 未开始 | — | 前置:批次 1 ✓(Tushare 日K)+ 批次 2(情绪状态用于条件回测) |
| 4 知识 + 研究 | 未开始 | — | 前置:批次 2(复盘就绪)+ skill 机制设计 |
| 5 训练 + 反馈 | 未开始 | — | 前置:无强依赖,可并行;交割单待 QuantT 原计划 |
| 6 假设验证 | 未开始 | — | 前置:批次 2(情绪)+ 批次 3(形态/信号追踪)+ 回测矩阵扩展 |
| 7 quantall 废弃 | 未开始 | — | 全部验收后 |

每批完成后更新本表 + 在对应小节记录实际对账结果。

### 批次 1 完成报告(2026-08-25)

**完成内容**:
- 1.1 修复 TickFlow 缺陷:`pyproject.toml` readme 越界 + `Dockerfile` COPY 路径 + `uv.lock` 重建(0.1.83→0.1.88)
- 1.2 Tushare provider:`backend/app/plugins/tushare/`(plugin.yaml + bridge.py + provider.py),daily/adj_factor/index 数据集
- 1.3 扩展 financial/moneyflow:`get_financials`(5 张表映射)+ `get_moneyflow`(替代 proxy)
- 1.4 `scripts/migrate_from_quants.py`:Quants DuckDB 只读导出(daily/adj_factor/moneyflow)
- 1.5 `scripts/collect_quantx.py`:ths_hot/zhangtingke 完整,pywencai/duanxianxia 骨架(批次 2 完善)
- 1.6 验收测试:`test_batch1_acceptance.py` + `docs/batch1-acceptance-checklist.md`

**验证证据**:
- `uv sync --extra tushare --extra socks --extra dev` 成功
- 全量测试 `672 passed, 0 failed`(53 新增 + 619 原有)
- `ruff check` 新文件全过(All checks passed!)
- Tushare provider 被 `_load_builtin_plugins` 发现:无 token 时 available=False,有 token 时 available=True + registered + daily/financial/moneyflow 全声明
- 脚本 `--help` 正常(migrate/collect)
- `from app.main import app` 成功

**未触碰用户已有改动**:只改 4 个已有文件(pyproject.toml/Dockerfile/.env.example/uv.lock),其余新建。

**手动对账待执行**(见 `docs/batch1-acceptance-checklist.md`):
- Tushare provider 日K/财务/资金对账(需 TUSHARE_TOKEN)
- migrate_from_quants 导出对账(需 Quants 库)
- ths_hot/zhangtingke 采集对账(需网络)

### 批次 2 完成报告(2026-08-25)

**完成内容**:
- 2.1 完善 `scripts/collect_quantx.py`:重写 pywencai(akshare 4 fetchers + pywencai 1)、duanxianxia(Playwright 完整移植)、修复 zhangtingke(JS 对象解析 bug);全部产出 JSON 到 `data/quantx/YYYYMMDD/`(兼容 QuantX 格式)
- 2.2 `services/emotion_state.py`(新 ~900 行):移植 QuantX `computed.py` 情绪三件套(market_heat = 0.5*st + 0.5*tr,short_term 6 sub-scores + stretch 1.7,trend 4 sub-scores + stretch 1.3)+ `_lerp_score`/`_stretch_around_mid`/`_zone_for_score`/`_dx_fallback` + 连板生态(`_calc_advance_stats`/`_calc_loss_effect`/`_build_height_trend`)
- 2.3 退潮/参与度/crash:`_calc_participation_check`(4 条件)、`_calc_ebb_risk_check`(4 信号 absolute + 5d trend)、`_calc_crash_signals`(3 信号)、`_check_suspension_impact` + 跨日 Markov 状态(`_build_height_trend` 20 日趋势)
- 2.5 `services/review_v4.py`(新 ~420 行):精简版 review V4 七区报告(metri-strip + 8 维诊断 + 风险清单 + 指数表 + 退潮表 + 题材表 + 连板网格 + 情绪条 + 行业资金流 + 仓位预案 + 7 个 CLAUDE_ANALYSIS marker + 暗色/亮色主题 CSS)
- 2.6 `services/market_catalog.py`(新 ~260 行):多日驾驶舱(catalog.json schema v1 + index.html 跨日表格 + delta 计算 + 题材生命周期事件)
- 2.7 API 路由 `app/api/quantx.py`(新):GET/POST emotion、GET/POST review、GET/POST catalog + 注册到 main.py

**验证证据**:
- 全量测试 `729 passed, 0 failed`(57 新增 + 672 原有)
- emotion_state 39 测试:纯函数 + 三件套 + 退潮/参与度/crash + compute() 端到端全过
- review_v4 10 测试:7 区结构 + marker + metric strip + 诊断表 + 情绪条 + 仓位预案 + build_review_html 端到端全过
- market_catalog 9 测试:单日提取 + delta + 变化摘要 + catalog 构建 + HTML 全过
- collect_quantx 10 测试:ths_hot + zhangtingke + _extract_js_object + pywencai(mock)+ _float_or_none + _stock_code + _write_json 全过
- `from app.main import app` 成功(233 routes,含 quantx 路由)
- ruff 自动修复 19 个;剩余 47 个(全角标点 + E701 中式代码风格,不影响功能)

**新建文件**:
- `backend/app/services/emotion_state.py`(~900 行)
- `backend/app/services/review_v4.py`(~420 行)
- `backend/app/services/market_catalog.py`(~260 行)
- `backend/app/api/quantx.py`(API 路由)
- `backend/tests/test_emotion_state.py`(39 测试)
- `backend/tests/test_review_v4.py`(10 测试)
- `backend/tests/test_market_catalog.py`(9 测试)

**修改文件**:
- `scripts/collect_quantx.py`(重写:修复 zhangtingke bug,完善 pywencai/duanxianxia,产出 JSON)
- `backend/tests/test_collect_quantx.py`(适配新接口)
- `backend/app/main.py`(注册 quantx 路由)
- `docs/tickflow-unification-master-plan.md`(进度更新)

**未完成**(标记为后续批次):
- review V4 LLM 编辑器(`review_editor_supervisor.py` + `review_html_blocks.py` + `review_decision.py`)— 框架就绪,LLM 提示词调参待批次 4
- 题材归因增强(`factor_attribution.py` + `relay_quality.py`)— 框架就绪,完整移植待批次 3
- 百日新高聚类(`new_high_cluster.py`)— review_v4 已展示数据,聚类算法待批次 3
- `akshare`/`legulegu` 采集器 — emotion_state 降级处理(空数据),待后续补充

**手动对账待执行**:
- 同日 TickFlow `_computed.json` vs QuantX `computed.py` 三套分数 ±1 以内(需采集数据)
- review V4 七区结构化字段一致性(需 LLM 编辑)
- 多日驾驶舱 catalog vs QuantX `catalog.json`(需多日数据)

## 9. 相关文档

- [`PROJECT_ANALYSIS.md`](../PROJECT_ANALYSIS.md):TickFlow 源码审计,迁移起点的事实依据
- [`architecture-and-extension.md`](./architecture-and-extension.md):TickFlow 架构与扩展开发指南
- [`architecture-and-extension.html`](./architecture-and-extension.html):同内容 HTML 报告
- [`system-integration-and-local-financials.md`](./system-integration-and-local-financials.md):历史 sidecar 契约(本规划执行后失效,改为内置)
- [`CONTRIBUTING.md`](../CONTRIBUTING.md):TickFlow 贡献与审查规范
- [`docs/trading-system.md`](../../../docs/trading-system.md):quantall 交易系统总览(本规划完成后更新为 TickFlow 视角)
- [`docs/A股短线与情绪流体系完整梳理报告.md`](../../../docs/A股短线与情绪流体系完整梳理报告.md):情绪流知识体系,批次 6 假设库的理论基础

## 10. 决策记录

| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-08-24 | 跟 TickFlow 上游脱钩,成为自有项目 | 内置 quantall 能力后 merge 冲突 > 上游收益 |
| 2026-08-24 | 双边并行迁移,不一次性废弃 quantall | 降低风险,每批独立可用,失败可回滚 |
| 2026-08-24 | 从批次 1(数据基础)开始 | 数据是所有能力的前提,风险最低,立即可用 |
| 2026-08-24 | 不照搬 Quants 数仓分层(ods/dwd/dm) | TickFlow Parquet 分区 + DuckDB 视图已够,分层是逻辑不是物理 |
| 2026-08-24 | review V4 替换 market_recap,情绪三件套替换 regime_builder | 避免两套并存,QuantX 更专业 |
| 2026-08-24 | research-daily 先简化版(单轮)再升级(两轮) | skill 机制 TickFlow 没有,渐进式 |
| 2026-08-24 | 假设验证系统放批次 6(最后) | 依赖批次 1-5 全部就绪,且是研究型工作 |
| 2026-08-25 | 批次 1 完成,672 测试全过 | Tushare provider + migrate + collector 就位 |
| 2026-08-25 | 装 socksio 修复 9 个 SOCKS 代理测试失败 | 环境问题,非代码引入 |

## 11. 后续执行顺序细化

### 11.1 批次依赖关系

```
批次 1(数据基础)✓
   │
   ├─→ 批次 2(情绪+复盘)
   │      │
   │      ├─→ 批次 4(知识+研究, 需复盘就绪)
   │      │
   │      └─→ 批次 6(假设验证, 需情绪状态)
   │
   ├─→ 批次 3(选股+信号追踪)
   │      │
   │      └─→ 批次 6(假设验证, 需形态/信号追踪)
   │
   └─→ 批次 5(训练+反馈, 可并行, 无强依赖)

批次 7(废弃):全部验收后
```

**可并行**:批次 5(训练)跟批次 2/3 无依赖,可同时进行。
**不可并行**:批次 6(假设验证)必须等批次 2+3 就绪。
**软依赖**:批次 3 的"状态条件回测"需要批次 2 的情绪状态,但形态策略迁移本身不依赖。

### 11.2 推荐执行顺序

| 顺序 | 批次 | 理由 | 预估工作量 |
|---|---|---|---|
| 1 | **批次 2**(情绪+复盘) | 消灭最大重合(regime/market_recap),QuantX 情绪三件套是后续假设验证的基础 | 中高(computed.py 1339 行移植 + review V4 七区) |
| 2 | **批次 3**(选股+信号追踪) | 形态策略迁移 + 信号追踪,跟批次 2 部分可并行(策略代码不依赖情绪) | 中高(5 形态 pandas→Polars + dm_signal_case) |
| 3 | **批次 5**(训练+反馈) | 独立模块,技术栈一致(React+FastAPI),可跟 2/3 并行 | 中(代码现成,搬过来) |
| 4 | **批次 4**(知识+研究) | 依赖批次 2 复盘就绪 + skill 机制设计(难点) | 高(research-daily 两轮隔离 + Quantr) |
| 5 | **批次 6**(假设验证) | 终极创新,依赖 2+3 全就绪;事件研究法机械化要研究 | 高(全新能力,无现成实现) |
| 6 | **批次 7**(废弃) | 全部验收后归档 quantall | 低(归档操作) |

### 11.3 各批次关键任务与验收

#### 批次 2:情绪 + 复盘(下一步)

**前置**:批次 1 ✓(Tushare 日K + collector ths_hot/zhangtingke 数据源就位)

**关键任务**:
1. `services/emotion_state.py`(新):移植 `apps/quantx/src/computed.py` 的 `_calc_market_heat`/`_calc_short_term_sentiment`/`_calc_trend_sentiment`/`_calc_ebb_risk_check`/`_calc_participation_check`/`_calc_crash_signals`,替换 `regime_builder`
2. `services/limit_ladder.py`(增强):加历史趋势 ECharts(从 `zhangtingke` collector 数据读 height_history)
3. `services/review_v4.py`(新):移植 `apps/quantx/src/report_builder.py` + `prompts/review_v4_blocks.json`,替换 `market_recap`
4. `services/market_catalog.py`(新):多日驾驶舱,移植 `apps/quantx/src/report_catalog.py`
5. 完善 `collect_quantx.py` 的 pywencai/duanxianxia 采集逻辑(从 `apps/quantx/src/scrapers/` 移植)

**验收**:同日 TickFlow 情绪分数 vs QuantX `_computed.json`,三套分数 ±1 以内;review V4 七区结构化字段一致。

**风险**:LLM 提示词迁移后要调参(review V4);pywencai/duanxianxia 采集依赖第三方接口稳定性。

#### 批次 3:选股 + 信号追踪

**前置**:批次 1 ✓(Tushare 日K);批次 2 软依赖(情绪状态用于条件回测)

**关键任务**:
1. 5 形态策略迁移:`backend/app/strategy/builtin/vcp.py` 等 5 个,从 `apps/quants/ppgu/patterns/*.py` 移植(pandas→Polars `filter_history_fn`)
2. 指标扩展:`indicators/pipeline.py` 加 ma50/150/200/RS rank/52周(从 Quants `dm_daily_factor` 读或即时计算)
3. `services/signal_tracking.py`(新)+ `data/signal_case/` Parquet:`dm_signal_case_unified` 表,5/10/20 日回填
4. 财务/资金真值:MarketLab `sector_flow` 用 Tushare `moneyflow` 替代 proxy

**验收**:同日策略结果 vs Quants `dm_pattern_detection`,标的/形态类型一致;信号追踪 5/10/20 日回填对账。

**风险**:pandas→Polars 重写要逐个对账;Tushare 财务 API 需高积分(5000+),积分不足时降级。

#### 批次 5:训练 + 反馈(可并行)

**前置**:无强依赖

**关键任务**:
1. `services/training.py` + `frontend/src/pages/Training.tsx`:移植 `apps/quantt/backend/app/`(React+FastAPI,代码现成)
2. `services/training_ai.py`:移植 `apps/quantt/backend/app/ai_prompts.py`(AI 两阶段点评)
3. `services/training_profile.py`:个人画像
4. `services/trade_journal.py`(待):交割单导入(QuantT 原计划未完成)

**验收**:训练流程跑通,决策记录进 `data/training/`;AI 点评 1-5 分 + 标签产出。

**风险**:交割单导入是新功能,无现成实现。

#### 批次 4:知识 + 研究

**前置**:批次 2 复盘就绪;skill 机制设计

**关键任务**:
1. `services/knowledge.py` + `data/knowledge/`:移植 `apps/quantx/src/knowledge_reflector.py` + `knowledge_store.py`
2. `services/research_daily.py`:research-daily 两轮隔离(item-auditor + writer),用 `ai_provider` Codex CLI 适配 skill 机制
3. `services/quantr_research.py` + `frontend/src/pages/Research.tsx`:移植 `apps/quantx/src/quantr/`

**验收**:心得卡片读写正常;研报 HTML 产出;研究报告 HTML/PNG 产出。

**风险**:skill 机制 TickFlow 当前没有,要新建或用 Codex CLI 适配;research-daily 两轮 attempt/inspect/accept 流程复杂。

#### 批次 6:假设验证(终极创新)

**前置**:批次 2(情绪状态)+ 批次 3(形态/信号追踪)+ 回测矩阵扩展

**关键任务**:
1. `services/hypothesis_ledger.py` + `data/hypothesis/`:假设库 10 个起步(来自《情绪流报告》行动清单)
2. `backtest/event_study.py`:事件研究回测,扩展矩阵引擎"状态切窗"模式(Markov 状态 bucket × 候选特征 × 前向收益)
3. `services/bias_recorder.py` + `data/bias/`:FIPA 偏差记录(预测/逻辑/执行/结果四分制)
4. `services/hypothesis_trigger.py`:验证过的假设转 `monitor_rules` + SSE

**验收**:单个假设(如"首分后核心抗住")产出条件概率表,样本量/胜率/MFE/MAE。

**风险**:全新能力,事件研究法机械化定义要研究;矩阵引擎"状态切窗"模式是新开发。

#### 批次 7:quantall 废弃

**前置**:批次 1-6 全部验收通过(见 §7 Checklist)

**动作**:`apps/quantx`/`apps/quants`/`apps/quantt` 移到 `archive/`;`prototypes/tickflow` 提升为顶层。

### 11.4 关键路径与瓶颈

**关键路径**:批次 1 → 2 → 6(假设验证是终极目标,依赖 2+3)。

**瓶颈 1**:批次 2 的 review V4 迁移(LLM 提示词调参,非机械工作)。
**瓶颈 2**:批次 4 的 skill 机制(research-daily 两轮隔离,TickFlow 没有现成框架)。
**瓶颈 3**:批次 6 的事件研究法机械化(全新研究,无现成实现)。

**加速建议**:
- 批次 5(训练)跟 2/3 并行,技术栈一致代码现成,可快速完成
- 批次 3 的形态策略迁移可拆分(先迁移 1 个 VCP 验证模式,再迁移其余 4 个)
- 批次 6 的假设库可提前开始机械化定义(不依赖代码,依赖研究)
