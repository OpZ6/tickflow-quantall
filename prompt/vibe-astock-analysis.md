# Vibe AStock 项目拆解与 TickFlow 接入参考

> 分析对象：本地运行的 `simonlin1212/vibe-astock`（`D:\repos\vibe-astock`）及其 `http://127.0.0.1:8910/` 页面、已生成的日复盘和个股深挖报告。
> 报告日期：2026-10-10。Vibe 日复盘目标日：2026-10-09；另检查了个股深挖样例“绿盟科技（300369）”。
> 方法：以当前本地源码、页面和已保存报告为依据。源码位置按 Vibe 仓库相对路径标注；TickFlow 侧按本仓库路径标注。
> 范围：功能/板块拆解、生成链路、逐项数据源盘点、与 TickFlow 当前代码的重叠和可复用信息增量。未对第三方来源做可用性、授权或商业 SLA 验证。

## 1. Vibe 板块逐项拆解

下表的“TickFlow 对照”以本仓库当前 QuantX / Market Facts / Provider 代码检索为准；“未检出”表示在相关实现中未找到同类接入，不能推断 TickFlow 所有插件配置都不具备该能力。

### 1.1 首页、对话与历史报告

首页承载最近运行、自然语言提问入口和已生成报告跳转。真正执行依赖后端数据与 AI runtime；提问入口并不代表数据自动全网搜索。报告序列化后保存到日期文件，历史版本可回看。

**可参考点：**把“用户问答”和“定期研究报告”作为同一个运行时的不同任务类型，但两者需要清楚标记输入日期、数据来源、数据时间以及材料缺口。TickFlow 已有研究报告、复盘和持久化工作流，本身无需照搬 Vibe 的首页形式。

### 1.2 Watch / 盘中观察

- 由腾讯 `qt.gtimg.cn` 批量行情接口按约 3 秒轮询 L1 行情，监控 watchlist 中股票价格、涨幅、成交量等；这属于轮询快照，不是交易所逐笔/原生 tick 流。
- Eastmoney `push2delay.eastmoney.com/api/qt/clist/get` 提供市场榜单/成交额热度类信息。
- 日内复盘采集固定时间截面（如 09:25、09:35、10:00、11:30、14:00、15:00），用于回看竞价至收盘不同阶段；它不是全市场逐秒历史快照。
- **TickFlow 对照：**TickFlow 的 provider 实时/分钟能力、监控和行情缓存更通用；Vibe 的腾讯轮询路径和“关键时点盘面快照”方法值得借鉴，但应先核对已有 provider 实时能力，避免平行行情链。

### 1.3 Daily Review / 每日短线复盘

核心是五个角色各自读取冻结材料，再由裁判综合：

1. **情绪面：**涨跌停/炸板/跌停、市场宽度、涨停梯队、首板晋级率、昨日涨停溢价、亏钱效应、封板质量、分制度涨跌幅与短周期分位。
2. **资金面：**行业/概念资金榜与成交额榜、大赛道强弱。Prompt 明确只有来源真实提供净流入字段才谈流入/流出；若降级数据只包含成交额/涨跌幅，不把它解释成主力买卖。本次运行此块上游失败。
3. **题材热点：**按涨停原因标签聚合题材热度；可选 Agent-Reach/Exa 检索新闻线索。目标日复盘为避免使用复盘日之后才公开的内容，strict 模式主动不做全网检索。
4. **龙虎榜：**从上榜记录分析净买额、上榜原因和样本行业；prompt 禁止把单日榜和三日榜相加，也禁止凭席位缺失猜游资/机构。
5. **龙头跟踪：**比较今日连板梯队与本地历史龙头归档；归档不连续时不写成逐日演化，不由行业推断题材或资金主体。

裁判读五份角色报告及可用历史记忆，生成“明天关注点”和结构化验证条件。模型文字不是所有数字的来源：封板、市场宽度、样本分位等确定性结果由代码计算后注入。

**TickFlow 对照：**TickFlow 的 QuantX 已覆盖更广的情绪、梯队、题材、板块、候选和逐股证据事实。最值得迁移的是“把封板过程字段做成可复用事实”以及提示词中的口径护栏，而不是复制五个角色的组织形式。

### 1.4 First Board / 首板与涨停原因

- 展示当日涨停股、首板/连板层级、首次封板时间、最后封板时间、炸板次数、封单资金、换手等字段（具体字段取决于上游接口和页面当前数据）。
- 涨停原因来自同花顺数据接口；可尝试 iWencai Open API（需 `IWENCAI_API_KEY`），缺少凭证时回退同花顺公开数据接口 `data.10jqka.com.cn/dataapi/limit_up/limit_up_pool`。代码按目标交易日校验。
- 题材串是供应商归因，适合按主题统计和形成研究线索，不是公司公告事实。
- **TickFlow 对照：**已有 `ths_hot`、`pywencai`、涨停梯队和逻辑证据来源；本次新接入 TickFlow 的是涨停行里的封板过程字段映射，不是新采集端。

