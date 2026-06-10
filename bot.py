import logging
import os
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from analysis import get_prediction, get_current_price

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to BTC Signal Bot\n\n"
        "Send me a time and I'll analyse the market and give you an UP or DOWN prediction.\n\n"
        "📌 Format examples:\n"
        "• /predict 3:45 PM\n"
        "• /predict 15:45\n"
        "• /predict now\n\n"
        "Use /help for more info."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use BTC Signal Bot*\n\n"
        "*Commands:*\n"
        "/predict <time> — Get UP/DOWN prediction\n"
        "/predict now — Analyse current market immediately\n"
        "/price — Get current BTC price\n\n"
        "*How it works:*\n"
        "The bot pulls live BTC/USDT data and analyses:\n"
        "• RSI (momentum)\n"
        "• MACD (trend direction)\n"
        "• Bollinger Bands (volatility)\n"
        "• Volume (market strength)\n\n"
        "⚠️ *Disclaimer:* Technical indicators only. Not financial advice.",
        parse_mode="Markdown"
    )


async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching current BTC price...")
    try:
        price, change = get_current_price()
        direction = "🟢" if change >= 0 else "🔴"
        await update.message.reply_text(
            f"₿ *BTC/USDT Current Price*\n\n"
            f"Price: `${price:,.2f}`\n"
            f"{direction} 24h Change: `{change:+.2f}%`\n\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error fetching price: {str(e)}")


async def predict_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Please provide a time.\n\nExample: /predict now\nOr: /predict 3:45 PM"
        )
        return

    time_input = " ".join(context.args).strip()
    await update.message.reply_text(f"🔍 Analysing BTC market for *{time_input}*...", parse_mode="Markdown")

    try:
        result = get_prediction(time_input)
        direction_emoji = "📈" if result["direction"] == "UP" else "📉"
        confidence_bar = "█" * int(result["confidence"] / 10) + "░" * (10 - int(result["confidence"] / 10))

        message = (
            f"{direction_emoji} *BTC Prediction — {time_input}*\n\n"
            f"Signal: *{result['direction']}*\n"
            f"Confidence: `{confidence_bar}` {result['confidence']}%\n\n"
            f"📊 *Indicator Breakdown:*\n"
            f"• RSI ({result['rsi']:.1f}): {result['rsi_signal']}\n"
            f"• MACD: {result['macd_signal']}\n"
            f"• Bollinger Bands: {result['bb_signal']}\n"
            f"• Volume: {result['volume_signal']}\n\n"
            f"💡 *Reasoning:* {result['reasoning']}\n\n"
            f"⚠️ Not financial advice. Use at your own risk."
        )

        await update.message.reply_text(message, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Error during analysis: {str(e)}\n\nTry again or use /predict now")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Use /predict <time> to get a prediction.\n\nExample: /predict now"
    )


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("price", price_command))
    app.add_handler(CommandHandler("predict", predict_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
