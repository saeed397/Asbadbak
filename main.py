"""
main.py

اجرای اصلی: اسکن یونیورس (فقط USDT، بدون استیبل‌کوین، با فیلتر حجم مطلق)،
محاسبه‌ی موتورها، امتیاز وزنی 0..100، تأیید با تایم‌فریم بالاتر، اعمال
پروفایل معاملاتی جداگانه برای کوین‌های ناهمسو، و نمایش رنگی میله‌ای در ترمینال.

اجرا:
pip install ccxt requests pandas numpy --break-system-packages
python main.py
"""

from config import load_config, resolve_confirm_timeframe
from data import get_universe, build_exchange, safe_fetch
from engines import (
    trend_engine, derivative_engine, integral_engine,
    energy_engine, funding_engine, regime_engine,
)
from decision import fuse_and_decide, ENGINE_LABELS_FA, IMPORTANCE_WEIGHTS, BUY_THRESHOLD, SELL_THRESHOLD

TF_LABELS_FA = {"30m": "۳۰دقیقه", "1h": "۱ساعته", "4h": "۴ساعته", "1d": "روزانه", "1w": "هفتگی"}

GREEN = "\033[92m"
RED = "\033[91m"
WHITE = "\033[97m"
BLUE = "\033[94m"
GRAY = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"

BAR_WIDTH = 28


def colored_bar(value: float, neutral: bool = False) -> str:
    """
    نوار میله‌ای خالص (بدون هیچ حرف فارسی در همین خط، تا هیچ محیطی جهتش را برعکس نکند).
    پرشدن از چپ به راست: بخش پرشده رنگی، بخش خالی بلوک سفیدِ ضخیم.
    """
    filled = max(0, min(BAR_WIDTH, round(value / 100 * BAR_WIDTH)))
    color = BLUE if neutral else (GREEN if value >= 50 else RED)
    filled_part = f"{color}{'█' * filled}{RESET}"
    empty_part = f"{WHITE}{'█' * (BAR_WIDTH - filled)}{RESET}"
    return f" {filled_part}{empty_part} {value}"


