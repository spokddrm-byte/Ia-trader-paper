"""
AI TRADER — PORTFOLIO ANALYZER V2 PANTERA
=========================================

Capa de inteligencia de portafolio.

Flujo:

    SCANNER
       ↓
    SIGNAL ENGINE
       ↓
    PORTFOLIO ANALYZER
       ↓
    RISK MANAGER
       ↓
    EXECUTOR
       ↓
    TRADE MANAGER

RESPONSABILIDADES:
- Analizar exposición actual.
- Medir concentración.
- Medir correlación entre posiciones.
- Evaluar impacto de una nueva operación.
- Detectar concentración excesiva.
- Detectar posiciones altamente correlacionadas.
- Calcular riesgo incremental.
- Proporcionar una decisión estructurada al motor superior.

IMPORTANTE:
Este módulo NO ejecuta órdenes.
El Risk Manager sigue siendo la autoridad final de riesgo.

CAMBIOS V2:
- La concentración del candidato se mide contra equity.
- Se evita bloquear una operación únicamente porque
  represente un porcentaje elevado del capital actualmente
  invertido.
- Se mantiene el límite de exposición total.
- Se mantiene el límite por símbolo.
- Se mantiene el límite de posición individual.
- Correlación y riesgo siguen siendo controles duros.
- Compatible con la integración dinámica de main.py.
"""

from __future__ import annotations

import math
import statistics

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ============================================================
# CONFIGURACIÓN
# ============================================================

DEFAULT_MAX_TOTAL_EXPOSURE = 0.70
DEFAULT_MAX_SYMBOL_EXPOSURE = 0.20
DEFAULT_MAX_SINGLE_POSITION = 0.20

# Correlación
DEFAULT_HIGH_CORRELATION = 0.85
DEFAULT_EXTREME_CORRELATION = 0.92

# Concentración
#
# IMPORTANTE:
# Estos porcentajes representan peso respecto al EQUITY,
# no respecto al capital actualmente invertido.
#
# Una posición del 10% del equity no debe convertirse
# automáticamente en un bloqueo solamente porque el
# portafolio actual tenga 30-40% de exposición.
DEFAULT_CONCENTRATION_WARNING = 0.15
DEFAULT_CONCENTRATION_BLOCK = 0.20

# Mínimo de observaciones para correlación.
DEFAULT_MIN_CORRELATION_OBSERVATIONS = 30

# Máximo de posiciones altamente correlacionadas.
DEFAULT_MAX_HIGHLY_CORRELATED_POSITIONS = 3


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class PositionSnapshot:
    symbol: str
    quantity: float
    market_value: float
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    unrealized_pl: Optional[float] = None
    original_stop: Optional[float] = None
    current_stop: Optional[float] = None


@dataclass
class CandidateAnalysis:
    symbol: str
    proposed_value: float

    current_exposure: float
    projected_exposure: float

    current_symbol_exposure: float
    projected_symbol_exposure: float

    concentration_ratio: float

    available_exposure_before: float
    available_exposure_after: float

    max_position_violation: bool
    total_exposure_violation: bool
    symbol_exposure_violation: bool
    concentration_warning: bool
    concentration_block: bool

    average_correlation: Optional[float]
    maximum_correlation: Optional[float]
    highly_correlated_positions: List[str]

    correlation_warning: bool
    correlation_block: bool

    risk_increment: float
    risk_remaining_before: float
    risk_remaining_after: float
    risk_violation: bool

    approved_for_portfolio: bool
    reasons: List[str]

    score: float


# ============================================================
# UTILIDADES
# ============================================================

def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        if value is None:
            return default

        result = float(value)

        if not math.isfinite(result):
            return default

        return result

    except (TypeError, ValueError):
        return default


def _safe_positive(
    value: Any,
) -> float:
    value = _safe_float(value)

    return max(0.0, value)


def _normalize_symbol(
    symbol: Any,
) -> str:
    return str(symbol or "").strip().upper()


def _clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(minimum, min(maximum, value))


