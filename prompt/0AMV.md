# 知乎：https://zhuanlan.zhihu.com/p/2032106743459788207

活跃市值0AMV
Var1:=SMA("AA02$AMOUNT",10,1)/10000000; 
Var2:=REF(Var1,1); 
AA: STICKLINE(Var1>Var2,Var1,Var2,8,1),COLORRED; 
AD: STICKLINE(Var1<Var2,Var1,Var2,8,0),COLORGREEN; 
C5: DMA(SMA(Var1,3,1),VOL/0.02/CAPITAL); 
C13: DMA(SMA(Var1,5,1),VOL/0.1/CAPITAL); 
C34: DMA(SMA(Var1,8,1),VOL/0.18/CAPITAL); 
∞: DMA(Var1,VOL/1.1/CAPITAL);

0AMV个股 个股活筹 
Var1:=SMA(AMOUNT,10,1)/10000000; 
Var2:=REF(Var1,1); 
AA: STICKLINE(Var1>Var2,Var1,Var2,8,1),COLORRED; 
AD: STICKLINE(Var1<Var2,Var1,Var2,8,0),COLORGREEN; 
C5: DMA(SMA(Var1,3,1),VOL/0.02/CAPITAL); 
C13: DMA(SMA(Var1,5,1),VOL/0.1/CAPITAL); 
C34: DMA(SMA(Var1,8,1),VOL/0.18/CAPITAL); 
∞: DMA(Var1,VOL/1.1/CAPITAL);

0DMV个股 个股死筹 
Var1:=CLOSE-SMA(VOL,9,1)/10000; 
Var2:=REF(Var1,1); 
AA: STICKLINE(Var1>Var2,Var1,Var2,8,1),COLORRED; 
AD: STICKLINE(Var1<Var2,Var1,Var2,8,0),COLORGREEN; 
C5: DMA(SMA(Var1,2,1),VOL/0.03/CAPITAL); 
C13: DMA(SMA(Var1,5,1),VOL/0.07/CAPITAL); 
C34: DMA(SMA(Var1,2,1),VOL/0.22/CAPITAL); 
∞: DMA(Var1,VOL/0.9/CAPITAL); 
Var3:=SUM(Var1*VOL,0)/SUM(VOL,0);





BB BAND
指南针布林线宽指标 
n=30
Var1:=MA(CLOSE,N);
Var2:=Var1+2*STD(CLOSE,N);
变盘: 5, POINTDOT;
布林宽度: (Var2-Var1)/Var1*100;
警戒: 30, POINTDOT;
===================================
CBW
指南针成本带宽
n1=97.5,n2=2.5
CBW: 100*(COST(N1)-COST(N2))/COST(N1);
=============================================
CBXQD
指南针成本均线强度
n=4,n1=5,n2=13,n3=34
Var1:=AMOUNT/(100*VOL);
Var2:=MA(Var1,N1);
Var3:=MA(Var1,N2);
Var4:=MA(Var1,N3);
Var5:=DMA(CLOSE,VOL/CAPITAL);
CYR5: 100*(Var2-REF(Var2,N))/REF(Var2,N);
CYR13: 100*(Var3-REF(Var3,N))/REF(Var3,N);
CYR34: 100*(Var4-REF(Var4,N))/REF(Var4,N);
CYR无穷: 100*(Var5-REF(Var5,N))/REF(Var5,1);
=============================================
CKD
指南针相对价位
Var1:=AMOUNT/(100*VOL);
Var2:=MA(Var1,13);
Var3:=DMA(Var1,VOL/CAPITAL);
CKDP: 100*(Var2-COST(0))/(COST(100)-COST(0));
CKDW: 100*(Var3-COST(0))/(COST(100)-COST(0));
============================================================
CMACD
指南针CMACD指标
n1=5,n2=13
Var1:=AMOUNT/(100*VOL);
Var2:=MA(Var1,N1);
Var3:=MA(Var1,N2);
CMACD: 100*(Var2-Var3)/Var3, COLORSTICK;
====================================================================
CYB
优化布林线
n=20
MB: MA(CLOSE,N);
上轨: MB+STD(CLOSE,N);
下轨: MB-STD(CLOSE,N);
上极限: MB+2*STD(CLOSE,N);
下极限: MB-2*STD(CLOSE,N);
STICKLINE(open>=close ,close ,open,9,0 ),COLORaaaaaa; 
STICKLINE(open>=close ,close ,open,6,0 ),COLORbbbbbb;
STICKLINE(open>=close ,close ,open,2.4,0 ),COLORcccccc;
STICKLINE(open>=close ,close ,open,1.1,0 ),COLORdddddd;

