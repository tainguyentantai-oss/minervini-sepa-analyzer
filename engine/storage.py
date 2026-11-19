"""
Local Database and Cache Layer for Vietnam Stock Market Data
Uses DuckDB for ultra-fast time series analytical storage.
"""
import os
from pathlib import Path
from typing import Dict, Any, Optional
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
