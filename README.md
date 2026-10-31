# Atlas for Atlas: GPL source of the North America territory layer

[Atlas for Atlas](https://atlasforatlas.com) is a time-scrubbable historical atlas. In its North America period (1492–1900), the **Territories** layer and the **Names of powers** layer are built partly from [historical-basemaps](https://github.com/aourednik/historical-basemaps) by André Ourednik, which is licensed under the GNU General Public License v3.0. Those layers (`data/north-america/fields/*.png`, `fields.json`, `lines.json`) are therefore distributed under the GPL-3.0. This repository is their corresponding source: the code that builds them and the committed inputs it reads.

Everything here is licensed under the GPL-3.0 (see `LICENSE`), except the inputs listed under "Other inputs", which keep their own licences.

Exported from the atlas's main repository at commit `8e78b43` by `app/scripts/gpl_export.py`. The rest of the atlas is not GPL-licensed and is not in this repository.

## Build

The build needs Python 3.11 or later and [uv](https://docs.astral.sh/uv/). The steps download their sources into `app/.cache/` and write the layer into `app/public/data/north-america/`:

1. `etl.fetch.north_america`: download and convert Newberry, Royce, historical-basemaps, OpenHistoricalMap and the Canadian treaties.
2. `etl.base.terrain`: the elevation grid the research claims spread over.
3. `etl.history.settlements`: dated settlements from Wikidata (colonial cores).
4. `etl.research.verify_quotes north-america-1492-1900`: check each research citation's quote against its page.
5. `etl.research.merge north-america-1492-1900`: fold in the verifiers' verdicts.
6. `etl.history.fields_polygons`: the territory fields: data/north-america/fields/*.png, fields.json.
7. `etl.history.labels`: names of powers and their colours: fields.json (labels), lines.json.

```bash
cd app
ATLAS_SCENE=north-america uv run --project .. python -m etl.fetch.north_america
ATLAS_SCENE=north-america uv run --project .. python -m etl.base.terrain
ATLAS_SCENE=north-america uv run --project .. python -m etl.history.settlements
ATLAS_SCENE=north-america uv run --project .. python -m etl.research.verify_quotes north-america-1492-1900
ATLAS_SCENE=north-america uv run --project .. python -m etl.research.merge north-america-1492-1900
ATLAS_SCENE=north-america uv run --project .. python -m etl.history.fields_polygons
ATLAS_SCENE=north-america uv run --project .. python -m etl.history.labels
```

The first step downloads about 1 GB. The research steps fetch every page the research catalogue cites, to check its quotes.

## Other inputs and their licences

The build downloads these; none is copied into this repository except where noted:
- [Newberry Library, Atlas of Historical County Boundaries](https://digital.newberry.org/ahcb/downloads/): reuse for any lawful purpose.
- [Royce, Indian Land Cessions (USFS 2018)](https://catalog.data.gov/dataset/tribal-lands-ceded-to-the-united-states-feature-layer): CC BY 4.0.
- [OpenHistoricalMap](https://www.openhistoricalmap.org/copyright): CC0, except features tagged otherwise.
- Historic treaties: [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada) and [Ontario](https://www.ontario.ca/page/open-government-licence-ontario).
- [historical-basemaps](https://github.com/aourednik/historical-basemaps): GPL-3.0.
- [Wikidata](https://www.wikidata.org/wiki/Wikidata:Licensing) (settlements): CC0.
- [AWS Terrain Tiles](https://github.com/tilezen/joerd/blob/master/docs/attribution.md) (elevation): open, with attribution to their providers.
- `app/research/north-america-1492-1900.*` (copied): the atlas's own research catalogue, compiled by AI research agents with quoted, checked citations. Each quote is a short extract of the page it cites and keeps that page's licence.
- `app/sources/catalogue.json` (copied) lists every source the atlas uses, with its licence.

## Files

- `app/etl/__init__.py`
- `app/etl/base/__init__.py`
- `app/etl/base/terrain.py`
- `app/etl/common.py`
- `app/etl/fetch/__init__.py`
- `app/etl/fetch/borders.py`
- `app/etl/fetch/north_america/__init__.py`
- `app/etl/fetch/north_america/__main__.py`
- `app/etl/fetch/north_america/canada_treaties.py`
- `app/etl/fetch/north_america/convert.py`
- `app/etl/fetch/north_america/fetch.py`
- `app/etl/fetch/north_america/helpers.py`
- `app/etl/fetch/north_america/make_sources.py`
- `app/etl/fetch/north_america/ohm_convert.py`
- `app/etl/fetch/north_america/ohm_fetch.py`
- `app/etl/history/__init__.py`
- `app/etl/history/border_sides.py`
- `app/etl/history/events_from_wikidata.py`
- `app/etl/history/fields_polygons.py`
- `app/etl/history/labels.py`
- `app/etl/history/na_sides.py`
- `app/etl/history/settlements.py`
- `app/etl/history/wars.py`
- `app/etl/net.py`
- `app/etl/polity_qids.py`
- `app/etl/profile.py`
- `app/etl/research/__init__.py`
- `app/etl/research/merge.py`
- `app/etl/research/review.py`
- `app/etl/research/verify_quotes.py`
- `app/etl/shp.py`
- `pipeline/__init__.py`
- `pipeline/influence.py`
- `app/scenes/north-america.json`
- `app/sources/catalogue.json`
- `app/sources/profiles.json`
- `app/sources/sides.json`
- `app/sources/north-america/canada_treaties.json`
- `app/research/north-america-1492-1900.raw.json`
- `app/research/north-america-1492-1900.verification.part1.json`
- `app/research/north-america-1492-1900.verification.part2.json`
- `app/research/north-america-1492-1900.verification.part3.json`
- `app/src/lib/themes.ts`