STICKLINE(close>open,close,open,9,0 ),COLOr6666cc;
STICKLINE(close>open,close,open,6 ,0 ),COLOR7777dd; 
STICKLINE(close>open,close,open,2.4 ,0 ),COLOR8888ee; 
STICKLINE(close>open,close,open,1.1 ,0 ),COLOR9999ff;

STICKLINE(close>open,open,low,0.5,0 ),COLOR1199ff; 
STICKLINE(close>open,close,HIGH,0.5 ,0 ),COLOR1199ff;
STICKLINE(open>=close,close,low,0.5 ,0 ),COLORcccccc; 
STICKLINE(open>=close,open,HIGH,0.5 ,0 ),COLORcccccc;
============================================================
CYC
指南针成本均线
n1=5,n2=13,n3=34
Var1:=AMOUNT/(100*VOL);
短线成本均线: MA(Var1,N1);
中线成本均线: MA(Var1,N2);
长线成本均线: MA(Var1,N3);
无穷成本均线: DMA(CLOSE,VOL/CAPITAL);
STICKLINE(open>=close ,close ,open,9,0 ),COLORaaaaaa; 
STICKLINE(open>=close ,close ,open,6,0 ),COLORbbbbbb;
STICKLINE(open>=close ,close ,open,2.4,0 ),COLORcccccc;
STICKLINE(open>=close ,close ,open,1.1,0 ),COLORdddddd;

STICKLINE(close>open,close,open,9,0 ),COLOr6666cc;
STICKLINE(close>open,close,open,6 ,0 ),COLOR7777dd; 
STICKLINE(close>open,close,open,2.4 ,0 ),COLOR8888ee; 
STICKLINE(close>open,close,open,1.1 ,0 ),COLOR9999ff;

