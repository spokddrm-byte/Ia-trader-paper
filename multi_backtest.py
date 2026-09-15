import os
import math
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed


# ============================================================
# AI TRADER — MULTI BACKTEST V3
# ============================================================
#
# SOLO BACKTEST
# NO ENVÍA ÓRDENES
#
# V3:
# - Datos OHLC
# - Datos ajustados por splits/dividendos
# - Datos ordenados cronológicamente
# - Señal al cierre
# - Entrada al OPEN del día siguiente
# - Stop usando LOW real
# - Slippage
# - Comisiones
# - Position sizing por riesgo
# - Equity curve
# - Drawdown
# - Profit Factor
# - Win Rate
# - CAGR
# - Sharpe
# - Rachas de pérdidas
# - Buy & Hold corregido
# - Exportación a backtest_results.txt
#
# IMPORTANTE:
# NO PAPER ORDERS
# NO LIVE ORDERS
# ============================================================


SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL"
]


PERIODS = {
    "1 AÑO": 365,
    "3 AÑOS": 1095,
    "5 AÑOS": 1825
}


INITIAL_CAPITAL = 100000.0

RISK_PER_TRADE = 0.01

STOP_PERCENT = 0.03

SLIPPAGE_PERCENT = 0.0005

COMMISSION_PER_SHARE = 0.01


# ============================================================
# ALPACA
# ============================================================

api_key = os.environ["ALPACA_API_KEY"]

secret_key = os.environ["ALPACA_SECRET_KEY"]


data_client = StockHistoricalDataClient(
    api_key,
    secret_key
)


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    average = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        average = (
            (price - average)
            * multiplier
        ) + average

    return average


# ============================================================
# RSI
# ============================================================

def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []

    losses = []

    for i in range(1, len(values)):

        change = (
            values[i] -
            values[i - 1]
        )

        if change > 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
            )

    average_gain = (
        sum(gains[:period]) /
        period
    )

    average_loss = (
        sum(losses[:period]) /
        period
    )

    for i in range(
        period,
        len(gains)
    ):

        average_gain = (
            (
                average_gain *
                (period - 1)
            )
            + gains[i]
        ) / period

        average_loss = (
            (
                average_loss *
                (period - 1)
            )
            + losses[i]
        ) / period

    if average_loss == 0:
        return 100.0

    relative_strength = (
        average_gain /
        average_loss
    )

    return 100 - (
        100 /
        (1 + relative_strength)
    )


# ============================================================
# LIMPIAR DATOS
# ============================================================

def clean_bars(symbol_bars):

    data = []

    for bar in symbol_bars:

        timestamp = bar.timestamp

        open_price = float(
            bar.open
        )

        high = float(
            bar.high
        )

        low = float(
            bar.low
        )

        close = float(
            bar.close
        )

        if (
            open_price <= 0
            or high <= 0
            or low <= 0
            or close <= 0
        ):
            continue

        if high < low:
            continue

        data.append(
            (
                timestamp,
                open_price,
                high,
                low,
                close
            )
        )

    data.sort(
        key=lambda item: item[0]
    )

    return data


# ============================================================
# MAX DRAWDOWN
# ============================================================

def calculate_max_drawdown(
    equity_curve
):

    if not equity_curve:

        return 0.0, 0.0

    peak = equity_curve[0]

    max_drawdown = 0.0

    max_drawdown_percent = 0.0

    for equity in equity_curve:

        if equity > peak:

            peak = equity

        if peak <= 0:
            continue

        drawdown = (
            peak -
            equity
        )

        drawdown_percent = (
            drawdown /
            peak
        ) * 100

        if drawdown > max_drawdown:

            max_drawdown = drawdown

        if (
            drawdown_percent >
            max_drawdown_percent
        ):

            max_drawdown_percent = (
                drawdown_percent
            )

    return (
        max_drawdown,
        max_drawdown_percent
    )


# ============================================================
# SHARPE
# ============================================================

def calculate_sharpe(
    equity_curve
):

    if len(equity_curve) < 2:

        return 0.0

    returns = []

    for i in range(
        1,
        len(equity_curve)
    ):

        previous = (
            equity_curve[i - 1]
        )

        current = (
            equity_curve[i]
        )

        if previous <= 0:
            continue

        daily_return = (
            current -
            previous
        ) / previous

        returns.append(
            daily_return
        )

    if len(returns) < 2:

        return 0.0

    average = (
        sum(returns) /
        len(returns)
    )

    variance = sum(
        (
            value -
            average
        ) ** 2
        for value in returns
    ) / (
        len(returns) - 1
    )

    standard_deviation = math.sqrt(
        variance
    )

    if standard_deviation == 0:

        return 0.0

    return (
        average /
        standard_deviation
    ) * math.sqrt(252)


