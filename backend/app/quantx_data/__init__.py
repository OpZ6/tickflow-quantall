"""Independent, deterministic QuantX data pipeline for TickFlow.

This package deliberately owns only market-data ingestion, normalization,
calculation and structured publication.  It never imports an LLM/report
writer and never reads ``apps/quantx/output``.
"""

from .pipeline import PipelineError, run_pipeline

__all__ = ["PipelineError", "run_pipeline"]
