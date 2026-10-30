-- =====================================================================
-- LAYER 2: CLEAN  (dedup, supersession, canonical codes). Every dropped row is written to `rejects`
-- with a reason, so that   raw_rows = clean_rows + rejected_rows   holds for every table (tested).
-- =====================================================================
DROP TABLE IF EXISTS rejects;
CREATE TABLE rejects (src_table TEXT, raw_row_id INTEGER, business_key TEXT, reason TEXT);

-- ---------------- PAYMENTS: duplicate payment_id (ingestion retries) ---------------------
-- Rule: same payment_id => same event. Keep one row, prefer the one with a payment_reference.
-- NOT a duplicate: shared payment_reference across different payment_id/account/amount (reference collision).
DROP TABLE IF EXISTS _pay_rank;
CREATE TABLE _pay_rank AS
SELECT *, ROW_NUMBER() OVER (PARTITION BY payment_id ORDER BY (payment_reference IS NULL), raw_row_id) AS rn,
          COUNT(*) OVER (PARTITION BY payment_id) AS n_rows
FROM stg_payments;

CREATE INDEX ix_pr ON _pay_rank(payment_id, rn);
INSERT INTO rejects
SELECT 'payments', d.raw_row_id, d.payment_id,
       CASE WHEN d.payment_reference IS k.payment_reference AND d.amount=k.amount AND d.payment_status=k.payment_status
            THEN 'EXACT_DUPLICATE_PAYMENT_ID' ELSE 'DUPLICATE_PAYMENT_ID_REFERENCE_MISSING_VARIANT' END
FROM _pay_rank d JOIN _pay_rank k ON k.payment_id=d.payment_id AND k.rn=1
WHERE d.rn>1;

DROP TABLE IF EXISTS clean_payments;
CREATE TABLE clean_payments AS
SELECT payment_id, account_id, payment_reference, amount, payment_status, payment_method, provider_id,
       event_ts_utc, event_ts_ist, substr(event_ts_ist,1,7) AS report_month, substr(event_ts_ist,1,10) AS report_date,
       raw_row_id,
       CASE WHEN payment_reference IS NULL THEN 1 ELSE 0 END AS ref_missing_flag,
       CASE WHEN event_ts_ist BETWEEN '2026-01-01 00:00:00' AND '2026-08-08 23:59:59' THEN 1 ELSE 0 END AS in_window
FROM _pay_rank WHERE rn=1;
-- reference-collision flag (kept, NOT removed): reference reused by a different payment
ALTER TABLE clean_payments ADD COLUMN ref_collision_flag INTEGER DEFAULT 0;
CREATE INDEX ix_cp_ref ON clean_payments(payment_reference);
UPDATE clean_payments SET ref_collision_flag=1
 WHERE payment_reference IN (SELECT payment_reference FROM clean_payments WHERE payment_reference IS NOT NULL
                             GROUP BY payment_reference HAVING COUNT(*)>1);
CREATE INDEX ix_cp_acct ON clean_payments(account_id, event_ts_ist);

-- ---------------- CALLS: duplicate call_id (exact dups, null-agent re-ingests, late re-ingests) ---------
DROP TABLE IF EXISTS _call_rank;
CREATE TABLE _call_rank AS
SELECT *, ROW_NUMBER() OVER (PARTITION BY call_id ORDER BY event_ts_utc, (agent_id IS NULL), raw_row_id) AS rn,
          MAX(agent_id) OVER (PARTITION BY call_id) AS agent_id_resolved
FROM stg_calls;

CREATE INDEX ix_cr ON _call_rank(call_id, rn);
INSERT INTO rejects
SELECT 'calls', d.raw_row_id, d.call_id,
       CASE WHEN d.event_ts_utc=k.event_ts_utc AND d.agent_id IS k.agent_id AND d.call_status=k.call_status
                 AND d.duration_sec=k.duration_sec AND d.vendor_id=k.vendor_id AND d.campaign_id=k.campaign_id
            THEN 'EXACT_DUPLICATE_CALL_ID'
            WHEN d.event_ts_utc=k.event_ts_utc THEN 'AGENT_NULL_VARIANT_MERGED'
            ELSE 'LATE_REINGEST_TIMESTAMP_CONFLICT' END
FROM _call_rank d JOIN _call_rank k ON k.call_id=d.call_id AND k.rn=1 WHERE d.rn>1;

