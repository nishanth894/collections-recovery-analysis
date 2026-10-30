-- =====================================================================
-- LAYER 6: RECONCILIATION & VALIDATION (results are asserted in tests/test_pipeline.py)
-- =====================================================================
-- 6.1 Row conservation: raw = clean + rejected
DROP TABLE IF EXISTS recon_row_counts;
CREATE TABLE recon_row_counts AS
SELECT 'payments' AS tbl,(SELECT COUNT(*) FROM raw_payments) AS raw_rows,(SELECT COUNT(*) FROM clean_payments) AS clean_rows,(SELECT COUNT(*) FROM rejects WHERE src_table='payments') AS rejected_rows
UNION ALL SELECT 'calls',(SELECT COUNT(*) FROM raw_calls),(SELECT COUNT(*) FROM clean_calls),(SELECT COUNT(*) FROM rejects WHERE src_table='calls')
UNION ALL SELECT 'borrowers',(SELECT COUNT(*) FROM raw_borrowers),(SELECT COUNT(*) FROM clean_borrowers),(SELECT COUNT(*) FROM rejects WHERE src_table='borrowers')
UNION ALL SELECT 'agents',(SELECT COUNT(*) FROM raw_agents),(SELECT COUNT(*) FROM clean_agents),(SELECT COUNT(*) FROM rejects WHERE src_table='agents')
UNION ALL SELECT 'whatsapp_events',(SELECT COUNT(*) FROM raw_whatsapp_events),(SELECT COUNT(*) FROM clean_whatsapp),(SELECT COUNT(*) FROM rejects WHERE src_table='whatsapp_events')
UNION ALL SELECT 'accounts',(SELECT COUNT(*) FROM raw_accounts),(SELECT COUNT(*) FROM dim_account),0
UNION ALL SELECT 'call_attempts',(SELECT COUNT(*) FROM raw_call_attempts),(SELECT COUNT(*) FROM fact_attempt),0
UNION ALL SELECT 'call_dispositions',(SELECT COUNT(*) FROM raw_call_dispositions),(SELECT COUNT(*) FROM fact_disposition),0
UNION ALL SELECT 'sms_events',(SELECT COUNT(*) FROM raw_sms_events),(SELECT COUNT(*) FROM clean_sms),0
UNION ALL SELECT 'field_visits',(SELECT COUNT(*) FROM raw_field_visits),(SELECT COUNT(*) FROM fact_field_visit),0
UNION ALL SELECT 'promises_to_pay',(SELECT COUNT(*) FROM raw_promises_to_pay),(SELECT COUNT(*) FROM fact_ptp),0
UNION ALL SELECT 'complaints',(SELECT COUNT(*) FROM raw_complaints),(SELECT COUNT(*) FROM fact_complaint),0
UNION ALL SELECT 'account_status_history',(SELECT COUNT(*) FROM raw_account_status_history),(SELECT COUNT(*) FROM clean_status_history),0
UNION ALL SELECT 'agent_sessions',(SELECT COUNT(*) FROM raw_agent_sessions),(SELECT COUNT(*) FROM fact_session),0
UNION ALL SELECT 'daily_targeting',(SELECT COUNT(*) FROM raw_daily_targeting),(SELECT COUNT(*) FROM fact_targeting),0
UNION ALL SELECT 'campaigns',(SELECT COUNT(*) FROM raw_campaigns),(SELECT COUNT(*) FROM dim_campaign),0
UNION ALL SELECT 'vendor_telephony',(SELECT COUNT(*) FROM raw_vendor_telephony),(SELECT COUNT(*) FROM dim_vendor)-1,0;

