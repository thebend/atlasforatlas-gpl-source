"""North America 1492–1900: map the scene's dated polygon sources onto sides.

Sources (see .cache/scenes/north-america/sources.json for licences):
  historical-basemaps snapshots   colonial claims + Indigenous nations, coarse, approximate; under a build
                                  profile that blocks it (none today; one whose data must not be GPL, such as
                                  exclusive paid content, would), Cliopatria's polity
                                  rows instead: colonial claims and the few Indigenous polities it maps
  OpenHistoricalMap (admin 2)     dated colonies, viceroyalties, republics, a few Indigenous polities
  Newberry AHCB states/territories US extent 1783–1900, academic, exact dates
  Royce cessions (USFS 2018)      land each nation held until it was ceded to the US

Claim weights (strength in the field): a homeland or organised state is 1.0; a
colonial or territorial claim over land Indigenous nations held is weaker, so
where both are mapped the nation leads and the claim shows as a frontier, and
where two full-strength claims meet (a state over unceded land) it reads as
contested. Crispness: academic and OHM boundaries draw crisp; the snapshot
dataset's Indigenous polygons are approximate and draw soft.
"""
from __future__ import annotations

import datetime as dt
import functools
import json
import re
import unicodedata

from shapely.geometry import shape

from etl import profile
from etl.common import CFG, SCACHE

Y0, Y1 = CFG["years"]
GEO = SCACHE / "geo"
TREATY_OF_PARIS = 1783.67

# ------------------------------------------------------------------ names
# canonical id -> display name; ids are what research claims must use too
DISPLAY = {
    "spain": "Spain", "france": "France", "britain": "England / Great Britain", "netherlands": "Dutch Republic / Netherlands",
    "sweden": "Sweden", "russia": "Russian Empire", "denmark": "Denmark–Norway / Denmark", "usa": "United States",
    "mexico": "Mexico", "canada": "Canada", "texas": "Republic of Texas", "csa": "Confederate States",
    "vermont": "Vermont Republic", "hawaii": "Hawaiian Kingdom", "yucatan": "Republic of Yucatán",
    "haiti": "Haiti", "central-america": "Federal Republic of Central America", "colombia": "New Granada / Colombia",
    "venezuela": "Venezuela", "courland": "Duchy of Courland", "brandenburg": "Brandenburg-Prussia",
    "knights-hospitaller": "Knights Hospitaller", "guatemala": "Guatemala", "honduras": "Honduras",
    "nicaragua": "Nicaragua", "el-salvador": "El Salvador", "costa-rica": "Costa Rica",
    "dominican-republic": "Dominican Republic", "rio-grande": "Republic of the Rio Grande",
    # Indigenous nations (display follows common present-day usage, source name in brackets)
    "haudenosaunee": "Haudenosaunee (Iroquois)", "ojibwe": "Ojibwe (Chippewa)", "lenape": "Lenape (Delaware)",
    "meskwaki": "Meskwaki (Fox)", "muscogee": "Muscogee (Creek)", "sioux": "Sioux (Dakota, Lakota, Nakota)",
    "ho-chunk": "Ho-Chunk (Winnebago)", "wendat": "Wendat (Huron)", "kaw": "Kaw (Kansa)", "otoe": "Otoe",
    "tohono-oodham": "Tohono O'odham (Papago)", "akimel-oodham": "Akimel O'odham (Pima)", "mikmaq": "Mi'kmaq",
    "illinois": "Illinois Confederation", "aaniiih": "A'aninin (Gros Ventre)", "innu": "Innu",
    "aztec": "Aztec Triple Alliance", "purepecha": "Purépecha (Tarascan) state", "maya": "Maya polities",
    "miskito": "Miskito Kingdom", "comanche": "Comanche (Comanchería)", "crow": "Apsáalooke (Crow)",
    "shoshone": "Shoshone", "athabaskan": "Athabaskan (Dene) peoples", "blackfoot": "Blackfoot Confederacy",
    "navajo": "Diné (Navajo)", "hopi": "Hopi", "ute": "Ute", "menominee": "Menominee", "ponca": "Ponca",
    "abenaki": "Abenaki", "assiniboine": "Assiniboine", "cahuilla": "Cahuilla", "chitimacha": "Chitimacha",
    "zuni": "Zuni", "modoc": "Modoc", "clatsop": "Clatsop", "nisqually": "Nisqually", "duwamish": "Duwamish",
    "apalachee": "Apalachee", "apalachicola": "Apalachicola", "seneca": "Seneca", "sauk": "Sauk",
    "nez-perce": "Nez Perce", "beothuk": "Beothuk", "itza": "Itza kingdom", "chan-santa-cruz": "Chan Santa Cruz (Maya)",
}

