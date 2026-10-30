-- =====================================================================
-- LAYER 3: GOLDEN  (conformed dimensions + facts; the only layer analysts/dashboards read)
-- Join key policy: account_id is the ONLY trusted foreign key (100% referential integrity).
--   borrower_id on event tables disagrees with accounts.borrower_id in >99.9% of rows -> not used.
--   call_id links calls<->attempts<->dispositions disagree on account in >99.99% of rows -> not used.
-- =====================================================================
DROP TABLE IF EXISTS dim_month;
CREATE TABLE dim_month (report_month TEXT PRIMARY KEY, month_start TEXT, days_observed INTEGER, days_in_month INTEGER, is_partial INTEGER);
INSERT INTO dim_month VALUES
 ('2026-01','2026-01-01 00:00:00',31,31,0),('2026-02','2026-02-01 00:00:00',28,28,0),
 ('2026-03','2026-03-01 00:00:00',31,31,0),('2026-04','2026-04-01 00:00:00',30,30,0),
 ('2026-05','2026-05-01 00:00:00',31,31,0),('2026-06','2026-06-01 00:00:00',30,30,0),
 ('2026-07','2026-07-01 00:00:00',31,31,0),('2026-08','2026-08-01 00:00:00',8,31,1);

DROP TABLE IF EXISTS dim_vendor;
CREATE TABLE dim_vendor AS SELECT vendor_id, vendor_name, vendor_account_id, vendor_tz, vendor_status, schema_version FROM stg_vendors
UNION ALL SELECT 'UNKNOWN','UNKNOWN',NULL,NULL,'UNKNOWN',NULL;

DROP TABLE IF EXISTS dim_campaign;
CREATE TABLE dim_campaign AS
SELECT campaign_id, campaign_name, channel AS campaign_channel, strategy_version, target_definition, start_at, end_at,
       -- 'modern' strategy = v2/v3 ; 'old' = legacy/v1  (used only in the counterfactual DiD, see analysis s7)
       CASE WHEN strategy_version IN ('v2','v3') THEN 1 ELSE 0 END AS is_new_strategy
FROM stg_campaigns;

DROP TABLE IF EXISTS dim_agent;
CREATE TABLE dim_agent AS
SELECT a.agent_id, a.vendor_id, a.team, a.status, a.joined_at_earliest, a.joined_at_latest, a.n_snapshots, a.n_employee_codes,
       CAST((julianday(a.joined_at_latest)-julianday(a.joined_at_earliest)) AS INTEGER) AS joined_at_spread_days
FROM clean_agents a
UNION ALL SELECT 'UNKNOWN',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL;

DROP TABLE IF EXISTS dim_account;
CREATE TABLE dim_account AS
SELECT a.account_id, a.borrower_id, a.loan_type, a.principal_amount, a.outstanding_amount, a.dpd, a.dpd_bucket,
       a.risk_segment, a.status AS status_snapshot, a.opened_at,
       substr(a.opened_at,1,4)||'-Q'||((CAST(substr(a.opened_at,6,2) AS INTEGER)+2)/3) AS opened_cohort,
       a.account_tz,
       COALESCE(b.state,'UNKNOWN') AS state, COALESCE(b.city,'UNKNOWN') AS city,
       CASE WHEN a.borrower_id IS NULL THEN 'NO_BORROWER_ID'
            WHEN b.borrower_id IS NULL THEN 'BORROWER_NOT_FOUND' ELSE 'MATCHED' END AS borrower_link_status,
       CASE WHEN a.outstanding_amount<175000 THEN '1: <1.75L' WHEN a.outstanding_amount<350000 THEN '2: 1.75-3.5L'
            WHEN a.outstanding_amount<525000 THEN '3: 3.5-5.25L' ELSE '4: >5.25L' END AS outstanding_band,
       CASE WHEN a.dpd>=1 THEN 1 ELSE 0 END AS is_collectible      -- dpd=0 accounts are not delinquent -> payments are not 'recovery'
FROM stg_accounts a LEFT JOIN clean_borrowers b ON b.borrower_id=a.borrower_id;
CREATE UNIQUE INDEX ux_dim_account ON dim_account(account_id);

-- ---------------- facts ----------------
DROP TABLE IF EXISTS fact_payment;
CREATE TABLE fact_payment AS
SELECT p.payment_id, p.account_id, p.payment_reference, p.amount, p.payment_status, p.payment_method, p.provider_id,
       p.event_ts_utc, p.event_ts_ist, p.report_month, p.report_date, p.in_window, p.ref_missing_flag, p.ref_collision_flag,
       d.dpd, d.dpd_bucket, d.loan_type, d.risk_segment, d.state, d.outstanding_band, d.status_snapshot, d.is_collectible,
       CASE WHEN p.amount>d.outstanding_amount THEN 1 ELSE 0 END AS overpayment_flag,
       CASE WHEN p.payment_status='SUCCESS' THEN 1 ELSE 0 END AS is_success,
       -- THE recovery flag: settled, in observation window, on a delinquent account
       CASE WHEN p.payment_status='SUCCESS' AND p.in_window=1 AND d.is_collectible=1 THEN 1 ELSE 0 END AS is_recovery
FROM clean_payments p JOIN dim_account d ON d.account_id=p.account_id;
CREATE UNIQUE INDEX ux_fact_payment ON fact_payment(payment_id);
CREATE INDEX ix_fact_payment_acct ON fact_payment(account_id, event_ts_utc);

