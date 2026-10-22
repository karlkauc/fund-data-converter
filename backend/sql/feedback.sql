-- User feedback submitted through the in-app dialog (POST /api/feedback).
-- Same database as usage_stats.sql; apply once as the owning role.
-- Columns must match app/usage/feedback.py (FeedbackRow).
CREATE TABLE IF NOT EXISTS feedback (
  feedback_id   uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  received_at   timestamptz NOT NULL DEFAULT now(),
  message       text        NOT NULL,   -- ≤ 4000 chars, enforced by the API
  email         text,                   -- optional reply address, user-provided
  page          text,                   -- SPA path the dialog was opened from
  direction     text,                   -- <source>-to-<target> (tpt, fundsxml, openfunds), if a conversion was open
  tpt_version   text,                   -- TPT version of that conversion, if any
  error_detail  text,                   -- error message the user was looking at, if any
  visitor_hash  text,                   -- daily-salted hash, no raw IP
  country_code  char(2),
  user_agent    text,
  device        text,                   -- desktop | mobile | bot | unknown
  app_version   text
);

CREATE INDEX IF NOT EXISTS idx_feedback_received ON feedback (received_at);
