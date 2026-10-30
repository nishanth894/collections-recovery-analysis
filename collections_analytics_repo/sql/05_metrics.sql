-- =====================================================================
-- LAYER 5: METRICS  (one row per IST calendar month; definitions in docs/metric_definitions.md)
-- Naming: rep_* = how a naive stack over the RAW data would compute it ("as reported" reconstruction)
--         *_net / no prefix = golden-layer definition.
-- =====================================================================
DROP TABLE IF EXISTS metrics_monthly;
CREATE TABLE metrics_monthly AS
WITH
rawpay AS (SELECT substr(event_ts_ist,1,7) AS m, SUM(amount) AS rep_all_inr, COUNT(*) AS rep_all_rows,
                  SUM(CASE WHEN payment_status='SUCCESS' THEN amount END) AS rep_success_inr
           FROM stg_payments GROUP BY 1),
netpay AS (SELECT report_month AS m, SUM(amount) AS net_inr, COUNT(*) AS n_payments, COUNT(DISTINCT account_id) AS paying_accounts
           FROM fact_payment WHERE is_recovery=1 GROUP BY 1),
succ_dedup AS (SELECT report_month AS m, SUM(amount) AS succ_dedup_inr FROM fact_payment WHERE is_success=1 AND in_window=1 GROUP BY 1),
base AS (SELECT SUM(outstanding_amount) AS base_out, COUNT(*) AS base_n FROM dim_account WHERE is_collectible=1),
am AS (SELECT report_month AS m, SUM(is_worked) AS worked_n,
              SUM(CASE WHEN is_worked=1 THEN outstanding_amount END) AS worked_out,
              SUM(CASE WHEN is_worked=1 THEN recovered END) AS rec_on_worked,
              SUM(is_targeted) AS targeted_n, SUM(CASE WHEN is_targeted=1 THEN outstanding_amount END) AS targeted_out,
              SUM(CASE WHEN is_targeted=1 THEN recovered END) AS rec_on_targeted
       FROM ft_account_month GROUP BY 1),
elig AS (SELECT a.report_month AS m, SUM(d.outstanding_amount) AS elig_out, COUNT(*) AS elig_n
         FROM ft_asof_status a JOIN dim_account d ON d.account_id=a.account_id
         WHERE d.is_collectible=1 AND a.asof_status NOT IN ('PAID','CLOSED','WRITEOFF') GROUP BY 1),
elig_rec AS (SELECT p.report_month AS m, SUM(p.amount) AS rec_on_elig
             FROM fact_payment p JOIN ft_asof_status a ON a.account_id=p.account_id AND a.report_month=p.report_month
             WHERE p.is_recovery=1 AND a.asof_status NOT IN ('PAID','CLOSED','WRITEOFF') GROUP BY 1),
calls AS (SELECT report_month AS m, COUNT(*) AS outbound_calls, SUM(is_answered) AS answered_calls,
                 COUNT(DISTINCT account_id) AS accounts_dialed,
                 COUNT(DISTINCT CASE WHEN is_answered=1 THEN account_id END) AS accounts_connected
          FROM fact_call WHERE is_outbound=1 AND in_window=1 GROUP BY 1),
rawcalls AS (SELECT substr(event_ts_ist,1,7) AS m, COUNT(*) AS rep_call_rows, SUM(call_status='ANSWERED') AS rep_answered
             FROM stg_calls GROUP BY 1),
disp AS (SELECT report_month AS m, COUNT(*) AS dispositions, SUM(is_rpc) AS rpc, SUM(is_ptp) AS ptp_disp,
                SUM(CASE WHEN disposition_code_raw='PTP' THEN 1 ELSE 0 END) AS ptp_legacy_code_only,
                COUNT(DISTINCT account_id) AS accounts_dispositioned,
                COUNT(DISTINCT CASE WHEN is_rpc=1 THEN account_id END) AS accounts_rpc
         FROM fact_disposition WHERE event_ts_ist BETWEEN '2026-01-01 00:00:00' AND '2026-08-08 23:59:59' GROUP BY 1),
ptp AS (SELECT report_month AS m, COUNT(*) AS ptp_created, SUM(is_matured) AS ptp_matured,
               SUM(ptp_status='KEPT') AS ptp_kept, SUM(ptp_status='BROKEN') AS ptp_broken,
               SUM(ptp_status='CANCELLED') AS ptp_cancelled, SUM(ptp_status='OPEN') AS ptp_open,
               SUM(CASE WHEN ptp_status='OPEN' AND is_matured=1 THEN 1 ELSE 0 END) AS ptp_open_pastdue,
               SUM(CASE WHEN is_matured=1 THEN payment_verified ELSE 0 END) AS ptp_verified_paid
        FROM fact_ptp GROUP BY 1),
hrs AS (SELECT report_month AS m, SUM(session_hours) AS agent_hours_all,
               SUM(CASE WHEN channel='VOICE' THEN session_hours ELSE 0 END) AS agent_hours_voice
        FROM fact_session GROUP BY 1)