# ============================================================
# CORRELACIÓN
# ============================================================

def _clean_pair(
    x: Sequence[float],
    y: Sequence[float],
) -> Tuple[List[float], List[float]]:
    """
    Elimina pares inválidos manteniendo alineación.
    """

    clean_x: List[float] = []
    clean_y: List[float] = []

    for a, b in zip(x, y):

        try:
            a = float(a)
            b = float(b)

            if not math.isfinite(a):
                continue

            if not math.isfinite(b):
                continue

            clean_x.append(a)
            clean_y.append(b)

        except (TypeError, ValueError):
            continue

    return clean_x, clean_y


def pearson_correlation(
    x: Sequence[float],
    y: Sequence[float],
    min_observations: int = DEFAULT_MIN_CORRELATION_OBSERVATIONS,
) -> Optional[float]:
    """
    Correlación de Pearson sin depender de numpy/pandas.
    """

    x, y = _clean_pair(x, y)

    if len(x) < min_observations:
        return None

    try:
        mean_x = statistics.fmean(x)
        mean_y = statistics.fmean(y)

        numerator = 0.0
        denominator_x = 0.0
        denominator_y = 0.0

        for a, b in zip(x, y):

            dx = a - mean_x
            dy = b - mean_y

            numerator += dx * dy
            denominator_x += dx * dx
            denominator_y += dy * dy

        denominator = math.sqrt(
            denominator_x * denominator_y
        )

        if denominator <= 0:
            return None

        correlation = numerator / denominator

        if not math.isfinite(correlation):
            return None

        return _clamp(
            correlation,
            -1.0,
            1.0,
        )

    except Exception:
        return None


# ============================================================
# EXPOSICIÓN
# ============================================================

def calculate_total_market_value(
    positions: Sequence[PositionSnapshot],
) -> float:
    return sum(
        _safe_positive(position.market_value)
        for position in positions
    )


def calculate_total_exposure(
    positions: Sequence[PositionSnapshot],
    equity: float,
) -> float:
    """
    Exposición = valor absoluto de posiciones / equity.
    """

    equity = _safe_positive(equity)

    if equity <= 0:
        return 1.0

    market_value = calculate_total_market_value(
        positions
    )

    return market_value / equity


def calculate_symbol_exposure(
    position: PositionSnapshot,
    equity: float,
) -> float:
    equity = _safe_positive(equity)

    if equity <= 0:
        return 1.0

    return (
        _safe_positive(position.market_value)
        / equity
    )


def calculate_projected_exposure(
    positions: Sequence[PositionSnapshot],
    proposed_value: float,
    equity: float,
) -> float:
    equity = _safe_positive(equity)

    if equity <= 0:
        return 1.0

    current_value = calculate_total_market_value(
        positions
    )

    return (
        current_value
        + _safe_positive(proposed_value)
    ) / equity


# ============================================================
# CONCENTRACIÓN
# ============================================================

def calculate_concentration_ratio(
    proposed_value: float,
    projected_market_value: float,
) -> float:
    """
    Peso del candidato dentro del capital invertido
    proyectado.

    NOTA:
    Esta función se conserva por compatibilidad.

    Para la decisión del Analyzer V2 se utiliza
    calculate_equity_concentration_ratio(), que mide
    la posición contra el equity total.
    """

    projected_market_value = _safe_positive(
        projected_market_value
    )

    if projected_market_value <= 0:
        return 1.0

    return (
        _safe_positive(proposed_value)
        / projected_market_value
    )


def calculate_equity_concentration_ratio(
    proposed_value: float,
    equity: float,
) -> float:
    """
    Peso real del candidato respecto al equity total.

    Ejemplo:

        Equity = $100,000
        Operación = $10,000

        concentración = 10%

    Esto evita que una cartera parcialmente invertida
    produzca falsos bloqueos de concentración.
    """

    equity = _safe_positive(equity)

    if equity <= 0:
        return 1.0

    return (
        _safe_positive(proposed_value)
        / equity
    )


