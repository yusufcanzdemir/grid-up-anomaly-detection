from dataclasses import dataclass
from enum import Enum

class AlarmLifecycle(str, Enum):
    CRITICAL = "CRITICAL"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    NOT_RESOLVED = "NOT_RESOLVED"
    FALSE_ALARM = "FALSE_ALARM"

# Alias for backwards compatibility with the ai package
AlarmStatus = AlarmLifecycle

@dataclass
class Alarm:
    id: int
    panel: str
    location: str
    error: str = ""
    temperature: float = 0.0
    voltage: float = 0.0
    current: float = 0.0
    fan: bool = False
    humidity: int = 0
    status: AlarmLifecycle = AlarmLifecycle.CRITICAL
    
    # AI Alanları
    ai_status: str = ""
    suspected_condition: str = ""
    reasons: list = None
