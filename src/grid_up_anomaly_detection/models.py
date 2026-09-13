#Genel veri modelleri (Alarm, Sensör verisi vb.)

from dataclasses import dataclass
from enum import Enum

class AlarmStatus(str, Enum):
    CRITICAL = "CRITICAL"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"

@dataclass
class Alarm:
    id: int
    panel: str
    location: str
    error: str
    temperature: float
    voltage: float
    current: float
    fan: bool
    humidity: int
    status: AlarmStatus = AlarmStatus.CRITICAL