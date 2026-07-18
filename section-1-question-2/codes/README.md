# COE Price Model & Quota Elasticity

Predicts COE prices for Category A & B, and works out how much price moves if quota changes.

## What's here

```
section-1-question-2/
├── codes/
│   ├── coe_analysis.ipynb   <- the analysis, start here
│   ├── data/                 raw source CSVs
│   └── output/                charts + tables the notebook produces
└── slides/
    └── coe_prediction_model_slides.pptx   short version of the findings
```

## Running it

Open `coe_analysis.ipynb` in Jupyter and run all cells top to bottom. Needs pandas, numpy,
matplotlib, scipy, statsmodels, scikit-learn.

## What's inside

- **Section 6** — the main number: quota elasticity ≈ -0.31 (Cat A) / -0.44 (Cat B). A plain
  regression misses this (multi-year cycles confound it); controlling for year fixes it.
- **Section 7** — forecasting next round's price. Simple beats fancy: last round's price / PQP
  beats machine learning.
- **Section 8** — turns the elasticity into an "add/remove X certificates → price impact" table,
  checked against a real quota change from May 2023.
- Everything else (Sections 1-5, 9-10) is setup, EDA, and caveats.

Six hypotheses are written down before looking at results (Section 1), scored at the end
(Section 10).