### 1.5 Heat / 情绪热度与龙头谱系

- 聚合近期涨停数量、涨停高度、连板梯队、晋级和昨日样本表现，展示近几日情绪温度变化。
- 龙头谱系依赖本地保存的每日 leader/梯队快照；这是应用生成并持久化的派生数据，不是单独的市场供应商。
- 对结果的解释受样本口径影响；涨停家数、连板高度不能单独说明市场参与者的实际盈亏。
- **TickFlow 对照：**QuantX 已有 market state/signal、limit ladder、theme observation、历史统计等标准事实。可借鉴多日热度与个股谱系展示；先把算法口径和样本分母放入 TickFlow 确定性服务。

### 1.6 Yesterday Ladder / 昨日涨停反馈与晋级

- 读取上一交易日涨停池，与本日行情或“昨日涨停表现”接口连接，计算次日收益、再次涨停、晋级、平均数、中位数和正收益比例。
- 样本通常是“昨日收盘时仍在涨停池的股票”，不等于当日所有盘中触板股；必须把样本定义和数量一起展示。
- 使用腾讯批量行情补充目标日价格表现，部分前日涨停池来自 AKShare `stock_zt_pool_previous_em`。
- **TickFlow 对照：**QuantX 已有昨日表现/溢价、候选和复盘来源；报告可借鉴把晋级结果写成基于明确样本的确定性指标。

### 1.7 历史统计与 Backtest

- Historical stats 主要对涨停样本做下一交易日表现统计，包括涨跌分布与再次涨停比例；不自动等同于能下单成交的策略回测。
- Backtest 页面把策略条件映射为规则并执行成交模拟，和前述样本描述统计是两种不同用途。
- 仅使用次日收盘/涨停表现不能证明买入时可成交；涨停一字板、买入排队、T+1、费用和滑点会影响真实交易结果。
- **TickFlow 对照：**TickFlow 回测边界更明确，已有成交模拟和 T+1/涨跌停相关约束。保留这种边界，不要把 Vibe 的次日样本统计当作可成交回测策略。

### 1.8 Intel / 新闻、公告与信息雷达

Intel 包含若干不同来源的页面/数据类型：

- **RSS NewsRadar：**读取 `vr/news_sources.json` 中 108 个 RSS/Atom feed，覆盖 AI、半导体、机器人、汽车/新能源、能源、生物医药、航天、网络安全、科技、消费电子、宏观财经、科学前沿等 12 个方向；取标题、链接、来源、发布时间和最多约 160 字摘要，并按行业词和红线词筛选近 7 天内容。它是行业背景雷达，不是面向 A 股涨停的实时快讯终端。
- **个股新闻：**个股新闻页经 AKShare `stock_news_em(symbol=code)` 读取 Eastmoney 个股新闻列表。
- **公告：**Eastmoney `np-anotice-stock.eastmoney.com/api/security/ann`，详情链接指向 Eastmoney 公告页；代码保留 CNINFO/AKShare 公告回退路径。
- **消息检索：**题材/个股深挖可调用 Agent-Reach，经 `mcporter` 接 Exa 全网搜索；本机当前依赖不可用，因此绿盟科技深挖没有拿到结果。日复盘 strict 模式不把全网检索结果混入历史日期报告。
- Watchlist 新闻/公告分栏依赖用户有自选股代码；当前检查的本地样例自选池为空，所以这些个股分栏无目标数据。
- **TickFlow 对照：**当前 QuantX 代码有涨停原因、公告/题材/逻辑证据等研究事实，但在当前仓库后端实现中未检出上面这套 108-feed 新闻雷达、Eastmoney 个股新闻页及 Agent-Reach 集成。这是 TickFlow 的消息面补充方向。应先选择有限且有用的来源组，不建议机械搬入 108 个 feed。

### 1.9 Stock Data / 个股研究与公司资料

Vibe 的个股研究页面可读取行情、历史 K 线、估值/财务、研报、预测、龙虎榜、新闻、公告和公司互动问答；不同页面/字段不是每日复盘都使用。

