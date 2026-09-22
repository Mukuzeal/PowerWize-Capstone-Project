"""solar_calc_check.py — prints solar_engine.compute() output for a handful of
sample inputs so the sizing math can be hand-checked. Read-only, no DB access.

Run from the src/ directory so flat imports resolve:
    cd src && ..\\venv\\Scripts\\python.exe ..\\scripts\\solar_calc_check.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from solar_engine import compute

SAMPLES = [
    {
        "label": "Residential, ₱8,000/mo bill, 100% target, 30 sqm roof",
        "kwh_monthly": None, "bill_php": 8000, "target_savings": "100",
        "roof_sqm": 30, "time_of_use_night_pct": 20,
        "electrical_phase": "single", "establishment_type": "residential",
        "grid_connection": "grid_tie",
    },
    {
        "label": "Residential, 350 kWh/mo, 50% target, small roof",
        "kwh_monthly": 350, "bill_php": None, "target_savings": "50",
        "roof_sqm": 10, "time_of_use_night_pct": 15,
        "electrical_phase": "single", "establishment_type": "residential",
        "grid_connection": "grid_tie",
    },
    {
        "label": "Commercial, 3-phase, high night usage -> hybrid expected",
        "kwh_monthly": 4000, "bill_php": None, "target_savings": "100",
        "roof_sqm": 300, "time_of_use_night_pct": 45,
        "electrical_phase": "three", "establishment_type": "commercial",
        "grid_connection": "grid_tie",
    },
    {
        "label": "Off-grid remote site -> battery required, no savings/payback",
        "kwh_monthly": 200, "bill_php": None, "target_savings": "100",
        "roof_sqm": 40, "time_of_use_night_pct": 40,
        "electrical_phase": "single", "establishment_type": "residential",
        "grid_connection": "off_grid",
    },
]


def main():
    for sample in SAMPLES:
        label = sample.pop("label")
        print(f"\n=== {label} ===")
        print("Input: ", {k: v for k, v in sample.items()})
        result = compute(**sample)
        print("Output:", json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
