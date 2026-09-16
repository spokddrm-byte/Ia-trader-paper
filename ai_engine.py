"""
AI TRADER — AI ENGINE V1
========================

Motor de aprendizaje del bot.

Objetivo V1:
- Registrar las características de cada señal.
- Guardar el resultado cuando la operación termina.
- Preparar dataset para machine learning.
- Entrenar un modelo ligero cuando exista suficiente información.
- Generar una probabilidad/confianza para nuevas señales.

IMPORTANTE:
- NO ejecuta órdenes.
- NO modifica Risk Manager.
- NO decide por sí solo.
- Si algo falla, devuelve una respuesta segura.
"""

from __future__ import annotations

import json
import math
import os
import pickle
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# CONFIGURACIÓN
# ============================================================

AI_ENGINE_VERSION = "V1"

DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    os.getenv("DB_PATH", "trader.db")
)

MODEL_PATH = os.getenv(
    "AI_MODEL_PATH",
    "ai_model.pkl"
)

MIN_TRAINING_SAMPLES = 100

FEATURE_NAMES = [
    "score",
    "rsi",
    "atr_pct",
    "volume_ratio",
    "relative_strength",
    "price_vs_ema_pct",
    "price_vs_sma_pct",
    "trend_strength",
]


# ============================================================
# UTILIDADES
# ============================================================

def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)

        if not math.isfinite(number):
            return default

        return number

    except (TypeError, ValueError):
        return default


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").strip().upper()


# ============================================================
# ESTRUCTURA DE UNA SEÑAL
# ============================================================

@dataclass
class AISignal:
    symbol: str

    score: float
    rsi: float
    atr_pct: float
    volume_ratio: float
    relative_strength: float
    price_vs_ema_pct: float
    price_vs_sma_pct: float
    trend_strength: float

    timestamp: str = ""

    def __post_init__(self):
        self.symbol = normalize_symbol(self.symbol)

        if not self.timestamp:
            self.timestamp = utc_now()

    def features(self) -> List[float]:
        return [
            safe_float(self.score),
            safe_float(self.rsi),
            safe_float(self.atr_pct),
            safe_float(self.volume_ratio),
            safe_float(self.relative_strength),
            safe_float(self.price_vs_ema_pct),
            safe_float(self.price_vs_sma_pct),
            safe_float(self.trend_strength),
        ]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# MOTOR DE IA
# ============================================================

