"""
Self-Hosted AI SEPA / VSA Investment Analyst (Phase 3)
Zero Paid 3rd-Party Dependency:
1. Built-in Mode (Default, Free, Offline, Zero Hallucination):
   Deterministic 5-Pillar SEPA Conviction Engine + Concrete Trade Plan + Structured Vietnamese Memo.
2. Optional Google Gemini Free Tier API (gemini-2.5-flash / gemini-2.0-flash) or Local Ollama LLM,
   strictly grounded on live verified numbers from DuckDB / SSI / Simplize / 5Y Backtester.
"""
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

from engine.backtest import run_backtest
from engine.service import get_full_stock_analysis, get_stock_ohlcv_df, sanitize_obj


def build_ground_truth_brief(symbol: str) -> Optional[Tuple[Dict[str, Any], str]]:
    """Gather 100% verified Ground-Truth technical, flow, valuation & 5Y backtest facts."""
    symbol = symbol.upper().strip()
    analysis = get_full_stock_analysis(symbol, include_chart=False)
    if analysis is None:
        return None

    df_ohlcv = get_stock_ohlcv_df(symbol)
    bt_sepa = run_backtest(symbol, df_ohlcv, strategy='sepa_combo', years=5, stop_loss_pct=7.0, take_profit_pct=20.0, trailing_ma='NONE', max_hold_days=60)
    bt_pp = run_backtest(symbol, df_ohlcv, strategy='pocket_pivot', years=5, stop_loss_pct=7.0, take_profit_pct=20.0, trailing_ma='NONE', max_hold_days=60)

    latest_bar = analysis.get('latest_bar') or {}
    tt = analysis.get('trend_template') or {}
    mf = analysis.get('market_flow') or {}
    val = analysis.get('valuation') or {}
    bc = analysis.get('broker_consensus') or {}
    fa = analysis.get('fundamentals') or {}

    facts = {
        'symbol': symbol,
        'company_name': analysis.get('company_name'),
        'exchange': analysis.get('exchange'),
        'latest_date': latest_bar.get('date'),
        'current_price': analysis.get('current_price'),
        'moving_averages': {
            'ma10': latest_bar.get('ma10'),
            'ma20': latest_bar.get('ma20'),
            'ma50': latest_bar.get('ma50'),
            'ma150': latest_bar.get('ma150'),
            'ma200': latest_bar.get('ma200'),
        },
        'rs_rating': analysis.get('rs_rating'),
        'trend_template': {
            'score': tt.get('score', 0),
            'max_score': tt.get('max_score', 8),
            'status': tt.get('status'),
            'passed': tt.get('passed'),
            'metrics': tt.get('metrics'),
            'criteria': [
                {'title': c.get('title'), 'passed': c.get('passed'), 'detail': c.get('detail')}
                for c in (tt.get('criteria') or [])
            ],
        },
        'recent_signals': (analysis.get('recent_signals') or [])[:6],
        'market_flow': {
            'latest': mf.get('latest') or {},
            'active_10d': mf.get('active_10d') or {},
            'foreign_summary': mf.get('foreign_summary') or {},
        },
        'fundamentals': fa,
        'valuation': {
            'sector': val.get('sector'),
            'pe_trailing': val.get('pe_trailing'),
            'pe_historical_avg': val.get('pe_historical_avg'),
            'pb': val.get('pb'),
            'eps_ttm': val.get('eps_ttm'),
            'book_value': val.get('book_value'),
            'dividend_yield': val.get('dividend_yield'),
            'market_cap_bil': val.get('market_cap_bil'),
            'peg': val.get('peg'),
            'peg_growth_basis': val.get('peg_growth_basis'),
            'peg_assessment': val.get('peg_assessment'),
            'fair_value': val.get('fair_value'),
            'fair_value_diff_pct': val.get('fair_value_diff_pct'),
            'graham_value': val.get('graham_value'),
            'pe_fair_value': val.get('pe_fair_value'),
        },
        'broker_consensus': {
            'has_reports': bc.get('has_reports'),
            'consensus_target': bc.get('consensus_target'),
            'upside_pct': bc.get('upside_pct'),
            'recommendation': bc.get('recommendation'),
            'num_analysts': bc.get('num_analysts'),
            'buy_pct': bc.get('buy_pct'),
            'hold_pct': bc.get('hold_pct'),
            'sell_pct': bc.get('sell_pct'),
            'window_label': bc.get('window_label'),
            'top_reports': (bc.get('reports') or [])[:5],
        },
        'backtest_5y': {
            'sepa_combo': bt_sepa.get('metrics') or {},
            'pocket_pivot': bt_pp.get('metrics') or {},
        },
    }
    facts = sanitize_obj(facts)

    prompt_bundle = (
        f"Bạn là Chuyên gia Phân tích Đầu tư Chứng khoán Việt Nam theo trường phái **Mark Minervini (SEPA)**, "
        f"**Wyckoff VSA**, **Pocket Pivot (Morales & Kacher)** và **Peter Lynch (PEG)**.\n"
        f"QUY TẮC TUYỆT ĐỐI: Chỉ sử dụng đúng các số liệu thực tế trong khối JSON GROUND TRUTH bên dưới cho mã **{symbol}**. "
        f"KHÔNG được bịa thêm số liệu tài chính hay báo cáo ngoài dữ liệu đã cung cấp.\n\n"
        f"Hãy viết bản Nhận Định Đầu Tư (Investment Memo) bằng Tiếng Việt chuẩn Markdown gồm 6 mục súc tích, thực chiến:\n"
        f"1. **Tổng Quan Xu Hướng SEPA & Sức Mạnh Giá (RS Rating)**\n"
        f"2. **Dấu Chân Dòng Tiền Lớn (Mua/Bán Chủ Động, Khối Ngoại & Tín Hiệu VSA / Pocket Pivot)**\n"
        f"3. **Sức Khỏe Cơ Bản (CANSLIM), Định Giá Thực & Đồng Thuận CTCK**\n"
        f"4. **Bằng Chứng Kiểm Định 5 Năm (Backtest Lịch Sử)**\n"
        f"5. **Kịch Bản Hành Động & Quản Trị Rủi Ro (Vùng Mua, Cắt Lỗ -7%, Mục Tiêu Chốt Lời)**\n"
        f"6. **Kết Luận Tóm Tắt (1–2 câu hành động rõ ràng)**\n\n"
        f"--- GROUND TRUTH DATA ({symbol}) ---\n"
        f"```json\n{json.dumps(facts, ensure_ascii=False, indent=2, allow_nan=False)}\n```"
    )
    return facts, prompt_bundle


