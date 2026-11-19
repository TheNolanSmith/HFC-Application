-- Team-wide refresh log. The app runs this automatically (CREATE IF NOT EXISTS)
-- the first time it logs, if your role is allowed to. Otherwise have an admin run it
-- and grant INSERT, SELECT on it to the people using the app.
CREATE TABLE IF NOT EXISTS {table} (
    RUN_ID          VARCHAR,
    BATCH_ID        VARCHAR,
    MODEL_ID        VARCHAR,
    MODEL_NAME      VARCHAR,
    LEVEL           VARCHAR,
    L3_CODES        VARCHAR,
    FILE_PATH       VARCHAR,
    STATUS          VARCHAR,        -- SUCCESS | FAILED
    TB_ROWS         NUMBER,
    LEGEND_ROWS     NUMBER,
    THROUGH_PERIOD  DATE,
    DATA_LOADED_AT  TIMESTAMP_NTZ,  -- newest LAST_LOADED_AT across the model's codes at refresh time
    STARTED_AT      TIMESTAMP_NTZ,
    FINISHED_AT     TIMESTAMP_NTZ,
    SECONDS         NUMBER(10,1),
    USER_NAME       VARCHAR,
    MACHINE         VARCHAR,
    APP_VERSION     VARCHAR,
    MESSAGE         VARCHAR,
    DATA_HASH       VARCHAR         -- fingerprint of the model's source rows at refresh time
)
