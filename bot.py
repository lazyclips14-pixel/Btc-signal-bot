import logging
import os
import json
import time as time_module
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from analysis import get_prediction, get_current_price, get_price_at, fetch_ohlc, PAIRS, TIMEFRAMES

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")

LOG_FILE = "predictions.json"
TIMEFRAME_SECONDS = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}


def load_log():
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_log(log):
    with open(LOG_FILE, "w") as f:
        json.dump(log, f)


def grade_prediction(p):
    """Returns (actual_direction, final_price) or (None, None) if still pending."""
    now = int(time_module.time())
    matures_at = p["time"] + TIMEFRAME_SECONDS[p["timeframe"]]
    if now < matures_at:
        return None, None
    final_price = get_price_at(p["coin"], p["timeframe"], matures_at)
    if final_price is None:
        return None, None
    actual = "UP" if final_price >= p["price"] else "DOWN"
    return actual, final_price


def fmt_time(ts):
    return datetime.utcfromtimestamp(ts).strftime("%b %d, %H:%M UTC")


def get_recent_candles(coin, timeframe, count=5):
    """Return the last `count` completed candle results for a coin/timeframe."""
    df = fetch_ohlc(coin, timeframe, limit=count + 1)
    candles = []
    for _, row in df.iloc[:-1].tail(count).iterrows():
        change = ((row["close"] - row["open"]) / row["open"]) * 100
        direction = "UP" if change >= 0 else "DOWN"
        emoji = "🟢" if change >= 0 else "🔴"
        candles.append(f"{emoji} {direction} {change:+.2f}%")
    return candles


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to Crypto Signal Bot\n\n"
        "📌 Commands:\n"
        "/predict btc 15m — prediction for a coin + timeframe\n"
        "/history eth 5m — what the market recently did\n"
        "/price eth — current price\n"
        "/coins — supported coins and timeframes\n"
        "/score — my accuracy history\n"
        "/score btc — accuracy for one coin\n"
        "/help — full guide"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Crypto Signal Bot Guide*\n\n"
        "*/predict <coin> <timeframe>*\n"
        "Example: /predict eth 15m\n"
        "Shows the market's recent candles + my last call for that coin first.\n\n"
        "*/history <coin> <timeframe>* — last 10 candle results\n"
        "*/price <coin>* — live price\n"
        "*/coins* — coins + timeframes\n"
        "*/score* — my track record with dates\n"
        "*/score <coin>* — record for one coin\n\n"
        "⚠️ Short-term signals are weak predictors. Judge me by /score. Not financial advice.",
        parse_mode="Markdown"
    )


async def coins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coins = ", ".join(c.upper() for c in PAIRS.keys())
    tfs = ", ".join(TIMEFRAMES.keys())
    await update.message.reply_text(
        f"🪙 *Coins:* {coins}\n⏱ *Timeframes:* {tfs}\n\nExample: /predict sol 1h",
        parse_mode="Markdown"
    )


