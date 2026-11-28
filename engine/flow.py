"""
Micro-Flow & Institutional Footprint Module for Vietnam Stock Market:
1. Exact latest-session Active Buy (BU) & Active Sell (SD) from SSI iBoard
2. ~20-day historical Active Buy / Sell estimated from Entrade 1-minute bars (Tick Rule)
3. ~120-day historical Foreign Net Buy / Sell from SSI Stock Info (fallback CafeF)
4. Summaries & time-series merging for 3-pane charts & Micro-Flow cards
"""
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, Tuple, List

import numpy as np
import pandas as pd
import requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*'
}
SSI_HEADERS = {**HEADERS, 'Referer': 'https://iboard.ssi.com.vn/'}
CAFEF_HEADERS = {**HEADERS, 'Referer': 'https://cafef.vn/'}


def _parse_ddmmyyyy(s: Any) -> Optional[str]:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    try:
        return datetime.strptime(s, '%d/%m/%Y').strftime('%Y-%m-%d')
    except Exception:
        return None


def _parse_yyyymmdd(s: Any) -> Optional[str]:
    if not s:
        return None
    s = str(s).strip()
    try:
        if len(s) == 8 and s.isdigit():
            return datetime.strptime(s, '%Y%m%d').strftime('%Y-%m-%d')
        if len(s) == 10 and '-' in s:
            return s
    except Exception:
        pass
    return None


def _safe_int(v: Any) -> Optional[int]:
    if v is None or v == '' or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        return int(round(float(v)))
    except Exception:
        return None


def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == '' or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        return float(v)
    except Exception:
        return None


