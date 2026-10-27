"""Coalition membership in the two world wars (shared by fields_polygons.py and fronts.py)."""
from __future__ import annotations

# Belligerent membership (standard chronology: entry into the war, armistice or
# surrender, change of side). Not individually cited: it only gives each
# coalition a weak background over the land its members control (de jure, or
# occupied per the verified occupation research), so a line exists where cited
# front towns are sparse; cited control always outweighs it.
MEMBERS = {
    "entente": {"france": [(1914.58, 1918.87)], "britain": [(1914.59, 1918.87)], "russia": [(1914.58, 1917.95)],
                "belgium": [(1914.59, 1918.87)], "serbia": [(1914.57, 1918.87)], "montenegro": [(1914.6, 1918.87)],
                "italy": [(1915.39, 1918.87)], "romania": [(1916.66, 1918.35)], "portugal": [(1916.18, 1918.87)],
                "greece": [(1917.49, 1918.87)]},
    "central-powers": {"germany": [(1914.58, 1918.87)], "austria-hungary": [(1914.57, 1918.84)],
                       "ottoman": [(1914.83, 1918.83)], "bulgaria": [(1915.78, 1918.745)]},
    "allies": {"poland": [(1939.67, 1939.76)], "britain": [(1939.67, 1945.36)], "france": [(1939.67, 1940.47), (1944.65, 1945.36)],
               "norway": [(1940.27, 1940.44)], "netherlands": [(1940.36, 1940.37)], "belgium": [(1940.36, 1940.41), (1944.68, 1945.36)],
               "luxembourg": [(1940.36, 1940.37)], "greece": [(1940.82, 1941.33)], "yugoslavia": [(1941.27, 1941.30)],
               "russia": [(1941.47, 1945.36)], "romania": [(1944.65, 1945.36)], "bulgaria": [(1944.69, 1945.36)],
               "italy": [(1943.78, 1945.36)]},
    "axis": {"germany": [(1939.67, 1945.35)], "italy": [(1940.44, 1943.69)], "hungary": [(1941.49, 1945.30)],
             "romania": [(1941.47, 1944.65)], "bulgaria": [(1941.2, 1944.69)], "finland": [(1941.48, 1944.71)]},
}


def coalition_of(side: str, y: float) -> str | None:
    for co, mem in MEMBERS.items():
        for a, b in mem.get(side, []):
            if a <= y < b:
                return co
    return None
