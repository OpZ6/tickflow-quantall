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

- **当日交易逻辑层**：`stock_logic_evidence_daily`逐股保存涨停梯队解读、同花顺热点理由、同花顺异动解读和热榜解读的原文、来源和观察时间；`app/stock_pools/topic_cluster.py`从来源专属`match_text`抽取术语，先归入`topics.py`的既有题材标签，再按术语别名等价归并。股票共现不作为题材同义依据；只保留至少两只成员的组，产出候选`topics`和逐条`topic_evidence`。每个聚类同时输出`subgroups`：把组内原始术语按别名等价合并成细分方向，供工作台展示和筛选。热点启动视图使用这一层；`topics.py`保留为同义标签表和Research索引的题材提取器，规则表不再直接决定热点聚类。
- **可选LLM归一化**：`settings.stock_pool_topic_llm`（环境变量`STOCK_POOL_TOPIC_LLM`）默认关闭；开启且已配置AI Key时，每次发布把聚类标签、术语和样例交给模型做别名合并与噪声剔除，模型不改成员归属；结果写入`summary.json`的`topic_normalization`并在同日重算时复用，调用失败降级回确定性标签并记录`llm-fallback`。
- **静态成分层**：`ext_data`的同花顺概念、一级行业、二级行业和属性通过`load_security_memberships`读取，附到候选`memberships`，并按“具体主题优先、行业显示规则其次、涨停与事件聚集度”确定`primary_concept`；品牌词有无“概念”后缀使用同一背景分类。趋势低吸顶层题材优先使用逐股当日逻辑；该股没有当日逻辑时才用一个静态主概念补充成组。只展示至少3只候选共有的题材卡，未成组的股票仍保留在低吸队列。卡片区分当日逻辑、逻辑／静态和仅静态关联；原始静态概念仍供交叉关联核对，不表示当日催化。低吸队列先列企稳修复、回踩整理，再列趋势延续，同阶段内按距MA20由近及远浏览；此排序表达形态核对顺序，不代表已验证的收益优势。
- 静态成分是最新快照代理，不是历史时点归属；页面和汇总元数据都明确标注。两层都保留原始归属，不改变九路召回及主阶段。

同花顺异动接口只返回当日快照：日常流水线在交易日自动采集`fuyao_anomaly`来源；历史日期用`scripts/import_fuyao_anomaly_snapshot.py`导入冻结响应，导入同时把快照写回`quantx/<date>/normalized/`，供离线`--recompute`复用。热榜解读与异动解读是同一上游分析：同股同文时只保留异动行；异动来源缺失或未覆盖该股时保留热榜行并标记`is_fallback`，详情抽屉显示“降级材料”。

## 页面用法

正式页面只有两个顶层视图：

1. **今日工作台**：先选择热点启动或趋势低吸视角，默认展示排序前15个题材组并可展开全部，再选择题材查看五区九阶段分布、成员和跨题材事件队列。展示数量不参与题材归并或候选召回。
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

手动`POST /api/pipeline/run`与盘后定时任务共用以下顺序：行情和enriched完成，QuantX/Market Facts发布，股票池发布。17:30 的 QuantX 恢复任务也在事实发布成功后串行重建当天股票池；不再单独调度股票池，以免休眠补跑时两个恢复任务并发，股票池先于事实发布。恢复任务遇到正在运行的数据任务时跳过，并在20:30补试；当天股票池已完整发布则跳过补试。手动 QuantX 更新与日K管道共用重任务执行槽，数据任务运行中返回409。

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

Research索引由TickFlow自己维护：`app/research_materials/smnc.py`增量轮询绝参网（`smnc.juecan.com`）并写入`data/research/items.json`；`app/research_materials/builder.py`把SMNC条目按确定性规则提取公司名（instruments精确匹配，带内容哈希缓存）和题材标签（复用`app/stock_pools/topics.py`），与已审计发布合并（同一item以审计版优先）。未提取到公司或旧题材标签的SMNC条目仍进入索引，供新细分方向按标题检索。全部候选都能按公司名核对Research材料，但未经审计的SMNC全文提及只保留在详情，不计入公司研究排序；已审计公司映射或标题明确命中的材料才计入。SMNC题材背景要求标题含该细分词或标题可提取到对应标签，全文抽出的宽泛概念不能单独构成题材背景；这些材料仍不改变候选归属。股票池发布前`refresh_if_configured`先更新SMNC再重建索引；网络被拦截时保留本地条目并降级，不阻断发布。

Research索引v4为每条材料保存`available_at`：SMNC使用首次本地采集时间，已审计材料使用研究发布与本地采集时间中较晚者。公司材料和题材背景查询同时要求源站发布时间及`available_at`换算为北京时间后均不晚于目标交易日，避免把事后回补材料写进历史股票池。SMNC还保存标题点名公司、唯一主角标记和每家公司在正文的原文摘录，查询时区分标题单股、标题多股和正文提及；题材背景仍要求标题有对应线索。研究筛选只计入已审计主证据/辅助证据或标题单股，反证、多股标题和正文提及留在详情核对。低吸队列按阶段及距MA20由近及远浏览，近10日涨幅同步展示，价格位置不改变召回。