SYN = {
    "chippewa": "ojibwe", "ottowa": "ottawa", "seneka": "seneca", "mixed seneka": "seneca", "six nations": "haudenosaunee",
    "iroquois": "haudenosaunee", "sac": "sauk", "fox": "meskwaki", "uta": "ute", "uintah uta": "ute", "capote": "ute",
    "navaho": "navajo", "navabo": "navajo", "moki": "hopi", "hopie": "hopi", "ponka": "ponca", "menomini": "menominee",
    "winnebago": "ho-chunk", "winebago": "ho-chunk", "abnaki": "abenaki", "abenaki abenaquis": "abenaki",
    "assiniboin": "assiniboine", "athabascan": "athabaskan", "muskogee": "muscogee", "creek": "muscogee",
    "shoshoni": "shoshone", "snake": "shoshone", "snake indians": "shoshone", "modok": "modoc", "klatsop": "clatsop",
    "kansa": "kaw", "kansas": "kaw", "oto": "otoe", "niskwali": "nisqually", "dwamish": "duwamish", "zuñi": "zuni",
    "aplache": "apalachee", "apalachees": "apalachee", "appalachicola": "apalachicola", "piegan": "blackfoot", "blood": "blackfoot",
    "mi kma ki": "mikmaq", "mi'kma'ki": "mikmaq", "huron": "wendat", "wendat confederacy": "wendat",
    "comancheria": "comanche", "apsaalooke people": "crow", "apsáalooke people": "crow", "river crow": "crow",
    "cahulia": "cahuilla", "chtimacha": "chitimacha", "papago": "tohono-oodham", "pima": "akimel-oodham",
    "gros ventre": "aaniiih", "montagnais innu": "innu", "naskapi innu": "innu", "delaware": "lenape", "munsee": "lenape",
    "eel river": "miami", "eel river miami": "miami", "kaskaskia": "illinois", "peoria": "illinois", "cahokia": "illinois",
    "mitchigamia": "illinois", "tamaroa": "illinois", "santee sioux": "sioux", "yankton sioux": "sioux", "teton": "sioux",
    "yankton": "sioux", "yankontai": "sioux", "santee": "sioux", "medewakanton": "sioux", "medewahkanton": "sioux",
    "wahpekuta": "sioux", "wahpekute": "sioux", "wahpeton": "sioux", "sisseton": "sioux", "nez percé": "nez-perce",
    "nez perce": "nez-perce", "saginaw": "ojibwe", "lake superior": "ojibwe", "swan creek": "ojibwe", "black river": "ojibwe",
    "aztec empire": "aztec", "aztec empire 1428 1465": "aztec", "mexico tenochtitlan": "aztec", "tetzcoco": "aztec",
    "tlacopan": "aztec", "purepecha empire": "purepecha", "purépecha empire": "purepecha", "mosquito kingdom": "miskito",
    "mosquito coast": "miskito", "mosquito reserve": "miskito", "miskito kingdom": "miskito", "itza kingdom": "itza",
    "wyandot": "wendat", "potawatomi": "potawatomi", "sauk and fox": "sauk", "great": None, "little osage": "osage",
    "the iowa": "iowa", "florida": "seminole", "tlinoit": "tlingit", "bella": "nuxalk", "walla walla": "walla-walla", "seven nations of canada": "seven-nations-of-canada",
}
STOP = {"wi", "others", "in the vicinity thereof", "michigan", "great", "buena vista", "christian", "certain chiefs in florida",
        "florida tribes", "colville", "indians on the oregon coast", "mission", "round valley", "tule river", "king's river",
        "kings river", "roche de boeuf", "milwaukee", "manitowoc rivers", "loup fork", "colorado river", "black river"}
# Maya polities of Yucatán in OHM (1441–1545) collapse to one side; they are many tiny cuchcabalob
MAYA = {"ah canul", "ah kin chel", "calotmul", "ceh pech", "chactemal", "chakan putum", "chakán", "chikinchel de chinkín",
        "dzuluinicob", "ekab", "hocabá homún", "kaan peech", "kock wah", "kupul", "sotuta", "tases", "tutul xiu", "uaymil",
        "tavasco", "manche chʼol", "maya city states", "mayas"}


OHM_INDIGENOUS_RAW = {"wendat confederacy", "comancheria", "shoshone", "apsáalooke people", "beothuk", "aztec empire",
                  "aztec empire 1428-1465", "mexico-tenochtitlan", "tetzcoco", "tlacopan", "purépecha empire", "itza kingdom",
                  "manche chʼol", "chan santa cruz", "miskito kingdom", "mosquito kingdom", "mosquito reserve"}
