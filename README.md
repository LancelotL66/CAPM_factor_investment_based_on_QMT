# CAPM 因子模型策略

这是一个基于 DQT Python Toolbox (`dqtrader`) 的沪深 300 成分股 CAPM Alpha 选股策略。

策略以沪深 300 指数作为市场基准，每月第一个交易日调仓。调仓时使用过去 20 个交易日的个股收益率与指数收益率做 CAPM 回归，取回归截距 Alpha 排名前 50 的股票，并按流通市值因子 `market_cap_2` 加权配置仓位。

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `CAPM因子模型.py` | DQT 策略源码 |
| `策略绩效报告-CAPM因子模型.pdf` | DQT 导出的策略绩效报告 |

## 运行环境

- Windows x64
- Python 3.9+
- DQT 客户端已打开并正常登录
- Python 包：
  - `dqtrader`
  - `numpy`
  - `pandas`
  - `statsmodels`

安装依赖示例：

```powershell
pip install dqtrader numpy pandas statsmodels
```

如果使用 Conda，建议在专用环境中安装：

```powershell
conda create -n dqt python=3.12 pip -y
conda activate dqt
pip install dqtrader numpy pandas statsmodels
```

## 策略参数

主要参数集中在脚本顶部：

```python
BEGIN_DATE = "2023-01-01"
END_DATE = "2026-06-03"
BENCHMARK_CODE = "SSE.000300"
STOCK_COUNT = 50
LOOKBACK_DAYS = 20
MAX_POSITION = 0.9
```

含义：

| 参数 | 说明 |
| --- | --- |
| `BEGIN_DATE` | 回测开始日期 |
| `END_DATE` | 回测结束日期 |
| `BENCHMARK_CODE` | CAPM 回归使用的市场基准 |
| `STOCK_COUNT` | 每次调仓持有股票数量 |
| `LOOKBACK_DAYS` | CAPM 回归使用的历史窗口 |
| `MAX_POSITION` | 股票组合最高总仓位 |

股票池在脚本启动时生成：

```python
stock_pool = get_code_list("hs300", date=BEGIN_DATE)["code"].tolist()
target_list = stock_pool + [BENCHMARK_CODE]
```

即：前面是沪深 300 成分股，最后一个标的是沪深 300 指数。

## 策略逻辑

1. 读取回测起始日的沪深 300 成分股。
2. 将沪深 300 指数追加到 `target_list` 末尾，用作 CAPM 市场收益率。
3. 注册日频行情数据。
4. 注册流通市值因子 `market_cap_2`。
5. 每月第一个交易日执行调仓。
6. 对每只股票使用过去 20 个交易日收益率做回归：

```text
stock_return = alpha + beta * market_return + error
```

7. 选择 Alpha 最高的 50 只股票。
8. 在选中股票内按 `market_cap_2` 市值加权。
9. 组合总仓位控制在 90%。
10. 不在候选池内的原持仓调仓到 0。

## 运行方式

确保 DQT 客户端已打开并登录，然后在策略目录运行：

```powershell
python .\CAPM因子模型.py
```

或使用指定解释器：

```powershell
D:\anaconda\envs\dqt\python.exe .\CAPM因子模型.py
```

## 注意事项

- 本策略依赖 DQT 客户端权限，离线状态下无法正常获取行情、因子或运行回测。
- `target_list` 中最后一个标的是指数，不参与股票交易。
- 当前股票池固定为 `BEGIN_DATE` 当天的沪深 300 成分股，没有做动态成分股调整。
- 当前策略没有额外过滤 ST、停牌、涨跌停、成交额过低等交易约束。
- 代码文件包含中文，建议使用 UTF-8 编码打开和提交。

## 免责声明

本项目仅用于量化策略研究和教学示例，不构成任何投资建议。历史回测结果不代表未来收益。