2026-09-26核查发现，旧版仅按源站发布时间关联材料，9月1日、2日、9日、10日、14日、15日的已发布快照存在事后材料关联。已只重建这六天的研究关联、研究计数和题材背景，并原子替换快照；候选、九路来源、阶段及层级保持原值。18个已发布日期的manifest校验通过，未再发现晚于目标交易日才可用的材料关联。直接重新计算旧日期会让9月14日候选从393只变为206只，因此不能用全量重算替代定点修复。

同日索引v4和低吸视角补充后，只刷新18个已发布交易日的研究关联、研究筛选计数与题材背景；9月24日仅给原有271只候选补充价格位置。当前输入全量重算当日会从271只扩为485只，基础过滤合格数从1297只升至2196只，原271只全部仍在且九路来源未变。两次的股票行情`input_generation`相同，但该标识不包含证券维表，且`instruments.parquet`仍在刷新；因此不能据此断言旧日期的全部输入相同，也未用重算替换正式候选。9月24日仍是271只、其中低吸阶段52只（趋势延续34、回踩整理18），52只都有价格位置，14只命中定向研究材料。18份manifest及产物哈希校验通过，研究材料和题材背景没有目标日之后才可用的条目。低吸聚类仅展示至少3只成员的卡片，未成组的股票仍留在完整候选列表。

同日做了SMNC池外候选的探索性影子比较：只取目标日已采集、近14自然日标题含公司名、满足股票池基础过滤、此前10个交易日涨幅不超过10%且不在九路池内的股票。9月1—17日可观察5个交易日后收盘价的964个股票日样本，均值+0.36%、正收益44.5%；同期低吸视角753个股票日样本，均值-0.92%、正收益39.7%。有完整三源Top100热榜事实的9月14—17日，额外排除热榜股票后，影子样本131个股票日均值+2.65%、正收益64.9%；同期低吸183个股票日均值+2.64%、正收益55.2%。这只是来源价值线索：股票日重复、样本期短、历史市值使用9月25日维表股本代理，也未检验交易执行或独立样本；不能据此新增正式召回或设定收益阈值。

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

2026-09-27补充：外部榜单除同名/确定性别名上榜外，另显示名称包含当前题材的更细榜单词条，明确标为“相关细分、未核对成员”；不会把“风电轴承”直接当作整个“风电”组的名次。SMNC标题单股材料增加本地可用距今天数、标题/摘录字面题材提及和已审计反证入口；动态聚类的原始术语可用于SMNC标题背景检索，背景材料剔除公司名误匹配并去重同标题，研究线索不参与九路召回或题材成员归属。逐股当日来源有合格术语但未达两只成组时，低吸队列显示“当日解读·未成组”及原始术语，筛选名改为“无成组题材”；亏损、股东拟减持、共同富裕示范区等状态或背景词不进入该提示，聚类噪声规则升至v3。`theme_member_daily`当前主要是问财涨停成员，不能据此补齐非涨停候选的历史细分归属；最新`ext_data`静态概念也不能伪装成历史时点事实。历史复盘的变化归因单列“双日均按时首次版”的可核验样本数；2026-09-24及更早快照仍是回放，9月25—27日休市，没有可制造的实盘样本。当前无AI服务配置，默认只使用可逐字核对的来源线索；是否启用已有可选聚类LLM，不影响九路候选。

## 验证记录

2026-09-15完成正式链路验收：44个股票池、SourceManager和盘后编排定向测试通过；Ruff定向检查、项目契约校验和前端生产构建通过。Standalone Python Playwright使用Microsoft Edge headless访问真实FastAPI服务，验证工作台、393只完整候选、题材联动、详情抽屉、搜索和虚拟表格；1600px桌面无页面横向溢出、console error或失败API请求。截图见`screenshots/gui-test-screenshots/stock-pools-formal-20260914.png`。

2026-09-16题材数据层验收：新增`stock_logic_evidence_daily`事实、`fuyao_anomaly`来源、`scripts/import_fuyao_anomaly_snapshot.py`和`app/stock_pools/topics.py`；`test_stock_pools.py`扩展题材规则、证据合并、热榜降级去重、Service归属和主概念排序用例。离线`--recompute`重建2026-09-14与2026-09-15的Market Facts并重发股票池快照；Playwright在1600px下验证两日热点／低吸聚类、成员联动与详情抽屉“当日交易逻辑／静态关联”，无console error。

2026-09-16 SMNC移植验收：`app/research_materials/smnc.py`（绝参网采集、增量游标、内容哈希去重）与`app/research_materials/builder.py`（公司/题材确定性提取、内容哈希缓存、审计发布合并）落地；`tests/test_research_materials.py`覆盖解析、离线/拦截降级、增量upsert、索引合并与缓存复用。首次索引构建32s，缓存后0.55s；通过代理全局路由回补2026-09-11至2026-09-16共471条SMNC条目（本地6421条、索引5923条），0914/0915的公司级命中分别提升到62/59只。规则模式下本网络按分类拦截`smnc.juecan.com`，采集器正确报告`blocked_or_redirected`并保留本地条目；已按代理全局路由完成一次性回补，长期需把该域名路由到远端节点。

2026-09-16动态聚类验证：`backend/.venv/Scripts/python.exe -m pytest tests/test_stock_pools.py tests/test_research_materials.py tests/test_market_facts.py -q`共36项通过，覆盖同义归并、题材过滤、特例标签隔离、LLM别名应用/复用/失败降级与Service接入；Ruff对改动文件通过；用真实Repository输入重建并原子发布2026-09-16快照（`rule_version=stock-pools-v2`，435只候选、57组、162只有题材）。
