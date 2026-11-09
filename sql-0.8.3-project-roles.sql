-- Boban 0.8.3
ALTER TABLE project_members ADD COLUMN IF NOT EXISTS relationship VARCHAR(24) NOT NULL DEFAULT 'member';
ALTER TABLE project_invitations ADD COLUMN IF NOT EXISTS relationship VARCHAR(24) NOT NULL DEFAULT 'member';
