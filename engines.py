"""
موتورهای تحلیلی استراتژی — نسخه‌ی اصلاح‌شده طبق نتیجه‌ی بک‌تست ۱۲ دیتاست
(۶ کوین × ۲ تایم‌فریم).

تغییرات نسبت به نسخه‌ی قبلی:
• موتور "ساختار" (Structure) به‌طور کامل حذف شد — در تمام ۱۲ دیتاست بک‌تست
  داده‌ی کافی (n>=30) برای هیچ نتیجه‌گیری معناداری وجود نداشت (اولویت ۲).
• موتور "مشتق" (Derivative) با فیلتر کالمن (Kalman Filter) بازطراحی شد —
  به‌جای تفاضل ساده (diff)، سرعت قیمت با یک فیلتر کالمن (مدل سرعت ثابت)
  برآورد می‌شود که نویز کمتری نسبت به تفاضل خام دارد (اولویت ۴).
• موتور "روند" با میان‌گیری نمایی (EMA) روی امتیاز نهایی، برای کاهش
  ناپایداری بین کوین‌ها که در بک‌تست مشاهده شد، صاف‌تر شد (اولویت ۵؛
  وزن این موتور در decision.py هم کاهش یافت).
• موتور "انتگرال" هم‌راستا با خروجی جدید مشتق بازطراحی شد — «حافظه‌ی روند»
  اکنون از انباشت سرعت کالمن‌شده محاسبه می‌شود، نه از انباشت بازده‌ی خام
  (اولویت ۷).
• موتور جدید "فاندینگ" (Funding Rate / Open Interest) اضافه شد (اولویت ۹).
• موتور "انرژی" (FWI) بدون تغییر فرمول باقی ماند؛ وزنش در تایم‌فریم‌های
  غیر از روزانه در decision.py کاهش می‌یابد (اولویت ۶).
• موتور "وضعیت بازار" (Regime) بدون تغییر باقی ماند (طبق بک‌تست: حفظ شود).

هر تابع یک DataFrame با ستون‌های open/high/low/close/volume می‌گیرد
و یک دیکشنری امتیاز نرمالایزشده برمی‌گرداند.
"""

import numpy as np
import pandas as pd


def _norm(series: pd.Series, window: int = 200) -> pd.Series:
    """نرمال‌سازی z-score غلتان و فشرده‌سازی به بازه‌ی 0..1 با تابع سیگموید."""
    roll_mean = series.rolling(window, min_periods=20).mean()
    roll_std = series.rolling(window, min_periods=20).std().replace(0, np.nan)
    z = (series - roll_mean) / roll_std
    return 1 / (1 + np.exp(-z.fillna(0)))


def _kalman_velocity(series: pd.Series, process_var: float = 1e-5, measurement_var: float = 1e-2) -> pd.Series:
    """
    فیلتر کالمن ساده با مدل «سرعت ثابت» (constant velocity) برای برآورد
    سرعت (مشتق) قیمت، با نویز کمتر نسبت به تفاضل ساده (diff).
    حالت پنهان: [قیمت, سرعت]. فقط قیمت اندازه‌گیری می‌شود.
    measurement_var بزرگ‌تر => فیلتر به اندازه‌گیری (قیمت خام) کمتر اعتماد
    می‌کند => خروجی نرم‌تر/کندتر (مناسب بازه‌های بلندمدت‌تر).
    """
    n = len(series)
    prices = series.values.astype(float)
    x = np.array([prices[0] if n else 0.0, 0.0])
    P = np.eye(2)
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    Q = np.array([[process_var, 0.0], [0.0, process_var]])
    R = measurement_var

    velocities = np.zeros(n)
    for i in range(n):
        # پیش‌بینی
        x = F @ x
        P = F @ P @ F.T + Q
        # به‌روزرسانی
        z = prices[i]
        y = z - (H @ x)[0]
        S = (H @ P @ H.T)[0, 0] + R
        K = (P @ H.T).flatten() / S
        x = x + K * y
        P = (np.eye(2) - np.outer(K, H)) @ P
        velocities[i] = x[1]
    return pd.Series(velocities, index=series.index)


