"""Reusable model functions for the ECDA childcare demand-supply MVP dashboard.

Mirrors the methodology in ../childcare_analysis.ipynb -- see that notebook for the full narrative,
data exploration, and justification behind every assumption below. This module exists so
the same logic can be re-run interactively (new data, adjusted assumptions) without
re-executing the whole notebook. Kept deliberately close to the notebook's own code so the
two don't drift into disagreement.
"""
import re
import time

import numpy as np
import pandas as pd
import geopandas as gpd
import requests

CAPACITY_PER_CENTRE = 100
BAND_WEIGHT_0_4 = 0.70
BAND_WEIGHT_5_9 = 0.40
BASE_YEAR_CENSUS = 2020
LATEST_ACTUAL_YEAR = 2025
DEFAULT_FORECAST_YEARS = [2026, 2027, 2028, 2029, 2030, 2031]
DEFAULT_BTO_YIELD = 0.28
CHILDCARE_LEVELS = ["pg", "n1", "n2", "k1", "k2"]
RELOCATION_SURPLUS_THRESHOLD = -20


# ---------------------------------------------------------------- loaders ----

def parse_subzone_hierarchical_csv(path_or_buffer):
    """Parse data.gov.sg's '<Planning Area> - Total' / subzone hierarchical CSV shape."""
    df = pd.read_csv(path_or_buffer)
    label_col = df.columns[0]
    value_cols = list(df.columns[1:])
    df[value_cols] = df[value_cols].replace("-", 0)
    for c in value_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df = df[df[label_col] != "Total"].reset_index(drop=True)

    marker_re = re.compile(r"\s*-\s*Total$")
    planning_area, pa_col, sz_col, pa_flag = None, [], [], []
    for label in df[label_col]:
        if marker_re.search(label):
            planning_area = marker_re.sub("", label).strip()
            pa_col.append(planning_area); sz_col.append(None); pa_flag.append(True)
        else:
            pa_col.append(planning_area); sz_col.append(label.strip()); pa_flag.append(False)
    df["planning_area"], df["subzone"], df["is_pa_total"] = pa_col, sz_col, pa_flag
    return df[~df["is_pa_total"]].drop(columns=["is_pa_total", label_col]).reset_index(drop=True)


def load_national_age_trend(path_or_buffer):
    raw = pd.read_csv(path_or_buffer, index_col=0)
    raw.index = raw.index.str.strip()
    block_end = raw.index.get_loc("Total Male Residents")
    age = raw.iloc[:block_end].T
    age.index = age.index.astype(int)
    age = age.sort_index()
    age = age.rename(columns={"Total Residents": "total", "0 - 4 Years": "age_0_4", "5 - 9 Years": "age_5_9"})
    return age[["total", "age_0_4", "age_5_9"]].apply(pd.to_numeric)


def load_national_places_enrolment(path_or_buffer):
    raw = pd.read_csv(path_or_buffer, index_col=0)
    natl = raw.loc[["Total Enrolment In Childcare", "Total Number Of Places In Childcare"]].T
    natl.index = natl.index.astype(int)
    natl.columns = ["enrolment", "places"]
    natl = natl.sort_index()
    natl["utilisation"] = natl["enrolment"] / natl["places"]
    return natl


def load_bto(path_or_buffer):
    bto = pd.read_csv(path_or_buffer)
    bto.columns = ["project_name", "region", "planning_area", "subzone", "completion_year", "units"]
    bto["subzone"] = bto["subzone"].str.strip()
    bto["completion_year"] = pd.to_numeric(bto["completion_year"], errors="coerce")
    return bto


