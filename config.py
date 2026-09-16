"""
AI TRADER — CONFIGURATION
Centralized configuration for the trading system.

Version: 1.0
Environment: Alpaca Paper Trading
"""

import os


# ============================================================
# SYSTEM
# ============================================================

BOT_NAME = "AI TRADER"
BOT_VERSION = "V3 GOD MODE"

# Paper trading ONLY
PAPER_TRADING = True

# Benchmark
BENCHMARK_SYMBOL = "SPY"


# ============================================================
# ALPACA
# ============================================================

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

# IEX is suitable for the current paper setup.
DATA_FEED = "iex"


# ============================================================
# UNIVERSE
# ============================================================

SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "AVGO",
    "AMD",
    "NFLX",
    "JPM",
    "V",
    "MA",
    "COST",
    "WMT",
    "HD",
    "ORCL",
    "CRM",
    "ADBE",
    "INTC",
    "QCOM",
    "MU",
    "AMAT",
    "SPY",
    "QQQ",
]


# ============================================================
# MARKET DATA
# ============================================================

LOOKBACK_DAYS = 120
MIN_BARS = 40

SMA_PERIOD = 20
EMA_PERIOD = 20
RSI_PERIOD = 14
ATR_PERIOD = 14

AVERAGE_VOLUME_PERIOD = 20
RELATIVE_STRENGTH_PERIOD = 20


# ============================================================
# SIGNAL ENGINE
# ============================================================

# Minimum score required before considering an entry.
MIN_SCORE = 70

# RSI entry range.
RSI_MIN = 45
RSI_MAX = 68

# Required relative strength versus benchmark.
REQUIRE_POSITIVE_RELATIVE_STRENGTH = True

# Require sufficient trading volume.
REQUIRE_VOLUME_CONFIRMATION = True


# ============================================================
# SCORE WEIGHTS
# ============================================================

TREND_SCORE_MAX = 30
RSI_SCORE_MAX = 15
MOMENTUM_SCORE_MAX = 15
VOLUME_SCORE_MAX = 10
RELATIVE_STRENGTH_SCORE_MAX = 10
VOLATILITY_SCORE_MAX = 10

MAX_SIGNAL_SCORE = (
    TREND_SCORE_MAX
    + RSI_SCORE_MAX
    + MOMENTUM_SCORE_MAX
    + VOLUME_SCORE_MAX
    + RELATIVE_STRENGTH_SCORE_MAX
    + VOLATILITY_SCORE_MAX
)


# ============================================================
# POSITION / TRADE LIMITS
# ============================================================

MAX_TRADES_PER_DAY = 5
MAX_OPEN_POSITIONS = 5

# Maximum percentage of account equity in one position.
MAX_POSITION_VALUE = 0.20

# Maximum total portfolio exposure.
MAX_TOTAL_EXPOSURE = 0.70

# Maximum exposure to a single symbol.
MAX_SYMBOL_EXPOSURE = 0.20


# ============================================================
# RISK MANAGEMENT
# ============================================================

# Maximum account risk allocated to one new trade.
MAX_RISK_PER_TRADE = 0.01

# Maximum combined portfolio risk.
MAX_PORTFOLIO_RISK = 0.03

# Maximum daily loss before trading is halted.
MAX_DAILY_LOSS = 0.03

# Minimum account value required to operate.
MIN_ACCOUNT_VALUE = 100.0


# ============================================================
# STOP LOSS
# ============================================================

ATR_STOP_MULTIPLIER = 2.0

MIN_STOP_DISTANCE_PCT = 0.005
MAX_STOP_DISTANCE_PCT = 0.10


# ============================================================
# ENTRY CONTROL
# ============================================================

# Maximum new entries allowed during one scanner cycle.
MAX_NEW_ENTRIES_PER_CYCLE = 2

# Never enter a symbol already held.
BLOCK_EXISTING_POSITIONS = True

# Never enter a symbol with an existing open order.
BLOCK_OPEN_ORDERS = True


# ============================================================
# TRADE MANAGEMENT
# ============================================================

TRAILING_ENABLED = True

TRAILING_ACTIVATION_PCT = 0.015
TRAILING_ATR_MULTIPLIER = 2.2

