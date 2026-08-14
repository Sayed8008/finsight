-- FinSight — database and application user setup
--
-- Run once, as an administrative MySQL user:
--     sudo mysql < scripts/setup_database.sql
--
-- IMPORTANT: change the password below before running, then put the same
-- password into your .env file. Do not commit .env.
--
-- Why a dedicated user instead of root:
--   The application should hold only the privileges it actually needs, on only
--   the databases it actually uses. If the app is ever compromised, the blast
--   radius is these two schemas — not the whole MySQL server. This is the
--   principle of least privilege, and it costs nothing to apply from day one.

-- ─── Databases ────────────────────────────────────────────────────────────
-- utf8mb4 is real UTF-8 in MySQL, including emoji and full Bangla text.
-- MySQL's legacy "utf8" is a 3-byte subset and will corrupt some characters.

CREATE DATABASE IF NOT EXISTS finsight
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

-- Separate database for the test suite. Tests destroy data; they must never
-- run against the development database.
CREATE DATABASE IF NOT EXISTS finsight_test
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

-- ─── Application user ─────────────────────────────────────────────────────
-- MySQL 8.4 disabled mysql_native_password; caching_sha2_password is the
-- default and only practical choice. The PyMySQL driver needs the
-- `cryptography` package installed to authenticate with it.

CREATE USER IF NOT EXISTS 'finsight'@'localhost'
    IDENTIFIED WITH caching_sha2_password BY 'CHANGE_ME_BEFORE_RUNNING';

-- Full rights on the two application schemas only. No global privileges,
-- no access to other databases, no user administration.
GRANT ALL PRIVILEGES ON finsight.*      TO 'finsight'@'localhost';
GRANT ALL PRIVILEGES ON finsight_test.* TO 'finsight'@'localhost';

FLUSH PRIVILEGES;

-- ─── Verify ───────────────────────────────────────────────────────────────
SELECT 'Databases created:' AS status;
SHOW DATABASES LIKE 'finsight%';

SELECT 'Grants for finsight@localhost:' AS status;
SHOW GRANTS FOR 'finsight'@'localhost';