def calculate_position_weights(
    positions: Sequence[PositionSnapshot],
) -> Dict[str, float]:

    total = calculate_total_market_value(
        positions
    )

    if total <= 0:
        return {}

    result: Dict[str, float] = {}

    for position in positions:

        symbol = _normalize_symbol(
            position.symbol
        )

        if not symbol:
            continue

        value = _safe_positive(
            position.market_value
        )

        result[symbol] = value / total

    return result


# ============================================================
# CORRELACIÓN DE CANDIDATO
# ============================================================

def analyze_correlations(
    candidate_symbol: str,
    existing_returns: Dict[str, Sequence[float]],
    candidate_returns: Sequence[float],
    high_threshold: float = DEFAULT_HIGH_CORRELATION,
    extreme_threshold: float = DEFAULT_EXTREME_CORRELATION,
    min_observations: int = DEFAULT_MIN_CORRELATION_OBSERVATIONS,
) -> Dict[str, Any]:
    """
    Analiza correlación del candidato contra las
    posiciones que tengan datos suficientes.
    """

    candidate_symbol = _normalize_symbol(
        candidate_symbol
    )

    correlations: Dict[str, float] = {}

    for symbol, returns in existing_returns.items():

        symbol = _normalize_symbol(symbol)

        if not symbol:
            continue

        if symbol == candidate_symbol:
            continue

        correlation = pearson_correlation(
            candidate_returns,
            returns,
            min_observations=min_observations,
        )

        if correlation is None:
            continue

        correlations[symbol] = correlation

    if not correlations:
        return {
            "correlations": {},
            "average_correlation": None,
            "maximum_correlation": None,
            "highly_correlated": [],
            "extremely_correlated": [],
        }

    average = statistics.fmean(
        correlations.values()
    )

    maximum = max(
        correlations.values()
    )

    highly_correlated = [
        symbol
        for symbol, value in correlations.items()
        if value >= high_threshold
    ]

    extremely_correlated = [
        symbol
        for symbol, value in correlations.items()
        if value >= extreme_threshold
    ]

    return {
        "correlations": correlations,
        "average_correlation": average,
        "maximum_correlation": maximum,
        "highly_correlated": highly_correlated,
        "extremely_correlated": extremely_correlated,
    }


# ============================================================
# RIESGO INCREMENTAL
# ============================================================

def estimate_trade_risk(
    proposed_value: float,
    entry_price: float,
    stop_price: Optional[float],
    equity: float,
) -> float:
    """
    Estima riesgo monetario del candidato utilizando stop.

    risk % =
        (entry - stop) * quantity / equity

    Para long-only.
    """

    proposed_value = _safe_positive(
        proposed_value
    )

    entry_price = _safe_positive(
        entry_price
    )

    stop_price = _safe_positive(
        stop_price
    )

    equity = _safe_positive(equity)

    if (
        proposed_value <= 0
        or entry_price <= 0
        or equity <= 0
    ):
        return 1.0

    if stop_price <= 0:
        return 1.0

    if stop_price >= entry_price:
        return 1.0

    stop_distance = (
        entry_price - stop_price
    ) / entry_price

    stop_distance = _clamp(
        stop_distance,
        0.0,
        1.0,
    )

    risk_value = (
        proposed_value
        * stop_distance
    )

    return risk_value / equity


def calculate_existing_portfolio_risk(
    positions: Sequence[PositionSnapshot],
    equity: float,
) -> float:
    """
    Estimación conservadora del riesgo de las posiciones
    existentes usando el stop disponible.

    Si una posición no tiene stop válido, se considera
    riesgo completo de la posición.
    """

    equity = _safe_positive(equity)

    if equity <= 0:
        return 1.0

    total_risk = 0.0

    for position in positions:

        value = _safe_positive(
            position.market_value
        )

        if value <= 0:
            continue

        entry = _safe_positive(
            position.entry_price
        )

        stop = _safe_positive(
            position.current_stop
            or position.original_stop
        )

        if (
            entry > 0
            and stop > 0
            and stop < entry
        ):

            distance = (
                entry - stop
            ) / entry

            distance = _clamp(
                distance,
                0.0,
                1.0,
            )

            total_risk += (
                value * distance
            )

        else:

            # Sin stop conocido.
            #
            # El tratamiento conservador se mantiene.
            # No se asume que una posición sin stop
            # tiene riesgo cero.
            total_risk += value

    return total_risk / equity


