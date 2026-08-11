"""
اپ وب استراتژی معاملاتی — نسخه‌ی Streamlit
همون منطق فایل‌های اصلی (config/engines/decision/data/main) را استفاده می‌کند.

نسخه‌ی اصلاح‌شده: موتور "ساختار" حذف و موتور "فاندینگ" جایگزین آن در
ردیف موتورها شد؛ هشدار ترکیبی «هر دو فرسودگی هم‌زمان بالا» حذف شد
(طبق نتیجه‌ی بک‌تست).

اجرای محلی (اختیاری، برای تست):
pip install streamlit ccxt requests pandas numpy --break-system-packages
streamlit run app.py

برای انتشار روی اینترنت: راهنمای DEPLOY.md را ببینید.
"""

import copy
import json
import os
import re
import streamlit as st

from config import CONFIG
from data import get_universe, build_exchange
from decision import ENGINE_LABELS_FA, IMPORTANCE_WEIGHTS, BUY_THRESHOLD, SELL_THRESHOLD
from main import analyze_symbol

st.set_page_config(page_title="سیگنال‌یاب رمزارز", page_icon="📊", layout="centered")

TF_OPTIONS = {"۳۰ دقیقه": "30m", "۱ ساعته": "1h", "۴ ساعته": "4h", "روزانه": "1d", "هفتگی": "1w"}
TF_LABELS_FA = {"30m": "۳۰دقیقه", "1h": "۱ساعته", "4h": "۴ساعته", "1d": "روزانه", "1w": "هفتگی"}
ENGINE_KEYS = ["trend", "derivative", "integral", "energy", "funding"]
ENGINE_LABELS_LOCAL = {"trend": "روند", "derivative": "مشتق", "integral": "انتگرال", "energy": "انرژی", "funding": "فاندینگ"}

# ---------------------------------------------------------------------------
# استایل کلی صفحه: راست‌به‌چپ + فونت فارسی
# ---------------------------------------------------------------------------
st.markdown("""
<style>
html, body, [class*="css"]  { direction: rtl; font-family: Tahoma, Arial, sans-serif; }
.stApp { direction: rtl; }
section.main > div { direction: rtl; }
.stCheckbox, .stSelectbox, .stSlider { direction: rtl; text-align: right; }
h1, h2, h3, p, label { text-align: right; }
</style>
""", unsafe_allow_html=True)


def bar_html(value: float, neutral: bool = False) -> str:
    color = "#3b82f6" if neutral else ("#22c55e" if value >= 50 else "#ef4444")
    pct = max(0, min(100, value))
    return (f'<div dir="ltr" style="background:#374151;border-radius:6px;height:14px;'
            f'width:100%;overflow:hidden;"><div style="background:{color};height:100%;'
            f'width:{pct}%;"></div></div>')


def row_html(label: str, value: float, weight=None, neutral: bool = False, value_text=None) -> str:
    w_txt = f'<span style="color:#9ca3af;font-size:11px;"> ×{weight}</span>' if weight else ""
    vt = value_text if value_text is not None else value
    return (f'<div style="display:grid;grid-template-columns:95px 1fr 46px;align-items:center;'
            f'gap:8px;margin:4px 0;"><span style="font-size:13px;">{label}{w_txt}</span>'
            f'{bar_html(value, neutral)}<span style="font-size:13px;text-align:left;">{vt}</span></div>')


def format_price(p: float) -> str:
    """قالب‌بندی قیمت با دقت مناسب بسته به بزرگی عدد (مناسب هم برای بیت‌کوین و هم آلت‌کوین‌های ریزقیمت)."""
    if p >= 1:
        return f"{p:,.2f}"
    elif p >= 0.01:
        return f"{p:.4f}"
    else:
        return f"{p:.8f}"


def exhaustion_bar_html(value: float) -> str:
    """نوار سه‌رنگ برای مرحله‌ی حرکت: سبز=ابتدا، زرد=میانه، قرمز=انتهای احتمالی."""
    if value <= 33:
        color = "#22c55e"
    elif value <= 66:
        color = "#eab308"
    else:
        color = "#ef4444"
    pct = max(0, min(100, value))
    return (f'<div dir="ltr" style="background:#374151;border-radius:6px;height:14px;'
            f'width:100%;overflow:hidden;"><div style="background:{color};height:100%;'
            f'width:{pct}%;"></div></div>')