STICKLINE(close>open,open,low,0.5,0 ),COLOR1199ff; 
STICKLINE(close>open,close,HIGH,0.5 ,0 ),COLOR1199ff;
STICKLINE(open>=close,close,low,0.5 ,0 ),COLORcccccc; 
STICKLINE(open>=close,open,HIGH,0.5 ,0 ),COLORcccccc;
=================================================
CYC2
成本均线
p1=5,p2=13,p3=34
CYC1:0.01*EMA(AMOUNT,P1)/EMA(VOL,P1);
CYC2:0.01*EMA(AMOUNT,P2)/EMA(VOL,P2);
CYC3:0.01*EMA(AMOUNT,P3)/EMA(VOL,P3);
CYC∞:DMA(AMOUNT/(100*VOL),VOL/(100*FINANCE(7)));
================================================
CYD
承接因子
n=21
CYDS:WINNER(CLOSE)/(VOL/CAPITAL);
CYDN:WINNER(CLOSE)/MA(VOL/CAPITAL,N);
============================================
CYD2
承接因子
A:=WINNER(CLOSE )*CAPITAL;
承接因子:A/VOL;
=====================================================
CYDD
指南针动态承接因子
Var1:=WINNER(CLOSE);
Var2:=DMA(Var1,VOL/CAPITAL);
Var3:=DMA(VOL,VOL/CAPITAL)/CAPITAL;
CYDD: Var1/Var3;
CYDD1: Var2/Var3;
1, POINTDOT;
=========================================================================
CYE
市场趋势
MAL:=MA(CLOSE,5);
MAS:=MA(MA(CLOSE,20),5);
CYEL:(MAL-REF(MAL,1))/REF(MAL,1)*100;
CYES:(MAS-REF(MAS,1))/REF(MAS,1)*100;
=========================================================================
CYF
市场能量
n=21
HSL:=VOL/CAPITAL*100;
CYF:100-100/(1+EMA(HSL,N)*100);
========================================================================
CYOBV
指南针优化累积能量线
n=34
NOBV1: SUM(IF(CLOSE>REF(CLOSE,1),VOL,IF(CLOSE<REF(CLOSE,1),0-VOL,0)),N)/CAPITAL;
========================================================================
CYQKL
指南针博弈K线长度
100*(WINNER(CLOSE)-WINNER(OPEN)), COLORSTICK;
========================================================================
CYR
市场强弱
n=13,m=5
DIVE:=0.01*EMA(AMOUNT,N)/EMA(VOL,N);
CYR:(DIVE/REF(DIVE,1)-1)*100;
MACYR:MA(CYR,M);
======================================================================
CYS
指南针盈亏指标
n1=5,n2=13,n3=34
Var1:=AMOUNT/(100*VOL);
Var2:=MA(Var1,N1);
Var3:=MA(Var1,N2);
Var4:=MA(Var1,N3);
Var5:=DMA(CLOSE,VOL/CAPITAL);
CYS5: 100*(CLOSE-Var2)/Var2;
CYS13: 100*(CLOSE-Var3)/Var3;
CYS34: 100*(CLOSE-Var4)/Var4;
CYS无穷: 100*(CLOSE-Var5)/Var5;
============================
CYS2
市场盈亏
CYC13:=0.01*EMA(AMOUNT,13)/EMA(VOL,13);
CYS:(CLOSE-CYC13)/CYC13*100;
============================
CYW
主力控盘
VAR1:=CLOSE-LOW;
VAR2:=HIGH-LOW;
VAR3:=CLOSE-HIGH;
VAR4:=IF(CLOSE>=0,(VAR1/VAR2+VAR3/VAR2)*VOL,(VAR3/VAR2+VAR1/VAR2)*VOL);
CYW: SUM(VAR4,10)/10000, COLORSTICK;
=======================================
CYW-YJJ
主力控盘
p1=16,p2=8,p3=45
VAR1:=1;
VAR2:=CLOSE-REF(CLOSE,1);
VAR3:=IF(CLOSE-REF(CLOSE,1)>=0,VAR2,0);
VAR4:=REF(CLOSE,1)-CLOSE;
VAR5:=IF(CLOSE-REF(CLOSE,1)<=0,VAR4,0);
VAR6:=SUM(VAR3,P1)/SUM(VAR5,P1);
VAR7:=100-100/(1+VAR6);
VAR8:=EMA(VAR7,P1);
VAR9:=EMA(VAR8,P2);
VARA:=EMA(VAR8,P3);
MO: (VAR8-VARA)*VAR1;
ML: (VAR9-VARA)*VAR1;
MODE: MO*VAR1, COLORSTICK;
======================================================
DKBL
指南针成本多空布林线
n=10,p=3
Var1:=AMOUNT/(100*VOL);
Var2:=MA(Var1,3);
Var3:=MA(Var1,6);
Var4:=MA(Var1,12);
Var5:=MA(Var1,24);
BBI: (Var2+Var3+Var4+Var5)/4;
UPR: BBI+P*STD(BBI,N);
DWN: BBI-P*STD(BBI,N);
STICKLINE(open>=close ,close ,open,9,0 ),COLORaaaaaa; 
STICKLINE(open>=close ,close ,open,6,0 ),COLORbbbbbb;
STICKLINE(open>=close ,close ,open,2.4,0 ),COLORcccccc;
STICKLINE(open>=close ,close ,open,1.1,0 ),COLORdddddd;

STICKLINE(close>open,close,open,9,0 ),COLOr6666cc;
STICKLINE(close>open,close,open,6 ,0 ),COLOR7777dd; 
STICKLINE(close>open,close,open,2.4 ,0 ),COLOR8888ee; 
STICKLINE(close>open,close,open,1.1 ,0 ),COLOR9999ff;

