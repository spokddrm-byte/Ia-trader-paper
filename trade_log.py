import json
import os
from datetime import datetime, timezone


LOG_FILE = "trade_history.json"


def load_history():
    if not os.path.exists(LOG_FILE):
        return []

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return []


def save_history(history):
    with open(LOG_FILE, "w", encoding="utf-8") as file:
        json.dump(history, file, indent=4, ensure_ascii=False)


def log_event(
    symbol,
    signal,
    entry_price,
    stop_price,
    position_size,
    status,
    profit_loss=0.0
):
    history = load_history()

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "signal": signal,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "position_size": position_size,
        "status": status,
        "profit_loss": profit_loss
    }

    history.append(event)
    save_history(history)

    return event


def get_today_events():
    history = load_history()

    today = datetime.now(timezone.utc).date()

    return [
        event
        for event in history
        if event.get("timestamp", "")[:10] == str(today)
    ]


def get_today_trade_count():
    events = get_today_events()

    return sum(
        1
        for event in events
        if event.get("status") == "EXECUTED"
    )


def get_today_loss():
    events = get_today_events()

    total_loss = 0.0

    for event in events:
        profit_loss = float(event.get("profit_loss", 0))

        if profit_loss < 0:
            total_loss += abs(profit_loss)

    return total_loss


if __name__ == "__main__":
    print("=== AI TRADER - TRADE LOG ===")

    event = log_event(
        symbol="AAPL",
        signal="COMPRAR",
        entry_price=333.00,
        stop_price=323.01,
        position_size=100,
        status="TEST",
        profit_loss=0.0
    )

    print("Evento registrado:")
    print(event)

    print()
    print(f"Eventos de hoy: {len(get_today_events())}")
    print(f"Operaciones ejecutadas hoy: {get_today_trade_count()}")
    print(f"Perdida de hoy: ${get_today_loss():.2f}")
