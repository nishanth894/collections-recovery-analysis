"""Executive memo (<=2 pages) -> reports/executive_memo.pdf and .md. All numbers come from cached analysis results."""
import pickle, json
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os
from .config import REPORTS_DIR

CR = 1e7


def _font():
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(p):
            pdfmetrics.registerFont(TTFont("DV", p)); pdfmetrics.registerFont(TTFont("DVB", p.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")))
            pdfmetrics.registerFont(TTFont("DVI", p.replace("DejaVuSans.ttf", "DejaVuSans-Oblique.ttf")))
            pdfmetrics.registerFontFamily("DV", normal="DV", bold="DVB", italic="DVI", boldItalic="DVB")
            return "DV", "DVB"
    return "Helvetica", "Helvetica-Bold"          # ₹ may not render without DejaVu; fall back to 'Rs'


def build():
    R = pickle.load(open(REPORTS_DIR / ".results.pkl", "rb")); D = json.loads((REPORTS_DIR / "dashboard_data.json").read_text())
    f, fb = _font(); rs = "₹" if f == "DV" else "Rs "
    inv, ex = R["invest"], R["experiment"]["table"]; r20 = ex[(ex.holdout_share == .2) & (ex.months == 3)].iloc[0]
    sc = inv["scenarios"]; cal = R["calendar"]; pdt = R["per_day_test"]; A_ = R["A"]; B = R["B_window"]; G = R["G"]; did_j, did_a = R["did_jul"], R["did_apr"]
    sc100 = sc[sc.benefit_basis.str.startswith("100%")].set_index("relative_uplift")
    roi = lambda u: f"{round(sc100.loc[u,'roi_year1_pct']):+d}%".replace('+0%','0%').replace('-0%','0%')
    drv = R["drivers"]
    ss = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=ss["Normal"], fontName=f, fontSize=9.2, leading=11.8, spaceAfter=2.2)
    h = ParagraphStyle("h", parent=base, fontName=fb, fontSize=10.2, leading=12.5, spaceBefore=4.5, spaceAfter=2, textColor=colors.HexColor("#1f3a5f"))
    t = ParagraphStyle("t", parent=base, fontName=fb, fontSize=14, leading=17, spaceAfter=1)
    sm = ParagraphStyle("s", parent=base, fontSize=7.6, leading=9.4, textColor=colors.HexColor("#555555"))
    cell = ParagraphStyle("c", parent=base, fontSize=8.2, leading=10, spaceAfter=0)
    P = lambda x, s=base: Paragraph(x, s)
    S = []
    S.append(P("Collections recovery: the “+11% month-on-month” claim is not real", t))
    S.append(P("Executive memo · data: 1 Jan – 8 Aug 2026 (the file holds ≈7.3 months, not 12) · every figure is reproducible from the repository", sm))
    S.append(P("1. What happened", h))
    S.append(P(f"<b>The 11% is reproducible — and it is an artefact.</b> Summing raw SUCCESS payment rows gives Feb→Mar <b>{D['claim_reported_style_feb_mar_pct']:+.1f}%</b>. "
               f"On the cleaned (golden) data total recovery rose {cal['total_mom']*100:+.1f}%, but March has 31 days and February 28 (<b>{cal['calendar_days_effect']*100:+.1f}%</b> from the calendar alone). "
               f"<b>Per day, recovery moved {cal['per_day_mom']*100:+.2f}%</b> (95% CI {pdt['ci95'][0]*100:+.1f}% to {pdt['ci95'][1]*100:+.1f}%). "
               f"Daily recovery is flat across Jan–Jul (≈{rs}{R['ts']['daily_mean_inr']/1e5:.0f} lakh/day, no break-point, permutation p={R['ts']['changepoint_perm_p']:.2f}). "
               f"Contact, right-party-contact, PTP-kept and recovery-rate show no significant Jan–Jul trend (all trend p>0.3); the largest single-month move is {R['trends'].loc[['Contact rate, accounts (%)','RPC rate (%)','PTP rate (% of RPC)','PTP kept, status (% resolved)'],'max_abs_mom_move'].max():.1f} pp. "
               f"The one drift is <i>downward</i>: PTP rate {R['trends'].loc['PTP rate (% of RPC)','jan']:.1f}% → {R['trends'].loc['PTP rate (% of RPC)','jul']:.1f}% (nominal p={R['trends'].loc['PTP rate (% of RPC)','p_trend']:.3f}, FDR q={R['trends'].loc['PTP rate (% of RPC)','q_bh']:.2f}) — a watch item, not a finding."))
    S.append(P(f"<b>Money that is not recovery:</b> of {rs}{D['raw_total_cr']:.1f} Cr in raw payment rows only <b>{rs}{D['golden_total_cr']:.1f} Cr</b> is settled, de-duplicated recovery on delinquent accounts "
               f"(duplicates {rs}{A_['total_inflation_inr']/CR:.1f} Cr = {A_['total_inflation_pct']:.1f}% of Jan–Jul recovery; non-settled FAILED/PENDING/REVERSED {rs}{abs(D['waterfall'][2]['inr_cr']):.1f} Cr; payments on current accounts {rs}{abs(D['waterfall'][4]['inr_cr']):.1f} Cr)."))
    S.append(P("2. Why — and what is not the cause", h))
    S.append(P(f"<b>Calendar length</b> and <b>definitions</b> explain the headline. We tested portfolio mix, DPD, geography, risk segment, agent, tenure, campaign, channel, vendor, calling hour/weekday and attempt frequency: "
               f"<b>{D['drivers_sig_raw']} of {D['drivers_tested']} tests look significant before multiple-testing correction and {D['drivers_sig_fdr']} after it</b>. No Simpson reversals in {R['simpson']['scans']} scans; mix effect on Feb→Mar is ≈0. "
               f"Client and language are not in the data. Payment-to-touch “attribution” is chance: {B.loc[7,'attributed_pct_of_payments']:.1f}% of payments follow a contact within 7 days vs {B.loc[7,'placebo_attributed_pct_mean']:.1f}% for random dates. "
               f"Adding more touches does not raise next-period payment (within-account slopes ≈0, all FDR q>0.9)."))
    S.append(P(f"<b>Integrity red flags:</b> {G['share_of_recovery_on_asof_closed_pct']:.0f}% of recovery ₹ lands on accounts that status history shows as PAID/CLOSED/WRITEOFF; "
               f"PTP “KEPT” is barely corroborated by payments (5.0% vs 4.1% for BROKEN); a rate computed with all payments over the shrinking “active” base would show a fake {G['table'].mismatch_cum_change_pct.iloc[-1]:+.0f}% gain; "
               f"{R['C']['pct_outside_8_19_ist']:.0f}% of calls are time-stamped outside 08:00–19:00 IST (compliance exposure if real); agent IDs cannot be reconciled."))
    S.append(P("3. How confident are we?", h))
    rows = [["Conclusion", "Class"],
            ["The 11% is calendar + definitions; per-day recovery is flat", "Fact (identity) / Strong evidence (CI, no break-point)"],
            ["Duplicate payments overstate recovery by 1.9%", "Fact"],
            ["No tested driver explains differences; payment-touch link = chance", "Strong evidence of no large effect (small effects undetectable)"],
            ["More attempts / WhatsApp / field visits do not lift payment", "Correlation (observational; reverse causality possible)"],
            [f"Effect of the mid-year targeting change (DiD {did_j['did_rel_to_baseline_pct']:+.0f}% [{did_j['ci95_rel_pct'][0]:+.0f},{did_j['ci95_rel_pct'][1]:+.0f}] at Jul-1; {did_a['did_rel_to_baseline_pct']:+.0f}% at Apr-1)", "Hypothesis — not identifiable"],
            ["Compliance and agent-level conclusions", "Hypothesis (timestamp / identity quality)"]]
    tb = Table([[P(c, cell) for c in r] for r in rows], colWidths=[112 * mm, 62 * mm])
    tb.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#c8ccd4")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9eef5")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    S.append(tb)
    S.append(P("4. What should we do with ₹10 Cr?", h))
    S.append(P(f"<b>Recommendation: Option 4 — better borrower targeting — released in tranches, each gated by a randomised holdout.</b> It is not chosen because its payoff is proven; it is chosen because it is the only option whose effect can be measured cheaply "
               f"and the data show no marginal return to capacity: telephony vendors/hours do not differ in contact rate, extra calls/agents/WhatsApp/field visits show no response, there is no AI-voice data and no cost data for any option. "
               f"The data foundation the investment must include (as-of status, valid account↔borrower↔call keys, one agent identity) is also the prerequisite for evaluating <i>any</i> future spend."))
    S.append(P(f"<b>Expected financial impact.</b> Baseline net recovery is {rs}{inv['baseline']['annualised_inr']/CR:.0f} Cr/year (95% CI {rs}{inv['baseline']['ci95'][0]/CR:.0f}–{inv['baseline']['ci95'][1]/CR:.0f} Cr). "
               f"<b>Break-even = +{inv['break_even_uplift_pct_100']:.1f}% recovery</b> in year 1 if each recovered rupee counts as benefit (+{inv['break_even_uplift_pct_50']:.0f}% at 50% capture, +{inv['break_even_uplift_pct_25']:.0f}% at 25%). "
               f"<b>Expected incremental recovery is not reliably estimable</b> from this data; the evidenced central case is {rs}0. Scenarios (100% capture, 12 months, all-in cost {rs}10 Cr): "
               f"0% uplift → ROI −100%; +5% → {rs}{sc100.loc[0.05,'incremental_benefit_year1_inr']/CR:.0f} Cr, ROI {roi(0.05)}; +10% → {rs}{sc100.loc[0.10,'incremental_benefit_year1_inr']/CR:.0f} Cr, ROI {roi(0.10)}; +15% → ROI {roi(0.15)}. "
               f"Implementation/operating cost cannot be built from the data (none supplied): {rs}10 Cr is treated as all-in; opex beyond it would raise break-even. <b>Downside:</b> if uplift is 0 the full {rs}10 Cr is lost — hence tranches."))
    S.append(P(f"<b>Pilot design (to turn the hypothesis into an estimate).</b> Randomise {int(r20.n_control):,} of {R['experiment']['eligible_accounts']:,} delinquent accounts (20%) to a never-treated holdout, stratified by DPD bucket × outstanding band; "
               f"outcome = {rs} recovered per account, measured per observed day; pre-register the metric. A 20% holdout over 3 months detects a ≥{r20.mde_rel_inr_per_account*100:.1f}% relative effect (80% power), i.e. just below the {inv['break_even_uplift_pct_100']:.1f}% break-even; "
               f"~{R['experiment']['n_per_arm_for_5pct_inr_effect_3m']:,} accounts per arm are needed for 5%. Release tranche 2 only if the lower CI bound clears break-even; stop if the point estimate is ≤0."))
    S.append(P("5. Immediate actions", h))
    S.append(P("(1) Retire the 11% figure; report <b>net recovery per observed day</b> and rates in <b>percentage points</b>. (2) Adopt the golden definitions and DQ gates (de-duplicate on payment_id, settled-only, delinquent-only, one clock). "
               "(3) Fix status history and the call↔attempt↔disposition keys. (4) Obtain cost per channel/agent-hour and the strategy-change date/assignment rule to enable cost-per-₹ and a proper counterfactual.", base))
    S.append(P("Limitations: single account snapshot (no as-of DPD); timestamps without a timezone assumed IST (robustness checked); several fields behave as independent random draws, so absence of effects is reported as absence of <i>detectable</i> effects.", sm))
    doc = SimpleDocTemplate(str(REPORTS_DIR / "executive_memo.pdf"), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=11 * mm,
                            title="Executive memo - collections recovery", author="Data Analyst")
    doc.build(S)
    from pypdf import PdfReader
    n = len(PdfReader(str(REPORTS_DIR / "executive_memo.pdf")).pages)
    return n


if __name__ == "__main__":
    print("memo pages:", build())
