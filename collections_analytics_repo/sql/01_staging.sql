-- =====================================================================
-- LAYER 1: STAGING  (typed, trimmed, tz-normalised; ONE ROW IN = ONE ROW OUT)
-- Dialect: SQLite 3.35+ (portable to Postgres/BigQuery; see docs/architecture.md)
-- Timestamp policy (see docs/assumptions.md A-03):
--   * Tables carrying an explicit timezone column (calls, agent_sessions) -> converted using it.
--   * Tables with NO timezone column -> assumed Asia/Kolkata (operating tz). Sensitivity: analysis section 5.
--   * event_ts_utc = canonical; event_ts_ist = reporting clock; report_month = IST calendar month.
-- =====================================================================

DROP TABLE IF EXISTS stg_accounts;
CREATE TABLE stg_accounts AS
SELECT rowid AS raw_row_id,
       UPPER(TRIM(account_id))                       AS account_id,
       NULLIF(UPPER(TRIM(borrower_id)),'')           AS borrower_id,
       UPPER(TRIM(loan_type))                        AS loan_type,
       CAST(principal_amount AS REAL)                AS principal_amount,
       CAST(outstanding_amount AS REAL)              AS outstanding_amount,
       CAST(dpd AS INTEGER)                          AS dpd,
       CASE WHEN CAST(dpd AS INTEGER)=0 THEN '0 (current)'
            WHEN CAST(dpd AS INTEGER)<=30 THEN '01-30'
            WHEN CAST(dpd AS INTEGER)<=60 THEN '31-60'
            WHEN CAST(dpd AS INTEGER)<=90 THEN '61-90'
            ELSE '91+' END                           AS dpd_bucket,
       UPPER(TRIM(risk_segment))                     AS risk_segment,
       UPPER(TRIM(status))                           AS status,
       opened_at,
       TRIM(timezone)                                AS account_tz,
       schema_version
FROM raw_accounts;

DROP TABLE IF EXISTS stg_borrowers;
CREATE TABLE stg_borrowers AS
SELECT rowid AS raw_row_id, UPPER(TRIM(borrower_id)) AS borrower_id, TRIM(name) AS name,
       TRIM(phone) AS phone, LOWER(TRIM(email)) AS email, TRIM(city) AS city, TRIM(state) AS state,
       created_at, updated_at,
       CASE WHEN updated_at >= created_at THEN 1 ELSE 0 END AS chronology_valid
FROM raw_borrowers;

DROP TABLE IF EXISTS stg_agents;
CREATE TABLE stg_agents AS
SELECT rowid AS raw_row_id, UPPER(TRIM(agent_id)) AS agent_id, UPPER(TRIM(employee_code)) AS employee_code,
       TRIM(agent_name) AS agent_name, UPPER(TRIM(vendor_id)) AS vendor_id, UPPER(TRIM(team)) AS team,
       UPPER(TRIM(status)) AS status, joined_at, updated_at
FROM raw_agents;

DROP TABLE IF EXISTS stg_vendors;
CREATE TABLE stg_vendors AS
SELECT rowid AS raw_row_id, UPPER(TRIM(vendor_id)) AS vendor_id, TRIM(vendor_name) AS vendor_name,
       vendor_account_id, TRIM(timezone) AS vendor_tz, UPPER(status) AS vendor_status, schema_version
FROM raw_vendor_telephony;

DROP TABLE IF EXISTS stg_campaigns;
CREATE TABLE stg_campaigns AS
SELECT rowid AS raw_row_id, UPPER(TRIM(campaign_id)) AS campaign_id, UPPER(TRIM(campaign_name)) AS campaign_name,
       UPPER(TRIM(channel)) AS channel, strategy_version, start_at, end_at, target_definition
FROM raw_campaigns;

-- ---- calls (explicit tz column) ------------------------------------------------
DROP TABLE IF EXISTS stg_calls;
CREATE TABLE stg_calls AS
WITH t AS (
  SELECT rowid AS raw_row_id, UPPER(TRIM(call_id)) AS call_id, UPPER(TRIM(account_id)) AS account_id,
         UPPER(TRIM(borrower_id)) AS borrower_id_src, event_at AS event_at_local,
         NULLIF(UPPER(TRIM(agent_id)),'') AS agent_id, UPPER(TRIM(campaign_id)) AS campaign_id,
         UPPER(TRIM(direction)) AS direction, UPPER(TRIM(vendor_id)) AS vendor_id,
         UPPER(TRIM(call_status)) AS call_status, CAST(duration_sec AS INTEGER) AS duration_sec,
         TRIM(timezone) AS tz,
         CASE TRIM(timezone) WHEN 'Asia/Kolkata' THEN 330 WHEN 'Asia/Dubai' THEN 240 ELSE 0 END AS off_min
  FROM raw_calls)