def _compute_sepa_score_and_plan(facts: Dict[str, Any]) -> Dict[str, Any]:
    price = float(facts.get('current_price') or 0)
    mas = facts.get('moving_averages') or {}
    ma10 = float(mas.get('ma10') or 0)
    ma20 = float(mas.get('ma20') or 0)
    ma50 = float(mas.get('ma50') or 0)
    ma150 = float(mas.get('ma150') or 0)

    tt = facts.get('trend_template') or {}
    tt_score = int(tt.get('score') or 0)
    rs = int(facts.get('rs_rating') or 50)

    # 1. Trend Pillar (max 30)
    rs_bonus = 5 if rs >= 80 else (3 if rs >= 70 else (1 if rs >= 55 else 0))
    p_trend = min(30, round(tt_score / 8.0 * 25.0) + rs_bonus)

    # 2. Signals & Setup Pillar (max 20)
    recent_sigs = facts.get('recent_signals') or []
    latest_date = str(facts.get('latest_date') or '')
    sig_pts_map = {'VCP': 20, 'PP': 18, 'NS': 15, 'SV': 13}
    p_signals = 0
    for s in recent_sigs[:3]:
        code = str(s.get('code') or '')
        if code in sig_pts_map:
            p_signals = max(p_signals, sig_pts_map[code])
    if p_signals == 0:
        if price > ma50 > 0 and ma50 > ma150 > 0:
            p_signals = 12
        elif price > ma50 > 0:
            p_signals = 8
        elif price > ma20 > 0:
            p_signals = 5
        else:
            p_signals = 2

    # 3. Micro-Flow Pillar (max 20)
    mf = facts.get('market_flow') or {}
    lat = mf.get('latest') or {}
    a10 = mf.get('active_10d') or {}
    f_sum = mf.get('foreign_summary') or {}

    bu_1d = lat.get('active_buy_pct')
    bu_10d = a10.get('buy_pct')
    f_1d = float(f_sum.get('net_1d_bil') or 0)
    f_10d = float(f_sum.get('net_10d_bil') or 0)
    streak = int(f_sum.get('consecutive_days') or 0)

    p_flow = 6
    if bu_1d is not None:
        if bu_1d >= 58:
            p_flow += 5
        elif bu_1d >= 50:
            p_flow += 3
        elif bu_1d < 40:
            p_flow -= 2
    if bu_10d is not None:
        if bu_10d >= 55:
            p_flow += 4
        elif bu_10d >= 48:
            p_flow += 2
        elif bu_10d < 42:
            p_flow -= 2
    if f_10d > 10 or streak >= 2:
        p_flow += 5
    elif f_1d > 5:
        p_flow += 3
    elif f_10d < -20 and f_1d < 0:
        p_flow -= 3

    # Wyckoff institutional absorption bonus (Stopping Vol + Foreign net buying)
    has_sv = any(s.get('code') == 'SV' for s in recent_sigs[:2])
    if has_sv and f_1d > 0:
        p_flow += 3
    p_flow = max(0, min(20, p_flow))

    # 4. Valuation & Fundamentals Pillar (max 20)
    val = facts.get('valuation') or {}
    fa = facts.get('fundamentals') or {}
    bc = facts.get('broker_consensus') or {}

    peg = val.get('peg')
    roe = fa.get('roe')
    eps_g = fa.get('eps_growth_yoy')
    up_bc = bc.get('upside_pct')
    up_fv = val.get('fair_value_diff_pct')

    p_val = 2
    if peg is not None:
        if peg < 1.0:
            p_val += 6
        elif peg <= 1.5:
            p_val += 4
        elif peg <= 2.2:
            p_val += 2
    if roe is not None:
        if roe >= 20:
            p_val += 5
        elif roe >= 15:
            p_val += 3
        elif roe >= 10:
            p_val += 1
    if eps_g is not None:
        if eps_g >= 25:
            p_val += 4
        elif eps_g > 0:
            p_val += 2
    best_upside = max(
        float(up_bc) if up_bc is not None else -999.0,
        float(up_fv) if up_fv is not None else -999.0,
    )
    if best_upside >= 15:
        p_val += 5
    elif best_upside > 0:
        p_val += 3
    p_val = max(0, min(20, p_val))

    # 5. Backtest Edge Pillar (max 10)
    bt = facts.get('backtest_5y') or {}
    bt_s = bt.get('sepa_combo') or {}
    bt_p = bt.get('pocket_pivot') or {}
    best_pf = max(float(bt_s.get('profit_factor') or 0), float(bt_p.get('profit_factor') or 0))
    best_alpha = max(float(bt_s.get('alpha_pct') or -999), float(bt_p.get('alpha_pct') or -999))
    best_ret = max(float(bt_s.get('total_return_pct') or -999), float(bt_p.get('total_return_pct') or -999))

    if best_pf >= 1.5 and best_alpha > 0:
        p_bt = 10
    elif best_pf >= 1.1 or best_ret > 15:
        p_bt = 7
    elif best_ret > 0:
        p_bt = 5
    else:
        p_bt = 2

    total_score = int(max(0, min(100, p_trend + p_signals + p_flow + p_val + p_bt)))

    # Action classification
    if total_score >= 75 and tt_score >= 6:
        action = 'MUA MẠNH (ĐẠT CHUẨN SEPA)'
        action_color = 'emerald'
    elif total_score >= 58 or (tt_score >= 5 and any(s.get('code') in ('PP', 'VCP') for s in recent_sigs[:2])):
        action = 'CANH MUA SỚM / GOM NỀN'
        action_color = 'cyan'
    elif total_score >= 42 or has_sv:
        action = 'THEO DÕI CHẶT (CHỜ XÁC NHẬN)'
        action_color = 'amber'
    else:
        action = 'ĐỨNG NGOÀI / PHÒNG THỦ'
        action_color = 'rose'

    # Concrete Trade Plan anchored to current price & MA support
    anchors = [v for v in (ma10, ma20) if v > 0 and price * 0.90 <= v <= price * 1.03]
    low_entry = round(min([price * 0.985] + anchors), -2) if price > 0 else 0
    high_entry = round(price * 1.015, -2) if price > 0 else 0
    stop_loss = round(price * 0.93, -2) if price > 0 else 0
    target_1 = round(price * 1.20, -2) if price > 0 else 0

    cons_tp = bc.get('consensus_target')
    fv_tp = val.get('fair_value')
    if cons_tp and float(cons_tp) > price * 1.12:
        target_2 = round(float(cons_tp), -2)
        t2_note = 'Theo đồng thuận CTCK'
    elif fv_tp and float(fv_tp) > price * 1.15:
        target_2 = round(float(fv_tp), -2)
        t2_note = 'Theo Định giá Fair Value'
    else:
        target_2 = round(price * 1.30, -2)
        t2_note = 'Mục tiêu +30% SEPA'

    risk = max(1.0, price - stop_loss)
    reward = max(0.0, target_1 - price)
    rr_plan = round(reward / risk, 2) if price > 0 else 0.0

    return {
        'score': total_score,
        'pillars': {
            'trend': {'score': p_trend, 'max': 30, 'label': 'Xu hướng SEPA & RS'},
            'signals': {'score': p_signals, 'max': 20, 'label': 'Tín hiệu VCP / PP / VSA'},
            'flow': {'score': p_flow, 'max': 20, 'label': 'Dòng tiền Chủ động & Ngoại'},
            'valuation_fa': {'score': p_val, 'max': 20, 'label': 'Định giá & Cơ bản'},
            'backtest': {'score': p_bt, 'max': 10, 'label': 'Hiệu quả Backtest 5Y'},
        },
        'action': action,
        'action_color': action_color,
        'trade_plan': {
            'current_price': round(price, 0),
            'entry_zone': f"{low_entry:,.0f} - {high_entry:,.0f} đ",
            'stop_loss': stop_loss,
            'stop_loss_pct': -7.0,
            'target_1': target_1,
            'target_1_pct': 20.0,
            'target_2': target_2,
            'target_2_note': t2_note,
            'risk_reward': rr_plan,
        },
        'latest_date': latest_date,
    }


