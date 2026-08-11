"""
تبدیل خروجی موتورها به امتیاز نهایی 0..100 و فیلتر نهایی سیگنال.

نسخه‌ی اصلاح‌شده طبق نتیجه‌ی بک‌تست ۱۲ دیتاست (۶ کوین × ۲ تایم‌فریم):
• موتور "ساختار" حذف شد (داده‌ی ناکافی در تمام ۱۲ دیتاست) — اولویت ۲.
• وزن موتور "روند" کاهش یافت (رفتار ناپایدار بین کوین‌ها، تضعیف‌کننده‌ی
  سیگنال بقیه‌ی موتورها به‌خاطر وزن ×۳ قبلی) — اولویت ۵.
• موتور "انرژی" روی تایم‌فریم‌های غیر از روزانه وزن کمتری می‌گیرد — اولویت ۶.
• موتور جدید "فاندینگ" (Funding Rate / Open Interest) اضافه شد — اولویت ۹.
• آستانه‌های خرید/فروش بعد از تغییرات بالا بازتنظیم شدند — اولویت ۸.
• پروفایل معاملاتی جداگانه برای کوین‌های ناهمسو (مثل TRX) اعمال می‌شود — اولویت ۱۱.
• هشدار ترکیبی «هر دو فرسودگی هم‌زمان» از منطق تصمیم‌گیری حذف شد (لایه‌ی
  رابط کاربری) — اولویت ۳؛ فرسودگی همچنان به‌صورت اطلاعاتی نمایش داده می‌شود.

منطق پایه (بدون تغییر):
• هر موتور جهت‌دار یک امتیاز 0..100 می‌گیرد (100 = کاملاً صعودی، 0 = کاملاً نزولی).
• میانگین وزنی این امتیازها بر اساس اهمیت هر موتور محاسبه می‌شود.
• Regime (رژیم بازار) در میانگین شرکت نمی‌کند؛ فقط زمینه‌ای نمایش داده می‌شود.
"""

import numpy as np

# اهمیت هر موتور در میانگین وزنی نهایی (پایه — روی تایم‌فریم روزانه)
IMPORTANCE_WEIGHTS = {
    "trend": 1,        # وزن کاهش‌یافته (بود: ۳) — بک‌تست: ناپایدار بین کوین‌ها، تضعیف‌کننده
    "derivative": 3,   # قوی‌ترین الگوی تکرارشونده‌ی بک‌تست (روی روزانه)
    "integral": 2,     # هم‌راستا با مشتق، دومین الگوی قوی
    "energy": 2,       # تأیید حجمی — وزن مؤثر روی تایم‌فریم غیر روزانه کمتر می‌شود
    "funding": 1,      # موتور جدید، کم‌اطمینان تا تست جداگانه (اولویت پایین)
}

# روی تایم‌فریم‌های غیر از روزانه، وزن مؤثر انرژی طبق بک‌تست کاهش می‌یابد
ENERGY_WEIGHT_MULTIPLIER_NON_DAILY = 0.5

ENGINE_LABELS_FA = {
    "trend": "روند",
    "derivative": "مشتق",
    "integral": "انتگرال",
    "energy": "انرژی",
    "funding": "فاندینگ",
}

REGIME_LABELS_FA = {
    "trending": "روندی",
    "ranging": "رنج",
    "volatile": "پرنوسان",
}

# آستانه‌های بازتنظیم‌شده بعد از حذف ساختار و کاهش وزن روند (بود: 75 / 25)
BUY_THRESHOLD = 78
SELL_THRESHOLD = 22


def _to_100(score_pm1: float) -> float:
    """تبدیل امتیاز -1..+1 به مقیاس 0..100"""
    s = max(-1.0, min(1.0, score_pm1))
    return round((s + 1) / 2 * 100, 1)


def _effective_weights(cfg: dict) -> dict:
    """وزن مؤثر هر موتور را بر اساس تایم‌فریم اصلی برمی‌گرداند (کپی، بدون تغییر دیکشنری پایه)."""
    weights = dict(IMPORTANCE_WEIGHTS)
    if cfg.get("MAIN_TIMEFRAME") != "1d":
        weights["energy"] = weights["energy"] * ENERGY_WEIGHT_MULTIPLIER_NON_DAILY
    return weights


def fuse_and_decide(engine_outputs: dict, cfg: dict, symbol: str = None) -> dict:
    trend = engine_outputs["trend"]
    deriv = engine_outputs["derivative"]
    integ = engine_outputs["integral"]
    energy = engine_outputs["energy"]
    funding = engine_outputs["funding"]
    regime = engine_outputs["regime"]

    raw_scores_100 = {
        "trend": _to_100(trend["trend_score"]),
        "derivative": _to_100(np.tanh(deriv["derivative_score"] * 2 - 1)),
        "integral": _to_100(integ["integral_memory_score"] * 2 - 1),
        "energy": _to_100(energy["energy_score"] * 2 - 1),
        "funding": _to_100(funding["funding_score"]),
    }

    weights = _effective_weights(cfg)
    total_weight = sum(weights.values())
    weighted_score = round(sum(
        raw_scores_100[k] * weights[k] for k in weights
    ) / total_weight, 1)

    # ---------- پروفایل معاملاتی جداگانه برای کوین‌های ناهمسو (مثل TRX) ----------
    buy_th, sell_th = BUY_THRESHOLD, SELL_THRESHOLD
    require_confirm_agree = False
    base_symbol = symbol.split("/")[0].upper() if symbol else None
    profile = (cfg.get("SPECIAL_PROFILES", {}) or {}).get(base_symbol)
    if profile:
        buy_th = profile.get("buy_threshold", buy_th)
        sell_th = profile.get("sell_threshold", sell_th)
        require_confirm_agree = profile.get("require_confirm_agree", False)

    if weighted_score >= buy_th:
        signal = "خرید"
    elif weighted_score <= sell_th:
        signal = "فروش"
    else:
        signal = None  # بین آستانه‌ها => سیگنال قطعی نیست (حذف نمی‌شود، فقط نمایش نزدیک‌ترین‌ها)

    return {
        "raw_scores_100": raw_scores_100,
        "weighted_score": weighted_score,
        "signal": signal,
        "regime_fa": REGIME_LABELS_FA.get(regime["regime"], regime["regime"]),
        "market_strength": round(min(regime["adx"] * 2, 100), 1),
        "buy_threshold": buy_th,
        "sell_threshold": sell_th,
        "require_confirm_agree": require_confirm_agree,
    }
