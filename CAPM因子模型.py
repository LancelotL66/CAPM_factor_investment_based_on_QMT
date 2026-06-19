# -*- coding: utf-8 -*-
"""基于 CAPM alpha 的沪深 300 成分股月度选股策略（DQT/dqtrader）。"""

import datetime

import numpy as np
import pandas as pd
import statsmodels.api as sm
from dqtrader import *


BEGIN_DATE = "2023-01-01"
END_DATE = "2026-06-03"
BENCHMARK_CODE = "SSE.000300"
STOCK_COUNT = 50
LOOKBACK_DAYS = 20
MAX_POSITION = 0.9


stock_pool = get_code_list("hs300", date=BEGIN_DATE)["code"].tolist()
target_list = stock_pool + [BENCHMARK_CODE]


config = {
    "account": {
        "initial_cash": 10_000_000,
        "future_cost_fee": 1.0,
        "stock_cost_fee": 2.5,
        "risk_free_rate": 0.02,
        "margin_rate": 1.0,
        "slide_price": 0,
        "price_loc": 1,
        "deal_type": 0,
        "limit_type": 0,
    },
    "strategy": {
        "name": "CAPM因子模型",
        "target_list": target_list,
        "frequency": "day",
        "fre_num": 1,
        "begin_date": BEGIN_DATE,
        "end_date": END_DATE,
        "fq": FQType.NA,
        "benchmark": "sse.000300",
    },
}


def init(context):
    """注册日线和流通市值因子，生成每月首个交易日列表。"""
    reg_kdata(frequency="day", frequency_num=1)
    reg_factor(factors=["market_cap_2"])

    trading_days = get_trading_days(
        "sse",
        begin_date=BEGIN_DATE,
        end_date=END_DATE,
    )
    trading_days = pd.to_datetime(pd.Series(trading_days))
    context.operation_days = (
        trading_days[trading_days.dt.month != trading_days.dt.month.shift(1)]
        .dt.strftime("%Y-%m-%d")
        .tolist()
    )

    # target_list 最后一个标的是沪深300基准，只参与回归，不参与交易。
    context.stock_pool_size = len(context.target_list) - 1
    context.benchmark_index = context.stock_pool_size
    context.lookback_days = LOOKBACK_DAYS
    context.max_position = MAX_POSITION
    context.stock_count_to_hold = min(STOCK_COUNT, context.stock_pool_size)


def _get_close_panel(context):
    data = get_reg_kdata(
        reg_idx=0,
        target_list=[],
        length=context.lookback_days,
        fill_up=True,
        df=True,
    )
    if data is None or len(data) == 0:
        return None

    # DQT 在 fill_up=True 的多标的窗口中可能返回重复的
    # (time, target_index) 记录；pivot 要求组合键唯一。
    data = (
        data.sort_values(["time", "target_index"])
        .drop_duplicates(subset=["time", "target_index"], keep="last")
    )
    close_panel = (
        data.pivot(index="time", columns="target_index", values="close")
        .sort_index()
        .astype(float)
    )
    required_columns = list(range(context.stock_pool_size)) + [context.benchmark_index]
    if not set(required_columns).issubset(close_panel.columns):
        return None

    close_panel = close_panel[required_columns]
    if len(close_panel) < context.lookback_days:
        return None
    return close_panel


def _get_market_cap(context):
    # DQT 的 get_reg_factor 固定返回 DataFrame，没有 df 参数。
    factor_data = get_reg_factor(
        reg_idx=0,
        # DQT 运行时要求这里传标的代码，而不是 target_index 整数。
        target_list=context.target_list[:context.stock_pool_size],
        length=1,
    )
    if factor_data is None or len(factor_data) == 0:
        return None

    market_cap = (
        factor_data[factor_data["factor"] == "market_cap_2"]
        .drop_duplicates("target_index", keep="last")
        .set_index("target_index")["value"]
        .reindex(range(context.stock_pool_size))
        .astype(float)
    )
    return market_cap.replace([np.inf, -np.inf], np.nan)


def _calculate_capm_alpha(stock_returns, market_returns):
    alpha_list = []
    for target_index in stock_returns.columns:
        reg_df = pd.DataFrame(
            {
                "stock_return": stock_returns[target_index].astype(float).values,
                "market_return": market_returns.astype(float).values,
            }
        ).replace([np.inf, -np.inf], np.nan).dropna()

        if len(reg_df) < 5:
            alpha_list.append(np.nan)
            continue

        x = sm.add_constant(reg_df["market_return"].values)
        y = reg_df["stock_return"].values
        result = sm.OLS(y, x).fit()
        alpha_list.append(result.params[0])

    return pd.Series(alpha_list, index=stock_returns.columns)


def _order_to_target_weights(context, target_weights):
    positions = pd.Series(
        np.asarray(get_account().volume_long()),
        index=range(len(context.target_list)),
        dtype=float,
    ).reindex(range(context.stock_pool_size)).fillna(0)

    for target_index in range(context.stock_pool_size):
        target_percent = float(target_weights.get(target_index, 0.0))
        if target_percent > 0:
            order_target_percent(
                target_index=target_index,
                target_percent=target_percent,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                price=0.0,
            )
            print(context.target_list[target_index], "调多仓到权重", target_percent)
        elif positions.loc[target_index] > 0:
            # DQT 的调仓函数中 side 表示目标持仓方向；多仓调至0仍使用 BUY。
            order_target_percent(
                target_index=target_index,
                target_percent=0.0,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                price=0.0,
            )
            print("平仓:", context.target_list[target_index], "持仓数量:", positions.loc[target_index])


def on_bar(context):
    """每日触发，只在每月首个交易日计算 CAPM alpha 并调仓。"""
    current_day = datetime.datetime.strftime(context.now, "%Y-%m-%d")
    if current_day not in context.operation_days:
        return

    close_panel = _get_close_panel(context)
    if close_panel is None or close_panel.isna().any().any():
        return

    market_cap = _get_market_cap(context)
    if market_cap is None:
        return

    stock_close = close_panel.loc[:, range(context.stock_pool_size)]
    benchmark_close = close_panel[context.benchmark_index]
    stock_returns = stock_close.pct_change().iloc[1:, :]
    market_returns = benchmark_close.pct_change().iloc[1:]

    alpha = _calculate_capm_alpha(stock_returns, market_returns)
    candidates = alpha.dropna().nlargest(context.stock_count_to_hold).index
    if len(candidates) == 0:
        return

    candidate_market_cap = market_cap.loc[candidates].dropna()
    candidate_market_cap = candidate_market_cap[candidate_market_cap > 0]
    if candidate_market_cap.empty or candidate_market_cap.sum() <= 0:
        return

    target_weights = context.max_position * candidate_market_cap / candidate_market_cap.sum()
    _order_to_target_weights(context, target_weights)


if __name__ == "__main__":
    run_backtest(config=config, init=init, on_bar=on_bar)
