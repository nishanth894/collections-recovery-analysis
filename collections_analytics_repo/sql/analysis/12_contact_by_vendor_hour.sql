-- Contact rate by telephony vendor (canonical name) and by IST hour band; outbound, in-window.
SELECT 'vendor' AS dim, vendor_name AS level, COUNT(*) AS calls, ROUND(100.0*AVG(is_answered),2) AS contact_rate_pct
FROM fact_call WHERE is_outbound=1 AND in_window=1 GROUP BY vendor_name
UNION ALL
SELECT 'hour_band_ist',
       CASE WHEN hour_ist<6 THEN '00-05' WHEN hour_ist<9 THEN '06-08' WHEN hour_ist<12 THEN '09-11' WHEN hour_ist<15 THEN '12-14'
            WHEN hour_ist<18 THEN '15-17' WHEN hour_ist<21 THEN '18-20' ELSE '21-23' END,
       COUNT(*), ROUND(100.0*AVG(is_answered),2)
FROM fact_call WHERE is_outbound=1 AND in_window=1 GROUP BY 2
ORDER BY dim, level;