def exhaustion_stage_label(value: float) -> str:
    if value <= 33:
        return "ابتدا"
    if value <= 66:
        return "میانه"
    return "انتها"


def exhaustion_row_html(title: str, value: float) -> str:
    stage = exhaustion_stage_label(value)
    return (f'<div style="display:grid;grid-template-columns:95px 1fr 46px;align-items:center;'
            f'gap:8px;margin:4px 0;"><span style="font-size:13px;">{title} {value}</span>'
            f'{exhaustion_bar_html(value)}<span style="font-size:12px;text-align:left;color:#9ca3af;">'
            f'{stage}</span></div>')


def render_result_html(res: dict, cfg: dict, stars: str = "") -> str:
    tf = TF_LABELS_FA.get(cfg["MAIN_TIMEFRAME"], cfg["MAIN_TIMEFRAME"])
    dot = "#22c55e" if res["signal"] == "خرید" else "#ef4444"
    star_html = f'<span style="color:#fbbf24;">{stars}</span> ' if stars else ""

    def engine_row(k):
        value = res["raw_scores_100"][k]
        return (f'<div style="display:grid;grid-template-columns:95px 1fr 46px;align-items:center;'
                f'gap:8px;margin:4px 0;"><span style="font-size:13px;">{ENGINE_LABELS_FA[k]} {value}</span>'
                f'{bar_html(value)}<span style="font-size:13px;text-align:left;color:#9ca3af;">'
                f'×{IMPORTANCE_WEIGHTS[k]}</span></div>')

    rows = "".join(engine_row(k) for k in ENGINE_KEYS)
    market_row = row_html("وضعیت بازار", res["market_strength"], neutral=True, value_text=res["regime_fa"])
    avg_row = row_html("<b>میانگین وزنی</b>", res["weighted_score"])
    signal_bg = "#052e16" if res["signal"] == "خرید" else "#450a0a"
    signal_color = "#22c55e" if res["signal"] == "خرید" else "#ef4444"

    trend_ex = res.get("trend_exhaustion")
    energy_ex = res.get("energy_exhaustion")
    if trend_ex is None or energy_ex is None:
        exhaustion_rows = ('<div style="color:#9ca3af;font-size:12px;margin:6px 0;">'
                            '⚠️ داده‌ی فرسودگی در دسترس نیست — مطمئن شوید آخرین نسخه‌ی main.py آپلود شده است.</div>')
        exhaustion_note = ""
    else:
        exhaustion_rows = (
            exhaustion_row_html("فرسودگی روند", trend_ex) +
            exhaustion_row_html("فرسودگی انرژی", energy_ex)
        )
        # هشدار ترکیبی «هر دو فرسودگی هم‌زمان بالا» طبق نتیجه‌ی بک‌تست حذف شد
        # (واریانس ۷-۸۸٪ بین کوین‌ها، غیرقابل‌اعتماد). این دو معیار فقط
        # اطلاعاتی نمایش داده می‌شوند و در تصمیم‌گیری اثر ندارند.
        exhaustion_note = ""
        if abs(trend_ex - energy_ex) > 30:
            exhaustion_note = ('<div style="color:#eab308;font-size:12px;margin-top:6px;">'
                                '↕️ این دو معیار با هم اختلاف دارند — شواهد فرسودگی هنوز قطعی نیست</div>')

    confirm_line = ""
    if res.get("confirm_status") == "agree":
        confirm_line = (f'<div style="color:#22c55e;font-size:12px;margin-top:6px;">'
                         f'موافق روند تایم‌فریم {res["confirm_tf_label"]}</div>')
    elif res.get("confirm_status") == "conflict":
        confirm_line = (f'<div style="color:#ef4444;font-size:12px;margin-top:6px;">'
                         f'⚠️ خلاف روند تایم‌فریم {res["confirm_tf_label"]}</div>')

    return (f'<div dir="rtl" style="max-width:480px;margin:10px auto;background:#111827;'
            f'border-radius:12px;padding:14px 18px;color:#e5e7eb;">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">'
            f'<span style="width:10px;height:10px;border-radius:50%;background:{dot};'
            f'display:inline-block;"></span><b style="font-size:15px;">{star_html}{res["symbol"]}</b>'
            f'<span style="font-size:13px;color:#e5e7eb;">'
            f'{format_price(res["price"]) + " USDT" if res.get("price") is not None else "—"}</span>'
            f'<span style="font-size:12px;color:#9ca3af;">— {tf}</span></div>'
            f'{rows}<div style="border-top:1px solid #374151;margin:8px 0;"></div>'
            f'{market_row}{avg_row}'
            f'<div style="border-top:1px solid #374151;margin:8px 0;"></div>'
            f'{exhaustion_rows}{exhaustion_note}'
            f'<div style="text-align:center;margin-top:10px;padding:8px;border-radius:8px;'
            f'background:{signal_bg};color:{signal_color};font-weight:bold;">'
            f'سیگنال نهایی: {res["signal"]}</div>{confirm_line}</div>')


