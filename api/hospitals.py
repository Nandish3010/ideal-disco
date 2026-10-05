"""MOCK capability, bed and diversion roster per corridor, used by the routing agent. Not real hospital data: capabilities,
bed counts, trauma levels, door-to-balloon times and diversion are invented for the demo and coordinates are approximate.
A real roster would come from agency feeds."""

import zlib

CAPS = {"cath_lab", "stroke_unit", "trauma", "burns", "paediatrics", "icu", "dialysis", "obstetrics"}
DIVERSION_PCT = {
    "blr_apollo_bg": 30
}  # mock live feed: this hospital is on diversion for this share of run ids


def _h(id, name, lat, lng, caps, beds, *, trauma_level=None, d2b=None, diversion=False):
    assert set(caps) <= CAPS
    return {
        "id": id,
        "name": name,
        "lat": lat,
        "lng": lng,
        "capabilities": sorted(caps),
        "beds_available": beds,
        "diversion": diversion,  # static roster flag; on_diversion() adds the mock live feed
        "trauma_level": trauma_level,  # 1 (highest) to 3, None: not a trauma centre
        "cath_lab_door_to_balloon_min": d2b,  # typical minutes, None without a cath lab
        "mock": True,
    }


HOSPITALS = {
    "blr": [
        _h(
            "blr_jayadeva",
            "Jayadeva Institute of Cardiovascular Sciences",
            12.9185,
            77.599,
            {"cath_lab", "stroke_unit", "icu", "dialysis"},
            4,
            d2b=38,
        ),
        _h(
            "blr_apollo_bg",
            "Apollo Hospital Bannerghatta Road",
            12.8957,
            77.5975,
            {"trauma", "burns", "cath_lab", "icu"},
            2,
            trauma_level=1,
            d2b=52,
        ),
        _h(
            "blr_fortis_bg",
            "Fortis Hospital Bannerghatta Road",
            12.8942,
            77.6008,
            {"trauma", "stroke_unit", "paediatrics", "icu", "obstetrics", "dialysis"},
            3,
            trauma_level=2,
        ),
    ],
    "hyd": [
        _h(
            "hyd_continental",
            "Continental Hospitals",
            17.4185,
            78.34,
            {"cath_lab", "trauma", "stroke_unit", "icu", "dialysis"},
            5,
            trauma_level=2,
            d2b=44,
        ),
        _h(
            "hyd_care_hitech",
            "Care Hospitals Hi-Tech City",
            17.4435,
            78.3772,
            {"cath_lab", "burns", "paediatrics", "icu", "obstetrics"},
            2,
            d2b=58,
        ),
        _h(
            "hyd_rainbow_kondapur",
            "Rainbow Children's Hospital Kondapur",
            17.4627,
            78.3646,
            {"paediatrics", "trauma", "icu"},
            6,
            trauma_level=3,
        ),
    ],
}


def by_id(hospital_id):
    return next((h for hs in HOSPITALS.values() for h in hs if h["id"] == hospital_id), None)


def on_diversion(h, run_id):
    """True when the hospital is on diversion for this run: the roster flag, or the mock feed (a fixed share of run ids
    by CRC32, so the same run always gets the same answer). No run id: the roster flag only."""
    pct = DIVERSION_PCT.get(h["id"], 0)
    return bool(h["diversion"] or (run_id and zlib.crc32(str(run_id).encode()) % 100 < pct))
