"""Write <CACHE>/scenes/north-america/sources.json (provenance, licence, date semantics) from the produced geo/*.geojson."""
import json
import os

from etl import profile
from .fetch import HB_YEARS
from .helpers import BASE


def entry(id, files, **kw):
    n = sum(len(json.load(open(BASE / f))["features"]) for f in files)
    return dict(id=id, files=files, feature_count=n, **kw)


OHM_LIC = ("CC0 1.0 (OpenHistoricalMap database licence; Overpass response header: 'made available under CC0'; "
           "per-object licence tag is CC0 on most relations, a few untagged)")
OHM_ATTR = "OpenHistoricalMap contributors (openhistoricalmap.org), CC0 - attribution not required, appreciated"
OHM_DATE = ("properties.start / properties.end copied from OHM start_date / end_date tags: ISO 8601 EDTF-ish, "
            "'YYYY', 'YYYY-MM' or 'YYYY-MM-DD'; end null = still current (or untagged)")


def main():
    srcs = []
    srcs.append(entry(
        "newberry_ahcb_stateterr",
        ["geo/newberry_ahcb_stateterr.geojson"],
        title="Atlas of Historical County Boundaries - US Historical States & Territories (Gen .001 deg), 1783-1900 subset",
        url="https://publications.newberry.org/ahcb/downloads/united_states.html (zip: https://publications.newberry.org/ahcb/downloads/gis/US_AtlasHCB_StateTerr_Gen001.zip)",
        licence=("Newberry download page: 'consulted, reviewed, and reused for any lawful purpose, commercial or non-commercial, without "
                 "licensing or permission fees'; Newberry donated the shapefiles to the Library of Congress in 2019 under CC0 (per Zenodo 10.5281/zenodo.7080770). "
                 "Files inside the zip still carry the old CC BY-NC-SA 2.5 notice, which the Newberry says to ignore."),
        attribution="Siczewicz, Peter. U.S. Historical States and Territories (Generalized .001 deg). Emily Kelley, digital comp. Atlas of Historical County Boundaries, ed. John H. Long. Chicago: The Newberry Library, 2011.",
        date_fields="properties.start / properties.end from START_DATE / END_DATE ('YYYYMMDD' in the source, rewritten to 'YYYY-MM-DD'); END_DATE 2000-12-31 means still current at dataset end; only features starting <= 1900-12-31 kept",
        name_field="FULL_NAME (source NAME/ABBR_NAME also exist)",
        years_covered="1783-09-03 .. 1900 (source covers to 2000)",
        notes=("Shapefile is Gen .001 deg (about 100 m) generalized, polygons tile exactly at any date. Extra props: ahcb_id, terr_type, version. "
               "Includes Vermont Republic, Texas Republic, Oregon Country, Louisiana Purchase, Mexican Cession, Gadsden Purchase, Deseret, Hawaii, Alaska. "
               "Only the area that became the US (no Canada/Mexico, no pre-1783 colonies). Cropped output is 21 MB because of the detailed coast; use the Gen .01 zip (2 MB) if size matters."),
    ))
    srcs.append(entry(
        "royce_cessions",
        ["geo/royce_cessions.geojson"],
        title="Indian Land Cessions in the United States (Royce, 1899) - digitized by USDA Forest Service, 2018 revision (data.gov: Tribal Lands Ceded to the United States)",
        url="https://catalog.data.gov/dataset/tribal-lands-ceded-to-the-united-states-feature-layer ; service https://apps.fs.usda.gov/ArcX/rest/services/EDW/EDW_TribalCessionLands_01/MapServer (layer 1 polygons, layer 2 attribute table)",
        licence="data.gov lists Creative Commons Attribution 4.0 (public access level); US Forest Service metadata adds an informational-only / not-a-legal-document disclaimer. Underlying Royce maps (1899) are public domain.",
        attribution="USDA Forest Service Office of Tribal Relations, with National Park Service National NAGPRA Program, EPA American Indian Environmental Office and Claudio Saunt (U. Georgia); after Charles C. Royce, Indian Land Cessions in the United States, 18th Annual Report of the Bureau of American Ethnology, 1899.",
        date_fields="properties.start = earliest treaty/statute/EO date (YYYY-MM-DD, from cessdate1..5 epoch-ms in the table, treaty signing date not proclamation); all dates in properties.dates; end is null (cession is permanent)",
        name_field="no treaty-name field exists in the source; name is synthesised 'Cession <Royce no.>: <tribes per Schedule>'. properties.tribes_schedule, tribes_present_day, royce_map, instrument, entries[] (links to Royce Schedule on archive.org and Kappler treaty text on HathiTrust), states",
        years_covered="1784-10-22 .. 1893-02-20 (Royce covers 1784-1894)",
        notes=("717 of 725 table rows have polygons. 7 cession ids have no polygon in the source (47, 65, 128, 129, 130, 543, 690) and 1 polygon has no cessnum. "
               "Polygons overlap where several cessions or treaties cover the same ground. Each cession polygon can be referenced by up to 5 dates (re-cessions, confirmations). "
               "Treaty names (e.g. 'Treaty of Fort Stanwix') are not in the data: only date, tribe(s), citations and links to the treaty text. "
               "Royce maps cover the contiguous US, so Alaska/Canada not included. Georeferenced from 1:~2M maps: boundaries are approximate."),
    ))
    if not profile.blocked("hb"):
        srcs.append(entry(
            "historical_basemaps",
            [f"geo/historical_basemaps_{y}.geojson" for y in HB_YEARS],
            title="aourednik/historical-basemaps - world_<year>.geojson snapshots, cropped to North America",
            url="https://github.com/aourednik/historical-basemaps (geojson/world_<year>.geojson)",
            licence="GPL-3.0 (repository LICENSE). Copyleft: derivative datasets distributed with the prototype must stay GPL-3.0-compatible.",
            attribution="Andre Ourednik, historical-basemaps (github.com/aourednik/historical-basemaps), GPL-3.0",
            date_fields="snapshot year only: properties.start = snapshot year ('YYYY'); properties.end = next snapshot year in this list (1900 -> null). Not true polity lifespans.",
            name_field="NAME (falls back to ABBREVN, SUBJECTO, PARTOF; null when the source has none). Extra props: subjecto, partof, precision",
            years_covered="snapshots 1492, 1500, 1530, 1600, 1650, 1700, 1715, 1783, 1800, 1815, 1878, 1880, 1900 (every requested year exists; 1500 and 1878 are extra; repo also has 1400, 1914 ...)",
            notes=("README says 'work in progress, verify before academic use'. BORDERPRECISION 1 = approximate, 3 = by treaty. "
                   "Early snapshots (1492/1600/1650/1700) mix Indigenous nations with colonial claims, many with no NAME (1492: 337 of 1167 features unnamed). "
                   "1783-1900 are only 30-40 coarse country-level polygons, with Indigenous territories sparse; use Newberry/Royce for US detail. "
                   "Polygons were not clipped at borders of the window except by the crop; overlapping claims occur."),
        ))
    OHM_URL = "https://overpass-api.openhistoricalmap.org/api/interpreter (relations boundary=administrative, admin_level 2-5, start_date<=1900, end_date>=1492 or unset, bbox 7,-170,75,-50; one tag query + id-chunked 'out geom' queries, 4 s apart)"
    srcs.append(entry(
        "ohm_canada_bna", ["geo/ohm_canada_bna.geojson"],
        title="OpenHistoricalMap - Canada / British North America / Rupert's Land / Acadia / Colony of Canada admin boundaries over time",
        url=OHM_URL, licence=OHM_LIC, attribution=OHM_ATTR, date_fields=OHM_DATE,
        name_field="name:en, falling back to name", years_covered="1500 .. 1900 (Beothuk 1500; Colony of Canada 1535; Rupert's Land 1670; Province of Quebec 1763; Upper/Lower Canada 1791; Dominion of Canada and provinces 1867+; NWT, Keewatin, Yukon to 1901)",
        notes=("Selected by name regex (+ admin_level 2-5) from the OHM query, so it can miss or over-include a relation. Many relations are consecutive time slices of one polity, so names repeat with different start/end. "
               "Boundaries of colonial/early-confederation entities are hand-drawn from OHM contributors and vary in precision; no Alberta/Saskatchewan (created 1905). Level 6+ divisions (counties/districts) were not fetched. "
               "Geometry assembled from way members with shapely polygonize, simplified at 0.0025 deg (about 250 m); a relation with unclosed rings loses that ring silently. Extra props: ohm_id, admin_level, license."),
    ))
    srcs.append(entry(
        "ohm_mexico_newspain", ["geo/ohm_mexico_newspain.geojson"],
        title="OpenHistoricalMap - Mexico / New Spain viceroyalty, kingdoms, intendancies, provinces and states over time",
        url=OHM_URL, licence=OHM_LIC, attribution=OHM_ATTR, date_fields=OHM_DATE,
        name_field="name:en, falling back to name", years_covered="1473 .. 1900 (Viceroyalty of New Spain as ~70 time slices from 1521; Intendancies 1786-87; Mexican Empire 1821; states 1823-24 onward; Departments of the 2nd Empire 1865-67)",
        notes=("Classified by name regex, includes Texas-adjacent entries (Coahuila y Tejas, Rio Grande republic, Gadsden/Mexican Cession) and Mexican-state-level divisions; Spanish borderland provinces appear as Nuevo Mexico, Alta California, Inner Provinces captaincies. "
               "Central America (Guatemala, Honduras etc.) is in ohm_other_polities. Quality varies: some border areas of the 1500s-1700s are very approximate; a few relations are simple one-year slices. Same geometry caveats as ohm_canada_bna."),
    ))
    srcs.append(entry(
        "ohm_other_polities", ["geo/ohm_other_polities.geojson"],
        title="OpenHistoricalMap - other polities in the window: US colonies/states/territories, Spanish/French/Dutch/Russian/British colonial claims, Caribbean, Central America, Indigenous polities (Comancheria, Wendat, Shoshone, Apsaalooke ...)",
        url=OHM_URL, licence=OHM_LIC, attribution=OHM_ATTR, date_fields=OHM_DATE,
        name_field="name:en, falling back to name", years_covered="1443 .. 1900",
        notes=("Residual bucket: everything not matched to Canada or Mexico. Notably the 13 colonies and proprietary colonies before 1783 (Newberry has nothing earlier than 1783), New France, French/Spanish Louisiana, Spanish Florida, Russian America, "
               "Oregon Country, Republic of Texas, Confederate States by date, Mosquito Kingdom, Hawaiian Kingdom. Only ~10 Indigenous polities (OHM coverage is thin; historical_basemaps_1492 has far more). Overlaps Newberry for 1783-1900 US states. Same geometry caveats."),
    ))
    CANADA_URL = (
        "CIRNAC/ISC: https://open.canada.ca/data/en/dataset/f281b150-0645-48e4-9c30-01f55f93f78e (SHP: https://data.sac-isc.gc.ca/geomatics/rest/directories/arcgisoutput/DonneesOuvertes_OpenData/Traite_historique_Historic_Treaty/Traite_historique_Historic_Treaty_SHP.zip ; "
        "REST: https://geo.sac-isc.gc.ca/geomatics/rest/services/Donnees_Ouvertes-Open_Data/Historic_Treaty_E/MapServer/0) ; Ontario: https://data.ontario.ca/dataset/ontario-first-nations-treaty-areas -> "
        "https://geohub.lio.gov.on.ca/documents/lio::compiled-plan-of-the-indian-treaties-and-purchases-in-the-province-of-ontario-morris-map-1943/about (SHP: https://ws.gisetl.lrc.gov.on.ca/fmedatadownload/Packages/TreatiesMorrisMap1943.zip, treaties_202403_geohub) ; "
        "dates: CIRNAC Treaty Texts https://www.rcaanc-cirnac.gc.ca/eng/1370373165583/1581292088522 (pages saved in raw/canada_treaties/cirnac_pages/)")
    srcs.append(entry(
        "canada_treaties", ["geo/canada_treaties.geojson"],
        title="Historic (pre-1975) treaty areas in Canada - CIRNAC/ISC 'Historic treaties' (outside Ontario) + Ontario 'First Nations treaty areas' (LIO, after Morris 1943) for Ontario",
        url=CANADA_URL,
        licence=("CIRNAC/ISC layer: Open Government Licence - Canada (https://open.canada.ca/en/open-government-licence-canada). "
                 "Ontario layer: Open Government Licence - Ontario (data.ontario.ca catalogue entry and LIO GeoHub item licenseInfo; credit 'Ontario Ministry of Indigenous Affairs (c) King's Printer for Ontario'). "
                 "Both publishers say boundaries are illustrative/approximate and not legal descriptions; Ontario: 'does not purport to reflect actual treaty boundaries'."),
        attribution=("Contains information licensed under the Open Government Licence - Canada (Crown-Indigenous Relations and Northern Affairs Canada / Indigenous Services Canada, Historic treaties). "
                     "Contains information licensed under the Open Government Licence - Ontario (Ontario Ministry of Indigenous Affairs, Ontario First Nations treaty areas, after J. L. Morris, "
                     "Compiled Plan of the Indian Treaties and Purchases in the Province of Ontario, 1943)."),
        date_fields=("properties.start = earliest dated instrument for the area (ISO; 'YYYY' or 'YYYY-MM' where the source gives only that, see start_precision); "
                     "properties.dates = all distinct signing/adhesion dates; properties.date_sources = which source gave which date: ontario_lio_DATE_E (LIO DATE_E field), "
                     "morris_1943_label (dates in the Morris map label, often the provisional agreement), cirnac_treaty_texts (dates transcribed from the CIRNAC treaty-text pages: "
                     "signing places + adhesions). The federal layer has no date fields at all (only names like 'Treaty 6 (1876)'); the Ontario layer has a text DATE_E. "
                     "No end date (surrenders are permanent)."),
        name_field=("Ontario: ALT_NAME_E (e.g. 'Toronto Purchase'; TREATY_E such as 'Treaty No. 13, 1805' kept in treaty_label). Federal: ENAME. "
                    "Extra props: treaty_id ('ON-<LIO TREATY_ID>' or 'CA-<TAG_ID>'), treaty_label, signatories (as named in the treaty preamble on CIRNAC pages, "
                    "or in the Morris 1943 label; historical ethnonyms, not modern Nation names), start_precision."),
        years_covered="1725 .. 1930 (41 features start <= 1900; later: Treaty 9 1905-06, Treaty 10 1906, Treaty 11 1921, Williams 1923, Treaty 9 adhesion 1929-30)",
        notes=("46 polygons: 34 Ontario LIO (Upper Canada Land Surrenders individually 1781-1862, Robinson-Superior/-Huron 1850, Treaty 9 1905-06 and its 1929-30 adhesion, Williams 1923) "
               "+ 12 federal (Peace and Friendship 1725-1779 as one aggregate, Douglas 1850-54 as one aggregate, Treaties 1-8, 10, 11). Dedupe: federal 'Southern Ontario Treaties (1764-1862)' "
               "aggregate, Robinson x2, Williams and Treaty 9 dropped in favour of the Ontario polygons; Ontario's Ontario-only Treaty 3 and Treaty 5 dropped in favour of the federal "
               "whole-treaty polygons; Ontario 025 (Treaty 45, 1836) and 032 (Treaty 94, 1862) have identical geometry and were merged. Polygons overlap by design (Williams 1923 re-covers "
               "Johnson-Butler/Collins/Rice Lake/Robinson-Huron land; Toronto Purchase vs Johnson-Butler etc.). Treaty areas are the Crown's description of land surrendered (or, for Peace "
               "and Friendship treaties which ceded no land, an illustrative area), estimated from written descriptions; they are not the signatory Nations' territories, and Indigenous "
               "understandings of several treaties differ from the written text. Date conflicts kept, start = earliest: e.g. Huron Tract (Morris 1825-04-25 provisional, CIRNAC deed "
               "1827-07-10, LIO 1833-08-13 apparently copied from Treaty 35); Long Woods 1819-03-09 vs 1822-07-08; Rideau 1819-05-31 vs 1822-11-28; Penetanguishene 1795 vs 1798-05-22; "
               "Saugeen Peninsula 1854-10-13 (CIRNAC) vs 1854-10-30 (LIO). Adhesion date lists come from the CIRNAC transcriptions and may be incomplete (e.g. 1940s-50s Treaty 6/8 "
               "adhesions are not there). Not included: Treaties of Peace and Neutrality (no mapped area), Michilimackinac 1781 and other surrenders outside the Ontario layer, US-side areas. "
               "Federal geometry is NAD83(CSRS) lon/lat taken as WGS84 (<2 m); Ontario reprojected from EPSG:3857. Simplified at 0.0005 deg (~50 m), snapped to 1e-5. "
               "Builder: etl/fetch/north_america/canada_treaties.py; transcribed dates, signatories and dedupe decisions in sources/north-america/canada_treaties.json."),
    ))
    tmp = BASE / "sources.json.tmp"
    tmp.write_text(json.dumps(srcs, ensure_ascii=False, indent=1))
    os.replace(tmp, BASE / "sources.json")
    return len(srcs)


ALL = [main]
