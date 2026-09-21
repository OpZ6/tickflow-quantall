# 股票池正式实现与运行说明

状态：已实现。静态原型仅保留为产品讨论记录；正式运行入口为 `/stock-pools`。

## 产品边界

股票池用于盘后压缩注意力。九个召回器回答“为什么值得查看”，`primary_stage`回答“当前处于什么状态”，题材聚合帮助先选方向再看股票。候选、阶段和层级不构成自动买卖指令。

基础过滤固定为总市值20—3000亿元、成交额不少于1亿元、换手率不少于1%，并排除当日可识别的ST。市值和展示价使用原始价格，技术形态使用连续复权序列，当日涨跌幅使用原始收盘价相对前一交易日原始收盘价。

## 已实现调用链

```text
行情 Provider -> KlineRepository / enriched
网页事实 -> SourceManager -> SourceSnapshotStore -> Market Facts
已发布 Research -> ResearchMaterialRepository
ext_data 静态成分 -> load_security_memberships
       \             |                    /
        -> app.stock_pools 确定性计算 -> 日期级原子快照
                                      -> FastAPI
                                      -> React /stock-pools
```

正式业务不读取研究账本、`data/quantx/<date>/*.json`、外部Quantall目录或原型输入。`legacy_scrapers`只在SourceManager后方执行，API、股票池Service和前端不导入采集器。

主要代码：

- `backend/app/stock_pools/rules.py`：九个版本化召回器、基础过滤、来源事件、主阶段和层级。
- `backend/app/stock_pools/topics.py`：题材关键词归并、展示层级和行业显示规则（确定性，不改召回）。
- `backend/app/stock_pools/service.py`：当日交易逻辑题材、静态成分、Research、跨日变化和日期汇总。
- `backend/app/stock_pools/publisher.py`：同日单写者、manifest、校验后原子替换。
- `backend/app/stock_pools/repository.py`：日期快照只读接口。
- `backend/app/api/stock_pools.py`：目录、汇总、筛选列表、详情和重算接口。
- `frontend/src/custom/stock_pools/`：平级导航和正式页面。

## 九个召回来源

| ID | 名称 | 召回条件摘要 | 页面阶段 |
| --- | --- | --- | --- |
| `breakthrough` | 突破 | 60/100/250日收盘或盘中新高，锚点未失守，保留最多10个交易日 | 突破启动 |
| `limit_ladder` | 涨停 | 当日真实涨停梯队事实 | 涨停强化 |
| `abnormal_surge` | 异动 | 新跨越10日30%、30日50%或3日15%加速 | 异动加速 |
| `liquidity_trend` | 趋势 | 成交额前200、`close > MA20 > MA60`、MA20向上且距20日高点不超15% | 趋势延续 |
| `divergence` | 分歧 | 首/二板后1—3日，非涨停、守事件低点且上部收盘 | 高位分歧 |
| `failed_limit_repair` | 炸板修复 | 炸板后1—3日，守低点、收涨、上部收盘且缩量 | 企稳修复 |
| `trend_pullback` | 趋势回踩 | 突破后5—20日、MA60上、缩量触及并收回MA10/20 | 回踩整理 |
| `active_character` | 股性活跃 | 近10日涨停或30日多次涨停，守最近事件低点和MA20 | 活跃观察 |
| `popularity_warm` | 人气中温 | 任一可信来源排名20—100 | 人气观察 |

同股多来源合并为一条候选。来源不丢失，主阶段按版本化优先级唯一确定。核心层级由跨来源事件组合产生，只用于工作台排序。

## 题材数据模型

正式版把 Demo 的两层题材拆开，不再混在同一个`topics`字段里：

- **当日交易逻辑层**：`stock_logic_evidence_daily`逐股保存涨停梯队解读、同花顺热点理由、同花顺异动解读和热榜解读的原文、来源和观察时间；`app/stock_pools/topic_cluster.py`从来源专属`match_text`抽取术语，先归入`topics.py`的既有题材标签（同义合并），再按股票集合Jaccard（`shared>=2`且`jaccard>=0.3`）凝聚聚类，只保留至少两只成员的组，产出候选`topics`和逐条`topic_evidence`。每个聚类同时输出`subgroups`：把并入该组的原始术语按别名等价合并成"细分方向"（如光互联下的共封装光学(CPO)／光通信／光纤概念／光模块），供工作台展示和筛选。热点启动视图使用这一层；`topics.py`保留为同义标签表和Research索引的题材提取器，规则表不再直接决定热点聚类。
- **可选LLM归一化**：`settings.stock_pool_topic_llm`（环境变量`STOCK_POOL_TOPIC_LLM`）默认关闭；开启且已配置AI Key时，每次发布把聚类标签、术语和样例交给模型做别名合并与噪声剔除，模型不改成员归属；结果写入`summary.json`的`topic_normalization`并在同日重算时复用，调用失败降级回确定性标签并记录`llm-fallback`。
- **静态成分层**：`ext_data`的同花顺概念、一级行业、二级行业和属性通过`load_security_memberships`读取，附到候选`memberships`，并按“具体主题优先、行业显示规则其次、涨停与事件聚集度”确定`primary_concept`。趋势低吸视图使用`primary_concept`聚类，一只股票只贡献一个默认组。
- 静态成分是最新快照代理，不是历史时点归属；页面和汇总元数据都明确标注。两层都保留原始归属，不改变九池召回、阶段和排序。

