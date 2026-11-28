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

    # Moving averages (MA10, MA20, MA50, MA150, MA200)
    df['ma10'] = df['close'].rolling(window=10).mean()
    df['ma20'] = df['close'].rolling(window=20).mean()
    df['ma50'] = df['close'].rolling(window=50).mean()
    df['ma150'] = df['close'].rolling(window=150).mean()
    df['ma200'] = df['close'].rolling(window=200).mean()

    # 20-day & 50-day Volume Averages + Spread metrics for VSA
    df['vol_ma20'] = df['volume'].rolling(window=20).mean()
    df['vol_ma50'] = df['volume'].rolling(window=50).mean()
    df['spread_pct'] = (df['high'] - df['low']) / df['close'].replace(0, np.nan)
    df['avg_spread_20'] = df['spread_pct'].rolling(window=20).mean()

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
    Detect technical & Wyckoff VSA signals (highest priority per bar, sorted ascending):
    1. Breakout VCP (Minervini): Break 20-day high on Volume >= 1.5x Vol MA50
    2. Pocket Pivot (Morales & Kacher): Bounce near MA10/MA50 with Vol > max down-day Vol over prior 10 sessions
    3. Stopping Volume (VSA): Selling Climax / Institutional absorption with high Vol >= 1.8x Vol MA20 & lower-wick reversal
    4. No Supply Test (VSA): Narrow spread dry-up with Vol < 0.65x Vol MA20 and lower than prior 2 sessions
    """
    signals: List[Dict[str, Any]] = []
    if len(df) < 50:
        return signals

    last_pp = -10
    last_sv = -10
    last_ns = -10

    for i in range(50, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        prev2 = df.iloc[i - 2]

        vol = float(row['volume'] or 0)
        vol_ma50 = float(row.get('vol_ma50') or 0) if pd.notna(row.get('vol_ma50')) else 0.0
        vol_ma20 = float(row.get('vol_ma20') or 0) if pd.notna(row.get('vol_ma20')) else 0.0

        o = float(row['open'] or 0)
        h = float(row['high'] or 0)
        l = float(row['low'] or 0)
        c = float(row['close'] or 0)
        prev_c = float(prev['close'] or 0)

        ma10 = float(row.get('ma10') or 0) if pd.notna(row.get('ma10')) else 0.0
        ma20 = float(row.get('ma20') or 0) if pd.notna(row.get('ma20')) else 0.0
        ma50 = float(row.get('ma50') or 0) if pd.notna(row.get('ma50')) else 0.0
        avg_spread_20 = float(row.get('avg_spread_20') or 0) if pd.notna(row.get('avg_spread_20')) else 0.0

        if c <= 0 or prev_c <= 0:
            continue

        date_str = str(row['date'])
        spread = (h - l) / c
        clv = (c - l) / (h - l) if h > l else 0.5

        # Priority 1: Breakout VCP
        highest_20 = float(df.iloc[i - 20:i]['high'].max())
        if (
            vol_ma50 > 0
            and vol >= 1.5 * vol_ma50
            and c > prev_c
            and c >= o
            and c >= highest_20
            and (ma50 == 0 or c > ma50)
        ):
            vol_ratio = vol / vol_ma50
            signals.append({
                'time': date_str,
                'code': 'VCP',
                'type': 'Breakout VCP',
                'category': 'BUY',
                'text': 'VCP',
                'price': c,
                'position': 'belowBar',
                'color': '#10B981',
                'shape': 'arrowUp',
                'detail': f"Vượt đỉnh 20 phiên, Vol đạt {vol_ratio:.1f}x TB50"
            })
            last_pp = i
            continue

        # Priority 2: Pocket Pivot (Morales & Kacher)
        if i - last_pp >= 3 and c > prev_c and clv >= 0.50 and vol_ma50 > 0 and vol >= 0.9 * vol_ma50:
            win = df.iloc[i - 10:i]
            win_prev_close = df.iloc[i - 11:i - 1]['close'].values
            down_vols = [
                float(win.iloc[k]['volume'])
                for k in range(len(win))
                if float(win.iloc[k]['close']) < float(win_prev_close[k])
            ]
            if down_vols and vol > max(down_vols):
                max_down_vol = max(down_vols)
                near_ma10 = ma10 > 0 and l <= ma10 * 1.025 and c >= ma10 and c <= ma10 * 1.07
                near_ma50 = ma50 > 0 and l <= ma50 * 1.025 and c >= ma50 and c <= ma50 * 1.07
                if (near_ma10 or near_ma50) and (ma50 == 0 or c >= ma50 * 0.98):
                    ma_label = 'MA10 & MA50' if (near_ma10 and near_ma50) else ('MA10' if near_ma10 else 'MA50')
                    ratio_down = vol / max_down_vol if max_down_vol > 0 else 1.0
                    signals.append({
                        'time': date_str,
                        'code': 'PP',
                        'type': 'Pocket Pivot',
                        'category': 'BUY',
                        'text': 'PP',
                        'price': c,
                        'position': 'belowBar',
                        'color': '#06B6D4',
                        'shape': 'arrowUp',
                        'detail': f"Điểm mua sớm quanh {ma_label}, Vol vượt đỉnh cung 10 phiên ({ratio_down:.1f}x)"
                    })
                    last_pp = i
                    continue

        # Priority 3: Stopping Volume (VSA - Selling Climax / Institutional Absorption)
        lowest_10 = float(df.iloc[i - 10:i]['low'].min())
        if (
            i - last_sv >= 5
            and vol_ma20 > 0
            and vol >= 1.8 * vol_ma20
            and spread >= 0.025
            and clv >= 0.45
            and (l <= lowest_10 * 1.01 or (ma20 > 0 and c < ma20))
        ):
            vol_ratio20 = vol / vol_ma20
            signals.append({
                'time': date_str,
                'code': 'SV',
                'type': 'Stopping Volume (VSA)',
                'category': 'VSA',
                'text': 'SV',
                'price': c,
                'position': 'belowBar',
                'color': '#F59E0B',
                'shape': 'circle',
                'detail': f"Rút chân hấp thụ khối lượng lớn ({vol_ratio20:.1f}x TB20, đóng cửa {clv * 100:.0f}% biên độ)"
            })
            last_sv = i
            continue

        # Priority 4: No Supply Test (VSA - Narrow Spread Dry-Up)
        prev_vol_1 = float(prev['volume'] or 0)
        prev_vol_2 = float(prev2['volume'] or 0)
        if (
            i - last_ns >= 5
            and vol_ma20 > 0
            and 0 < vol < 0.65 * vol_ma20
            and vol < prev_vol_1
            and vol < prev_vol_2
        ):
            max_allowed_spread = min(0.032, max(0.022, 0.75 * avg_spread_20)) if avg_spread_20 > 0 else 0.022
            if (
                spread <= max_allowed_spread
                and clv >= 0.40
                and abs(c - prev_c) / prev_c <= 0.025
                and (ma50 == 0 or c >= ma50 * 0.95)
                and ma10 > 0
                and l <= max(ma10, ma20, ma50) * 1.03
            ):
                vol_pct20 = vol / vol_ma20 * 100
                signals.append({
                    'time': date_str,
                    'code': 'NS',
                    'type': 'No Supply Test (VSA)',
                    'category': 'VSA',
                    'text': 'NS',
                    'price': c,
                    'position': 'belowBar',
                    'color': '#A855F7',
                    'shape': 'circle',
                    'detail': f"Cạn cung test nền (Vol = {vol_pct20:.0f}% TB20, biên độ {spread * 100:.1f}%)"
                })
                last_ns = i

    return signals