def analyze_symbol(exchange, symbol: str, cfg: dict):
    df_main = safe_fetch(exchange, symbol, cfg["MAIN_TIMEFRAME"], cfg["CANDLE_LIMIT"])
    if df_main is None or len(df_main) < 60:
        return None

    enabled = cfg.get("ENGINES_ENABLED", {})
    outputs = {
        "trend": trend_engine(df_main, cfg["EMA_PERIODS"]) if enabled.get("trend", True) else
            {"trend_score": 0.0, "trend_quality": 0.0, "trend_direction": 0.0, "trend_exhaustion": 0.0},
        "derivative": derivative_engine(df_main, cfg["SCALES"]) if enabled.get("derivative", True) else
            {"derivative_score": 0.5, "derivative_acceleration": 0.5, "derivative_alignment": 0.0, "derivative_conflict": 0.0, "raw": {}},
        "integral": integral_engine(df_main, cfg["SCALES"]) if enabled.get("integral", True) else
            {"integral_memory_score": 0.5, "integral_energy_score": 0.5, "integral_persistence": 0.0},
        "energy": energy_engine(df_main) if enabled.get("energy", True) else
            {"energy_score": 0.5, "energy_growth": 0.0, "energy_exhaustion": 0.0},
        "funding": funding_engine(exchange, symbol) if enabled.get("funding", True) else
            {"funding_score": 0.0, "funding_rate": None, "open_interest": None, "available": False},
        "regime": regime_engine(df_main) if enabled.get("regime", True) else
            {"regime": "ranging", "adx": 0.0, "noise_score": 0.5},
    }

    result = fuse_and_decide(outputs, cfg, symbol=symbol)
    result["trend_exhaustion"] = round(outputs["trend"]["trend_exhaustion"] * 100, 1)
    result["energy_exhaustion"] = round(outputs["energy"]["energy_exhaustion"] * 100, 1)
    result["symbol"] = symbol
    result["price"] = float(df_main["close"].iloc[-1])

    # ---------- تأیید با تایم‌فریم بالاتر (فقط برای سیگنال‌های قطعی، بدون منطقه‌ی خنثی) ----------
    result["confirm_status"] = None
    result["confirm_tf_label"] = None
    if result["signal"]:
        confirm_tf = resolve_confirm_timeframe(cfg["MAIN_TIMEFRAME"], cfg)
        if confirm_tf:
            df_confirm = safe_fetch(exchange, symbol, confirm_tf, cfg["CANDLE_LIMIT"])
            if df_confirm is not None and len(df_confirm) >= 60:
                confirm_trend = trend_engine(df_confirm, cfg["EMA_PERIODS"])["trend_score"]
                confirm_direction = "up" if confirm_trend >= 0 else "down"
                result["confirm_tf_label"] = TF_LABELS_FA.get(confirm_tf, confirm_tf)
                if result["signal"] == "خرید":
                    result["confirm_status"] = "agree" if confirm_direction == "up" else "conflict"
                elif result["signal"] == "فروش":
                    result["confirm_status"] = "agree" if confirm_direction == "down" else "conflict"

    # ---------- حذف سیگنال‌های مخالف تایم‌فریم بالاتر (برای همه‌ی کوین‌ها) ----------
    # فقط سیگنال‌هایی که با تایم‌فریم بالاتر «موافق» هستند (یا داده‌ی تأییدی
    # در دسترس نیست) به‌عنوان خروجی نهایی اعلام می‌شوند؛ سیگنال‌های «مخالف»
    # به‌طور کامل حذف می‌شوند، نه فقط با هشدار نمایش داده شوند.
    if result["signal"] and result["confirm_status"] == "conflict":
        result["signal"] = None

    # ---------- پروفایل معاملاتی جداگانه (مثل TRX): علاوه‌بر رد مخالف‌ها، فقط تأیید صریح «موافق» پذیرفته می‌شود ----------
    if result.get("require_confirm_agree") and result["signal"] and result["confirm_status"] != "agree":
        result["signal"] = None

    return result


def print_result(res: dict, cfg: dict):
    tf = TF_LABELS_FA.get(cfg["MAIN_TIMEFRAME"], cfg["MAIN_TIMEFRAME"])
    dot = f"{GREEN}●{RESET}" if res["signal"] == "خرید" else f"{RED}●{RESET}"

    # خط اول: فقط نماد (لاتین) — خط دوم: فقط فارسی. هرکدام تک‌جهته، بدون ابهام.
    print(f"\n{dot} {BOLD}{res['symbol']}{RESET}")
    print(f"  تایم‌فریم: {tf}")

    for key, label in ENGINE_LABELS_FA.items():
        w = IMPORTANCE_WEIGHTS[key]
        value = res["raw_scores_100"][key]
        print(f"{label} {value}")
        print(colored_bar(value).rsplit(" ", 1)[0] + f" (×{w})")

    print(f"{GRAY}{'─' * (BAR_WIDTH + 15)}{RESET}")

    print(f"وضعیت بازار ({res['regime_fa']})")
    print(colored_bar(res["market_strength"], neutral=True))

    print(f"{BOLD}میانگین وزنی{RESET}")
    print(colored_bar(res["weighted_score"]))

    signal_color = GREEN if res["signal"] == "خرید" else RED
    print(f"{signal_color}{BOLD}سیگنال نهایی: {res['signal']}{RESET}")

    if res["confirm_status"] == "conflict":
        print(f"{RED}⚠️ خلاف روند تایم‌فریم {res['confirm_tf_label']}{RESET}")
    elif res["confirm_status"] == "agree":
        print(f"{GREEN}موافق روند تایم‌فریم {res['confirm_tf_label']}{RESET}")