MIN_PROFIT_PCT = 0.003
MAX_TRAILING_DISTANCE_PCT = 0.08


# ============================================================
# PROFIT PROTECTION
# ============================================================

PROFIT_PROTECTION_ENABLED = True

PROFIT_PROTECTION_TRIGGER_PCT = 0.025
PROFIT_PROTECTION_PCT = 0.008


# ============================================================
# SIGNAL EXIT
# ============================================================

EXIT_RSI = 42

EXIT_BELOW_EMA = True
EXIT_BELOW_SMA = False

EMA_EXIT_PERIOD = 20
SMA_EXIT_PERIOD = 20


# ============================================================
# TIME-BASED EXIT
# ============================================================

MAX_HOLDING_DAYS = 15
MIN_PROFIT_TO_IGNORE_TIME_EXIT = 0.01


# ============================================================
# EMERGENCY PROTECTION
# ============================================================

EMERGENCY_LOSS_PCT = -0.10


# ============================================================
# KILL SWITCH
# ============================================================

KILL_SWITCH_ENABLED = True

# Number of consecutive API errors before emergency halt.
MAX_CONSECUTIVE_API_ERRORS = 5

# Number of consecutive data failures before emergency halt.
MAX_CONSECUTIVE_DATA_ERRORS = 3

# Maximum allowed portfolio exposure before emergency halt.
KILL_SWITCH_MAX_EXPOSURE = 0.90

# Halt if an existing position has no protective stop.
KILL_SWITCH_ON_UNPROTECTED_POSITION = True


# ============================================================
# EXECUTION
# ============================================================

ORDER_TIMEOUT_SECONDS = 30

ORDER_CHECK_INTERVAL_SECONDS = 2

# Small delay after cancelling protective orders before
# submitting an emergency market exit.
EXIT_CANCEL_DELAY_SECONDS = 0.5


# ============================================================
# DATABASE
# ============================================================

DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    "trade_history.db"
)


# ============================================================
# LOGGING
# ============================================================

LOG_LEVEL = os.getenv(
    "LOG_LEVEL",
    "INFO"
)


# ============================================================
# SAFETY
# ============================================================

# HARD SAFETY LOCK:
# The system must never use live trading accidentally.
if not PAPER_TRADING:
    raise RuntimeError(
        "LIVE TRADING IS DISABLED. "
        "PAPER_TRADING must remain True during development."
    )


# ============================================================
# STARTUP SUMMARY
# ============================================================

def print_config_summary():
    """Print a safe configuration summary without exposing API keys."""

    print("=" * 60)
    print("AI TRADER — CONFIGURATION")
    print("=" * 60)

    print(f"Version:              {BOT_VERSION}")
    print(f"Paper Trading:        {PAPER_TRADING}")
    print(f"Benchmark:            {BENCHMARK_SYMBOL}")

    print()
    print("RISK")
    print(f"Risk / trade:         {MAX_RISK_PER_TRADE:.2%}")
    print(f"Portfolio risk:       {MAX_PORTFOLIO_RISK:.2%}")
    print(f"Daily loss limit:     {MAX_DAILY_LOSS:.2%}")
    print(f"Max positions:        {MAX_OPEN_POSITIONS}")
    print(f"Max total exposure:   {MAX_TOTAL_EXPOSURE:.2%}")
    print(f"Max symbol exposure:  {MAX_SYMBOL_EXPOSURE:.2%}")

    print()
    print("SIGNAL")
    print(f"Minimum score:        {MIN_SCORE}/{MAX_SIGNAL_SCORE}")
    print(f"RSI range:            {RSI_MIN} - {RSI_MAX}")

    print()
    print("TRADE MANAGEMENT")
    print(f"Trailing enabled:     {TRAILING_ENABLED}")
    print(f"Trailing activation:  {TRAILING_ACTIVATION_PCT:.2%}")
    print(f"Profit protection:    {PROFIT_PROTECTION_ENABLED}")

    print()
    print("SAFETY")
    print(f"Kill switch:          {KILL_SWITCH_ENABLED}")
    print(f"Database:             {DATABASE_PATH}")

    print("=" * 60)