def load_centres(path_or_buffer):
    centres = pd.read_csv(path_or_buffer, dtype={"postal_code": str})
    centres["postal_code"] = centres["postal_code"].str.zfill(6)
    for lvl in ["infant"] + CHILDCARE_LEVELS:
        col = f"{lvl}_vacancy_current_month"
        centres[f"offers_{lvl}"] = centres[col] != "Not Applicable"
    centres["is_childcare_centre"] = centres[[f"offers_{lvl}" for lvl in CHILDCARE_LEVELS]].any(axis=1)
    level_cols = [f"{lvl}_vacancy_current_month" for lvl in CHILDCARE_LEVELS]

    def pct_full(row):
        vals = [row[c] for c in level_cols if row[c] != "Not Applicable"]
        return np.mean([v == "Full" for v in vals]) if vals else np.nan

    centres["pct_levels_full"] = centres.apply(pct_full, axis=1)
    return centres[centres["is_childcare_centre"]].copy()


def to_title_case(s):
    s2 = s.str.title()
    return s2.str.replace(r"(?<=')([A-Z])", lambda m: m.group(1).lower(), regex=True)


def load_subzone_boundaries(path_or_buffer):
    gdf = gpd.read_file(path_or_buffer)
    gdf = gdf.rename(columns={"SUBZONE_N": "subzone_raw", "PLN_AREA_N": "planning_area_raw"})
    gdf["subzone"] = to_title_case(gdf["subzone_raw"])
    gdf["planning_area"] = to_title_case(gdf["planning_area_raw"])
    gdf = gdf[["subzone", "planning_area", "geometry"]]
    return gdf.set_crs(epsg=4326) if gdf.crs is None else gdf


# ------------------------------------------------------------- geocoding ----

def geocode_postal_code(postal, retries=4, base_delay=0.8):
    for attempt in range(retries):
        try:
            r = requests.get(
                "https://www.onemap.gov.sg/api/common/elastic/search",
                params={"searchVal": postal, "returnGeom": "Y", "getAddrDetails": "N", "pageNum": 1},
                timeout=10,
            )
            if r.status_code == 200:
                js = r.json()
                if js.get("found", 0) > 0:
                    res = js["results"][0]
                    return postal, float(res["LATITUDE"]), float(res["LONGITUDE"])
                return postal, None, None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(base_delay * (2 ** attempt))
    return postal, None, None


def geocode_centres(centres, geocode_cache_df, progress_cb=None):
    """Geocode any postal codes not already in geocode_cache_df.
    Returns (updated_cache_df, centres_merged_with_latlon). Reuses cached postal
    codes so this is instant unless the uploaded centre list has genuinely new addresses.
    """
    postal_codes = sorted(centres["postal_code"].dropna().unique())
    cache = geocode_cache_df.copy()
    cache["postal_code"] = cache["postal_code"].astype(str).str.zfill(6)
    already_ok = set(cache.loc[cache["lat"].notna(), "postal_code"])
    missing = [p for p in postal_codes if p not in already_ok]
    if missing:
        results = []
        for i, p in enumerate(missing):
            results.append(geocode_postal_code(p))
            if progress_cb:
                progress_cb((i + 1) / len(missing), p)
        new_df = pd.DataFrame(results, columns=["postal_code", "lat", "lon"])
        cache = pd.concat([cache[~cache["postal_code"].isin(new_df["postal_code"])], new_df], ignore_index=True)
    merged = centres.merge(cache, on="postal_code", how="left")
    return cache, merged