CARIB = {"dominica", "grenada", "saint lucia", "saint vincent and the grenadines", "saint martin", "saint barthelemy",
         "montserrat", "anguilla", "antigua and barbuda", "netherlands antilles", "bahamas", "barbados", "trinidad"}
CENTRAL = {"guatemala", "honduras", "nicaragua", "el salvador", "costa rica", "dominican republic"}


def _fold_keys() -> None:
    global SYN, MAYA, STOP, OHM_INDIGENOUS
    SYN = {fold(k): v for k, v in SYN.items()}
    MAYA = {fold(k) for k in MAYA}
    STOP = {fold(k) for k in STOP}
    OHM_INDIGENOUS = {fold(k) for k in OHM_INDIGENOUS_RAW}


def fold(s: str) -> str:
    """Lowercase, strip accents, unify quotes and hyphens."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[‘’ʼ`]", "'", s)
    return re.sub(r"\s+", " ", re.sub(r"[-_/]+", " ", s)).strip()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")


# a token anywhere in the name decides the nation (Royce lists bands and reservations)
TOKEN_NATION = {"chippewa": "ojibwe", "sioux": "sioux", "apache": "apache", "pawnee": "pawnee", "shoshoni": "shoshone",
                "shoshone": "shoshone", "shawnee": "shawnee", "paiute": "paiute", "cheyenne": "cheyenne", "potawatomi": "potawatomi",
                "ottawa": "ottawa", "wyandot": "wendat", "seneka": "seneca", "seneca": "seneca", "delaware": "lenape",
                "miami": "miami", "kickapoo": "kickapoo", "osage": "osage", "creek": "muscogee", "cherokee": "cherokee",
                "choctaw": "choctaw", "chickasaw": "chickasaw", "seminole": "seminole", "navaho": "navajo", "navajo": "navajo",
                "navabo": "navajo", "crow": "crow", "blackfoot": "blackfoot", "ute": "ute", "uta": "ute"}
SIOUX_RES = {"standing rock", "pine ridge", "rosebud", "lower brule", "crow creek", "cheyenne river"}


def canon(name: str | None) -> str | None:
    """Canonical Indigenous-nation id from any source's spelling (Royce, snapshots, OHM, research)."""
    if not name:
        return None
    n = fold(re.sub(r"\(.*?\)|\[.*?\]", " ", name))
    n = re.split(r" or ", n)[0].strip(" ,.;:")
    if n in SYN:
        return None if SYN[n] is None else slug(SYN[n])
    if n in MAYA:
        return "maya"
    n = re.sub(r"\b(the|several|tribes?|nations?|indians?|bands?|people|confederated|mixed|party)\b", " ", n)
    n = re.sub(r"\b(of|residing|on|at|west|in)\b.*$", "", n)
    n = re.sub(r"\s+", " ", n).strip(" ,.;:")
    if not n or n in STOP or len(n) < 3:
        return None
    if n in MAYA:
        return "maya"
    if n in SYN:
        return None if SYN[n] is None else slug(SYN[n])
    if n.endswith("s") and n[:-1] in SYN:
        return slug(SYN[n[:-1]])
    if any(n.startswith(r) for r in SIOUX_RES):
        return "sioux"
    for tok in n.split():
        if tok in TOKEN_NATION and tok != n:
            return TOKEN_NATION[tok]
    if n.endswith("s") and n[:-1] in TOKEN_NATION:
        return TOKEN_NATION[n[:-1]]
    return slug(n)


_fold_keys()
SYN.update({"mississagas": "mississauga", "misssissagas": "mississauga", "mississaga": "mississauga",
            "ojibways": "ojibwe", "ojibbeway": "ojibwe", "chippeways": "ojibwe", "chippewa nation": "ojibwe",
            "saugeen": "ojibwe", "swampy cree": "cree", "plain and wood cree": "cree", "crees": "cree",
            "blackfeet": "blackfoot", "sarcee": "tsuutina", "stony": "assiniboine", "beaver": "dane-zaa",
            "chipewyan": "dene-chipewyan", "ottawas": "ottawa", "hurons": "wendat", "wyandots": "wendat",
            "pottawatomys": "potawatomi", "algonquins": "algonquin", "tyendinaga mohawks": "haudenosaunee",
            "iroquois of st regis": "haudenosaunee", "slave": "dene-yellowknives-slavey", "dogrib": "tlicho",
            "loucheux": "gwichin", "hare": "sahtu", "wood cree": "cree", "plain": None, "morris": None})