def _fmt_price(v: Any) -> str:
    return f"{float(v):,.0f} đ" if v is not None else "--"


def _fmt_num(v: Any, suffix: str = '', signed: bool = False) -> str:
    if v is None:
        return '--'
    val = float(v)
    prefix = '+' if (signed and val > 0) else ''
    return f"{prefix}{val:g}{suffix}"


def _render_builtin_markdown(facts: Dict[str, Any], ev: Dict[str, Any]) -> str:
    sym = facts['symbol']
    name = facts.get('company_name') or sym
    price = float(facts.get('current_price') or 0)
    mas = facts.get('moving_averages') or {}
    tt = facts.get('trend_template') or {}
    tt_m = tt.get('metrics') or {}
    rs = facts.get('rs_rating')
    mf = facts.get('market_flow') or {}
    lat = mf.get('latest') or {}
    a10 = mf.get('active_10d') or {}
    f_sum = mf.get('foreign_summary') or {}
    sigs = facts.get('recent_signals') or []
    val = facts.get('valuation') or {}
    fa = facts.get('fundamentals') or {}
    bc = facts.get('broker_consensus') or {}
    bt = facts.get('backtest_5y') or {}
    bt_s = bt.get('sepa_combo') or {}
    bt_p = bt.get('pocket_pivot') or {}
    tp = ev['trade_plan']

    # 1. Trend comment
    tt_score = int(tt.get('score') or 0)
    if tt_score >= 7:
        trend_note = f"Cổ phiếu đang ở **Giai đoạn 2 (Uptrend bền vững)** khi đạt **{tt_score}/8 tiêu chí Minervini**."
    elif tt_score >= 4:
        trend_note = f"Cổ phiếu đang trong **pha chuyển tiếp / tích lũy lại** ({tt_score}/8 tiêu chí), giá chưa đồng thuận hoàn toàn với các đường MA dài hạn."
    else:
        trend_note = f"Cổ phiếu **chưa đạt chuẩn xu hướng Stage 2** ({tt_score}/8 tiêu chí), cần thận trọng tránh bắt đáy khi MA50/MA150/MA200 chưa đảo chiều tăng."

    # 2. Signals & Micro-Flow comment
    if sigs:
        sig_lines = "\n".join(
            f"- **{s.get('code')} ({s.get('type')})** ngày `{s.get('time')}` tại {_fmt_price(s.get('price'))}: {s.get('detail')}"
            for s in sigs[:4]
        )
    else:
        sig_lines = "- Chưa xuất hiện tín hiệu VCP / Pocket Pivot / VSA mới trong các phiên gần nhất."

    has_sv = any(s.get('code') == 'SV' for s in sigs[:2])
    bu_1d = lat.get('active_buy_pct')
    bu_10d = a10.get('buy_pct')
    f_1d = f_sum.get('net_1d_bil')
    f_10d = f_sum.get('net_10d_bil')

    absorption_note = ""
    if has_sv and (f_1d or 0) > 0:
        absorption_note = (
            f"\n> **Nhận diện Wyckoff đáng chú ý:** Dù lực bán chủ động 10 phiên chiếm ưu thế "
            f"(Mua CĐ 10D: {_fmt_num(bu_10d, '%')}), nhưng phiên gần nhất xuất hiện nến **Stopping Volume (SV)** "
            f"kèm **Khối ngoại mua ròng +{_fmt_num(f_1d, ' tỷ')}** — dấu hiệu dòng tiền lớn đang chủ động hấp thụ lực cung giá thấp."
        )

    # 3. Valuation comment
    tp_ctck = bc.get('consensus_target')
    if bc.get('has_reports') and tp_ctck:
        cons_line = (
            f"- **Đồng thuận CTCK ({bc.get('num_analysts')} đơn vị · {bc.get('window_label')}):** "
            f"Giá mục tiêu TB **{_fmt_price(tp_ctck)}** (Upside **{_fmt_num(bc.get('upside_pct'), '%', signed=True)}**, "
            f"Khuyến nghị: **{bc.get('recommendation')}** — {bc.get('buy_pct')}% Mua)."
        )
    else:
        cons_line = "- **Đồng thuận CTCK:** Chưa ghi nhận báo cáo mục tiêu giá công khai cho mã này."

    # 4. Conclusion
    score = ev['score']
    if score >= 75:
        verdict = f"**{sym}** hội tụ đầy đủ điều kiện SEPA + dòng tiền xác nhận (**{score}/100 điểm**), phù hợp giải ngân thăm dò/gia tăng tại vùng giá chuẩn và tuân thủ cắt lỗ cứng tại **{_fmt_price(tp['stop_loss'])}**."
    elif score >= 55:
        verdict = f"**{sym}** đạt mức tích cực vừa phải (**{score}/100 điểm**), có thể theo dõi giải ngân từng phần khi giá giữ vững nền hỗ trợ và khối lượng bùng nổ xác nhận."
    else:
        verdict = f"**{sym}** hiện mới đạt **{score}/100 điểm**. Nhà đầu tư nên ưu tiên quan sát quá trình tạo nền/hấp thụ cung (VCP/No Supply) hoặc chờ giá lấy lại trên **MA50 ({_fmt_price(mas.get('ma50'))})** trước khi giải ngân lớn."

    md = f"""### BÁO CÁO PHÂN TÍCH ĐẦU TƯ SEPA & VSA — {sym} ({name})
*Ngày dữ liệu: `{facts.get('latest_date')}` · Sàn `{facts.get('exchange')}` · Điểm tổng hợp: **{score}/100** · Khuyến nghị: **{ev['action']}***

---

#### 1. Xu Hướng Mark Minervini (Trend Template & RS Rating)
- {trend_note}
- **Giá hiện tại:** {_fmt_price(price)} | **RS Rating:** `{rs}/99` | **Đỉnh 52T:** {_fmt_price(tt_m.get('high_52w'))} ({_fmt_num(tt_m.get('diff_from_high_pct'), '%')}) | **Đáy 52T:** {_fmt_price(tt_m.get('low_52w'))} (+{_fmt_num(tt_m.get('diff_from_low_pct'), '%')}).
- **Cấu trúc MA:** `MA10`: {_fmt_price(mas.get('ma10'))} · `MA20`: {_fmt_price(mas.get('ma20'))} · `MA50`: {_fmt_price(mas.get('ma50'))} · `MA150`: {_fmt_price(mas.get('ma150'))} · `MA200`: {_fmt_price(mas.get('ma200'))}.

#### 2. Dấu Chân Dòng Tiền Vi Mô & Tín Hiệu VSA / Pocket Pivot
- **Khớp lệnh chủ động:** Phiên mới nhất Mua CĐ **{_fmt_num(bu_1d, '%')}** ({'SSI Chuẩn' if lat.get('active_is_exact') else 'Ước tính 1m'}) · Trung bình 10 phiên: Mua CĐ **{_fmt_num(bu_10d, '%')}** ({a10.get('trend') or '--'}).
- **Dòng tiền Khối ngoại:** Phiên cuối **{_fmt_num(f_1d, ' tỷ', signed=True)}** · 10 phiên: **{_fmt_num(f_10d, ' tỷ', signed=True)}** · 20 phiên: **{_fmt_num(f_sum.get('net_20d_bil'), ' tỷ', signed=True)}** ({f_sum.get('trend') or '--'}).
{sig_lines}{absorption_note}

#### 3. Cơ Bản Doanh Nghiệp, Định Giá Thực & Đồng Thuận CTCK
- **Tăng trưởng Quý (CANSLIM):** EPS YoY **{_fmt_num(fa.get('eps_growth_yoy'), '%', signed=True)}** · Doanh thu YoY **{_fmt_num(fa.get('rev_growth_yoy'), '%', signed=True)}** · Biên gộp **{_fmt_num(fa.get('gross_margin'), '%')}** · ROE **{_fmt_num(fa.get('roe'), '%')}**.
- **Chỉ số định giá thực ({val.get('sector') or '--'}):** `P/E`: **{_fmt_num(val.get('pe_trailing'))}** (TB ngành `{_fmt_num(val.get('pe_historical_avg'))}`) · `P/B`: **{_fmt_num(val.get('pb'))}** · `EPS TTM`: **{_fmt_price(val.get('eps_ttm'))}** · `PEG`: **{_fmt_num(val.get('peg'))}** ({val.get('peg_assessment')}).
- **Định giá hợp lý (Fair Value Model):** **{_fmt_price(val.get('fair_value'))}** (chênh lệch **{_fmt_num(val.get('fair_value_diff_pct'), '%', signed=True)}** so với thị giá; Graham: {_fmt_price(val.get('graham_value'))}).
{cons_line}

#### 4. Bằng Chứng Kiểm Định Chiến Lược 5 Năm (T+2.5 · Phí 0.35%)
- **SEPA Tổng Hợp (Stage 2 VCP + PP):** `{bt_s.get('total_trades', 0)}` lệnh · Win Rate **{_fmt_num(bt_s.get('win_rate_pct'), '%')}** · Profit Factor **{_fmt_num(bt_s.get('profit_factor'))}** · Tổng LN **{_fmt_num(bt_s.get('total_return_pct'), '%', signed=True)}** vs Buy & Hold **{_fmt_num(bt_s.get('buy_hold_return_pct'), '%', signed=True)}** (**Alpha {_fmt_num(bt_s.get('alpha_pct'), '%', signed=True)}**).
- **Pocket Pivot thuần (Morales & Kacher):** `{bt_p.get('total_trades', 0)}` lệnh · Win Rate **{_fmt_num(bt_p.get('win_rate_pct'), '%')}** · Profit Factor **{_fmt_num(bt_p.get('profit_factor'))}** · Tổng LN **{_fmt_num(bt_p.get('total_return_pct'), '%', signed=True)}** (Max Drawdown **{_fmt_num(bt_p.get('max_drawdown_pct'), '%')}**).

#### 5. Kế Hoạch Giao Dịch & Quản Trị Rủi Ro Minervini
- **Vùng giải ngân tham chiếu:** `{tp['entry_zone']}`
- **Điểm cắt lỗ kỷ luật (-7%):** **{_fmt_price(tp['stop_loss'])}** *(tuyệt đối không bình quân giá xuống nếu gãy mốc này)*.
- **Mục tiêu 1 (Chốt lời từng phần +20%):** **{_fmt_price(tp['target_1'])}** (`R/R = {tp['risk_reward']}x`).
- **Mục tiêu 2 ({tp['target_2_note']}):** **{_fmt_price(tp['target_2'])}**.

#### 6. Kết Luận Hành Động
{verdict}
"""
    return md


