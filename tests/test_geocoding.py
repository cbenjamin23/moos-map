from __future__ import annotations

import httpx
import pytest

from moos_map.errors import ValidationError
from moos_map.geocoding import GeocodingError, PhotonGeocoder


def test_photon_search_normalizes_results_and_caches_requests() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "geometry": {
                            "type": "Point",
                            "coordinates": [-121.9010668, 36.7999557],
                        },
                        "properties": {
                            "name": "Monterey Bay",
                            "state": "California",
                            "country": "United States",
                            "extent": [-122.1, 37.0, -121.7, 36.5],
                        },
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    geocoder = PhotonGeocoder(client=client)

    first = geocoder.search(
        "  Monterey   Bay ", latitude=36.8, longitude=-121.9, zoom=11
    )
    second = geocoder.search(
        "monterey bay", latitude=36.8, longitude=-121.9, zoom=11
    )

    assert first == second
    assert len(requests) == 1
    assert requests[0].url.params["q"] == "Monterey Bay"
    assert requests[0].url.params["lat"] == "36.8"
    assert requests[0].url.params["lon"] == "-121.9"
    assert requests[0].url.params["limit"] == "10"
    assert first[0].label == "Monterey Bay, California, United States"
    assert first[0].longitude == pytest.approx(-121.9010668)
    assert first[0].latitude == pytest.approx(36.7999557)
    assert first[0].bounds is not None
    assert first[0].bounds.west == pytest.approx(-122.1)
    assert first[0].bounds.south == pytest.approx(36.5)
    assert first[0].bounds.east == pytest.approx(-121.7)
    assert first[0].bounds.north == pytest.approx(37.0)


def test_photon_search_deduplicates_labels_and_keeps_ranked_order() -> None:
    places = [
        ("Reading", "Massachusetts", "United States", -71.1, 42.5),
        ("Reading", "England", "United Kingdom", -1.0, 51.4),
        ("Reading", "Massachusetts", "United States", -71.0, 42.6),
        ("Reading", "Pennsylvania", "United States", -75.9, 40.3),
        ("Reading", "Massachusetts", "United States", -71.2, 42.4),
        ("Reading", "California", "United States", -122.0, 38.0),
    ]
    features = [
        {
            "geometry": {"coordinates": [longitude, latitude]},
            "properties": {"name": name, "state": state, "country": country},
        }
        for name, state, country, longitude, latitude in places
    ]
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"features": features})
        )
    )

    results = PhotonGeocoder(client=client).search("Reading", limit=4)

    assert [result.label for result in results] == [
        "Reading, Massachusetts, United States",
        "Reading, England, United Kingdom",
        "Reading, Pennsylvania, United States",
        "Reading, California, United States",
    ]


def test_photon_search_ignores_invalid_features() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "features": [
                        {"geometry": {"coordinates": [0, 90]}, "properties": {"name": "Polar"}},
                        {"geometry": {"coordinates": [1, 2]}, "properties": {}},
                    ]
                },
            )
        )
    )

    assert PhotonGeocoder(client=client).search("invalid") == []


def test_photon_search_reports_upstream_failures() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    )

    with pytest.raises(GeocodingError, match="temporarily unavailable"):
        PhotonGeocoder(client=client).search("Boston")


def test_photon_search_validates_query_and_bias() -> None:
    geocoder = PhotonGeocoder(client=httpx.Client(transport=httpx.MockTransport(lambda request: None)))

    with pytest.raises(ValidationError, match="three characters"):
        geocoder.search("ab")
    with pytest.raises(ValidationError, match="provided together"):
        geocoder.search("Boston", latitude=42.36)
