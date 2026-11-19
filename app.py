"""
Minervini SEPA Analyzer - Web Server
Built with FastAPI, DuckDB, Pandas, and TradingView Lightweight Charts
"""
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from engine.fetcher import fetch_ohlcv, fetch_financial_ratios, get_company_name
from engine.minervini import calculate_technical_indicators, evaluate_trend_template, detect_minervini_signals
from engine.rs_rating import calculate_stock_rs_score
from engine.storage import (
    save_ohlcv, load_ohlcv, save_rs_rating, get_rs_rating,
    save_fundamentals, get_fundamentals
)
from scheduler.daily_update import run_daily_update, WATCHLIST

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
os.makedirs(STATIC_DIR, exist_ok=True)

app = FastAPI(title="Minervini SEPA Analyzer")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Background Scheduler for daily 15:30 EOD update (Mon-Fri)
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup_event():
    # Schedule daily job at 15:30 Monday-Friday (Asia/Ho_Chi_Minh timezone)
    scheduler.add_job(
        run_daily_update,
        CronTrigger(day_of_week='mon-fri', hour=15, minute=30, timezone='Asia/Ho_Chi_Minh'),
        id="daily_eod_update",
        replace_existing=True
    )
    scheduler.start()
    print("[Server] APScheduler started: Daily EOD update scheduled at 15:30 (Mon-Fri).")


@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/stock/{symbol}")
async def get_stock_analysis(symbol: str):
    symbol = symbol.upper().strip()

    # 1. Load from DB or Fetch live
    df = load_ohlcv(symbol)
    if df is None or len(df) < 50:
        df = fetch_ohlcv(symbol, days=365)
        if df is not None and len(df) > 0:
            save_ohlcv(symbol, df)

    if df is None or len(df) == 0:
        return JSONResponse(status_code=404, content={"error": f"Không tìm thấy dữ liệu cho mã {symbol}"})

    # 2. Calculate Indicators & Minervini signals
    df_calc = calculate_technical_indicators(df)
    signals = detect_minervini_signals(df_calc)

    # 3. RS Rating (1-99)
    rs_val = get_rs_rating(symbol)
    if rs_val is None:
        # Approximate score if market rank isn't built yet
        raw_score = calculate_stock_rs_score(df_calc)
        # Normalize typical score to 50-95 percentile estimate
        rs_val = min(99, max(1, int(50 + raw_score * 40)))
        save_rs_rating(symbol, rs_val)

    # 4. Trend Template (8/8 criteria)
    trend_res = evaluate_trend_template(df_calc, rs_rating=rs_val)

    # 5. Financial statements & ratios
    fin_data = get_fundamentals(symbol)
    if not fin_data:
        fin_data = fetch_financial_ratios(symbol)
        if fin_data:
            save_fundamentals(fin_data)

    current_price = float(df_calc.iloc[-1]['close'])
    company_name = get_company_name(symbol)

    # Format chart data
    chart_records = df_calc.tail(250).to_dict(orient='records')
    # Clean NaN values for JSON serialization
    for row in chart_records:
        for k, v in row.items():
            if str(v) == 'nan':
                row[k] = None

    return {
        "symbol": symbol,
        "company_name": company_name,
        "current_price": current_price,
        "rs_rating": rs_val,
        "trend_template": trend_res,
        "signals": signals[-10:], # latest signals
        "fundamentals": fin_data,
        "chart_data": chart_records
    }


@app.post("/api/update-daily")
async def trigger_daily_update_api(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_daily_update)
    return {"message": "Đang chạy cập nhật toàn thị trường trong nền..."}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
