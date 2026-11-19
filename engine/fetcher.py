"""
Data fetcher for Vietnamese Stock Market
Fetches EOD OHLCV price data and quarterly financial statements
"""
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import requests
import pandas as pd

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*'
}

def fetch_ohlcv(symbol: str, days: int = 500) -> pd.DataFrame:
    """
    Fetch historical daily OHLCV for a stock symbol.
    Uses Entrade / DNSE public chart API with fallback to VNDirect.
    Returns DataFrame with columns: date, open, high, low, close, volume
    """
    symbol = symbol.upper().strip()
    now = int(time.time())
    from_time = now - int(days * 86400 * 1.5)  # Add buffer for weekends & holidays

    # Method 1: Entrade / DNSE chart API
    try:
        url = f"https://services.entrade.com.vn/chart-api/v2/ohlcs/stock?from={from_time}&to={now}&symbol={symbol}&resolution=1D"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if 't' in data and len(data['t']) > 0:
                df = pd.DataFrame({
                    'time': data['t'],
                    'open': data['o'],
                    'high': data['h'],
                    'low': data['l'],
                    'close': data['c'],
                    'volume': data['v']
                })
                df['date'] = pd.to_datetime(df['time'], unit='s').dt.strftime('%Y-%m-%d')
                df = df.sort_values('time').drop_duplicates('date').reset_index(drop=True)
                # If price is in thousands (e.g. 45.7 instead of 45700), normalize to full VND
                scale = 1000.0 if df['close'].iloc[-1] < 1000 else 1.0
                for col in ['open', 'high', 'low', 'close']:
                    df[col] = df[col] * scale

                return df[['date', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        print(f"[Fetcher] Entrade API error for {symbol}: {e}")

    # Method 2: Fallback to VNDirect DChart API
    try:
        url = f"https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol={symbol}&from={from_time}&to={now}"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get('s') == 'ok' and 't' in data:
                # Note: VNDirect prices might be in thousands (e.g. 98.5 instead of 98500), check scale
                prices_scale = 1000 if data['c'][-1] < 1000 else 1
                df = pd.DataFrame({
                    'time': data['t'],
                    'open': [x * prices_scale for x in data['o']],
                    'high': [x * prices_scale for x in data['h']],
                    'low': [x * prices_scale for x in data['l']],
                    'close': [x * prices_scale for x in data['c']],
                    'volume': data['v']
                })
                df['date'] = pd.to_datetime(df['time'], unit='s').dt.strftime('%Y-%m-%d')
                df = df.sort_values('time').drop_duplicates('date').reset_index(drop=True)
                return df[['date', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        print(f"[Fetcher] VNDirect API error for {symbol}: {e}")

    return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume'])


def fetch_financial_ratios(symbol: str) -> Dict[str, Any]:
    """
    Fetch quarterly financial reports and key indicators:
    - EPS Growth YoY (%)
    - Revenue Growth YoY (%)
    - Gross Profit Margin (%)
    - ROE (%)
    """
    symbol = symbol.upper().strip()
    result = {
        'symbol': symbol,
        'quarter': 'Gần nhất',
        'eps_growth_yoy': None,
        'rev_growth_yoy': None,
        'gross_margin': None,
        'roe': None,
        'source': 'Simplize & BCTC'
    }

    try:
        url = f"https://api.simplize.vn/api/company/fi/ratio/{symbol.lower()}?period=Q&size=4"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Referer': 'https://simplize.vn/'
        }
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            items = data.get('data', {}).get('items', [])
            if items:
                latest = items[0]
                result['quarter'] = latest.get('periodDateName', 'Gần nhất')
                
                # Revenue growth YoY: isg1
                rev_g = latest.get('isg1')
                if rev_g is not None:
                    result['rev_growth_yoy'] = round(float(rev_g), 1)
                
                # Net income / EPS growth YoY: isg3
                eps_g = latest.get('isg3')
                if eps_g is not None:
                    result['eps_growth_yoy'] = round(float(eps_g), 1)

                # Gross margin: op1
                gm = latest.get('op1')
                if gm is not None:
                    result['gross_margin'] = round(float(gm), 1)

                # ROE: op17
                roe = latest.get('op17') or latest.get('op11')
                if roe is not None:
                    result['roe'] = round(float(roe), 1)

    except Exception as e:
        print(f"[Fetcher] Error fetching financial ratios for {symbol}: {e}")

    return result


def get_company_name(symbol: str) -> str:
    """Return common Vietnamese company name for known tickers or fallback"""
    symbol = symbol.upper().strip()
    COMPANY_NAMES = {
        'FPT': 'Công ty Cổ phần FPT',
        'VNM': 'Công ty Cổ phần Sữa Việt Nam (Vinamilk)',
        'HPG': 'Công ty Cổ phần Tập đoàn Hòa Phát',
        'MWG': 'Công ty Cổ phần Đầu tư Thế Giới Di Động',
        'SSI': 'Công ty Cổ phần Chứng khoán SSI',
        'VCI': 'Công ty Cổ phần Chứng khoán Vietcap',
        'TCB': 'Ngân hàng TMCP Kỹ thương Việt Nam (Techcombank)',
        'MBB': 'Ngân hàng TMCP Quân đội (MBBank)',
        'ACB': 'Ngân hàng TMCP Á Châu',
        'VCB': 'Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank)',
        'CTG': 'Ngân hàng TMCP Công thương Việt Nam (VietinBank)',
        'DGC': 'Công ty Cổ phần Tập đoàn Hóa chất Đức Giang',
        'FRT': 'Công ty Cổ phần Bán lẻ Kỹ thuật số FPT',
        'PNJ': 'Công ty Cổ phần Vàng bạc Đá quý Phú Nhuận',
        'CTR': 'Tổng Công ty Cổ phần Công trình Viettel',
        'VTP': 'Tổng Công ty Cổ phần Bưu chính Viettel',
        'GAS': 'Tổng Công ty Khí Việt Nam (PV GAS)',
        'PVD': 'Tổng Công ty Cổ phần Khoan và Dịch vụ Khoan Dầu khí',
        'PVS': 'Tổng Công ty Cổ phần Dịch vụ Kỹ thuật Dầu khí Việt Nam',
        'KDH': 'Công ty Cổ phần Đầu tư và Kinh doanh Nhà Khang Điền',
        'NLG': 'Công ty Cổ phần Đầu tư Nam Long',
        'VHM': 'Công ty Cổ phần Vinhomes',
        'VIC': 'Tập đoàn Vingroup'
    }
    return COMPANY_NAMES.get(symbol, f"Công ty Cổ phần {symbol}")