def _call_gemini_free(prompt_bundle: str, api_key: str, model: str = "gemini-2.5-flash") -> Tuple[Optional[str], Optional[str]]:
    candidates = [model or "gemini-2.5-flash", "gemini-2.0-flash"]
    seen = []
    for m in candidates:
        if m not in seen:
            seen.append(m)

    last_err = None
    for m in seen:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
            body = {
                "contents": [{"parts": [{"text": prompt_bundle}]}],
                "generationConfig": {"temperature": 0.25, "maxOutputTokens": 2048},
            }
            r = requests.post(url, json=body, timeout=25)
            if r.status_code == 200:
                data = r.json()
                cands = data.get("candidates") or []
                if cands:
                    parts = (cands[0].get("content") or {}).get("parts") or []
                    text = "".join(str(p.get("text") or "") for p in parts).strip()
                    if text:
                        return text, None
                last_err = "Gemini trả về phản hồi rỗng."
            elif r.status_code == 404:
                last_err = f"Model {m} không khả dụng (404)."
                continue
            else:
                last_err = f"Gemini HTTP {r.status_code}"
                break
        except Exception as e:
            last_err = f"Lỗi kết nối Gemini: {e}"
            break
    return None, last_err


def _call_local_ollama(prompt_bundle: str, ollama_url: str = "http://127.0.0.1:11434", model: str = "qwen2.5:7b") -> Tuple[Optional[str], Optional[str]]:
    base = (ollama_url or "http://127.0.0.1:11434").rstrip("/")
    target_model = model or "qwen2.5:7b"
    try:
        r = requests.post(
            f"{base}/api/chat",
            json={
                "model": target_model,
                "messages": [{"role": "user", "content": prompt_bundle}],
                "stream": False,
            },
            timeout=45,
        )
        if r.status_code == 200:
            msg = (r.json().get("message") or {}).get("content") or ""
            if msg.strip():
                return msg.strip(), None
            return None, "Ollama trả về phản hồi rỗng."
        return None, f"Ollama HTTP {r.status_code}"
    except Exception as e:
        return None, f"Không kết nối được Ollama tại {base}: {e}"


