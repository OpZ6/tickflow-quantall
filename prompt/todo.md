# tickflow：
1. 考虑实现板块、情绪周期等分析、市场方向预判
3. 题材库 + 板块指标？1amv
4. 自动化深入个股分析：quantr基本面/smnc小作文、订单流汇总分析、K线量价/1amv指标等
5. 催化网站如何做？
6. https://stock.quicktiny.cn/ 完全爬取（题材库、工作台、连阳、板块资金、板块轮动、热榜、资讯等）
7. simonlin1212/vibe-astock （数据源、报告分析逻辑、提示词）—— 新增数据源

### level2相关：
1. quant-stock-data/a-share-level2-mcp 订单流数据接口（4.5T 自行实现？）
2. https://pan.quark.cn/s/1ae1c55c0a03?pwd=QNhy

---
# quantt
1. 增加交割单导入分析，增加全量数据（题材、板块、量价、换手等等）
2. 增加策略触发标记？自定义指标

---
# quants
1. K线图画图近似走法（半路中可能符合的、历史上符合的、历史好图可能出现的）
2. 资产依赖关联图谱
3. 其他参考案例整理上传+ 《如何快速了解一个行业》，第一性原理/对抗性审查/苏格拉底提问

---
# tickflow
1.  trading agent- cn分析接入？https://b23.tv/Q06PQ9K
2.  https://github.com/fadewalk/serenity-stock-choke
3.  相关系数看不见的股票关系我用信息论挖出来了-哔哩哔哩】 https://b23.tv/FJwnFmI 

---

1. 哪些应该复盘页面 / 新建一个长期统计页面（quantx复盘优化）
2. 多日资金曲线统计实施（连板天梯 / 看盘啦 复刻）
   1. https://github.com/dean-stack/a-share-sector-flow-visualizer （实现）
   2. https://github.com/Timmmmmo/ashare-fund-flow （实现）
   3. https://www.plotcap.com/editor    https://coooapi.cn/sector    https://astock.ai9p.com/  （参考）
   4. https://passforever.github.io/a-share-sector-rotation-dashboard/ （复盘参考）
   5. https://flowscope.deq.plus/  （最佳复刻参考）
3. 题材库（爬 https://stock.quicktiny.cn/themes?view=kpl + 开盘啦？ 打标签？）


---

# 理想情况
## 信号流（超短核心选大哥跟随+市场认不认-板、窗口期节点定一切、去噪音去杂音）

市场总体情绪（极端反馈/接力反馈/大资金反馈） ———— 感知市场温度、
超大盘面（红绿地图） ———— 上帝视角看水位分布
细分概念板块（异动涨速排序） ———— 快速定位具体进攻点
板块内涨幅涨速排序（全市场涨速排序）———— 找到带头大哥
实时净量/成交量 ———— 判断带头大哥力度、市场认不认

---

# tushare

MCP 使用：
{"mcpServers":{"myMCP":{"url":"https://t.xiaodefa.top/mcp?token=2c616d4e35f719c29a1365ccb31220d5fc5ed9fc6e0a5668fb337482"}}}

python 使用:
import tushare as ts
pro = ts.pro_api('2c616d4e35f719c29a1365ccb31220d5fc5ed9fc6e0a5668fb337482')
pro._DataApi__http_url = "https://t.xiaodefa.top/"
df = pro.stock_basic(limit=5)
print(df)