- 腾讯行情 `qt.gtimg.cn`：价格、涨幅、换手、量比、市值、PE/PB、涨跌停价等快照字段。
- 腾讯日 K 通过 AKShare `stock_zh_a_hist_tx`；回看历史趋势/收益时使用。
- Eastmoney 研报列表 API `reportapi.eastmoney.com/report/list`，PDF 地址 `pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf`。
- 同花顺财务预测 `stock_profit_forecast_ths`、财务摘要 `stock_financial_abstract_ths`（由 AKShare 封装）。
- AKShare `stock_news_em` 个股新闻；Eastmoney 公告接口及其详情页。
- `investor_qa` 调用 CNINFO 互动易站点内部 JSON 接口：`irm.cninfo.com.cn/newircs/index/queryKeyboardInfo`、`/newircs/company/question`，取问题、回复及时间。
- **互动易/上证 e 互动：**Vibe 当前实际代码可确认的是 CNINFO 互动易接口；没有发现另接 SSE “上证 e 互动”的实现。SSE e-互动可以作为未来单独来源研究，需独立适配上海市场。
- **TickFlow 对照：**公司公告、财务与基本面信息在 TickFlow 有部分既有能力或可由现有数据源取得；上述 Eastmoney 研报列表/PDF、THS 分析师预测、Eastmoney 个股新闻和 CNINFO 互动问答，在当前 QuantX 数据源管线代码检索中未检出直接接入，属于潜在新增来源/信息类型。腾讯报价/K线则需与已启用 Provider 能力逐项比对，不能仅凭未找到直连接口就判为整体缺失。

### 1.10 DeepDive / 个股深挖与多空讨论

- 接收单只股票及用户问题，先拉腾讯报价/K线、AKShare 龙虎榜、可选 iWencai 题材，再尝试 Agent-Reach 检索近期事件。
- 深挖分析被要求区分事实、推断和缺口；龙虎榜日榜/三日榜不混加；缺资料时不把未观察到写成事件未发生。
- bull/bear debate 把看多与看空材料并列，适合做证据结构和反例检查。
- **当前样例的限制：**样例得到报价、K 线和单日龙虎榜，但消息、公告、题材资料未覆盖，Agent-Reach 还不可用；不能把页面提供了栏目当成此次分析实际拿到了这些数据。
- **TickFlow 对照：**可参考“明确材料边界 + 多空反证 + 证据缺口”的输出约束；研究资料源需通过 TickFlow SourceManager / Market Facts 接入，避免报告直接抓网页。

### 1.11 My Stocks / 自选、持仓与交易日志

- 自选股作为个股新闻、公告、行情和监控的关注范围；组合/持仓由用户交易记录汇总；journal 保存人工复盘与交易笔记。
- 当前本地样例没有自选股/组合记录，因此只确认功能实现，不能评价个股数据覆盖效果。
- **TickFlow 对照：**TickFlow 已有监控、策略和交易/组合相关功能。值得参考的是把复盘后观察对象与交易日志连接起来；不是数据源增量。

## 2. 报告生成与证据链

从代码路径看，日复盘是一条带确定性取数和校验的流程，而不是直接把“大盘问题”交给模型自由回答：

1. **入口选择日期和模型配置。**报告元数据记录 `api-compatible`、`deepseek-v4-flash` 和 `https://api.deepseek.com`。这是保存报告时的配置记录；本地其他页面当前也显示“尚未接入 AI”，说明配置状态可能按页面/时刻不同，不能把一处 UI 状态覆盖成全局事实。
2. **冻结复盘输入。**`review_agent/daily.py::FrozenInputs` 按目标交易日缓存各个 `get_*` 输入到本次 run 目录，禁止跨日期取数；每个 payload 记录目标日期、获取时间和 SHA-256。报告任务不会让分析模型任意调用网络工具。
3. **抓取/构造确定性输入。**`duanxian.data`、`fetchers.py`、`breadth.py`、`emotion_metrics.py` 产生各角色素材及结构化指标。涨停时间、昨日反馈、涨跌家数、封板质量等由代码计算，缺源会呈现 unavailable/warning。
4. **五个分析角色分别写定性摘要。**每一角色收到本域数据和自己的 prompt；输入失败时显式标注降级，不通过别的角色“补脑”缺失字段。
5. **裁判生成次日关注点。**结构化 focus 包含观察条件、阈值/方向、依据等。LLM 输出不应突破动作/价格推荐限制；结果需通过 JSON schema、指标白名单、引用 ID 和文字规则检查，允许一次受限校正。裁判会注入历史 reflection 作为上下文，但它不替代本次数据。
6. **证据引用核对。**构建 evidence catalog 后检查引用是否指向本次冻结素材；报告 `references_validated` 仅说明引用结构有效，不证明来源真实性或分析推论一定正确。
7. **版本化保存与后处理。**保存日期版报告和 latest；保存后另行归档市场数据、主题/统计，并调用 `reflection.auto_evaluate_prior(date)` 尝试评估上期关注条件。缺少次日真实交易事实时标记未完成/不适用，不应伪造命中结果。

