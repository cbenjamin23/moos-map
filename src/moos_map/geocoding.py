from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from . import __version__
from .errors import MoosMapError, ValidationError


PHOTON_SEARCH_URL = "https://photon.komoot.io/api/"
WEB_MERCATOR_LATITUDE_LIMIT = 85.05112878


class GeocodingError(MoosMapError):
    """A remote location search could not be completed."""


@dataclass(frozen=True, slots=True)
class SearchBounds:
    west: float
    south: float
    east: float
    north: float


@dataclass(frozen=True, slots=True)
class SearchResult:
    label: str
    latitude: float
    longitude: float
    bounds: SearchBounds | None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["bounds"] = asdict(self.bounds) if self.bounds else None
        return result


class PhotonGeocoder:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        cache_ttl_seconds: float = 300,
        max_cache_entries: int = 256,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=5,
            follow_redirects=True,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    f"moos-map/{__version__} "
                    "(+https://github.com/cbenjamin23/moos-map)"
                ),
            },
        )
        self._cache_ttl_seconds = cache_ttl_seconds
        self._max_cache_entries = max_cache_entries
        self._cache: dict[
            tuple[str, float | None, float | None, int, int],
            tuple[float, tuple[SearchResult, ...]],
        ] = {}
        self._cache_lock = threading.Lock()

    def search(
        self,
        query: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        zoom: int = 12,
        limit: int = 5,
    ) -> list[SearchResult]:
        cleaned_query = " ".join(query.split())
        if len(cleaned_query) < 3:
            raise ValidationError("Enter at least three characters to search")
        if len(cleaned_query) > 200:
            raise ValidationError("Location searches may not exceed 200 characters")
        if (latitude is None) != (longitude is None):
            raise ValidationError("Search latitude and longitude must be provided together")
        if latitude is not None and not -90 <= latitude <= 90:
            raise ValidationError("Search latitude must be between -90 and 90")
        if longitude is not None and not -180 <= longitude <= 180:
            raise ValidationError("Search longitude must be between -180 and 180")
        if not 0 <= zoom <= 24:
            raise ValidationError("Search zoom must be between 0 and 24")
        if not 1 <= limit <= 10:
            raise ValidationError("Search result limit must be between 1 and 10")

        cache_key = (
            cleaned_query.casefold(),
            round(latitude, 2) if latitude is not None else None,
            round(longitude, 2) if longitude is not None else None,
            zoom,
            limit,
        )
        cached = self._cached(cache_key)
        if cached is not None:
            return list(cached)

        params: dict[str, str | int | float] = {
            "q": cleaned_query,
            # Ask Photon for spare candidates so duplicate OSM features do not
            # leave the user-facing list shorter than requested.
            "limit": min(limit * 2, 10),
        }
        if latitude is not None and longitude is not None:
            params.update({"lat": latitude, "lon": longitude, "zoom": zoom})

        try:
            response = self._client.get(PHOTON_SEARCH_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GeocodingError(
                "Location search is temporarily unavailable. Coordinates still work."
            ) from exc

        results = self._normalize(payload, limit=limit)
        self._store(cache_key, tuple(results))
        return results

    def _cached(
        self,
        key: tuple[str, float | None, float | None, int, int],
    ) -> tuple[SearchResult, ...] | None:
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is None:
                return None
            expires_at, results = cached
            if expires_at <= now:
                del self._cache[key]
                return None
            return results

    def _store(
        self,
        key: tuple[str, float | None, float | None, int, int],
        results: tuple[SearchResult, ...],
    ) -> None:
        with self._cache_lock:
            if len(self._cache) >= self._max_cache_entries:
                oldest = min(self._cache, key=lambda item: self._cache[item][0])
                del self._cache[oldest]
            self._cache[key] = (time.monotonic() + self._cache_ttl_seconds, results)

    @staticmethod
    def _normalize(payload: Any, *, limit: int) -> list[SearchResult]:
        features = payload.get("features", []) if isinstance(payload, dict) else []
        if not isinstance(features, list):
            return []

        results: list[SearchResult] = []
        seen_labels: set[str] = set()
        for feature in features:
            result = _normalize_feature(feature)
            if result is None:
                continue
            label_key = result.label.casefold()
            if label_key in seen_labels:
                continue
            seen_labels.add(label_key)
            results.append(result)
            if len(results) >= limit:
                break
        return results


def _normalize_feature(feature: Any) -> SearchResult | None:
    if not isinstance(feature, dict):
        return None
    geometry = feature.get("geometry")
    properties = feature.get("properties")
    if not isinstance(geometry, dict) or not isinstance(properties, dict):
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None

    try:
        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
    except (TypeError, ValueError):
        return None
    if not (
        -180 <= longitude <= 180
        and -WEB_MERCATOR_LATITUDE_LIMIT <= latitude <= WEB_MERCATOR_LATITUDE_LIMIT
    ):
        return None

    label_parts: list[str] = []
    for key in ("name", "city", "state", "country"):
        value = properties.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if value.casefold() not in {part.casefold() for part in label_parts}:
            label_parts.append(value)
    if not label_parts:
        return None

    bounds = _normalize_extent(properties.get("extent"))
    return SearchResult(
        label=", ".join(label_parts),
        latitude=latitude,
        longitude=longitude,
        bounds=bounds,
    )


def _normalize_extent(extent: Any) -> SearchBounds | None:
    if not isinstance(extent, list) or len(extent) != 4:
        return None
    try:
        first_lon, first_lat, second_lon, second_lat = map(float, extent)
    except (TypeError, ValueError):
        return None

    west, east = sorted((first_lon, second_lon))
    south, north = sorted((first_lat, second_lat))
    if not (
        -180 <= west < east <= 180
        and -WEB_MERCATOR_LATITUDE_LIMIT
        <= south
        < north
        <= WEB_MERCATOR_LATITUDE_LIMIT
    ):
        return None
    return SearchBounds(west=west, south=south, east=east, north=north)


_default_geocoder = PhotonGeocoder()


def search_locations(
    query: str,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    zoom: int = 12,
    limit: int = 5,
) -> list[SearchResult]:
    return _default_geocoder.search(
        query,
        latitude=latitude,
        longitude=longitude,
        zoom=zoom,
        limit=limit,
    )