STICKLINE(close>open,open,low,0.5,0 ),COLOR1199ff; 
STICKLINE(close>open,close,HIGH,0.5 ,0 ),COLOR1199ff;
STICKLINE(open>=close,close,low,0.5 ,0 ),COLORcccccc; 
STICKLINE(open>=close,open,HIGH,0.5 ,0 ),COLORcccccc;
=======================================================
JBCYS
CYS越低的股涨得越好。
JBCYF: MA(CLOSE,13)*(CLOSE-MA(CLOSE,13));
====================================
MYP
指南针年最大收益指标
Var1:=LLV(HIGH,240);
MYP: 100*(CLOSE-Var1)/Var1;
=========================================
PAS1
指南针筹码穿透率
Var1:=100*VOL/CAPITAL;
Var2:=100*(WINNER(CLOSE)-REF(WINNER(CLOSE),1))
筹码穿透率: Var2/Var1, VOLSTICK;
==================================================
P-CBY
博弈均线
博弈均线: MA(WINNER(CLOSE)*100,3);
Var1:=COST(0);
Var2:=COST(5);
Var3:=COST(45);
Var4:=COST(55);
Var5:=COST(95);
Var6:=COST(100);
底部线: (Var4-Var3)*100/(Var6-Var1);
牛熊线: (Var5-Var2)*100/(Var6-Var1);
=======================================================
RPY
指南针年相对价位
n=240
Var1:=REF(HHV(CLOSE,N),1);
Var2:=REF(LLV(CLOSE,N),1);
100*(CLOSE-Var2)/(Var1-Var2);
RPY2
指南针两年相对价位
Var1:=REF(HHV(CLOSE,480),1);
Var2:=REF(LLV(CLOSE,480),1);
100*(CLOSE-Var2)/(Var1-Var2);
==========================================================
SDR
指南针锁定筹码  
Var1:=1.1*CLOSE;
Var2:=0.9*CLOSE;
Var3:=100*(WINNER(Var1)-WINNER(Var2));
锁定筹码: 100-Var3;
博奕K线
Var1:=MA(WINNER(CLOSE)*100,3); 
底部线: (COST(55)-COST(45))*100/(COST(97)-COST(3)); 
牛熊线: (COST(65)-COST(35))*100/(COST(97)-COST(3)),COLORRED; 
压力线: (COST(95)-COST(5))*100/(COST(97)-COST(3)); 
STICKLINE(WINNER(CLOSE)*100>=WINNER(OPEN)*100,WINNER(OPEN)*100,WINNER(CLOSE)*100,5,1),COLORRED; 
STICKLINE(WINNER(OPEN)*100>WINNER(CLOSE)*100,WINNER(CLOSE)*100,WINNER(OPEN)*100,5,0),COLORGREEN; 
STICKLINE(WINNER(CLOSE)*100>=WINNER(OPEN)*100,WINNER(CLOSE)*100,WINNER(HIGH)*100,0.5,1),COLORRED; 
STICKLINE(WINNER(CLOSE)*100>=WINNER(OPEN)*100,WINNER(OPEN)*100,WINNER(LOW)*100,0.5,1),COLORRED; 
STICKLINE(WINNER(OPEN)*100>WINNER(CLOSE)*100,WINNER(CLOSE)*100,WINNER(LOW)*100,0.5,0),COLORGREEN; 
STICKLINE(WINNER(OPEN)*100>WINNER(CLOSE)*100,WINNER(OPEN)*100,WINNER(HIGH)*100,0.5,0),COLORGREEN; 
DRAWTEXT(CLOSE/OPEN>88,LOW,'');
博奕柱线
ABS(WINNER(CLOSE)-WINNER(OPEN))*100, VOLSTICK;



---


# b站：https://www.bilibili.com/opus/1210800501123186727

{ == 通达信0AMV副图代码v1.2学习版：活筹指数(880007) == }

{ == 附图安装方法参照往期视频，本版本仅建议添加在活筹指数附图使用 ==}

OAMVN:=12; OAMVM:=13; OAMVLAG:=1; 

OAMVA:=10971.22; OAMVK:=0.79;

OAMVV1:=SMA(AMOUNT,OAMVN,1)/1000000;

OAMVV3:=MA(REF(CLOSE,OAMVLAG),OAMVM);

OAMVO:=OAMVA+OAMVV1*OPEN/OAMVV3*0.1*OAMVK;

OAMVH:=OAMVA+OAMVV1*HIGH/OAMVV3*0.1*OAMVK;

OAMVL:=OAMVA+OAMVV1*LOW/OAMVV3*0.1*OAMVK;

OAMVC:=OAMVA+OAMVV1*CLOSE/OAMVV3*0.1*OAMVK;

OAMV开盘:OAMVO,NODRAW; OAMV最高:OAMVH,NODRAW;

