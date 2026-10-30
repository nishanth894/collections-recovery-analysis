-- Which definition reproduces "+11% MoM"?  Raw vs golden, total vs per-day. Dialect: SQLite (LAG is ANSI).
WITH s AS (
  SELECT report_month, days_observed, rep_all_inr, rep_success_inr, succ_dedup_inr, net_inr, net_inr_per_day
  FROM metrics_monthly WHERE is_partial=0)
SELECT report_month,
  ROUND((rep_all_inr*1.0/LAG(rep_all_inr) OVER (ORDER BY report_month)-1)*100,2)      AS raw_all_status_mom_pct,
  ROUND((rep_success_inr*1.0/LAG(rep_success_inr) OVER (ORDER BY report_month)-1)*100,2) AS raw_success_mom_pct,
  ROUND((succ_dedup_inr*1.0/LAG(succ_dedup_inr) OVER (ORDER BY report_month)-1)*100,2) AS dedup_success_mom_pct,
  ROUND((net_inr*1.0/LAG(net_inr) OVER (ORDER BY report_month)-1)*100,2)              AS golden_total_mom_pct,
  ROUND((net_inr_per_day/LAG(net_inr_per_day) OVER (ORDER BY report_month)-1)*100,2)  AS golden_per_day_mom_pct
FROM s ORDER BY report_month;