def fetch_ssi_realtime_snapshot(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetch exact latest-session Active Buy (stockBUVol), Active Sell (stockSDVol),
    Foreign Flow, Company Name, and Exchange from SSI iBoard.
    """
    symbol = symbol.upper().strip()
    try:
        url = f"https://iboard-query.ssi.com.vn/stock/{symbol}"
        r = requests.get(url, headers=SSI_HEADERS, timeout=6)
        if r.status_code != 200:
            return None
        d = r.json().get('data') or {}
        if not d:
            return None

        trading_date = _parse_yyyymmdd(d.get('tradingDate'))
        if not trading_date:
            trading_date = datetime.now().strftime('%Y-%m-%d')

        bu = _safe_int(d.get('stockBUVol')) or 0
        sd = _safe_int(d.get('stockSDVol')) or 0
        total_vol = _safe_int(d.get('stockVol')) or 0

        f_buy_vol = _safe_int(d.get('buyForeignQtty')) or 0
        f_sell_vol = _safe_int(d.get('sellForeignQtty')) or 0
        f_buy_val = _safe_float(d.get('buyForeignValue')) or 0.0
        f_sell_val = _safe_float(d.get('sellForeignValue')) or 0.0

        return {
            'trading_date': trading_date,
            'active_buy_vol': bu if (bu + sd) > 0 else None,
            'active_sell_vol': sd if (bu + sd) > 0 else None,
            'total_vol': total_vol,
            'active_is_exact': bool((bu + sd) > 0),
            'foreign_buy_vol': f_buy_vol,
            'foreign_sell_vol': f_sell_vol,
            'foreign_net_vol': f_buy_vol - f_sell_vol,
            'foreign_buy_val': f_buy_val,
            'foreign_sell_val': f_sell_val,
            'foreign_net_val': f_buy_val - f_sell_val,
            'company_name': d.get('companyNameVi') or d.get('companyNameEn'),
            'exchange': str(d.get('exchange') or '').upper() or None,
        }
    except Exception as e:
        print(f"[Flow] SSI snapshot error for {symbol}: {e}")
        return None


def _fetch_ssi_foreign_page(symbol: str, page: int, from_str: str, to_str: str) -> List[Dict[str, Any]]:
    url = (
        f"https://iboard-api.ssi.com.vn/statistics/company/ssmi/stock-info"
        f"?symbol={symbol}&page={page}&pageSize=40&fromDate={from_str}&toDate={to_str}"
    )
    try:
        r = requests.get(url, headers=SSI_HEADERS, timeout=6)
        if r.status_code != 200:
            return []
        return r.json().get('data') or []
    except Exception:
        return []


def _fetch_cafef_foreign_page(symbol: str, page: int) -> List[Dict[str, Any]]:
    url = (
        f"https://cafef.vn/du-lieu/Ajax/PageNew/DataHistory/GDKhoiNgoai.ashx"
        f"?Symbol={symbol}&StartDate=&EndDate=&PageIndex={page}&PageSize=30"
    )
    try:
        r = requests.get(url, headers=CAFEF_HEADERS, timeout=6)
        if r.status_code != 200:
            return []
        data_wrap = r.json().get('Data') or {}
        return data_wrap.get('Data') or []
    except Exception:
        return []


def fetch_foreign_flow_history(symbol: str, pages: int = 3) -> pd.DataFrame:
    """
    Fetch ~120 trading days of Foreign Net Buy/Sell (volume & VND value)
    from SSI stock-info (3 pages in parallel), with fallback to CafeF GDKhoiNgoai.
    """
    symbol = symbol.upper().strip()
    cols = [
        'date', 'foreign_buy_vol', 'foreign_sell_vol', 'foreign_net_vol',
        'foreign_buy_val', 'foreign_sell_val', 'foreign_net_val'
    ]
    rows: List[Dict[str, Any]] = []

    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=200)
    from_str = from_dt.strftime('%d/%m/%Y')
    to_str = to_dt.strftime('%d/%m/%Y')

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(_fetch_ssi_foreign_page, symbol, p, from_str, to_str) for p in range(1, pages + 1)]
            for fut in futures:
                for item in fut.result():
                    iso_date = _parse_ddmmyyyy(item.get('tradingDate'))
                    if not iso_date:
                        continue
                    buy_v = _safe_int(item.get('foreignBuyVolTotal')) or 0
                    sell_v = _safe_int(item.get('foreignSellVolTotal')) or 0
                    net_v = _safe_int(item.get('netBuySellVol'))
                    if net_v is None:
                        net_v = buy_v - sell_v

                    buy_val = _safe_float(item.get('foreignBuyValTotal')) or 0.0
                    sell_val = _safe_float(item.get('foreignSellValTotal')) or 0.0
                    net_val = _safe_float(item.get('netBuySellVal'))
                    if net_val is None:
                        net_val = buy_val - sell_val

                    rows.append({
                        'date': iso_date,
                        'foreign_buy_vol': buy_v,
                        'foreign_sell_vol': sell_v,
                        'foreign_net_vol': net_v,
                        'foreign_buy_val': buy_val,
                        'foreign_sell_val': sell_val,
                        'foreign_net_val': net_val,
                    })
    except Exception as e:
        print(f"[Flow] SSI foreign history error for {symbol}: {e}")

    # Fallback to CafeF if SSI returns nothing
    if not rows:
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(_fetch_cafef_foreign_page, symbol, p) for p in range(1, 3)]
                for fut in futures:
                    for item in fut.result():
                        iso_date = _parse_ddmmyyyy(item.get('Ngay'))
                        if not iso_date:
                            continue
                        buy_v = _safe_int(item.get('KLMua')) or 0
                        sell_v = _safe_int(item.get('KLBan')) or 0
                        net_v = _safe_int(item.get('KLGDRong'))
                        if net_v is None:
                            net_v = buy_v - sell_v

                        buy_val = _safe_float(item.get('GtMua')) or 0.0
                        sell_val = _safe_float(item.get('GtBan')) or 0.0
                        net_val = _safe_float(item.get('GTDGRong'))
                        if net_val is None:
                            net_val = buy_val - sell_val

                        rows.append({
                            'date': iso_date,
                            'foreign_buy_vol': buy_v,
                            'foreign_sell_vol': sell_v,
                            'foreign_net_vol': net_v,
                            'foreign_buy_val': buy_val,
                            'foreign_sell_val': sell_val,
                            'foreign_net_val': net_val,
                        })
        except Exception as e:
            print(f"[Flow] CafeF foreign fallback error for {symbol}: {e}")

    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=['date'], keep='first').sort_values('date').reset_index(drop=True)
    return df[cols]


def fetch_intraday_estimated_active_flow(symbol: str, days: int = 32) -> pd.DataFrame:
    """
    Estimate ~20 trading days of Active Buy / Active Sell volume from Entrade 1-minute bars
    using the Tick Rule (close vs previous bar close, tie-breaker close vs open).
    """
    symbol = symbol.upper().strip()
    cols = ['date', 'active_buy_vol', 'active_sell_vol', 'active_is_exact']
    try:
        now = int(time.time())
        from_ts = now - days * 86400
        url = (
            f"https://services.entrade.com.vn/chart-api/v2/ohlcs/stock"
            f"?from={from_ts}&to={now}&symbol={symbol}&resolution=1"
        )
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return pd.DataFrame(columns=cols)
        data = r.json()
        ts = data.get('t') or []
        if not ts:
            return pd.DataFrame(columns=cols)

        df_1m = pd.DataFrame({
            't': ts,
            'o': data['o'],
            'c': data['c'],
            'v': data['v']
        }).sort_values('t').reset_index(drop=True)

        # Convert UTC epoch to Vietnam local trading date (UTC+7)
        df_1m['date'] = pd.to_datetime(df_1m['t'] + 7 * 3600, unit='s').dt.strftime('%Y-%m-%d')

        results = []
        for dt, grp in df_1m.groupby('date', sort=True):
            direction = 1
            prev_c: Optional[float] = None
            buy_vol = 0
            sell_vol = 0
            for o, c, v in zip(grp['o'], grp['c'], grp['v']):
                if v is None or v <= 0:
                    if c is not None:
                        prev_c = float(c)
                    continue
                o_f = float(o)
                c_f = float(c)
                ref = prev_c if prev_c is not None else o_f
                if c_f > ref:
                    direction = 1
                elif c_f < ref:
                    direction = -1
                elif c_f > o_f:
                    direction = 1
                elif c_f < o_f:
                    direction = -1

                vol_int = int(round(float(v)))
                if direction == 1:
                    buy_vol += vol_int
                else:
                    sell_vol += vol_int
                prev_c = c_f

            if buy_vol + sell_vol > 0:
                results.append({
                    'date': dt,
                    'active_buy_vol': buy_vol,
                    'active_sell_vol': sell_vol,
                    'active_is_exact': False
                })

        if not results:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame(results, columns=cols)
    except Exception as e:
        print(f"[Flow] Entrade 1m active flow error for {symbol}: {e}")
        return pd.DataFrame(columns=cols)


def fetch_combined_daily_flow(symbol: str) -> Tuple[pd.DataFrame, Optional[Dict[str, Any]]]:
    """
    Fetch SSI snapshot, Foreign history, and 1m estimated Active Flow concurrently,
    then combine them with priority given to exact SSI snapshot data.
    """
    symbol = symbol.upper().strip()
    all_cols = [
        'date', 'active_buy_vol', 'active_sell_vol', 'active_is_exact',
        'foreign_buy_vol', 'foreign_sell_vol', 'foreign_net_vol',
        'foreign_buy_val', 'foreign_sell_val', 'foreign_net_val'
    ]

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_snap = pool.submit(fetch_ssi_realtime_snapshot, symbol)
        f_foreign = pool.submit(fetch_foreign_flow_history, symbol, 3)
        f_active = pool.submit(fetch_intraday_estimated_active_flow, symbol, 32)

        snapshot = f_snap.result()
        foreign_df = f_foreign.result()
        active_df = f_active.result()

    if len(foreign_df) > 0 and len(active_df) > 0:
        merged = pd.merge(foreign_df, active_df, on='date', how='outer')
    elif len(foreign_df) > 0:
        merged = foreign_df.copy()
        merged['active_buy_vol'] = None
        merged['active_sell_vol'] = None
        merged['active_is_exact'] = False
    elif len(active_df) > 0:
        merged = active_df.copy()
        for c in ['foreign_buy_vol', 'foreign_sell_vol', 'foreign_net_vol',
                  'foreign_buy_val', 'foreign_sell_val', 'foreign_net_val']:
            merged[c] = None
    else:
        merged = pd.DataFrame(columns=all_cols)

    # Overlay exact SSI snapshot on its trading date
    if snapshot and snapshot.get('trading_date'):
        snap_date = snapshot['trading_date']
        if len(merged) == 0 or snap_date not in set(merged['date']):
            new_row = {
                'date': snap_date,
                'active_buy_vol': snapshot.get('active_buy_vol'),
                'active_sell_vol': snapshot.get('active_sell_vol'),
                'active_is_exact': bool(snapshot.get('active_is_exact')),
                'foreign_buy_vol': snapshot.get('foreign_buy_vol'),
                'foreign_sell_vol': snapshot.get('foreign_sell_vol'),
                'foreign_net_vol': snapshot.get('foreign_net_vol'),
                'foreign_buy_val': snapshot.get('foreign_buy_val'),
                'foreign_sell_val': snapshot.get('foreign_sell_val'),
                'foreign_net_val': snapshot.get('foreign_net_val'),
            }
            merged = pd.concat([merged, pd.DataFrame([new_row])], ignore_index=True)
        else:
            mask = merged['date'] == snap_date
            if snapshot.get('active_is_exact'):
                merged.loc[mask, 'active_buy_vol'] = snapshot.get('active_buy_vol')
                merged.loc[mask, 'active_sell_vol'] = snapshot.get('active_sell_vol')
                merged.loc[mask, 'active_is_exact'] = True

            has_snap_foreign = (
                (snapshot.get('foreign_buy_vol') or 0) > 0 or
                (snapshot.get('foreign_sell_vol') or 0) > 0
            )
            existing_missing = merged.loc[mask, 'foreign_net_vol'].isna().any()
            if has_snap_foreign or existing_missing:
                for col in ['foreign_buy_vol', 'foreign_sell_vol', 'foreign_net_vol',
                            'foreign_buy_val', 'foreign_sell_val', 'foreign_net_val']:
                    merged.loc[mask, col] = snapshot.get(col)

    if len(merged) > 0:
        merged['active_is_exact'] = merged['active_is_exact'].map(lambda x: bool(x) if pd.notna(x) else False)
        merged = merged.drop_duplicates(subset=['date'], keep='last').sort_values('date').reset_index(drop=True)
        return merged[all_cols], snapshot

    return pd.DataFrame(columns=all_cols), snapshot


def merge_flow_into_chart_df(df_calc: pd.DataFrame, df_flow: pd.DataFrame) -> pd.DataFrame:
    """
    Left-join flow metrics onto calculated OHLCV DataFrame and compute derived chart series:
    - active_net_vol
    - active_buy_pct
    - foreign_net_val_bil (VND billions)
    - foreign_cum_net_val (cumulative VND billions starting from first non-null foreign row)
    """
    df_out = df_calc.copy()
    if df_flow is None or len(df_flow) == 0:
        for col in ['active_buy_vol', 'active_sell_vol', 'active_is_exact',
                    'active_net_vol', 'active_buy_pct',
                    'foreign_net_vol', 'foreign_net_val_bil', 'foreign_cum_net_val']:
            df_out[col] = np.nan
        return df_out

    flow_cols = df_flow[['date', 'active_buy_vol', 'active_sell_vol', 'active_is_exact',
                         'foreign_net_vol', 'foreign_net_val']].drop_duplicates('date', keep='last')
    df_out = pd.merge(df_out, flow_cols, on='date', how='left')

    bu = pd.to_numeric(df_out['active_buy_vol'], errors='coerce').astype('float64')
    sd = pd.to_numeric(df_out['active_sell_vol'], errors='coerce').astype('float64')
    tot_active = bu + sd
    valid_active = (tot_active > 0).fillna(False).to_numpy(dtype=bool)

    df_out['active_net_vol'] = np.where(valid_active, bu - sd, np.nan)
    df_out['active_buy_pct'] = np.where(valid_active, np.round(bu / tot_active * 100.0, 1), np.nan)

    f_val = pd.to_numeric(df_out['foreign_net_val'], errors='coerce').astype('float64')
    df_out['foreign_net_val_bil'] = np.where(f_val.notna().to_numpy(dtype=bool), np.round(f_val / 1e9, 2), np.nan)

    # Cumulative foreign flow starting cleanly from first date with foreign data
    cum_vals = np.full(len(df_out), np.nan, dtype=float)
    running = 0.0
    started = False
    for idx, val in enumerate(df_out['foreign_net_val_bil']):
        if pd.notna(val):
            started = True
            running += float(val)
            cum_vals[idx] = round(running, 2)
        elif started:
            cum_vals[idx] = round(running, 2)
    df_out['foreign_cum_net_val'] = cum_vals

    return df_out


def summarize_market_flow(
    df_flow: pd.DataFrame,
    df_ohlcv: pd.DataFrame,
    snapshot: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Build structured summary dict for Micro-Flow KPIs, 10-day accumulation stats,
    multi-period Foreign Flow + streak, and 10-session detail table.
    """
    empty_res = {
        'has_data': False,
        'latest': {},
        'active_10d': {},
        'foreign_summary': {},
        'recent_sessions': []
    }
    if (df_flow is None or len(df_flow) == 0) and not snapshot:
        return empty_res

    df = df_flow.copy() if df_flow is not None else pd.DataFrame()
    if len(df) > 0:
        df = df.sort_values('date').reset_index(drop=True)

    # Join with OHLCV to align trading sessions, close price & % change
    ohlcv = df_ohlcv[['date', 'close', 'volume']].copy().sort_values('date').reset_index(drop=True)
    ohlcv['prev_close'] = ohlcv['close'].shift(1)
    ohlcv['change_pct'] = np.where(
        ohlcv['prev_close'] > 0,
        np.round((ohlcv['close'] - ohlcv['prev_close']) / ohlcv['prev_close'] * 100.0, 2),
        0.0
    )

    if len(df) > 0:
        joined = pd.merge(ohlcv, df, on='date', how='left')
        for num_col in ['active_buy_vol', 'active_sell_vol', 'foreign_buy_vol',
                        'foreign_sell_vol', 'foreign_net_vol', 'foreign_net_val']:
            if num_col in joined.columns:
                joined[num_col] = pd.to_numeric(joined[num_col], errors='coerce').astype('float64')
    else:
        joined = ohlcv.copy()
        for col in ['active_buy_vol', 'active_sell_vol', 'active_is_exact',
                    'foreign_buy_vol', 'foreign_sell_vol', 'foreign_net_vol', 'foreign_net_val']:
            joined[col] = np.nan

    # Latest session with any flow info
    flow_present = joined[
        joined['active_buy_vol'].notna() | joined['foreign_net_vol'].notna()
    ].copy()

    latest_dict: Dict[str, Any] = {}
    if len(flow_present) > 0:
        last_row = flow_present.iloc[-1]
        bu = _safe_int(last_row.get('active_buy_vol'))
        sd = _safe_int(last_row.get('active_sell_vol'))
        tot = (bu or 0) + (sd or 0)
        bu_pct = round(bu / tot * 100.0, 1) if (bu is not None and tot > 0) else None
        sd_pct = round(100.0 - bu_pct, 1) if bu_pct is not None else None
        f_net_val = _safe_float(last_row.get('foreign_net_val'))
        latest_dict = {
            'date': str(last_row['date']),
            'active_buy_vol': bu,
            'active_sell_vol': sd,
            'active_net_vol': (bu - sd) if (bu is not None and sd is not None and tot > 0) else None,
            'active_buy_pct': bu_pct,
            'active_sell_pct': sd_pct,
            'active_is_exact': bool(last_row.get('active_is_exact')) if pd.notna(last_row.get('active_is_exact')) else False,
            'foreign_buy_vol': _safe_int(last_row.get('foreign_buy_vol')),
            'foreign_sell_vol': _safe_int(last_row.get('foreign_sell_vol')),
            'foreign_net_vol': _safe_int(last_row.get('foreign_net_vol')),
            'foreign_net_val_bil': round(f_net_val / 1e9, 2) if f_net_val is not None else None,
        }

    # 10-day Active Flow Summary
    active_rows = joined[
        joined['active_buy_vol'].notna() & joined['active_sell_vol'].notna() &
        ((joined['active_buy_vol'].fillna(0) + joined['active_sell_vol'].fillna(0)) > 0)
    ].tail(10)

    active_10d: Dict[str, Any] = {}
    if len(active_rows) > 0:
        bu10 = int(active_rows['active_buy_vol'].sum())
        sd10 = int(active_rows['active_sell_vol'].sum())
        tot10 = bu10 + sd10
        bu10_pct = round(bu10 / tot10 * 100.0, 1) if tot10 > 0 else 50.0
        sd10_pct = round(100.0 - bu10_pct, 1)
        exact_cnt = int(active_rows['active_is_exact'].map(lambda x: bool(x) if pd.notna(x) else False).sum())
        if bu10_pct >= 55.0:
            a_trend = 'MUA CHỦ ĐỘNG ÁP ĐẢO'
        elif sd10_pct >= 55.0:
            a_trend = 'BÁN CHỦ ĐỘNG ÁP ĐẢO'
        else:
            a_trend = 'CÂN BẰNG'
        active_10d = {
            'sessions': int(len(active_rows)),
            'exact_count': exact_cnt,
            'buy_vol': bu10,
            'sell_vol': sd10,
            'net_vol': bu10 - sd10,
            'buy_pct': bu10_pct,
            'sell_pct': sd10_pct,
            'trend': a_trend,
        }

    # Foreign Flow Multi-Period Summary
    foreign_rows = joined[joined['foreign_net_val'].notna()].copy()
    foreign_summary: Dict[str, Any] = {}
    if len(foreign_rows) > 0:
        def _period_sums(n: int) -> Tuple[float, int]:
            sub = foreign_rows.tail(n)
            val_bil = round(float(sub['foreign_net_val'].sum()) / 1e9, 2)
            vol_sum = int(sub['foreign_net_vol'].fillna(0).sum())
            return val_bil, vol_sum

        n1_bil, n1_vol = _period_sums(1)
        n5_bil, n5_vol = _period_sums(5)
        n10_bil, n10_vol = _period_sums(10)
        n20_bil, n20_vol = _period_sums(20)

        # Consecutive buy / sell streak
        streak = 0
        vals_list = foreign_rows['foreign_net_val'].tolist()
        if vals_list:
            last_v = float(vals_list[-1])
            if last_v > 0:
                for v in reversed(vals_list):
                    if float(v) > 0:
                        streak += 1
                    else:
                        break
            elif last_v < 0:
                for v in reversed(vals_list):
                    if float(v) < 0:
                        streak -= 1
                    else:
                        break

        if n10_bil > 20 or (n10_bil > 5 and streak >= 2):
            f_trend = 'KHỐI NGOẠI GOM MẠNH'
        elif n10_bil < -20 or (n10_bil < -5 and streak <= -2):
            f_trend = 'KHỐI NGOẠI BÁN RÒNG'
        else:
            f_trend = 'TRUNG TÍNH'

        foreign_summary = {
            'net_1d_bil': n1_bil,
            'net_5d_bil': n5_bil,
            'net_10d_bil': n10_bil,
            'net_20d_bil': n20_bil,
            'net_1d_vol': n1_vol,
            'net_5d_vol': n5_vol,
            'net_10d_vol': n10_vol,
            'net_20d_vol': n20_vol,
            'consecutive_days': streak,
            'trend': f_trend,
        }

    # Recent 10 sessions breakdown table (newest first)
    recent_rows = flow_present.tail(10).iloc[::-1]
    recent_sessions = []
    for _, r in recent_rows.iterrows():
        bu = _safe_int(r.get('active_buy_vol'))
        sd = _safe_int(r.get('active_sell_vol'))
        tot = (bu or 0) + (sd or 0)
        bu_pct = round(bu / tot * 100.0, 1) if (bu is not None and tot > 0) else None
        f_val = _safe_float(r.get('foreign_net_val'))
        recent_sessions.append({
            'date': str(r['date']),
            'close': _safe_float(r.get('close')),
            'change_pct': _safe_float(r.get('change_pct')),
            'volume': _safe_int(r.get('volume')),
            'active_buy_vol': bu,
            'active_sell_vol': sd,
            'active_buy_pct': bu_pct,
            'active_is_exact': bool(r.get('active_is_exact')) if pd.notna(r.get('active_is_exact')) else False,
            'foreign_net_vol': _safe_int(r.get('foreign_net_vol')),
            'foreign_net_val_bil': round(f_val / 1e9, 2) if f_val is not None else None,
        })

    return {
        'has_data': bool(latest_dict or active_10d or foreign_summary),
        'latest': latest_dict,
        'active_10d': active_10d,
        'foreign_summary': foreign_summary,
        'recent_sessions': recent_sessions,
    }
