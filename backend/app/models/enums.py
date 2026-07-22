from enum import Enum


class ReportCategory(str, Enum):
    ROAD = "Road"
    WATER = "Water Supply"
    ELECTRICITY = "Electricity"
    GARBAGE = "Garbage"
    DRAINAGE = "Drainage"
    STREET_LIGHT = "Street Light"
    TRAFFIC = "Traffic"
    PUBLIC_TRANSPORT = "Public Transport"
    CRIME = "Crime"
    MEDICAL = "Medical"
    FIRE = "Fire"
    OTHER = "Other"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"