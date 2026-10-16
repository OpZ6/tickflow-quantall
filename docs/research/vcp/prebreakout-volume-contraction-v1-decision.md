# 突破前缩量：扔掉，子集更差

协议 [prebreakout-volume-contraction-v1.json](prebreakout-volume-contraction-v1.json)。数字 [analysis](prebreakout-volume-contraction-v1-analysis.json)。

## 四句

1. **改了什么：** 当前基线上只留突破前 5 日均量 < 前 20 日均量的单（收缩后再突破）。
2. **相对哪条基线：** 171 笔（VCP 领涨 + 两根无需求）。
3. **胜率 / 盈亏比 / 平均净收益：** 基线 31.6% / 3.22 / +1.08%；缩量子集 71 笔 **28.2% / 1.92 / −0.57%**。
4. **扔掉。** 领涨 VCP 里「先缩量再突破」这段更差。下一处改测相反机制：突破前 5 日均量 ≥ 前 20 日均量（已经放量推进再突破）。
