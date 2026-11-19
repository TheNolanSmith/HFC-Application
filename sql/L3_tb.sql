-- L3 TB EXPORT -> written to the L3 model's TB sheet (see layouts.L3.tb in settings).
--
-- Paste your existing L3 TB export query here. Columns come out in the order you
-- SELECT them and land starting at layouts.L3.tb.data_start_col, so match the
-- TB sheet's column order. Headers in the workbook are left alone.
--
-- Filter on the L3 code with:   WHERE L3_CODE IN %(l3_codes)s
-- (the app passes a tuple; for an L3 model it holds that one code)
SELECT *
FROM <<HFC_DATA.MARTS.YOUR_TB_MART>>
WHERE L3_CODE IN %(l3_codes)s
  -- Skip rows where both periodic and perpetual balances are zero
  AND NOT (COALESCE(PERIODIC_BALANCE, 0) = 0 AND COALESCE(PERPETUAL_BALANCE, 0) = 0)
ORDER BY PERIOD_END_DATE, ACCOUNT_NUMBER
