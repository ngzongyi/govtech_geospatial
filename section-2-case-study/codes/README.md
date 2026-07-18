# Section 2 Case Study — Scenario 1: Preschool Demand-Supply Forecast

Forecasts subzone-level demand for childcare (18mo-6y) in Singapore through 2031, compares it
against current ECDA-licensed supply, and produces a prioritised build/relocate list for ECDA —
plus a working MVP of a recurring internal tool.

## What's here

```
codes/
├── childcare_analysis.ipynb  # the full analysis: narrative, code, charts, all in one notebook
├── data/
│   ├── raw/               # source CSVs (population, BTO, ECDA centres, births/TFR, etc.)
│   ├── geo/                # URA Master Plan 2019 subzone boundary (GeoJSON)
│   └── cache/               # geocoding cache (auto-created on first run, safe to delete)
├── output/
│   ├── charts/             # every chart the notebook produces, as PNGs
│   └── data/                 # gap table, priority lists, summary.json
├── tool/                  # runnable Streamlit MVP of the Section 9 tool concept -- see tool/README.md
└── README.md              # this file
```

## How to run it

1. **Python 3.11+** with: `pandas numpy matplotlib geopandas shapely pyproj requests jupyter`
   ```
   pip install pandas numpy matplotlib geopandas shapely pyproj requests jupyter
   ```
2. Run from **inside this `codes/` folder** (the notebook uses relative paths):
   ```
   jupyter nbconvert --to notebook --execute --inplace childcare_analysis.ipynb
   ```
   or open it in Jupyter/VS Code and run all cells.
3. **First run only**: Section 4 geocodes ~1,700 unique postal codes against the free
   [OneMap](https://www.onemap.gov.sg/) public API (no key needed). This takes a few minutes and
   is cached to `data/cache/postal_code_geocode.csv` — every run after the first reuses the cache
   and finishes in well under a minute. If OneMap is unreachable (offline / blocked), delete
   nothing — the notebook will simply reuse whatever's already cached and report a lower match
   rate rather than failing.
4. **Want the interactive version?** A working MVP dashboard (same model, live sliders) lives in
   `tool/`. Run it from **inside `codes/tool/`**:
   ```
   cd tool
   pip install -r requirements.txt
   streamlit run app.py
   ```
   Opens at `http://localhost:8501`. First load reuses the geocoding cache already shipped in
   `data/cache/`, so it's quick — no network calls unless you upload a centre listing with
   postal codes that aren't cached yet. `Ctrl+C` in the terminal to stop it. See `tool/README.md`
   for what's interactive (sliders, data refresh, map views) and what it deliberately doesn't do.

No API keys or credentials are required anywhere in this notebook.

## Where the outputs land

- `output/charts/` — every figure in the accompanying slide deck, numbered in the order it
  appears in the notebook.
- `output/data/gap_table_all_subzones.csv` — the full subzone-level model output (demand, supply,
  gap, category, and the Section 6.6 younger/older sub-band columns) for all forecast years.
- `output/data/priority_build_list.csv` / `relocation_candidates.csv` — the two lists ECDA asked
  for.
- `output/data/priority_build_list_with_subbands.csv` — the priority list annotated with whether
  each subzone's shortage is younger-band-, older-band-, or mixed-driven (Section 6.6).
- `output/data/masked_subzones_2026.csv` / `masked_subzones_2031.csv` — subzones the combined
  (flat-capacity) view calls comfortable but that are short in one specific age band (Section 6.6).
- `output/data/deficit_cascade_by_year.csv` — every subzone, with the first year it tips into
  deficit (Section 6.5).
- `output/data/summary.json` — headline figures cited in the deck, machine-readable.

## Key assumptions (see the notebook for full detail and rationale)

| Assumption | Value | Set in |
|---|---|---|
| Childcare capacity per centre | 100 children | Given in the case brief |
| Age-band apportionment (Census 5-yr bands → 18mo-6y) | 0.70 × age 0-4, 0.40 × age 5-9 | Section 5.1 |
| Formal-care participation rate | ~modelled from 2020 national enrolment vs. eligible population | Section 5.2 |
| BTO child-yield | 0.28 children (18mo-6y) per new unit | Section 5.4, sensitivity-tested in Section 7.2 |
| Forecast horizon | 2026-2031 | — |
| Per-level capacity split (younger 18mo-4y vs. older 5-6y) | Each centre's 100-child norm divided evenly across the levels it actually runs | Section 6.6 |

All are stated explicitly at the point they're used in `childcare_analysis.ipynb`, along with what
would be needed to replace each with a measured figure instead of a planning assumption.
