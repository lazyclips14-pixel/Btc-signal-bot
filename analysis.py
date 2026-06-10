import requests
import pandas as pd
import numpy as np

KRAKEN_BASE = "https://api.kraken.com/0/public"

PAIRS = {
    "btc": "XBTUSD",
    "eth": "ETHUSD",
    "sol": "SOLUSD",
    "xrp": "XRPUSD",
    "doge": "DOGEUSD",
}

TIMEFRAMES = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
}


def fetch_ohlc(coin="btc", timeframe="5m", limit=100):
    pair = PAIRS[coin]
    interval = TIMEFRAMES[timeframe]
    url = f"{KRAKEN_BASE}/OHLC"
    params = {"pair": pair, "interval": interval}
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise Exception(f"Kraken API error: {data['error']}")
    pair_key = [k for k in data["result"].keys() if k != "last"][0]
    ohlc = data["result"][pair_key]
    df = pd.DataFrame(ohlc, columns=[
        "time", "open", "high", "low", "close", "vwap", "volume", "count"
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["time"] = df["time"].astype(int)
    return df.tail(limit).reset_index(drop=True)


def get_current_price(coin="btc"):
    pair = PAIRS[coin]
    url = f"{KRAKEN_BASE}/Ticker"
    params = {"pair": pair}
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise Exception(f"Kraken API error: {data['error']}")
    pair_key = list(data["result"].keys())[0]
    ticker = data["result"][pair_key]
    price = float(ticker["c"][0])
    open_price = float(ticker["o"])
    change = ((price - open_price) / open_price) * 100
    return price, change


def get_price_at(coin, timeframe, target_time):
    """Find the close price of the candle at or after target_time."""
    df = fetch_ohlc(coin, timeframe, limit=200)
    matured = df[df["time"] >= target_time]
    if matured.empty:
        return None
    return matured.iloc[0]["close"]


def calculate_rsi(prices, period=14):
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(prices, fast=12, slow=26, signal=9):
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(prices, period=20, std_dev=2):
    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return upper, sma, lower


def get_prediction(coin="btc", timeframe="5m") -> dict:
    df = fetch_ohlc(coin, timeframe, limit=100)
    prices = df["close"]
    volume = df["volume"]

    rsi_series = calculate_rsi(prices)
    rsi = rsi_series.iloc[-1]

    if rsi < 30:
        rsi_signal = "Oversold — bullish"
        rsi_score = 2
    elif rsi < 45:
        rsi_signal = "Slightly oversold — mild bullish"
        rsi_score = 1
    elif rsi > 70:
        rsi_signal = "Overbought — bearish"
        rsi_score = -2
    elif rsi > 55:
        rsi_signal = "Slightly overbought — mild bearish"
        rsi_score = -1
    else:
        rsi_signal = "Neutral"
        rsi_score = 0

    macd_line, signal_line, histogram = calculate_macd(prices)
    macd_val = macd_line.iloc[-1]
    signal_val = signal_line.iloc[-1]
    hist_val = histogram.iloc[-1]
    prev_hist = histogram.iloc[-2]

    if macd_val > signal_val and hist_val > prev_hist:
        macd_signal = "Bullish crossover strengthening"
        macd_score = 2
    elif macd_val > signal_val:
        macd_signal = "Bullish — above signal line"
        macd_score = 1
    elif macd_val < signal_val and hist_val < prev_hist:
        macd_signal = "Bearish crossover strengthening"
        macd_score = -2
    elif macd_val < signal_val:
        macd_signal = "Bearish — below signal line"
        macd_score = -1
    else:
        macd_signal = "Neutral"
        macd_score = 0

    upper, mid, lower = calculate_bollinger_bands(prices)
    current_price = prices.iloc[-1]

    if current_price <= lower.iloc[-1]:
        bb_signal = "Price at lower band — possible bounce UP"
        bb_score = 2
    elif current_price >= upper.iloc[-1]:
        bb_signal = "Price at upper band — possible reversal DOWN"
        bb_score = -2
    elif current_price < mid.iloc[-1]:
        bb_signal = "Price below midline — mild bearish"
        bb_score = -1
    elif current_price > mid.iloc[-1]:
        bb_signal = "Price above midline — mild bullish"
        bb_score = 1
    else:
        bb_signal = "Price near midline — neutral"
        bb_score = 0

    avg_volume = volume.rolling(20).mean().iloc[-1]
    current_volume = volume.iloc[-1]
    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

    if volume_ratio > 1.5:
        volume_signal = f"High volume ({volume_ratio:.1f}x avg) — strong move likely"
        volume_multiplier = 1.2
    elif volume_ratio > 1.0:
        volume_signal = f"Above average volume ({volume_ratio:.1f}x) — moderate conviction"
        volume_multiplier = 1.0
    else:
        volume_signal = f"Low volume ({volume_ratio:.1f}x avg) — weak signal"
        volume_multiplier = 0.8

    total_score = (rsi_score + macd_score + bb_score) * volume_multiplier
    max_possible = 6 * 1.2

    direction = "UP" if total_score >= 0 else "DOWN"

    raw_confidence = abs(total_score) / max_possible
    confidence = int(50 + (raw_confidence * 45))
    confidence = min(95, max(50, confidence))

    bullish = sum(1 for s in [rsi_score, macd_score, bb_score] if s > 0)
    bearish = sum(1 for s in [rsi_score, macd_score, bb_score] if s < 0)

    if direction == "UP":
        reasoning = f"{bullish}/3 indicators bullish at ${current_price:,.2f}."
    else:
        reasoning = f"{bearish}/3 indicators bearish at ${current_price:,.2f}."

    return {
        "direction": direction,
        "confidence": confidence,
        "rsi": rsi,
        "rsi_signal": rsi_signal,
        "macd_signal": macd_signal,
        "bb_signal": bb_signal,
        "volume_signal": volume_signal,
        "reasoning": reasoning,
        "current_price": current_price,
    }
