-- Share of recovery payments that have >=1 contact touch in the preceding N days (compare with placebo in Python).
SELECT w.n_days,
       ROUND(100.0*COUNT(DISTINCT CASE WHEN t.account_id IS NOT NULL THEN p.payment_id END)/COUNT(DISTINCT p.payment_id),2) AS pct_payments_with_touch
FROM (SELECT 1 n_days UNION ALL SELECT 3 UNION ALL SELECT 7 UNION ALL SELECT 14 UNION ALL SELECT 30) w
CROSS JOIN fact_payment p
LEFT JOIN fact_touch t ON t.account_id=p.account_id AND t.touch_ts_utc<=p.event_ts_utc
                      AND t.touch_ts_utc>=datetime(p.event_ts_utc,'-'||w.n_days||' days')
WHERE p.is_recovery=1 GROUP BY w.n_days ORDER BY w.n_days;
