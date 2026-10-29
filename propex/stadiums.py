"""Stadium locations (keyed by nflverse stadium_id) for weather lookups."""

# stadium_id: (latitude, longitude, roof type)
# roof type: "outdoor", "dome" (always covered), or "retractable"
STADIUMS = {
    "ATL97": (33.7554, -84.4008, "retractable"),
    "BAL00": (39.2780, -76.6227, "outdoor"),
    "BOS00": (42.0909, -71.2643, "outdoor"),
    "BUF00": (42.7738, -78.7870, "outdoor"),
    "CAR00": (35.2258, -80.8528, "outdoor"),
    "CHI98": (41.8623, -87.6167, "outdoor"),
    "CIN00": (39.0955, -84.5161, "outdoor"),
    "CLE00": (41.5061, -81.6995, "outdoor"),
    "DAL00": (32.7473, -97.0945, "retractable"),
    "DEN00": (39.7439, -105.0201, "outdoor"),
    "DET00": (42.3400, -83.0456, "dome"),
    "GNB00": (44.5013, -88.0622, "outdoor"),
    "HOU00": (29.6847, -95.4107, "retractable"),
    "IND00": (39.7601, -86.1639, "retractable"),
    "JAX00": (30.3239, -81.6373, "outdoor"),
    "KAN00": (39.0489, -94.4839, "outdoor"),
    "LAX01": (33.9535, -118.3392, "dome"),
    "LON00": (51.5560, -0.2796, "outdoor"),
    "LON02": (51.6043, -0.0662, "outdoor"),
    "MAD01": (40.4531, -3.6883, "retractable"),
    "MEL00": (-37.8200, 144.9834, "outdoor"),
    "MEX00": (19.3029, -99.1505, "outdoor"),
    "MIA00": (25.9580, -80.2389, "outdoor"),
    "MIN01": (44.9737, -93.2577, "dome"),
    "MUN01": (48.2188, 11.6247, "outdoor"),
    "NAS00": (36.1665, -86.7713, "outdoor"),
    "NOR00": (29.9511, -90.0812, "dome"),
    "NYC01": (40.8135, -74.0745, "outdoor"),
    "PAR00": (48.9245, 2.3602, "outdoor"),
    "PHI00": (39.9008, -75.1675, "outdoor"),
    "PHO00": (33.5276, -112.2626, "retractable"),
    "PIT00": (40.4468, -80.0158, "outdoor"),
    "RIO00": (-22.9122, -43.2302, "outdoor"),
    "SEA00": (47.5952, -122.3316, "outdoor"),
    "SFO01": (37.4030, -121.9700, "outdoor"),
    "TAM00": (27.9759, -82.5033, "outdoor"),
    "VEG00": (36.0909, -115.1833, "dome"),
    "WAS00": (38.9076, -76.8645, "outdoor"),
}


def lookup(stadium_id, stadium_name=""):
    # nflverse sometimes files a London game under the home team's usual id
    if "Tottenham" in (stadium_name or ""):
        stadium_id = "LON02"
    elif "Wembley" in (stadium_name or ""):
        stadium_id = "LON00"
    return STADIUMS.get(stadium_id)


def is_covered(stadium_id, stadium_name, schedule_roof):
    """True when weather can't affect the game (dome, or retractable roof closed)."""
    info = lookup(stadium_id, stadium_name)
    if schedule_roof in ("dome", "closed"):
        return True
    if schedule_roof in ("open", "outdoors"):
        return False
    # Roof not announced yet: retractable roofs are usually closed
    return info is not None and info[2] in ("dome", "retractable")
