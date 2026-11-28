"""
Minervini SEPA Analyzer - Web Server + Self-Hosted MCP Server + AI Analyst
Built with FastAPI, DuckDB, Pandas, TradingView Lightweight Charts, and MCP JSON-RPC 2.0
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from engine.service import get_stock_ohlcv_df, get_full_stock_analysis
from engine.backtest import run_backtest
from engine.ai_analyst import analyze_stock_ai
from engine.mcp_core import handle_mcp_jsonrpc, get_mcp_server_metadata
from scheduler.daily_update import run_daily_update

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
os.makedirs(STATIC_DIR, exist_ok=True)

app = FastAPI(title="Minervini SEPA Analyzer & MCP Server")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Background Scheduler for daily 15:30 EOD update (Mon-Fri)
scheduler = AsyncIOScheduler()


class AiAnalyzeRequest(BaseModel):
    mode: str = "builtin"
    api_key: Optional[str] = None
    model: Optional[str] = None
    ollama_url: Optional[str] = None


def _check_mcp_auth(request: Request) -> bool:
    """Optional Bearer/token auth when MCP_API_KEY env var is configured."""
    expected = os.environ.get("MCP_API_KEY", "").strip()
    if not expected:
        return True
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        if auth_header[7:].strip() == expected:
            return True
    if request.query_params.get("token", "").strip() == expected:
        return True
    return False


@app.on_event("startup")
async def startup_event():
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
async def get_stock_analysis_api(symbol: str):
    data = get_full_stock_analysis(symbol, include_chart=True)
    if data is None:
        return JSONResponse(status_code=404, content={"error": f"Không tìm thấy dữ liệu cho mã {symbol.upper().strip()}"})
    return data


@app.get("/api/backtest/{symbol}")
async def run_stock_backtest(
    symbol: str,
    strategy: str = Query("sepa_combo"),
    years: int = Query(5, ge=0, le=10),
    stop_loss_pct: float = Query(7.0, ge=1.0, le=40.0),
    take_profit_pct: float = Query(20.0, ge=0.0, le=200.0),
    trailing_ma: str = Query("NONE"),
    max_hold_days: int = Query(60, ge=0, le=500),
):
    symbol = symbol.upper().strip()
    df = get_stock_ohlcv_df(symbol)
    if df is None or len(df) == 0:
        return JSONResponse(status_code=404, content={"error": f"Không tìm thấy dữ liệu lịch sử cho mã {symbol}"})

    return run_backtest(
        symbol=symbol,
        df_ohlcv=df,
        strategy=strategy,
        years=years,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        trailing_ma=trailing_ma,
        max_hold_days=max_hold_days,
    )


@app.post("/api/ai-analyze/{symbol}")
async def ai_analyze_stock_api(symbol: str, body: AiAnalyzeRequest):
    result = analyze_stock_ai(
        symbol=symbol,
        mode=body.mode,
        api_key=body.api_key,
        model=body.model,
        ollama_url=body.ollama_url,
    )
    if result is None:
        return JSONResponse(status_code=404, content={"error": f"Không tìm thấy dữ liệu cho mã {symbol.upper().strip()}"})
    return result


# ==============================================================================
# Self-Hosted Standard MCP (Model Context Protocol) Streamable HTTP Endpoints
# ==============================================================================
MCP_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, Mcp-Session-Id, MCP-Protocol-Version",
}


@app.options("/mcp")
async def mcp_options():
    return Response(status_code=204, headers=MCP_CORS_HEADERS)


@app.get("/mcp")
async def mcp_discovery(request: Request):
    base = str(request.base_url).rstrip("/")
    return JSONResponse(content=get_mcp_server_metadata(base), headers=MCP_CORS_HEADERS)


@app.post("/mcp")
async def mcp_jsonrpc_endpoint(request: Request):
    if not _check_mcp_auth(request):
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "message": "Invalid or missing MCP Bearer token"},
            headers={"WWW-Authenticate": "Bearer", **MCP_CORS_HEADERS},
        )

    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {e}"}},
            headers=MCP_CORS_HEADERS,
        )

    resp = handle_mcp_jsonrpc(payload)
    if resp is None:
        return Response(status_code=202, headers=MCP_CORS_HEADERS)

    return JSONResponse(
        content=resp,
        headers={"MCP-Protocol-Version": "2024-11-05", **MCP_CORS_HEADERS},
    )


@app.get("/api/mcp/info")
async def mcp_info_api(request: Request):
    base = str(request.base_url).rstrip("/")
    meta = get_mcp_server_metadata(base)
    meta["stdio_python"] = str(BASE_DIR / ".venv" / "bin" / "python")
    meta["stdio_script"] = str(BASE_DIR / "mcp_server.py")
    return meta


@app.post("/api/update-daily")
async def trigger_daily_update_api(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_daily_update)
    return {"message": "Đang chạy cập nhật toàn thị trường trong nền..."}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
