-- Account-level payment propensity by static dimension (collectible accounts, full window). Inputs for the chi-square tests in src/analysis.py
SELECT 'dpd_bucket' AS dimension, d.dpd_bucket AS level, COUNT(*) AS accounts,
       SUM(CASE WHEN p.account_id IS NOT NULL THEN 1 ELSE 0 END) AS paying_accounts,
       ROUND(100.0*SUM(CASE WHEN p.account_id IS NOT NULL THEN 1 ELSE 0 END)/COUNT(*),2) AS paid_rate_pct,
       ROUND(AVG(COALESCE(p.rec,0)),0) AS avg_recovery_inr
FROM dim_account d LEFT JOIN (SELECT account_id, SUM(amount) rec FROM fact_payment WHERE is_recovery=1 GROUP BY 1) p USING(account_id)
WHERE d.is_collectible=1 GROUP BY d.dpd_bucket
UNION ALL
SELECT 'loan_type', d.loan_type, COUNT(*), SUM(p.account_id IS NOT NULL), ROUND(100.0*SUM(p.account_id IS NOT NULL)/COUNT(*),2), ROUND(AVG(COALESCE(p.rec,0)),0)
FROM dim_account d LEFT JOIN (SELECT account_id, SUM(amount) rec FROM fact_payment WHERE is_recovery=1 GROUP BY 1) p USING(account_id)
WHERE d.is_collectible=1 GROUP BY d.loan_type
UNION ALL
SELECT 'risk_segment', d.risk_segment, COUNT(*), SUM(p.account_id IS NOT NULL), ROUND(100.0*SUM(p.account_id IS NOT NULL)/COUNT(*),2), ROUND(AVG(COALESCE(p.rec,0)),0)
FROM dim_account d LEFT JOIN (SELECT account_id, SUM(amount) rec FROM fact_payment WHERE is_recovery=1 GROUP BY 1) p USING(account_id)
WHERE d.is_collectible=1 GROUP BY d.risk_segment
UNION ALL
SELECT 'state', d.state, COUNT(*), SUM(p.account_id IS NOT NULL), ROUND(100.0*SUM(p.account_id IS NOT NULL)/COUNT(*),2), ROUND(AVG(COALESCE(p.rec,0)),0)
FROM dim_account d LEFT JOIN (SELECT account_id, SUM(amount) rec FROM fact_payment WHERE is_recovery=1 GROUP BY 1) p USING(account_id)
WHERE d.is_collectible=1 GROUP BY d.state
ORDER BY dimension, level;
