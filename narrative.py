"""
narrative.py

لایه‌ی تحلیل کلامی (Analysis Layer) برای نمایش داخل Expander زیر هر کارت سیگنال.

نکته‌ی مهم درباره‌ی معماری:
• این فایل هیچ داده‌ی جدیدی از صرافی/API دریافت نمی‌کند و هیچ عدد فرضی یا
  شبیه‌سازی‌شده تولید نمی‌کند؛ فقط همان دیکشنری res را که main.py/decision.py
  از قبل و فقط یک‌بار محاسبه کرده‌اند می‌گیرد و به زبان محاوره‌ای تفسیر می‌کند.
• هیچ فرمول، وزن، آستانه یا منطق تصمیم‌گیری‌ای در این فایل وجود ندارد و
  تغییر نمی‌کند — این فایل کاملاً در لایه‌ی نمایش (UI) قرار دارد.
• طبق اصل «هر بخش در فایل مستقل خودش»، این ماژول جدا از app.py نگه داشته
  شده تا لایه‌ی تحلیل کلامی از لایه‌ی چیدمان/رندر UI مجزا بماند.
"""

ENGINE_LABELS_CASUAL = {
    "trend": "روند",
    "derivative": "سرعت بازار",
    "integral": "حافظه‌ی روند",
    "energy": "انرژی",
    "funding": "فاندینگ",
}


def _level(value: float) -> str:
    """
    سطح کیفیِ صرفاً کلامیِ یک امتیاز 0..100 — این فقط یک برچسب برای نوشتن
    جمله است و هیچ ارتباطی با آستانه‌های تصمیم‌گیری استراتژی (BUY/SELL) در
    decision.py ندارد و آن‌ها را تغییر نمی‌دهد.
    """
    if value >= 75:
        return "قوی"
    if value >= 60:
        return "نسبتاً قوی"
    if value >= 40:
        return "خنثی"
    if value >= 25:
        return "نسبتاً ضعیف"
    return "ضعیف"


_ENGINE_PHRASES = {
    "trend": {
        "قوی": "روند قیمت خیلی واضح و رو به بالا حرکت می‌کند",
        "نسبتاً قوی": "روند نسبتاً مثبت است، ولی هنوز خیلی قدرتمند نشده",
        "خنثی": "روند مشخصی دیده نمی‌شود، بازار سردرگم است",
        "نسبتاً ضعیف": "روند کمی رو به پایین کشیده شده",
        "ضعیف": "روند به‌وضوح نزولی است",
    },
    "derivative": {
        "قوی": "سرعت حرکت قیمت (شتاب بازار) بالاست",
        "نسبتاً قوی": "سرعت بازار کمی رو به افزایش است",
        "خنثی": "سرعت بازار در حالت عادی و بدون تغییر محسوس است",
        "نسبتاً ضعیف": "سرعت بازار کمی کند شده",
        "ضعیف": "بازار به‌شدت کند شده، انگار ترمز گرفته",
    },
    "integral": {
        "قوی": "این حرکت پشتوانه‌ی خوبی از حافظه‌ی روند قبلی دارد",
        "نسبتاً قوی": "حافظه‌ی روند تا حدی از این حرکت حمایت می‌کند",
        "خنثی": "حافظه‌ی روند نظر خاصی نمی‌دهد",
        "نسبتاً ضعیف": "حافظه‌ی روند کمی در جهت مخالف است",
        "ضعیف": "حافظه‌ی روند با این حرکت هم‌خوانی ندارد",
    },
    "energy": {
        "قوی": "حجم معاملات و انرژی بازار بالاست، پول واقعی وارد شده",
        "نسبتاً قوی": "انرژی بازار قابل‌قبول است",
        "خنثی": "انرژی بازار در سطح معمولی است",
        "نسبتاً ضعیف": "انرژی بازار کمی افت کرده",
        "ضعیف": "انرژی بازار خیلی کم است، حجم معاملات ضعیف است",
    },
    "funding": {
        "قوی": "فضای فاندینگ به نفع این حرکت است",
        "نسبتاً قوی": "فضای فاندینگ کمی مثبت است",
        "خنثی": "فاندینگ در حالت خنثی است",
        "نسبتاً ضعیف": "فاندینگ کمی در جهت مخالف است",
        "ضعیف": "فضای فاندینگ در تضاد با این حرکت است",
    },
}