-- 6.2 Recovery waterfall: raw reported-style total -> golden net recovery (every rupee accounted for)
DROP TABLE IF EXISTS recon_recovery_waterfall;
CREATE TABLE recon_recovery_waterfall (step INTEGER, step_name TEXT, delta_inr REAL, running_inr REAL, rows_affected INTEGER);
INSERT INTO recon_recovery_waterfall
SELECT 1,'Raw payments, all statuses, incl. duplicates', SUM(amount), SUM(amount), COUNT(*) FROM stg_payments;
INSERT INTO recon_recovery_waterfall
SELECT 2,'less: duplicate payment_id rows', -SUM(s.amount), 0, COUNT(*) FROM stg_payments s JOIN rejects r ON r.src_table='payments' AND r.raw_row_id=s.raw_row_id;
INSERT INTO recon_recovery_waterfall
SELECT 3,'less: FAILED / PENDING / REVERSED (not settled)', -SUM(amount), 0, COUNT(*) FROM fact_payment WHERE payment_status<>'SUCCESS';
INSERT INTO recon_recovery_waterfall
SELECT 4,'less: outside observation window', -COALESCE(SUM(amount),0), 0, COUNT(*) FROM fact_payment WHERE payment_status='SUCCESS' AND in_window=0;
INSERT INTO recon_recovery_waterfall
SELECT 5,'less: payments on current (dpd=0) accounts - not recovery', -SUM(amount), 0, COUNT(*) FROM fact_payment WHERE payment_status='SUCCESS' AND in_window=1 AND is_collectible=0;
INSERT INTO recon_recovery_waterfall
SELECT 6,'= Golden net recovery (is_recovery=1)', 0, SUM(amount), COUNT(*) FROM fact_payment WHERE is_recovery=1;
UPDATE recon_recovery_waterfall SET running_inr=(SELECT SUM(delta_inr) FROM recon_recovery_waterfall w2 WHERE w2.step<=recon_recovery_waterfall.step AND w2.step<=5)
  WHERE step BETWEEN 2 AND 5;

