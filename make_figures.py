"""
Generate the two experimental figures of the paper from the benchmark CSVs:
  - hf_cactus.png          (Fig. 11)  from results_compare_hf_full_dataset.csv
  - scaling_artificial.png (Fig. 12)  from scaling_artificial.csv

Usage:  python make_figures.py [--outdir .]
"""

import argparse
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))


def cactus(outdir):
    path = os.path.join(HERE, "results_compare_hf_full_dataset.csv")
    rows = list(csv.DictReader(open(path)))
    bad = [r for r in rows if r["agree"] != "1" or
           (r["ip_valid"] and r["ip_valid"] != "True" and r["ip_valid"] != "OK")]
    print(f"hf benchmark: {len(rows)} instances, disagreements/invalid: {len(bad)}")
    sat = sorted(float(r["sat_solve_ms"]) for r in rows)
    ip = sorted(float(r["ip_solve_ms"]) for r in rows)
    fig, ax = plt.subplots(figsize=(4.2, 2.2))
    ax.plot(range(1, len(ip) + 1), ip, color="#c0392b", label="IP (SCIP)", lw=1.3)
    ax.plot(range(1, len(sat) + 1), sat, color="#2471a3", label="SAT (Glucose 4)", lw=1.3)
    ax.set_yscale("log")
    ax.set_xlabel("instances solved")
    ax.set_ylabel("time per instance (ms)")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(True, which="both", alpha=.25)
    fig.tight_layout()
    out = os.path.join(outdir, "hf_cactus.png")
    fig.savefig(out, dpi=200)
    print("saved", out)


def scaling(outdir):
    path = os.path.join(HERE, "scaling_artificial.csv")
    rows = sorted(csv.DictReader(open(path)), key=lambda r: int(r["n"]))
    n_sat = [int(r["n"]) for r in rows if r["sat_solve_ms"]]
    sat_solve = [float(r["sat_solve_ms"]) / 1000 for r in rows if r["sat_solve_ms"]]
    sat_total = [(float(r["sat_encode_ms"]) + float(r["sat_solve_ms"])) / 1000
                 for r in rows if r["sat_solve_ms"]]
    n_ip = [int(r["n"]) for r in rows if r["ip_solve_ms"]]
    ip_solve = [float(r["ip_solve_ms"]) / 1000 for r in rows if r["ip_solve_ms"]]
    ip_total = [(float(r["ip_build_ms"]) + float(r["ip_solve_ms"])) / 1000
                for r in rows if r["ip_solve_ms"]]
    fig, ax = plt.subplots(figsize=(5.2, 2.2))
    ax.plot(n_ip, ip_total, "s-", color="#c0392b", label="IP (SCIP), build + solve")
    ax.plot(n_ip, ip_solve, "s--", color="#e08283", label="IP (SCIP), solve only")
    ax.plot(n_sat, sat_total, "o-", color="#2471a3", label="SAT (Glucose 4), encode + solve")
    ax.plot(n_sat, sat_solve, "o--", color="#7fb3d5", label="SAT (Glucose 4), solve only")
    ax.set_yscale("log")
    ax.set_xlabel(r"size parameter $n$  (grid $(2n{+}2)\times(2n{+}2)$)")
    ax.set_ylabel("time (s)")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=7, loc="upper left")
    fig.tight_layout()
    out = os.path.join(outdir, "scaling_artificial.png")
    fig.savefig(out, dpi=200)
    print("saved", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=HERE)
    ap.parse_args_ns = ap.parse_args()
    cactus(ap.parse_args_ns.outdir)
    scaling(ap.parse_args_ns.outdir)