SYN.update({"apsaalooke": "crow", "certain chiefs": None, "educated": None, "eastern": None, "coast": None, "six": None})
STOP |= {"certain chiefs", "educated", "eastern", "coast", "san imirio", "cha"}


# research catalogue ids that name the same nation as a mapped side
RESEARCH_ALIAS = {
    "mexica-triple-alliance": "aztec", "maya-yucatan": "maya", "cruzob": "chan-santa-cruz", "dine": "navajo",
    "apache-chiricahua": "chiricahua", "apache-mescalero": "mescalero", "apache-jicarilla": "jicarilla",
    "apache-lipan": "lipan", "apache-western": "apache", "lakota": "sioux", "dakota": "sioux", "nakota-yankton": "sioux",
    "anishinaabe-ojibwe": "ojibwe", "odawa": "ottawa", "nimiipuu": "nez-perce", "yupik": "yup-ik-cup-ik",
    "inupiat": "inupiaq", "coeur-dalene": "coeur-d-alene", "yakama": "yakima", "western-shoshone": "shoshone",
    "northern-shoshone": "shoshone", "eastern-shoshone": "shoshone", "washoe": "washo", "kwakwakawakw": "kwakwaka-wakw",
    "susquehannock": "susquehanna", "quechan": "yuma", "mandan-hidatsa-arikara": "mandan",
}


def na_alias(pid: str) -> str:
    """Research polity id -> scene side id."""
    if pid in RESEARCH_ALIAS:
        return RESEARCH_ALIAS[pid]
    if pid in DISPLAY:
        return pid
    return canon(pid.replace("-", " ")) or pid


# ------------------------------------------------------------------ sovereign mapping
def sovereign(name: str, year: float) -> tuple[str, float] | None:
    """(side, claim weight) for a colonial/state polygon name, or None if Indigenous/unknown."""
    n = name.lower()
    if fold(n) in MAYA:
        return None
    if n in CENTRAL:
        return slug(n), 0.9
    rules = [
        (r"\(uk\)", ("britain", 0.8)),
        (r"\(spain\)", ("spain", 0.8)),
        (r"\(netherlands\)", ("netherlands", 0.8)),
        (r"united states|^us military government", ("usa", 0.95)),
        (r"confederate states", ("csa", 0.95)),
        (r"republic of texas|texas republic", ("texas", 1.0)),
        (r"vermont republic", ("vermont", 1.0)),
        (r"republic of the rio grande", ("rio-grande", 0.9)),
        (r"republic of yucat", ("yucatan", 1.0)),
        (r"hawai", ("hawaii", 1.0)),
        (r"russia", ("russia", 0.8)),
        (r"denmark|danish|kalmar|greenland|virgin islands \(danemark\)", ("denmark", 0.9)),
        (r"new sweden|saint barthelemy", ("sweden", 1.0) if year >= 1784 or "sweden" in n else ("france", 0.9)),
        (r"new netherland|new amsterdam|walcheren|kolonie|essequibo|dutch|netherlands|nova zeelandia|guyana \(netherlands\)", ("netherlands", 0.9)),
        (r"courland|neu-kurland", ("courland", 1.0)),
        (r"brandenburg", ("brandenburg", 1.0)),
        (r"knights hospitaller", ("knights-hospitaller", 1.0)),
        (r"republic of west florida|republic of pirates|republic of indian stream|transylvania colony|republic of spanish haiti", None),
        (r"new france|acadia|isle saint-jean|french|fort st\. louis|saint-domingue|company of the american islands|"
         r"saint pierre|sainte-lucie|guadelupe|guadeloupe|martinique|colony of canada|^louisiana$|colony of louisiana|^france$", ("france", 0.8)),
        # the Dominion's legal extent is a claim over land its treaties had not yet reached;
        # its provinces (OHM admin level 4) and treaty cessions are what it held
        (r"^canada$|dominion of canada", ("canada", CLAIM) if year >= 1867 else ("britain", 0.85)),
        (r"viceroyalty|captaincy general|spanish|spain|^santiago$|colony of santiago|^florida$|luisiana|cuba|hispaniola|"
         r"santo domingo|castilla de oro|veragua|caracas province|little venice|nueva|new kingdom|kingdom of new|alta california", ("spain", 0.75)),
        (r"mexican empire|^mexico$|mexican", ("mexico", 0.85)),
        (r"federal republic of central america", ("central-america", 0.9)),
        (r"haiti", ("haiti", 0.9) if year >= 1804 else ("france", 0.8)),
        (r"colombia|new granada|granadine|state of the isthmus|panam", ("colombia", 0.9)),
        (r"venezuela", ("venezuela", 0.9)),
        (r"united kingdom|british|england|rupert|north-west territories|columbia district|new caledonia|red river|"
         r"newfoundland|nova scotia|new brunswick|cape breton|prince edward|st\. john's island|upper canada|lower canada|"
         r"province of canada|province of quebec|^quebec$|vancouver island|british columbia|queen charlotte|stickeen|"
         r"colony of|province of|massachusetts|plymouth|new hampshire|new haven|saybrook|maryland|dominion of new england|"
         r"jersey|roanoke|somers isles|virgineola|bristol's hope|cuper's cove|renews|providence island|virginia|carolina|"
         r"georgia|east florida|west florida|bermuda|bahamas|jamaica|barbados|belize|cayman|anguilla|montserrat|antigua|"
         r"saint kitts|saint christopher|trinidad|turks and caicos|lower counties|maine|"
         r"rhode island|connecticut|pennsylvania|new york", ("britain", 0.8)),
    ]
    for pat, res in rules:
        if re.search(pat, n):
            return res
    return None


