# -*- coding: utf-8 -*-
"""CAPM alpha stock selection strategy for DQT."""

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
        "future_cost_fee": 1,
        "stock_cost_fee": 2.5,
        "rate": 0.02,
        "margin_rate": 1,
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
    reg_kdata("day", 1)
    reg_factor(["market_cap_2"])

    trading_days = get_trading_days(
        "sse",
        begin_date=config["strategy"]["begin_date"],
        end_date=config["strategy"]["end_date"],
    )
    trading_days = pd.to_datetime(pd.Series(trading_days))

    context.operation_days = (
        trading_days[trading_days.dt.month != trading_days.dt.month.shift(1)]
        .dt.strftime("%Y-%m-%d")
        .tolist()
    )
    context.stock_count = len(context.target_list) - 1
    context.benchmark_index = context.stock_count
    context.lookback_days = LOOKBACK_DAYS
    context.max_position = MAX_POSITION
    context.stock_count_to_hold = STOCK_COUNT


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

    close_panel = (
        data.pivot(index="time", columns="target_index", values="close")
        .sort_index()
        .astype(float)
    )

    required_columns = list(range(context.stock_count)) + [context.benchmark_index]
    if not set(required_columns).issubset(set(close_panel.columns)):
        return None
    return close_panel[required_columns]


def _get_market_cap(context):
    factor_data = get_reg_factor(
        reg_idx=0,
        target_list=list(range(context.stock_count)),
        length=1,
        df=True,
    )
    if factor_data is None or len(factor_data) == 0:
        return None

    market_cap = (
        factor_data[factor_data["factor"] == "market_cap_2"]
        .drop_duplicates("target_index", keep="last")
        .set_index("target_index")["value"]
        .reindex(range(context.stock_count))
        .astype(float)
    )
    market_cap = market_cap.replace([np.inf, -np.inf], np.nan)
    return market_cap


def _calculate_capm_alpha(stock_returns, market_returns):
    alpha_list = []
    for target in stock_returns.columns:
        reg_df = pd.DataFrame(
            {
                "stock_return": stock_returns[target].astype(float).values,
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
    account = get_account()
    positions = pd.Series(account.volume_long()).reindex(range(context.stock_count)).fillna(0)

    for target_index in range(context.stock_count):
        target_percent = float(target_weights.get(target_index, 0.0))
        if target_percent > 0:
            order_target_percent(
                account_index=0,
                target_index=target_index,
                target_percent=target_percent,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                price=0,
            )
            print(context.target_list[target_index], "调多仓到仓位", target_percent)
        elif positions.iloc[target_index] > 0:
            order_target_percent(
                account_index=0,
                target_index=target_index,
                target_percent=0,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                price=0,
            )
            print("平仓:", context.target_list[target_index], "持仓数量:", positions.iloc[target_index])


def on_bar(context):
    current_day = datetime.datetime.strftime(context.now, "%Y-%m-%d")
    if current_day not in context.operation_days:
        return

    close_panel = _get_close_panel(context)
    if close_panel is None or close_panel.isna().any().any():
        return

    market_cap = _get_market_cap(context)
    if market_cap is None:
        return

    stock_close = close_panel.loc[:, range(context.stock_count)]
    benchmark_close = close_panel[context.benchmark_index]

    stock_returns = stock_close.pct_change().iloc[1:, :]
    market_returns = benchmark_close.pct_change().iloc[1:]

    alpha = _calculate_capm_alpha(stock_returns, market_returns)
    candidates = alpha.dropna().sort_values().tail(context.stock_count_to_hold).index
    if len(candidates) == 0:
        return

    candidate_market_cap = market_cap.loc[candidates].dropna()
    candidate_market_cap = candidate_market_cap[candidate_market_cap > 0]
    if candidate_market_cap.sum() <= 0:
        return

    target_weights = context.max_position * candidate_market_cap / candidate_market_cap.sum()
    _order_to_target_weights(context, target_weights)


if __name__ == "__main__":
    run_backtest(config=config, init=init, on_bar=on_bar)


def on_order_status(context, order):
    pass


def on_order_execution(context, trade):
    pass