OAMV最低:OAMVL,NODRAW; OAMV收盘:OAMVC,NODRAW;

OAMV昨收:=REF(OAMVC,1); OAMV涨幅:(OAMVC-OAMV昨收)/OAMV昨收*100,NODRAW;

DRAWTEXT_FIX(ISLASTBAR,0.01,0.01,0,'声明: 本公式仅供学习交流与技术研究,不构成投资建议或收益承诺;BY-红梅金属变体'),COLORGRAY;

DRAWTEXT_FIX(ISLASTBAR,0.01,0.09,0,'提示: OAMV涨幅为拟合收盘派生参考,不代表精准还原每日涨跌幅,如有疑问请看视频'),COLORGRAY;

OAMV生命线:EMA(OAMVC,12),COLORCYAN,LINETHICK1;

STICKLINE(OAMVC>=OAMVO,OAMVC,OAMVO,3,0),COLORRED;

STICKLINE(OAMVC>=OAMVO,OAMVH,MAX(OAMVC,OAMVO),0,0),COLORRED;

STICKLINE(OAMVC>=OAMVO,MIN(OAMVC,OAMVO),OAMVL,0,0),COLORRED;

STICKLINE(OAMVC<OAMVO,OAMVC,OAMVO,3,0),COLORGREEN;

STICKLINE(OAMVC<OAMVO,OAMVH,MAX(OAMVC,OAMVO),0,0),COLORGREEN;

STICKLINE(OAMVC<OAMVO,MIN(OAMVC,OAMVO),OAMVL,0,0),COLORGREEN;

OAMVH60:=HHV(OAMVH,60); OAMVL60:=LLV(OAMVL,60);

OAMVR60:=OAMVH60-OAMVL60; OAMV标记位:=OAMVL-OAMVR60*0.025;

DRAWTEXT(CURRBARSCOUNT<=180,OAMV标记位,VAR2STR(OAMV涨幅,2)),COLORGRAY;

{ == 结束复制，声明如下 == }

---

# 博客：https://blog.sina.com.cn/s/blog_693ee8b70102ds0y.html

oamv活筹指数大智慧版
使用说明
0AmV活筹指数及0DmV死筹指数均以K线形式表示。活筹指数上、下震荡剧烈程度比0号指数大得多。活筹增多时死筹自然减少，反之亦然。活筹指数加死筹指数大约等于0号指数。
    主要作用：
   用0AmV指数比例变化研判大势后市走势，及判断大盘的顶部及底部区域。
    使用要领：
   一、近期流入股市的资金多了，活筹就增多，能推动股指上涨，反之则会逐渐引发股指回调；
   二、每轮上升行情启动后大盘活筹指数都迅速增加，但增加到一定程度后再
不能继续增加，而进入震荡横盘或下降时，上升行情就将结束了；
   三、每轮中级上升行情完结时活筹指数均比启动前高出四、五倍以上。中级下跌行情完结时活筹指数又仅相当于前个顶部区域的四、五分之一或更少；
    四、0号指数上升0AMV指数下降属牛背离，预示上升行情将到顶；
    五、0号指数上升一定幅度后，0AMV指数的CYE指标由正变负时大盘即将到顶；
    六、 0号指数下降0AMV指数上升属熊背离，预示行情将到底。
    七、当0AMV趋势向上，则资金面上是牛市，反过来是熊市。而0AMV横向运动，则是资金的平衡状态，需密切关注，一旦新的趋势形成，则可顺势而为。
   八、如果0AMV向上而沪深指数下跌，这个下跌并不可怕。如果沪深指数上涨但0AMV下跌，则是主力拉抬指标股掩护出货。
源码：
{0AMV活筹指数}
Var1:=AMOUNT;
Var2:=SMA(Var1,10,1);
Var3:=REF(Var2,1);
STICKLINE(Var2>Var3,Var2,Var3,7,0),colorred;
STICKLINE(Var2<Var3,Var2,Var3,7,0),colorgreen;


---

# github项目

https://github.com/lpeiyi/0AMV
https://github.com/pulsiferkelley87-a11y/amv-site
https://github.com/WdBlink/compass-0amv-imitate


---

# 本地进阶1AMV：D:\BaiduNetdiskDownload\通达信活跃市值_按序安装TXT