class AIEngine:

    def __init__(
        self,
        database_path: str = DATABASE_PATH,
        model_path: str = MODEL_PATH,
    ):
        self.database_path = database_path
        self.model_path = model_path

        self.model = None
        self.model_ready = False
        self.training_samples = 0

        self._load_model()

    # ========================================================
    # BASE DE DATOS
    # ========================================================

    def _connect(self):
        connection = sqlite3.connect(
            self.database_path,
            timeout=30
        )

        connection.row_factory = sqlite3.Row

        return connection

    # ========================================================
    # CREAR TABLA DE EXPERIENCIA
    # ========================================================

    def initialize(self) -> bool:

        try:

            with self._connect() as conn:

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ai_experience (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,

                        symbol TEXT NOT NULL,

                        timestamp TEXT NOT NULL,

                        score REAL,
                        rsi REAL,
                        atr_pct REAL,
                        volume_ratio REAL,
                        relative_strength REAL,
                        price_vs_ema_pct REAL,
                        price_vs_sma_pct REAL,
                        trend_strength REAL,

                        outcome INTEGER,

                        realized_pl REAL,
                        realized_pl_pct REAL,

                        metadata TEXT
                    )
                    """
                )

                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    idx_ai_experience_symbol
                    ON ai_experience(symbol)
                    """
                )

                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    idx_ai_experience_outcome
                    ON ai_experience(outcome)
                    """
                )

                conn.commit()

            return True

        except Exception as exc:

            print(
                f"[AI ENGINE] Error inicializando experiencia: {exc}"
            )

            return False

    # ========================================================
    # REGISTRAR SEÑAL
    # ========================================================

    def record_signal(
        self,
        signal: AISignal,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:

        if not self.initialize():
            return None

        try:

            with self._connect() as conn:

                cursor = conn.execute(
                    """
                    INSERT INTO ai_experience (
                        symbol,
                        timestamp,
                        score,
                        rsi,
                        atr_pct,
                        volume_ratio,
                        relative_strength,
                        price_vs_ema_pct,
                        price_vs_sma_pct,
                        trend_strength,
                        outcome,
                        realized_pl,
                        realized_pl_pct,
                        metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
                    """,
                    (
                        signal.symbol,
                        signal.timestamp,
                        signal.score,
                        signal.rsi,
                        signal.atr_pct,
                        signal.volume_ratio,
                        signal.relative_strength,
                        signal.price_vs_ema_pct,
                        signal.price_vs_sma_pct,
                        signal.trend_strength,
                        json.dumps(
                            metadata or {},
                            ensure_ascii=False
                        ),
                    )
                )

                conn.commit()

                return cursor.lastrowid

        except Exception as exc:

            print(
                f"[AI ENGINE] Error registrando señal: {exc}"
            )

            return None

    # ========================================================
    # REGISTRAR RESULTADO
    # ========================================================

    def record_outcome(
        self,
        experience_id: int,
        realized_pl: float,
        realized_pl_pct: float,
    ) -> bool:

        try:

            pl = safe_float(realized_pl)
            pl_pct = safe_float(realized_pl_pct)

            outcome = 1 if pl > 0 else 0

            with self._connect() as conn:

                cursor = conn.execute(
                    """
                    UPDATE ai_experience
                    SET
                        outcome = ?,
                        realized_pl = ?,
                        realized_pl_pct = ?
                    WHERE id = ?
                    """,
                    (
                        outcome,
                        pl,
                        pl_pct,
                        int(experience_id),
                    )
                )

                conn.commit()

                return cursor.rowcount > 0

        except Exception as exc:

            print(
                f"[AI ENGINE] Error registrando resultado: {exc}"
            )

            return False

    # ========================================================
    # OBTENER DATASET
    # ========================================================

    def get_training_data(
        self,
    ) -> Tuple[List[List[float]], List[int]]:

        if not self.initialize():
            return [], []

        try:

            with self._connect() as conn:

                rows = conn.execute(
                    """
                    SELECT
                        score,
                        rsi,
                        atr_pct,
                        volume_ratio,
                        relative_strength,
                        price_vs_ema_pct,
                        price_vs_sma_pct,
                        trend_strength,
                        outcome
                    FROM ai_experience
                    WHERE outcome IS NOT NULL
                    ORDER BY id ASC
                    """
                ).fetchall()

            X: List[List[float]] = []
            y: List[int] = []

            for row in rows:

                features = [
                    safe_float(row["score"]),
                    safe_float(row["rsi"]),
                    safe_float(row["atr_pct"]),
                    safe_float(row["volume_ratio"]),
                    safe_float(row["relative_strength"]),
                    safe_float(row["price_vs_ema_pct"]),
                    safe_float(row["price_vs_sma_pct"]),
                    safe_float(row["trend_strength"]),
                ]

                outcome = int(row["outcome"])

                X.append(features)
                y.append(outcome)

            return X, y

        except Exception as exc:

            print(
                f"[AI ENGINE] Error obteniendo dataset: {exc}"
            )

            return [], []

    # ========================================================
    # ENTRENAMIENTO
    # ========================================================

    def train(self) -> Dict[str, Any]:

        X, y = self.get_training_data()

        self.training_samples = len(y)

        if len(y) < MIN_TRAINING_SAMPLES:

            return {
                "trained": False,
                "reason": "insufficient_data",
                "samples": len(y),
                "minimum_required": MIN_TRAINING_SAMPLES,
            }

        if len(set(y)) < 2:

            return {
                "trained": False,
                "reason": "only_one_class",
                "samples": len(y),
            }

        try:

            from sklearn.ensemble import RandomForestClassifier

            model = RandomForestClassifier(
                n_estimators=150,
                max_depth=6,
                min_samples_leaf=3,
                random_state=42,
                class_weight="balanced",
            )

            model.fit(X, y)

            self.model = model
            self.model_ready = True

            self._save_model()

            return {
                "trained": True,
                "samples": len(y),
                "features": len(FEATURE_NAMES),
                "model": "RandomForestClassifier",
                "version": AI_ENGINE_VERSION,
            }

        except ImportError:

            return {
                "trained": False,
                "reason": "scikit_learn_not_installed",
                "samples": len(y),
            }

        except Exception as exc:

            print(
                f"[AI ENGINE] Error entrenando: {exc}"
            )

            return {
                "trained": False,
                "reason": "training_error",
                "error": str(exc),
                "samples": len(y),
            }

    # ========================================================
    # PREDICCIÓN
    # ========================================================

    def predict(
        self,
        signal: AISignal,
    ) -> Dict[str, Any]:

        if not self.model_ready or self.model is None:

            return {
                "ready": False,
                "prediction": None,
                "probability": None,
                "reason": "model_not_ready",
            }

        try:

            features = [signal.features()]

            probabilities = self.model.predict_proba(features)[0]

            classes = list(self.model.classes_)

            probability_positive = 0.0

            if 1 in classes:

                positive_index = classes.index(1)

                probability_positive = safe_float(
                    probabilities[positive_index]
                )

            prediction = 1 if probability_positive >= 0.50 else 0

            return {
                "ready": True,
                "prediction": prediction,
                "probability": probability_positive,
                "confidence_pct": probability_positive * 100.0,
                "symbol": signal.symbol,
                "version": AI_ENGINE_VERSION,
            }

        except Exception as exc:

            print(
                f"[AI ENGINE] Error en predicción: {exc}"
            )

            return {
                "ready": False,
                "prediction": None,
                "probability": None,
                "reason": "prediction_error",
                "error": str(exc),
            }

    # ========================================================
    # MODELO
    # ========================================================

    def _save_model(self) -> bool:

        try:

            payload = {
                "version": AI_ENGINE_VERSION,
                "features": FEATURE_NAMES,
                "model": self.model,
                "saved_at": utc_now(),
            }

            with open(
                self.model_path,
                "wb"
            ) as file:

                pickle.dump(
                    payload,
                    file
                )

            return True

        except Exception as exc:

            print(
                f"[AI ENGINE] Error guardando modelo: {exc}"
            )

            return False

    def _load_model(self) -> bool:

        if not os.path.exists(self.model_path):

            return False

        try:

            with open(
                self.model_path,
                "rb"
            ) as file:

                payload = pickle.load(file)

            if not isinstance(payload, dict):
                return False

            if payload.get("features") != FEATURE_NAMES:
                return False

            model = payload.get("model")

            if model is None:
                return False

            self.model = model
            self.model_ready = True

            return True

        except Exception as exc:

            print(
                f"[AI ENGINE] No se pudo cargar modelo: {exc}"
            )

            self.model = None
            self.model_ready = False

            return False

    # ========================================================
    # ESTADO
    # ========================================================

    def status(self) -> Dict[str, Any]:

        X, y = self.get_training_data()

        self.training_samples = len(y)

        return {
            "engine": "AI ENGINE",
            "version": AI_ENGINE_VERSION,
            "model_ready": self.model_ready,
            "training_samples": self.training_samples,
            "minimum_training_samples": MIN_TRAINING_SAMPLES,
            "features": FEATURE_NAMES,
            "database": self.database_path,
            "model_path": self.model_path,
        }

    # ========================================================
    # SELF TEST
    # ========================================================

    def self_test(self) -> Dict[str, Any]:

        initialized = self.initialize()

        test_signal = AISignal(
            symbol="TEST",
            score=75.0,
            rsi=55.0,
            atr_pct=2.0,
            volume_ratio=1.2,
            relative_strength=0.03,
            price_vs_ema_pct=1.5,
            price_vs_sma_pct=2.0,
            trend_strength=0.70,
        )

        prediction = self.predict(test_signal)

        return {
            "initialized": initialized,
            "prediction": prediction,
            "status": self.status(),
        }


# ============================================================
# INSTANCIA GLOBAL
# ============================================================

ai_engine = AIEngine()


# ============================================================
# FUNCIONES DE ACCESO RÁPIDO
# ============================================================

def initialize_ai_engine() -> bool:
    return ai_engine.initialize()


def record_ai_signal(
    symbol: str,
    score: float,
    rsi: float,
    atr_pct: float,
    volume_ratio: float,
    relative_strength: float,
    price_vs_ema_pct: float,
    price_vs_sma_pct: float,
    trend_strength: float,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[int]:

    signal = AISignal(
        symbol=symbol,
        score=score,
        rsi=rsi,
        atr_pct=atr_pct,
        volume_ratio=volume_ratio,
        relative_strength=relative_strength,
        price_vs_ema_pct=price_vs_ema_pct,
        price_vs_sma_pct=price_vs_sma_pct,
        trend_strength=trend_strength,
    )

    return ai_engine.record_signal(
        signal,
        metadata=metadata,
    )


def train_ai() -> Dict[str, Any]:
    return ai_engine.train()


def ai_predict(
    symbol: str,
    score: float,
    rsi: float,
    atr_pct: float,
    volume_ratio: float,
    relative_strength: float,
    price_vs_ema_pct: float,
    price_vs_sma_pct: float,
    trend_strength: float,
) -> Dict[str, Any]:

    signal = AISignal(
        symbol=symbol,
        score=score,
        rsi=rsi,
        atr_pct=atr_pct,
        volume_ratio=volume_ratio,
        relative_strength=relative_strength,
        price_vs_ema_pct=price_vs_ema_pct,
        price_vs_sma_pct=price_vs_sma_pct,
        trend_strength=trend_strength,
    )

    return ai_engine.predict(signal)


# ============================================================
# EJECUCIÓN DIRECTA
# ============================================================

if __name__ == "__main__":

    print("=" * 72)
    print("              AI TRADER — AI ENGINE V1")
    print("=" * 72)

    engine = AIEngine()

    print(
        json.dumps(
            engine.status(),
            indent=2,
            ensure_ascii=False,
        )
    )

    print("-" * 72)

    result = engine.self_test()

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
