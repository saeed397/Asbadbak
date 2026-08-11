"""
دریافت داده: لیست جهانِ کوین‌ها (بر اساس مارکت‌کپ) + کندل‌های OHLCV
نیازمند: pip install ccxt requests pandas --break-system-packages

نسخه‌ی اصلاح‌شده: فیلتر نقدینگی/حجم مطلق (Absolute Volume Filter) اضافه شد
(اولویت ۹ نقشه‌راه بک‌تست) — برای حذف کامل کوین‌های کم‌نقدینگی از یونیورس،
مستقل از رتبه‌ی مارکت‌کپ.
"""

import time
import requests
import pandas as pd
import ccxt

# استیبل‌کوین‌ها و دارایی‌های پیوندی به دلار/طلا (روند/مشتق برایشان بی‌معنی است)
STABLE_BLOCKLIST = {
    "USDT", "USDC", "USDE", "USDS", "USDD", "DAI", "PYUSD", "USDY", "USYC",
    "BUIDL", "PAXG", "XAUT", "RLUSD", "USDG", "BUSD", "TUSD", "FDUSD", "USDP",
    "GUSD", "EURT", "EURS", "LEO", "FIGR_HELOC",
}


def _clean_universe(symbols: list, quote: str) -> list:
    """حذف استیبل‌کوین‌ها و جفت‌های خودارجاع (مثل USDT/USDT) از لیست کوین‌ها"""
    cleaned = []
    for sym in symbols:
        base = sym.split("/")[0].upper()
        if base == quote.upper() or base in STABLE_BLOCKLIST:
            continue
        cleaned.append(sym)
    return cleaned


def _filter_by_volume(coins: list, min_volume: float) -> list:
    """حذف کوین‌هایی که حجم معاملات ۲۴ساعته‌شان (total_volume، به دلار) کمتر از آستانه‌ی مطلق است."""
    if not min_volume:
        return coins
    return [c for c in coins if (c.get("total_volume") or 0) >= min_volume]


def get_top_universe(n: int, quote: str = "USDT", min_volume: float = 0) -> list:
    """
    n کوین برتر بازار را از CoinGecko می‌گیرد و به نمادهای USDT نگاشت می‌کند.
    اگر CoinGecko در دسترس نبود، یک لیست ثابتِ fallback برمی‌گرداند.
    استیبل‌کوین‌ها همیشه از لیست حذف می‌شوند؛ در صورت تعیین min_volume، کوین‌های
    کم‌نقدینگی هم حذف می‌شوند.
    """
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        # کمی بیشتر از n می‌گیریم چون بعد از حذف استیبل‌کوین‌ها/کم‌نقدینگی‌ها ممکن است کم شود
        params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": n + 15, "page": 1}
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        data = _filter_by_volume(data, min_volume)
        symbols = [f"{c['symbol'].upper()}/{quote}" for c in data]
        return _clean_universe(symbols, quote)[:n]
    except Exception:
        fallback = [
            "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TON", "AVAX", "DOT",
            "LINK", "TRX", "MATIC", "SHIB", "LTC", "BCH", "NEAR", "UNI", "ATOM", "ETC",
        ]
        return _clean_universe([f"{s}/{quote}" for s in fallback], quote)[:n]


def get_top_universe_range(start_rank: int, end_rank: int, quote: str = "USDT", min_volume: float = 0) -> list:
    """
    دریافت رمزارزها بر اساس بازه‌ی رتبه‌ی مارکت‌کپ (مثلاً از رتبه‌ی ۵۰ تا ۲۰۰)، تا سقف ۷۰۰.
    این تابع اضافه‌ست و به get_top_universe اصلی هیچ تغییری نمی‌دهد.
    """
    start_rank = max(1, int(start_rank))
    end_rank = max(start_rank, min(int(end_rank), 700))
    buffer = 60  # حاشیه‌ی اضافه برای جبران حذف استیبل‌کوین‌ها/کم‌نقدینگی‌ها از داخل بازه
    fetch_until = min(end_rank + buffer, 700)

    try:
        all_coins = []
        per_page = 250
        page = 1
        while len(all_coins) < fetch_until and page <= 4:
            url = "https://api.coingecko.com/api/v3/coins/markets"
            params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": per_page, "page": page}
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            all_coins.extend(data)
            page += 1
        all_coins = _filter_by_volume(all_coins, min_volume)
        symbols = [f"{c['symbol'].upper()}/{quote}" for c in all_coins]
        cleaned = _clean_universe(symbols, quote)
        return cleaned[start_rank - 1: end_rank]
    except Exception:
        fallback = get_top_universe(end_rank, quote, min_volume)
        return fallback[start_rank - 1: end_rank]


def get_top_universe_tradingview(n: int, quote: str = "USDT") -> list:
    """
    استفاده از کتابخانه‌ی tradingview-screener برای دریافت لیست کوین‌های برتر.
    نکته‌ی مهم: این کتابخانه فقط برای «فیلتر/رتبه‌بندی لحظه‌ای» است، نه دریافت کندل‌های
    تاریخی. کندل‌ها همچنان باید از صرافی (ccxt) گرفته شوند.
    نصب: pip install tradingview-screener --break-system-packages
    """
    try:
        from tradingview_screener import Scanner
        n_rows, df = Scanner.crypto.get_scanner_data()
        cap_col = next((c for c in df.columns if "market_cap" in c.lower()), None)
        if cap_col:
            df = df.sort_values(cap_col, ascending=False)
        name_col = next((c for c in df.columns if c.lower() in ("name", "ticker", "symbol")), df.columns[0])
        names = df[name_col].head(n + 15).tolist()
        symbols = [f"{str(name).upper().split('/')[0].split(':')[-1]}/{quote}" for name in names]
        return _clean_universe(symbols, quote)[:n]
    except Exception:
        return get_top_universe(n, quote)


def get_universe(cfg: dict) -> list:
    """
    بر اساس کانفیگ، منبع مناسب را انتخاب می‌کند و فیلتر حجم مطلق (در صورت تعیین) را اعمال می‌کند.
    اگر UNIVERSE_START و UNIVERSE_END هر دو مشخص شده باشند، از بازه‌ی رتبه‌ای استفاده می‌شود.
    """
    min_volume = cfg.get("MIN_24H_VOLUME_USDT", 0)
    if cfg.get("UNIVERSE_START") is not None and cfg.get("UNIVERSE_END") is not None:
        return get_top_universe_range(cfg["UNIVERSE_START"], cfg["UNIVERSE_END"], cfg["QUOTE_ASSET"], min_volume)
    if cfg.get("UNIVERSE_SOURCE") == "tradingview":
        return get_top_universe_tradingview(cfg["UNIVERSE_SIZE"], cfg["QUOTE_ASSET"])
    return get_top_universe(cfg["UNIVERSE_SIZE"], cfg["QUOTE_ASSET"], min_volume)


def fetch_ohlcv(exchange, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df


def build_exchange(exchange_id: str):
    ex_class = getattr(ccxt, exchange_id)
    return ex_class({"enableRateLimit": True})


def safe_fetch(exchange, symbol, timeframe, limit, retries=2, pause=1.0):
    """دریافت با تحمل خطا (بی‌سروصدا؛ نمادهایی که در صرافی موجود نیستند فقط رد می‌شوند)."""
    for attempt in range(retries + 1):
        try:
            return fetch_ohlcv(exchange, symbol, timeframe, limit)
        except Exception:
            if attempt == retries:
                return None
            time.sleep(pause)
