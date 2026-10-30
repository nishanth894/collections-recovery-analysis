-- =====================================================================
-- LAYER 4: FEATURE  (account x month panel, payment attribution, as-of eligibility)
-- =====================================================================

-- 4.1 Payment attribution: for each recovery payment, the touches in the preceding N days (default 7).
-- Three credit rules are stored so that rule choice can be audited (last / first / count in window).
DROP TABLE IF EXISTS ft_payment_attribution;
CREATE TABLE ft_payment_attribution AS
WITH cand AS (
  SELECT p.payment_id, p.amount, p.report_month, t.channel, t.touch_ts_utc, t.campaign_id, t.agent_id,
         ROW_NUMBER() OVER (PARTITION BY p.payment_id ORDER BY t.touch_ts_utc DESC) AS rn_last,
         ROW_NUMBER() OVER (PARTITION BY p.payment_id ORDER BY t.touch_ts_utc ASC)  AS rn_first,
         COUNT(*) OVER (PARTITION BY p.payment_id) AS n_touches
  FROM fact_payment p
  JOIN fact_touch t ON t.account_id=p.account_id AND t.touch_ts_utc<=p.event_ts_utc
                   AND t.touch_ts_utc>=datetime(p.event_ts_utc,'-7 days')
  WHERE p.is_recovery=1)
SELECT p.payment_id, p.amount, p.report_month,
       l.channel AS last_touch_channel, l.touch_ts_utc AS last_touch_ts, l.campaign_id AS last_touch_campaign, l.agent_id AS last_touch_agent,
       f.channel AS first_touch_channel, COALESCE(l.n_touches,0) AS n_touches,
       CASE WHEN l.payment_id IS NULL THEN 'UNATTRIBUTED' ELSE 'ATTRIBUTED' END AS attribution_status
FROM fact_payment p
LEFT JOIN cand l ON l.payment_id=p.payment_id AND l.rn_last=1
LEFT JOIN cand f ON f.payment_id=p.payment_id AND f.rn_first=1
WHERE p.is_recovery=1;

-- 4.2 As-of account status at each month start (from status history; event time, not recorded time)
DROP TABLE IF EXISTS ft_asof_status;
CREATE TABLE ft_asof_status AS
SELECT d.account_id, m.report_month,
       COALESCE((SELECT h.status FROM clean_status_history h WHERE h.account_id=d.account_id AND h.event_ts_ist<m.month_start
                 ORDER BY h.event_ts_ist DESC LIMIT 1),'NO_HISTORY') AS asof_status
FROM dim_account d CROSS JOIN dim_month m;
CREATE INDEX ix_asof ON ft_asof_status(report_month, account_id);

-- 4.3 Account x month panel (eligible accounts only)
DROP TABLE IF EXISTS ft_account_month;
CREATE TABLE ft_account_month AS
WITH calls AS (
  SELECT account_id, report_month, COUNT(*) AS outbound_calls, SUM(is_answered) AS answered_calls
  FROM fact_call WHERE is_outbound=1 AND in_window=1 GROUP BY 1,2),
msg AS (
  SELECT account_id, report_month, SUM(channel='WHATSAPP') AS wa_events, SUM(channel='SMS') AS sms_events FROM fact_message GROUP BY 1,2),
fv AS (SELECT account_id, report_month, COUNT(*) AS field_visits FROM fact_field_visit GROUP BY 1,2),
tg AS (SELECT account_id, report_month, COUNT(*) AS target_rows, MIN(priority) AS best_priority FROM fact_targeting GROUP BY 1,2),
pay AS (SELECT account_id, report_month, SUM(amount) AS recovered, COUNT(*) AS n_payments FROM fact_payment WHERE is_recovery=1 GROUP BY 1,2)
SELECT d.account_id, m.report_month, d.dpd_bucket, d.loan_type, d.risk_segment, d.state, d.outstanding_amount, d.outstanding_band, d.opened_cohort,
       COALESCE(c.outbound_calls,0) AS outbound_calls, COALESCE(c.answered_calls,0) AS answered_calls,
       COALESCE(g.wa_events,0) AS wa_events, COALESCE(g.sms_events,0) AS sms_events, COALESCE(f.field_visits,0) AS field_visits,
       COALESCE(t.target_rows,0) AS target_rows, t.best_priority,
       COALESCE(p.recovered,0) AS recovered, COALESCE(p.n_payments,0) AS n_payments,
       CASE WHEN COALESCE(c.outbound_calls,0)+COALESCE(g.wa_events,0)+COALESCE(g.sms_events,0)+COALESCE(f.field_visits,0)>0 THEN 1 ELSE 0 END AS is_worked,
       CASE WHEN COALESCE(t.target_rows,0)>0 THEN 1 ELSE 0 END AS is_targeted
FROM dim_account d CROSS JOIN dim_month m
LEFT JOIN calls c ON c.account_id=d.account_id AND c.report_month=m.report_month
LEFT JOIN msg g ON g.account_id=d.account_id AND g.report_month=m.report_month
LEFT JOIN fv f ON f.account_id=d.account_id AND f.report_month=m.report_month
LEFT JOIN tg t ON t.account_id=d.account_id AND t.report_month=m.report_month
LEFT JOIN pay p ON p.account_id=d.account_id AND p.report_month=m.report_month
WHERE d.is_collectible=1;
CREATE INDEX ix_ftam ON ft_account_month(report_month, account_id);