def feature(side_ws: list[tuple[str, float]], name: str, names: dict, y0, y1, geom, crisp: float, source: str,
            kind: str = "state", ramp: float = 1.0) -> dict:
    return {"side": side_ws[0][0], "sides": side_ws, "name": name, "names": names, "y0": y0, "y1": y1,
            "geom": geom, "crisp": crisp, "source": source, "kind": kind, "ramp": ramp}


# Control vs claim. Strength is degree of control: a homeland, an organised state or a
# settled colony is held (>= 0.8); a charter, viceroyalty extent, trading-company grant or
# unorganised purchase over land others held is a claim (CLAIM, below 0.5), which the
# renderer draws faint, hatched and soft rather than as ownership.
CLAIM = 0.4
COLONIAL = {"britain", "france", "spain", "netherlands", "sweden", "russia", "denmark", "courland",
            "brandenburg", "knights-hospitaller"}
CLAIM_NAMES = re.compile(r"viceroyalty|captaincy general|new france|louisiana|rupert|north-west territor|arctic|"
                         r"columbia district|new caledonia|alta california|the californias|russian|inner provinces|"
                         r"kingdom of|new kingdom|nueva|province of quebec|dominion of canada|spanish florida|"
                         r"united kingdom|^spain$|^france$|luisiana|florida", re.I)
SETTLED_MAX_AREA = 60.0          # square degrees: larger colonial polygons are claims, not administered land


def colonial_weight(side: str, name: str, geom, held: float) -> float:
    if side not in COLONIAL:
        return held
    if CLAIM_NAMES.search(name) or geom.area > SETTLED_MAX_AREA:
        return CLAIM
    return held


def display(side: str, src_name: str) -> str:
    return DISPLAY.get(side) or re.sub(r"\s*\(.*?\)\s*$", "", src_name).strip() or side


def dec(s) -> float | None:
    if s is None or s == "":
        return None
    m = re.match(r"(-?\d{1,4})(?:-(\d{2}))?(?:-(\d{2}))?", str(s))
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1)
    try:
        return y + (dt.date(y, mo, d) - dt.date(y, 1, 1)).days / 365.25
    except ValueError:
        return float(y)


# ------------------------------------------------------------------ sources
SNAPSHOTS = [1500, 1530, 1600, 1650, 1700, 1715, 1783, 1800, 1815, 1880, 1900]
# 1492 (Native-Land-style homelands, ~800 names, no historical dating) is left out on purpose.