SELECT *, datetime(event_at_local, '-'||off_min||' minutes') AS event_ts_utc,
          datetime(event_at_local, '-'||off_min||' minutes', '+330 minutes') AS event_ts_ist
FROM t;

DROP TABLE IF EXISTS stg_agent_sessions;
CREATE TABLE stg_agent_sessions AS
WITH t AS (
  SELECT rowid AS raw_row_id, UPPER(TRIM(session_id)) AS session_id, UPPER(TRIM(agent_id)) AS agent_id,
         login_at, logout_at, UPPER(channel) AS channel, device_id, TRIM(timezone) AS tz,
         CASE TRIM(timezone) WHEN 'Asia/Kolkata' THEN 330 WHEN 'Asia/Dubai' THEN 240 ELSE 0 END AS off_min
  FROM raw_agent_sessions)
SELECT *, datetime(login_at,'-'||off_min||' minutes') AS login_ts_utc,
          datetime(logout_at,'-'||off_min||' minutes') AS logout_ts_utc,
          datetime(login_at,'-'||off_min||' minutes','+330 minutes') AS login_ts_ist,
          (julianday(logout_at)-julianday(login_at))*24.0 AS session_hours
FROM t;

-- ---- event tables WITHOUT tz column: assumed IST --------------------------------
DROP TABLE IF EXISTS stg_call_attempts;
CREATE TABLE stg_call_attempts AS
SELECT rowid AS raw_row_id, UPPER(TRIM(attempt_id)) AS attempt_id, UPPER(TRIM(account_id)) AS account_id,
       UPPER(TRIM(borrower_id)) AS borrower_id_src, UPPER(TRIM(call_id)) AS call_id,
       NULLIF(UPPER(TRIM(agent_id)),'') AS agent_id, CAST(attempt_no AS INTEGER) AS attempt_no,
       NULLIF(UPPER(TRIM(vendor_id)),'') AS vendor_id, UPPER(TRIM(attempt_status)) AS attempt_status,
       event_at AS event_at_local, datetime(event_at,'-330 minutes') AS event_ts_utc, event_at AS event_ts_ist
FROM raw_call_attempts;

DROP TABLE IF EXISTS stg_call_dispositions;
CREATE TABLE stg_call_dispositions AS
SELECT rowid AS raw_row_id, UPPER(TRIM(disposition_id)) AS disposition_id, UPPER(TRIM(account_id)) AS account_id,
       UPPER(TRIM(borrower_id)) AS borrower_id_src, UPPER(TRIM(call_id)) AS call_id,
       NULLIF(UPPER(TRIM(agent_id)),'') AS agent_id, UPPER(TRIM(disposition_code)) AS disposition_code_raw,
       disposition_version, event_at AS event_at_local, datetime(event_at,'-330 minutes') AS event_ts_utc, event_at AS event_ts_ist
FROM raw_call_dispositions;

DROP TABLE IF EXISTS stg_whatsapp;
CREATE TABLE stg_whatsapp AS
SELECT rowid AS raw_row_id, UPPER(TRIM(whatsapp_event_id)) AS event_id, UPPER(TRIM(account_id)) AS account_id,
       UPPER(TRIM(borrower_id)) AS borrower_id_src, message_id, UPPER(TRIM(event_type)) AS event_type,
       UPPER(TRIM(template_code)) AS template_code, UPPER(TRIM(provider_id)) AS provider_id,
       datetime(event_at,'-330 minutes') AS event_ts_utc, event_at AS event_ts_ist, 'WHATSAPP' AS channel
FROM raw_whatsapp_events;

DROP TABLE IF EXISTS stg_sms;
CREATE TABLE stg_sms AS
SELECT rowid AS raw_row_id, UPPER(TRIM(sms_event_id)) AS event_id, UPPER(TRIM(account_id)) AS account_id,
       UPPER(TRIM(borrower_id)) AS borrower_id_src, message_id, UPPER(TRIM(event_type)) AS event_type,
       UPPER(TRIM(template_code)) AS template_code, UPPER(TRIM(provider_id)) AS provider_id,
       datetime(event_at,'-330 minutes') AS event_ts_utc, event_at AS event_ts_ist, 'SMS' AS channel
