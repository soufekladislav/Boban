-- Boban / Web Booster 0.8.2 – lokální čekající pozvánky k projektům.
CREATE TABLE IF NOT EXISTS project_invitations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    project_id BIGINT UNSIGNED NOT NULL,
    email VARCHAR(255) NOT NULL,
    role VARCHAR(40) NOT NULL DEFAULT 'visitor',
    status VARCHAR(40) NOT NULL DEFAULT 'pending',
    invited_by BIGINT UNSIGNED NULL,
    created_at VARCHAR(32) NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    UNIQUE KEY uq_project_invitations (project_id,email),
    INDEX idx_project_invitations_email (email,status),
    INDEX idx_project_invitations_project (project_id,status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