def basemaps() -> list[dict]:
    if profile.blocked("hb"):
        return cliopatria_claims()
    out = []
    for i, y in enumerate(SNAPSHOTS):
        ya = Y0 if i == 0 else float(y)
        if y == 1783:
            ya = TREATY_OF_PARIS
        yb = (TREATY_OF_PARIS if SNAPSHOTS[i + 1] == 1783 else float(SNAPSHOTS[i + 1])) if i + 1 < len(SNAPSHOTS) else Y1 + 1.0
        d = json.loads((GEO / f"historical_basemaps_{y}.geojson").read_text())
        for f in d["features"]:
            nm = (f["properties"].get("name") or "").strip()
            if not nm:
                continue
            sv = sovereign(nm, ya)
            try:
                g = shape(f["geometry"])
            except Exception:
                continue
            if sv:
                side, w = sv
                # snapshot claims persist until the next snapshot, so they are weak: dated OHM polygons win
                w = min(sv[1], colonial_weight(side, nm, g, 0.8))
                yb2 = yb
                # snapshot features persist until the next snapshot; end French mainland claims at the
                # 1763 Treaty of Paris instead of carrying the 1715 snapshot to 1783
                if side == "france" and g.centroid.y > 25 and g.centroid.x < -60:
                    yb2 = min(yb, 1763.12)
                if yb2 > ya:
                    out.append(feature([(side, w)], display(side, nm), {}, ya, yb2, g, 0.4, "historical-basemaps", ramp=3.0))
            elif nm.lower() in CARIB:
                out.append(feature([(slug(nm), 0.8)], nm, {}, ya, yb, g, 0.4, "historical-basemaps", ramp=2.0))
            else:
                side = canon(nm)
                if side is None:
                    continue
                # approximate homelands: a wide ramp (~1 degree) so the edge reads as a zone of doubt
                # 0.9: verified, cited research (cost-distance over terrain, 0.97) outranks the coarse snapshot
                out.append(feature([(side, 0.9)], display(side, nm), {}, ya, yb, g, 0.2, "historical-basemaps", "nation", ramp=6.0))
    return out


def cliopatria_claims() -> list[dict]:
    """historical-basemaps' replacement where a profile blocks it: Cliopatria's polity rows (CC BY 4.0,
    year resolution), each drawn as its empire's claim (a colony is a member row of its empire) through
    the same sovereign rules and claim weights, or as an Indigenous polity when it is one we name."""
    from etl.fetch.borders import cliopatria
    out = []
    for f in cliopatria():
        p = f["properties"]
        top = p["member_of"] or p["name"]
        ya, yb = max(float(p["from"]), float(Y0)), float(p["to"]) + 1
        g = shape(f["geometry"])
        sv = sovereign(top, ya) or sovereign(p["name"], ya)
        if sv:
            side, w = sv
            out.append(feature([(side, min(w, colonial_weight(side, p["name"], g, 0.8)))], display(side, p["name"]), {},
                               ya, yb, g, 0.4, "cliopatria", ramp=3.0))
        elif (side := canon(p["name"])) is not None:
            out.append(feature([(side, 0.9)], display(side, p["name"]), {}, ya, yb, g, 0.2, "cliopatria", "nation", ramp=6.0))
    return out


def ohm() -> list[dict]:
    out = []
    for fn in ("ohm_other_polities", "ohm_canada_bna", "ohm_mexico_newspain"):
        d = json.loads((GEO / f"{fn}.geojson").read_text())
        for f in d["features"]:
            p = f["properties"]
            lvl = str(p.get("admin_level"))
            if fn == "ohm_canada_bna" and lvl == "4":
                out += canada_unit(p, f)
                continue
            if lvl != "2":
                continue
            nm = re.sub(r"\s*\(\d{4}.*?\)$", "", p.get("name") or "")
            if not nm or nm.lower() == "united states":       # US extent comes from Newberry
                continue
            y0, y1 = dec(p.get("start")), dec(p.get("end"))
            y0 = Y0 if y0 is None else y0
            y1 = Y1 + 1.0 if y1 is None else y1
            if "new spain" in nm.lower():
                y1 = min(y1, 1821.74)                          # Mexican independence, Sept 1821
            if y1 <= Y0 or y0 > Y1 + 1:
                continue
            try:
                g = shape(f["geometry"])
            except Exception:
                continue
            if "joint mexico-texas" in nm.lower():
                out.append(feature([("texas", 0.9), ("mexico", 0.9)], nm, {"texas": DISPLAY["texas"], "mexico": DISPLAY["mexico"]},
                                   y0, y1, g, 1.0, "ohm"))
                continue
            if re.search(r"disputed|neutral ground", nm.lower()):
                out.append(feature([("usa", 0.8), ("spain", 0.8)], nm, {"usa": DISPLAY["usa"], "spain": DISPLAY["spain"]},
                                   y0, y1, g, 1.0, "ohm"))
                continue
            sv = sovereign(nm, y0)
            if sv:
                side, w = sv
                w = min(w, colonial_weight(side, nm, g, 0.9))      # never stronger than the rule says
                out.append(feature([(side, w)], display(side, nm), {}, y0, y1, g, 1.0 if w >= 0.5 else 0.5, "ohm",
                                   ramp=1.0 if w >= 0.5 else 2.0))
            elif fold(nm) not in OHM_INDIGENOUS and fold(nm) not in MAYA:
                out.append(feature([(slug(nm), 0.9)], nm, {}, y0, y1, g, 1.0, "ohm"))
            else:
                side = canon(nm)
                if side is None:
                    continue
                out.append(feature([(side, 1.0)], display(side, nm), {}, y0, y1, g, 1.0, "ohm", "nation"))
    return out


