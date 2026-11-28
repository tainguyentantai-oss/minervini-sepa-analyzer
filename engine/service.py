"""
Shared Stock Analysis Service Layer
Single source of truth reused by FastAPI endpoints, the Self-Hosted MCP Server,
and the AI SEPA/VSA Investment Analyst.
"""
import math
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from engine.fetcher import fetch_ohlcv, fetch_financial_ratios, get_company_name
from engine.minervini import (
    calculate_technical_indicators,
    evaluate_trend_template,
    detect_minervini_signals,
)
from engine.rs_rating import calculate_stock_rs_score
from engine.valuation import (
    fetch_broker_reports_live,
    fetch_company_valuation_live,
    is_cache_fresh,
    get_broker_consensus,
    calculate_valuation_metrics,
)
from engine.flow import (
    fetch_combined_daily_flow,
    merge_flow_into_chart_df,
    summarize_market_flow,
)
from engine.storage import (
    get_connection,
    save_ohlcv,
    load_ohlcv,
    save_rs_rating,
    get_rs_rating,
    save_fundamentals,
    get_fundamentals,
    save_daily_flow,
    load_daily_flow,
    save_broker_reports,
    load_broker_reports,
    save_company_valuation,
    load_company_valuation,
)


def clean_json_val(v: Any) -> Any:
    """Convert pandas/numpy scalars, NaN/NA, and Inf values safely for strict JSON."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f_val = float(v)
        if math.isnan(f_val) or math.isinf(f_val):
            return None
        return f_val
    return v


def sanitize_obj(obj: Any) -> Any:
    """Recursively sanitize dicts, lists, and numpy/pandas values for allow_nan=False JSON."""
    if isinstance(obj, dict):
        return {str(k): sanitize_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_obj(v) for v in obj]
    return clean_json_val(obj)


def get_stock_ohlcv_df(symbol: str) -> pd.DataFrame:
    """Load 3-5 years OHLCV from DuckDB, fetching live or topping up stale dates if needed."""
    symbol = symbol.upper().strip()
    today_str = datetime.now().strftime('%Y-%m-%d')

    df = load_ohlcv(symbol)
    if df is None or len(df) < 500:
        df = fetch_ohlcv(symbol, days=1825)
        if df is not None and len(df) > 0:
            save_ohlcv(symbol, df)
    else:
        latest_cached = str(df['date'].iloc[-1])
        if latest_cached < today_str:
            df_recent = fetch_ohlcv(symbol, days=30)
            if df_recent is not None and len(df_recent) > 0:
                save_ohlcv(symbol, df_recent)
                df = load_ohlcv(symbol)

    return df if df is not None else pd.DataFrame()


def get_full_stock_analysis(symbol: str, include_chart: bool = True) -> Optional[Dict[str, Any]]:
    """
    Unified full analysis pipeline:
    OHLCV -> 4-way concurrent cache-aware refresh -> Indicators & 4 VSA/SEPA signals ->
    RS Rating -> Trend Template 8/8 -> Broker Consensus & Live Valuation -> Micro-Flow.
    """
    symbol = symbol.upper().strip()
    df = get_stock_ohlcv_df(symbol)
    if df is None or len(df) == 0:
        return None

    latest_ohlcv_date = str(df['date'].iloc[-1])

    # Check cache freshness across all 4 live feeds
    df_flow = load_daily_flow(symbol)
    needs_flow_refresh = False
    if df_flow is None or len(df_flow) == 0:
        needs_flow_refresh = True
    else:
        latest_flow_date = str(df_flow['date'].iloc[-1])
        latest_row = df_flow[df_flow['date'] == latest_ohlcv_date]
        latest_is_exact = bool(latest_row['active_is_exact'].iloc[-1]) if len(latest_row) > 0 else False
        active_count = int(df_flow['active_buy_vol'].notna().sum())
        if latest_flow_date < latest_ohlcv_date or not latest_is_exact or active_count < 10:
            needs_flow_refresh = True

    fin_data = get_fundamentals(symbol)
    needs_fin_fetch = not fin_data

    cached_reports, rep_updated = load_broker_reports(symbol)
    needs_reports_refresh = (not cached_reports) or (not is_cache_fresh(rep_updated, max_hours=24))

    cached_val = load_company_valuation(symbol)
    needs_val_refresh = (not cached_val) or (not is_cache_fresh(cached_val.get('updated_at'), max_hours=24))

    df_new_flow = None
    ssi_snapshot = None
    live_reports = None
    live_val = None

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_flow = pool.submit(fetch_combined_daily_flow, symbol) if needs_flow_refresh else None
        f_fin = pool.submit(fetch_financial_ratios, symbol) if needs_fin_fetch else None
        f_rep = pool.submit(fetch_broker_reports_live, symbol) if needs_reports_refresh else None
        f_val = pool.submit(fetch_company_valuation_live, symbol) if needs_val_refresh else None

        if f_flow is not None:
            df_new_flow, ssi_snapshot = f_flow.result()
        if f_fin is not None:
            fin_data = f_fin.result()
        if f_rep is not None:
            live_reports = f_rep.result()
        if f_val is not None:
            live_val = f_val.result()

    if df_new_flow is not None and len(df_new_flow) > 0:
        save_daily_flow(symbol, df_new_flow)
        df_flow = load_daily_flow(symbol)

    if needs_fin_fetch and fin_data:
        save_fundamentals(fin_data)

    if live_reports:
        save_broker_reports(symbol, live_reports)
        cached_reports, _ = load_broker_reports(symbol)

    if live_val:
        save_company_valuation(symbol, live_val)
        cached_val = live_val

    if fin_data is not None and fin_data.get('roe') is None and cached_val and cached_val.get('roe') is not None:
        fin_data = {**fin_data, 'roe': round(float(cached_val['roe']), 1)}

    # Technical indicators & signals
    df_calc = calculate_technical_indicators(df)
    all_signals = detect_minervini_signals(df_calc)

    # RS Rating
    rs_val = get_rs_rating(symbol)
    if rs_val is None:
        raw_score = calculate_stock_rs_score(df_calc)
        rs_val = min(99, max(1, int(50 + raw_score * 40)))
        save_rs_rating(symbol, rs_val)

    # Trend Template 8/8
    trend_res = evaluate_trend_template(df_calc, rs_rating=rs_val)

    current_price = float(df_calc.iloc[-1]['close'])
    company_name = (
        (ssi_snapshot.get('company_name') if ssi_snapshot else None)
        or get_company_name(symbol)
    )
    exchange = (ssi_snapshot.get('exchange') if ssi_snapshot else None) or "HOSE"

    # Broker Consensus & Live Valuation
    broker_consensus = get_broker_consensus(symbol, current_price, raw_reports=cached_reports)
    valuation = calculate_valuation_metrics(symbol, current_price, fin_data or {}, live_val=cached_val)

    # Merge Micro-Flow
    df_merged = merge_flow_into_chart_df(df_calc, df_flow)
    market_flow = summarize_market_flow(df_flow, df_calc, snapshot=ssi_snapshot)

    chart_slice = df_merged.tail(1500)
    last_row_raw = chart_slice.iloc[-1].to_dict()
    latest_bar_keys = [
        'date', 'open', 'high', 'low', 'close', 'volume',
        'ma10', 'ma20', 'ma50', 'ma150', 'ma200',
        'vol_ma20', 'vol_ma50', 'high_52w', 'low_52w',
        'active_buy_pct', 'foreign_net_val_bil'
    ]
    latest_bar = {k: clean_json_val(last_row_raw.get(k)) for k in latest_bar_keys}

    if include_chart:
        chart_records = chart_slice.to_dict(orient='records')
        for row in chart_records:
            for k in list(row.keys()):
                row[k] = clean_json_val(row[k])
        valid_dates = {r['date'] for r in chart_records}
        chart_signals = [s for s in all_signals if s.get('time') in valid_dates][-60:]
    else:
        chart_records = []
        valid_dates = {str(d) for d in chart_slice['date'].tolist()}
        chart_signals = [s for s in all_signals if s.get('time') in valid_dates][-20:]

    recent_signals = list(reversed(chart_signals[-8:]))

    payload = {
        "symbol": symbol,
        "exchange": exchange,
        "company_name": company_name,
        "current_price": current_price,
        "rs_rating": rs_val,
        "trend_template": trend_res,
        "signals": chart_signals,
        "recent_signals": recent_signals,
        "latest_bar": latest_bar,
        "market_flow": market_flow,
        "fundamentals": fin_data,
        "broker_consensus": broker_consensus,
        "valuation": valuation,
        "chart_data": chart_records,
    }
    return sanitize_obj(payload)


def list_cached_symbols() -> List[str]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT DISTINCT symbol FROM daily_prices ORDER BY symbol ASC").fetchall()
        return [str(r[0]) for r in rows if r and r[0]]
    finally:
        conn.close()


def screen_sepa_watchlist(
    min_trend_score: int = 0,
    min_rs: int = 0,
    signal_code: str = "",
) -> List[Dict[str, Any]]:
    """
    Screen all stocks cached in DuckDB using Minervini Trend Template 8/8,
    RS Rating, latest 10-session signals (VCP/PP/SV/NS), and cached valuation.
    """
    symbols = list_cached_symbols()
    if not symbols:
        seed_tickers = ['FPT', 'HPG', 'MWG', 'CII', 'PVS']
        for sym in seed_tickers:
            get_stock_ohlcv_df(sym)
        symbols = list_cached_symbols()

    sig_filter = str(signal_code or '').upper().strip()
    results: List[Dict[str, Any]] = []

    for sym in symbols:
        try:
            df = load_ohlcv(sym)
            if df is None or len(df) < 60:
                continue

            df_calc = calculate_technical_indicators(df)
            signals = detect_minervini_signals(df_calc)

            rs_val = get_rs_rating(sym)
            if rs_val is None:
                raw_score = calculate_stock_rs_score(df_calc)
                rs_val = min(99, max(1, int(50 + raw_score * 40)))

            trend_res = evaluate_trend_template(df_calc, rs_rating=rs_val)
            trend_score = int(trend_res.get('score', 0))

            if trend_score < min_trend_score:
                continue
            if rs_val < min_rs:
                continue

            recent_dates_10 = {str(d) for d in df_calc['date'].tail(10).tolist()}
            recent_sigs = [s for s in signals if s.get('time') in recent_dates_10]
            recent_codes = [s.get('code') for s in recent_sigs]

            if sig_filter and sig_filter not in recent_codes:
                continue

            latest_sig = recent_sigs[-1] if recent_sigs else (signals[-1] if signals else None)
            val_cache = load_company_valuation(sym) or {}
            current_price = float(df_calc.iloc[-1]['close'])
            reps, _ = load_broker_reports(sym)
            bc_summary = None
            if reps:
                tps = [
                    float(r['target_price'])
                    for r in reps[:8]
                    if r.get('target_price') and 0.2 * current_price <= float(r['target_price']) <= 5.0 * current_price
                ]
                if tps:
                    avg_tp = round(sum(tps) / len(tps), -2)
                    bc_summary = {
                        'target_price': avg_tp,
                        'upside_pct': round((avg_tp - current_price) / current_price * 100.0, 1) if current_price > 0 else None,
                    }

            results.append({
                'symbol': sym,
                'date': str(df_calc.iloc[-1]['date']),
                'close': round(current_price, 0),
                'trend_score': trend_score,
                'trend_status': trend_res.get('status'),
                'rs_rating': rs_val,
                'recent_signal': f"{latest_sig['code']} ({latest_sig['time']})" if latest_sig else '--',
                'recent_signal_codes': recent_codes,
                'pe_trailing': clean_json_val(val_cache.get('pe_ratio')),
                'pb_ratio': clean_json_val(val_cache.get('pb_ratio')),
                'consensus_target': bc_summary['target_price'] if bc_summary else None,
                'upside_pct': bc_summary['upside_pct'] if bc_summary else None,
            })
        except Exception as e:
            print(f"[Screen] Skip {sym}: {e}")

    results.sort(key=lambda r: (r['trend_score'], r['rs_rating']), reverse=True)
    return sanitize_obj(results)
