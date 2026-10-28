"""City -> areas lookup (OpenStreetMap Nominatim), with the network faked."""
import pytest
import requests

from app.engine import areas


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(areas, "_PAUSE_S", 0)
    areas._mem_cache.clear()
    yield
    areas._mem_cache.clear()


class Resp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def place(name, kind="suburb", lat=18.5, lon=73.8, pid=None, category="place"):
    return {"place_id": pid or hash((name, kind)) % 10**8, "name": name, "category": category,
            "type": kind, "lat": str(lat), "lon": str(lon)}


PUNE = [{"name": "Pune", "lat": "18.52", "lon": "73.85", "boundingbox": ["18.4", "18.6", "73.7", "74.0"],
         "address": {"country_code": "in"}}]


class FakeHttp:
    """``by_kind`` maps a searched kind ("suburb"...) to the list of rows Nominatim would return."""

    def __init__(self, geocode=PUNE, by_kind=None):
        self.geocode, self.by_kind, self.calls = geocode, by_kind or {}, []

    def get(self, url, params=None, **kw):
        self.calls.append(dict(params))
        if "addressdetails" in params:
            return Resp(self.geocode)
        assert params["bounded"] == 1 and params["viewbox"] == "73.7,18.6,74.0,18.4"
        return Resp(self.by_kind.get(params["q"], []))


def test_lists_areas_for_a_city_sorted_and_deduplicated():
    rows = [place("Kothrud"), place("Baner"), place("Aundh"), place("baner"),
            place("A Shop", category="shop"), place("Some Hill", kind="hill")]
    res = areas.localities("Pune", http=FakeHttp(by_kind={"suburb": rows}))
    assert res["source"] == "online" and res["country"] == "in" and res["city"] == "Pune"
    assert [a["name"] for a in res["presets"]] == ["Aundh", "Baner", "Kothrud"]
    assert set(res["presets"][0]) == {"name", "lat", "lng"}


def test_second_lookup_comes_from_the_cache():
    areas.localities("Pune", http=FakeHttp(by_kind={"suburb": [place("A"), place("B"), place("C")]}))
    res = areas.localities("  pune ", http=FakeHttp(geocode=[]))   # would find nothing if it hit the network
    assert res["source"] == "cache" and len(res["presets"]) == 3
    assert areas.find_area("b", "Pune")[0] == "B"


def test_falls_back_to_smaller_kinds_when_few_suburbs():
    http = FakeHttp(by_kind={"suburb": [place("Only")],
                             "neighbourhood": [place("N1", "neighbourhood"), place("N2", "neighbourhood")],
                             "quarter": [place("Q1", "quarter")]})
    res = areas.localities("Pune", http=http)
    assert [a["name"] for a in res["presets"]] == ["N1", "N2", "Only", "Q1"]


def test_pages_through_a_big_city():
    page1 = [place(f"S{i:02d}", pid=i) for i in range(40)]
    page2 = [place("Z-last", pid=100)]

    class Paged(FakeHttp):
        def get(self, url, params=None, **kw):
            if params.get("exclude_place_ids"):
                self.calls.append(dict(params))
                return Resp(page2)
            return super().get(url, params=params, **kw)

    res = areas.localities("Pune", http=Paged(by_kind={"suburb": page1}))
    assert len(res["presets"]) == 41 and res["presets"][-1]["name"] == "Z-last"


def test_unknown_place_gives_a_friendly_error():
    res = areas.localities("Xyzzyland", http=FakeHttp(geocode=[]))
    assert res["presets"] == [] and "could not find" in res["error"] and not res.get("offline")


def test_no_internet_keeps_the_city_so_areas_can_be_typed():
    class Offline:
        def get(self, *a, **k):
            raise requests.ConnectionError("down")

    res = areas.localities("Pune", http=Offline())
    assert res["offline"] is True and res["city"] == "Pune" and res["presets"] == [] and res["error"]


def test_a_place_with_no_listed_areas_is_not_cached_as_empty():
    areas.localities("Pune", http=FakeHttp())
    assert areas._cached("pune") is None


def test_custom_area_has_no_coordinates():
    assert areas.find_area("My Neighbourhood", "Pune") == ("My Neighbourhood", None, None)
