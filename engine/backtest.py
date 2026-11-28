"""
5-Year Local Strategy Backtester Engine for Vietnam Equities
Realistic simulation:
- T+2.5 settlement enforcement (earliest exit check at entry_idx + 2)
- 0.35% round-trip transaction fee & tax deduction
- Gap-aware Stop-Loss & Take-Profit execution
- Optional Trailing MA exit (MA10, MA20, MA50) & Max Hold limit
- Daily Mark-to-Market Equity Curve vs Buy & Hold
"""
from typing import Dict, Any, List
import pandas as pd
import numpy as np

from engine.minervini import calculate_technical_indicators, detect_minervini_signals

STRATEGY_CATALOG = {
    'sepa_combo': 'SEPA Tổng Hợp (Stage 2: VCP + Pocket Pivot)',
    'pocket_pivot': 'Pocket Pivot (Morales & Kacher)',
    'breakout_vcp': 'Breakout VCP (Mark Minervini)',
    'wyckoff_vsa': 'Wyckoff VSA (Stopping Vol & No Supply)',
    'trend_ma50': 'Minervini Pullback MA50 (Stage 2)',
}


def run_backtest(
    symbol: str,
    df_ohlcv: pd.DataFrame,
    strategy: str = 'sepa_combo',
    years: int = 5,
    stop_loss_pct: float = 7.0,
    take_profit_pct: float = 20.0,
    trailing_ma: str = 'NONE',
    max_hold_days: int = 60,
    fee_pct: float = 0.35,
) -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    if strategy not in STRATEGY_CATALOG:
        strategy = 'sepa_combo'

    stop_loss_pct = min(40.0, max(1.0, float(stop_loss_pct)))
    take_profit_pct = min(200.0, max(0.0, float(take_profit_pct)))
    max_hold_days = min(500, max(0, int(max_hold_days)))
    trailing_ma = str(trailing_ma or 'NONE').upper().strip()
    if trailing_ma not in ('NONE', 'MA10', 'MA20', 'MA50'):
        trailing_ma = 'NONE'

    if df_ohlcv is None or len(df_ohlcv) < 60:
        return {
            'symbol': symbol,
            'strategy': strategy,
            'strategy_name': STRATEGY_CATALOG[strategy],
            'error': 'Không đủ dữ liệu lịch sử để kiểm định.',
            'metrics': {},
            'equity_curve': [],
            'trades': [],
        }

    # Compute indicators & signals on full history so MA200 is warmed up
    df_calc = calculate_technical_indicators(df_ohlcv)
    signals = detect_minervini_signals(df_calc)
    sig_by_date = {s['time']: s for s in signals}

    n = len(df_calc)
    if years in (1, 3, 5):
        start_idx = max(50, n - years * 250)
    else:
        start_idx = max(50, n - 1500)

    if start_idx >= n - 3:
        start_idx = max(50, n - 60)

    dates = [str(d) for d in df_calc['date'].tolist()]
    opens = df_calc['open'].astype(float).tolist()
    highs = df_calc['high'].astype(float).tolist()
    lows = df_calc['low'].astype(float).tolist()
    closes = df_calc['close'].astype(float).tolist()
    ma10s = df_calc['ma10'].fillna(0).astype(float).tolist() if 'ma10' in df_calc.columns else [0.0] * n
    ma20s = df_calc['ma20'].fillna(0).astype(float).tolist() if 'ma20' in df_calc.columns else [0.0] * n
    ma50s = df_calc['ma50'].fillna(0).astype(float).tolist() if 'ma50' in df_calc.columns else [0.0] * n
    ma150s = df_calc['ma150'].fillna(0).astype(float).tolist() if 'ma150' in df_calc.columns else [0.0] * n
    ma200s = df_calc['ma200'].fillna(0).astype(float).tolist() if 'ma200' in df_calc.columns else [0.0] * n

    trail_arr = {'MA10': ma10s, 'MA20': ma20s, 'MA50': ma50s}.get(trailing_ma)

    trades: List[Dict[str, Any]] = []
    i = start_idx
    while i < n - 2:
        d = dates[i]
        c = closes[i]
        o = opens[i]
        l = lows[i]
        prev_c = closes[i - 1]
        ma50 = ma50s[i]
        ma150 = ma150s[i]
        ma200 = ma200s[i]
        sig = sig_by_date.get(d)

        entry_signal = None
        if strategy == 'sepa_combo':
            if sig and sig['code'] in ('VCP', 'PP'):
                stage2_ok = (
                    (ma50 == 0 or c > ma50)
                    and (ma150 == 0 or c >= ma150 * 0.98)
                    and (ma200 == 0 or ma50 >= ma200 * 0.97)
                )
                if stage2_ok:
                    entry_signal = sig['code']
        elif strategy == 'pocket_pivot':
            if sig and sig['code'] == 'PP':
                entry_signal = 'PP'
        elif strategy == 'breakout_vcp':
            if sig and sig['code'] == 'VCP':
                entry_signal = 'VCP'
        elif strategy == 'wyckoff_vsa':
            if sig and sig['code'] in ('SV', 'NS'):
                entry_signal = sig['code']
        elif strategy == 'trend_ma50':
            if (
                ma50 > 0 and ma150 > 0 and ma200 > 0
                and c > ma50 and ma50 > ma150 and ma150 > ma200
                and l <= ma50 * 1.02 and c > prev_c and c >= o
            ):
                entry_signal = 'MA50'

        if entry_signal and c > 0:
            entry_price = c
            stop_price = entry_price * (1.0 - stop_loss_pct / 100.0)
            target_price = entry_price * (1.0 + take_profit_pct / 100.0) if take_profit_pct > 0 else None

            exit_idx = n - 1
            exit_price = closes[n - 1]
            reason = 'Đang mở (Chưa đóng)'
            is_open = True

            # Vietnam T+2.5 settlement: earliest exit check at i + 2
            for j in range(i + 2, n):
                o_j = opens[j]
                h_j = highs[j]
                l_j = lows[j]
                c_j = closes[j]

                if l_j <= stop_price:
                    exit_idx = j
                    exit_price = min(o_j, stop_price) if o_j > 0 else stop_price
                    reason = f"Cắt lỗ (-{stop_loss_pct:g}%)"
                    is_open = False
                    break

                if target_price is not None and h_j >= target_price:
                    exit_idx = j
                    exit_price = max(o_j, target_price) if o_j > 0 else target_price
                    reason = f"Chốt lời (+{take_profit_pct:g}%)"
                    is_open = False
                    break

                if trail_arr is not None and (j - i) >= 3:
                    ma_v = trail_arr[j]
                    if ma_v > 0 and c_j < ma_v:
                        exit_idx = j
                        exit_price = c_j
                        reason = f"Gãy {trailing_ma}"
                        is_open = False
                        break

                if max_hold_days > 0 and (j - i) >= max_hold_days:
                    exit_idx = j
                    exit_price = c_j
                    reason = f"Hết hạn ({max_hold_days} phiên)"
                    is_open = False
                    break

            applied_fee = fee_pct if not is_open else (fee_pct / 2.0)
            net_ret = round(((exit_price / entry_price) - 1.0) * 100.0 - applied_fee, 2)
            hold_days = int(exit_idx - i)

            trades.append({
                'entry_idx': i,
                'exit_idx': exit_idx,
                'signal': entry_signal,
                'entry_date': d,
                'exit_date': dates[exit_idx],
                'entry_price': round(entry_price, 0),
                'exit_price': round(exit_price, 0),
                'return_pct': net_ret,
                'hold_days': hold_days,
                'reason': reason,
                'is_open': is_open,
                'win': net_ret > 0,
            })

            i = exit_idx + 1
        else:
            i += 1

    # Build Daily Mark-to-Market Equity Curve (Strategy vs Buy & Hold, Base = 100)
    trade_by_entry = {t['entry_idx']: t for t in trades}
    start_close = closes[start_idx] if closes[start_idx] > 0 else 1.0

    capital = 100.0
    active_trade = None
    peak_eq = 100.0
    max_dd = 0.0
    equity_curve: List[Dict[str, Any]] = []

    for k in range(start_idx, n):
        if active_trade is None and k in trade_by_entry:
            active_trade = trade_by_entry[k]

        if active_trade is not None:
            if k == active_trade['exit_idx']:
                capital = capital * (1.0 + active_trade['return_pct'] / 100.0)
                cur_eq = capital
                active_trade = None
            else:
                cur_eq = capital * (closes[k] / active_trade['entry_price'])
        else:
            cur_eq = capital

        if cur_eq > peak_eq:
            peak_eq = cur_eq
        dd = ((cur_eq - peak_eq) / peak_eq * 100.0) if peak_eq > 0 else 0.0
        if dd < max_dd:
            max_dd = dd

        bh_eq = (closes[k] / start_close) * 100.0
        equity_curve.append({
            'time': dates[k],
            'strategy': round(cur_eq, 2),
            'buy_hold': round(bh_eq, 2),
        })

    # Compute Institutional Metrics
    total_trades = len(trades)
    closed_list = [t for t in trades if not t['is_open']]
    eval_list = closed_list if closed_list else trades

    wins_list = [t['return_pct'] for t in eval_list if t['return_pct'] > 0]
    losses_list = [t['return_pct'] for t in eval_list if t['return_pct'] <= 0]

    wins = len(wins_list)
    losses = len(losses_list)
    eval_cnt = len(eval_list)

    win_rate = round((wins / eval_cnt * 100.0), 1) if eval_cnt > 0 else 0.0
    avg_win = round(sum(wins_list) / len(wins_list), 2) if wins_list else 0.0
    avg_loss = round(sum(losses_list) / len(losses_list), 2) if losses_list else 0.0

    if avg_loss < 0:
        rr_ratio = round(avg_win / abs(avg_loss), 2)
    else:
        rr_ratio = round(avg_win, 2) if avg_win > 0 else 0.0

    sum_wins = sum(wins_list)
    sum_losses = sum(losses_list)
    if sum_losses < 0:
        profit_factor = round(sum_wins / abs(sum_losses), 2)
    else:
        profit_factor = 99.9 if sum_wins > 0 else 0.0

    wr_dec = win_rate / 100.0
    expectancy = round(wr_dec * avg_win + (1.0 - wr_dec) * avg_loss, 2)

    final_strat_ret = round(equity_curve[-1]['strategy'] - 100.0, 1) if equity_curve else 0.0
    final_bh_ret = round(equity_curve[-1]['buy_hold'] - 100.0, 1) if equity_curve else 0.0
    alpha_pct = round(final_strat_ret - final_bh_ret, 1)
    avg_hold = round(sum(t['hold_days'] for t in trades) / total_trades, 1) if total_trades > 0 else 0.0

    # Clean trade list (newest first, cap 100, drop internal indices)
    clean_trades = []
    for idx_t, t in enumerate(reversed(trades[-100:]), start=1):
        clean_trades.append({
            'id': total_trades - idx_t + 1,
            'signal': t['signal'],
            'entry_date': t['entry_date'],
            'exit_date': t['exit_date'],
            'entry_price': t['entry_price'],
            'exit_price': t['exit_price'],
            'return_pct': t['return_pct'],
            'hold_days': t['hold_days'],
            'reason': t['reason'],
            'is_open': t['is_open'],
            'win': t['win'],
        })

    return {
        'symbol': symbol,
        'strategy': strategy,
        'strategy_name': STRATEGY_CATALOG[strategy],
        'period': {
            'start_date': dates[start_idx],
            'end_date': dates[-1],
            'bars': int(n - start_idx),
            'years': years,
        },
        'params': {
            'stop_loss_pct': stop_loss_pct,
            'take_profit_pct': take_profit_pct,
            'trailing_ma': trailing_ma,
            'max_hold_days': max_hold_days,
            'fee_pct': fee_pct,
        },
        'metrics': {
            'total_trades': total_trades,
            'closed_trades': len(closed_list),
            'open_trades': total_trades - len(closed_list),
            'wins': wins,
            'losses': losses,
            'win_rate_pct': win_rate,
            'avg_win_pct': avg_win,
            'avg_loss_pct': avg_loss,
            'reward_risk_ratio': rr_ratio,
            'profit_factor': profit_factor,
            'expectancy_pct': expectancy,
            'total_return_pct': final_strat_ret,
            'buy_hold_return_pct': final_bh_ret,
            'alpha_pct': alpha_pct,
            'max_drawdown_pct': round(max_dd, 1),
            'avg_hold_days': avg_hold,
        },
        'equity_curve': equity_curve,
        'trades': clean_trades,
    }
