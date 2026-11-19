"""
Relative Strength (RS) Rating calculation (1-99)
Based on William O'Neil / Mark Minervini IBD methodology:
Weighted performance over 12 months:
40% Q1 (last 3 months) + 20% Q2 + 20% Q3 + 20% Q4
Percentile ranked across the entire market (1 to 99).
"""
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

def calculate_stock_rs_score(df: pd.DataFrame) -> float:
    """
    Calculate raw RS score for a single stock using 4 quarters weighting:
    Score = 0.4 * R_3m + 0.2 * R_6m + 0.2 * R_9m + 0.2 * R_12m
    """
    if len(df) < 63:
        return 0.0

    closes = df['close'].values
    p_current = closes[-1]

    # Quarter closes (approx 63 trading days per quarter)
    p_3m = closes[-63] if len(closes) >= 63 else closes[0]
    p_6m = closes[-126] if len(closes) >= 126 else closes[0]
    p_9m = closes[-189] if len(closes) >= 189 else closes[0]
    p_12m = closes[-250] if len(closes) >= 250 else closes[0]

    r1 = (p_current - p_3m) / p_3m if p_3m > 0 else 0
    r2 = (p_3m - p_6m) / p_6m if p_6m > 0 else 0
    r3 = (p_6m - p_9m) / p_9m if p_9m > 0 else 0
    r4 = (p_9m - p_12m) / p_12m if p_12m > 0 else 0

    score = (0.4 * r1) + (0.2 * r2) + (0.2 * r3) + (0.2 * r4)
    return score


def calculate_market_rs_ratings(stock_dfs: Dict[str, pd.DataFrame]) -> Dict[str, int]:
    """
    Given a dictionary of {symbol: ohlcv_df},
    calculate raw score for each, sort, and assign percentile RS Rating (1 to 99).
    """
    scores = {}
    for sym, df in stock_dfs.items():
        if df is not None and len(df) >= 60:
            scores[sym] = calculate_stock_rs_score(df)

    if not scores:
        return {}

    series = pd.Series(scores)
    # Calculate percentile rank from 1 to 99
    ranks = series.rank(pct=True) * 99
    ratings = ranks.round().astype(int).clip(1, 99).to_dict()
    return ratings
