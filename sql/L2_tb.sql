-- L2 TB EXPORT -> written to the L2 model's TB sheet (see layouts.L2.tb in settings).
--
-- Same mart as the L3 export, without the portco account number / description.
-- %(l3_codes)s is every L3 code in the group: the app resolves it from the
-- model's l3_codes rule ("prefix:A" or an explicit list) in config/models.csv.
SELECT *
FROM <<HFC_DATA.MARTS.YOUR_TB_MART_L2_GRAIN>>
WHERE L3_CODE IN %(l3_codes)s
ORDER BY L3_CODE, PERIOD_END_DATE