FROM raw_sms_events;

DROP TABLE IF EXISTS stg_field_visits;
CREATE TABLE stg_field_visits AS
SELECT rowid AS raw_row_id, UPPER(TRIM(visit_id)) AS visit_id, UPPER(TRIM(account_id)) AS account_id,
       UPPER(TRIM(borrower_id)) AS borrower_id_src, NULLIF(UPPER(TRIM(agent_id)),'') AS agent_id,
       UPPER(TRIM(visit_type)) AS visit_type, UPPER(TRIM(outcome)) AS outcome,
       CAST(latitude AS REAL) AS latitude, CAST(longitude AS REAL) AS longitude, scheduled_at,
       datetime(event_at,'-330 minutes') AS event_ts_utc, event_at AS event_ts_ist
FROM raw_field_visits;

DROP TABLE IF EXISTS stg_ptp;
CREATE TABLE stg_ptp AS
SELECT rowid AS raw_row_id, UPPER(TRIM(ptp_id)) AS ptp_id, UPPER(TRIM(account_id)) AS account_id,
       UPPER(TRIM(borrower_id)) AS borrower_id_src, NULLIF(UPPER(TRIM(agent_id)),'') AS agent_id,
       CAST(promised_amount AS REAL) AS promised_amount, promised_date AS promised_ts_ist,
       UPPER(TRIM(status)) AS ptp_status, UPPER(TRIM(source)) AS source,
       datetime(event_at,'-330 minutes') AS event_ts_utc, event_at AS event_ts_ist
FROM raw_promises_to_pay;

DROP TABLE IF EXISTS stg_payments;
CREATE TABLE stg_payments AS
SELECT rowid AS raw_row_id, UPPER(TRIM(payment_id)) AS payment_id, UPPER(TRIM(account_id)) AS account_id,
       UPPER(TRIM(borrower_id)) AS borrower_id_src, NULLIF(UPPER(TRIM(payment_reference)),'') AS payment_reference,
       CAST(amount AS REAL) AS amount, UPPER(TRIM(payment_status)) AS payment_status,
       UPPER(TRIM(payment_method)) AS payment_method, UPPER(TRIM(provider_id)) AS provider_id,
       datetime(event_at,'-330 minutes') AS event_ts_utc, event_at AS event_ts_ist
FROM raw_payments;

DROP TABLE IF EXISTS stg_complaints;
CREATE TABLE stg_complaints AS
SELECT rowid AS raw_row_id, UPPER(TRIM(complaint_id)) AS complaint_id, UPPER(TRIM(account_id)) AS account_id,
       UPPER(TRIM(complaint_type)) AS complaint_type, UPPER(TRIM(severity)) AS severity,
       UPPER(TRIM(status)) AS complaint_status, UPPER(TRIM(source)) AS source, resolution_at,
       datetime(event_at,'-330 minutes') AS event_ts_utc, event_at AS event_ts_ist
FROM raw_complaints;

DROP TABLE IF EXISTS stg_status_history;
CREATE TABLE stg_status_history AS
SELECT rowid AS raw_row_id, UPPER(TRIM(history_id)) AS history_id, UPPER(TRIM(account_id)) AS account_id,
       UPPER(TRIM(status)) AS status, UPPER(TRIM(changed_by)) AS changed_by, UPPER(TRIM(source)) AS source,
       recorded_at AS recorded_ts_ist, datetime(event_at,'-330 minutes') AS event_ts_utc, event_at AS event_ts_ist
FROM raw_account_status_history;

DROP TABLE IF EXISTS stg_targeting;
CREATE TABLE stg_targeting AS
SELECT rowid AS raw_row_id, UPPER(TRIM(target_id)) AS target_id, UPPER(TRIM(account_id)) AS account_id,
       UPPER(TRIM(campaign_id)) AS campaign_id, substr(target_date,1,10) AS target_date,
       CAST(priority AS INTEGER) AS priority, UPPER(TRIM(recommended_channel)) AS recommended_channel,
       UPPER(TRIM(status)) AS target_status
FROM raw_daily_targeting;