SELECT dm.report_month, dm.days_observed, dm.is_partial,
       -- recovery value
       rp.rep_all_inr, rp.rep_success_inr, sd.succ_dedup_inr, np.net_inr, np.n_payments, np.paying_accounts,
       np.net_inr*1.0/dm.days_observed AS net_inr_per_day,
       -- recovery rate: numerator and denominator on the SAME population (collectible accounts)
       b.base_n, b.base_out, np.net_inr*100.0/b.base_out AS recovery_rate_fixed_pct,
       am.targeted_out, am.rec_on_targeted*100.0/am.targeted_out AS recovery_rate_targeted_pct,
       am.worked_n, am.worked_out, am.rec_on_worked*100.0/am.worked_out AS recovery_rate_worked_pct,
       el.elig_n, el.elig_out, er.rec_on_elig*100.0/el.elig_out AS recovery_rate_asof_eligible_pct,
       np.net_inr*100.0/el.elig_out AS rep_recovery_rate_mismatched_denominator_pct,  -- ALL payments / shrinking eligible base (the trap)
       np.net_inr*1.0/b.base_n AS recovery_per_account_base, np.net_inr*1.0/am.worked_n AS recovery_per_worked_account,
       -- contact / RPC / PTP
       c.outbound_calls, c.answered_calls, c.answered_calls*100.0/c.outbound_calls AS contact_rate_call_pct,
       c.accounts_dialed, c.accounts_connected, c.accounts_connected*100.0/c.accounts_dialed AS contact_rate_account_pct,
       rc.rep_answered*100.0/rc.rep_call_rows AS rep_contact_rate_pct,
       d.dispositions, d.rpc, d.rpc*100.0/d.dispositions AS rpc_rate_pct,
       d.ptp_disp, d.ptp_disp*100.0/NULLIF(d.rpc,0) AS ptp_rate_pct, d.ptp_legacy_code_only*100.0/NULLIF(d.rpc,0) AS rep_ptp_rate_legacy_code_pct,
       p.ptp_created, p.ptp_matured, p.ptp_kept, p.ptp_broken, p.ptp_cancelled, p.ptp_open, p.ptp_open_pastdue,
       p.ptp_kept*100.0/NULLIF(p.ptp_kept+p.ptp_broken,0) AS ptp_kept_rate_resolved_pct,
       p.ptp_kept*100.0/p.ptp_created AS rep_ptp_kept_rate_naive_pct,
       p.ptp_verified_paid*100.0/NULLIF(p.ptp_matured,0) AS ptp_payment_verified_rate_pct,
       -- productivity
       h.agent_hours_all, h.agent_hours_voice, np.net_inr/h.agent_hours_all AS recovery_per_agent_hour,
       h.agent_hours_all/ (np.net_inr/100000.0) AS agent_hours_per_lakh_recovered,
       c.outbound_calls*100000.0/np.net_inr AS outbound_calls_per_lakh_recovered
FROM dim_month dm
LEFT JOIN rawpay rp ON rp.m=dm.report_month LEFT JOIN netpay np ON np.m=dm.report_month
LEFT JOIN succ_dedup sd ON sd.m=dm.report_month CROSS JOIN base b
LEFT JOIN am ON am.m=dm.report_month LEFT JOIN elig el ON el.m=dm.report_month LEFT JOIN elig_rec er ON er.m=dm.report_month
LEFT JOIN calls c ON c.m=dm.report_month LEFT JOIN rawcalls rc ON rc.m=dm.report_month
LEFT JOIN disp d ON d.m=dm.report_month LEFT JOIN ptp p ON p.m=dm.report_month LEFT JOIN hrs h ON h.m=dm.report_month
ORDER BY dm.report_month;

-- Month-on-month view: percentage change vs percentage-POINT change, total vs per-observed-day
DROP VIEW IF EXISTS metrics_mom;
CREATE VIEW metrics_mom AS
SELECT report_month, is_partial,
  ROUND((rep_all_inr*1.0/LAG(rep_all_inr) OVER w-1)*100,2)      AS rep_all_mom_pct,
  ROUND((rep_success_inr*1.0/LAG(rep_success_inr) OVER w-1)*100,2) AS rep_success_mom_pct,
  ROUND((net_inr*1.0/LAG(net_inr) OVER w-1)*100,2)              AS net_total_mom_pct,
  ROUND((net_inr_per_day/LAG(net_inr_per_day) OVER w-1)*100,2)  AS net_per_day_mom_pct,
  ROUND(recovery_rate_fixed_pct-LAG(recovery_rate_fixed_pct) OVER w,4)  AS recovery_rate_mom_pp,
  ROUND(contact_rate_account_pct-LAG(contact_rate_account_pct) OVER w,3) AS contact_rate_mom_pp,
  ROUND(rpc_rate_pct-LAG(rpc_rate_pct) OVER w,3)                 AS rpc_rate_mom_pp,
  ROUND(ptp_kept_rate_resolved_pct-LAG(ptp_kept_rate_resolved_pct) OVER w,3) AS ptp_kept_mom_pp
FROM metrics_monthly WINDOW w AS (ORDER BY report_month);
