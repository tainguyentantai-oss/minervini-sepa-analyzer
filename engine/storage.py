"""
Local Database and Cache Layer for Vietnam Stock Market Data
Uses DuckDB for ultra-fast time series analytical storage.
"""
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import duckdb
import pandas as pd

DB_DIR = Path(os.environ.get("DB_DIR", "/tmp" if os.environ.get("VERCEL") else (Path(__file__).resolve().parent.parent / "data")))
DB_PATH = DB_DIR / "stock_data.duckdb"

def get_connection():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH))
    # Initialize tables if not exist
    conn.execute("""
    CREATE TABLE IF NOT EXISTS daily_prices (
        symbol VARCHAR,
        date VARCHAR,
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        close DOUBLE,
        volume BIGINT,
        PRIMARY KEY (symbol, date)
    );
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS rs_ratings (
        symbol VARCHAR PRIMARY KEY,
        rs_rating INTEGER,
        updated_at VARCHAR
    );
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS fundamentals (
        symbol VARCHAR PRIMARY KEY,
        quarter VARCHAR,
        eps_growth_yoy DOUBLE,
        rev_growth_yoy DOUBLE,
        gross_margin DOUBLE,
        roe DOUBLE,
        updated_at VARCHAR
    );
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS daily_flow (
        symbol VARCHAR,
        date VARCHAR,
        active_buy_vol BIGINT,
        active_sell_vol BIGINT,
        active_is_exact BOOLEAN DEFAULT FALSE,
        foreign_buy_vol BIGINT,
        foreign_sell_vol BIGINT,
        foreign_net_vol BIGINT,
        foreign_buy_val DOUBLE,
        foreign_sell_val DOUBLE,
        foreign_net_val DOUBLE,
        updated_at VARCHAR,
        PRIMARY KEY (symbol, date)
    );
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS broker_reports (
        symbol VARCHAR,
        report_id VARCHAR,
        broker VARCHAR,
        issue_date VARCHAR,
        action VARCHAR,
        target_price DOUBLE,
        title VARCHAR,
        pdf_url VARCHAR,
        updated_at VARCHAR,
        PRIMARY KEY (symbol, report_id)
    );
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS company_valuation_cache (
        symbol VARCHAR PRIMARY KEY,
        sector VARCHAR,
        industry VARCHAR,
        pe_ratio DOUBLE,
        pb_ratio DOUBLE,
        eps_ttm DOUBLE,
        book_value DOUBLE,
        ev_ebitda DOUBLE,
        market_cap DOUBLE,
        dividend_yield DOUBLE,
        beta_5y DOUBLE,
        roe DOUBLE,
        roa DOUBLE,
        ni_5y_growth DOUBLE,
        rev_5y_growth DOUBLE,
        updated_at VARCHAR
    );
    """)
    return conn

def save_ohlcv(symbol: str, df: pd.DataFrame):
    if df is None or len(df) == 0:
        return
    conn = get_connection()
    try:
        df_to_save = df[['date', 'open', 'high', 'low', 'close', 'volume']].copy()
        df_to_save['symbol'] = symbol.upper()
        # Upsert into daily_prices
        conn.register('temp_df', df_to_save)
        conn.execute("""
        INSERT OR REPLACE INTO daily_prices
        SELECT symbol, date, open, high, low, close, volume FROM temp_df
        """)
    finally:
        conn.close()

def load_ohlcv(symbol: str) -> pd.DataFrame:
    conn = get_connection()
    try:
        symbol = symbol.upper()
        res = conn.execute("""
        SELECT date, open, high, low, close, volume
        FROM daily_prices
        WHERE symbol = ?
        ORDER BY date ASC
        """, [symbol]).fetchdf()
        return res
    finally:
        conn.close()

def save_rs_rating(symbol: str, rating: int):
    conn = get_connection()
    try:
        from datetime import datetime
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("""
        INSERT OR REPLACE INTO rs_ratings VALUES (?, ?, ?)
        """, [symbol.upper(), rating, now_str])
    finally:
        conn.close()

def get_rs_rating(symbol: str) -> Optional[int]:
    conn = get_connection()
    try:
        res = conn.execute("""
        SELECT rs_rating FROM rs_ratings WHERE symbol = ?
        """, [symbol.upper()]).fetchone()
        return res[0] if res else None
    finally:
        conn.close()

