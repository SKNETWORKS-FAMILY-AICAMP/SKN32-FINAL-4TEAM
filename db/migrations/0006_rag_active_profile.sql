-- One active embedding profile; same-dimensional models still cannot mix.
-- Keep the existing 1024-dimensional column for the initial Titan v2 profile.
CREATE UNIQUE INDEX rag_one_active_profile
  ON rag.embedding_profile ((status)) WHERE status = 'active';
