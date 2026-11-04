-- =====================================================================
-- 00_setup_user.sql  --  run ONCE as root:
--     mysql -u root -p < db/00_setup_user.sql
-- Creates the application user and the two databases (main + test).
-- Replace CHANGE_ME below with a password of your choice and put the
-- same value in DB_PASSWORD in .env (copy .env.example to .env).
-- =====================================================================

CREATE DATABASE IF NOT EXISTS insurance_db   CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS insurance_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'insurance_app'@'localhost' IDENTIFIED BY 'CHANGE_ME';
CREATE USER IF NOT EXISTS 'insurance_app'@'127.0.0.1' IDENTIFIED BY 'CHANGE_ME';

GRANT ALL PRIVILEGES ON insurance_db.*   TO 'insurance_app'@'localhost', 'insurance_app'@'127.0.0.1';
GRANT ALL PRIVILEGES ON insurance_test.* TO 'insurance_app'@'localhost', 'insurance_app'@'127.0.0.1';
-- PROCESS lets the app user run SHOW ENGINE INNODB STATUS for the deadlock demo
GRANT PROCESS ON *.* TO 'insurance_app'@'localhost', 'insurance_app'@'127.0.0.1';

-- Binary logging is on by default in MySQL 8; without SUPER, a non-root user
-- may only create triggers/functions when this flag is set.
SET PERSIST log_bin_trust_function_creators = 1;

FLUSH PRIVILEGES;
SELECT VERSION() AS mysql_version, 'insurance_app ready' AS status;