def save_fundamentals(data: Dict[str, Any]):
    conn = get_connection()
    try:
        from datetime import datetime
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("""
        INSERT OR REPLACE INTO fundamentals VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            data['symbol'].upper(),
            data.get('quarter', ''),
            data.get('eps_growth_yoy'),
            data.get('rev_growth_yoy'),
            data.get('gross_margin'),
            data.get('roe'),
            now_str
        ])
    finally:
        conn.close()

def get_fundamentals(symbol: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        res = conn.execute("""
        SELECT symbol, quarter, eps_growth_yoy, rev_growth_yoy, gross_margin, roe, updated_at
        FROM fundamentals WHERE symbol = ?
        """, [symbol.upper()]).fetchone()
        if res:
            return {
                'symbol': res[0],
                'quarter': res[1],
                'eps_growth_yoy': res[2],
                'rev_growth_yoy': res[3],
                'gross_margin': res[4],
                'roe': res[5],
                'updated_at': res[6]
            }
        return None
    finally:
        conn.close()


def save_daily_flow(symbol: str, df_flow: pd.DataFrame):
    """
    Upsert daily active buy/sell & foreign flow into DuckDB.
    Preserves exact SSI active buy/sell records so later estimated rows never overwrite them.
    """
    if df_flow is None or len(df_flow) == 0:
        return

    from datetime import datetime
    expected_cols = [
        'date', 'active_buy_vol', 'active_sell_vol', 'active_is_exact',
        'foreign_buy_vol', 'foreign_sell_vol', 'foreign_net_vol',
        'foreign_buy_val', 'foreign_sell_val', 'foreign_net_val'
    ]
    df_save = df_flow.copy()
    for col in expected_cols:
        if col not in df_save.columns:
            df_save[col] = False if col == 'active_is_exact' else None

    df_save = df_save.dropna(subset=['date']).drop_duplicates(subset=['date'], keep='last').copy()
    if len(df_save) == 0:
        return

    df_save['active_is_exact'] = df_save['active_is_exact'].map(lambda x: bool(x) if pd.notna(x) else False)
    df_save['symbol'] = symbol.upper().strip()
    df_save['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cols_order = [
        'symbol', 'date', 'active_buy_vol', 'active_sell_vol', 'active_is_exact',
        'foreign_buy_vol', 'foreign_sell_vol', 'foreign_net_vol',
        'foreign_buy_val', 'foreign_sell_val', 'foreign_net_val', 'updated_at'
    ]
    df_save = df_save[cols_order]

    # Normalize nullable numeric columns for DuckDB registration
    int_cols = [
        'active_buy_vol', 'active_sell_vol',
        'foreign_buy_vol', 'foreign_sell_vol', 'foreign_net_vol'
    ]
    float_cols = ['foreign_buy_val', 'foreign_sell_val', 'foreign_net_val']
    for c in int_cols:
        df_save[c] = pd.to_numeric(df_save[c], errors='coerce').astype('Int64')
    for c in float_cols:
        df_save[c] = pd.to_numeric(df_save[c], errors='coerce').astype('float64')

    conn = get_connection()
    try:
        conn.register('temp_flow_df', df_save)
        conn.execute("""
        INSERT INTO daily_flow (
            symbol, date, active_buy_vol, active_sell_vol, active_is_exact,
            foreign_buy_vol, foreign_sell_vol, foreign_net_vol,
            foreign_buy_val, foreign_sell_val, foreign_net_val, updated_at
        )
        SELECT
            symbol, date, active_buy_vol, active_sell_vol, active_is_exact,
            foreign_buy_vol, foreign_sell_vol, foreign_net_vol,
            foreign_buy_val, foreign_sell_val, foreign_net_val, updated_at
        FROM temp_flow_df
        ON CONFLICT (symbol, date) DO UPDATE SET
            active_buy_vol = CASE
                WHEN daily_flow.active_is_exact AND NOT excluded.active_is_exact THEN daily_flow.active_buy_vol
                WHEN excluded.active_buy_vol IS NOT NULL AND (excluded.active_buy_vol > 0 OR excluded.active_sell_vol > 0) THEN excluded.active_buy_vol
                ELSE daily_flow.active_buy_vol
            END,
            active_sell_vol = CASE
                WHEN daily_flow.active_is_exact AND NOT excluded.active_is_exact THEN daily_flow.active_sell_vol
                WHEN excluded.active_sell_vol IS NOT NULL AND (excluded.active_buy_vol > 0 OR excluded.active_sell_vol > 0) THEN excluded.active_sell_vol
                ELSE daily_flow.active_sell_vol
            END,
            active_is_exact = daily_flow.active_is_exact OR excluded.active_is_exact,
            foreign_buy_vol = COALESCE(excluded.foreign_buy_vol, daily_flow.foreign_buy_vol),
            foreign_sell_vol = COALESCE(excluded.foreign_sell_vol, daily_flow.foreign_sell_vol),
            foreign_net_vol = COALESCE(excluded.foreign_net_vol, daily_flow.foreign_net_vol),
            foreign_buy_val = COALESCE(excluded.foreign_buy_val, daily_flow.foreign_buy_val),
            foreign_sell_val = COALESCE(excluded.foreign_sell_val, daily_flow.foreign_sell_val),
            foreign_net_val = COALESCE(excluded.foreign_net_val, daily_flow.foreign_net_val),
            updated_at = excluded.updated_at
        """)
    finally:
        conn.close()


def load_daily_flow(symbol: str) -> pd.DataFrame:
    conn = get_connection()
    try:
        res = conn.execute("""
        SELECT
            date, active_buy_vol, active_sell_vol, active_is_exact,
            foreign_buy_vol, foreign_sell_vol, foreign_net_vol,
            foreign_buy_val, foreign_sell_val, foreign_net_val
        FROM daily_flow
        WHERE symbol = ?
        ORDER BY date ASC
        """, [symbol.upper().strip()]).fetchdf()
        return res
    finally:
        conn.close()


def save_broker_reports(symbol: str, reports: List[Dict[str, Any]]):
    if not reports:
        return
    from datetime import datetime
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sym = symbol.upper().strip()
    conn = get_connection()
    try:
        for r in reports:
            rid = str(r.get('report_id') or f"{r.get('broker', 'CTCK')}_{r.get('issue_date', '')}")
            conn.execute("""
            INSERT OR REPLACE INTO broker_reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                sym,
                rid,
                r.get('broker') or 'CTCK',
                r.get('issue_date') or '',
                r.get('action') or 'CẬP NHẬT',
                r.get('target_price'),
                r.get('title') or '',
                r.get('pdf_url') or '',
                now_str
            ])
    finally:
        conn.close()