# ============================================================
# Racha máxima de pérdidas
# ============================================================

def calculate_max_losing_streak(
    trades
):

    current = 0

    maximum = 0

    for trade in trades:

        if trade < 0:

            current += 1

            if current > maximum:

                maximum = current

        else:

            current = 0

    return maximum


# ============================================================
# BACKTEST V3
# ============================================================

def run_backtest(data):

    if len(data) < 50:

        return None


    dates = [
        item[0]
        for item in data
    ]

    opens = [
        item[1]
        for item in data
    ]

    highs = [
        item[2]
        for item in data
    ]

    lows = [
        item[3]
        for item in data
    ]

    closes = [
        item[4]
        for item in data
    ]


    capital = INITIAL_CAPITAL

    position = 0

    entry_price = 0.0

    stop_price = 0.0

    trades = []

    equity_curve = []

    wins = 0

    losses = 0

    total_commissions = 0.0

    pending_entry = False


    # ========================================================
    # RECORRIDO HISTÓRICO
    # ========================================================

    for i in range(
        20,
        len(closes) - 1
    ):

        price = closes[i]

        history = closes[:i + 1]


        ema20 = ema(
            history,
            20
        )

        rsi14 = rsi(
            history,
            14
        )


        if (
            ema20 is None
            or rsi14 is None
        ):

            equity_curve.append(
                capital
            )

            continue


        # ====================================================
        # ENTRADA
        #
        # La señal se generó al cierre
        # del día anterior.
        #
        # La entrada ocurre al OPEN
        # de este día.
        # ====================================================

        if (
            position == 0
            and pending_entry
        ):

            entry_execution_price = (
                opens[i] *
                (
                    1 +
                    SLIPPAGE_PERCENT
                )
            )


            stop_distance = (
                entry_execution_price *
                STOP_PERCENT
            )


            risk_amount = (
                capital *
                RISK_PER_TRADE
            )


            shares_by_risk = int(
                risk_amount /
                stop_distance
            )


            shares_by_capital = int(
                capital /
                (
                    entry_execution_price +
                    COMMISSION_PER_SHARE
                )
            )


            shares = min(
                shares_by_risk,
                shares_by_capital
            )


            if shares > 0:

                commission = (
                    shares *
                    COMMISSION_PER_SHARE
                )


                total_cost = (
                    entry_execution_price *
                    shares
                    +
                    commission
                )


                if total_cost <= capital:

                    capital -= (
                        total_cost
                    )

                    position = shares

                    entry_price = (
                        entry_execution_price
                    )

                    stop_price = (
                        entry_price *
                        (
                            1 -
                            STOP_PERCENT
                        )
                    )

                    total_commissions += (
                        commission
                    )


            pending_entry = False


        # ====================================================
        # GESTIÓN DE POSICIÓN
        # ====================================================

        if position > 0:

            exit_reason = None

            execution_price = None


            # ------------------------------------------------
            # STOP
            #
            # Usamos LOW real del día.
            # ------------------------------------------------

            if lows[i] <= stop_price:

                exit_reason = "STOP"

                execution_price = (
                    stop_price *
                    (
                        1 -
                        SLIPPAGE_PERCENT
                    )
                )


            # ------------------------------------------------
            # SALIDA EMA
            # ------------------------------------------------

            elif price < ema20:

                exit_reason = "EMA"

                execution_price = (
                    price *
                    (
                        1 -
                        SLIPPAGE_PERCENT
                    )
                )


            if exit_reason is not None:

                gross_result = (
                    execution_price -
                    entry_price
                ) * position


                commission = (
                    position *
                    COMMISSION_PER_SHARE
                )


                profit_loss = (
                    gross_result -
                    commission
                )


                capital += (
                    execution_price *
                    position
                )


                capital -= commission


                trades.append(
                    profit_loss
                )


                total_commissions += (
                    commission
                )


                if profit_loss >= 0:

                    wins += 1

                else:

                    losses += 1


                position = 0

                entry_price = 0.0

                stop_price = 0.0


        # ====================================================
        # SEÑAL
        #
        # Se calcula al cierre.
        #
        # La ejecución será en el
        # siguiente OPEN.
        # ====================================================

        if (
            position == 0
            and not pending_entry
        ):

            signal = (
                price > ema20
                and rsi14 < 70
            )


            if signal:

                pending_entry = True


        # ====================================================
        # EQUITY
        # ====================================================

        if position > 0:

            unrealized = (
                closes[i] -
                entry_price
            ) * position


            equity = (
                capital
                +
                (
                    entry_price *
                    position
                )
                +
                unrealized
            )

        else:

            equity = capital


        equity_curve.append(
            equity
        )


    # ========================================================
    # CIERRE FINAL
    # ========================================================

    if position > 0:

        final_price = (
            closes[-1] *
            (
                1 -
                SLIPPAGE_PERCENT
            )
        )


        gross_result = (
            final_price -
            entry_price
        ) * position


        commission = (
            position *
            COMMISSION_PER_SHARE
        )


        profit_loss = (
            gross_result -
            commission
        )


        capital += (
            final_price *
            position
        )


        capital -= commission


        trades.append(
            profit_loss
        )


        total_commissions += (
            commission
        )


        if profit_loss >= 0:

            wins += 1

        else:

            losses += 1


        position = 0


    # ========================================================
    # MÉTRICAS
    # ========================================================

    total_trades = len(trades)


    final_capital = capital


    total_profit = (
        final_capital -
        INITIAL_CAPITAL
    )


    strategy_return = (
        total_profit /
        INITIAL_CAPITAL
    ) * 100


    if total_trades > 0:

        win_rate = (
            wins /
            total_trades
        ) * 100

    else:

        win_rate = 0.0


    gross_profit = sum(
        trade
        for trade in trades
        if trade > 0
    )


    gross_loss = abs(
        sum(
            trade
            for trade in trades
            if trade < 0
        )
    )


    if gross_loss > 0:

        profit_factor = (
            gross_profit /
            gross_loss
        )

    else:

        profit_factor = float(
            "inf"
        )


    max_drawdown, max_drawdown_percent = (
        calculate_max_drawdown(
            equity_curve
        )
    )


    # ========================================================
    # BUY & HOLD
    #
    # Ahora usamos precios ajustados
    # por splits/dividendos.
    # ========================================================

    first_price = closes[0]

    last_price = closes[-1]


    buy_hold_return = (
        (
            last_price -
            first_price
        )
        /
        first_price
    ) * 100


    buy_hold_final = (
        INITIAL_CAPITAL *
        (
            last_price /
            first_price
        )
    )


    # ========================================================
    # CAGR
    # ========================================================

    total_days = (
        dates[-1] -
        dates[0]
    ).total_seconds() / 86400


    years = max(
        total_days /
        365.25,
        0.01
    )


    if final_capital > 0:

        cagr = (
            (
                final_capital /
                INITIAL_CAPITAL
            )
            ** (
                1 /
                years
            )
            - 1
        ) * 100

    else:

        cagr = -100.0


    # ========================================================
    # SHARPE
    # ========================================================

    sharpe = calculate_sharpe(
        equity_curve
    )


    # ========================================================
    # RACHA DE PÉRDIDAS
    # ========================================================

    max_losing_streak = (
        calculate_max_losing_streak(
            trades
        )
    )


    # ========================================================
    # MEJOR / PEOR TRADE
    # ========================================================

    if trades:

        best_trade = max(
            trades
        )

        worst_trade = min(
            trades
        )

    else:

        best_trade = 0.0

        worst_trade = 0.0


    # ========================================================
    # DIFERENCIA VS BUY & HOLD
    # ========================================================

    vs_buy_hold = (
        strategy_return -
        buy_hold_return
    )


    return {

        "start_date":
            dates[0].strftime(
                "%Y-%m-%d"
            ),

        "end_date":
            dates[-1].strftime(
                "%Y-%m-%d"
            ),

        "start_price":
            first_price,

        "end_price":
            last_price,

        "final_capital":
            final_capital,

        "return":
            strategy_return,

        "buy_hold":
            buy_hold_return,

        "buy_hold_final":
            buy_hold_final,

        "vs_buy_hold":
            vs_buy_hold,

        "cagr":
            cagr,

        "trades":
            total_trades,

        "wins":
            wins,

        "losses":
            losses,

        "win_rate":
            win_rate,

        "profit_factor":
            profit_factor,

        "drawdown":
            max_drawdown_percent,

        "drawdown_dollars":
            max_drawdown,

        "sharpe":
            sharpe,

        "max_losing_streak":
            max_losing_streak,

        "best_trade":
            best_trade,

        "worst_trade":
            worst_trade,

        "commissions":
            total_commissions
    }