def _funding_tier(conviction_value: float) -> str:
    """
    ورودی این تابع «امتیاز هم‌جهتی با سیگنال فعلی» است (نه لزوماً امتیاز خام):
    ۵۰ = خنثی، بالای ۵۰ = هم‌جهت/تأییدکننده‌ی سیگنال، زیر ۵۰ = مخالف سیگنال.
    اگر فاندینگ در جهت مخالف سیگنال باشد (یا اثر ناچیزی داشته باشد)، در ردیف
    «ضعیف» قرار می‌گیرد؛ فقط انحراف در جهتِ تأییدکننده تقویت و به سه‌سطح
    ضعیف/خوب/عالی نگاشت می‌شود (طبق مقیاس درخواستی: <۶۰ ضعیف، ۶۰-۸۰ خوب، ۸۰-۱۰۰ عالی).
    """
    supportive_deviation = conviction_value - 50
    if supportive_deviation <= 0:
        return "ضعیف"
    # حداکثر نوسان واقعی مشاهده‌شده حدود ۳ واحد است؛ این مقدار به بالای مقیاس نگاشت می‌شود
    amplified = min(100.0, 50 + supportive_deviation * (50 / 3))
    if amplified >= 80:
        return "عالی"
    if amplified >= 60:
        return "خوب"
    return "ضعیف"


_FUNDING_TIER_PHRASES = {
    "عالی": "فاندینگ خیلی واضح و قاطع هم‌جهت با این حرکت قرار گرفته",
    "خوب": "فاندینگ هم تا حد قابل‌قبولی همین جهت را تأیید می‌کند",
    "ضعیف": "فاندینگ فعلاً سیگنال قاطعی نمی‌دهد و نسبتاً بی‌طرف یا مخالف است",
}


def _engine_phrase(key: str, value: float, conviction_value: float = None) -> str:
    if key == "funding":
        return _FUNDING_TIER_PHRASES[_funding_tier(conviction_value if conviction_value is not None else value)]
    return _ENGINE_PHRASES.get(key, {}).get(_level(value), "")