def build_supply(centres_geo, subzones_gdf):
    """Spatial-join geocoded centres onto subzones and aggregate to subzone-level supply."""
    geocoded_ok = centres_geo["lat"].notna()
    gdf = gpd.GeoDataFrame(
        centres_geo[geocoded_ok].copy(),
        geometry=gpd.points_from_xy(centres_geo.loc[geocoded_ok, "lon"], centres_geo.loc[geocoded_ok, "lat"]),
        crs="EPSG:4326",
    )
    gdf = gpd.sjoin(gdf, subzones_gdf[["subzone", "planning_area", "geometry"]], how="left", predicate="within")
    unmatched = gdf["subzone"].isna()
    if unmatched.any():
        nearest = gpd.sjoin_nearest(
            gdf.loc[unmatched, ["centre_code", "geometry"]],
            subzones_gdf[["subzone", "planning_area", "geometry"]],
            how="left",
        ).drop_duplicates(subset="centre_code").set_index("centre_code")
        for col in ["subzone", "planning_area"]:
            gdf.loc[unmatched, col] = gdf.loc[unmatched, "centre_code"].map(nearest[col])
    gdf = gdf[gdf["subzone"].notna()]

    supply = gdf.groupby("subzone").agg(
        n_centres=("centre_code", "count"), pct_full_avg=("pct_levels_full", "mean")
    ).reset_index()
    supply["capacity"] = supply["n_centres"] * CAPACITY_PER_CENTRE
    subzone_list = subzones_gdf[["subzone", "planning_area"]].drop_duplicates(subset="subzone")
    supply = subzone_list.merge(supply, on="subzone", how="left")
    supply[["n_centres", "capacity"]] = supply[["n_centres", "capacity"]].fillna(0)
    return supply.set_index("subzone")


# ---------------------------------------------------------------- demand ----

def compute_participation_rate(pop_subzone, natl_age, natl_places):
    national_eligible = (
        BAND_WEIGHT_0_4 * natl_age.loc[BASE_YEAR_CENSUS, "age_0_4"]
        + BAND_WEIGHT_5_9 * natl_age.loc[BASE_YEAR_CENSUS, "age_5_9"]
    )
    return natl_places.loc[BASE_YEAR_CENSUS, "enrolment"] / national_eligible


def compute_growth_factors(natl_age, forecast_years):
    cagr_0_4 = (natl_age.loc[LATEST_ACTUAL_YEAR, "age_0_4"] / natl_age.loc[BASE_YEAR_CENSUS, "age_0_4"]) ** (
        1 / (LATEST_ACTUAL_YEAR - BASE_YEAR_CENSUS)
    ) - 1
    cagr_5_9 = (natl_age.loc[LATEST_ACTUAL_YEAR, "age_5_9"] / natl_age.loc[BASE_YEAR_CENSUS, "age_5_9"]) ** (
        1 / (LATEST_ACTUAL_YEAR - BASE_YEAR_CENSUS)
    ) - 1
    out = {}
    for y in forecast_years:
        if y <= LATEST_ACTUAL_YEAR and y in natl_age.index:
            f04 = natl_age.loc[y, "age_0_4"] / natl_age.loc[BASE_YEAR_CENSUS, "age_0_4"]
            f59 = natl_age.loc[y, "age_5_9"] / natl_age.loc[BASE_YEAR_CENSUS, "age_5_9"]
        else:
            base04 = natl_age.loc[LATEST_ACTUAL_YEAR, "age_0_4"] / natl_age.loc[BASE_YEAR_CENSUS, "age_0_4"]
            base59 = natl_age.loc[LATEST_ACTUAL_YEAR, "age_5_9"] / natl_age.loc[BASE_YEAR_CENSUS, "age_5_9"]
            f04 = base04 * (1 + cagr_0_4) ** (y - LATEST_ACTUAL_YEAR)
            f59 = base59 * (1 + cagr_5_9) ** (y - LATEST_ACTUAL_YEAR)
        out[y] = {"factor_0_4": f04, "factor_5_9": f59}
    return pd.DataFrame(out).T


def compute_organic_demand(pop_subzone, forecast_years, participation_rate, growth_factor_df):
    pop_indexed = pop_subzone.set_index("subzone")
    organic = pd.DataFrame(index=pop_indexed.index)
    for y in forecast_years:
        gf = growth_factor_df.loc[y]
        organic[y] = (
            BAND_WEIGHT_0_4 * pop_indexed["Total_0_4"] * gf["factor_0_4"]
            + BAND_WEIGHT_5_9 * pop_indexed["Total_5_9"] * gf["factor_5_9"]
        ) * participation_rate
    return organic