# ============================================================
# INICIO
# ============================================================

print()

print(
    "=============================================="
)

print(
    "       AI TRADER — MULTI BACKTEST V3"
)

print(
    "=============================================="
)

print()

print(
    "DATOS AJUSTADOS: SPLITS + DIVIDENDOS"
)

print(
    "ENTRADA: OPEN DEL DÍA SIGUIENTE"
)

print(
    "STOP: LOW REAL"
)

print()


results = []


# ============================================================
# EJECUTAR PRUEBAS
# ============================================================

for symbol in SYMBOLS:

    print(
        f"Analizando {symbol}..."
    )


    for period_name, days in PERIODS.items():

        end = datetime.now(
            timezone.utc
        )

        start = (
            end -
            timedelta(
                days=days
            )
        )


        request = StockBarsRequest(

            symbol_or_symbols=[
                symbol
            ],

            timeframe=TimeFrame.Day,

            start=start,

            end=end,

            feed=DataFeed.IEX,

            adjustment="all"
        )


        try:

            bars = (
                data_client
                .get_stock_bars(
                    request
                )
            )


            symbol_bars = (
                bars[symbol]
            )


            data = clean_bars(
                symbol_bars
            )


            if len(data) < 50:

                print(
                    f"  {period_name}: "
                    "DATOS INSUFICIENTES"
                )

                continue


            result = run_backtest(
                data
            )


            if result is None:

                print(
                    f"  {period_name}: "
                    "BACKTEST NO DISPONIBLE"
                )

                continue


            results.append({

                "symbol":
                    symbol,

                "period":
                    period_name,

                **result

            })


            pf = result[
                "profit_factor"
            ]


            if math.isinf(pf):

                pf_text = "INF"

            else:

                pf_text = (
                    f"{pf:.2f}"
                )


            print(

                f"  {period_name}: "

                f"{result['return']:.2f}% | "

                f"B&H "
                f"{result['buy_hold']:.2f}% | "

                f"DD "
                f"{result['drawdown']:.2f}% | "

                f"PF "
                f"{pf_text}"

            )


            print(

                f"      Datos: "

                f"{result['start_date']} "
                f"→ "
                f"{result['end_date']} | "

                f"{result['trades']} trades"

            )


        except Exception as error:

            print(
                f"  {period_name}: ERROR"
            )

            print(
                f"      {error}"
            )


    print()