# ------------------------------------------------------------------
# 1) Trend Engine
# ------------------------------------------------------------------
def trend_engine(df: pd.DataFrame, ema_periods: list) -> dict:
    close = df["close"]
    emas = {p: close.ewm(span=p, adjust=False).mean() for p in ema_periods}

    # شیب هر EMA (رگرسیون خطی ساده روی 10 کندل آخر، به‌صورت بردار)
    def slope(s, n=10):
        return (s - s.shift(n)) / n

    slopes = {p: slope(e) for p, e in emas.items()}

    # همسویی EMAها (Alignment): آیا EMA کوتاه‌تر بالای EMA بلندتر است (روند صعودی مرتب)
    ordered = sorted(ema_periods)
    alignment_up = np.ones(len(close), dtype=bool)
    for a, b in zip(ordered, ordered[1:]):
        alignment_up &= (emas[a] > emas[b]).values
    alignment_down = np.ones(len(close), dtype=bool)
    for a, b in zip(ordered, ordered[1:]):
        alignment_down &= (emas[a] < emas[b]).values

    alignment_score = pd.Series(
        np.where(alignment_up, 1.0, np.where(alignment_down, -1.0, 0.0)), index=close.index
    )

    # جهت کلی از میانگین شیب‌های نرمال‌شده
    slope_avg = pd.concat(slopes.values(), axis=1).mean(axis=1)
    direction_score = np.tanh(slope_avg / close.rolling(50).std().replace(0, np.nan))
    direction_score = direction_score.fillna(0)

    # کیفیت روند = هم‌جهتی EMAها + پایداری شیب (کم بودن نوسان شیب)
    slope_std = pd.concat(slopes.values(), axis=1).std(axis=1)
    quality_score = _norm(-slope_std)

    # فرسودگی روند: وقتی شیب در حال کاهش است ولی قیمت هنوز بالاست
    exhaustion = _norm(-slope_avg.diff(5))

    raw_trend_score = (alignment_score.clip(-1, 1) + np.tanh(direction_score)) / 2
    # میان‌گیری نمایی (EMA) برای کاهش ناپایداری بین کوین‌ها که در بک‌تست دیده شد
    trend_score = raw_trend_score.ewm(span=5, adjust=False).mean()

    return {
        "trend_score": float(trend_score.iloc[-1]),
        "trend_quality": float(quality_score.iloc[-1]),
        "trend_direction": float(direction_score.iloc[-1]),
        "trend_exhaustion": float(exhaustion.iloc[-1]),
    }


# ------------------------------------------------------------------
# 2) Derivative Engine — بازطراحی‌شده با فیلتر کالمن (Kalman Filter Derivative)
# ------------------------------------------------------------------
def derivative_engine(df: pd.DataFrame, scales: list) -> dict:
    close = df["close"]
    results = {}
    aligned_signs = []

    for s in scales:
        # مقیاس بزرگ‌تر => واریانس اندازه‌گیری کمتر => فیلتر نرم‌تر/پایدارتر
        measurement_var = 0.5 / s
        v1 = _kalman_velocity(close, process_var=1e-5, measurement_var=measurement_var)  # سرعت کالمن‌شده
        v2 = v1.diff(s)  # شتاب (تغییر سرعت کالمن‌شده در بازه‌ی s)
        v1n = _norm(v1)
        v2n = _norm(v2)
        results[f"d1_{s}"] = float(v1n.iloc[-1])
        results[f"d2_{s}"] = float(v2n.iloc[-1])
        aligned_signs.append(np.sign(v1.iloc[-1]))

    # همگرایی/همسویی مشتق‌ها در سه مقیاس (کوتاه/میان/بلند)
    alignment = 1.0 if len(set(aligned_signs)) == 1 and aligned_signs[0] != 0 else 0.0
    # اگر جهت مشتق کوتاه‌مدت با بلندمدت مخالف باشد => تضاد (ریسک بازگشت روند)
    conflict = 1.0 if aligned_signs[0] != aligned_signs[-1] else 0.0

    d1_avg = np.mean([results[f"d1_{s}"] for s in scales])
    d2_avg = np.mean([results[f"d2_{s}"] for s in scales])

    return {
        "derivative_score": float(d1_avg),
        "derivative_acceleration": float(d2_avg),
        "derivative_alignment": alignment,
        "derivative_conflict": conflict,
        "raw": results,
    }


# ------------------------------------------------------------------
# 3) Integral Engine — بازطراحی‌شده هم‌راستا با مشتق کالمن‌شده
# ------------------------------------------------------------------
def integral_engine(df: pd.DataFrame, scales: list) -> dict:
    close = df["close"]
    vol = df["volume"]
    ret = close.pct_change().fillna(0)

    trend_memory = {}
    energy_accum = {}

    for s in scales:
        measurement_var = 0.5 / s
        velocity = _kalman_velocity(close, process_var=1e-5, measurement_var=measurement_var)
        vol_norm_std = close.rolling(s, min_periods=5).std().replace(0, np.nan)
        velocity_norm = velocity / vol_norm_std
        # Trend Integral: انباشت سرعت کالمن‌شده روی پنجره‌ی s => «حافظه‌ی روند»
        # (هم‌راستا با موتور مشتق جدید، به‌جای انباشت بازده‌ی خام قبلی)
        trend_memory[s] = float(_norm(velocity_norm.rolling(s).sum()).iloc[-1])
        # Energy Integral: مجموع (حجم نسبی × قدر مطلق بازده) => انرژی انباشته واقعی (بدون تغییر)
        energy = (vol / vol.rolling(s).mean().replace(0, np.nan)) * ret.abs()
        energy_accum[s] = float(_norm(energy.rolling(s).sum()).iloc[-1])

    memory_score = float(np.mean(list(trend_memory.values())))
    energy_score = float(np.mean(list(energy_accum.values())))

    # پایداری/بلوغ روند: آیا حافظه کوتاه‌مدت با بلندمدت هم‌جهت و هم‌سطح است؟
    persistence = 1.0 - abs(trend_memory[scales[0]] - trend_memory[scales[-1]])

    return {
        "integral_memory_score": memory_score,
        "integral_energy_score": energy_score,
        "integral_persistence": float(persistence),
    }