# ============================================================
# PORTFOLIO ANALYZER
# ============================================================

class PortfolioAnalyzer:
    """
    Cerebro de análisis de portafolio.

    No ejecuta operaciones.
    """

    def __init__(
        self,
        max_total_exposure: float = DEFAULT_MAX_TOTAL_EXPOSURE,
        max_symbol_exposure: float = DEFAULT_MAX_SYMBOL_EXPOSURE,
        max_single_position: float = DEFAULT_MAX_SINGLE_POSITION,
        max_highly_correlated_positions: int = (
            DEFAULT_MAX_HIGHLY_CORRELATED_POSITIONS
        ),
        high_correlation: float = DEFAULT_HIGH_CORRELATION,
        extreme_correlation: float = DEFAULT_EXTREME_CORRELATION,
        concentration_warning: float = (
            DEFAULT_CONCENTRATION_WARNING
        ),
        concentration_block: float = (
            DEFAULT_CONCENTRATION_BLOCK
        ),
        min_correlation_observations: int = (
            DEFAULT_MIN_CORRELATION_OBSERVATIONS
        ),
    ):

        self.max_total_exposure = _clamp(
            _safe_float(max_total_exposure),
            0.0,
            1.0,
        )

        self.max_symbol_exposure = _clamp(
            _safe_float(max_symbol_exposure),
            0.0,
            1.0,
        )

        self.max_single_position = _clamp(
            _safe_float(max_single_position),
            0.0,
            1.0,
        )

        self.max_highly_correlated_positions = max(
            1,
            int(
                max_highly_correlated_positions
            ),
        )

        self.high_correlation = _clamp(
            _safe_float(high_correlation),
            -1.0,
            1.0,
        )

        self.extreme_correlation = _clamp(
            _safe_float(extreme_correlation),
            -1.0,
            1.0,
        )

        self.concentration_warning = _clamp(
            _safe_float(concentration_warning),
            0.0,
            1.0,
        )

        self.concentration_block = _clamp(
            _safe_float(concentration_block),
            0.0,
            1.0,
        )

        self.min_correlation_observations = max(
            5,
            int(min_correlation_observations),
        )

    # ========================================================
    # SNAPSHOT
    # ========================================================

    def portfolio_snapshot(
        self,
        positions: Sequence[PositionSnapshot],
        equity: float,
        buying_power: Optional[float] = None,
    ) -> Dict[str, Any]:

        equity = _safe_positive(equity)

        market_value = calculate_total_market_value(
            positions
        )

        exposure = calculate_total_exposure(
            positions,
            equity,
        )

        weights = calculate_position_weights(
            positions
        )

        largest_symbol = None
        largest_weight = 0.0

        if weights:

            largest_symbol = max(
                weights,
                key=weights.get,
            )

            largest_weight = weights[
                largest_symbol
            ]

        concentration = sum(
            weight * weight
            for weight in weights.values()
        )

        return {
            "equity": equity,
            "buying_power": (
                _safe_positive(
                    buying_power
                )
                if buying_power is not None
                else None
            ),
            "market_value": market_value,
            "total_exposure": exposure,
            "available_exposure": max(
                0.0,
                self.max_total_exposure
                - exposure,
            ),
            "position_count": len(positions),
            "largest_position": largest_symbol,
            "largest_position_weight": largest_weight,
            "concentration_index": concentration,
            "weights": weights,
        }

    # ========================================================
    # CANDIDATE ANALYSIS
    # ========================================================

    def analyze_candidate(
        self,
        symbol: str,
        proposed_value: float,
        entry_price: float,
        stop_price: Optional[float],
        equity: float,
        positions: Sequence[PositionSnapshot],
        existing_returns: Optional[
            Dict[str, Sequence[float]]
        ] = None,
        candidate_returns: Optional[
            Sequence[float]
        ] = None,
        existing_portfolio_risk: Optional[float] = None,
        max_portfolio_risk: float = 0.03,
    ) -> CandidateAnalysis:

        symbol = _normalize_symbol(symbol)

        proposed_value = _safe_positive(
            proposed_value
        )

        equity = _safe_positive(equity)

        reasons: List[str] = []

        # ----------------------------------------------------
        # VALORES ACTUALES
        # ----------------------------------------------------

        current_market_value = (
            calculate_total_market_value(
                positions
            )
        )

        current_exposure = (
            calculate_total_exposure(
                positions,
                equity,
            )
        )

        projected_market_value = (
            current_market_value
            + proposed_value
        )

        projected_exposure = (
            calculate_projected_exposure(
                positions,
                proposed_value,
                equity,
            )
        )

        # ----------------------------------------------------
        # EXPOSICIÓN DEL MISMO SÍMBOLO
        # ----------------------------------------------------

        current_symbol_value = sum(
            _safe_positive(
                position.market_value
            )
            for position in positions
            if _normalize_symbol(
                position.symbol
            ) == symbol
        )

        current_symbol_exposure = (
            current_symbol_value / equity
            if equity > 0
            else 1.0
        )

        projected_symbol_exposure = (
            (
                current_symbol_value
                + proposed_value
            ) / equity
            if equity > 0
            else 1.0
        )

        # ----------------------------------------------------
        # CONCENTRACIÓN
        # ----------------------------------------------------
        #
        # V1:
        #
        # proposed / projected_market_value
        #
        # Esto podía generar falsos bloqueos cuando el
        # portafolio tenía poca exposición.
        #
        # V2:
        #
        # proposed / equity
        #
        # Ahora representa directamente cuánto capital
        # del portafolio consume el candidato.
        # ----------------------------------------------------

        concentration_ratio = (
            calculate_equity_concentration_ratio(
                proposed_value,
                equity,
            )
        )

        # ----------------------------------------------------
        # EXPOSURE LIMITS
        # ----------------------------------------------------

        available_exposure_before = max(
            0.0,
            self.max_total_exposure
            - current_exposure,
        )

        available_exposure_after = max(
            0.0,
            self.max_total_exposure
            - projected_exposure,
        )

        total_exposure_violation = (
            projected_exposure
            > self.max_total_exposure
        )

        symbol_exposure_violation = (
            projected_symbol_exposure
            > self.max_symbol_exposure
        )

        max_position_violation = (
            proposed_value / equity
            > self.max_single_position
            if equity > 0
            else True
        )

        # ----------------------------------------------------
        # CONCENTRATION FLAGS
        # ----------------------------------------------------

        concentration_warning = (
            concentration_ratio
            >= self.concentration_warning
        )

        concentration_block = (
            concentration_ratio
            > self.concentration_block
        )

        # ----------------------------------------------------
        # CORRELACIÓN
        # ----------------------------------------------------

        average_correlation = None
        maximum_correlation = None
        highly_correlated: List[str] = []

        correlation_warning = False
        correlation_block = False

        if (
            existing_returns
            and candidate_returns
        ):

            correlation_data = (
                analyze_correlations(
                    candidate_symbol=symbol,
                    existing_returns=existing_returns,
                    candidate_returns=candidate_returns,
                    high_threshold=self.high_correlation,
                    extreme_threshold=self.extreme_correlation,
                    min_observations=(
                        self.min_correlation_observations
                    ),
                )
            )

            average_correlation = (
                correlation_data[
                    "average_correlation"
                ]
            )

            maximum_correlation = (
                correlation_data[
                    "maximum_correlation"
                ]
            )

            highly_correlated = (
                correlation_data[
                    "highly_correlated"
                ]
            )

            if highly_correlated:

                correlation_warning = True

            # Bloqueo solamente cuando el candidato
            # ya estaría altamente correlacionado con
            # demasiadas posiciones.
            if (
                len(highly_correlated)
                >= self.max_highly_correlated_positions
            ):

                correlation_block = True

        # ----------------------------------------------------
        # RIESGO
        # ----------------------------------------------------

        if existing_portfolio_risk is None:

            existing_portfolio_risk = (
                calculate_existing_portfolio_risk(
                    positions,
                    equity,
                )
            )

        existing_portfolio_risk = _clamp(
            _safe_float(
                existing_portfolio_risk
            ),
            0.0,
            1.0,
        )

        risk_increment = estimate_trade_risk(
            proposed_value=proposed_value,
            entry_price=entry_price,
            stop_price=stop_price,
            equity=equity,
        )

        risk_remaining_before = max(
            0.0,
            max_portfolio_risk
            - existing_portfolio_risk,
        )

        projected_portfolio_risk = (
            existing_portfolio_risk
            + risk_increment
        )

        risk_remaining_after = max(
            0.0,
            max_portfolio_risk
            - projected_portfolio_risk,
        )

        risk_violation = (
            projected_portfolio_risk
            > max_portfolio_risk
        )

        # ----------------------------------------------------
        # REASONS
        # ----------------------------------------------------

        if total_exposure_violation:

            reasons.append(
                "TOTAL_EXPOSURE_LIMIT"
            )

        if symbol_exposure_violation:

            reasons.append(
                "SYMBOL_EXPOSURE_LIMIT"
            )

        if max_position_violation:

            reasons.append(
                "MAX_POSITION_LIMIT"
            )

        if concentration_block:

            reasons.append(
                "CONCENTRATION_LIMIT"
            )

        if correlation_block:

            reasons.append(
                "CORRELATION_CONCENTRATION"
            )

        if risk_violation:

            reasons.append(
                "PORTFOLIO_RISK_LIMIT"
            )

        if correlation_warning:

            reasons.append(
                "HIGH_CORRELATION_WARNING"
            )

        if concentration_warning:

            reasons.append(
                "CONCENTRATION_WARNING"
            )

        # ----------------------------------------------------
        # APPROVAL
        # ----------------------------------------------------

        approved = not any(
            [
                total_exposure_violation,
                symbol_exposure_violation,
                max_position_violation,
                concentration_block,
                correlation_block,
                risk_violation,
            ]
        )

        if approved:

            reasons.append(
                "PORTFOLIO_COMPATIBLE"
            )

        # ----------------------------------------------------
        # SCORE
        # ----------------------------------------------------

        score = 100.0

        if total_exposure_violation:

            score -= 35

        if symbol_exposure_violation:

            score -= 25

        if max_position_violation:

            score -= 20

        if concentration_block:

            score -= 20

        elif concentration_warning:

            score -= 8

        if correlation_block:

            score -= 20

        elif correlation_warning:

            score -= 8

        if risk_violation:

            score -= 35

        # ----------------------------------------------------
        # PRESIÓN DE EXPOSICIÓN
        # ----------------------------------------------------

        if self.max_total_exposure > 0:

            exposure_pressure = (
                projected_exposure
                / self.max_total_exposure
            )

            if exposure_pressure > 0.80:

                score -= min(
                    15.0,
                    (
                        exposure_pressure
                        - 0.80
                    ) * 75.0,
                )

        score = _clamp(
            score,
            0.0,
            100.0,
        )

        # ----------------------------------------------------
        # RESULTADO
        # ----------------------------------------------------

        return CandidateAnalysis(

            symbol=symbol,

            proposed_value=proposed_value,

            current_exposure=current_exposure,

            projected_exposure=projected_exposure,

            current_symbol_exposure=(
                current_symbol_exposure
            ),

            projected_symbol_exposure=(
                projected_symbol_exposure
            ),

            concentration_ratio=(
                concentration_ratio
            ),

            available_exposure_before=(
                available_exposure_before
            ),

            available_exposure_after=(
                available_exposure_after
            ),

            max_position_violation=(
                max_position_violation
            ),

            total_exposure_violation=(
                total_exposure_violation
            ),

            symbol_exposure_violation=(
                symbol_exposure_violation
            ),

            concentration_warning=(
                concentration_warning
            ),

            concentration_block=(
                concentration_block
            ),

            average_correlation=(
                average_correlation
            ),

            maximum_correlation=(
                maximum_correlation
            ),

            highly_correlated_positions=(
                highly_correlated
            ),

            correlation_warning=(
                correlation_warning
            ),

            correlation_block=(
                correlation_block
            ),

            risk_increment=risk_increment,

            risk_remaining_before=(
                risk_remaining_before
            ),

            risk_remaining_after=(
                risk_remaining_after
            ),

            risk_violation=risk_violation,

            approved_for_portfolio=approved,

            reasons=reasons,

            score=score,
        )

    # ========================================================
    # MULTIPLE CANDIDATES
    # ========================================================

    def rank_candidates(
        self,
        candidates: Sequence[Dict[str, Any]],
        equity: float,
        positions: Sequence[PositionSnapshot],
        existing_returns: Optional[
            Dict[str, Sequence[float]]
        ] = None,
        max_portfolio_risk: float = 0.03,
    ) -> List[CandidateAnalysis]:

        """
        Analiza varios candidatos.

        No ejecuta ninguno.

        Los candidatos se procesan sobre el portafolio
        ACTUAL, no sobre un portafolio ficticio creado
        por las operaciones anteriores del mismo lote.
        """

        results: List[CandidateAnalysis] = []

        for candidate in candidates:

            symbol = candidate.get(
                "symbol"
            )

            if not symbol:
                continue

            candidate_returns = (
                candidate.get(
                    "returns"
                )
            )

            analysis = self.analyze_candidate(

                symbol=symbol,

                proposed_value=_safe_float(
                    candidate.get(
                        "proposed_value"
                    )
                ),

                entry_price=_safe_float(
                    candidate.get(
                        "entry_price"
                    )
                ),

                stop_price=candidate.get(
                    "stop_price"
                ),

                equity=equity,

                positions=positions,

                existing_returns=(
                    existing_returns
                ),

                candidate_returns=(
                    candidate_returns
                ),

                existing_portfolio_risk=(
                    candidate.get(
                        "existing_portfolio_risk"
                    )
                ),

                max_portfolio_risk=(
                    max_portfolio_risk
                ),
            )

            results.append(
                analysis
            )

        # Primero compatibles.
        # Después por score.
        results.sort(
            key=lambda item: (
                not item.approved_for_portfolio,
                -item.score,
            )
        )

        return results


