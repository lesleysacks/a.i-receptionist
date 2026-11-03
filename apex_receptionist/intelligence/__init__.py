"""Code-first, AI-assisted response pipeline for idle receptionist messages.

The conversation FSM stays authoritative for an in-progress booking. This
package only interprets idle messages: deterministic facts first, optional AI
second. It never selects a tenant and never executes model output.
"""

from apex_receptionist.intelligence.pipeline import ResponsePipeline
from apex_receptionist.intelligence.types import (
    Classification,
    Intent,
    PipelineDecision,
    PipelineResult,
)

__all__ = [
    "Classification",
    "Intent",
    "PipelineDecision",
    "PipelineResult",
    "ResponsePipeline",
]