可迁移到 TickFlow 的报告工程做法：把数据冻结、证据引用、结构化可核验条件、模型校验与原始来源快照拆开。TickFlow 已有 publication manifest、SourceSnapshotStore、确定性报告/事实管线和 QuantX report writer，这些能力无需重造；可吸收 Vibe 的短线问题模板和封板过程指标。

## 3. 数据源和数据清单（带 TickFlow 对照）

### 3.1 来源标签

| 标记 | 含义 |
| --- | --- |
| **已有** | TickFlow 当前代码/QuantX 来源路由已有同类来源或事实能力；Vibe 不构成新数据源 |
| **已有源新增信息** | TickFlow 已有该来源/原始数据，但之前没有将该字段映射到标准 Market Fact；本次已补通 |
| **新增候选** | 当前 TickFlow QuantX 相关代码未检出该来源/接口；需与其他插件配置及既有公告能力核对后再接入 |
| **部分重叠** | 同一类数据 TickFlow 有部分能力，Vibe 来源或字段不同，需字段级对账 |
| **不属于外部数据源** | 本地算法计算、历史归档或 AI 输出 |

### 3.2 行情、涨停、宽度、资金和龙虎榜

| Vibe 具体源 / 代码接口 | 主要字段/数据 | 用于哪些板块 | TickFlow 对照 |
| --- | --- | --- | --- |
| AKShare `stock_zt_pool_em(date=...)`；上游 Eastmoney 涨停池 | 代码、名称、连板数、行业/原因、首次封板、最后封板、炸板次数、封板资金 | Daily Review、First Board、昨日样本/涨停历史 | **已有源新增信息**：TickFlow 同一 scraper 已抓上述四个过程字段；本次映射到 `limit_event_daily` v3 |
| AKShare `stock_zt_pool_zbgc_em(date=...)`；Eastmoney 炸板池 | 盘中炸板后未最终封板样本 | Daily Review、情绪面 | **已有**：`pywencai` scraper 已有 |
| AKShare `stock_zt_pool_dtgc_em(date=...)`；Eastmoney 跌停池 | 跌停代码/涨跌幅 | Daily Review 亏钱效应 | **已有**：`pywencai` scraper 已有 |
| AKShare `stock_zt_pool_previous_em(date=...)`；Eastmoney 昨日涨停表现 | 昨日涨停样本今日涨跌、当前价、涨停价、昨日连板数 | Yesterday Ladder、晋级/溢价统计 | **已有**：TickFlow scraper 有昨日样本表现字段 |
| 同花顺公开接口 `https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool` | 涨停原因标签/题材；按目标日期查询 | 题材热点、首板原因 | **已有/部分重叠**：TickFlow 有 THS 热点与题材观察；Vibe 的涨停池归因 API 路径是具体实现差异 |
| iWencai Open API（`IWENCAI_API_KEY`、`IWENCAI_BASE_URL`） | 有 key 时获取自然语言选股/涨停原因数据；无 key 时回退 THS 公共池 | First Board、题材归因、个股深挖 | **已有**：TickFlow 已用 iWencai/问财选股或百日新高查询；Vibe 提供可选接口配置方式 |
| Eastmoney delayed quote `https://push2delay.eastmoney.com/api/qt/clist/get` | 涨跌、成交额、个股/板块资金排名、榜单 | 资金面、Watch、市场热度 | **部分重叠/新增候选**：TickFlow 有板块资金和行情事实，但未检出此 Vibe 直连接口；需比较数据字段及当前 Provider 覆盖 |
| Eastmoney delayed quote `https://push2delay.eastmoney.com/api/qt/ulist.np/get` | 沪深涨跌家数、成交额等宽度数据 | 情绪、市场宽度 | **部分重叠**：TickFlow 已从逐股日线/行情计算宽度；这是不同聚合源及范围口径，只有对账后才考虑接入 |
| Eastmoney delayed quote `push2delay.eastmoney.com/api/qt/clist/get` 分页 | 全 A（含北交所）涨跌幅分布与大跌家数 | 亏钱效应、市场广度 | **部分重叠**：TickFlow 的逐股日线可计算同类统计；需保留全 A/沪深范围差异 |
| AKShare `stock_lhb_detail_em(start_date,end_date)`；Eastmoney 龙虎榜明细 | 上榜日期、代码、原因及净买卖统计；Vibe 日复盘只读取目标日记录 | 龙虎榜、个股深挖 | **已有/部分重叠**：TickFlow 具龙虎榜数据能力；具体依赖来源和席位字段需对接口契约，不把榜单金额叫全市场资金流 |
| 腾讯 `http://qt.gtimg.cn/q=` 批量报价 | 现价、涨幅、成交额、换手、量比、PE/PB/市值、涨跌停价等 | 个股、盘中观察、昨日反馈、reflection | **新增候选/待 Provider 对账**：QuantX 后端当前搜索未检出该直连；若 Provider 已能供同字段则不是数据缺口 |
| 腾讯行情 `qt.gtimg.cn` 按指数代码批量拉取 | 指数即时报价 | 盘面背景、Watch | **部分重叠**：TickFlow 有固定指数/行情能力，但需确认上游和时点；Vibe 腾讯接口不直接等价于 TickFlow 指数契约 |
| AKShare `stock_zh_a_hist_tx(symbol=...)`（腾讯历史 K 线） | 个股历史日 K，用于收益/走势、昨日溢价与 reflection | 历史行情、个股研究、回看 | **新增候选/待 Provider 对账**：TickFlow 已有统一日 K Provider；该源是否需要取决于现有历史覆盖、回退和时点质量 |
| 本地涨停池缓存、历史 leader/archive、统计缓存 | 近 N 日样本、龙头延续、题材累积 | Heat、历史统计、Reflection | **不属于外部数据源**：TickFlow 已有 Parquet facts/Report history/候选快照等不同存储 |

