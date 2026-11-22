"""Request bodies for the API.

Validation that needs the city graph (does this location exist? is that a real
road?) cannot live in a schema, because the graph belongs to the session; the
routes in `app.py` check those and answer 422 with the list of valid names.
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class IncidentIn(BaseModel):
    kind: str = Field(..., description="Fire, Accident or Medical")
    location: str = Field(..., description="city name")
    severity: int = Field(3, ge=1, le=5)
    people: int = Field(10, ge=1, le=100_000)


class BatchIn(BaseModel):
    """Several incidents reported at the same simulated moment.

    Reporting them together is not the same as reporting them one after
    another: the CSP sees the whole set at once and allocates by priority.
    """
    items: List[IncidentIn] = Field(..., min_length=1, max_length=20)


class RoadIn(BaseModel):
    a: str
    b: str
    closed: Optional[bool] = Field(None, description="omit to toggle")


class ControlIn(BaseModel):
    paused: Optional[bool] = None
    speed: Optional[float] = Field(None, gt=0, le=64)
    random_events: Optional[bool] = None


class ScenarioIn(BaseModel):
    """A scenario in plain English, for the prompt engine."""
    text: str = Field(..., min_length=1, max_length=2000)
    use_llm: bool = Field(False, description="allow the optional LLM fallback")
    run: bool = Field(True, description="queue the events, rather than only parsing them")


class DemoIn(BaseModel):
    name: str = Field("showcase", description="a scenario from the scenarios file")
    reset: bool = True
