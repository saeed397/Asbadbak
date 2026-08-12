"""
تنظیمات اصلی استراتژی — همه‌ی پارامترهای قابل تغییر اینجا هستند
تا حجم اجرا (تعداد کوین × تعداد تایم‌فریم × بازه‌های محاسباتی) قابل کنترل باشد.
"""

CONFIG = {
    # ---------- جهان قابل بررسی (Universe) ----------
    "UNIVERSE_SIZE": 50,          # تعداد کوین برتر بر اساس مارکت‌کپ (قابل تغییر: 20 / 50 / 100 / 300)
    "QUOTE_ASSET": "USDT",
    "EXCHANGE_ID": "mexc",         # از طریق ccxt — به‌جای Binance (فیلتر/تحریم ایران)؛ MEXC معمولاً برای کاربران ایرانی
                                   # کمترین مشکل دسترسی رو داره. اگر کار نکرد، گزینه‌ی جایگزین: "kucoin"

    # ---------- تایم‌فریم ----------
    # به‌جای تحلیل هم‌زمان 5 تایم‌فریم (Monthly..1H) که حجم محاسبات را انفجاری می‌کند،
    # فقط یک تایم‌فریم اصلی + یک تایم‌فریم تأیید (بالادست) استفاده می‌شود.
    "MAIN_TIMEFRAME": "4h",        # قابل تغییر: '30m', '1h', '4h', '1d', '1w'
    "CONFIRM_TIMEFRAME": "auto",   # "auto" = خودش بر اساس سلسله‌مراتب TF_HIERARCHY تایم‌فریم بالاتر را انتخاب می‌کند
    "CANDLE_LIMIT": 500,           # تعداد کندل مورد نیاز برای محاسبات (پوشش بزرگ‌ترین بازه + حاشیه)

    # ---------- بازه‌های محاسباتی مشتق/انتگرال (ایده اصلی کاربر) ----------
    # به‌جای 10 بازه (3..233)، فقط 3 بازه فیبوناچی نماینده: کوتاه/میان/بلندمدت
    "SCALES": [8, 21, 55],

    # ---------- EMAهای روند ----------
    "EMA_PERIODS": [21, 50, 100, 200],

    # ---------- وزن موتورها بر اساس رژیم بازار ----------
    # رژیم Trending: وزن بیشتر به Trend/Derivative/Energy
    # رژیم Ranging/Noisy: وزن بیشتر به Structure/Regime (احتیاط بیشتر) و کاهش وزن ورود
    "ENGINE_WEIGHTS": {
        "trending": {
            "trend": 0.25, "derivative": 0.20, "integral": 0.15,
            "energy": 0.20, "structure": 0.15, "regime": 0.05,
        },
        "ranging": {
            "trend": 0.10, "derivative": 0.10, "integral": 0.10,
            "energy": 0.15, "structure": 0.35, "regime": 0.20,
        },
        "volatile": {
            "trend": 0.10, "derivative": 0.10, "integral": 0.10,
            "energy": 0.15, "structure": 0.25, "regime": 0.30,
        },
    },

    # ---------- آستانه‌های تصمیم‌گیری ----------
    "CONFIDENCE_MIN": 0.55,     # حداقل اعتماد برای صدور هر سیگنالی غیر از No Trade
    "CONSENSUS_MIN": 0.55,      # حداقل هم‌راستایی موتورها
    "STRONG_SIGNAL_TH": 0.75,   # آستانه‌ی Strong Buy/Sell

    # ---------- خروجی ----------
    "TOP_N_RESULTS": 15,        # فقط بهترین N کوین نمایش داده شود (نه کل یونیورس)

    # ---------- منبع لیست کوین‌ها (Universe) ----------
    "UNIVERSE_SOURCE": "coingecko",   # گزینه‌ها: "coingecko" یا "tradingview"

    # ---------- توگل کردن موتورها (روشن/خاموش) ----------
    "ENGINES_ENABLED": {
        "trend": True,
        "derivative": True,
        "integral": True,
        "energy": True,
        "structure": True,
        "regime": True,
    },
}


import json
import os
import copy

# سلسله‌مراتب تایم‌فریم‌ها از کوچک به بزرگ — برای تشخیص خودکار «تایم‌فریم تأیید»
TF_HIERARCHY = ["30m", "1h", "4h", "1d", "1w"]


def resolve_confirm_timeframe(main_tf: str, cfg: dict) -> str | None:
    """
    اگر CONFIRM_TIMEFRAME روی "auto" باشد، تایم‌فریم بزرگ‌تر بعدی در TF_HIERARCHY
    را برمی‌گرداند. اگر مقدار دستی داده شده باشد، همان را برمی‌گرداند.
    اگر تایم‌فریم اصلی از قبل بالاترین سطح باشد (مثلاً هفتگی)، None برمی‌گرداند
    (یعنی تأیید تایم‌فریم بالاتر انجام نمی‌شود).
    """
    manual = cfg.get("CONFIRM_TIMEFRAME", "auto")
    if manual and manual != "auto":
        return manual
    if main_tf in TF_HIERARCHY:
        idx = TF_HIERARCHY.index(main_tf)
        if idx + 1 < len(TF_HIERARCHY):
            return TF_HIERARCHY[idx + 1]
    return None


def load_config(settings_path: str = "settings.json") -> dict:
    """
    تنظیمات پیش‌فرض بالا را با محتوای settings.json (اگر وجود داشته باشد) ادغام می‌کند.
    settings.json از طریق پنل تصویری تنظیمات ساخته می‌شود و نیازی به دست‌کاری این فایل نیست.
    """
    cfg = copy.deepcopy(CONFIG)
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                overrides = json.load(f)
            for key, value in overrides.items():
                if key == "ENGINES_ENABLED" and isinstance(value, dict):
                    cfg["ENGINES_ENABLED"].update(value)
                else:
                    cfg[key] = value
            pass  # بارگذاری موفق بود؛ بی‌صدا
        except Exception:
            pass  # خطا در خواندن؛ بی‌صدا از تنظیمات پیش‌فرض استفاده می‌شود
    # اگر settings.json نبود، بی‌صدا از تنظیمات پیش‌فرض config.py استفاده می‌شود
    return cfg
