"""Pydantic response models for the occupation routes.

These define what GET /api/v1/occupations/search and
GET /api/v1/occupations/{id} actually return - both for FastAPI to
validate the response against before sending it, and so Swagger shows
a real shape instead of "Successful Response" with nothing underneath.
"""

from pydantic import BaseModel


class OccupationMatch(BaseModel):
    occupation_id: int
    title: str


class OccupationSearchResponse(BaseModel):
    query: str
    count: int
    matches: list[OccupationMatch]
    fallback_available: bool
    fallback_suggestions: list[OccupationMatch] = []
    message: str | None = None


class OccupationDetail(BaseModel):
    id: int
    title: str
    aliases: list[str]
    description: str | None = None
    tasks: list[str]
    median_weekly_earnings: float | None = None
    part_time_share_pct: float | None = None
    female_share_pct: float | None = None
    profile_source_id: int | None = None


class Destination(BaseModel):
    occupation_id: int
    title: str
    share: float
    source_id: int
    tag: str
    body_load_band: str | None = None
    region_share_percentage: float | None = None
    tier: str | None = None


class DestinationsResponse(BaseModel):
    occupation_id: int
    is_fallback: bool
    group: str | None = None
    destinations: list[Destination]


class DestinationDetail(BaseModel):
    occupation_id: int
    title: str
    share: float
    source_id: int
    tier: str | None = None


class BodyRegionContributor(BaseModel):
    variable: str
    score: float


class BodyRegion(BaseModel):
    region: str
    score: float | None = None
    contributors: list[BodyRegionContributor]
    message: str | None = None


class BodyRegionsResponse(BaseModel):
    occupation_id: int
    title: str
    body_regions: list[BodyRegion]
    overall_exposure_percentile: float | None = None


class InjuryInsight(BaseModel):
    tier: str
    model_name: str
    model_version: str
    generated_at: str


class InjuryInsightResponse(BaseModel):
    occupation_id: int
    title: str
    insight: InjuryInsight | None = None
    message: str | None = None


class AiExposureResponse(BaseModel):
    occupation_id: int
    title: str
    occupation_matrix_group: str | None = None
    automation_exposure: float | None = None
    automation_sd: float | None = None
    augmentation_exposure: float | None = None
    augmentation_sd: float | None = None
    rate_of_skill_change: float | None = None
    high_fit_transition_rate: float | None = None
    entry_level_ad_share: float | None = None
    source_id: int | None = None
    message: str | None = None


class PayGapSpecialization(BaseModel):
    anzsco_6digit_code: str
    anzsco_6digit_title: str
    segregation_intensity: str | None = None
    female_income_median: float | None = None
    male_income_median: float | None = None
    gender_pay_gap: float | None = None
    hours_difference: float | None = None
    ten_year_pay_gap: float | None = None


class PayGapResponse(BaseModel):
    occupation_id: int
    title: str
    specializations: list[PayGapSpecialization]
    source_id: int | None = None
    message: str | None = None