async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coin = context.args[0].lower() if context.args else "btc"
    if coin not in PAIRS:
        await update.message.reply_text("Unknown coin. Use /coins to see the list.")
        return
    await update.message.reply_text(f"⏳ Fetching {coin.upper()} price...")
    try:
        price, change = get_current_price(coin)
        direction = "🟢" if change >= 0 else "🔴"
        await update.message.reply_text(
            f"*{coin.upper()}/USD*\n\nPrice: `${price:,.4f}`\n"
            f"{direction} 24h: `{change:+.2f}%`\n\n"
            f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coin = "btc"
    timeframe = "5m"
    if context.args:
        for arg in context.args:
            a = arg.lower()
            if a in PAIRS:
                coin = a
            elif a in TIMEFRAMES:
                timeframe = a
    try:
        candles = get_recent_candles(coin, timeframe, count=10)
        lines = "\n".join(f"{i+1}. {c}" for i, c in enumerate(candles))
        await update.message.reply_text(
            f"📊 *{coin.upper()} — last 10 × {timeframe} candles (oldest first):*\n\n{lines}",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def predict_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coin = "btc"
    timeframe = "5m"
    if context.args:
        for arg in context.args:
            a = arg.lower()
            if a in PAIRS:
                coin = a
            elif a in TIMEFRAMES:
                timeframe = a

    log = load_log()

    # Market's recent behaviour on this timeframe
    try:
        candles = get_recent_candles(coin, timeframe, count=5)
        await update.message.reply_text(
            f"📊 *{coin.upper()} last 5 × {timeframe} candles:*\n" + " | ".join(candles),
            parse_mode="Markdown"
        )
    except Exception:
        pass

    # My last call for this coin
    previous = [p for p in log if p["coin"] == coin]
    if previous:
        last = previous[-1]
        actual, final_price = grade_prediction(last)
        if actual is not None:
            hit = actual == last["direction"]
            mark = "✅ I was right" if hit else "❌ I was wrong"
            await update.message.reply_text(
                f"📒 *Last {coin.upper()} call ({fmt_time(last['time'])}):*\n"
                f"I said {last['direction']} on {last['timeframe']}, "
                f"it went {actual}. {mark}.\n"
                f"(${last['price']:,.2f} → ${final_price:,.2f})",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"📒 Last {coin.upper()} call ({fmt_time(last['time'])}) is still pending."
            )

    await update.message.reply_text(
        f"🔍 Analysing *{coin.upper()}* on the *{timeframe}* timeframe...",
        parse_mode="Markdown"
    )

    try:
        result = get_prediction(coin, timeframe)
        emoji = "📈" if result["direction"] == "UP" else "📉"
        bar = "█" * int(result["confidence"] / 10) + "░" * (10 - int(result["confidence"] / 10))

        log.append({
            "coin": coin,
            "timeframe": timeframe,
            "direction": result["direction"],
            "price": result["current_price"],
            "time": int(time_module.time()),
        })
        save_log(log)

        message = (
            f"{emoji} *{coin.upper()} — next {timeframe}*\n\n"
            f"Signal: *{result['direction']}*\n"
            f"Confidence: `{bar}` {result['confidence']}%\n\n"
            f"📊 *Breakdown:*\n"
            f"• RSI ({result['rsi']:.1f}): {result['rsi_signal']}\n"
            f"• MACD: {result['macd_signal']}\n"
            f"• Bollinger: {result['bb_signal']}\n"
            f"• Volume: {result['volume_signal']}\n\n"
            f"💡 {result['reasoning']}\n\n"
            f"📒 Logged at {fmt_time(int(time_module.time()))}. Check /score after {timeframe}.\n"
            f"⚠️ Not financial advice."
        )
        await update.message.reply_text(message, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log = load_log()
    if not log:
        await update.message.reply_text("No predictions logged yet. Make some with /predict first.")
        return

    coin_filter = None
    if context.args and context.args[0].lower() in PAIRS:
        coin_filter = context.args[0].lower()
        log = [p for p in log if p["coin"] == coin_filter]
        if not log:
            await update.message.reply_text(f"No predictions logged for {coin_filter.upper()} yet.")
            return

    await update.message.reply_text("⏳ Grading predictions...")

    try:
        per_coin = {}
        lines = []
        pending = 0

        for p in log[-50:]:
            actual, final_price = grade_prediction(p)
            if actual is None:
                pending += 1
                continue
            hit = actual == p["direction"]
            c = p["coin"]
            if c not in per_coin:
                per_coin[c] = {"correct": 0, "wrong": 0}
            if hit:
                per_coin[c]["correct"] += 1
            else:
                per_coin[c]["wrong"] += 1
            mark = "✅" if hit else "❌"
            lines.append(
                f"{mark} [{fmt_time(p['time'])}] {p['coin'].upper()} {p['timeframe']}: "
                f"said {p['direction']}, went {actual}"
            )

        total_correct = sum(v["correct"] for v in per_coin.values())
        total_wrong = sum(v["wrong"] for v in per_coin.values())
        total = total_correct + total_wrong

        if total == 0:
            await update.message.reply_text(
                f"All {pending} prediction(s) still pending. Check back later."
            )
            return

        accuracy = (total_correct / total) * 100

        coin_lines = []
        for c, v in per_coin.items():
            t = v["correct"] + v["wrong"]
            acc = (v["correct"] / t) * 100
            coin_lines.append(f"• {c.upper()}: {acc:.0f}% ({v['correct']}/{t})")

        title = f"{coin_filter.upper()} Track Record" if coin_filter else "Full Track Record"
        recent = "\n".join(lines[-12:])

        await update.message.reply_text(
            f"📒 *{title}*\n\n"
            f"*Overall: {accuracy:.1f}%* ({total_correct}/{total} graded, {pending} pending)\n\n"
            f"*Per coin:*\n" + "\n".join(coin_lines) + "\n\n"
            f"*Recent:*\n{recent}\n\n"
            f"💭 A coin flip scores 50%. Judge me honestly.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error grading: {str(e)}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Try /predict btc 15m or /coins to see options.")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("coins", coins_command))
    app.add_handler(CommandHandler("price", price_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("predict", predict_command))
    app.add_handler(CommandHandler("score", score_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
