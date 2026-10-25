from regions import REGIONS, region_prefers_pce, region_note


def test_regions_cover_major_areas():
    ids = {r["id"] for r in REGIONS}
    assert "global" in ids
    assert "us" in ids
    assert "us_pce" in ids
    assert "uk_europe" in ids
    assert "nordic" in ids
    assert "eastern_europe" in ids
    assert "caribbean" in ids
    assert "south_asia" in ids
    assert "east_asia" in ids
    assert "sub_saharan_africa" in ids
    assert len(REGIONS) >= 15


def test_only_us_pce_prefers_pce_by_default():
    assert region_prefers_pce("us_pce") is True
    assert region_prefers_pce("us") is False
    assert region_prefers_pce("global") is False
    assert region_prefers_pce("uk_europe") is False
    assert region_prefers_pce("south_asia", prefer_pce_flag=True) is True


def test_region_notes_are_honest():
    note = region_note("uk_europe")
    assert "SCORE2" in note or "PREVENT" in note
    assert region_note("global")