DROP TABLE IF EXISTS clean_calls;
CREATE TABLE clean_calls AS
SELECT call_id, account_id, agent_id_resolved AS agent_id, campaign_id, direction, vendor_id, call_status, duration_sec,
       tz AS source_tz, event_ts_utc, event_ts_ist, substr(event_ts_ist,1,7) AS report_month,
       substr(event_ts_ist,1,10) AS report_date, CAST(substr(event_ts_ist,12,2) AS INTEGER) AS hour_ist,
       CAST(strftime('%w',event_ts_ist) AS INTEGER) AS dow,
       -- hour as it would have been (mis)classified if the source tz were ignored
       CAST(substr(event_at_local,12,2) AS INTEGER) AS hour_naive,
       substr(event_at_local,1,7) AS month_naive,
       CASE WHEN call_status='ANSWERED' THEN 1 ELSE 0 END AS is_answered,
       CASE WHEN direction='OUTBOUND' THEN 1 ELSE 0 END AS is_outbound,
       CASE WHEN call_status<>'ANSWERED' AND duration_sec>0 THEN 1 ELSE 0 END AS status_duration_conflict,
       CASE WHEN event_ts_ist BETWEEN '2026-01-01 00:00:00' AND '2026-08-08 23:59:59' THEN 1 ELSE 0 END AS in_window,
       raw_row_id
FROM _call_rank WHERE rn=1;

-- ---------------- BORROWERS: versions of the same borrower_id with conflicting attributes ------------
-- Keep the latest chronologically-valid version (updated_at >= created_at), else latest updated_at.
DROP TABLE IF EXISTS _bor_rank;
CREATE TABLE _bor_rank AS
SELECT *, ROW_NUMBER() OVER (PARTITION BY borrower_id ORDER BY chronology_valid DESC, updated_at DESC, raw_row_id) AS rn,
          COUNT(*) OVER (PARTITION BY borrower_id) AS n_versions
FROM stg_borrowers;
CREATE INDEX ix_br ON _bor_rank(borrower_id, rn);
INSERT INTO rejects
SELECT 'borrowers', d.raw_row_id, d.borrower_id,
       CASE WHEN d.name=k.name AND d.phone IS k.phone AND d.email IS k.email AND d.city=k.city AND d.state=k.state
                 AND d.created_at=k.created_at AND d.updated_at=k.updated_at THEN 'EXACT_DUPLICATE_ROW'
            ELSE 'SUPERSEDED_CONFLICTING_VERSION' END
FROM _bor_rank d JOIN _bor_rank k ON k.borrower_id=d.borrower_id AND k.rn=1 WHERE d.rn>1;
DROP TABLE IF EXISTS clean_borrowers;
CREATE TABLE clean_borrowers AS
SELECT borrower_id, city, state, created_at, updated_at, n_versions, chronology_valid, raw_row_id
FROM _bor_rank WHERE rn=1;   -- name/phone/email deliberately dropped: PII, not needed, not reliable

-- ---------------- AGENTS: snapshot log (30k rows, 1,000 agent_ids) -> one row per agent_id ---------
-- agent_id is the only key used by every event table; employee_code cannot be used as a crosswalk
-- (merging by employee_code collapses all 1,000 agents into 1 component - see data-quality report).
DROP TABLE IF EXISTS _agent_rank;
CREATE TABLE _agent_rank AS
SELECT *, ROW_NUMBER() OVER (PARTITION BY agent_id ORDER BY updated_at DESC, raw_row_id) AS rn,
          MIN(joined_at) OVER (PARTITION BY agent_id) AS joined_min,
          MAX(joined_at) OVER (PARTITION BY agent_id) AS joined_max,
          COUNT(*) OVER (PARTITION BY agent_id) AS n_snapshots,
          nec.n_employee_codes
FROM stg_agents JOIN (SELECT agent_id AS aid, COUNT(DISTINCT employee_code) AS n_employee_codes FROM stg_agents GROUP BY 1) nec
  ON nec.aid=stg_agents.agent_id;
INSERT INTO rejects SELECT 'agents', raw_row_id, agent_id, 'SUPERSEDED_SNAPSHOT' FROM _agent_rank WHERE rn>1;
DROP TABLE IF EXISTS clean_agents;
CREATE TABLE clean_agents AS
SELECT agent_id, vendor_id, team, status, joined_min AS joined_at_earliest, joined_max AS joined_at_latest,
       n_snapshots, n_employee_codes, raw_row_id
FROM _agent_rank WHERE rn=1;