### 3.3 消息、新闻、公告、研报与公司沟通

| Vibe 具体源 / 代码接口 | 主要数据 | 使用位置/限制 | TickFlow 对照 |
| --- | --- | --- | --- |
| `vr/news_sources.json` → 108 个 RSS/Atom feeds；`vr/newsradar.py` | 标题、URL、时间、来源名、短摘要；近 7 天、12 行业方向；订阅源每次最多取 6 条 | NewsRadar 行业背景。并非此次 10-09 日复盘的来源，也非 A 股实时快讯 | **新增候选**：当前 QuantX 未检出 RSS 聚合器。完整 feed 清单见本报告附录 |
| Agent-Reach → `mcporter` / Exa 全网检索 | 搜索网页结果/新闻片段 | 主题分析、个股深挖；strict 历史复盘关闭检索；当前本机不可用 | **新增候选**：当前 QuantX 未检出此集成；接入前需锁定发布时间与历史可见性 |
| AKShare `stock_news_em(symbol=...)`；Eastmoney 个股新闻 | 代码相关资讯标题/时间/来源/链接等 | Intel 个股新闻 | **新增候选/部分重叠**：当前 QuantX 后端检索未找到直接适配；公告/逻辑证据并不等价于个股新闻 |
| Eastmoney `https://np-anotice-stock.eastmoney.com/api/security/ann` | 个股公告列表/公告 ID/标题/时间/详情链接；详情页 `data.eastmoney.com/notices/detail/...` | Intel、个股研究；可回退 CNINFO/AKShare 公告实现 | **部分重叠**：TickFlow 有公告/研究素材能力；该具体 Eastmoney API 与逐股公告结构需核对现有来源 |
| CNINFO/巨潮公告站点与 AKShare 公告回退 | 公告列表或全文/附件，覆盖沪深上市公司信息披露 | 个股公告 | **已有/部分重叠**：TickFlow 已有巨潮公告来源，Vibe 的 Eastmoney 主路由可作为备用源研究 |
| Eastmoney 研报列表 `https://reportapi.eastmoney.com/report/list` | 研报标题、机构、分析师、评级、发布日期、PDF 信息 | 个股研究/研报列表 | **新增候选**：TickFlow 当前 QuantX 代码检索未发现该研报列表 API |
| Eastmoney 研报 PDF `https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf` | 研报 PDF 原文 | 个股研究 | **新增候选**：需要后续再做 PDF 抽取、来源时间与版权/可存储策略；本报告不评估许可 |
| AKShare `stock_profit_forecast_ths` | THS 一致预期/预测 EPS 等 | 个股基本面研究 | **新增候选/部分重叠**：TickFlow 当前有基础财务数据；分析师一致预测是不同数据类型 |
| AKShare `stock_financial_abstract_ths` | THS 财务摘要/报告期指标 | 个股研究 | **部分重叠**：基础财务已有；来源、字段和公告时间需对账 |
| CNINFO 互动易 JSON：`irm.cninfo.com.cn/newircs/index/queryKeyboardInfo`、`/newircs/company/question` | 投资者提问、公司答复、答复/提问时间 | 个股研究 Company IR；它是站点内部接口，不等同公告或投资建议 | **新增候选**：当前 QuantX 未检出互动易问答接入 |
| SSE 上证 e 互动 `one.sse.com.cn/list/tzzgx/` | 上交所上市公司投资者沟通平台 | 本次 Vibe 代码没有发现接入；仅列为 TickFlow 可调查的上海补充源 | **候选，不是 Vibe 已用源** |

### 3.4 逐股/个股行情技术字段

