"""
Aria Observability — switch between LangSmith
Set OBSERVABILITY_BACKEND=langsmith 
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)

BACKEND = os.getenv("OBSERVABILITY_BACKEND", "langsmith")


class AriaObservability:
    """Unified observability interface for Aria."""

    def __init__(self):
        self.backend  = BACKEND
        self._langfuse = None

    def create_trace(self, name: str, brief_id: str, topics: list):
        """Create a trace in the configured backend."""
        if self.backend == "langfuse":
            return self._langfuse.trace(
                name     = name,
                user_id  = brief_id,
                metadata = {"brief_id": brief_id, "topics": topics},
                tags     = ["production"]
            )
        # LangSmith: trace() context manager handles it automatically
        return None

    def record_score(self, trace_id: str, score: float, comment: str = ""):
        """Record a quality score."""
        if self.backend == "langfuse" and self._langfuse:
            self._langfuse.score(
                trace_id = trace_id,
                name     = "critic_score",
                value    = score,
                comment  = comment
            )

    def flush(self):
        """Flush pending events — critical in Lambda."""
        if self.backend == "langfuse" and self._langfuse:
            self._langfuse.flush()


# Singleton
observability = AriaObservability()