# ============================================================
# RESULTADOS
# ============================================================

print()

print(
    "=============================================="
)

print(
    "                 RESULTADOS"
)

print(
    "=============================================="
)

print()


print(

    "ACTIVO | PERIODO | "
    "ESTRATEGIA | B&H | "
    "TRADES | WIN% | PF | "
    "DD | CAGR | SHARPE"

)


print(
    "-" * 105
)


for result in results:

    pf = result[
        "profit_factor"
    ]


    if math.isinf(pf):

        pf_text = "INF"

    else:

        pf_text = (
            f"{pf:.2f}"
        )


    print(

        f"{result['symbol']:6} | "

        f"{result['period']:7} | "

        f"{result['return']:9.2f}% | "

        f"{result['buy_hold']:6.2f}% | "

        f"{result['trades']:6} | "

        f"{result['win_rate']:5.1f}% | "

        f"{pf_text:>4} | "

        f"{result['drawdown']:5.2f}% | "

        f"{result['cagr']:5.2f}% | "

        f"{result['sharpe']:6.2f}"

    )


# ============================================================
# DETALLE
# ============================================================

print()

print(
    "=============================================="
)

print(
    "              DETALLE DE RIESGO"
)

print(
    "=============================================="
)

print()


for result in results:

    print(
        f"{result['symbol']} — "
        f"{result['period']}"
    )

    print(
        f"  Capital final: "
        f"${result['final_capital']:,.2f}"
    )

    print(
        f"  Rendimiento: "
        f"{result['return']:.2f}%"
    )

    print(
        f"  Buy & Hold: "
        f"{result['buy_hold']:.2f}%"
    )

    print(
        f"  Diferencia vs B&H: "
        f"{result['vs_buy_hold']:+.2f}%"
    )

    print(
        f"  Drawdown máximo: "
        f"{result['drawdown']:.2f}% "
        f"(${result['drawdown_dollars']:,.2f})"
    )

    print(
        f"  Mejor operación: "
        f"${result['best_trade']:,.2f}"
    )

    print(
        f"  Peor operación: "
        f"${result['worst_trade']:,.2f}"
    )

    print(
        f"  Racha máxima de pérdidas: "
        f"{result['max_losing_streak']}"
