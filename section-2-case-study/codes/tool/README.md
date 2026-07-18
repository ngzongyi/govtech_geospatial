# MVP: ECDA Childcare Demand-Supply Tool

A runnable version of the recurring decision-support tool described in `childcare_analysis.ipynb`
Section 9 — not a mockup. It reuses the same model logic as the notebook (`model.py` mirrors
Sections 4-8) so adjusting an assumption or dropping in a refreshed data file actually
recomputes the demand/supply/gap model, live.

## Run it

From inside this folder:

```
pip install -r requirements.txt
streamlit run app.py
```

Opens at `http://localhost:8501`. First launch is instant — it reuses the fully-geocoded
cache already shipped in `../data/cache/postal_code_geocode.csv` (99% match rate from the
notebook run), so no network calls happen unless you upload a centre listing with postal
codes that aren't in that cache yet.

## What's interactive

- **BTO child-yield** and **participation rate** sliders — the map, metrics, priority list and
  cascade chart recompute immediately (pure pandas, no I/O, sub-second).
- **Upload a refreshed population, BTO, or centre-listing CSV** in the sidebar to override the
  shipped data for that input. Population/BTO refreshes are instant. A centre-listing refresh
  re-geocodes and re-joins to subzones — fast if it's mostly the same centres (cache reuse),
  slower the first time for a wholesale replacement (uncached postal codes hit the free OneMap
  API, a few requests/second).
- **Map view toggle**: gap magnitude for any single forecast year, or the "first year in
  deficit" roadmap map from notebook Section 6.5.

## What this MVP deliberately doesn't do

- No authentication, no persistence between sessions, no run history/versioning — Section 9's
  production sketch (scheduled ETL, access control, run logging) is still a description, not
  code, in the notebook. This is the "adjust assumptions and see it update" core loop made
  real, which is the part most useful to validate with ECDA planners before investing further.
- No accessibility/travel-time modelling — same subzone-boundary limitation as the notebook
  (Section 10.1).

## Files

- `app.py` — Streamlit UI.
- `model.py` — the actual model: data parsing, geocoding, demand/supply/gap computation.
  Deliberately kept close to `childcare_analysis.ipynb`'s own code so the two don't drift apart; if you
  change the methodology in the notebook, mirror the change here.
- `requirements.txt` — dependencies (superset of what the notebook needs, plus `streamlit`).
