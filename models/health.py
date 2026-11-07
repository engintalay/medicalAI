# models/health.py - HealthMetrics Model & Schema

from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List


# --- Request Models ---

class HealthMetricCreate(BaseModel):
    """HealthMetrics créate request"""
    metric_name: str  # e.g: 'weight', 'height', 'blood_pressure'
    value: float
    unit: str  # e.g: 'kg', 'cm', 'psi'
    recorded_at: Optional[datetime] = None


class HealthMetricUpdate(BaseModel):
    """HealthMetrics update request"""
    metric_name: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    recorded_at: Optional[datetime] = None


# --- Response Models ---

class HealthMetric(BaseModel):
    """HealthMetrics response model"""
    metric_id: int
    user_id: int
    metric_name: str
    value: float
    unit: str
    recorded_at: datetime

    class Config:
        from_attributes = True


class HealthMetricResponse(BaseModel):
    """HealthMetrics API response"""
    success: bool = True
    message: Optional[str] = None
    data: Optional[HealthMetric] = None
    metrics: Optional[List[HealthMetric]] = None
    pagination: Optional[dict] = None


# --- Utility Functions ---

def format_metric_response(metric_data) -> HealthMetric:
    """Format database row to HealthMetric model"""
    return HealthMetric(
        metric_id=metric_data['metric_id'],
        user_id=metric_data['user_id'],
        metric_name=metric_data['metric_name'],
        value=float(metric_data['value']),
        unit=metric_data['unit'],
        recorded_at=metric_data['recorded_at']
    )


def format_metric_list(metrics_data: List[dict]) -> List[HealthMetric]:
    """Format list of database rows to HealthMetric models"""
    return [format_metric_response(m) for m in metrics_data]