# ============================================================
# FUNCIONES DE CONVENIENCIA
# ============================================================

def build_position_snapshot(
    position: Any,
) -> PositionSnapshot:

    """
    Convierte un objeto/dict de posición en nuestro formato.
    """

    if isinstance(position, dict):

        symbol = position.get(
            "symbol"
        )

        quantity = position.get(
            "quantity",
            0,
        )

        market_value = position.get(
            "market_value",
            0,
        )

        entry_price = position.get(
            "entry_price"
        )

        current_price = position.get(
            "current_price"
        )

        unrealized_pl = position.get(
            "unrealized_pl"
        )

        original_stop = position.get(
            "original_stop"
        )

        current_stop = position.get(
            "current_stop"
        )

    else:

        symbol = getattr(
            position,
            "symbol",
            "",
        )

        quantity = getattr(
            position,
            "qty",
            getattr(
                position,
                "quantity",
                0,
            ),
        )

        market_value = getattr(
            position,
            "market_value",
            0,
        )

        entry_price = getattr(
            position,
            "avg_entry_price",
            getattr(
                position,
                "entry_price",
                None,
            ),
        )

        current_price = getattr(
            position,
            "current_price",
            None,
        )

        unrealized_pl = getattr(
            position,
            "unrealized_pl",
            None,
        )

        original_stop = getattr(
            position,
            "original_stop",
            None,
        )

        current_stop = getattr(
            position,
            "current_stop",
            None,
        )

    return PositionSnapshot(

        symbol=_normalize_symbol(
            symbol
        ),

        quantity=_safe_float(
            quantity
        ),

        market_value=_safe_float(
            market_value
        ),

        entry_price=(
            _safe_float(
                entry_price
            )
            if entry_price is not None
            else None
        ),

        current_price=(
            _safe_float(
                current_price
            )
            if current_price is not None
            else None
        ),

        unrealized_pl=(
            _safe_float(
                unrealized_pl
            )
            if unrealized_pl is not None
            else None
        ),

        original_stop=(
            _safe_float(
                original_stop
            )
            if original_stop is not None
            else None
        ),

        current_stop=(
            _safe_float(
                current_stop
            )
            if current_stop is not None
            else None
        ),
    )


