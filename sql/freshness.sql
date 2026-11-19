-- FRESHNESS: one row per L3 saying how current its data is. Drives the Status board
-- and expands L2 "prefix:" rules.
--
-- DATA_HASH fingerprints exactly the rows/columns the L3 export pulls (same 3-year
-- window), so ANY change - new JE, restatement, remap, re-load - flags the model as
-- "Updated data" without needing a loaded-at timestamp in the mart.
WITH win AS (
    SELECT
        L3,
        MAX(DATE)                                           AS LATEST_PERIOD,
        DATE_TRUNC('YEAR', DATEADD(YEAR, -3, MAX(DATE)))    AS START_DATE
    FROM HFC_DATA.MARTS.MART_ACCOUNT_ACTUALS_DETAILS
    GROUP BY L3
)
SELECT
    w.L3                        AS L3_CODE,
    NULL::VARCHAR               AS L3_NAME,
    w.LATEST_PERIOD,
    NULL::TIMESTAMP_NTZ         AS LAST_LOADED_AT,
    HASH_AGG(
        d.DATE, d.L4, d.FINANCIAL_REPORT,
        d.MAPPING_NUMBER_FINANCIAL, d.MAPPING_NAME_FINANCIAL,
        d.MAPPING_NUMBER_HIGH, d.MAPPING_NAME_HIGH,
        d.MAPPING_NUMBER_MID, d.MAPPING_NAME_MID,
        d.MAPPING_NUMBER_LOW, d.MAPPING_NAME_LOW,
        d.PORTCO_ACCOUNT_NUMBER, d.PORTCO_ACCOUNT_DESCRIPTION,
        d.PERIODIC, d.PERPETUAL_YTD, d.ACQUISITION_DETAIL
    )::VARCHAR                  AS DATA_HASH
FROM win w
JOIN HFC_DATA.MARTS.MART_ACCOUNT_ACTUALS_DETAILS d
  ON d.L3 = w.L3
 AND d.DATE >= w.START_DATE
GROUP BY w.L3, w.LATEST_PERIOD
ORDER BY w.L3
