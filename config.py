"""
تنظیمات اصلی استراتژی — همه‌ی پارامترهای قابل تغییر اینجا هستند
تا حجم اجرا (تعداد کوین × تعداد تایم‌فریم × بازه‌های محاسباتی) قابل کنترل باشد.

نسخه‌ی اصلاح‌شده بر اساس نتیجه‌گیری بک‌تست ۱۲ دیتاست (۶ کوین × ۲ تایم‌فریم):
تایم‌فریم پیش‌فرض از ۴ساعته به روزانه تغییر کرد، موتور ساختار حذف شد،
موتور فاندینگ اضافه شد، فیلتر حجم مطلق اضافه شد و پروفایل معاملاتی
جداگانه برای کوین‌های ناهمسو (مثل TRX) اضافه شد.
"""

import json
import os
import copy

CONFIG = {
    # ---------- جهان قابل بررسی (Universe) ----------
    "UNIVERSE_SIZE": 50,  # تعداد کوین برتر بر اساس مارکت‌کپ (قابل تغییر: 20 / 50 / 100 / 300)
    "QUOTE_ASSET": "USDT",
    "EXCHANGE_ID": "mexc",  # از طریق ccxt — به‌جای Binance (فیلتر/تحریم ایران)؛ جایگزین: "kucoin"

    # ---------- تایم‌فریم ----------
    # طبق نتیجه‌ی بک‌تست: در همه‌ی ۶ کوین بدون استثنا خروجی روی روزانه
    # قابل‌اعتماد بود و روی ۴ساعته ضعیف/نامعتبر؛ تایم‌فریم پیش‌فرض از
    # "4h" به "1d" تغییر کرد (اولویت ۱ در جدول نقشه‌راه بک‌تست).
    "MAIN_TIMEFRAME": "1d",
    "CONFIRM_TIMEFRAME": "auto",  # "auto" = خودش تایم‌فریم بالاتر را از TF_HIERARCHY انتخاب می‌کند
    "CANDLE_LIMIT": 500,

    # ---------- بازه‌های محاسباتی مشتق/انتگرال (ایده اصلی کاربر) ----------
    "SCALES": [8, 21, 55],

    # ---------- EMAهای روند ----------
    "EMA_PERIODS": [21, 50, 100, 200],

    # ---------- وزن موتورها بر اساس رژیم بازار (رزرو برای توسعه‌ی آینده) ----------
    "ENGINE_WEIGHTS": {
        "trending": {
            "trend": 0.15, "derivative": 0.25, "integral": 0.20,
            "energy": 0.25, "funding": 0.10, "regime": 0.05,
        },
        "ranging": {
            "trend": 0.10, "derivative": 0.15, "integral": 0.15,
            "energy": 0.20, "funding": 0.15, "regime": 0.25,
        },
        "volatile": {
            "trend": 0.10, "derivative": 0.15, "integral": 0.15,
            "energy": 0.20, "funding": 0.10, "regime": 0.30,
        },
    },

    # ---------- آستانه‌های تصمیم‌گیری ----------
    "CONFIDENCE_MIN": 0.55,
    "CONSENSUS_MIN": 0.55,
    "STRONG_SIGNAL_TH": 0.75,

    # ---------- خروجی ----------
    "TOP_N_RESULTS": 15,

    # ---------- منبع لیست کوین‌ها (Universe) ----------
    "UNIVERSE_SOURCE": "coingecko",  # گزینه‌ها: "coingecko" یا "tradingview"

    # ---------- فیلتر نقدینگی/حجم مطلق (جدید — اولویت ۹ نقشه‌راه) ----------
    # کوین‌هایی با حجم معاملات ۲۴ساعته (به دلار) کمتر از این مقدار، مستقل از
    # رتبه‌ی مارکت‌کپ، به‌طور کامل از یونیورس حذف می‌شوند.
    "MIN_24H_VOLUME_USDT": 1_000_000,

    # ---------- پروفایل معاملاتی جداگانه برای کوین‌های ناهمسو (جدید — اولویت ۱۱) ----------
    # طبق بک‌تست، TRX تنها کوینی بود که رفتار متفاوت/معکوس نسبت به بقیه نشان
    # داد. برای این نمادها آستانه‌ی سخت‌گیرانه‌تر و الزام تأیید تایم‌فریم
    # بالاتر اعمال می‌شود (سیگنال بدون تأیید صادر نمی‌شود).
    "SPECIAL_PROFILES": {
        "TRX": {
            "buy_threshold": 82,
            "sell_threshold": 18,
            "require_confirm_agree": True,
        },
    },

    # ---------- توگل کردن موتورها (روشن/خاموش) ----------
    # موتور "structure" طبق نتیجه‌ی بک‌تست حذف شد (در تمام ۱۲ دیتاست داده‌ی
    # کافی برای نتیجه‌گیری معنادار وجود نداشت — n<30، اغلب n<10).
    # موتور "funding" جدید اضافه شد (Funding Rate / Open Interest).
    "ENGINES_ENABLED": {
        "trend": True,
        "derivative": True,
        "integral": True,
        "energy": True,
        "funding": True,
        "regime": True,
    },

    # ---------- پارامترهای بک‌تست (برای backtest_app.py) ----------
    # LOOKAHEAD افزایش یافت (اولویت ۱۲ نقشه‌راه) تا افق سنجش ادامه/بازگشت
    # واقعی‌تر باشد، به‌خصوص روی تایم‌فریم روزانه‌ی جدید.
    "BACKTEST_LOOKAHEAD": 10,
    "BACKTEST_WARMUP": 220,
}

# سلسله‌مراتب تایم‌فریم‌ها از کوچک به بزرگ — برای تشخیص خودکار «تایم‌فریم تأیید»
TF_HIERARCHY = ["30m", "1h", "4h", "1d", "1w"]


def resolve_confirm_timeframe(main_tf: str, cfg: dict):
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
                elif key == "SPECIAL_PROFILES" and isinstance(value, dict):
                    cfg["SPECIAL_PROFILES"].update(value)
                else:
                    cfg[key] = value
        except Exception:
            pass  # خطا در خواندن؛ بی‌صدا از تنظیمات پیش‌فرض استفاده می‌شود
    return cfg
