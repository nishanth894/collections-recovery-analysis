"""Builds figures, dashboard (HTML+PNG), dashboard_data.json, architecture diagram, memo PDF, DQ report from the SAME
analysis results (single source of truth). Usage: python -m src.build_reports"""
import json, subprocess, html
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from .config import REPORTS_DIR, FIG_DIR, ROOT
from . import analysis as A

CR = 1e7
NAVY, RED, GREY, GREEN, AMBER = "#1f3a5f", "#c0392b", "#8a94a6", "#2e8b57", "#d98e04"


def dashboard_data(R):
    m = R["monthly"].loc[A.FULL_MONTHS]
    cal, pdt = R["calendar"], R["per_day_test"]
    wf = R["waterfall"]
    drv = R["drivers"]
    inv = R["invest"]; ex = R["experiment"]["table"]
    r20 = ex[(ex.holdout_share == 0.2) & (ex.months == 3)].iloc[0]
    j, jn = m.iloc[-1], m.iloc[-2]
    D = {
        "months": list(m.index), "net_cr": (m.net_inr / CR).round(2).tolist(), "per_day_lakh": (m.net_inr_per_day / 1e5).round(2).tolist(),
        "claim_reported_style_feb_mar_pct": round(float(R["claim"].loc["B. Raw SUCCESS rows, duplicates included (₹)", "Feb→Mar %"]), 2),
        "golden_total_feb_mar_pct": round(cal["total_mom"] * 100, 2), "calendar_days_effect_pct": round(cal["calendar_days_effect"] * 100, 2),
        "golden_per_day_feb_mar_pct": round(cal["per_day_mom"] * 100, 2),
        "per_day_ci95_pct": [round(pdt["ci95"][0] * 100, 1), round(pdt["ci95"][1] * 100, 1)],
        "waterfall": [{"step": r.step_name, "inr_cr": round(float(r.running_inr) / CR, 2) if r.step in (1, 6) else round(float(r.delta_inr) / CR, 2)} for r in wf.itertuples()],
        "raw_total_cr": round(float(wf.iloc[0].delta_inr) / CR, 2), "golden_total_cr": round(float(wf.iloc[5].running_inr) / CR, 2),
        "kpi": {
            "contact_rate_account_pct": [round(j.contact_rate_account_pct, 1), round(j.contact_rate_account_pct - jn.contact_rate_account_pct, 2)],
            "rpc_rate_pct": [round(j.rpc_rate_pct, 1), round(j.rpc_rate_pct - jn.rpc_rate_pct, 2)],
            "ptp_rate_pct": [round(j.ptp_rate_pct, 1), round(j.ptp_rate_pct - jn.ptp_rate_pct, 2)],
            "ptp_kept_resolved_pct": [round(j.ptp_kept_rate_resolved_pct, 1), round(j.ptp_kept_rate_resolved_pct - jn.ptp_kept_rate_resolved_pct, 2)],
            "ptp_payment_verified_pct": [round(j.ptp_payment_verified_rate_pct, 1), round(j.ptp_payment_verified_rate_pct - jn.ptp_payment_verified_rate_pct, 2)],
            "recovery_rate_pct": [round(j.recovery_rate_fixed_pct, 2), round(j.recovery_rate_fixed_pct - jn.recovery_rate_fixed_pct, 3)],
            "recovery_per_agent_hour_inr": [round(j.recovery_per_agent_hour), round(j.recovery_per_agent_hour - jn.recovery_per_agent_hour)],
        },
        "trend_p": {k: round(float(R["trends"].loc[lab, "p_trend"]), 3) for k, lab in {"contact_rate_account_pct": "Contact rate, accounts (%)", "rpc_rate_pct": "RPC rate (%)", "ptp_rate_pct": "PTP rate (% of RPC)", "ptp_kept_resolved_pct": "PTP kept, status (% resolved)", "ptp_payment_verified_pct": "PTP kept, payment-verified (%)", "recovery_rate_pct": "Recovery rate (% outstanding)"}.items()},
        "drivers_tested": int(len(drv)), "drivers_sig_raw": int(drv["significant_raw_p<0.05"].sum()), "drivers_sig_fdr": int(drv["significant_after_BH_q<0.05"].sum()),
        "annual_run_rate_cr": round(inv["baseline"]["annualised_inr"] / CR, 1), "break_even_uplift_pct": round(inv["break_even_uplift_pct_100"], 2),
        "mde_20pct_holdout_3m_pct": round(r20.mde_rel_inr_per_account * 100, 1),
        "duplicate_inflation_pct": round(R["A"]["total_inflation_pct"], 2), "duplicate_inflation_cr": round(R["A"]["total_inflation_inr"] / CR, 2),
        "attribution_7d_pct": round(float(R["B_window"].loc[7, "attributed_pct_of_payments"]), 2),
        "attribution_7d_placebo_pct": round(float(R["B_window"].loc[7, "placebo_attributed_pct_mean"]), 2),
    }
    return D


