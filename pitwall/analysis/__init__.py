"""Analysis engine: lap metrics, handling diagnosis and single-setting advice.

Pure functions over recorded frames, no I/O and no global state::

    analyze_lap(frames, LapContext(...)) -> LapAnalysis
    analyze_session(laps, SessionContext(...)) -> SessionAnalysis
    LiveAnalyzer(drivetrain, tune_values, unit_system).push(frame) -> LiveAnalysis | None

Every result type has ``to_dict()`` with JSON-ready output in canonical API
units. See ``docs/analysis.md`` for metrics, thresholds and rules.
"""

__version__ = "1.1"  # bump when results change, so cached analyses are recomputed

from .lap import analyze_lap
from .live import LiveAnalyzer
from .results import (
    BoardItem,
    CornerSummary,
    Finding,
    LapAnalysis,
    LapContext,
    LapMetrics,
    LiveAnalysis,
    Recommendation,
    SessionAnalysis,
    SessionContext,
    TuneChange,
    Verdict,
    Where,
)
from .session import analyze_session

__all__ = [
    "__version__",
    "BoardItem",
    "CornerSummary",
    "Finding",
    "LapAnalysis",
    "LapContext",
    "LapMetrics",
    "LiveAnalysis",
    "LiveAnalyzer",
    "Recommendation",
    "SessionAnalysis",
    "SessionContext",
    "TuneChange",
    "Verdict",
    "Where",
    "analyze_lap",
    "analyze_session",
]