个股报价和 K 线属于 TickFlow 标准行情域。若现有 Provider 已提供 `realtime`、`daily`、`minute`、`financial`，优先使用统一契约；只有需要新的行情能力或独立备用源，才按 Provider 插件规则评估。不要把行情快照、公司新闻、公告、问答和研报都硬塞成 OHLCV Provider 数据集；公告/新闻/研报/互动问答应按可复用市场事实通过 SourceManager + Market Facts 或研究素材流接入。

## 4. 与 TickFlow 的信息增量分层

### A. 已有输入，不必新接数据源

- 涨停池、炸板池、跌停池、昨日涨停表现：TickFlow 已有 AKShare/Eastmoney 采集。
- 涨停原因/问财、同花顺热点、梯队、题材观察、资金面/市场宽度：TickFlow 已有多个对应事实及来源路由。
- 龙头梯队、历史市场状态、候选快照和逐股逻辑证据：QuantX 已有相应数据集。

### B. 已有来源新增字段（本次已做）

- `first_seal_time`、`last_seal_time`、`broken_count`、`seal_amount_yi` 进入 `limit_event_daily` v3。
- 可用这些列确定性构造：封板时段分布、早盘封板占比、尾盘最后封板占比、从未炸板占比、平均/分位炸板次数、封板资金分组；派生结果应按样本数、交易板块、涨跌幅制度展示。
- “封板资金”是上游字段统计值，不能直接解释为净流入；首次封板时间不等于题材启动时间；最后封板时间不等于持续封单质量。数据可用性和解释边界要与原字段一起保留。

### C. 对 TickFlow 有潜在新信息类型，后续可以单独立项

1. **A 股新闻事件流：**先从 Eastmoney 个股新闻、公告和已有公开 RSS 中选小范围来源；保存 source、原始 URL/ID、发布时间、采集时间、代码/主题关联、原文/摘要边界。计算“截至目标交易日收盘可见”的材料集，避免用未来新闻回填历史判断。
2. **公司 IR 问答：**CNINFO 互动易问答可帮助识别公司对业务、订单、题材的公开回应。必须保留问答时间、原始问题/答复、股票代码与检索条件；问答不是公告事实的替代。若后续需要沪市覆盖，再评估 SSE e-互动。
3. **分析师研报与一致预期：**Eastmoney 列表/PDF 和 THS 预测 EPS 对研究有用，但不是日常涨停复盘核心，适合先进入按需个股研究，而不是每日日报关键路径。
4. **外部搜索增强：**Agent-Reach/Exa 能扩展事件搜索面，但需支持日期过滤和可引用 URL/发布时间；全网搜索结果不能直接作为复盘日已知事实。

## 5. 代码参考

### Vibe AStock

- `duanxian/analysts.py`：五角色分析 prompt 和输入分工。
- `duanxian/data.py`、`duanxian/fetchers.py`、`duanxian/breadth.py`、`duanxian/emotion_metrics.py`：复盘输入和派生指标。
- `review_agent/daily.py`、`review_agent/grounding.py`、`review_agent/post_review.py`：输入冻结、校验、证据引用、发布后回评。
- `duanxian/pool_source.py`、`duanxian/historical_sources.py`：涨停池与同花顺来源。
- `duanxian/reflection.py`、`duanxian/verification.py`：T+1 reflection/验证条件。
- `duanxian/deepdive/data.py`：个股深挖行情、K 线、龙虎榜、题材与搜索。
- `vr/astock.py`：报价、研报、THS 财务/预测、新闻、公告和投资者问答。
- `vr/news_sources.json`、`vr/newsradar.py`：RSS 配置和订阅器。
- `vr/watchtower.py`：盘中行情轮询。

### TickFlow

- `backend/app/quantx_data/legacy_scrapers/pywencai_scraper.py::fetch_limit_up_details`：已有涨停来源原始字段。
- `backend/app/market_facts/builders.py::_event_rows`、`_build_limit_events`：字段标准化及事实构造。
- `backend/app/market_facts/registry.py::DatasetId.LIMIT_EVENT_DAILY`：Market Facts v3 契约。
- `backend/app/market_facts/repository.py::get_limit_events`：已发布事实读取。
- `backend/app/quantx_data/collectors.py`、`source_manager.py`：QuantX SourceManager 采集边界。
- `backend/app/market_facts/registry.py::ROUTES`：当前 Dataset 来源路由。
- `backend/tests/test_market_facts.py`：字段标准化与事实构造验证。
- `docs/data-foundation.md`：Market Facts 数据契约。

## 附录 A：Vibe 已配置的全部 108 个 RSS/Atom feed

该列表来自 `vr/news_sources.json`。名称、hint 和 URL 是配置清单；是否每个源当次拉取成功需看 NewsRadar 运行结果。feed 的元数据按最多 7 天和单源最多 6 条筛选。

