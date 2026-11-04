-- =====================================================================
-- run_all.sql  --  rebuild everything from scratch with ONE command.
-- Run from inside the db/ folder (SOURCE paths are relative):
--     cd db
--     mysql -u insurance_app -p < run_all.sql          (cmd / bash)
-- or, from the project root on any OS:
--     python scripts/build_db.py
-- =====================================================================
DROP DATABASE IF EXISTS insurance_db;
CREATE DATABASE insurance_db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE insurance_db;

SOURCE 01_schema.sql;
SOURCE 02_triggers.sql;
SOURCE 03_procedures.sql;
SOURCE 04_views.sql;
SOURCE 05_seed_data.sql;
SOURCE 06_indexes.sql;

SELECT 'insurance_db rebuilt' AS status,
       (SELECT COUNT(*) FROM policy) AS policies,
       (SELECT COUNT(*) FROM claim)  AS claims;