DROP TABLE IF EXISTS fact_call;
CREATE TABLE fact_call AS
SELECT c.call_id, c.account_id, c.agent_id, COALESCE(c.agent_id,'UNKNOWN') AS agent_key, c.campaign_id, c.direction, c.vendor_id,
       v.vendor_name, v.vendor_status, c.call_status, c.duration_sec, c.source_tz, c.event_ts_utc, c.event_ts_ist, c.report_month,
       c.report_date, c.hour_ist, c.dow, c.hour_naive, c.month_naive, c.is_answered, c.is_outbound, c.status_duration_conflict, c.in_window,
       cm.strategy_version, cm.campaign_channel, cm.is_new_strategy,
       CASE WHEN c.event_ts_ist BETWEEN cm.start_at AND cm.end_at THEN 1 ELSE 0 END AS within_campaign_window,
       CAST((julianday(c.event_ts_ist)-julianday(ag.joined_at_earliest))/30.4375 AS INTEGER) AS agent_tenure_months,
       d.dpd_bucket, d.loan_type, d.risk_segment, d.state, d.is_collectible
FROM clean_calls c
LEFT JOIN dim_vendor v ON v.vendor_id=c.vendor_id
LEFT JOIN dim_campaign cm ON cm.campaign_id=c.campaign_id
LEFT JOIN dim_agent ag ON ag.agent_id=c.agent_id
JOIN dim_account d ON d.account_id=c.account_id;
CREATE UNIQUE INDEX ux_fact_call ON fact_call(call_id);
CREATE INDEX ix_fact_call_acct ON fact_call(account_id, event_ts_utc);

DROP TABLE IF EXISTS fact_attempt;
CREATE TABLE fact_attempt AS
SELECT t.*, d.dpd_bucket, d.is_collectible FROM clean_attempts t JOIN dim_account d USING(account_id);
DROP TABLE IF EXISTS fact_disposition;
CREATE TABLE fact_disposition AS
SELECT t.*, d.dpd_bucket, d.is_collectible FROM clean_dispositions t JOIN dim_account d USING(account_id);

DROP TABLE IF EXISTS fact_ptp;
CREATE TABLE fact_ptp AS
SELECT t.ptp_id, t.account_id, t.agent_id, t.promised_amount, t.promised_ts_ist, t.ptp_status, t.source, t.event_ts_utc,
       t.event_ts_ist, t.report_month, d.dpd_bucket, d.is_collectible,
       CASE WHEN t.promised_ts_ist <= '2026-08-08 23:59:59' THEN 1 ELSE 0 END AS is_matured,
       -- payment-verified: a settled payment on the same account between PTP creation and promised date + 3d grace
       CASE WHEN EXISTS (SELECT 1 FROM clean_payments p WHERE p.account_id=t.account_id AND p.payment_status='SUCCESS'
              AND p.event_ts_ist>=t.event_ts_ist AND p.event_ts_ist<=datetime(t.promised_ts_ist,'+3 days')) THEN 1 ELSE 0 END AS payment_verified
FROM clean_ptp t JOIN dim_account d USING(account_id);

DROP TABLE IF EXISTS fact_message;
CREATE TABLE fact_message AS
SELECT event_id, account_id, channel, event_type, template_code, provider_id, event_ts_utc, event_ts_ist,
       substr(event_ts_ist,1,7) AS report_month FROM clean_whatsapp
UNION ALL
SELECT event_id, account_id, channel, event_type, template_code, provider_id, event_ts_utc, event_ts_ist,
       substr(event_ts_ist,1,7) FROM clean_sms;
CREATE INDEX ix_fact_message_acct ON fact_message(account_id, event_ts_utc);

DROP TABLE IF EXISTS fact_field_visit;
CREATE TABLE fact_field_visit AS SELECT f.*, d.dpd_bucket, d.is_collectible FROM clean_field_visits f JOIN dim_account d USING(account_id);
DROP TABLE IF EXISTS fact_session;
CREATE TABLE fact_session AS SELECT * FROM clean_sessions;
DROP TABLE IF EXISTS fact_targeting;
CREATE TABLE fact_targeting AS
SELECT t.*, cm.strategy_version, cm.is_new_strategy, cm.campaign_name, d.dpd_bucket, d.is_collectible, d.outstanding_amount
FROM clean_targeting t LEFT JOIN dim_campaign cm USING(campaign_id) JOIN dim_account d USING(account_id);
DROP TABLE IF EXISTS fact_complaint;
CREATE TABLE fact_complaint AS SELECT * FROM clean_complaints;

-- unified touch log (for attribution + intensity). CONTACT touches only:
--   answered outbound call | non-failed WhatsApp/SMS event | field visit
DROP TABLE IF EXISTS fact_touch;
CREATE TABLE fact_touch AS
SELECT account_id, 'VOICE' AS channel, event_ts_utc AS touch_ts_utc, report_month, agent_id, campaign_id, call_id AS touch_id
  FROM fact_call WHERE is_outbound=1 AND is_answered=1 AND in_window=1
UNION ALL SELECT account_id, channel, event_ts_utc, report_month, NULL, NULL, event_id
  FROM fact_message WHERE event_type<>'FAILED'
UNION ALL SELECT account_id, 'FIELD', event_ts_utc, report_month, agent_id, NULL, visit_id FROM fact_field_visit;
CREATE INDEX ix_fact_touch ON fact_touch(account_id, touch_ts_utc);