| ?? | ?? hint | ?? | Feed URL |
| ---: | --- | --- | --- |
| 1 | ai | OpenAI | https://openai.com/news/rss.xml |
| 2 | ai | Google Research | https://research.google/blog/rss/ |
| 3 | ai | Hugging Face | https://huggingface.co/blog/feed.xml |
| 4 | ai | 量子位 | https://www.qbitai.com/feed |
| 5 | ai | MIT Tech Review AI | https://www.technologyreview.com/topic/artificial-intelligence/feed |
| 6 | ai | The Verge AI | https://www.theverge.com/rss/ai-artificial-intelligence/index.xml |
| 7 | ai | TechCrunch AI | https://techcrunch.com/category/artificial-intelligence/feed/ |
| 8 | ai | arXiv cs.AI | https://export.arxiv.org/rss/cs.AI |
| 9 | ai | KDnuggets | https://www.kdnuggets.com/feed |
| 10 | ai | MarkTechPost | https://www.marktechpost.com/feed/ |
| 11 | ai | BAIR Blog | https://bair.berkeley.edu/blog/feed.xml |
| 12 | ai | Import AI | https://importai.substack.com/feed |
| 13 | ai | DeepMind | https://deepmind.google/blog/rss.xml |
| 14 | ai | 智东西 | https://zhidx.com/rss |
| 15 | ai | 机器之心 | https://wechat2rss.xlab.app/feed/51e92aad2728acdd1fda7314be32b16639353001.xml |
| 16 | ai | 新智元 | https://wechat2rss.xlab.app/feed/ede30346413ea70dbef5d485ea5cbb95cca446e7.xml |
| 17 | semi | DIGITIMES | https://www.digitimes.com/rss/daily.xml |
| 18 | semi | SemiAnalysis | https://semianalysis.substack.com/feed |
| 19 | semi | Semiconductor Engineering | https://semiengineering.com/feed/ |
| 20 | semi | EE Times | https://www.eetimes.com/feed/ |
| 21 | semi | IEEE Spectrum 半导体 | https://spectrum.ieee.org/feeds/topic/semiconductors.rss |
| 22 | semi | SemiWiki | https://semiwiki.com/feed/ |
| 23 | semi | Semiconductor Today | https://www.semiconductor-today.com/rss/news.xml |
| 24 | semi | Electronics Weekly | https://www.electronicsweekly.com/feed/ |
| 25 | semi | All About Circuits | https://www.allaboutcircuits.com/rss/news/ |
| 26 | robot | The Robot Report | https://www.therobotreport.com/feed/ |
| 27 | robot | IEEE Spectrum 机器人 | https://spectrum.ieee.org/feeds/topic/robotics.rss |
| 28 | robot | Robohub | https://robohub.org/feed/ |
| 29 | robot | Robotics & Automation | https://roboticsandautomationnews.com/feed/ |
| 30 | robot | Robotics Business Review | https://www.roboticsbusinessreview.com/feed/ |
| 31 | auto | Electrek | https://electrek.co/feed/ |
| 32 | auto | InsideEVs | https://insideevs.com/rss/articles/all/ |
| 33 | auto | The Verge Transport | https://www.theverge.com/rss/transportation/index.xml |
| 34 | auto | TechCrunch Transport | https://techcrunch.com/category/transportation/feed/ |
| 35 | auto | CnEVPost | https://cnevpost.com/feed/ |
| 36 | energy | CleanTechnica | https://cleantechnica.com/feed/ |
| 37 | energy | Utility Dive | https://www.utilitydive.com/feeds/news/ |
| 38 | energy | pv magazine | https://www.pv-magazine.com/feed/ |
| 39 | energy | Energy Storage News | https://www.energy-storage.news/feed/ |
| 40 | energy | OilPrice | https://oilprice.com/rss/main |
| 41 | energy | Canary Media | https://www.canarymedia.com/articles.rss |
| 42 | energy | PV Tech | https://www.pv-tech.org/feed/ |
| 43 | energy | Renewable Energy World | https://www.renewableenergyworld.com/feed/ |
| 44 | energy | 国际能源网 | https://www.in-en.com/feed/rss.php?mid=21 |
| 45 | bio | STAT News | https://www.statnews.com/feed/ |
| 46 | bio | Endpoints News | https://endpts.com/feed/ |
| 47 | bio | FierceBiotech | https://www.fiercebiotech.com/rss/xml |
| 48 | bio | FiercePharma | https://www.fiercepharma.com/rss/xml |
| 49 | bio | BioPharma Dive | https://www.biopharmadive.com/feeds/news/ |
| 50 | bio | GEN | https://www.genengnews.com/feed/ |
| 51 | bio | Nature Biotech | https://www.nature.com/nbt.rss |
| 52 | space | SpaceNews | https://spacenews.com/feed/ |
| 53 | space | Space.com | https://www.space.com/feeds/all |
| 54 | space | Spaceflight Now | https://spaceflightnow.com/feed/ |
| 55 | space | Payload | https://payloadspace.com/feed/ |
| 56 | space | NASA | https://www.nasa.gov/news-release/feed/ |
| 57 | space | NASASpaceflight | https://www.nasaspaceflight.com/feed/ |
| 58 | security | Krebs on Security | https://krebsonsecurity.com/feed/ |
| 59 | security | The Hacker News | https://feeds.feedburner.com/TheHackersNews |
| 60 | security | BleepingComputer | https://www.bleepingcomputer.com/feed/ |
| 61 | security | Dark Reading | https://www.darkreading.com/rss.xml |
| 62 | security | SecurityWeek | https://www.securityweek.com/feed/ |
| 63 | tech | TechCrunch | https://techcrunch.com/feed/ |
| 64 | tech | The Verge | https://www.theverge.com/rss/index.xml |
| 65 | tech | Ars Technica | https://feeds.arstechnica.com/arstechnica/index |
| 66 | tech | Hacker News | https://hnrss.org/frontpage |
| 67 | tech | WIRED | https://www.wired.com/feed/rss |
| 68 | tech | Engadget | https://www.engadget.com/rss.xml |
| 69 | tech | Techmeme | https://www.techmeme.com/feed.xml |
| 70 | tech | 36氪 | https://36kr.com/feed |
| 71 | tech | 钛媒体 | https://www.tmtpost.com/rss.xml |
| 72 | tech | 少数派 | https://sspai.com/feed |
| 73 | tech | IT之家 | https://www.ithome.com/rss/ |
| 74 | tech | GitHub Blog | https://github.blog/feed/ |
| 75 | tech | Stratechery | https://stratechery.com/feed/ |
| 76 | tech | 虎嗅 | https://rss.huxiu.com/ |
| 77 | tech | 动点科技 | https://cn.technode.com/feed/ |
| 78 | tech | 月光博客 | https://www.williamlong.info/rss.xml |
| 79 | tech | Solidot | https://www.solidot.org/index.rss |
| 80 | tech | 白鲸出海 | https://www.baijingapp.com/feed |
| 81 | consumer | Engadget | https://www.engadget.com/rss.xml |
| 82 | consumer | 9to5Mac | https://9to5mac.com/feed/ |
| 83 | consumer | 9to5Google | https://9to5google.com/feed/ |
| 84 | consumer | GSMArena | https://www.gsmarena.com/rss-news-reviews.php3 |
| 85 | consumer | Android Authority | https://www.androidauthority.com/feed/ |
| 86 | consumer | DPReview | https://www.dpreview.com/feeds/news.xml |
| 87 | consumer | 少数派 | https://sspai.com/feed |
| 88 | macro | CNBC | https://www.cnbc.com/id/100003114/device/rss/rss.html |
| 89 | macro | Financial Times | https://www.ft.com/rss/home |
| 90 | macro | WSJ Markets | https://feeds.a.dj.com/rss/RSSMarketsMain.xml |
| 91 | macro | MarketWatch | https://feeds.marketwatch.com/marketwatch/topstories/ |
| 92 | macro | Yahoo Finance | https://finance.yahoo.com/news/rssindex |
| 93 | macro | 华尔街见闻 | https://dedicated.wallstreetcn.com/rss.xml |
| 94 | macro | Finextra | https://www.finextra.com/rss/headlines.aspx |
| 95 | macro | SEC | https://www.sec.gov/news/pressreleases.rss |
| 96 | macro | Federal Reserve | https://www.federalreserve.gov/feeds/press_all.xml |
| 97 | macro | Seeking Alpha | https://seekingalpha.com/market_currents.xml |
| 98 | macro | 东方财富股票 | http://rss.eastmoney.com/rss_stock.xml |
| 99 | macro | 东方财富资讯 | http://rss.eastmoney.com/rss_partener.xml |
| 100 | macro | 经济观察网 | http://www.eeo.com.cn/rss.xml |
| 101 | science | Nature News | https://www.nature.com/nature.rss |
| 102 | science | ScienceDaily | https://www.sciencedaily.com/rss/all.xml |
| 103 | science | Quanta Magazine | https://api.quantamagazine.org/feed/ |
| 104 | science | New Scientist | https://www.newscientist.com/feed/home/ |
| 105 | science | Live Science | https://www.livescience.com/feeds/all |
| 106 | science | MIT News | https://news.mit.edu/rss/research |
| 107 | science | Science News | https://www.sciencenews.org/feed |
| 108 | science | Ars Technica Science | https://feeds.arstechnica.com/arstechnica/science |
