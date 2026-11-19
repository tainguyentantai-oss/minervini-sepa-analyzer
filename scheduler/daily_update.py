"""
Daily market data updater (Runs automatically after 15:15 every trading day)
1. Fetches latest OHLCV for watched stocks
2. Calculates updated RS Ratings (1-99)
3. Caches quarterly financial ratios
4. Saves to local DuckDB database
"""
import sys
import time
from pathlib import Path
from datetime import datetime

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from engine.fetcher import fetch_ohlcv, fetch_financial_ratios
from engine.rs_rating import calculate_market_rs_ratings
from engine.storage import save_ohlcv, save_rs_rating, save_fundamentals

# Default universe of top liquid and growth stocks in Vietnam
WATCHLIST = [
    'FPT', 'HPG', 'MWG', 'VNM', 'DGC', 'FRT', 'CTR', 'PNJ',
    'VCI', 'SSI', 'TCB', 'MBB', 'ACB', 'VCB', 'CTG',
    'KDH', 'NLG', 'VHM', 'VIC', 'GAS', 'PVD', 'PVS',
    'VTP', 'DBC', 'GMD', 'REE', 'HAH', 'MSN', 'STB', 'TPB'
]

def run_daily_update(watchlist=None):
    if watchlist is None:
        watchlist = WATCHLIST

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bắt đầu cập nhật dữ liệu hàng ngày cho {len(watchlist)} mã cổ phiếu...")

    stock_dfs = {}
    for sym in watchlist:
        try:
            print(f"-> Đang tải nến EOD cho {sym}...")
            df = fetch_ohlcv(sym, days=365)
            if df is not None and len(df) > 0:
                save_ohlcv(sym, df)
                stock_dfs[sym] = df
            time.sleep(0.1) # polite delay
        except Exception as e:
            print(f"Lỗi tải nến {sym}: {e}")

    # Calculate and save RS Ratings
    print("-> Đang tính toán RS Rating phân vị (1-99)...")
    rs_ratings = calculate_market_rs_ratings(stock_dfs)
    for sym, rating in rs_ratings.items():
        save_rs_rating(sym, rating)
        print(f"   {sym}: RS Rating = {rating}/99")

    # Fetch and save Financial Ratios
    print("-> Đang cập nhật Báo cáo tài chính quý gần nhất...")
    for sym in watchlist:
        try:
            fin = fetch_financial_ratios(sym)
            if fin:
                save_fundamentals(fin)
            time.sleep(0.1)
        except Exception as e:
            print(f"Lỗi tải BCTC {sym}: {e}")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Hoàn tất cập nhật dữ liệu thành công!")


if __name__ == '__main__':
    run_daily_update()
