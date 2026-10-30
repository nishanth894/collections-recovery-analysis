-- Production-style DQ assertions: each row returns 0 violations when healthy. Wire into the orchestrator as blocking/warning gates.
SELECT 'payments: duplicate payment_id in golden' AS check_name, 'BLOCK' AS severity, COUNT(*)-COUNT(DISTINCT payment_id) AS violations FROM fact_payment
UNION ALL SELECT 'payments: negative or zero amount', 'BLOCK', COUNT(*) FROM fact_payment WHERE amount<=0
UNION ALL SELECT 'payments: orphan account_id', 'BLOCK', COUNT(*) FROM fact_payment WHERE account_id NOT IN (SELECT account_id FROM dim_account)
UNION ALL SELECT 'calls: duplicate call_id in golden', 'BLOCK', COUNT(*)-COUNT(DISTINCT call_id) FROM fact_call
UNION ALL SELECT 'calls: timestamp after data cut-off', 'WARN', COUNT(*) FROM fact_call WHERE in_window=0
UNION ALL SELECT 'row conservation broken (raw != clean+rejected)', 'BLOCK', COUNT(*) FROM recon_row_counts WHERE raw_rows<>clean_rows+rejected_rows
UNION ALL SELECT 'metrics: rate outside [0,100]', 'BLOCK', COUNT(*) FROM metrics_monthly WHERE contact_rate_call_pct NOT BETWEEN 0 AND 100 OR rpc_rate_pct NOT BETWEEN 0 AND 100
UNION ALL SELECT 'metrics: month missing recovery', 'BLOCK', COUNT(*) FROM metrics_monthly WHERE net_inr IS NULL
UNION ALL SELECT 'payments: success share of duplicates rows rejected > 5% (ingestion health)', 'WARN',
       CASE WHEN (SELECT COUNT(*) FROM rejects WHERE src_table='payments')*100.0/(SELECT COUNT(*) FROM raw_payments)>5 THEN 1 ELSE 0 END;
