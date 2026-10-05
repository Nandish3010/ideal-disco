"""MOCK capability and bed roster per corridor, used by the routing agent. Not real hospital data: capabilities and
bed counts are invented for the demo and coordinates are approximate. A real roster would come from agency feeds."""

CAPS = {"cath_lab", "trauma", "burns", "stroke_unit", "paediatrics"}


def _h(id, name, lat, lng, caps, beds):
    assert set(caps) <= CAPS
    return {"id": id, "name": name, "lat": lat, "lng": lng, "capabilities": sorted(caps), "beds_available": beds, "mock": True}


HOSPITALS = {
    "blr": [
        _h("blr_jayadeva", "Jayadeva Institute of Cardiovascular Sciences", 12.9185, 77.599, {"cath_lab", "stroke_unit"}, 4),
        _h("blr_apollo_bg", "Apollo Hospital Bannerghatta Road", 12.8957, 77.5975, {"trauma", "burns", "cath_lab"}, 2),
        _h("blr_fortis_bg", "Fortis Hospital Bannerghatta Road", 12.8942, 77.6008, {"trauma", "stroke_unit", "paediatrics"}, 3),
    ],
    "hyd": [
        _h("hyd_continental", "Continental Hospitals", 17.4185, 78.34, {"cath_lab", "trauma", "stroke_unit"}, 5),
        _h("hyd_care_hitech", "Care Hospitals Hi-Tech City", 17.4435, 78.3772, {"cath_lab", "burns", "paediatrics"}, 2),
        _h("hyd_rainbow_kondapur", "Rainbow Children's Hospital Kondapur", 17.4627, 78.3646, {"paediatrics", "trauma"}, 6),
    ],
}


def by_id(hospital_id):
    return next((h for hs in HOSPITALS.values() for h in hs if h["id"] == hospital_id), None)
