"""ECDA Childcare Demand-Supply MVP dashboard.

Interactive version of ../childcare_analysis.ipynb Sections 4-8: adjust the two judgment-call
assumptions live, or drop in refreshed population/BTO/centre-listing data, and the
map/priority list/cascade recompute immediately. See ../childcare_analysis.ipynb for the full
methodology write-up -- this app deliberately does not repeat that narrative, it exists
to demonstrate the tool concept described in that notebook's Section 9.

Run from inside this folder:  streamlit run app.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import Patch
import streamlit as st

import model as m

st.set_page_config(page_title="ECDA Childcare Demand-Supply Tool", layout="wide")

# .resolve() first: if this script is launched with a relative path (e.g. plain
# `streamlit run app.py`), __file__ can come through as just "app.py" with no directory
# component, and .parent.parent on that stays "." instead of climbing to codes/ -- resolving
# to an absolute path before taking parents makes this work regardless of the invocation style.
_THIS_DIR = Path(__file__).resolve().parent
DATA_RAW = _THIS_DIR.parent / "data" / "raw"
DATA_GEO = _THIS_DIR.parent / "data" / "geo"
DATA_CACHE = _THIS_DIR.parent / "data" / "cache"

C_DEFICIT, C_SURPLUS, C_NEUTRAL, C_BTO = "#C0392B", "#2E86AB", "#95A5A6", "#E67E22"
YEAR_COLORS = {2026: "#67000d", 2027: "#a50f15", 2028: "#cb181d", 2029: "#ef3b2c", 2030: "#fb6a4a", 2031: "#fcbba1"}
NEVER_COLOR = "#c6dbef"


# ---------------------------------------------------------------- cached loaders ----

@st.cache_data(show_spinner="Loading population, BTO and national trend data...")
def load_demand_inputs(pop_file, bto_file):
    pop_subzone = m.parse_subzone_hierarchical_csv(
        pop_file or DATA_RAW / "ResidentPopulationbyPlanningAreaSubzoneofResidenceAgeGroupandSexCensusofPopulation2020.csv"
    )
    natl_age = m.load_national_age_trend(DATA_RAW / "SingaporeResidentsByAgeGroupEthnicGroupAndSexAtEndJuneAnnual.csv")
    natl_places = m.load_national_places_enrolment(DATA_RAW / "TotalNumberOfPlacesAndEnrolmentForChildcareAnnual.csv")
    bto = m.load_bto(bto_file or DATA_RAW / "btomapping.csv")
    return pop_subzone, natl_age, natl_places, bto


@st.cache_data(show_spinner="Loading subzone boundaries...")
def load_boundaries():
    return m.load_subzone_boundaries(DATA_GEO / "MasterPlan2019SubzoneBoundaryNoSea.geojson")


@st.cache_data(show_spinner="Geocoding centres and building the supply map (only new postal codes hit the network)...")
def load_supply(centres_file, _subzones_gdf):
    centres = m.load_centres(centres_file or DATA_RAW / "ListingofCentres.csv")
    cache_path = DATA_CACHE / "postal_code_geocode.csv"
    geocode_cache = pd.read_csv(cache_path, dtype={"postal_code": str}) if cache_path.exists() else pd.DataFrame(columns=["postal_code", "lat", "lon"])
    _, centres_geo = m.geocode_centres(centres, geocode_cache)
    return m.build_supply(centres_geo, _subzones_gdf), int(centres_geo["lat"].notna().sum()), int(len(centres_geo))


# ---------------------------------------------------------------- sidebar ----

st.sidebar.title("Assumptions")
bto_yield = st.sidebar.slider(
    "BTO child-yield (18mo-6y children per new unit)", 0.0, 0.6, m.DEFAULT_BTO_YIELD, 0.01,
    help="Notebook Section 5.4's base case is 0.28. Section 7.2 shows the top-15 priority list "
         "is stable to +/-50% of this value.",
)
auto_participation = st.sidebar.checkbox("Auto-compute participation rate from 2020 enrolment", value=True)
manual_participation = None
if not auto_participation:
    manual_participation = st.sidebar.slider("Participation rate override (%)", 30, 95, 63) / 100

st.sidebar.divider()
st.sidebar.subheader("Refresh data (optional)")
pop_file = st.sidebar.file_uploader("Updated population by subzone x age (Census-shape CSV)", type="csv")
bto_file = st.sidebar.file_uploader("Updated BTO pipeline CSV", type="csv")
centres_file = st.sidebar.file_uploader("Updated ECDA centre listing CSV", type="csv")
st.sidebar.caption(
    "Leave blank to use the data shipped in `codes/data/raw/`. A new centre listing triggers "
    "geocoding for any postal code not already cached -- fast for a handful of new/moved "
    "centres, slower the first time for a wholesale refresh."
)

st.sidebar.divider()
map_view = st.sidebar.radio("Map view", ["Gap for a selected year", "First year of deficit (roadmap)"])
selected_year = st.sidebar.select_slider("Year", options=m.DEFAULT_FORECAST_YEARS, value=2031)


# ---------------------------------------------------------------- pipeline ----

pop_subzone, natl_age, natl_places, bto = load_demand_inputs(pop_file, bto_file)
subzones_gdf = load_boundaries()
subzone_master = subzones_gdf[["subzone", "planning_area"]].drop_duplicates(subset="subzone").set_index("subzone")
supply, n_geocoded, n_centres_total = load_supply(centres_file, subzones_gdf)

participation_rate = manual_participation
gap_table, participation_rate_used = m.run_full_pipeline(
    pop_subzone, natl_age, natl_places, bto, supply, subzone_master,
    forecast_years=m.DEFAULT_FORECAST_YEARS, bto_yield=bto_yield, participation_rate=participation_rate,
)


# ---------------------------------------------------------------- header + metrics ----

st.title("Subzone-Level Childcare Demand-Supply Tool")
st.caption(
    "MVP for ECDA -- recomputes the model from `childcare_analysis.ipynb` Sections 4-8 live. "
    "Adjust assumptions in the sidebar, or upload refreshed data, and everything below updates."
)

deficit_share = (gap_table[f"gap_{m.DEFAULT_FORECAST_YEARS[0]}"] > 0).mean()
total_deficit = gap_table.loc[gap_table[f"gap_{m.DEFAULT_FORECAST_YEARS[-1]}"] > 0, f"gap_{m.DEFAULT_FORECAST_YEARS[-1]}"].sum()
total_surplus = -gap_table.loc[gap_table[f"gap_{m.DEFAULT_FORECAST_YEARS[-1]}"] < 0, f"gap_{m.DEFAULT_FORECAST_YEARS[-1]}"].sum()

c1, c2, c3, c4 = st.columns(4)
c1.metric("National utilisation (2024, actual)", f"{natl_places.loc[2024, 'utilisation']:.0%}")
c1.metric("Participation rate used", f"{participation_rate_used:.1%}")
c2.metric("Subzones in deficit today", f"{int((gap_table[f'gap_{m.DEFAULT_FORECAST_YEARS[0]}']>0).sum())}", f"{deficit_share:.0%} of {len(gap_table)}")
c3.metric(f"Centres needed by {m.DEFAULT_FORECAST_YEARS[-1]}", f"{int(gap_table['centres_needed'].sum())}")
c4.metric("Surplus : deficit ratio, 2031", f"{(total_surplus/total_deficit if total_deficit else float('nan')):.2f}x")
st.caption(f"Supply: {n_geocoded:,} / {n_centres_total:,} centres successfully geocoded ({n_geocoded/max(n_centres_total,1):.0%}).")


# ---------------------------------------------------------------- map ----

st.subheader("Map")
plot_gdf = subzones_gdf.merge(gap_table, left_on="subzone", right_index=True, how="left")

fig, ax = plt.subplots(figsize=(8, 8.5))
if map_view == "Gap for a selected year":
    vmax = plot_gdf[f"gap_{selected_year}"].abs().quantile(0.97) or 1
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
    plot_gdf.plot(column=f"gap_{selected_year}", cmap="RdBu_r", norm=norm, edgecolor="white", linewidth=0.15, ax=ax)
    sm = plt.cm.ScalarMappable(cmap="RdBu_r", norm=norm)
    cbar = fig.colorbar(sm, ax=ax, orientation="horizontal", fraction=0.045, pad=0.02, shrink=0.6)
    cbar.set_label("Demand - supply (children)  |  red = deficit, blue = surplus")
    ax.set_title(f"Demand-supply gap, {selected_year}", fontsize=13, loc="left")
else:
    plot_gdf["fill_color"] = plot_gdf["first_deficit_year"].map(YEAR_COLORS).fillna(NEVER_COLOR)
    plot_gdf.plot(color=plot_gdf["fill_color"], edgecolor="white", linewidth=0.15, ax=ax)
    handles = [Patch(facecolor=YEAR_COLORS[y], label=str(y)) for y in m.DEFAULT_FORECAST_YEARS]
    handles.append(Patch(facecolor=NEVER_COLOR, label="Comfortable throughout"))
    ax.legend(handles=handles, loc="lower left", frameon=False, fontsize=8.5, title="First year in deficit")
    ax.set_title("When each subzone first tips into deficit", fontsize=13, loc="left")
ax.axis("off")
st.pyplot(fig, width="stretch")


# ---------------------------------------------------------------- lists + cascade ----

left, right = st.columns([3, 2])

with left:
    st.subheader("Priority build/relocate list")
    display_cols = ["planning_area", "category", "n_centres", f"gap_{m.DEFAULT_FORECAST_YEARS[0]}",
                     f"gap_{m.DEFAULT_FORECAST_YEARS[-1]}", "centres_needed", "first_deficit_year"]
    priority = gap_table[gap_table["category"].str.startswith(("Urgent", "Emerging"))].sort_values(
        f"gap_{m.DEFAULT_FORECAST_YEARS[-1]}", ascending=False
    )
    st.dataframe(priority[display_cols].round(0), width="stretch", height=420)
    st.download_button(
        "Download full gap table (CSV)",
        gap_table.to_csv().encode("utf-8"),
        "gap_table.csv",
        "text/csv",
    )

with right:
    st.subheader("Year-by-year cascade")
    cascade = pd.DataFrame({
        "newly_at_risk": [int((gap_table["first_deficit_year"] == y).sum()) for y in m.DEFAULT_FORECAST_YEARS],
        "cumulative_centres": [
            int(np.ceil(gap_table[f"gap_{y}"].clip(lower=0) / m.CAPACITY_PER_CENTRE).sum())
            for y in m.DEFAULT_FORECAST_YEARS
        ],
    }, index=pd.Index(m.DEFAULT_FORECAST_YEARS, name="year"))

    fig2, ax1 = plt.subplots(figsize=(5.5, 4))
    ax1.bar(cascade.index, cascade["newly_at_risk"], color=C_DEFICIT, alpha=0.85)
    ax1.set_ylabel("Newly at-risk subzones")
    ax2 = ax1.twinx()
    ax2.plot(cascade.index, cascade["cumulative_centres"], color="black", marker="o", linewidth=2)
    ax2.set_ylabel("Cumulative centres needed")
    ax2.grid(False)
    fig2.tight_layout()
    st.pyplot(fig2, width="stretch")
    st.caption("Bars: subzones newly crossing into deficit that year. Line: running total of additional centres needed.")

st.divider()
st.caption(
    "Full methodology, hypothesis testing and limitations: see `../childcare_analysis.ipynb`. "
    "This dashboard is the Section 9 tool concept made runnable, not a replacement for the notebook's narrative."
)