def analyze_stock_ai(
    symbol: str,
    mode: str = "builtin",
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    ollama_url: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Produce AI SEPA/VSA Investment Memo using Built-in Engine (default),
    Google Gemini Free Tier, or Local Ollama LLM — strictly grounded on verified numbers.
    """
    brief = build_ground_truth_brief(symbol)
    if brief is None:
        return None

    facts, prompt_bundle = brief
    ev = _compute_sepa_score_and_plan(facts)
    builtin_md = _render_builtin_markdown(facts, ev)

    mode_req = str(mode or "builtin").lower().strip()
    if mode_req not in ("builtin", "gemini", "ollama"):
        mode_req = "builtin"

    mode_used = "builtin"
    engine_label = "Bộ não SEPA Nội bộ (Miễn phí · Zero-Hallucination)"
    report_md = builtin_md
    fallback_note = None

    if mode_req == "gemini":
        effective_key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
        if not effective_key:
            fallback_note = (
                "Chưa nhập Gemini API Key (miễn phí tại aistudio.google.com). "
                "Hệ thống tự động sử dụng Bộ não SEPA Nội bộ."
            )
        else:
            llm_text, err = _call_gemini_free(prompt_bundle, effective_key, model=model or "gemini-2.5-flash")
            if llm_text:
                mode_used = "gemini"
                engine_label = f"Google Gemini ({model or 'gemini-2.5-flash'}) · Ground-Truth SEPA"
                report_md = llm_text
            else:
                fallback_note = f"{err} — Đã tự động chuyển về Bộ não SEPA Nội bộ."

    elif mode_req == "ollama":
        target_model = model or os.environ.get("OLLAMA_MODEL") or "qwen2.5:7b"
        target_url = ollama_url or os.environ.get("OLLAMA_URL") or "http://127.0.0.1:11434"
        llm_text, err = _call_local_ollama(prompt_bundle, ollama_url=target_url, model=target_model)
        if llm_text:
            mode_used = "ollama"
            engine_label = f"Local Ollama ({target_model}) · Ground-Truth SEPA"
            report_md = llm_text
        else:
            fallback_note = f"{err} — Đã tự động chuyển về Bộ não SEPA Nội bộ."

    return sanitize_obj({
        'symbol': facts['symbol'],
        'company_name': facts.get('company_name'),
        'exchange': facts.get('exchange'),
        'latest_date': facts.get('latest_date'),
        'mode_requested': mode_req,
        'mode_used': mode_used,
        'engine_label': engine_label,
        'score': ev['score'],
        'pillars': ev['pillars'],
        'action': ev['action'],
        'action_color': ev['action_color'],
        'trade_plan': ev['trade_plan'],
        'report_markdown': report_md,
        'prompt_bundle': prompt_bundle,
        'fallback_note': fallback_note,
    })
