-- 0013_schema_reduction_scope_constraints.sql
-- P0 SR08 완결: 0011/0012 가 최상위 JSON 모양만 막던 것을 실제 계약 수준으로 끌어올린다.
--
-- 0012 까지의 상태에서는 아래가 전부 DB 에 그대로 들어갔다:
--   * evidence_refs.refs = [{"junk":1},{"junk":1}]  → 필수 키 없음 + 중복 허용
--   * run 이 속한 리비전과 다른 리비전의 requirement 를 가리키는 candidate → 스코프 위반
--   * candidate 의 run 과 무관한 retrieval_run 에서 나온 evidence → 실행 스코프 위반
-- 이 마이그레이션은 세 가지를 각각 CHECK / 복합 FK / 트리거로 강제한다.
-- 모든 제약은 NOT VALID 로 선언만 하지 않고 이 파일 안에서 VALIDATE 까지 수행한다.

-- ═══════════════════════ Phase 1: JSON 항목 구조 검증 함수 ═══════════════════════
-- CHECK 제약은 서브쿼리를 직접 쓸 수 없으므로 IMMUTABLE 함수로 감싼다.

-- refs 배열 하나에 대한 검증: 각 원소가 v1 EvidenceRef 필수 키를 모두 갖고,
-- (evidence_id, claim_key) 가 중복되지 않는다. src.reduction_contracts.EvidenceRef 와 1:1.
CREATE OR REPLACE FUNCTION app.evidence_ref_list_valid(arr jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT jsonb_typeof(arr) = 'array'
     AND NOT EXISTS (
           SELECT 1 FROM jsonb_array_elements(arr) AS r
           WHERE jsonb_typeof(r) IS DISTINCT FROM 'object'
              OR COALESCE(r->>'evidence_id', '') = ''
              OR COALESCE(r->>'claim_key', '') = ''
              OR COALESCE(r->>'material_id', '') = ''
              OR COALESCE(r->>'material_version', '') = ''
              OR COALESCE(r->>'file_sha256', '') = ''
              OR jsonb_typeof(r->'locator') IS DISTINCT FROM 'object'
         )
     AND (SELECT count(*) FROM jsonb_array_elements(arr) AS r)
       = (SELECT count(DISTINCT (r->>'evidence_id', r->>'claim_key')) FROM jsonb_array_elements(arr) AS r)
$$;

-- candidate.evidence_refs 전체(v1 봉투 + refs 배열).
CREATE OR REPLACE FUNCTION app.evidence_refs_v1_valid(obj jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT jsonb_typeof(obj) = 'object'
     AND obj->>'schema_version' = '1'
     AND app.evidence_ref_list_valid(obj->'refs')
$$;

-- validation_result.issues: v1 ValidationIssue 배열. target 은 항상 보존되고
-- evidence_refs 는 refs 와 동일한 항목 규칙을 따른다.
CREATE OR REPLACE FUNCTION app.validation_issues_v1_valid(arr jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT jsonb_typeof(arr) = 'array'
     AND NOT EXISTS (
           SELECT 1 FROM jsonb_array_elements(arr) AS i
           WHERE jsonb_typeof(i) IS DISTINCT FROM 'object'
              OR i->>'schema_version' IS DISTINCT FROM '1'
              OR COALESCE(i->>'rule_key', '') = ''
              OR COALESCE(i->>'rule_version', '') = ''
              OR COALESCE(i->>'status', '') NOT IN ('pass', 'fail', 'unknown')
              OR jsonb_typeof(i->'target') IS DISTINCT FROM 'object'
              OR NOT app.evidence_ref_list_valid(COALESCE(i->'evidence_refs', '[]'::jsonb))
         )
$$;

-- ═══════════════════════ Phase 2: 기존 행을 새 계약으로 정규화 ═══════════════════════
-- 0012 이전 쓰기 경로는 {evidence_id, claim_key} 만 남기는 부분 ref 를 만들 수 있었다.
-- 신규 설치에서는 대상 행이 없고, 그렇지 않은 경우에도 계약을 못 맞추는 ref 는
-- 조용히 남겨두지 않고 제거한다(불완전 인용을 유효한 것처럼 통과시키지 않는다).
UPDATE engine.recommendation_candidate c
SET evidence_refs = jsonb_build_object('schema_version', 1, 'refs',
      COALESCE((SELECT jsonb_agg(r) FROM jsonb_array_elements(c.evidence_refs->'refs') AS r
                WHERE app.evidence_ref_list_valid(jsonb_build_array(r))), '[]'::jsonb))
WHERE NOT app.evidence_refs_v1_valid(c.evidence_refs);

UPDATE engine.validation_result v
SET issues = COALESCE((
      SELECT jsonb_agg(jsonb_set(i, '{evidence_refs}',
               COALESCE((SELECT jsonb_agg(r) FROM jsonb_array_elements(COALESCE(i->'evidence_refs', '[]'::jsonb)) AS r
                         WHERE app.evidence_ref_list_valid(jsonb_build_array(r))), '[]'::jsonb)))
      FROM jsonb_array_elements(v.issues) AS i
      WHERE jsonb_typeof(i) = 'object' AND i->>'schema_version' = '1'
        AND jsonb_typeof(i->'target') = 'object'
        AND COALESCE(i->>'rule_key', '') <> '' AND COALESCE(i->>'rule_version', '') <> ''
        AND COALESCE(i->>'status', '') IN ('pass', 'fail', 'unknown')
    ), '[]'::jsonb)
WHERE NOT app.validation_issues_v1_valid(v.issues);

-- ═══════════════════════ Phase 3: 항목 단위 CHECK 제약 (선언 + 검증) ═══════════════════════
ALTER TABLE engine.recommendation_candidate
  DROP CONSTRAINT IF EXISTS recommendation_candidate_evidence_refs_items_check;
ALTER TABLE engine.recommendation_candidate
  ADD CONSTRAINT recommendation_candidate_evidence_refs_items_check
  CHECK (app.evidence_refs_v1_valid(evidence_refs)) NOT VALID;
ALTER TABLE engine.recommendation_candidate
  VALIDATE CONSTRAINT recommendation_candidate_evidence_refs_items_check;

ALTER TABLE engine.validation_result
  DROP CONSTRAINT IF EXISTS validation_result_issues_items_check;
ALTER TABLE engine.validation_result
  ADD CONSTRAINT validation_result_issues_items_check
  CHECK (app.validation_issues_v1_valid(issues)) NOT VALID;
ALTER TABLE engine.validation_result
  VALIDATE CONSTRAINT validation_result_issues_items_check;

-- ═══════════════════════ Phase 4: 리비전 스코프 (선언적 복합 FK) ═══════════════════════
-- candidate 는 자신의 run 이 속한 리비전의 requirement 만 가리킬 수 있다.
-- planning.requirement(id, revision_id) UNIQUE 는 0011 이 이미 만들어 뒀다.
ALTER TABLE engine.recommendation_run
  DROP CONSTRAINT IF EXISTS recommendation_run_id_revision_key;
ALTER TABLE engine.recommendation_run
  ADD CONSTRAINT recommendation_run_id_revision_key UNIQUE (id, revision_id);

ALTER TABLE engine.recommendation_candidate
  ADD COLUMN IF NOT EXISTS revision_id uuid;
UPDATE engine.recommendation_candidate c
SET revision_id = r.revision_id
FROM engine.recommendation_run r
WHERE r.id = c.run_id AND c.revision_id IS DISTINCT FROM r.revision_id;
ALTER TABLE engine.recommendation_candidate ALTER COLUMN revision_id SET NOT NULL;

-- run 쪽 스코프: (run_id, revision_id) 가 실제 run 행과 일치해야 한다.
ALTER TABLE engine.recommendation_candidate
  DROP CONSTRAINT IF EXISTS rec_candidate_run_revision_fk;
ALTER TABLE engine.recommendation_candidate
  ADD CONSTRAINT rec_candidate_run_revision_fk
  FOREIGN KEY (run_id, revision_id)
  REFERENCES engine.recommendation_run(id, revision_id) ON DELETE CASCADE NOT VALID;
ALTER TABLE engine.recommendation_candidate
  VALIDATE CONSTRAINT rec_candidate_run_revision_fk;

-- requirement 쪽 스코프: 같은 revision_id 의 requirement 만 참조 가능.
ALTER TABLE engine.recommendation_candidate
  DROP CONSTRAINT IF EXISTS rec_candidate_requirement_revision_fk;
ALTER TABLE engine.recommendation_candidate
  ADD CONSTRAINT rec_candidate_requirement_revision_fk
  FOREIGN KEY (requirement_id, revision_id)
  REFERENCES planning.requirement(id, revision_id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE engine.recommendation_candidate
  VALIDATE CONSTRAINT rec_candidate_requirement_revision_fk;

-- revision_id 는 run 에서 파생되는 값이므로 애플리케이션이 직접 바꾸지 못하게 한다.
CREATE OR REPLACE FUNCTION engine.candidate_revision_from_run() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE run_revision uuid;
BEGIN
  SELECT revision_id INTO run_revision FROM engine.recommendation_run WHERE id = NEW.run_id;
  IF run_revision IS NULL THEN
    RAISE EXCEPTION 'candidate_scope_violation: run % 이(가) 없습니다', NEW.run_id;
  END IF;
  NEW.revision_id := run_revision;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS candidate_revision_from_run ON engine.recommendation_candidate;
CREATE TRIGGER candidate_revision_from_run
  BEFORE INSERT OR UPDATE OF run_id, revision_id ON engine.recommendation_candidate
  FOR EACH ROW EXECUTE FUNCTION engine.candidate_revision_from_run();

-- ═══════════════════════ Phase 5: evidence 실행 스코프 (트리거) ═══════════════════════
-- refs 의 evidence_id 는 실재해야 하고, material 근거라면 그 evidence 를 만든
-- retrieval_run 이 이 candidate 와 같은 recommendation_run 에 속해야 한다.
-- (다른 실행에서 검색된 인용을 이 실행의 근거로 재사용하는 것을 막는다.)
CREATE OR REPLACE FUNCTION engine.candidate_evidence_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE bad uuid;
BEGIN
  -- 구조가 깨진 refs 는 여기서 가로채지 않는다 — evidence_refs_items_check 가
  -- 정확한 위반 사유로 거부하게 둔다(트리거가 CHECK 보다 먼저 돈다).
  IF NOT app.evidence_refs_v1_valid(NEW.evidence_refs) THEN
    RETURN NEW;
  END IF;
  SELECT (r->>'evidence_id')::uuid INTO bad
  FROM jsonb_array_elements(COALESCE(NEW.evidence_refs->'refs', '[]'::jsonb)) AS r
  WHERE NOT EXISTS (
    SELECT 1 FROM evidence.evidence ev
    LEFT JOIN rag.retrieval_hit rh ON rh.id = ev.retrieval_hit_id
    LEFT JOIN rag.retrieval_run rr ON rr.id = rh.retrieval_run_id
    WHERE ev.id = (r->>'evidence_id')::uuid
      AND (ev.kind <> 'material' OR rr.recommendation_run_id = NEW.run_id)
  )
  LIMIT 1;
  IF bad IS NOT NULL THEN
    RAISE EXCEPTION 'evidence_scope_violation: evidence % 은(는) run % 의 근거가 아닙니다', bad, NEW.run_id;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS candidate_evidence_scope ON engine.recommendation_candidate;
CREATE TRIGGER candidate_evidence_scope
  BEFORE INSERT OR UPDATE OF evidence_refs ON engine.recommendation_candidate
  FOR EACH ROW EXECUTE FUNCTION engine.candidate_evidence_scope();

-- ═══════════════════════ Phase 6: 스냅샷 불변 (도메인 규칙 변경 무관) ═══════════════════════
-- plan_revision.domain_snapshot / recommendation_run.domain_snapshot 은 생성 시점
-- 게시 규칙의 사본이다. 이후 config.domain 이 바뀌어도 절대 따라 움직이면 안 된다.
CREATE OR REPLACE FUNCTION app.freeze_domain_snapshot() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.domain_snapshot IS DISTINCT FROM OLD.domain_snapshot THEN
    RAISE EXCEPTION 'domain_snapshot_immutable: % 의 도메인 스냅샷은 생성 이후 변경할 수 없습니다', TG_TABLE_NAME;
  END IF;
  RETURN NEW;
END $$;

-- plan_revision 만 예외가 하나 있다: 세션 생성 시점에는 카테고리가 없으므로 임시
-- 도메인이 들어가고, 사용자가 카테고리를 고를 때 PlanRepo.bind_domain 이 한 번
-- 다시 묶는다. 그 창은 "아직 draft 이고 이 리비전으로 실행된 run 이 없을 때"뿐이다.
-- 실행이 한 번이라도 시작됐으면 그 run 이 이 스냅샷을 근거로 삼았으므로 고정된다.
CREATE OR REPLACE FUNCTION app.freeze_plan_revision_snapshot() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.domain_snapshot IS DISTINCT FROM OLD.domain_snapshot
     AND NOT (OLD.state = 'draft'
              AND NOT EXISTS (SELECT 1 FROM engine.recommendation_run WHERE revision_id = OLD.id))
  THEN
    RAISE EXCEPTION 'domain_snapshot_immutable: plan_revision 의 도메인 스냅샷은 실행 시작 이후 변경할 수 없습니다';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS freeze_domain_snapshot ON planning.plan_revision;
CREATE TRIGGER freeze_domain_snapshot
  BEFORE UPDATE OF domain_snapshot ON planning.plan_revision
  FOR EACH ROW EXECUTE FUNCTION app.freeze_plan_revision_snapshot();

DROP TRIGGER IF EXISTS freeze_domain_snapshot ON engine.recommendation_run;
CREATE TRIGGER freeze_domain_snapshot
  BEFORE UPDATE OF domain_snapshot ON engine.recommendation_run
  FOR EACH ROW EXECUTE FUNCTION app.freeze_domain_snapshot();

-- ═══════════════════════ Phase 7: 도메인 스냅샷 내용 계약 ═══════════════════════
-- 빈 정의/제로 해시 스냅샷은 "사용된 규칙을 보존한다"는 계약을 만족하지 못한다.
-- 기존 행 중 계약을 못 맞추는 것은 현재 config.domain 값으로 복구한다(신규 설치에는 대상 없음).
ALTER TABLE planning.plan_revision DISABLE TRIGGER freeze_domain_snapshot;
UPDATE planning.plan_revision r
SET domain_snapshot = jsonb_build_object('version_no', d.current_version_no, 'definition', d.definition,
      'attribute_schema', d.attribute_schema, 'content_hash', d.content_hash)
FROM config.domain d
WHERE d.id = r.domain_id
  AND (jsonb_typeof(r.domain_snapshot->'definition') IS DISTINCT FROM 'object'
       OR COALESCE(r.domain_snapshot->>'content_hash', '') ~ '^0*$'
       OR r.domain_snapshot->'definition' = '{}'::jsonb);
ALTER TABLE planning.plan_revision ENABLE TRIGGER freeze_domain_snapshot;

ALTER TABLE engine.recommendation_run DISABLE TRIGGER freeze_domain_snapshot;
UPDATE engine.recommendation_run run
SET domain_snapshot = jsonb_build_object('version_no', d.current_version_no, 'definition', d.definition,
      'attribute_schema', d.attribute_schema, 'content_hash', d.content_hash)
FROM config.domain d
WHERE d.id = run.domain_id
  AND (jsonb_typeof(run.domain_snapshot->'definition') IS DISTINCT FROM 'object'
       OR COALESCE(run.domain_snapshot->>'content_hash', '') ~ '^0*$'
       OR run.domain_snapshot->'definition' = '{}'::jsonb);
ALTER TABLE engine.recommendation_run ENABLE TRIGGER freeze_domain_snapshot;

CREATE OR REPLACE FUNCTION app.domain_snapshot_v1_valid(snap jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT jsonb_typeof(snap) = 'object'
     AND jsonb_typeof(snap->'definition') = 'object'
     AND snap->'definition' <> '{}'::jsonb
     AND jsonb_typeof(snap->'attribute_schema') = 'object'
     AND COALESCE(snap->>'content_hash', '') <> ''
     AND COALESCE(snap->>'content_hash', '') !~ '^0*$'
     AND (snap->>'version_no') ~ '^[0-9]+$'
$$;

ALTER TABLE planning.plan_revision
  DROP CONSTRAINT IF EXISTS plan_revision_domain_snapshot_v1_check;
ALTER TABLE planning.plan_revision
  ADD CONSTRAINT plan_revision_domain_snapshot_v1_check
  CHECK (app.domain_snapshot_v1_valid(domain_snapshot)) NOT VALID;
ALTER TABLE planning.plan_revision
  VALIDATE CONSTRAINT plan_revision_domain_snapshot_v1_check;

ALTER TABLE engine.recommendation_run
  DROP CONSTRAINT IF EXISTS recommendation_run_domain_snapshot_v1_check;
ALTER TABLE engine.recommendation_run
  ADD CONSTRAINT recommendation_run_domain_snapshot_v1_check
  CHECK (app.domain_snapshot_v1_valid(domain_snapshot)) NOT VALID;
ALTER TABLE engine.recommendation_run
  VALIDATE CONSTRAINT recommendation_run_domain_snapshot_v1_check;

-- 스냅샷을 채우려면 config.domain 이 실제 게시 정의를 갖고 있어야 한다.
ALTER TABLE config.domain
  DROP CONSTRAINT IF EXISTS domain_published_definition_check;
ALTER TABLE config.domain
  ADD CONSTRAINT domain_published_definition_check
  CHECK (status <> 'active'
         OR (jsonb_typeof(definition) = 'object' AND definition <> '{}'::jsonb
             AND length(btrim(content_hash)) > 0 AND content_hash !~ '^0*$')) NOT VALID;
ALTER TABLE config.domain VALIDATE CONSTRAINT domain_published_definition_check;
