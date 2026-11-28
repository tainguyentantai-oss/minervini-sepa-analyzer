"""
Dynamic Valuation and Broker Consensus Module for Vietnam Equities
1. Crawls live Broker Analyst Reports & Target Prices from Simplize (fallback CafeF)
2. Fetches live Valuation Ratios (P/E, P/B, EPS TTM, BVPS, EV/EBITDA, Market Cap, Dividend Yield)
3. Computes Peter Lynch PEG, Benjamin Graham Intrinsic Value, and Sector P/E Fair Value
"""
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import math
import re
import requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*'
}
SIMPLIZE_HEADERS = {**HEADERS, 'Referer': 'https://simplize.vn/'}
CAFEF_HEADERS = {**HEADERS, 'Referer': 'https://cafef.vn/'}

SECTOR_PE_BENCHMARK = {
    'Công nghệ': 18.0,
    'Tài chính': 10.5,
    'Ngân hàng': 9.5,
    'Nguyên vật liệu': 12.0,
    'Công nghiệp': 14.0,
    'Hàng tiêu dùng thiết yếu': 16.0,
    'Hàng hóa không thiết yếu': 15.0,
    'Bất động sản': 15.0,
    'Năng lượng': 13.0,
    'Y tế': 16.5,
    'Tiện ích': 13.5,
    'Viễn thông': 15.0,
}


def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == '':
        return None
    try:
        val = float(v)
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    except Exception:
        return None


def _parse_ddmmyyyy_to_iso(s: Any) -> Optional[str]:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), '%d/%m/%Y').strftime('%Y-%m-%d')
    except Exception:
        return None


def _iso_to_ddmmyy(s: Any) -> str:
    if not s or not isinstance(s, str):
        return '--'
    try:
        return datetime.strptime(s.strip()[:10], '%Y-%m-%d').strftime('%d/%m/%y')
    except Exception:
        return str(s)


def _parse_cafef_date(s: Any) -> Optional[str]:
    if not s or not isinstance(s, str):
        return None
    m = re.search(r'/Date\((\d+)\)/', s)
    if not m:
        return None
    try:
        ts_ms = int(m.group(1))
        return datetime.utcfromtimestamp(ts_ms / 1000.0).strftime('%Y-%m-%d')
    except Exception:
        return None


def is_cache_fresh(updated_at: Optional[str], max_hours: int = 24) -> bool:
    if not updated_at:
        return False
    try:
        dt = datetime.strptime(str(updated_at).strip()[:19], '%Y-%m-%d %H:%M:%S')
        return (datetime.now() - dt) < timedelta(hours=max_hours)
    except Exception:
        return False


def _classify_action(action: Optional[str], upside: Optional[float] = None) -> Optional[str]:
    act = str(action or '').upper().strip()
    buy_kw = ('MUA', 'KHẢ QUAN', 'OUTPERFORM', 'TĂNG TỶ TRỌNG', 'TÍCH LŨY', 'BUY', 'ADD', 'OVERWEIGHT')
    sell_kw = ('BÁN', 'KÉM KHẢ QUAN', 'GIẢM TỶ TRỌNG', 'SELL', 'UNDERPERFORM', 'REDUCE', 'UNDERWEIGHT')
    hold_kw = ('TRUNG LẬP', 'NẮM GIỮ', 'PHÙ HỢP', 'HOLD', 'NEUTRAL', 'MARKET PERFORM', 'THEO DÕI')

    if any(k in act for k in sell_kw):
        return 'SELL'
    if any(k in act for k in buy_kw):
        return 'BUY'
    if any(k in act for k in hold_kw):
        return 'HOLD'
    if upside is not None:
        if upside >= 15.0:
            return 'BUY'
        if upside <= -5.0:
            return 'SELL'
        return 'HOLD'
    return None


