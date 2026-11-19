-- L2 TB EXPORT -> the L2 model's TB sheet (layouts.L2.tb in settings).
-- Same mart as the L3, rolled up without portco account number/description.
-- %(l3_codes)s = every L3 in the group, resolved from the model's l3_codes in the
-- Models page: "prefix:T" (by vertical) or "MFMF, MFHE, ..." (by list).
WITH src AS (
    SELECT *
    FROM HFC_DATA.MARTS.MART_ACCOUNT_ACTUALS_DETAILS
    WHERE L3 IN %(l3_codes)s
)
SELECT
    DATE,
    L3,
    L4,
    FINANCIAL_REPORT AS NEW_FINANCIAL_REPORT,
    MAPPING_NUMBER_FINANCIAL,
    MAPPING_NAME_FINANCIAL,
    MAPPING_NUMBER_HIGH,
    MAPPING_NAME_HIGH,
    MAPPING_NUMBER_MID,
    MAPPING_NAME_MID,
    MAPPING_NUMBER_LOW,
    MAPPING_NAME_LOW,
    SUM(COALESCE(PERIODIC, 0)) * -1       AS PERIODIC,
    SUM(COALESCE(PERPETUAL_YTD, 0)) * -1  AS PERPETUAL,
    ACQUISITION_DETAIL
FROM src
WHERE DATE >= (
        SELECT DATE_TRUNC('YEAR', DATEADD(YEAR, -3, MAX(DATE)))
        FROM src
      )
GROUP BY ALL
HAVING NOT (ABS(SUM(COALESCE(PERIODIC, 0))) < 0.0005
        AND ABS(SUM(COALESCE(PERPETUAL_YTD, 0))) < 0.0005)
ORDER BY DATE, L3, L4
