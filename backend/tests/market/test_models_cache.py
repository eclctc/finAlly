from app.market.cache import PriceCache
from app.market.models import PriceUpdate


def test_price_update_derived_fields():
    up = PriceUpdate("AAPL", 101.0, 100.0, 1.0)
    assert up.change == 1.0
    assert abs(up.change_percent - 1.0) < 1e-9
    assert up.direction == "up"
    assert PriceUpdate("A", 99.0, 100.0, 1.0).direction == "down"
    assert PriceUpdate("A", 100.0, 100.0, 1.0).direction == "flat"


def test_zero_previous_price_safe():
    assert PriceUpdate("A", 1.0, 0.0, 1.0).change_percent == 0.0


def test_day_change_uses_reference():
    up = PriceUpdate("A", 110.0, 109.0, 1.0, reference_price=100.0)
    assert abs(up.day_change_percent - 10.0) < 1e-9
    assert PriceUpdate("A", 101.0, 100.0, 1.0).day_change_percent == up.__class__(
        "A", 101.0, 100.0, 1.0
    ).change_percent


def test_to_dict_keys():
    d = PriceUpdate("AAPL", 101.0, 100.0, 5.0).to_dict()
    assert d["ticker"] == "AAPL"
    assert d["direction"] == "up"
    assert d["timestamp"] == 5.0
    assert {"price", "previous_price", "change", "change_percent"} <= d.keys()


def test_cache_first_update_previous_equals_price():
    c = PriceCache()
    u = c.update("aapl", 190.0)
    assert u.ticker == "AAPL"
    assert u.previous_price == 190.0


def test_cache_tracks_previous_and_reference():
    c = PriceCache()
    c.update("AAPL", 100.0, reference_price=99.0)
    u = c.update("AAPL", 101.0)
    assert u.previous_price == 100.0
    assert u.reference_price == 99.0


def test_cache_get_all_is_copy_and_remove_bumps_version():
    c = PriceCache()
    c.update("AAPL", 1.0)
    snap = c.get_all()
    snap.clear()
    assert c.get_price(" aapl ") == 1.0
    v = c.version
    c.remove("AAPL")
    assert c.get("AAPL") is None
    assert c.version == v + 1
    c.remove("AAPL")  # missing: no version change
    assert c.version == v + 1


def test_version_increments_on_update():
    c = PriceCache()
    v = c.version
    c.update("A", 1.0)
    c.update("A", 2.0)
    assert c.version == v + 2