同花顺异动接口只返回当日快照：日常流水线在交易日自动采集`fuyao_anomaly`来源；历史日期用`scripts/import_fuyao_anomaly_snapshot.py`导入冻结响应，导入同时把快照写回`quantx/<date>/normalized/`，供离线`--recompute`复用。热榜解读与异动解读是同一上游分析：同股同文时只保留异动行；异动来源缺失或未覆盖该股时保留热榜行并标记`is_fallback`，详情抽屉显示“降级材料”。

## 页面用法

正式页面只有两个顶层视图：

1. **今日工作台**：先选择热点启动或趋势低吸视角，再选择题材，随后查看该题材的五区九阶段分布、成员和跨题材事件队列。
2. **完整候选**：查看九来源卡、全部候选、变化状态和组合筛选。点击任意股票打开详情抽屉，检查来源事件、锚点、题材证据及目标日前已发布Research材料。

个人“待看／已看／忽略”状态保存在浏览器localStorage，只影响本机注意力管理，不修改服务端候选。

## API

```text
GET  /api/stock-pools
GET  /api/stock-pools/{YYYYMMDD}
GET  /api/stock-pools/{YYYYMMDD}/candidates
GET  /api/stock-pools/{YYYYMMDD}/candidates/{symbol}
POST /api/stock-pools/runs
```

候选列表支持`source`、`stage`、`topic`、`tier`、`change`和`q`筛选。缺少日期快照返回404；指定日期重算没有enriched数据或已有同日写入者时返回409。

## 数据更新与恢复

手动`POST /api/pipeline/run`与盘后定时任务共用以下顺序：行情和enriched完成，QuantX/Market Facts发布，股票池发布。主调度器另注册17:45恢复任务：若最新交易日没有可读股票池快照，则从已发布Repository输入重建。

单独重算：

```powershell
Invoke-RestMethod -Method Post -ContentType 'application/json' `
  -Body '{"trade_date":"20260914"}' `
  http://127.0.0.1:8000/api/stock-pools/runs
```

实时人气接口只能采集上海时区当天。历史快照必须显式导入：

```powershell
backend/.venv/Scripts/python.exe scripts/import_security_popularity_snapshot.py `
  --date 20260914 --input <当日冻结快照.json>
backend/.venv/Scripts/python.exe scripts/import_fuyao_anomaly_snapshot.py `
  --date 20260914 --input <当日冻结异动响应.json>
```

两个导入脚本都会把来源快照写回`quantx/<date>/normalized/`，因此后续离线`--recompute`会复用冻结快照而不是发布空分区。

Research索引由TickFlow自己维护：`app/research_materials/smnc.py`增量轮询绝参网（`smnc.juecan.com`）并写入`data/research/items.json`；`app/research_materials/builder.py`把SMNC条目按确定性规则提取公司名（instruments精确匹配，带内容哈希缓存）和题材标签（复用`app/stock_pools/topics.py`），与已审计发布合并（同一item以审计版优先）。股票池发布前`refresh_if_configured`先更新SMNC再重建索引；网络被拦截时保留本地条目并降级，不阻断发布。

采集器依赖`http://smnc.juecan.com`（仅HTTP）。本地网络按分类拦截该站点时，需要在代理中把`juecan.com`路由到远端节点；本机已在Clash Verge的当前订阅profile与运行时配置中加入`DOMAIN-SUFFIX,juecan.com,漏网兜底`（订阅重新下载后需重新添加）。拦截时`update_items`返回`blocked_or_redirected`并在日志中提示，本地条目不受影响。

手动重建索引：

```powershell
backend/.venv/Scripts/python.exe scripts/build_research_material_index.py `
  --research-dir data/research --data-dir data
