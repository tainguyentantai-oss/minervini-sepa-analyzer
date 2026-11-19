"""
Mark Minervini SEPA (Specific Order Execution Method) Analysis Engine:
1. Trend Template (8 Criteria)
2. Pivot Points & Breakout Detection (Volume +50%)
3. VCP (Volatility Contraction Pattern) Analysis
"""
from typing import Dict, Any, List
import pandas as pd
import numpy as np

def calculate_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate moving averages (MA20, MA50, MA150, MA200),
    52-week highs/lows, and volume average.
    """
    df = df.copy()
    if len(df) < 20:
        return df

    # Moving averages
    df['ma20'] = df['close'].rolling(window=20).mean()
    df['ma50'] = df['close'].rolling(window=50).mean()
    df['ma150'] = df['close'].rolling(window=150).mean()
    df['ma200'] = df['close'].rolling(window=200).mean()

    # 50-day Volume Average
    df['vol_ma50'] = df['volume'].rolling(window=50).mean()

    # 52-week (approx 250 trading days) High and Low
    window_52w = min(250, len(df))
    df['high_52w'] = df['high'].rolling(window=window_52w).max()
    df['low_52w'] = df['low'].rolling(window=window_52w).min()

    # Slope of MA200 over 1 month (~20 trading days)
    df['ma200_1m_ago'] = df['ma200'].shift(20)

    return df


def evaluate_trend_template(df: pd.DataFrame, rs_rating: int = 80) -> Dict[str, Any]:
    """
    Evaluate the 8 Mark Minervini Trend Template criteria:
    1. Giá > MA50, MA150, MA200
    2. MA150 > MA200
    3. MA200 hướng lên (>= 1 tháng)
    4. MA50 > MA150 & MA200
    5. Giá > MA50
    6. Giá cao hơn đáy 52 tuần ít nhất 25-30%
    7. Giá trong phạm vi 25% tính từ đỉnh 52 tuần
    8. RS Rating >= 70 (ưu tiên 80+)
    """
    if len(df) < 50:
        return {
            'score': 0,
            'max_score': 8,
            'status': 'KHÔNG ĐẠT (Chưa đủ dữ liệu)',
            'criteria': []
        }

    latest = df.iloc[-1]
    close = float(latest['close'])
    ma50 = float(latest.get('ma50', 0) or 0)
    ma150 = float(latest.get('ma150', 0) or 0)
    ma200 = float(latest.get('ma200', 0) or 0)
    ma200_1m = float(latest.get('ma200_1m_ago', 0) or 0)
    high_52w = float(latest.get('high_52w', close) or close)
    low_52w = float(latest.get('low_52w', close) or close)

    criteria = []

    # 1. Giá > MA50, MA150, MA200
    cond1 = (close > ma50) and (close > ma150) and (close > ma200) if (ma150 > 0 and ma200 > 0) else (close > ma50)
    criteria.append({
        'id': 1,
        'title': '1. Giá > MA50, MA150, MA200',
        'passed': bool(cond1),
        'detail': f"Giá: {close:,.0f} | MA50: {ma50:,.0f} | MA150: {ma150:,.0f} | MA200: {ma200:,.0f}"
    })

    # 2. MA150 > MA200
    cond2 = (ma150 > ma200) if (ma150 > 0 and ma200 > 0) else True
    criteria.append({
        'id': 2,
        'title': '2. MA150 > MA200',
        'passed': bool(cond2),
        'detail': f"MA150: {ma150:,.0f} | MA200: {ma200:,.0f}"
    })

    # 3. MA200 hướng lên (>= 1 tháng)
    cond3 = (ma200 >= ma200_1m) if (ma200 > 0 and ma200_1m > 0) else True
    criteria.append({
        'id': 3,
        'title': '3. MA200 hướng lên (>= 1 tháng)',
        'passed': bool(cond3),
        'detail': f"MA200 hiện tại: {ma200:,.0f} vs 1 tháng trước: {ma200_1m:,.0f}"
    })

    # 4. MA50 > MA150 và MA200
    cond4 = (ma50 > ma150) and (ma50 > ma200) if (ma150 > 0 and ma200 > 0) else True
    criteria.append({
        'id': 4,
        'title': '4. MA50 > MA150, MA200',
        'passed': bool(cond4),
        'detail': f"MA50: {ma50:,.0f} > MA150: {ma150:,.0f} & MA200: {ma200:,.0f}"
    })

    # 5. Giá > MA50
    cond5 = (close > ma50) if ma50 > 0 else True
    criteria.append({
        'id': 5,
        'title': '5. Giá > MA50',
        'passed': bool(cond5),
        'detail': f"Giá: {close:,.0f} > MA50: {ma50:,.0f}"
    })

    # 6. Giá trong 25% đỉnh 52 tuần
    diff_from_high = ((high_52w - close) / high_52w * 100) if high_52w > 0 else 0
    cond6 = diff_from_high <= 25.0
    criteria.append({
        'id': 6,
        'title': '6. Giá trong 25% đỉnh 52 tuần',
        'passed': bool(cond6),
        'detail': f"Cách đỉnh 52 tuần ({high_52w:,.0f}): -{diff_from_high:.1f}% (<= 25%)"
    })

    # 7. Giá cao hơn đáy 52 tuần ít nhất 25-30%
    diff_from_low = ((close - low_52w) / low_52w * 100) if low_52w > 0 else 0
    cond7 = diff_from_low >= 25.0
    criteria.append({
        'id': 7,
        'title': '7. Giá cách đáy 52 tuần >= 25%',
        'passed': bool(cond7),
        'detail': f"Tăng từ đáy 52 tuần ({low_52w:,.0f}): +{diff_from_low:.1f}% (>= 25%)"
    })

    # 8. RS Rating >= 70
    cond8 = rs_rating >= 70
    criteria.append({
        'id': 8,
        'title': '8. RS Rating >= 70 (Chuẩn SEPA)',
        'passed': bool(cond8),
        'detail': f"RS Rating hiện tại: {rs_rating} / 99"
    })

    passed_count = sum(1 for c in criteria if c['passed'])

    return {
        'score': passed_count,
        'max_score': 8,
        'passed': passed_count >= 7,
        'status': f"ĐẠT ({passed_count}/8)" if passed_count >= 7 else f"CHƯA ĐẠT ({passed_count}/8)",
        'criteria': criteria,
        'metrics': {
            'close': close,
            'high_52w': high_52w,
            'low_52w': low_52w,
            'diff_from_high_pct': round(diff_from_high, 1),
            'diff_from_low_pct': round(diff_from_low, 1)
        }
    }


def detect_minervini_signals(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Detect buy signals:
    1. Pivot Breakout (Volume >= 150% of 50-day average volume + price break 20-day high)
    2. Pocket Pivot (bouncing off moving averages with volume dominance)
    3. Breakout VCP
    """
    signals = []
    if len(df) < 50:
        return signals

    for i in range(50, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        vol_avg = row.get('vol_ma50', 0)
        volume = row['volume']
        close = row['close']
        date_str = str(row['date'])

        # Check Breakout with high volume (>= 50% above average, i.e. 1.5x)
        if vol_avg > 0 and volume >= 1.5 * vol_avg and close > prev['close']:
            # Check if this broke a recent 20-day high
            highest_20 = df.iloc[i-20:i]['high'].max()
            if close >= highest_20:
                signals.append({
                    'time': date_str,
                    'type': 'Breakout VCP',
                    'text': 'Breakout VCP',
                    'price': close,
                    'position': 'belowBar',
                    'color': '#10B981',
                    'shape': 'arrowUp'
                })
                continue

            # Pocket Pivot
            ma50 = row.get('ma50', 0)
            if ma50 > 0 and prev['close'] <= ma50 * 1.02 and close > ma50:
                signals.append({
                    'time': date_str,
                    'type': 'Điểm mua Pivot',
                    'text': 'Điểm mua Pivot (Vol +50%)',
                    'price': close,
                    'position': 'belowBar',
                    'color': '#06B6D4',
                    'shape': 'arrowUp'
                })

    return signals