FAVORITES_FILE = "favorites.json"


def load_favorites() -> dict:
    """بارگذاری رمزارزهای منتخبِ ذخیره‌شده از دفعه‌ی قبل (اگر وجود داشته باشد)."""
    if os.path.exists(FAVORITES_FILE):
        try:
            with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"fav1": "", "fav2": "", "fav3": ""}


def save_favorites():
    """ذخیره‌ی خودکار رمزارزهای منتخب، هر بار که یکی از سه فیلد تغییر کند."""
    data = {
        "fav1": st.session_state.get("fav1_input", ""),
        "fav2": st.session_state.get("fav2_input", ""),
        "fav3": st.session_state.get("fav3_input", ""),
    }
    try:
        with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def parse_symbol_list(text: str) -> set:
    """متن ورودی (جدا شده با کاما یا فاصله) را به مجموعه‌ای از نمادهای پایه (بدون USDT) تبدیل می‌کند."""
    if not text:
        return set()
    parts = re.split(r"[,\s/]+", text.strip())
    return {p.upper() for p in parts if p}


def get_stars(symbol: str, fav1: set, fav2: set, fav3: set) -> str:
    """اگر رمزارز در یکی از سه لیست منتخب باشد، تعداد ستاره‌ی متناظر را برمی‌گرداند."""
    base = symbol.split("/")[0].upper()
    if base in fav1:
        return "⭐⭐⭐"
    if base in fav2:
        return "⭐⭐"
    if base in fav3:
        return "⭐"
    return ""


def build_cfg(engine_states: dict, timeframe: str, universe_size: int) -> dict:
    cfg = copy.deepcopy(CONFIG)
    cfg["MAIN_TIMEFRAME"] = timeframe
    cfg["UNIVERSE_SIZE"] = universe_size
    cfg["ENGINES_ENABLED"].update(engine_states)
    return cfg


# ---------------------------------------------------------------------------
# رابط کاربری
# ---------------------------------------------------------------------------
st.title("📊 سیگنال‌یاب رمزارز")
st.caption("موتورها را روشن/خاموش کنید، تایم‌فریم را انتخاب کنید، و سیگنال بگیرید.")

st.subheader("⚙️ تنظیمات")
cols = st.columns(5)
engine_states = {}
for i, (k, label) in enumerate(ENGINE_LABELS_LOCAL.items()):
    with cols[i]:
        engine_states[k] = st.checkbox(label, value=True, key=f"engine_{k}")

tf_display = st.selectbox("تایم‌فریم اصلی", options=list(TF_OPTIONS.keys()), index=3)  # پیش‌فرض: روزانه

st.markdown("بازه‌ی رتبه‌ی مارکت‌کپ رمزارزها (حداکثر ۷۰۰) ")
rank_cols = st.columns(2)
with rank_cols[0]:
    universe_start = st.number_input("از رتبه‌ی", min_value=1, max_value=700, value=1, step=1)
with rank_cols[1]:
    universe_end = st.number_input("تا رتبه‌ی", min_value=1, max_value=700, value=50, step=1)

signal_filter = st.radio(
    "کدام سیگنال‌ها نمایش داده شوند؟",
    options=["هر دو (خرید و فروش)", "فقط خرید", "فقط فروش"],
    index=0, horizontal=True,
)