```

人气、题材或Research缺失时，页面展示对应`unavailable`/降级状态；其余可用召回继续发布。历史页面不使用目标日之后的Research材料，也不以当前实时热榜回填过去。

## 快照契约

路径为`data/stock_pools/date=YYYY-MM-DD/`，包含：

- `summary.json`：规则版本、输入generation、来源质量、九来源和阶段统计、题材聚类（含`subgroups`细分方向）、`topic_normalization`（聚类模式、规则、LLM别名与剔除记录）及跨日变化。
- `candidates.json`：每股一行的紧凑列表。
- `details.json`：来源事件、锚点、题材证据及Research材料。
- `manifest.json`：run ID、发布时间、状态和各产物SHA-256。

同日发布先写`.runs/<run_id>`，完成后原子替换正式目录；失败保留上一份有效快照。

## 当前样本

已用2026-09-14正式Repository输入生成快照：基础过滤后2067只，九源591次命中，去重393只，多来源131只，当日事件160只。正式结果与旧Demo的409只有差异，因为正式版只使用已发布Market Facts事件，不回读Demo研究账本或外部项目文件。

题材层对齐 Demo 后的2026-09-14结果：393只候选全部获得静态成分；当日逻辑题材覆盖92只（Demo 98只，差额全部是正式版未召回、Demo研究账本召回的7只加口径差异），30个逻辑题材组与Demo一致（PCB／覆铜板21只、网络／AI安全12只、液冷9只）；50只趋势低吸候选全部有`primary_concept`，低吸静态题材组27个（Demo 26个，差异来自主概念排序）。

2026-09-15最终快照：333只候选全部获得静态成分，40只趋势低吸候选全部有`primary_concept`；当日逻辑题材覆盖63只（涨停30、活跃观察17、人气观察7、异动加速5、突破启动3、高位分歧1），25个逻辑题材组。该日可用材料为梯队解读32条、同花顺热点理由32条（与涨停名单完全重合）和同花顺热榜概念84条（结构化`concept_tag`，85%非涨停）；异动接口只返回当日快照，0915未在当日采集且事后无法回补，因此非涨停覆盖弱于0914。多源人气覆盖3/4来源（东财接口当日返回空，历史不可回补）。SMNC材料独立维护并已回补到2026-09-16（6421条本地条目，5923条进入索引），0915有59只候选命中公司级材料、23个题材组共46条背景材料。

2026-09-14快照同步刷新：92只逻辑题材、62只候选命中Research材料、29个题材组共58条背景材料。

2026-09-16动态聚类上线（`stock-pools-v2`）：`app/stock_pools/topic_cluster.py`把热点题材从30条固定关键词表改为"抽取→同义归并→共现凝聚聚类"，`topics.py`降级为同义标签表。0916重发快照对比旧口径：有题材候选141→162只，聚类42组（含16个单票组）→57组（全部≥2只）；光互联42只、PCB／覆铜板32只与旧口径完全一致，新增存储芯片16只、风电7只、半导体硅片3只、12英寸2只等旧表无法生成的组；光互联组输出细分方向共封装光学(CPO)22、光通信18、光纤概念15、光模块8。`topic_normalization`记录`mode=deterministic`、`rule=jaccard>=0.3,shared>=2`、术语432、标签57、覆盖股票162。LLM归一化开关默认关闭，开启后经`generate_ai_text`单次调用并持久化到快照。

静态原型仍在`docs/research/stock-pools/pool-panel-prototype.html`，仅用于比较产品设计；正式实现和数据口径以本文件、权威数据文档和源码为准。

## 验证记录

2026-09-15完成正式链路验收：44个股票池、SourceManager和盘后编排定向测试通过；Ruff定向检查、项目契约校验和前端生产构建通过。Standalone Python Playwright使用Microsoft Edge headless访问真实FastAPI服务，验证工作台、393只完整候选、题材联动、详情抽屉、搜索和虚拟表格；1600px桌面无页面横向溢出、console error或失败API请求。截图见`screenshots/gui-test-screenshots/stock-pools-formal-20260914.png`。

2026-09-16题材数据层验收：新增`stock_logic_evidence_daily`事实、`fuyao_anomaly`来源、`scripts/import_fuyao_anomaly_snapshot.py`和`app/stock_pools/topics.py`；`test_stock_pools.py`扩展题材规则、证据合并、热榜降级去重、Service归属和主概念排序用例。离线`--recompute`重建2026-09-14与2026-09-15的Market Facts并重发股票池快照；Playwright在1600px下验证两日热点／低吸聚类、成员联动与详情抽屉“当日交易逻辑／静态关联”，无console error。

2026-09-16 SMNC移植验收：`app/research_materials/smnc.py`（绝参网采集、增量游标、内容哈希去重）与`app/research_materials/builder.py`（公司/题材确定性提取、内容哈希缓存、审计发布合并）落地；`tests/test_research_materials.py`覆盖解析、离线/拦截降级、增量upsert、索引合并与缓存复用。首次索引构建32s，缓存后0.55s；通过代理全局路由回补2026-09-11至2026-09-16共471条SMNC条目（本地6421条、索引5923条），0914/0915的公司级命中分别提升到62/59只。规则模式下本网络按分类拦截`smnc.juecan.com`，采集器正确报告`blocked_or_redirected`并保留本地条目；已按代理全局路由完成一次性回补，长期需把该域名路由到远端节点。

2026-09-16动态聚类验证：`backend/.venv/Scripts/python.exe -m pytest tests/test_stock_pools.py tests/test_research_materials.py tests/test_market_facts.py -q`共36项通过，覆盖同义归并、题材过滤、特例标签隔离、LLM别名应用/复用/失败降级与Service接入；Ruff对改动文件通过；用真实Repository输入重建并原子发布2026-09-16快照（`rule_version=stock-pools-v2`，435只候选、57组、162只有题材）。
