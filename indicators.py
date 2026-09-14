import math


def sma(values, period):
    if len(values) < period:
        return None

    return sum(values[-period:]) / period


def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    average = sum(values[:period]) / period

    for price in values[period:]:
        average = ((price - average) * multiplier) + average

    return average


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        average_gain = (
            (average_gain * (period - 1)) + gains[i]
        ) / period

        average_loss = (
            (average_loss * (period - 1)) + losses[i]
        ) / period

    if average_loss == 0:
        return 100

    relative_strength = average_gain / average_loss

    return 100 - (100 / (1 + relative_strength))


def volatility(values, period=20):
    if len(values) < period:
        return None

    recent = values[-period:]
    average = sum(recent) / period

    variance = sum(
        (price - average) ** 2
        for price in recent
    ) / period

    return math.sqrt(variance)


if __name__ == "__main__":
    print("=== AI TRADER — INDICATORS ===")

    prices = [
        300, 301, 299, 302, 304,
        303, 305, 307, 306, 309,
        311, 310, 313, 315, 314,
        316, 318, 317, 319, 320
    ]

    print(f"SMA 20: {sma(prices, 20):.2f}")
    print(f"EMA 20: {ema(prices, 20):.2f}")
    print(f"RSI 14: {rsi(prices, 14):.2f}")
    print(f"Volatilidad 20: {volatility(prices, 20):.4f}")
