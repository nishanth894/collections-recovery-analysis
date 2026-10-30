-- Same numerator, four denominators -> how much of a "rate improvement" is just the denominator.
SELECT report_month,
       ROUND(recovery_rate_fixed_pct,3)                       AS rate_fixed_base_pct,
       ROUND(recovery_rate_worked_pct,3)                      AS rate_worked_accounts_pct,
       ROUND(recovery_rate_asof_eligible_pct,3)               AS rate_asof_eligible_consistent_pct,
       ROUND(rep_recovery_rate_mismatched_denominator_pct,3)  AS rate_MISMATCHED_numerator_all_denominator_eligible_pct,
       elig_n                                                 AS eligible_accounts_asof
FROM metrics_monthly WHERE is_partial=0 ORDER BY report_month;
