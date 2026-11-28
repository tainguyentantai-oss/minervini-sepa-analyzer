"""
Self-Hosted Model Context Protocol (MCP) Core (Phase 3)
Implements standard MCP JSON-RPC 2.0 protocol for both:
- Streamable HTTP endpoint (POST /mcp in FastAPI / Vercel)
- Local Stdio server (mcp_server.py for Claude Desktop / Cursor / Antigravity IDE)
Zero paid 3rd-party dependencies.
"""
import json
import os
from typing import Any, Dict, List, Optional

from engine.ai_analyst import analyze_stock_ai
from engine.backtest import run_backtest
from engine.service import (
    get_full_stock_analysis,
    get_stock_ohlcv_df,
    list_cached_symbols,
    sanitize_obj,
    screen_sepa_watchlist,
)

SERVER_NAME = "minervini-sepa-mcp"
SERVER_VERSION = "1.0.0"
SUPPORTED_PROTOCOLS = ["2025-03-26", "2024-11-05"]

MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "get_stock_overview",
        "description": (
            "Lấy tổng quan phân tích Mark Minervini SEPA cho một mã cổ phiếu Việt Nam: "
            "giá hiện tại, 5 đường MA (MA10/20/50/150/200), RS Rating (1-99), 8/8 tiêu chí Trend Template và BCTC quý."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Mã cổ phiếu Việt Nam (ví dụ: FPT, CII, HPG, PVS, MWG)"
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_market_flow",
        "description": (
            "Lấy dữ liệu Dòng tiền Vi mô (Micro-Flow): Khớp lệnh Mua/Bán Chủ động (phiên gần nhất chuẩn SSI + "
            "lịch sử 10-20 phiên) và Mua/Bán ròng Khối ngoại 1D/5D/10D/20D kèm chuỗi phiên liên tiếp."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Mã cổ phiếu Việt Nam (ví dụ: CII, FPT)"
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_vsa_and_pivot_signals",
        "description": (
            "Quét tín hiệu kỹ thuật & Wyckoff VSA trong dữ liệu lịch sử 5 năm: Breakout VCP, Pocket Pivot (Morales & Kacher), "
            "Stopping Volume / Rũ bỏ hấp thụ (SV), và No Supply Test / Cạn cung (NS)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Mã cổ phiếu Việt Nam"},
                "limit": {"type": "integer", "description": "Số tín hiệu gần nhất cần lấy (mặc định 12)", "default": 12},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_valuation_and_consensus",
        "description": (
            "Lấy chỉ số định giá thực tế (P/E Trailing, P/B, EPS TTM, BVPS, Vốn hóa, Cổ tức, PEG Peter Lynch, "
            "Định giá hợp lý Graham & P/E ngành) cùng Đồng thuận Giá mục tiêu CTCK (SSI, MAS, MBS, ACBS, KBSV...) và link PDF."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Mã cổ phiếu Việt Nam"}
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "run_strategy_backtest",
        "description": (
            "Chạy kiểm định chiến lược giao dịch lịch sử 1-5 năm trên dữ liệu DuckDB (chuẩn T+2.5 Việt Nam, phí & thuế 0.35%). "
            "Trả về Win Rate, Profit Factor, R/R, Alpha vs Buy & Hold, Max Drawdown và 10 lệnh gần nhất."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Mã cổ phiếu Việt Nam"},
                "strategy": {
                    "type": "string",
                    "enum": ["sepa_combo", "pocket_pivot", "breakout_vcp", "wyckoff_vsa", "trend_ma50"],
                    "default": "sepa_combo",
                    "description": "Tên chiến lược kiểm định"
                },
                "years": {"type": "integer", "default": 5, "description": "Số năm kiểm định (1, 3, 5 hoặc 0 = toàn bộ)"},
                "stop_loss_pct": {"type": "number", "default": 7.0, "description": "Mức cắt lỗ (%)"},
                "take_profit_pct": {"type": "number", "default": 20.0, "description": "Mức chốt lời (%)"},
                "trailing_ma": {"type": "string", "enum": ["NONE", "MA10", "MA20", "MA50"], "default": "NONE"},
                "max_hold_days": {"type": "integer", "default": 60, "description": "Số phiên nắm giữ tối đa"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "analyze_stock_sepa_ai",
        "description": (
            "Chạy phân tích đầu tư SEPA/VSA tổng hợp (0-100 điểm, khuyến nghị hành động, kế hoạch vùng mua / cắt lỗ -7% / mục tiêu) "
            "và xuất báo cáo nhận định chi tiết không ảo giác số liệu."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Mã cổ phiếu Việt Nam"}
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "screen_sepa_watchlist",
        "description": (
            "Sàng lọc toàn bộ các mã cổ phiếu đã lưu trong cơ sở dữ liệu DuckDB theo điểm Trend Template (0-8), "
            "RS Rating tối thiểu (1-99) và tín hiệu gần đây (VCP, PP, SV, NS)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "min_trend_score": {"type": "integer", "default": 0, "description": "Điểm Trend Template tối thiểu (0-8)"},
                "min_rs": {"type": "integer", "default": 0, "description": "RS Rating tối thiểu (0-99)"},
                "signal_code": {
                    "type": "string",
                    "default": "",
                    "description": "Lọc mã có tín hiệu trong 10 phiên gần nhất: VCP, PP, SV, NS hoặc để trống"
                },
            },
        },
    },
]

MCP_RESOURCES: List[Dict[str, Any]] = [
    {
        "uri": "sepa://watchlist",
        "name": "Danh sách mã cổ phiếu đang lưu trong DuckDB",
        "description": "Liệt kê các mã chứng khoán Việt Nam hiện đã có dữ liệu nến 5 năm trong bộ nhớ cục bộ.",
        "mimeType": "application/json",
    },
    {
        "uri": "sepa://methodology",
        "name": "Phương pháp luận SEPA, Wyckoff VSA & Pocket Pivot",
        "description": "Bộ quy tắc chuẩn Mark Minervini Trend Template 8/8, IBD RS Rating, Wyckoff VSA và Pocket Pivot.",
        "mimeType": "text/markdown",
    },
]

MCP_PROMPTS: List[Dict[str, Any]] = [
    {
        "name": "sepa_deep_analysis",
        "description": "Kịch bản hỏi đáp phân tích chuyên sâu 1 cổ phiếu Việt Nam chuẩn SEPA + VSA + Dòng tiền + Định giá.",
        "arguments": [
            {"name": "symbol", "description": "Mã cổ phiếu cần phân tích (ví dụ FPT, CII)", "required": True}
        ],
    },
    {
        "name": "compare_two_stocks",
        "description": "So sánh 2 cổ phiếu Việt Nam về xu hướng SEPA, RS Rating, dòng tiền ngoại, định giá và hiệu quả backtest.",
        "arguments": [
            {"name": "symbol_a", "description": "Mã cổ phiếu thứ nhất", "required": True},
            {"name": "symbol_b", "description": "Mã cổ phiếu thứ hai", "required": True},
        ],
    },
]

METHODOLOGY_DOC = """# Phương Pháp Luận Hệ Thống Minervini SEPA Analyzer (VN Equities)

1. **Mark Minervini Trend Template (8/8 Tiêu chí Stage 2):**
   - Giá > MA50, MA150, MA200; MA150 > MA200; MA200 hướng lên >= 1 tháng; MA50 > MA150 & MA200.
   - Giá tăng từ đáy 52 tuần >= 25% và nằm trong phạm vi <= 25% từ đỉnh 52 tuần.
   - IBD Relative Strength (RS Rating) >= 70 (trọng số 40% Q1 + 20% Q2 + 20% Q3 + 20% Q4).
2. **Tín Hiệu Mua & Wyckoff VSA:**
   - **VCP (Breakout VCP):** Vượt đỉnh 20 phiên, Vol >= 1.5x Vol MA50, giá đóng cửa trên MA50.
   - **PP (Pocket Pivot - Morales & Kacher):** Phiên tăng quanh MA10/MA50 với khối lượng vượt đỉnh khối lượng các phiên giảm trong 10 ngày trước.
   - **SV (Stopping Volume - VSA):** Nến rút chân hấp thụ khối lượng >= 1.8x Vol MA20 tại vùng điều chỉnh/đáy 10 phiên.
   - **NS (No Supply Test - VSA):** Nến biên độ hẹp với khối lượng cạn kiệt < 65% Vol MA20 và thấp hơn 2 phiên trước.
3. **Dòng Tiền Vi Mô & Backtest T+2.5:**
   - Khớp lệnh chủ động chuẩn SSI (`stockBUVol`/`stockSDVol`) kết hợp ước tính nến 1 phút (Tick Rule) và mua/bán ròng khối ngoại.
   - Kiểm định chiến lược 5 năm tuân thủ T+2.5 Việt Nam và trừ 0.35% phí/thuế hai chiều.
"""


def _tool_result(obj: Any, is_error: bool = False) -> Dict[str, Any]:
    if isinstance(obj, str):
        text = obj
    else:
        text = json.dumps(sanitize_obj(obj), ensure_ascii=False, indent=2, allow_nan=False)
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def execute_mcp_tool(name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    args = arguments or {}
    try:
        if name == "get_stock_overview":
            sym = str(args.get("symbol") or "").upper().strip()
            if not sym:
                return _tool_result("Thiếu tham số bắt buộc 'symbol'.", is_error=True)
            data = get_full_stock_analysis(sym, include_chart=False)
            if not data:
                return _tool_result(f"Không tìm thấy dữ liệu cho mã {sym}.", is_error=True)
            return _tool_result({
                "symbol": data["symbol"],
                "company_name": data["company_name"],
                "exchange": data["exchange"],
                "current_price": data["current_price"],
                "rs_rating": data["rs_rating"],
                "latest_bar": data["latest_bar"],
                "trend_template": data["trend_template"],
                "fundamentals": data["fundamentals"],
            })

        if name == "get_market_flow":
            sym = str(args.get("symbol") or "").upper().strip()
            if not sym:
                return _tool_result("Thiếu tham số bắt buộc 'symbol'.", is_error=True)
            data = get_full_stock_analysis(sym, include_chart=False)
            if not data:
                return _tool_result(f"Không tìm thấy dữ liệu cho mã {sym}.", is_error=True)
            return _tool_result({
                "symbol": data["symbol"],
                "current_price": data["current_price"],
                "market_flow": data["market_flow"],
            })

        if name == "get_vsa_and_pivot_signals":
            sym = str(args.get("symbol") or "").upper().strip()
            if not sym:
                return _tool_result("Thiếu tham số bắt buộc 'symbol'.", is_error=True)
            limit = max(1, min(40, int(args.get("limit") or 12)))
            data = get_full_stock_analysis(sym, include_chart=False)
            if not data:
                return _tool_result(f"Không tìm thấy dữ liệu cho mã {sym}.", is_error=True)
            sigs = list(reversed((data.get("signals") or [])[-limit:]))
            return _tool_result({
                "symbol": data["symbol"],
                "current_price": data["current_price"],
                "total_returned": len(sigs),
                "signals": sigs,
            })

        if name == "get_valuation_and_consensus":
            sym = str(args.get("symbol") or "").upper().strip()
            if not sym:
                return _tool_result("Thiếu tham số bắt buộc 'symbol'.", is_error=True)
            data = get_full_stock_analysis(sym, include_chart=False)
            if not data:
                return _tool_result(f"Không tìm thấy dữ liệu cho mã {sym}.", is_error=True)
            return _tool_result({
                "symbol": data["symbol"],
                "company_name": data["company_name"],
                "current_price": data["current_price"],
                "valuation": data["valuation"],
                "broker_consensus": data["broker_consensus"],
            })

        if name == "run_strategy_backtest":
            sym = str(args.get("symbol") or "").upper().strip()
            if not sym:
                return _tool_result("Thiếu tham số bắt buộc 'symbol'.", is_error=True)
            df = get_stock_ohlcv_df(sym)
            if df is None or len(df) == 0:
                return _tool_result(f"Không tìm thấy dữ liệu lịch sử cho mã {sym}.", is_error=True)
            bt = run_backtest(
                symbol=sym,
                df_ohlcv=df,
                strategy=str(args.get("strategy") or "sepa_combo"),
                years=int(args.get("years") if args.get("years") is not None else 5),
                stop_loss_pct=float(args.get("stop_loss_pct") or 7.0),
                take_profit_pct=float(args.get("take_profit_pct") if args.get("take_profit_pct") is not None else 20.0),
                trailing_ma=str(args.get("trailing_ma") or "NONE"),
                max_hold_days=int(args.get("max_hold_days") if args.get("max_hold_days") is not None else 60),
            )
            return _tool_result({
                "symbol": bt.get("symbol"),
                "strategy": bt.get("strategy"),
                "strategy_name": bt.get("strategy_name"),
                "period": bt.get("period"),
                "params": bt.get("params"),
                "metrics": bt.get("metrics"),
                "recent_trades": (bt.get("trades") or [])[:10],
            })

        if name == "analyze_stock_sepa_ai":
            sym = str(args.get("symbol") or "").upper().strip()
            if not sym:
                return _tool_result("Thiếu tham số bắt buộc 'symbol'.", is_error=True)
            res = analyze_stock_ai(sym, mode="builtin")
            if not res:
                return _tool_result(f"Không tìm thấy dữ liệu cho mã {sym}.", is_error=True)
            return _tool_result({
                "symbol": res["symbol"],
                "company_name": res["company_name"],
                "score": res["score"],
                "action": res["action"],
                "pillars": res["pillars"],
                "trade_plan": res["trade_plan"],
                "report_markdown": res["report_markdown"],
            })

        if name == "screen_sepa_watchlist":
            min_ts = int(args.get("min_trend_score") or 0)
            min_rs = int(args.get("min_rs") or 0)
            sig_code = str(args.get("signal_code") or "")
            rows = screen_sepa_watchlist(min_trend_score=min_ts, min_rs=min_rs, signal_code=sig_code)
            return _tool_result({
                "filters": {"min_trend_score": min_ts, "min_rs": min_rs, "signal_code": sig_code},
                "matched_count": len(rows),
                "stocks": rows,
            })

        return _tool_result(f"Không tồn tại tool '{name}'.", is_error=True)
    except Exception as e:
        return _tool_result(f"Lỗi thực thi tool '{name}': {e}", is_error=True)


def _handle_single_jsonrpc(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}

    req_id = msg.get("id")
    method = str(msg.get("method") or "")
    params = msg.get("params") or {}

    # JSON-RPC Notifications (no response expected)
    if req_id is None and method.startswith("notifications/"):
        return None
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None if req_id is None else {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "initialize":
        client_ver = str(params.get("protocolVersion") or "2024-11-05")
        proto = client_ver if client_ver in SUPPORTED_PROTOCOLS else "2024-11-05"
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": proto,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS}}

    if method == "tools/call":
        tool_name = str(params.get("name") or "")
        tool_args = params.get("arguments") or {}
        if not tool_name:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Missing tool name"}}
        return {"jsonrpc": "2.0", "id": req_id, "result": execute_mcp_tool(tool_name, tool_args)}

    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": MCP_RESOURCES}}

    if method == "resources/read":
        uri = str(params.get("uri") or "")
        if uri == "sepa://watchlist":
            syms = list_cached_symbols()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "contents": [{
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps({"count": len(syms), "symbols": syms}, ensure_ascii=False, indent=2),
                    }]
                },
            }
        if uri == "sepa://methodology":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "contents": [{"uri": uri, "mimeType": "text/markdown", "text": METHODOLOGY_DOC}]
                },
            }
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32002, "message": f"Resource not found: {uri}"}}

    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": MCP_PROMPTS}}

    if method == "prompts/get":
        p_name = str(params.get("name") or "")
        p_args = params.get("arguments") or {}
        if p_name == "sepa_deep_analysis":
            sym = str(p_args.get("symbol") or "FPT").upper().strip()
            text = (
                f"Hãy dùng các công cụ MCP (`get_stock_overview`, `get_market_flow`, `get_vsa_and_pivot_signals`, "
                f"`get_valuation_and_consensus`, `run_strategy_backtest`) để phân tích toàn diện mã cổ phiếu {sym} "
                f"theo chuẩn Mark Minervini SEPA + Wyckoff VSA + Peter Lynch PEG, đồng thời đề xuất vùng mua, "
                f"điểm cắt lỗ -7% và mục tiêu chốt lời cụ thể."
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "description": f"Phân tích SEPA & VSA toàn diện cho {sym}",
                    "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
                },
            }
        if p_name == "compare_two_stocks":
            sa = str(p_args.get("symbol_a") or "FPT").upper().strip()
            sb = str(p_args.get("symbol_b") or "MWG").upper().strip()
            text = (
                f"Hãy gọi `analyze_stock_sepa_ai` và `get_market_flow` cho cả hai mã {sa} và {sb}, "
                f"sau đó lập bảng so sánh chi tiết về: (1) Xu hướng SEPA & RS Rating, (2) Mua/Bán Chủ Động & Khối Ngoại, "
                f"(3) Định giá thực P/E, PEG & Giá mục tiêu CTCK, (4) Kết quả Backtest 5 năm — và kết luận nên ưu tiên mã nào."
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "description": f"So sánh cổ phiếu {sa} vs {sb}",
                    "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
                },
            }
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Unknown prompt: {p_name}"}}

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def handle_mcp_jsonrpc(payload: Any) -> Any:
    """Dispatch single JSON-RPC 2.0 request or batch array."""
    if isinstance(payload, list):
        responses = []
        for item in payload:
            res = _handle_single_jsonrpc(item)
            if res is not None:
                responses.append(res)
        return responses if responses else None
    return _handle_single_jsonrpc(payload)


def get_mcp_server_metadata(base_url: str = "") -> Dict[str, Any]:
    root = base_url.rstrip("/") if base_url else ""
    endpoint = f"{root}/mcp" if root else "/mcp"
    auth_required = bool(os.environ.get("MCP_API_KEY", "").strip())
    return {
        "name": SERVER_NAME,
        "version": SERVER_VERSION,
        "protocolVersions": SUPPORTED_PROTOCOLS,
        "transport": ["streamable-http", "stdio"],
        "endpoint": endpoint,
        "auth_required": auth_required,
        "tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]} for t in MCP_TOOLS],
        "resources": MCP_RESOURCES,
        "prompts": MCP_PROMPTS,
    }