def newberry() -> list[dict]:
    out = []
    d = json.loads((GEO / "newberry_ahcb_stateterr.geojson").read_text())
    for f in d["features"]:
        p = f["properties"]
        nm, tt = p.get("name") or "", p.get("terr_type") or ""
        y0, y1 = dec(p.get("start")), dec(p.get("end"))
        if y0 is None or y0 > Y1 + 1:
            continue
        y1 = Y1 + 1.0 if (y1 is None or y1 > Y1 + 1) else y1 + 1 / 365.25
        try:
            g = shape(f["geometry"])
        except Exception:
            continue
        if nm == "Deseret":
            continue                                           # proposed state, never sovereign
        if nm == "Texas Republic":
            sw = [("texas", 1.0)]
        elif nm == "Vermont Republic":
            sw = [("vermont", 1.0)]
        elif nm == "Oregon Country":
            sw = [("usa", CLAIM), ("britain", CLAIM)]          # joint occupation 1818–1846: two claims
        elif tt in ("State", "District of Columbia"):
            sw = [("usa", 1.0)]
        elif tt == "Territory":
            sw = [("usa", 0.85)]
        elif nm == "Indian Territory":
            sw = [("usa", CLAIM)]
        elif nm == "Uncertain Boundary Area":
            sw = [("usa", CLAIM * 0.8)]
        else:
            sw = [("usa", CLAIM)]                              # purchases, cessions, unorganised land
        out.append(feature(sw, display(sw[0][0], nm), {s: DISPLAY.get(s, s) for s, _ in sw}, y0, y1, g, 1.0, "newberry"))
    return out


CANADA_TERRITORIES = re.compile(r"north-west territor|keewatin|yukon|dispute", re.I)


def canada_unit(p: dict, f: dict) -> list[dict]:
    """A Canadian province (held) or territory (claim) from OHM admin level 4."""
    nm = p.get("name") or ""
    y0, y1 = dec(p.get("start")), dec(p.get("end"))
    if y0 is None or y0 < 1867.4 or y0 > Y1 + 1 or "dispute" in nm.lower():
        return []
    y1 = Y1 + 1.0 if y1 is None else y1
    try:
        g = shape(f["geometry"])
    except Exception:
        return []
    if CANADA_TERRITORIES.search(nm):
        return [feature([("canada", CLAIM)], "Canada", {}, y0, y1, g, 0.5, "ohm", ramp=2.0)]
    return [feature([("canada", 0.9)], "Canada", {}, y0, y1, g, 1.0, "ohm")]


ROYAL_PROCLAMATION = 1763.76      # 7 Oct 1763: the Crown recognises Indigenous title west of the settlements


def canada_treaties() -> list[dict]:
    """Canadian historic treaties (CIRNAC + Ontario/Morris 1943): the signatories' land until the
    treaty, then the Crown's (Britain before Confederation, Canada after). Crown grants TO nations
    (Haldimand Tract, Tyendinaga) are the nation's from the grant. Peace and Friendship treaties
    ceded no land and are not used."""
    fp = GEO / "canada_treaties.geojson"
    if not fp.exists():
        return []
    out = []
    for f in json.loads(fp.read_text())["features"]:
        p = f["properties"]
        nm = p.get("name") or ""
        if "peace and friendship" in nm.lower():
            continue
        y = dec(p.get("start"))
        if y is None or y > Y1 + 1:
            continue
        try:
            g = shape(f["geometry"])
        except Exception:
            continue
        sig = re.sub(r"\(.*?\)|'.*?'", "", p.get("signatories") or "")
        if "douglas" in nm.lower():
            ids = ["coast-salish"]
        else:
            ids = []
            for tok in re.split(r",|;| and |&", sig):
                c = canon(tok)
                if c and c not in ids and c not in ("other", "other-indians", "indians"):
                    ids.append(c)
        if not ids:
            continue
        names = {i: display(i, i.replace("-", " ").title()) for i in ids}
        if "crown grant" in nm.lower():
            out.append(feature([(ids[0], 1.0)], names[ids[0]], names, y, Y1 + 1.0, g, 0.9, "canada-treaties", "nation"))
            continue
        sw = [(ids[0], 1.0)] + ([(ids[1], 0.9)] if len(ids) > 1 else [])
        if y > ROYAL_PROCLAMATION:
            out.append(feature(sw, names[ids[0]], names, ROYAL_PROCLAMATION, y, g, 0.9, "canada-treaties", "nation"))
        # ceded to the Crown: Britain's until Confederation (1 Jul 1867), Canada's after
        if y < 1867.5:
            out.append(feature([("britain", 0.9)], DISPLAY["britain"], {}, y, 1867.5, g, 0.9, "canada-treaties"))
        out.append(feature([("canada", 0.9)], DISPLAY["canada"], {}, max(y, 1867.5), Y1 + 1.0, g, 0.9, "canada-treaties"))
    return out


