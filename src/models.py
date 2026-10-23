"""Data classes shared by the modules."""
from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    """A monitored location (default city or result of the geocoding API)."""
    name: str
    lat: float
    lon: float
    country: str = ""

    @property
    def label(self) -> str:
        """Display name, with the country to tell homonyms apart (e.g. "Paris (France)")."""
        return f"{self.name} ({self.country})" if self.country else self.name

