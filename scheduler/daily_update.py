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
from engine.flow import fetch_combined_daily_flow
from engine.valuation import fetch_broker_reports_live, fetch_company_valuation_live
from engine.rs_rating import calculate_market_rs_ratings
from engine.storage import (
    save_ohlcv, save_rs_rating, save_fundamentals, save_daily_flow,
    save_broker_reports, save_company_valuation,
)

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

    # Fetch and save Micro-Flow (Active Buy/Sell & Foreign Net Flow)
    print("-> Đang lưu dữ liệu Dòng tiền (Mua/Bán chủ động chuẩn SSI & Khối ngoại)...")
    for sym in watchlist:
        try:
            df_flow, _ = fetch_combined_daily_flow(sym)
            if df_flow is not None and len(df_flow) > 0:
                save_daily_flow(sym, df_flow)
            time.sleep(0.15)
        except Exception as e:
            print(f"Lỗi tải Dòng tiền {sym}: {e}")

    # Refresh Broker Reports & Live Company Valuation Cache
    print("-> Đang làm mới Báo cáo CTCK & Định giá doanh nghiệp...")
    for sym in watchlist:
        try:
            reps = fetch_broker_reports_live(sym)
            if reps:
                save_broker_reports(sym, reps)
            val_live = fetch_company_valuation_live(sym)
            if val_live:
                save_company_valuation(sym, val_live)
            time.sleep(0.15)
        except Exception as e:
            print(f"Lỗi cập nhật CTCK/Định giá {sym}: {e}")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Hoàn tất cập nhật dữ liệu thành công!")


if __name__ == '__main__':
    run_daily_update()