SETTLED_RADIUS = 1.0       # degrees (~100 km): the neighbourhood a town or fort actually held
CORE_SIDES = COLONIAL | {"canada", "usa"}


def colonial_cores(feats: list[dict]) -> list[dict]:
    """Held cores inside paper claims: around each settlement or fort founded (Wikidata
    inception >= 1492, so pre-contact Indigenous towns don't count) inside a claim polygon,
    the claiming power held the land from the founding date for as long as the claim lasted."""
    sp = SCACHE / "settlements.json"
    if not sp.exists():
        return []
    import shapely
    from shapely.geometry import Point
    pts = [s for s in json.loads(sp.read_text()) if s["from"] >= 1492]
    # one core per (power, settlement), over the union of the claim's time windows: claims are
    # often many consecutive OHM slices of the same polygon
    windows: dict[tuple[str, str], list] = {}
    for f in feats:
        claims = [(sd, w) for sd, w in f["sides"] if sd in CORE_SIDES and w <= CLAIM + 1e-6]
        if not claims:
            continue
        g = f["geom"]
        shapely.prepare(g)
        x0, y0, x1, y1 = g.bounds
        for s in pts:
            if not (x0 <= s["lon"] <= x1 and y0 <= s["lat"] <= y1) or s["from"] >= f["y1"]:
                continue
            if not shapely.contains_xy(g, s["lon"], s["lat"]):
                continue
            key = (claims[0][0], s["qid"])
            windows.setdefault(key, []).append((max(f["y0"], float(s["from"])), f["y1"], g, s))
    out = []
    for (side, _), ws in windows.items():
        ws.sort(key=lambda w: w[0])
        merged = [list(ws[0])]
        for a, b, g, s in ws[1:]:
            if a <= merged[-1][1] + 0.01:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b, g, s])
        for a, b, g, s in merged:
            core = g.intersection(Point(s["lon"], s["lat"]).buffer(SETTLED_RADIUS, quad_segs=8))
            if core.is_empty:
                continue
            out.append(feature([(side, 0.8)], DISPLAY.get(side, side), {}, a, b, core, 0.4, "settlements", ramp=3.0))
    return out


def royce() -> list[dict]:
    """Each cession area belongs to its signatory nation(s) until the cession date."""
    out = []
    d = json.loads((GEO / "royce_cessions.geojson").read_text())
    for f in d["features"]:
        p = f["properties"]
        y1 = dec(p.get("start"))
        if y1 is None:
            continue
        raw = re.sub(r"\(.*?\)|\[.*?\]", "", p.get("tribes_schedule") or "")
        ids: list[str] = []
        for tok in re.split(r",|;| and |&", raw):
            c = canon(tok)
            if c and c not in ids:
                ids.append(c)
        if not ids:
            continue
        try:
            g = shape(f["geometry"])
        except Exception:
            continue
        # joint cessions: the first signatory leads, the second shows as a faint share
        # (all signatories stay listed in the cession's source record)
        sw = [(ids[0], 1.0)] + ([(ids[1], 0.9)] if len(ids) > 1 else [])
        out.append(feature(sw, display(ids[0], ids[0].replace("-", " ").title()),
                           {s: display(s, s.replace("-", " ").title()) for s, _ in sw},
                           TREATY_OF_PARIS, y1, g, 0.9, "royce", "nation"))
    return out


@functools.lru_cache(maxsize=1)
def _sources() -> tuple:
    base = basemaps() + ohm() + newberry() + royce() + canada_treaties()
    return tuple(base + colonial_cores(base))


def north_america_sources() -> list[dict]:
    return list(_sources())


def _unused() -> list[dict]:
    feats = basemaps() + ohm() + newberry() + royce()
    return feats


def north_america_slice_years() -> list[float]:
    """Every source change date in the window, quantised to ~half a year (the merge step thins further)."""
    ys = {float(Y0)}
    for f in north_america_sources():
        for y in (f["y0"], f["y1"]):
            if y is not None and Y0 <= y <= Y1 + 0.99:
                ys.add(round(round(y * 4) / 4, 2))
    return sorted(ys)