def analyze_portfolio_candidate(
    symbol: str,
    proposed_value: float,
    entry_price: float,
    stop_price: Optional[float],
    equity: float,
    positions: Sequence[Any],
    existing_returns: Optional[
        Dict[str, Sequence[float]]
    ] = None,
    candidate_returns: Optional[
        Sequence[float]
    ] = None,
    max_portfolio_risk: float = 0.03,
) -> Dict[str, Any]:

    """
    Función sencilla para integrar posteriormente
    con main.py.
    """

    snapshots = [
        build_position_snapshot(
            position
        )
        for position in positions
    ]

    analyzer = PortfolioAnalyzer()

    result = analyzer.analyze_candidate(

        symbol=symbol,

        proposed_value=proposed_value,

        entry_price=entry_price,

        stop_price=stop_price,

        equity=equity,

        positions=snapshots,

        existing_returns=existing_returns,

        candidate_returns=candidate_returns,

        max_portfolio_risk=max_portfolio_risk,
    )

    return asdict(
        result
    )


# ============================================================
# SELF TEST
# ============================================================

def self_test() -> None:
    """
    Prueba interna sin conexión a Alpaca.
    """

    positions = [

        PositionSnapshot(
            symbol="AAPL",
            quantity=10,
            market_value=2000,
            entry_price=190,
            current_price=200,
            current_stop=180,
        ),

        PositionSnapshot(
            symbol="MSFT",
            quantity=5,
            market_value=2000,
            entry_price=390,
            current_price=400,
            current_stop=370,
        ),

    ]

    equity = 10000

    analyzer = PortfolioAnalyzer()

    snapshot = analyzer.portfolio_snapshot(

        positions=positions,

        equity=equity,

        buying_power=5000,
    )

    assert snapshot[
        "market_value"
    ] == 4000

    assert abs(
        snapshot[
            "total_exposure"
        ] - 0.40
    ) < 0.000001

    result = analyzer.analyze_candidate(

        symbol="NVDA",

        proposed_value=1000,

        entry_price=100,

        stop_price=95,

        equity=equity,

        positions=positions,
    )

    assert result.symbol == "NVDA"

    assert result.proposed_value == 1000

    assert (
        result.projected_exposure
        == 0.50
    )

    # V2:
    # $1,000 sobre $10,000 = 10%.
    # No debe ser bloqueado por concentración.
    assert abs(
        result.concentration_ratio
        - 0.10
    ) < 0.000001

    assert (
        result.concentration_block
        is False
    )

    print(
        "PORTFOLIO ANALYZER SELF-TEST: OK"
    )


# ============================================================
# ARRANQUE DIRECTO
# ============================================================

if __name__ == "__main__":

    print(
        "=" * 72
    )

    print(
        "AI TRADER — PORTFOLIO ANALYZER V2 PANTERA"
    )

    print(
        "=" * 72
    )

    try:

        self_test()

        print(
            "Estado: OK"
        )

    except Exception as exc:

        print(
            f"SELF-TEST ERROR: {exc}"
        )

        raise