-- 6.3 Data-quality issue log (counts computed from data, not typed in)
DROP TABLE IF EXISTS dq_issue_log;
CREATE TABLE dq_issue_log (issue_id TEXT, area TEXT, issue TEXT, rows_affected INTEGER, base_rows INTEGER, treatment TEXT);
INSERT INTO dq_issue_log SELECT 'DQ-01','payments','Duplicate payment_id rows (ingestion retries)', COUNT(*), (SELECT COUNT(*) FROM raw_payments), 'Keep 1 row per payment_id; prefer row with payment_reference' FROM rejects WHERE src_table='payments';
INSERT INTO dq_issue_log SELECT 'DQ-02','payments','Rows sharing a payment_reference with a DIFFERENT payment (reference collision, NOT duplicate)', SUM(ref_collision_flag), COUNT(*), 'Kept; flagged ref_collision_flag' FROM clean_payments;
INSERT INTO dq_issue_log SELECT 'DQ-03','payments','Missing payment_reference', SUM(ref_missing_flag), COUNT(*), 'Kept; flagged' FROM clean_payments;
INSERT INTO dq_issue_log SELECT 'DQ-04','payments','Non-settled payments (FAILED/PENDING/REVERSED) that a raw sum would count', COUNT(*), (SELECT COUNT(*) FROM clean_payments), 'Excluded from recovery' FROM clean_payments WHERE payment_status<>'SUCCESS';
INSERT INTO dq_issue_log SELECT 'DQ-05','payments','SUCCESS payments on current (dpd=0) accounts', COUNT(*), (SELECT COUNT(*) FROM fact_payment WHERE is_success=1), 'Excluded from recovery (regular EMI, not recovery)' FROM fact_payment WHERE is_success=1 AND is_collectible=0;
INSERT INTO dq_issue_log SELECT 'DQ-06','payments','Payment amount exceeds account outstanding (overpayment)', SUM(overpayment_flag), COUNT(*), 'Kept; flagged (not capped)' FROM fact_payment WHERE is_recovery=1;
INSERT INTO dq_issue_log SELECT 'DQ-07','calls','Duplicate call_id rows', COUNT(*), (SELECT COUNT(*) FROM raw_calls), 'Dedup; earliest ts kept; non-null agent merged' FROM rejects WHERE src_table='calls';
INSERT INTO dq_issue_log SELECT 'DQ-08','calls','Calls with missing agent_id (after merge)', SUM(agent_id IS NULL), COUNT(*), 'agent_key=UNKNOWN; excluded from agent-level analysis only' FROM clean_calls;
INSERT INTO dq_issue_log SELECT 'DQ-09','calls','Calls outside observation window (late/future/early)', SUM(in_window=0), COUNT(*), 'Kept, flagged, excluded from monthly metrics' FROM clean_calls;
INSERT INTO dq_issue_log SELECT 'DQ-10','calls','Non-ANSWERED calls with duration>0 (status/duration conflict)', SUM(status_duration_conflict), COUNT(*), 'Status trusted; duration not used for contact definition' FROM clean_calls;
INSERT INTO dq_issue_log SELECT 'DQ-11','calls','Calls whose calendar MONTH changes when source timezone is honoured (vs. ignoring it)', SUM(month_naive<>report_month), COUNT(*), 'Converted via row timezone to UTC then IST' FROM clean_calls;
INSERT INTO dq_issue_log SELECT 'DQ-12','calls','Calls on telephony vendors flagged INACTIVE in vendor master', SUM(vendor_status='INACTIVE'), COUNT(*), 'Kept; vendor master status is a current snapshot, not as-of' FROM fact_call;
INSERT INTO dq_issue_log SELECT 'DQ-13','calls','Calls dated outside the lifetime of their campaign', SUM(within_campaign_window=0), COUNT(*), 'Campaign attribution on calls is unreliable; analysed by campaign_id only as a hypothesis' FROM fact_call;
INSERT INTO dq_issue_log SELECT 'DQ-14','borrowers','Superseded / duplicate borrower versions', COUNT(*), (SELECT COUNT(*) FROM raw_borrowers), 'Latest chronologically-valid version kept' FROM rejects WHERE src_table='borrowers';
INSERT INTO dq_issue_log SELECT 'DQ-15','borrowers','Kept borrower versions with updated_at < created_at', SUM(1-chronology_valid), COUNT(*), 'Flagged; geography low reliability' FROM clean_borrowers;
INSERT INTO dq_issue_log SELECT 'DQ-16','accounts','Accounts whose borrower_id is NULL or absent from borrowers', SUM(borrower_link_status<>'MATCHED'), COUNT(*), 'state=UNKNOWN' FROM dim_account;
INSERT INTO dq_issue_log SELECT 'DQ-17','agents','Agent snapshot rows superseded (1,000 agent_ids in 30,000 rows)', COUNT(*), (SELECT COUNT(*) FROM raw_agents), 'Latest snapshot for attributes; earliest joined_at for tenure' FROM rejects WHERE src_table='agents';
INSERT INTO dq_issue_log SELECT 'DQ-18','agents','Agents with >1 employee_code across snapshots', SUM(n_employee_codes>1), COUNT(*), 'agent_id retained as canonical key; employee_code unusable as crosswalk' FROM clean_agents;
INSERT INTO dq_issue_log SELECT 'DQ-19','whatsapp_events','Duplicate event ids', COUNT(*), (SELECT COUNT(*) FROM raw_whatsapp_events), 'Dedup' FROM rejects WHERE src_table='whatsapp_events';
INSERT INTO dq_issue_log SELECT 'DQ-20','dispositions','Rows using the alias code PROMISE_TO_PAY (same outcome as PTP)', SUM(disposition_code_raw='PROMISE_TO_PAY'), COUNT(*), 'Mapped to canonical PTP' FROM clean_dispositions;
INSERT INTO dq_issue_log SELECT 'DQ-21','field_visits','scheduled_at missing', SUM(schedule_missing_flag), COUNT(*), 'Flagged' FROM clean_field_visits;
INSERT INTO dq_issue_log SELECT 'DQ-22','attempts','vendor_id missing', SUM(vendor_id='UNKNOWN'), COUNT(*), 'vendor=UNKNOWN' FROM clean_attempts;
INSERT INTO dq_issue_log SELECT 'DQ-23','status_history','recorded_at earlier than event_at (back-dated / clock skew)', SUM(recorded_ts_ist<event_ts_ist), COUNT(*), 'Event time used for as-of status' FROM clean_status_history;
INSERT INTO dq_issue_log SELECT 'DQ-24','ptp','OPEN promises already past promised_date at data cut-off (stale)', SUM(ptp_status='OPEN' AND is_matured=1), COUNT(*), 'Reported separately; excluded from resolved kept-rate' FROM fact_ptp;
INSERT INTO dq_issue_log SELECT 'DQ-25','joins','Attempts whose account_id equals the parent call account_id (call_id FK validity)', SUM(a.account_id=c.account_id), COUNT(*), 'call_id link NOT trusted; tables analysed independently via account_id' FROM clean_attempts a JOIN clean_calls c ON c.call_id=a.call_id;
INSERT INTO dq_issue_log SELECT 'DQ-26','joins','Dispositions whose account_id equals the parent call account_id', SUM(d.account_id=c.account_id), COUNT(*), 'call_id link NOT trusted' FROM clean_dispositions d JOIN clean_calls c ON c.call_id=d.call_id;
INSERT INTO dq_issue_log SELECT 'DQ-27','joins','Calls whose borrower_id equals accounts.borrower_id', SUM(r.borrower_id_src=a.borrower_id), COUNT(*), 'borrower_id on events NOT trusted; account_id used' FROM stg_calls r JOIN stg_accounts a ON a.account_id=r.account_id;
