"""Pydantic models for AI-extracted facts. Every fact carries a page citation."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GuidanceItem(BaseModel):
    metric: str
    statement: str
    direction: Literal["up", "flat", "down"]
    horizon: str
    page: int


class RiskItem(BaseModel):
    category: str
    description: str
    severity: int = Field(ge=1, le=5)
    page: int


class SegmentItem(BaseModel):
    segment_name: str
    revenue_eur_m: float
    fiscal_year: int
    page: int


class ManagementTone(BaseModel):
    label: Literal["positive", "neutral", "cautious"]
    rationale: str


class ExtractionPayload(BaseModel):
    """Schema sent to the LLM as the tool input_schema."""

    guidance: list[GuidanceItem]
    risks: list[RiskItem]
    segments: list[SegmentItem]
    management_tone: ManagementTone


class Extraction(BaseModel):
    ticker: str
    fiscal_year: int
    model: str
    extracted_at: datetime
    guidance: list[GuidanceItem]
    risks: list[RiskItem]
    segments: list[SegmentItem]
    management_tone: ManagementTone
    rejected_count: int = 0