def load_broker_reports(symbol: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    conn = get_connection()
    try:
        rows = conn.execute("""
        SELECT report_id, broker, issue_date, action, target_price, title, pdf_url, updated_at
        FROM broker_reports
        WHERE symbol = ?
        ORDER BY issue_date DESC
        """, [symbol.upper().strip()]).fetchall()
        if not rows:
            return [], None
        reports = []
        max_upd = None
        for r in rows:
            upd = r[7]
            if upd and (max_upd is None or upd > max_upd):
                max_upd = upd
            reports.append({
                'report_id': r[0],
                'broker': r[1],
                'issue_date': r[2],
                'action': r[3],
                'target_price': r[4],
                'title': r[5],
                'pdf_url': r[6],
            })
        return reports, max_upd
    finally:
        conn.close()


def save_company_valuation(symbol: str, data: Dict[str, Any]):
    if not data:
        return
    from datetime import datetime
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_connection()
    try:
        conn.execute("""
        INSERT OR REPLACE INTO company_valuation_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            symbol.upper().strip(),
            data.get('sector'),
            data.get('industry'),
            data.get('pe_ratio'),
            data.get('pb_ratio'),
            data.get('eps_ttm'),
            data.get('book_value'),
            data.get('ev_ebitda'),
            data.get('market_cap'),
            data.get('dividend_yield'),
            data.get('beta_5y'),
            data.get('roe'),
            data.get('roa'),
            data.get('ni_5y_growth'),
            data.get('rev_5y_growth'),
            now_str,
        ])
    finally:
        conn.close()


def load_company_valuation(symbol: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        res = conn.execute("""
        SELECT
            sector, industry, pe_ratio, pb_ratio, eps_ttm, book_value,
            ev_ebitda, market_cap, dividend_yield, beta_5y, roe, roa,
            ni_5y_growth, rev_5y_growth, updated_at
        FROM company_valuation_cache
        WHERE symbol = ?
        """, [symbol.upper().strip()]).fetchone()
        if not res:
            return None
        return {
            'sector': res[0],
            'industry': res[1],
            'pe_ratio': res[2],
            'pb_ratio': res[3],
            'eps_ttm': res[4],
            'book_value': res[5],
            'ev_ebitda': res[6],
            'market_cap': res[7],
            'dividend_yield': res[8],
            'beta_5y': res[9],
            'roe': res[10],
            'roa': res[11],
            'ni_5y_growth': res[12],
            'rev_5y_growth': res[13],
            'updated_at': res[14],
        }
    finally:
        conn.close()