def _fmt_delta(v, unit="pp", d=1):
    return f"{v:+.{d}f}{unit}"


def build_dashboard_html(D):
    mo = [x[5:] for x in D["months"]]
    names = dict(zip(["01", "02", "03", "04", "05", "06", "07"], ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"]))
    # --- SVG bar+line chart
    W, H, pl, pb = 440, 190, 34, 22
    mx = max(D["net_cr"]) * 1.12
    bw = (W - pl - 10) / len(mo)
    bars, labs, line_pts = [], [], []
    base = D["per_day_lakh"][0]
    for i, (cr, pdl) in enumerate(zip(D["net_cr"], D["per_day_lakh"])):
        x = pl + i * bw + bw * 0.18
        h = (H - pb - 10) * cr / mx
        hi = D["months"][i] == "2026-03"
        bars.append(f'<rect x="{x:.1f}" y="{H-pb-h:.1f}" width="{bw*0.64:.1f}" height="{h:.1f}" fill="{"var(--red)" if hi else "var(--bar)"}"/>'
                    f'<text x="{x+bw*0.32:.1f}" y="{H-pb-h-3:.1f}" font-size="9.5" text-anchor="middle" fill="var(--fg)">{cr:.0f}</text>')
        labs.append(f'<text x="{x+bw*0.32:.1f}" y="{H-6}" font-size="10" text-anchor="middle" fill="var(--mut)">{names[mo[i]]}</text>')
        yy = (H - pb - 10) * (1 - (pdl / (max(D["per_day_lakh"]) * 1.25)))
        line_pts.append((x + bw * 0.32, 10 + yy * 0 + (H - pb - 10) - (H - pb - 10) * pdl / (max(D["per_day_lakh"]) * 1.25) + 0))
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in line_pts)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="var(--amb)"/>' for x, y in line_pts)
    chart = (f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Monthly net recovery bars and per-day line">'
             f'{"".join(bars)}{"".join(labs)}<polyline points="{pts}" fill="none" stroke="var(--amb)" stroke-width="2"/>{dots}</svg>')
    # --- waterfall as horizontal bars
    wf = D["waterfall"]; maxv = D["raw_total_cr"]
    short = ["Raw payments (all rows)", "− duplicate payment_id", "− not settled (FAILED/PENDING/REVERSED)", "− outside window", "− current (dpd=0) accounts", "= Golden net recovery"]
    wrows = []
    for i, w in enumerate(wf):
        v = abs(w["inr_cr"]); wd = 190 * v / maxv
        col = "var(--bar)" if i in (0, 5) else "var(--red)"
        wrows.append(f'<div class="wr"><span class="wl">{short[i]}</span><span class="wb"><i style="width:{max(wd,1.5):.1f}px;background:{col}"></i></span><b>{"" if i in (0,5) else "−"}{v:,.1f}</b></div>')
    k = D["kpi"]
    def tile(label, key, unit="%", dfmt="pp", d=1, note=""):
        val, dl = k[key]
        vtxt = f"{val:,.0f}" if unit == "₹" else f"{val:.{d if unit!='%2' else 2}f}{'%' if unit=='%' else ''}"
        return (f'<div class="kpi"><div class="kl">{label}</div><div class="kv">{("₹" if unit=="₹" else "")}{vtxt}</div>'
                f'<div class="kd">{dl:+.1f} {dfmt} vs Jun · Jan–Jul trend p={D["trend_p"][key]:.2f}</div>{note}</div>')
    kp = "".join([
        tile("Contact rate (accounts)", "contact_rate_account_pct"), tile("Right-party contact", "rpc_rate_pct"),
        tile("PTP rate (of RPC)", "ptp_rate_pct"), tile("PTP kept (status)", "ptp_kept_resolved_pct"),
        tile("PTP kept (payment-verified)", "ptp_payment_verified_pct"),
        tile("Recovery rate (% of ₹ outstanding)", "recovery_rate_pct", unit="%", d=2),
    ])
    html_doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Collections recovery - executive dashboard</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--fg:#17202e;--mut:#667085;--bar:#3b5b88;--red:#c0392b;--amb:#d98e04;--ok:#2e8b57;--bd:#e3e6eb;box-sizing:border-box}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#10151d;--card:#18202c;--fg:#e8edf4;--mut:#9aa7b8;--bar:#6f93c4;--bd:#2a3444}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:13px/1.35 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:10px 12px}}
h1{{font-size:17px;margin:0 0 2px}}.sub{{color:var(--mut);font-size:11.5px;margin-bottom:8px}}
.ban{{background:var(--red);color:#fff;border-radius:8px;padding:9px 12px;font-size:14px;font-weight:600;margin-bottom:8px}}.ban span{{font-weight:400;font-size:12.5px;display:block;margin-top:2px}}
.g{{display:grid;grid-template-columns:1.15fr 1fr;gap:8px}}.c{{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:8px 10px}}
.c h2{{font-size:12px;margin:0 0 4px;text-transform:uppercase;letter-spacing:.4px;color:var(--mut)}}
.wr{{display:flex;align-items:center;gap:6px;font-size:11.5px;margin:2px 0}}.wl{{width:190px;flex:none}}.wb{{flex:1}}.wb i{{display:block;height:9px;border-radius:2px}}.wr b{{width:52px;text-align:right}}
.k{{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}}.kpi{{border:1px solid var(--bd);border-radius:6px;padding:5px 7px}}.kl{{font-size:10.5px;color:var(--mut)}}.kv{{font-size:18px;font-weight:700}}.kd{{font-size:10.5px;color:var(--mut)}}
.rec{{border-left:4px solid var(--ok)}}.rec p{{margin:3px 0}}.leg{{font-size:10.5px;color:var(--mut)}}.leg i{{display:inline-block;width:9px;height:9px;border-radius:2px;margin:0 3px 0 8px;vertical-align:middle}}
.pill{{display:inline-block;border-radius:10px;padding:0 7px;font-size:11px;background:var(--bd)}}
@media(max-width:820px){{.g{{grid-template-columns:1fr}}.k{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body>
<h1>Collections recovery: is “+11% month-on-month” real?</h1>
<div class="sub">Golden dataset (IST months), Jan–Jul 2026 full months; Aug 1–8 excluded as partial · all figures from SQL golden layer</div>
<div class="ban">NOT SUPPORTED — the 11% is a calendar effect.<span>Feb→Mar total recovery {D['golden_total_feb_mar_pct']:+.1f}% (raw settled-payment sum: {D['claim_reported_style_feb_mar_pct']:+.1f}%) but March has 31 days vs 28 ({D['calendar_days_effect_pct']:+.1f}%). Per day: {D['golden_per_day_feb_mar_pct']:+.1f}% (95% CI {D['per_day_ci95_pct'][0]:+.1f}% to {D['per_day_ci95_pct'][1]:+.1f}%) — no improvement detectable.</span></div>
<div class="g">
<div class="c"><h2>Net recovery by month (₹ Cr) and per-day rate</h2>{chart}<div class="leg"><i style="background:var(--bar)"></i>total ₹ Cr<i style="background:var(--red)"></i>March<i style="background:var(--amb)"></i>per-day ₹ (scaled, flat)</div></div>
<div class="c"><h2>Reported-style total → golden net (₹ Cr, Jan–Aug 8)</h2>{"".join(wrows)}
<div class="leg" style="margin-top:4px">Duplicates inflate Jan–Jul recovery by {D['duplicate_inflation_pct']:.1f}% (₹{D['duplicate_inflation_cr']:.1f} Cr). {D['attribution_7d_pct']:.1f}% of payments follow a touch within 7 days — chance level is {D['attribution_7d_placebo_pct']:.1f}%.</div></div>
<div class="c"><h2>Operating KPIs — July vs June (golden definitions)</h2><div class="k">{kp}</div>
<div class="leg" style="margin-top:4px">Status “KEPT” is not corroborated by payments. Recovery per agent-hour ₹{k['recovery_per_agent_hour_inr'][0]:,} ({k['recovery_per_agent_hour_inr'][1]:+,} vs Jun).</div></div>
<div class="c rec"><h2>Decision: ₹10 Cr</h2>
<p><b>Better borrower targeting — released in tranches behind a randomised holdout.</b></p>
<p>Why: {D['drivers_sig_fdr']} of {D['drivers_tested']} driver tests survive FDR correction; extra calls, WhatsApp, field visits show no response; no AI-voice or cost data exists.</p>
<p>Break-even needs <b>+{D['break_even_uplift_pct']:.1f}%</b> recovery on a ₹{D['annual_run_rate_cr']:.0f} Cr/yr run-rate. A 20% holdout for 3 months detects ≥{D['mde_20pct_holdout_3m_pct']:.1f}%. Expected uplift today: <span class="pill">not estimable</span> · downside: tranche 1 only.</p></div>
</div></body></html>"""
    (REPORTS_DIR / "dashboard.html").write_text(html_doc)
    return html_doc


def build_dashboard_png(D):
    fig = plt.figure(figsize=(14, 7.6), dpi=130)
    fig.patch.set_facecolor("#f6f7f9")
    fig.text(0.02, 0.965, "Collections recovery: is “+11% month-on-month” real?", fontsize=16, weight="bold", color="#17202e")
    fig.patches.append(plt.Rectangle((0.015, 0.84), 0.97, 0.095, transform=fig.transFigure, color=RED))
    fig.text(0.025, 0.905, "NOT SUPPORTED — the 11% is a calendar effect (28 vs 31 days)", color="w", fontsize=14, weight="bold", va="center")
    fig.text(0.025, 0.862, f"Feb→Mar total {D['golden_total_feb_mar_pct']:+.1f}% (raw settled sum {D['claim_reported_style_feb_mar_pct']:+.1f}%), calendar {D['calendar_days_effect_pct']:+.1f}%; per day "
             f"{D['golden_per_day_feb_mar_pct']:+.1f}% (95% CI {D['per_day_ci95_pct'][0]:+.1f}% to {D['per_day_ci95_pct'][1]:+.1f}%)", color="w", fontsize=10.5, va="center")
    gs = fig.add_gridspec(2, 2, left=0.05, right=0.98, top=0.78, bottom=0.04, hspace=0.38, wspace=0.42)
    ax = fig.add_subplot(gs[0, 0]); mo = [x[5:] for x in D["months"]]
    nm = {"01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "May", "06": "Jun", "07": "Jul"}
    cols = [RED if m == "03" else NAVY for m in mo]
    ax.bar([nm[m] for m in mo], D["net_cr"], color=cols)
    for i, v in enumerate(D["net_cr"]): ax.text(i, v + 0.4, f"{v:.1f}", ha="center", fontsize=8)
    ax.set_title("Net recovery by month (₹ Cr)  — bars; amber = per-day rate (₹ lakh/day)", fontsize=9.5, loc="left"); ax.set_ylim(0, max(D["net_cr"]) * 1.25)
    a2 = ax.twinx(); a2.plot(range(7), D["per_day_lakh"], color=AMBER, marker="o"); a2.set_ylim(0, max(D["per_day_lakh"]) * 1.4); a2.set_yticks([])
    for s in ("top",): ax.spines[s].set_visible(False); a2.spines[s].set_visible(False)
    ax = fig.add_subplot(gs[0, 1]); wf = D["waterfall"]
    labels = ["Raw payments", "− duplicates", "− not settled", "− out of window", "− current accts", "= Golden net"]
    vals = [abs(w["inr_cr"]) for w in wf]; ax.barh(labels[::-1], vals[::-1], color=[NAVY if i in (0, 5) else RED for i in range(6)][::-1])
    for i, v in enumerate(vals[::-1]): ax.text(v + 2, i, f"{v:,.1f}", va="center", fontsize=8)
    ax.set_title("Reported-style total → golden net (₹ Cr)", fontsize=9.5, loc="left"); ax.set_xlim(0, max(vals) * 1.18)
    ax.spines[["top", "right"]].set_visible(False)
    ax = fig.add_subplot(gs[1, 0]); ax.axis("off"); k = D["kpi"]
    items = [("Contact rate (accts)", f"{k['contact_rate_account_pct'][0]}%", k['contact_rate_account_pct'][1], "contact_rate_account_pct"), ("Right-party contact", f"{k['rpc_rate_pct'][0]}%", k['rpc_rate_pct'][1], "rpc_rate_pct"),
             ("PTP rate", f"{k['ptp_rate_pct'][0]}%", k['ptp_rate_pct'][1], "ptp_rate_pct"), ("PTP kept (status)", f"{k['ptp_kept_resolved_pct'][0]}%", k['ptp_kept_resolved_pct'][1], "ptp_kept_resolved_pct"),
             ("PTP kept (payment-verified)", f"{k['ptp_payment_verified_pct'][0]}%", k['ptp_payment_verified_pct'][1], "ptp_payment_verified_pct"), ("Recovery rate (% outstanding)", f"{k['recovery_rate_pct'][0]}%", k['recovery_rate_pct'][1], "recovery_rate_pct")]
    ax.set_title("Operating KPIs, July vs June (and Jan–Jul trend p-value)", fontsize=9.5, loc="left")
    for i, (l, v, d, key) in enumerate(items):
        x, y = 0.02 + (i % 3) * 0.33, 0.62 - (i // 3) * 0.45
        ax.text(x, y + 0.18, l, fontsize=8.5, color="#667085", transform=ax.transAxes); ax.text(x, y, v, fontsize=17, weight="bold", transform=ax.transAxes)
        ax.text(x, y - 0.14, f"{d:+.2f} pp vs Jun · trend p={D['trend_p'][key]:.2f}", fontsize=8, color="#667085", transform=ax.transAxes)
    ax = fig.add_subplot(gs[1, 1]); ax.axis("off")
    ax.set_title("Decision: ₹10 Cr", fontsize=9.5, loc="left")
    txt = (f"Better borrower targeting, released in tranches\nbehind a randomised holdout.\n\n"
           f"• {D['drivers_sig_fdr']}/{D['drivers_tested']} driver tests survive FDR; more calls, WhatsApp, field visits show no response\n"
           f"• Break-even needs +{D['break_even_uplift_pct']:.1f}% on a ₹{D['annual_run_rate_cr']:.0f} Cr/yr run-rate\n"
           f"• 20% holdout × 3 months detects ≥{D['mde_20pct_holdout_3m_pct']:.1f}%\n• Expected uplift: not reliably estimable; downside = tranche 1")
    ax.text(0.0, 0.95, txt, va="top", fontsize=10, transform=ax.transAxes, linespacing=1.5)
    fig.savefig(REPORTS_DIR / "dashboard.png", facecolor=fig.get_facecolor()); plt.close(fig)


def build_architecture():
    dot = r'''digraph G { rankdir=LR; fontname="Helvetica"; node [fontname="Helvetica", fontsize=11, shape=box, style="rounded,filled", fillcolor="#eef2f8", color="#3b5b88"]; edge [color="#667085"];
 subgraph cluster_src { label="Source systems"; style=dashed; color="#aaaabb"; dialer[label="Dialer / telephony\n(calls, attempts, dispositions)"]; msg[label="WhatsApp / SMS\nproviders"]; field[label="Field app"]; lms[label="LMS: accounts,\nborrowers, status history"]; pay[label="Payment gateway"]; crm[label="Agent HRMS / sessions"]; }
 raw[label="RAW\nimmutable files + SHA-256\nappend-only, partition by load_date", fillcolor="#fdecea"];
 stg[label="STAGING\ntyped, trimmed IDs\ntz -> UTC/IST, row lineage"];
 cln[label="CLEAN\ndedup + supersession\nREJECTS table (reason codes)"];
 gold[label="GOLDEN\ndim_* / fact_*\nPK/FK enforced, account_id spine", fillcolor="#e6f4ea"];
 feat[label="FEATURE\naccount x month panel\nattribution, as-of status"];
 met[label="METRICS\nversioned definitions\nmetrics_monthly (+ per-day)"];
 dash[label="DASHBOARD\none-screen exec view\n+ drill-down", fillcolor="#fff4e0"];
 dq[label="DATA-QUALITY GATES\ncontracts, row conservation,\nrecon of ₹, freshness", shape=hexagon, fillcolor="#ffffff"];
 mon[label="MONITORING\nanomaly detection on per-day\nmetrics, DQ trend, alerts", shape=hexagon, fillcolor="#ffffff"];
 exp[label="EXPERIMENT SERVICE\nrandomised holdouts\n(targeting pilots)", fillcolor="#fff4e0"];
 dialer->raw; msg->raw; field->raw; lms->raw; pay->raw; crm->raw;
 raw->stg->cln->gold->feat->met->dash;
 dq->cln [style=dashed, label="block on fail"]; dq->gold [style=dashed]; dq->met [style=dashed];
 met->mon; exp->feat [label="treatment flag"]; gold->exp; }'''
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "architecture.dot").write_text(dot)
    try:
        subprocess.run(["dot", "-Tpng", "-Gdpi=130", str(ROOT / "docs/architecture.dot"), "-o", str(REPORTS_DIR / "architecture.png")], check=True)
        subprocess.run(["dot", "-Tsvg", str(ROOT / "docs/architecture.dot"), "-o", str(REPORTS_DIR / "architecture.svg")], check=True)
    except Exception as e:
        print("graphviz not available:", e)


def build_figures(R):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    m = R["monthly"].loc[A.FULL_MONTHS]
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.6))
    ax[0].bar(range(7), m.net_inr / CR, color=NAVY); ax[0].set_xticks(range(7)); ax[0].set_xticklabels([x[5:] for x in m.index]); ax[0].set_title("Total net recovery (₹ Cr)")
    ax[1].bar(range(7), m.net_inr_per_day / 1e5, color=AMBER); ax[1].set_xticks(range(7)); ax[1].set_xticklabels([x[5:] for x in m.index]); ax[1].set_title("Net recovery per observed day (₹ lakh)")
    for a in ax: a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(FIG_DIR / "claim_total_vs_per_day.png", dpi=120); plt.close(fig)
    w = R["B_window"]
    fig, ax = plt.subplots(figsize=(6, 3.6)); x = np.arange(len(w))
    ax.bar(x - 0.2, w.attributed_pct_of_payments, 0.4, label="observed", color=NAVY); ax.bar(x + 0.2, w.placebo_attributed_pct_mean, 0.4, yerr=1.96 * w.placebo_sd, label="placebo (random dates)", color=GREY)
    ax.set_xticks(x); ax.set_xticklabels([f"{d}d" for d in w.index]); ax.set_title("% of payments with a touch in prior N days"); ax.legend(); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(FIG_DIR / "attribution_vs_placebo.png", dpi=120); plt.close(fig)
    d = R["drivers"].copy(); d["label"] = d.dimension.str.slice(0, 28) + " | " + d.outcome
    d = d.sort_values("p")
    fig, ax = plt.subplots(figsize=(7, 5)); ax.scatter(np.arange(len(d)), d.p, color=NAVY, label="raw p")
    ax.plot(np.arange(len(d)), 0.05 * (np.arange(len(d)) + 1) / len(d), color=RED, label="BH threshold (q=0.05)"); ax.set_xlabel("tests ranked by p"); ax.set_ylabel("p-value")
    ax.set_title("29 driver tests: nothing beats the FDR line"); ax.legend(); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(FIG_DIR / "drivers_pvalues.png", dpi=120); plt.close(fig)


def main():
    import pickle
    R = A.run_all()
    REPORTS_DIR.mkdir(exist_ok=True)
    D = dashboard_data(R)
    (REPORTS_DIR / "dashboard_data.json").write_text(json.dumps(D, indent=2, default=float))
    build_dashboard_html(D); build_dashboard_png(D); build_architecture(); build_figures(R)
    for name in ["claim", "stepwise", "waterfall", "drivers", "dose", "channel", "reported_vs_real", "tgt_scan", "grid", "volatility"]:
        R[name].to_csv(REPORTS_DIR / f"result_{name}.csv")
    R["B_window"].to_csv(REPORTS_DIR / "result_attribution_window.csv"); R["C"]["payment_tz_sensitivity"].to_csv(REPORTS_DIR / "result_tz_sensitivity.csv")
    R["invest"]["scenarios"].to_csv(REPORTS_DIR / "result_investment_scenarios.csv", index=False); R["experiment"]["table"].to_csv(REPORTS_DIR / "result_experiment_power.csv", index=False)
    R["G"]["table"].to_csv(REPORTS_DIR / "result_denominator.csv"); R["trends"].to_csv(REPORTS_DIR / "result_kpi_trends.csv")
    pickle.dump(R, open(REPORTS_DIR / ".results.pkl", "wb"))
    print("reports built")
    return R, D


if __name__ == "__main__":
    main()
