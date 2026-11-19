-- L3 LEGEND EXPORT -> written to the L3 model's Legend sheet.
-- Delete this file if the L3 has no Legend export; the app then skips that step.
SELECT *
FROM <<HFC_DATA.MARTS.YOUR_LEGEND_TABLE>>
WHERE L3_CODE IN %(l3_codes)s
ORDER BY 1
