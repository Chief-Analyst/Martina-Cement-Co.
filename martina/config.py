"""Settings and business rules.

Every number a planner might want to argue about lives here, with a default
and an environment variable to override it, so the rules are visible in one
place rather than buried in the code.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:                                   # dotenv is optional
    pass

ROOT = Path(__file__).resolve().parent.parent


def _f(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def _i(name, default):
    return int(_f(name, default))


@dataclass(frozen=True)
class Rules:
    # Order book
    cover_critical_days: float = _f("MC_COVER_CRITICAL_DAYS", 1.25)
    cover_watch_days: float = _f("MC_COVER_WATCH_DAYS", 3.5)
    behaviour_poor: float = _f("MC_BEHAVIOUR_POOR", 0.45)      # lifted / ordered
    behaviour_fair: float = _f("MC_BEHAVIOUR_FAIR", 0.75)
    partial_alert_days: int = _i("MC_PARTIAL_ALERT_DAYS", 5)
    fifo_wait_days: int = _i("MC_FIFO_WAIT_DAYS", 2)
    planning_horizons: tuple = (1, 2, 3, 5, 7)
    ageing_buckets: tuple = ((0, 3, "0-3"), (4, 7, "4-7"), (8, 14, "8-14"),
                             (15, 30, "15-30"), (31, 60, "31-60"),
                             (61, 10_000, "60+"))

    # Logistics. Site time counts only inside the receiving window.
    site_open_hour: int = _i("MC_SITE_OPEN_HOUR", 7)
    site_close_hour: int = _i("MC_SITE_CLOSE_HOUR", 18)
    site_watch_hours: float = _f("MC_SITE_WATCH_HOURS", 5.0)   # line up alternatives
    site_reroute_hours: float = _f("MC_SITE_REROUTE_HOURS", 8.0)
    site_escalate_hours: float = _f("MC_SITE_ESCALATE_HOURS", 16.0)
    idle_alert_hours: float = _f("MC_IDLE_ALERT_HOURS", 4.0)
    gps_lost_minutes: int = _i("MC_GPS_LOST_MINUTES", 30)
    shift_hours: tuple = (7, 19)
    reroute_radii_km: tuple = (15, 30, 60)
    truck_speed_kmh: float = _f("MC_TRUCK_SPEED_KMH", 42.0)
    road_factor: float = _f("MC_ROAD_FACTOR", 1.28)            # road km / straight km


@dataclass(frozen=True)
class Settings:
    data_source: str = os.environ.get("MC_DATA_SOURCE", "synthetic")   # synthetic | csv
    data_dir: Path = Path(os.environ.get("MC_DATA_DIR", ROOT / "data"))
    seed: int = _i("MC_SEED", 2024)
    refresh_minutes: int = _i("MC_REFRESH_MINUTES", 240)
    sim_minutes_per_second: float = _f("MC_SIM_MINUTES_PER_SECOND", 2.0)
    sim_history_days: int = _i("MC_SIM_HISTORY_DAYS", 60)
    fleet_size: int = _i("MC_FLEET_SIZE", 140)
    groq_api_key: str = os.environ.get("GROQ_API_KEY", "")
    groq_model: str = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    tomtom_api_key: str = os.environ.get("TOMTOM_API_KEY", "")
    smtp_host: str = os.environ.get("SMTP_HOST", "")
    smtp_port: int = _i("SMTP_PORT", 587)
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    smtp_sender: str = os.environ.get("SMTP_SENDER", "")
    debug: bool = os.environ.get("MC_DEBUG", "0") == "1"
    rules: Rules = field(default_factory=Rules)


SETTINGS = Settings()
RULES = SETTINGS.rules
