-- FRESHNESS: one row per L3 code saying how current its data is in Snowflake.
-- Drives the Status board (what's stale) and expands L2 "prefix:" rules.
--
-- Must return exactly these columns (names matter, order doesn't):
--   L3_CODE         the L3 company code
--   L3_NAME         display name (optional -- return NULL if you don't have one)
--   LATEST_PERIOD   last period end date that has data (DATE)
--   LAST_LOADED_AT  when that company's data last changed (TIMESTAMP)
--
-- Replace the <<...>> placeholders with the mart that feeds your L3 export.
SELECT
    L3_CODE,
    MAX(L3_NAME)            AS L3_NAME,
    MAX(PERIOD_END_DATE)    AS LATEST_PERIOD,
    MAX(LOADED_AT)          AS LAST_LOADED_AT
FROM <<HFC_DATA.MARTS.YOUR_TB_MART>>
GROUP BY L3_CODE
ORDER BY L3_CODE