st.markdown("رمزارزهای منتخب (اختیاری) — اگر سیگنال بگیرند، کنار نامشان ستاره‌ی طلایی نمایش داده می‌شود؛ "
            "این‌ها به‌صورت خودکار ذخیره می‌شوند")
_saved_favs = load_favorites()
fav_cols = st.columns(3)
with fav_cols[0]:
    fav1_text = st.text_input("منتخب ۱ (⭐⭐⭐)", value=_saved_favs.get("fav1", ""),
                               placeholder="مثلاً: BTC, ETH", key="fav1_input", on_change=save_favorites)
with fav_cols[1]:
    fav2_text = st.text_input("منتخب ۲ (⭐⭐)", value=_saved_favs.get("fav2", ""),
                               placeholder="مثلاً: SOL, XRP", key="fav2_input", on_change=save_favorites)
with fav_cols[2]:
    fav3_text = st.text_input("منتخب ۳ (⭐)", value=_saved_favs.get("fav3", ""),
                               placeholder="مثلاً: DOGE, ADA", key="fav3_input", on_change=save_favorites)

run = st.button("🚀 دریافت سیگنال", use_container_width=True, type="primary")

if run:
    if universe_end < universe_start:
        st.error("رتبه‌ی «تا» باید بزرگ‌تر یا مساوی رتبه‌ی «از» باشد.")
        st.stop()

    fav1 = parse_symbol_list(fav1_text)
    fav2 = parse_symbol_list(fav2_text)
    fav3 = parse_symbol_list(fav3_text)

    cfg = build_cfg(engine_states, TF_OPTIONS[tf_display], universe_end - universe_start + 1)
    cfg["UNIVERSE_START"] = universe_start
    cfg["UNIVERSE_END"] = universe_end
    with st.spinner("در حال دریافت داده و تحلیل، چند لحظه صبر کنید..."):
        exchange = build_exchange(cfg["EXCHANGE_ID"])
        universe = get_universe(cfg)
        results = []
        progress = st.progress(0.0)
        for i, symbol in enumerate(universe):
            res = analyze_symbol(exchange, symbol, cfg)
            if res:
                results.append(res)
            progress.progress((i + 1) / len(universe))
        progress.empty()

    results.sort(key=lambda r: r["weighted_score"], reverse=True)
    found = [r for r in results if r["signal"]]
    buys = [r for r in found if r["signal"] == "خرید"]
    sells = [r for r in found if r["signal"] == "فروش"]

    show_buys = signal_filter in ("هر دو (خرید و فروش)", "فقط خرید")
    show_sells = signal_filter in ("هر دو (خرید و فروش)", "فقط فروش")
    display_buys = buys if show_buys else []
    display_sells = sells if show_sells else []

    st.markdown(f"### 📊 خلاصه: از رتبه‌ی {universe_start} تا {universe_end} مارکت‌کپ، "
                f"{len(buys)} سیگنال خرید و {len(sells)} سیگنال فروش پیدا شد.")

    if not display_buys and not display_sells:
        st.info("با توجه به فیلتر انتخابی، در حال حاضر سیگنال قطعی‌ای برای نمایش وجود ندارد.")
        if results:
            st.markdown("نزدیک‌ترین موارد به آستانه:")

            def _dist(r):
                return min(BUY_THRESHOLD - r["weighted_score"], r["weighted_score"] - SELL_THRESHOLD)

            near = sorted(results, key=_dist)[:5]
            for r in near:
                st.markdown(f"- {r['symbol']} — میانگین: {r['weighted_score']}")
    else:
        if display_buys:
            st.markdown("## 🟢 سیگنال‌های خرید")
            for r in display_buys:
                st.markdown(render_result_html(r, cfg, stars=get_stars(r["symbol"], fav1, fav2, fav3)), unsafe_allow_html=True)
        if display_sells:
            st.markdown("## 🔴 سیگنال‌های فروش")
            for r in display_sells:
                st.markdown(render_result_html(r, cfg, stars=get_stars(r["symbol"], fav1, fav2, fav3)), unsafe_allow_html=True)