def build_analysis(res: dict) -> dict:
    """
    ورودی: همان دیکشنری res که main.py از قبل و فقط یک‌بار محاسبه کرده است
    (raw_scores_100, weighted_score, regime_fa, trend_exhaustion,
    energy_exhaustion, signal) — هیچ محاسبه‌ی تکراری یا داده‌ی جدیدی اینجا
    انجام/دریافت نمی‌شود.

    خروجی: متن سه‌لایه‌ی محاوره‌ای (طبق قاعده‌ی ۳لایه) برای نمایش در Expander.
    """
    scores = res["raw_scores_100"]
    is_buy = res["signal"] == "خرید"

    # رتبه‌بندی موتورها بر اساس «میزان هم‌جهتی با سیگنال فعلی» (نه مقدار خام)،
    # چون شاخص‌هایی مثل فاندینگ ذاتاً حول ۵۰ نوسان می‌کنند و مقایسه‌ی مقدار
    # خام آن‌ها با موتورهایی که بازه‌ی طبیعی ۰..۱۰۰ دارند (مثل روند) گمراه‌کننده
    # است؛ این تغییر فقط انتخاب جمله‌ی نمایشی را اصلاح می‌کند و بر امتیاز نهایی/
    # آستانه‌های تصمیم‌گیری هیچ اثری ندارد.
    conviction = {k: (v if is_buy else 100 - v) for k, v in scores.items()}

    # فاندینگ ذاتاً حول ۵۰ نوسان می‌کند؛ برای مقایسه‌ی «کدام موتور برجسته‌تر
    # است» با موتورهایی که بازه‌ی طبیعی ۰..۱۰۰ دارند، نسخه‌ی تقویت‌شده (همان
    # منطق _funding_tier) فقط برای رتبه‌بندی استفاده می‌شود؛ امتیاز خام نمایشی
    # و امتیاز وزنی نهایی دست‌نخورده باقی می‌مانند.
    ranking_conviction = dict(conviction)
    if "funding" in ranking_conviction:
        fdev = ranking_conviction["funding"] - 50
        if fdev > 0:
            ranking_conviction["funding"] = min(100.0, 50 + fdev * (50 / 3))

    sorted_engines = sorted(ranking_conviction.items(), key=lambda kv: kv[1], reverse=True)
    strongest_key, _ = sorted_engines[0]
    weakest_key, _ = sorted_engines[-1]
    strongest_val = scores[strongest_key]
    weakest_val = scores[weakest_key]

    # ---------- لایه‌ی ۱: جمع‌بندی قضاوتی ----------
    if is_buy:
        layer1 = ("🟢 بازار خیلی قدرتمند داره حرکت می‌کنه!" if res["weighted_score"] >= 80
                   else "🟢 بازار داره به سمت بالا حرکت می‌کنه")
    else:
        layer1 = ("🔴 فشار فروش قوی روی بازار حس می‌شه، مراقب باش!" if res["weighted_score"] <= 20
                   else "🔴 بازار داره ضعیف می‌شه و نزولی به نظر می‌رسه")

    # ---------- لایه‌ی ۲: توضیح ساده (چی شده، برای معامله‌گر یعنی چی، قوت یا ضعف) ----------
    strongest_phrase = _engine_phrase(strongest_key, strongest_val, conviction[strongest_key])
    weakest_phrase = _engine_phrase(weakest_key, weakest_val, conviction[weakest_key])

    trend_ex = res.get("trend_exhaustion")
    energy_ex = res.get("energy_exhaustion")
    exhaustion_note = ""
    if trend_ex is not None and energy_ex is not None:
        if max(trend_ex, energy_ex) >= 70:
            exhaustion_note = " البته یه‌کم نشونه‌ی خستگی تو حرکت دیده می‌شه، پس بی‌گدار به آب نزن."
        elif max(trend_ex, energy_ex) <= 35:
            exhaustion_note = " این حرکت هنوز تازه‌ست و جای رشد داره."

    layer2 = (
        f"چی شده؟ {ENGINE_LABELS_CASUAL.get(strongest_key, strongest_key)} این‌جا حرف اول رو می‌زنه: "
        f"{strongest_phrase}. از طرفی {ENGINE_LABELS_CASUAL.get(weakest_key, weakest_key)} یه‌کم عقب‌تره: "
        f"{weakest_phrase}.{exhaustion_note} برای معامله‌گر یعنی الان "
        f"{'ورود هم‌جهت با روند منطقی‌تره' if is_buy else 'بهتره جانب احتیاط رعایت بشه'}؛ "
        f"وضعیت کلی بازار هم «{res['regime_fa']}» تشخیص داده شده."
    )

    # ---------- لایه‌ی ۳: نقاط قوت/ضعف/ریسک و امتیاز کیفی نهایی ----------
    strengths, weaknesses = [], []
    for key, val in scores.items():
        label = ENGINE_LABELS_CASUAL.get(key, key)
        if is_buy and val >= 60:
            strengths.append(label)
        elif is_buy and val < 45:
            weaknesses.append(label)
        elif (not is_buy) and val <= 40:
            strengths.append(label)
        elif (not is_buy) and val > 55:
            weaknesses.append(label)

    if not strengths:
        strengths = ["در حال حاضر مورد برجسته‌ای نیست"]
    if not weaknesses:
        weaknesses = ["ریسک خاصی در موتورها دیده نمی‌شود"]

    directional_score = res["weighted_score"] if is_buy else (100 - res["weighted_score"])
    if directional_score >= 90:
        final_score = "⭐️⭐️⭐️ عالی"
    elif directional_score >= 85:
        final_score = "⭐️⭐️ خوب"
    else:
        final_score = "⭐️ ضعیف"

    return {
        "layer1": layer1,
        "layer2": layer2,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "final_score": final_score,
    }