-- ---------------- WHATSAPP: duplicate event ids ----------------------------------------------------
DROP TABLE IF EXISTS _wa_rank;
CREATE TABLE _wa_rank AS
SELECT *, ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY raw_row_id) AS rn FROM stg_whatsapp;
INSERT INTO rejects SELECT 'whatsapp_events', raw_row_id, event_id, 'EXACT_DUPLICATE_EVENT_ID' FROM _wa_rank WHERE rn>1;
DROP TABLE IF EXISTS clean_whatsapp;
CREATE TABLE clean_whatsapp AS SELECT event_id, account_id, message_id, event_type, template_code, provider_id,
  event_ts_utc, event_ts_ist, channel, raw_row_id FROM _wa_rank WHERE rn=1;

-- ---------------- DISPOSITIONS: legacy/v1/v2 codes -> canonical code ----------------------------
-- 'PTP' and 'PROMISE_TO_PAY' are the same business outcome emitted under different code versions.
-- RPC (right-party contact) = borrower reached. NO_CONTACT and WRONG_NUMBER are not RPC.
DROP TABLE IF EXISTS clean_dispositions;
CREATE TABLE clean_dispositions AS
SELECT disposition_id, account_id, agent_id, call_id, disposition_version,
       disposition_code_raw,
       CASE disposition_code_raw WHEN 'PROMISE_TO_PAY' THEN 'PTP' ELSE disposition_code_raw END AS disposition_code,
       CASE WHEN disposition_code_raw IN ('NO_CONTACT','WRONG_NUMBER') THEN 0 ELSE 1 END AS is_rpc,
       CASE WHEN disposition_code_raw IN ('PTP','PROMISE_TO_PAY') THEN 1 ELSE 0 END AS is_ptp,
       event_ts_utc, event_ts_ist, substr(event_ts_ist,1,7) AS report_month, raw_row_id
FROM stg_call_dispositions;

-- ---------------- Pass-through tables (PK unique in raw; verified in tests) ---------------------------
DROP TABLE IF EXISTS clean_attempts;
CREATE TABLE clean_attempts AS
SELECT attempt_id, account_id, call_id, agent_id, attempt_no, COALESCE(vendor_id,'UNKNOWN') AS vendor_id, attempt_status,
       event_ts_utc, event_ts_ist, substr(event_ts_ist,1,7) AS report_month, raw_row_id FROM stg_call_attempts;
DROP TABLE IF EXISTS clean_sms;
CREATE TABLE clean_sms AS SELECT event_id, account_id, message_id, event_type, template_code, provider_id,
  event_ts_utc, event_ts_ist, channel, raw_row_id FROM stg_sms;
DROP TABLE IF EXISTS clean_field_visits;
CREATE TABLE clean_field_visits AS
SELECT visit_id, account_id, agent_id, visit_type, outcome, latitude, longitude, scheduled_at, event_ts_utc, event_ts_ist,
       substr(event_ts_ist,1,7) AS report_month, raw_row_id,
       CASE WHEN scheduled_at IS NULL THEN 1 ELSE 0 END AS schedule_missing_flag FROM stg_field_visits;
DROP TABLE IF EXISTS clean_ptp;
CREATE TABLE clean_ptp AS
SELECT ptp_id, account_id, agent_id, promised_amount, promised_ts_ist, ptp_status, source, event_ts_utc, event_ts_ist,
       substr(event_ts_ist,1,7) AS report_month, raw_row_id FROM stg_ptp;
DROP TABLE IF EXISTS clean_complaints;
CREATE TABLE clean_complaints AS SELECT complaint_id, account_id, complaint_type, severity, complaint_status, source,
  event_ts_utc, event_ts_ist, substr(event_ts_ist,1,7) AS report_month, raw_row_id FROM stg_complaints;
DROP TABLE IF EXISTS clean_status_history;
CREATE TABLE clean_status_history AS SELECT history_id, account_id, status, changed_by, source, recorded_ts_ist,
  event_ts_utc, event_ts_ist, raw_row_id FROM stg_status_history;
CREATE INDEX ix_csh ON clean_status_history(account_id, event_ts_ist);
DROP TABLE IF EXISTS clean_sessions;
CREATE TABLE clean_sessions AS SELECT session_id, agent_id, channel, tz, login_ts_utc, logout_ts_utc, login_ts_ist,
  substr(login_ts_ist,1,7) AS report_month, session_hours, raw_row_id FROM stg_agent_sessions;
DROP TABLE IF EXISTS clean_targeting;
CREATE TABLE clean_targeting AS SELECT target_id, account_id, campaign_id, target_date, substr(target_date,1,7) AS report_month,
  priority, recommended_channel, target_status, raw_row_id FROM stg_targeting;