# ------------------------------------------------------------------
# 4) Energy Engine (FWI: Force Work Indicator) — بدون تغییر فرمول
# ------------------------------------------------------------------
def energy_engine(df: pd.DataFrame) -> dict:
    close = df["close"]
    volume = df["volume"]
    high, low = df["high"], df["low"]

    price_velocity = close.diff()
    atr = (high - low).rolling(14).mean().replace(0, np.nan)
    fwi = (volume * price_velocity / atr).ewm(span=14, adjust=False).mean()

    fwi_norm = _norm(fwi)
    fwi_slope = fwi.diff(5)

    growth = 1.0 if fwi_slope.iloc[-1] > 0 else 0.0
    exhaustion = _norm(-fwi.diff(1).rolling(10).mean())

    return {
        "energy_score": float(fwi_norm.iloc[-1]),
        "energy_growth": growth,
        "energy_exhaustion": float(exhaustion.iloc[-1]),
    }


# ------------------------------------------------------------------
# 5) Funding Engine (جدید — Funding Rate / Open Interest)
# ------------------------------------------------------------------
def funding_engine(exchange, symbol: str) -> dict:
    """
    نرخ فاندینگ و بهره‌ی باز (Open Interest) بازار فیوچرز/پرپچوال متناظر.
    این داده مستقل از قیمت است و می‌تواند ضعف موتورهای دیگر روی تایم‌فریم‌های
    کوتاه‌تر را جبران کند (طبق پیشنهاد مرحله‌ی ۶ بک‌تست).
    اگر صرافی یا نماد از فاندینگ پشتیبانی نکند (مثلاً بازار اسپات)، امتیاز
    خنثی (۰.۰) برمی‌گرداند تا در میانگین وزنی اثر مصنوعی نگذارد.
    """
    neutral = {"funding_score": 0.0, "funding_rate": None, "open_interest": None, "available": False}
    try:
        if not getattr(exchange, "has", {}).get("fetchFundingRate", False):
            return neutral
        data = exchange.fetch_funding_rate(symbol)
        rate = data.get("fundingRate")
        if rate is None:
            return neutral
        # فاندینگ مثبت بالا => ازدحام لانگ‌ها (فشار احتمالی نزولی) و برعکس؛
        # با tanh به بازه‌ی -1..1 فشرده می‌شود (خلاف جهت ازدحام معامله‌گران)
        funding_score = float(np.tanh(-rate * 500))
        open_interest = None
        if getattr(exchange, "has", {}).get("fetchOpenInterest", False):
            try:
                oi_data = exchange.fetch_open_interest(symbol)
                open_interest = oi_data.get("openInterestAmount") or oi_data.get("openInterestValue")
            except Exception:
                open_interest = None
        return {
            "funding_score": funding_score,
            "funding_rate": float(rate),
            "open_interest": open_interest,
            "available": True,
        }
    except Exception:
        return neutral


# ------------------------------------------------------------------
# 6) Regime Engine (تشخیص نویز/رنج/روند به‌صورت یکپارچه) — بدون تغییر
# ------------------------------------------------------------------
def regime_engine(df: pd.DataFrame) -> dict:
    high, low, close = df["high"], df["low"], df["close"]
    atr = (high - low).rolling(14).mean()
    atr_pct = atr / close

    # ADX ساده برای قدرت روند
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = pd.concat([
        high - low, (high - close.shift()).abs(), (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean().replace(0, np.nan)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(14).mean() / atr14
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(14).mean() / atr14
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx = dx.rolling(14).mean()

    adx_last = float(adx.iloc[-1]) if not np.isnan(adx.iloc[-1]) else 0.0
    vol_pct_last = float(atr_pct.iloc[-1]) if not np.isnan(atr_pct.iloc[-1]) else 0.0
    vol_pct_hist = atr_pct.rolling(100).mean().iloc[-1]

    if adx_last > 25:
        regime = "trending"
    elif vol_pct_last > (vol_pct_hist * 1.5 if vol_pct_hist else 0):
        regime = "volatile"
    else:
        regime = "ranging"

    noise_score = float(1 - min(adx_last / 50, 1.0))  # ADX پایین = نویز/بی‌جهتی بیشتر

    return {
        "regime": regime,
        "adx": adx_last,
        "noise_score": noise_score,
    }
