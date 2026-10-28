from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NextStep(StrictModel):
    action: str = Field(min_length=1)
    owner: str | None
    deadline: str | None
    status: Literal["agreed", "proposed"]


class DialogReport(StrictModel):
    client_name: str | None
    topic: str = Field(min_length=1)
    main_request: str = Field(min_length=1)
    mood: Literal["positive", "neutral", "negative", "mixed", "unknown"]
    deadline: str | None
    budget: str | None
    requirements: list[str]
    next_steps: list[NextStep]
    open_questions: list[str]