def compute_bto_demand(bto, subzone_index, forecast_years, yield_per_unit):
    bto_valid = bto.dropna(subset=["completion_year", "subzone"]).copy()
    bto_valid["completion_year"] = bto_valid["completion_year"].astype(int)
    cols = {}
    for y in forecast_years:
        active = bto_valid[bto_valid["completion_year"] <= y].copy()
        active["occ_factor"] = np.where(active["completion_year"] == y, 0.5, 1.0)
        active["contribution"] = active["units"] * yield_per_unit * active["occ_factor"]
        cols[y] = active.groupby("subzone")["contribution"].sum()
    out = pd.DataFrame(cols)
    return out.reindex(subzone_index).fillna(0.0)


# ---------------------------------------------------------------- gap ----

def build_gap_table(subzone_master, supply, organic_demand, bto_demand, forecast_years):
    gap_table = subzone_master.copy()
    gap_table["supply"] = supply["capacity"].reindex(subzone_master.index).fillna(0)
    gap_table["n_centres"] = supply["n_centres"].reindex(subzone_master.index).fillna(0)
    if "pct_full_avg" in supply.columns:
        gap_table["pct_full_avg"] = supply["pct_full_avg"].reindex(subzone_master.index)

    total_demand = organic_demand.reindex(subzone_master.index).fillna(0) + bto_demand.reindex(subzone_master.index).fillna(0)
    for y in forecast_years:
        gap_table[f"demand_{y}"] = total_demand[y]
        gap_table[f"bto_{y}"] = bto_demand[y].reindex(subzone_master.index).fillna(0)
        gap_table[f"gap_{y}"] = gap_table[f"demand_{y}"] - gap_table["supply"]

    gap_table["gap_trend"] = gap_table[f"gap_{forecast_years[-1]}"] - gap_table[f"gap_{forecast_years[0]}"]
    gap_table["centres_needed"] = np.ceil(gap_table[f"gap_{forecast_years[-1]}"].clip(lower=0) / CAPACITY_PER_CENTRE)

    def _first_deficit(row):
        for y in forecast_years:
            if row[f"gap_{y}"] > 0:
                return y
        return np.nan

    gap_table["first_deficit_year"] = gap_table.apply(_first_deficit, axis=1)

    def _cat(row):
        if row[f"gap_{forecast_years[0]}"] > 0:
            return "Urgent: deficit today"
        elif row[f"gap_{forecast_years[-1]}"] > 0:
            return f"Emerging: deficit by {forecast_years[-1]}"
        elif row["gap_trend"] < RELOCATION_SURPLUS_THRESHOLD:
            return "Relocation candidate"
        return "Comfortable"

    gap_table["category"] = gap_table.apply(_cat, axis=1)
    return gap_table


def run_full_pipeline(pop_subzone, natl_age, natl_places, bto, supply, subzone_master,
                       forecast_years=DEFAULT_FORECAST_YEARS, bto_yield=DEFAULT_BTO_YIELD,
                       participation_rate=None):
    """One call, from loaded inputs to the final gap table -- what the app re-runs on every
    slider change. Geocoding/spatial-join (the slow part) is NOT in here on purpose; `supply`
    is passed in already computed, so this stays fast enough to be interactive."""
    if participation_rate is None:
        participation_rate = compute_participation_rate(pop_subzone, natl_age, natl_places)
    growth_factor_df = compute_growth_factors(natl_age, forecast_years)
    organic_demand = compute_organic_demand(pop_subzone, forecast_years, participation_rate, growth_factor_df)
    bto_demand = compute_bto_demand(bto, organic_demand.index, forecast_years, bto_yield)
    gap_table = build_gap_table(subzone_master, supply, organic_demand, bto_demand, forecast_years)
    return gap_table, participation_rate