def distance_to_threshold(score: float) -> tuple:
    dist_buy = BUY_THRESHOLD - score
    dist_sell = score - SELL_THRESHOLD
    if dist_buy <= dist_sell:
        return dist_buy, "خرید"
    return dist_sell, "فروش"


def auto_scan_step(cfg: dict, start_pos: int, batch_size: int = 50, max_rank: int = 500):
    """
    جستجوی خودکار پلکانی: از رتبه‌ی start_pos شروع می‌کند، هر بار batch_size
    رمزارز (طبق مارکت‌کپ) را در تایم‌فریم cfg["MAIN_TIMEFRAME"] بررسی می‌کند
    و به محض یافتن اولین سیگنال (خرید یا فروش) متوقف می‌شود.

    خروجی: (نتایج_سیگنال‌دار_این_مرحله، رتبه‌ی شروعِ ادامه‌ی جستجو در دفعه‌ی
    بعد، آیا کل بازه‌ی ۱..max_rank به پایان رسید).

    فراخوان (مثلاً app.py) باید رتبه‌ی بازگشتی را برای دفعه‌ی بعد نگه دارد
    تا با فراخوانی مجدد، جستجو دقیقاً از همان‌جا ادامه یابد.
    """
    exchange = build_exchange(cfg["EXCHANGE_ID"])
    pos = max(1, start_pos)
    if pos > max_rank:
        return [], pos, True

    while pos <= max_rank:
        batch_end = min(pos + batch_size - 1, max_rank)
        batch_cfg = dict(cfg)
        batch_cfg["UNIVERSE_START"] = pos
        batch_cfg["UNIVERSE_END"] = batch_end

        universe = get_universe(batch_cfg)
        found = []
        for symbol in universe:
            res = analyze_symbol(exchange, symbol, batch_cfg)
            if res and res["signal"]:
                found.append(res)

        if found:
            return found, batch_end + 1, batch_end >= max_rank

        pos = batch_end + 1

    return [], pos, True


def run_scan(cfg: dict = None):
    cfg = cfg or load_config()
    exchange = build_exchange(cfg["EXCHANGE_ID"])
    universe = get_universe(cfg)

    results = []
    for symbol in universe:
        res = analyze_symbol(exchange, symbol, cfg)
        if res:
            results.append(res)

    results.sort(key=lambda r: r["weighted_score"], reverse=True)
    return results


if __name__ == "__main__":
    cfg = load_config()
    all_results = run_scan(cfg)
    found = [r for r in all_results if r["signal"]]

    if not found:
        print(f"در حال حاضر هیچ رمزارزی سیگنال قطعی خرید یا فروش "
              f"(بالای {BUY_THRESHOLD} یا زیر {SELL_THRESHOLD}) ندارد.\n")
        if all_results:
            print(f"{BOLD}نزدیک‌ترین موارد به آستانه:{RESET}")
            near = sorted(all_results, key=lambda r: distance_to_threshold(r["weighted_score"])[0])[:5]
            for r in near:
                dist, direction = distance_to_threshold(r["weighted_score"])
                print(f"  {r['symbol']:<12}  میانگین: {r['weighted_score']:<6}  "
                      f"(فاصله تا {direction}: {round(dist, 1)} واحد)")
    else:
        buys = [r for r in found if r["signal"] == "خرید"]
        sells = [r for r in found if r["signal"] == "فروش"]

        print(f"📊 خلاصه: از {cfg['UNIVERSE_SIZE']} رمزارز اول مارکت "
              f"{len(buys)} سیگنال خرید و {len(sells)} سیگنال فروش پیدا شد.")

        if buys:
            print(f"\n{BOLD}========== سیگنال‌های خرید =========={RESET}")
            for r in buys:
                print_result(r, cfg)

        if sells:
            print(f"\n{BOLD}========== سیگنال‌های فروش =========={RESET}")
            for r in sells:
                print_result(r, cfg)