def _extract_target_from_text(text: str) -> Optional[float]:
    if not text:
        return None
    patterns = [
        r'(?:giá mục tiêu|mục tiêu|target price|TP)[^0-9]{0,25}([0-9]{2,3}[.,][0-9]{3})',
        r'(?:giá mục tiêu|mục tiêu|TP)[^0-9]{0,15}([0-9]{5,6})\b',
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            raw = m.group(1).replace('.', '').replace(',', '')
            val = _safe_float(raw)
            if val and val >= 1000:
                return val
    return None


def _extract_action_from_text(text: str) -> str:
    up = (text or '').upper()
    if any(k in up for k in ('MUA MẠNH', 'STRONG BUY')):
        return 'MUA MẠNH'
    if any(k in up for k in ('KÉM KHẢ QUAN', 'BÁN', 'GIẢM TỶ TRỌNG', 'UNDERPERFORM', 'SELL')):
        return 'BÁN'
    if any(k in up for k in ('OUTPERFORM', 'KHẢ QUAN')):
        return 'KHẢ QUAN'
    if any(k in up for k in ('TĂNG TỶ TRỌNG', 'OVERWEIGHT')):
        return 'TĂNG TỶ TRỌNG'
    if any(k in up for k in ('MUA', 'BUY')):
        return 'MUA'
    if any(k in up for k in ('TRUNG LẬP', 'NẮM GIỮ', 'NEUTRAL', 'HOLD')):
        return 'TRUNG LẬP'
    return 'CẬP NHẬT'


def fetch_broker_reports_live(symbol: str) -> List[Dict[str, Any]]:
    """
    Crawl live broker analyst reports & target prices for a stock symbol.
    Primary: Simplize analysis-report API
    Fallback: CafeF BaoCaoPhanTich API
    """
    symbol = symbol.upper().strip()
    reports: List[Dict[str, Any]] = []

    # 1. Primary: Simplize
    try:
        url = f"https://api.simplize.vn/api/company/analysis-report/list?ticker={symbol}&size=25&page=0"
        r = requests.get(url, headers=SIMPLIZE_HEADERS, timeout=6)
        if r.status_code == 200:
            items = r.json().get('data') or []
            for it in items:
                rid = it.get('id')
                iso_date = _parse_ddmmyyyy_to_iso(it.get('issueDate')) or ''
                tp = _safe_float(it.get('targetPrice'))
                raw_rec = str(it.get('recommend') or '').strip().upper()
                action = 'CẬP NHẬT' if raw_rec in ('', 'KHÁC', 'NONE', 'NULL') else raw_rec
                broker = str(it.get('source') or 'CTCK').strip()
                title = str(it.get('title') or '').strip()
                if (tp is None or tp <= 0) and title:
                    tp = _extract_target_from_text(title)
                pdf_url = str(it.get('attachedLink') or '').strip()
                reports.append({
                    'report_id': f"simp_{rid}" if rid else f"simp_{broker}_{iso_date}",
                    'broker': broker,
                    'issue_date': iso_date,
                    'action': action,
                    'target_price': tp,
                    'title': title,
                    'pdf_url': pdf_url,
                })
    except Exception as e:
        print(f"[Valuation] Simplize reports error for {symbol}: {e}")

    # 2. Fallback: CafeF BaoCaoPhanTich
    if not reports:
        try:
            url = f"https://cafef.vn/du-lieu/Ajax/PageNew/BaoCaoPhanTich.ashx?Symbol={symbol}&PageIndex=1&PageSize=15"
            r = requests.get(url, headers=CAFEF_HEADERS, timeout=6)
            if r.status_code == 200:
                items = r.json().get('Data') or []
                for it in items:
                    rid = it.get('ID') or ''
                    iso_date = _parse_cafef_date(it.get('DateDeploy')) or ''
                    broker = str(it.get('ResourceCode') or it.get('ResourceName') or 'CTCK').strip()
                    title = str(it.get('Title') or '').strip()
                    body = str(it.get('Body') or '').strip()
                    tp = _extract_target_from_text(f"{title} {body}")
                    action = _extract_action_from_text(f"{title} {body}")
                    link_detail = str(it.get('LinkDetail') or '').strip()
                    pdf_url = f"https://cafef.vn{link_detail}" if link_detail.startswith('/') else link_detail
                    reports.append({
                        'report_id': f"cafef_{rid}" if rid else f"cafef_{broker}_{iso_date}",
                        'broker': broker,
                        'issue_date': iso_date,
                        'action': action,
                        'target_price': tp,
                        'title': title,
                        'pdf_url': pdf_url,
                    })
        except Exception as e:
            print(f"[Valuation] CafeF reports error for {symbol}: {e}")

    reports.sort(key=lambda x: x.get('issue_date') or '', reverse=True)
    return reports


def fetch_company_valuation_live(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetch real live company valuation & growth ratios from Simplize summary API.
    """
    symbol = symbol.upper().strip()
    try:
        url = f"https://api.simplize.vn/api/company/summary/{symbol}"
        r = requests.get(url, headers=SIMPLIZE_HEADERS, timeout=6)
        if r.status_code != 200:
            return None
        d = r.json().get('data') or {}
        if not d:
            return None

        return {
            'sector': str(d.get('bcEconomicSectorName') or '').strip() or None,
            'industry': str(d.get('industryActivity') or '').strip() or None,
            'pe_ratio': _safe_float(d.get('peRatio')),
            'pb_ratio': _safe_float(d.get('pbRatio')),
            'eps_ttm': _safe_float(d.get('epsRatio')),
            'book_value': _safe_float(d.get('bookValue')),
            'ev_ebitda': _safe_float(d.get('evEbitdaRatio')),
            'market_cap': _safe_float(d.get('marketCap')),
            'dividend_yield': _safe_float(d.get('dividendYieldCurrent')),
            'beta_5y': _safe_float(d.get('beta5y')),
            'roe': _safe_float(d.get('roe')),
            'roa': _safe_float(d.get('roa')),
            'ni_5y_growth': _safe_float(d.get('netIncome5yGrowth')),
            'rev_5y_growth': _safe_float(d.get('revenue5yGrowth')),
        }
    except Exception as e:
        print(f"[Valuation] Simplize summary error for {symbol}: {e}")
        return None


def get_broker_consensus(
    symbol: str,
    current_price: float,
    raw_reports: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Aggregate real brokerage consensus target price, range, Buy/Hold/Sell % breakdown,
    and deduplicated reports per brokerage firm. Never fabricates fake targets.
    """
    symbol = symbol.upper().strip()
    if raw_reports is None:
        raw_reports = fetch_broker_reports_live(symbol)

    raw_sorted = sorted(raw_reports or [], key=lambda x: x.get('issue_date') or '', reverse=True)

    # Filter valid target prices (sanity guard against unadjusted pre-split historical prices)
    valid_tp_reports = []
    for r in raw_sorted:
        tp = _safe_float(r.get('target_price'))
        if tp is not None and tp > 0:
            if current_price <= 0 or (0.2 * current_price <= tp <= 5.0 * current_price):
                valid_tp_reports.append({**r, 'target_price': tp})

    now = datetime.now()
    cutoff_12m = (now - timedelta(days=365)).strftime('%Y-%m-%d')
    cutoff_24m = (now - timedelta(days=730)).strftime('%Y-%m-%d')

    window_label = ''
    active_reports = [r for r in valid_tp_reports if (r.get('issue_date') or '') >= cutoff_12m]
    if active_reports:
        window_label = '12 tháng gần nhất'
    else:
        active_reports = [r for r in valid_tp_reports if (r.get('issue_date') or '') >= cutoff_24m]
        if active_reports:
            window_label = '24 tháng gần nhất'
        elif valid_tp_reports:
            active_reports = valid_tp_reports[:5]
            window_label = 'Lịch sử gần nhất'

    # Deduplicate by broker (keep newest report per securities firm)
    unique_by_broker: Dict[str, Dict[str, Any]] = {}
    for r in active_reports:
        b_key = str(r.get('broker') or 'CTCK').upper().strip()
        if b_key not in unique_by_broker:
            unique_by_broker[b_key] = r
    unique_reports = list(unique_by_broker.values())

    # Format up to 12 recent reports for table display (prioritizing reports with target price)
    tp_first = [r for r in raw_sorted if _safe_float(r.get('target_price')) and (current_price <= 0 or 0.2 * current_price <= _safe_float(r.get('target_price')) <= 5.0 * current_price)]
    other_reps = [r for r in raw_sorted if r not in tp_first]
    display_src = (tp_first[:10] + other_reps[:4])[:12]
    display_src.sort(key=lambda x: x.get('issue_date') or '', reverse=True)

    display_reports: List[Dict[str, Any]] = []
    for r in display_src:
        tp = _safe_float(r.get('target_price'))
        valid_tp = tp if (tp and tp > 0 and (current_price <= 0 or 0.2 * current_price <= tp <= 5.0 * current_price)) else None
        upside = round(((valid_tp - current_price) / current_price * 100.0), 1) if (valid_tp and current_price > 0) else None
        raw_act = str(r.get('action') or '').strip().upper()
        action_disp = 'CẬP NHẬT' if raw_act in ('', 'KHÁC', 'NONE', 'NULL') else raw_act
        display_reports.append({
            'broker': r.get('broker') or 'CTCK',
            'action': action_disp,
            'target_price': valid_tp,
            'date': _iso_to_ddmmyy(r.get('issue_date')),
            'iso_date': r.get('issue_date') or '',
            'upside': upside,
            'title': r.get('title') or '',
            'pdf_url': r.get('pdf_url') or '',
        })

    if not unique_reports:
        return {
            'symbol': symbol,
            'has_reports': False,
            'consensus_target': None,
            'target_high': None,
            'target_low': None,
            'upside_pct': None,
            'recommendation': 'CHƯA CÓ BÁO CÁO',
            'buy_pct': 0,
            'hold_pct': 0,
            'sell_pct': 0,
            'num_analysts': 0,
            'window_label': '',
            'source': 'Simplize / CafeF CTCK',
            'reports': display_reports,
        }

    tps = [float(r['target_price']) for r in unique_reports]
    consensus_target = round(sum(tps) / len(tps), -2)
    target_high = round(max(tps), -2)
    target_low = round(min(tps), -2)
    upside_pct = round(((consensus_target - current_price) / current_price * 100.0), 1) if current_price > 0 else 0.0

    buy_cnt = 0
    hold_cnt = 0
    sell_cnt = 0
    for r in unique_reports:
        rep_tp = float(r['target_price'])
        rep_up = ((rep_tp - current_price) / current_price * 100.0) if current_price > 0 else None
        bucket = _classify_action(r.get('action'), rep_up)
        if bucket == 'BUY':
            buy_cnt += 1
        elif bucket == 'SELL':
            sell_cnt += 1
        else:
            hold_cnt += 1

    total_b = max(1, buy_cnt + hold_cnt + sell_cnt)
    buy_pct = int(round(buy_cnt / total_b * 100))
    sell_pct = int(round(sell_cnt / total_b * 100))
    hold_pct = max(0, 100 - buy_pct - sell_pct)

    if buy_pct >= 75 and upside_pct >= 15.0:
        recommendation = 'MUA MẠNH'
    elif buy_pct >= 60:
        recommendation = 'MUA'
    elif buy_pct >= 45:
        recommendation = 'KHẢ QUAN'
    elif sell_pct < 40:
        recommendation = 'NẮM GIỮ'
    else:
        recommendation = 'BÁN'

    return {
        'symbol': symbol,
        'has_reports': True,
        'consensus_target': consensus_target,
        'target_high': target_high,
        'target_low': target_low,
        'upside_pct': upside_pct,
        'recommendation': recommendation,
        'buy_pct': buy_pct,
        'hold_pct': hold_pct,
        'sell_pct': sell_pct,
        'num_analysts': len(unique_reports),
        'window_label': window_label,
        'source': 'Simplize / CafeF CTCK',
        'reports': display_reports,
    }


def calculate_valuation_metrics(
    symbol: str,
    current_price: float,
    fundamentals: Dict[str, Any],
    live_val: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Calculate real live valuation indicators:
    - Real P/E Trailing, P/B, EPS TTM, Book Value, EV/EBITDA, Market Cap, Dividend Yield
    - Peter Lynch PEG Ratio (grounded in 5Y Net Income CAGR or EPS YoY)
    - Intrinsic Fair Value (Sector P/E Fair Value & Benjamin Graham Value)
    """
    lv = live_val or {}
    sector = lv.get('sector') or 'Thị trường'
    industry = lv.get('industry') or ''
    pe_hist = SECTOR_PE_BENCHMARK.get(sector, 13.5)

    pe_raw = _safe_float(lv.get('pe_ratio'))
    pb_raw = _safe_float(lv.get('pb_ratio'))
    eps_ttm = _safe_float(lv.get('eps_ttm'))
    book_value = _safe_float(lv.get('book_value'))
    ev_ebitda = _safe_float(lv.get('ev_ebitda'))
    market_cap = _safe_float(lv.get('market_cap'))
    div_yield = _safe_float(lv.get('dividend_yield'))
    ni_5y = _safe_float(lv.get('ni_5y_growth'))
    eps_yoy = _safe_float((fundamentals or {}).get('eps_growth_yoy'))

    pe_trailing = round(pe_raw, 2) if pe_raw is not None else None
    pb = round(pb_raw, 2) if pb_raw is not None else None
    market_cap_bil = round(market_cap / 1e9, 0) if market_cap is not None else None

    # Peter Lynch PEG growth basis: prefer positive 5Y Net Income CAGR, fallback positive EPS YoY
    growth_for_peg: Optional[float] = None
    peg_growth_basis = '--'
    if ni_5y is not None and ni_5y > 0:
        growth_for_peg = ni_5y
        peg_growth_basis = f"LN 5Y (+{ni_5y:.1f}%)"
    elif eps_yoy is not None and eps_yoy > 0:
        growth_for_peg = eps_yoy
        peg_growth_basis = f"EPS YoY (+{eps_yoy:.1f}%)"

    if pe_trailing is not None and pe_trailing > 0 and growth_for_peg is not None:
        peg = round(pe_trailing / max(3.0, growth_for_peg), 2)
        if peg < 1.0:
            peg_assessment = "Hấp dẫn (< 1.0)"
            peg_color = "text-emerald-400"
        elif peg <= 1.5:
            peg_assessment = "Hợp lý (1.0 - 1.5)"
            peg_color = "text-sky-400"
        elif peg <= 2.5:
            peg_assessment = "Hơi cao (1.5 - 2.5)"
            peg_color = "text-amber-400"
        else:
            peg_assessment = "Định giá cao (> 2.5)"
            peg_color = "text-rose-400"
    else:
        peg = None
        peg_assessment = "N/A (LN / Tăng trưởng âm)"
        peg_color = "text-slate-400"

    # Intrinsic / Fair Value Models
    pe_fair_value = round(eps_ttm * pe_hist, -2) if (eps_ttm is not None and eps_ttm > 0) else None
    graham_value = (
        round(math.sqrt(22.5 * eps_ttm * book_value), -2)
        if (eps_ttm is not None and eps_ttm > 0 and book_value is not None and book_value > 0)
        else None
    )
    valid_fvs = [v for v in (pe_fair_value, graham_value) if v is not None and v > 0]
    fair_value = round(sum(valid_fvs) / len(valid_fvs), -2) if valid_fvs else None
    fair_value_diff_pct = (
        round(((fair_value - current_price) / current_price * 100.0), 1)
        if (fair_value is not None and current_price > 0)
        else None
    )

    return {
        'pe_trailing': pe_trailing,
        'pe_historical_avg': pe_hist,
        'pb': pb,
        'eps_ttm': round(eps_ttm, 0) if eps_ttm is not None else None,
        'book_value': round(book_value, 0) if book_value is not None else None,
        'ev_ebitda': round(ev_ebitda, 2) if ev_ebitda is not None else None,
        'market_cap_bil': market_cap_bil,
        'dividend_yield': round(div_yield, 2) if div_yield is not None else None,
        'sector': sector,
        'industry': industry,
        'peg': peg,
        'peg_growth_basis': peg_growth_basis,
        'peg_assessment': peg_assessment,
        'peg_color': peg_color,
        'graham_value': graham_value,
        'pe_fair_value': pe_fair_value,
        'fair_value': fair_value,
        'fair_value_diff_pct': fair_value_diff_pct,
        'is_live': bool(live_val),
    }
