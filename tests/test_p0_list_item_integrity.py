"""P0 v3 (develop alignment) — D0-02/D0-03 real-DB regressions.

Guest/owner list lifecycle, candidate revision scope, offer/observation reference
integrity and repeatable confirm() against `planning.purchase_line` (develop's real
target table — `planning.item` never existed in develop and must not reappear).
"""
import os
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from fastapi.testclient import TestClient

from src.api import app
from src.auth.deps import Principal
from src.repo.plan_repo import PlanRepo
from src.repo.engine_repo import EngineRepo
from src.services import session_service, list_service

DSN = os.getenv('RAG_TEST_DATABASE_URL') or os.getenv('DATABASE_URL')
pytestmark = pytest.mark.skipif(not DSN, reason='requires disposable PostgreSQL')


@pytest.fixture
def conn():
    with psycopg.connect(DSN, row_factory=dict_row) as c:
        yield c
        c.rollback()


def revision(c, principal=None):
    principal = principal or Principal(user_id=None, browser_token=None)
    session = session_service.create_session(c, principal)
    return session['list_id'], PlanRepo(c).get_current_revision(session['list_id'])


def test_guest_list_lifecycle_and_ownership():
    if not os.getenv('DATABASE_URL'):
        pytest.skip('requires app database')
    with TestClient(app) as a:
        lid = a.post('/session').json()['list_id']
        assert a.post(f'/session/{lid}/category', json={'category': 'baby', 'mode': 'born'}).status_code == 200
        assert lid in [x['list_id'] for x in a.get('/lists').json()['items']]
        with TestClient(app) as b:
            assert b.patch(f'/lists/{lid}', json={'name': 'intruder'}).status_code == 404
            assert b.delete(f'/lists/{lid}').status_code == 404
        assert a.patch(f'/lists/{lid}', json={'name': 'Renamed'}).json()['name'] == 'Renamed'
        assert a.post(f'/lists/{lid}/confirm', json={'name': 'Confirm'}).status_code == 401
        assert a.delete(f'/lists/{lid}').status_code == 204
        assert lid not in [x['list_id'] for x in a.get('/lists').json()['items']]
        assert a.patch(f'/lists/{lid}', json={'name': 'Deleted'}).status_code == 404


def _seed_run_with_one_candidate(conn):
    """Build a real computer revision + completed run + one priced candidate, via the
    real repositories — never a synthetic run/candidate id string."""
    lid, rev = revision(conn)
    principal = Principal(user_id=None, browser_token=None)
    # Force category to computer so PlanRepo.get_candidates()/list_service's node join works.
    from src.repo.plan_repo import PlanRepo as _PR
    _PR(conn).bind_domain_version(rev['id'], 'computer')
    rev = PlanRepo(conn).get_current_revision(lid)  # re-fetch: bind_domain_version just changed it
    node = PlanRepo(conn).ensure_node(rev['id'], 'CPU', 'CPU')
    req = PlanRepo(conn).ensure_requirement(rev['id'], node, {})
    offer = conn.execute(
        'SELECT o.id, o.variant_id, obs.id AS observation_id FROM catalog.offer o '
        'JOIN catalog.offer_observation obs ON obs.offer_id=o.id WHERE obs.price IS NOT NULL LIMIT 1'
    ).fetchone()
    engine = EngineRepo(conn)
    run = engine.start_run(rev['id'], rev['domain_version_id'], input_snapshot={}, input_hash='0' * 64,
                           draft_lock_version=rev['lock_version'], engine_versions={})
    cand_id = engine.add_candidate(run, req, offer['variant_id'], result='selected',
                                   reason='fixture', offer_observation_id=offer['observation_id'])
    engine.complete_run(run)
    return lid, rev, run, cand_id, offer


def test_candidate_requirement_must_belong_to_same_run_revision(conn):
    """engine.recommendation_candidate.requirement_id from a DIFFERENT revision's requirement
    must be rejected — a candidate can never point outside its own run's revision.

    Not a DB constraint in develop's schema (no composite FK to the (run, revision)
    pair), so EngineRepo.add_candidate itself must refuse the write (P0 review R1) —
    no row may exist afterward, not merely be unreadable as "in scope"."""
    _, a = revision(conn)
    _, b = revision(conn)
    node_a = PlanRepo(conn).ensure_node(a['id'], 'CPU', 'CPU')
    req_a = PlanRepo(conn).ensure_requirement(a['id'], node_a, {})
    engine = EngineRepo(conn)
    run_b = engine.start_run(b['id'], b['domain_version_id'], input_snapshot={}, input_hash='0' * 64,
                             draft_lock_version=b['lock_version'], engine_versions={})
    offer = conn.execute(
        'SELECT o.variant_id FROM catalog.offer o LIMIT 1'
    ).fetchone()
    with pytest.raises(ValueError, match='cross_revision_candidate_rejected'):
        engine.add_candidate(run_b, req_a, offer['variant_id'], result='pending')
    assert conn.execute(
        'SELECT count(*) AS n FROM engine.recommendation_candidate WHERE run_id=%s', (run_b,)
    ).fetchone()['n'] == 0, 'no candidate row may exist for the rejected cross-revision write'


def test_missing_candidate_reference_rejected(conn):
    _, rev = revision(conn)
    node = PlanRepo(conn).ensure_node(rev['id'], 'CPU', 'CPU')
    req = PlanRepo(conn).ensure_requirement(rev['id'], node, {})
    engine = EngineRepo(conn)
    run = engine.start_run(rev['id'], rev['domain_version_id'], input_snapshot={}, input_hash='0' * 64,
                           draft_lock_version=rev['lock_version'], engine_versions={})
    with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
        conn.execute(
            "INSERT INTO engine.recommendation_candidate (run_id,requirement_id,variant_id,result) "
            "VALUES (%s,%s,%s,'pending')", (run, req, uuid4()),
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
        conn.execute(
            "INSERT INTO engine.recommendation_candidate (run_id,requirement_id,variant_id,result) "
            "VALUES (%s,%s,(SELECT id FROM catalog.product_variant LIMIT 1),'pending')", (run, uuid4()),
        )


def test_offer_observation_must_belong_to_its_own_offer(conn):
    """purchase_line.selected_observation_id must actually be an observation of offer_id."""
    _, rev = revision(conn)
    offers = conn.execute(
        'SELECT DISTINCT ON (o.id) o.id, obs.id AS observation_id FROM catalog.offer o '
        'JOIN catalog.offer_observation obs ON obs.offer_id=o.id ORDER BY o.id LIMIT 2'
    ).fetchall()
    assert len(offers) >= 2
    assert offers[0]['id'] != offers[1]['id']
    with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
        conn.execute(
            "INSERT INTO planning.purchase_line (revision_id,offer_id,selected_observation_id,pack_count,line_amount,snapshot) "
            "VALUES (%s,%s,%s,1,100,'{}'::jsonb)",
            (rev['id'], offers[0]['id'], offers[1]['observation_id']),
        )


def test_confirm_reads_purchase_line_snapshot_and_is_repeatable(conn):
    key = uuid4().hex
    user = conn.execute(
        "INSERT INTO identity.app_user(email_normalized,auth_subject,display_name) VALUES (%s,%s,'Reviewer') RETURNING id",
        (key + '@example.test', key),
    ).fetchone()['id']
    principal = Principal(user_id=user, browser_token=None)
    lid, rev, run, cand_id, offer = _seed_run_with_one_candidate(conn)
    # confirm() needs an *owned* revision — rebuild with the real user as owner.
    conn.execute('UPDATE planning.plan SET owner_user_id=%s WHERE id=%s', (user, lid))
    args = dict(name='Snapshot', planned_purchase_at=None, target_amount=None, memo='', if_match=rev['lock_version'])
    report = list_service.confirm(conn, UUID(lid), principal, **args)
    assert len(report['items']) == 1
    assert list_service.confirm(conn, UUID(lid), principal, **args) == report
    assert conn.execute(
        'SELECT count(*) AS n FROM planning.purchase_line WHERE revision_id=%s', (rev['id'],)
    ).fetchone()['n'] == 1
    conn.execute('UPDATE catalog.offer_observation SET price=price+100 WHERE id=%s', (offer['observation_id'],))
    list_service.rename(conn, UUID(lid), principal, name='New title')
    assert list_service.get_report(conn, UUID(lid), principal) == report


def test_confirm_rejects_when_nothing_selected(conn):
    key = uuid4().hex
    user = conn.execute(
        "INSERT INTO identity.app_user(email_normalized,auth_subject,display_name) VALUES (%s,%s,'Reviewer') RETURNING id",
        (key + '@example.test', key),
    ).fetchone()['id']
    principal = Principal(user_id=user, browser_token=None)
    lid, rev = revision(conn)
    conn.execute('UPDATE planning.plan SET owner_user_id=%s WHERE id=%s', (user, lid))
    from src.errors import ValidationFailed
    with pytest.raises(ValidationFailed):
        list_service.confirm(conn, UUID(lid), principal, name='x', planned_purchase_at=None, target_amount=None, memo='', if_match=rev['lock_version'])


def test_confirm_rejects_when_conditions_changed_without_a_new_run(conn):
    """P7 review R2: editing a condition after a completed run (without ever
    starting a new recommend) must block confirm even though If-Match matches the
    CURRENT lock_version — the completed run's own input_snapshot no longer
    reflects the current conditions, so confirming it would charge/record a basket
    that was never actually computed against what the user now has answered."""
    key = uuid4().hex
    user = conn.execute(
        "INSERT INTO identity.app_user(email_normalized,auth_subject,display_name) VALUES (%s,%s,'Reviewer') RETURNING id",
        (key + '@example.test', key),
    ).fetchone()['id']
    principal = Principal(user_id=user, browser_token=None)
    lid, rev, run, cand_id, offer = _seed_run_with_one_candidate(conn)
    conn.execute('UPDATE planning.plan SET owner_user_id=%s WHERE id=%s', (user, lid))

    # The completed run's input_snapshot has no 'values' at all (fixture uses {});
    # adding ANY condition now makes "current conditions" diverge from it.
    PlanRepo(conn).upsert_condition(rev['id'], 'budget_max', {'value': 999999}, 'explicit')
    fresh = PlanRepo(conn).get_current_revision(lid)

    from src.errors import Conflict
    with pytest.raises(Conflict) as exc_info:
        list_service.confirm(conn, UUID(lid), principal, name='x', planned_purchase_at=None,
                             target_amount=None, memo='', if_match=fresh['lock_version'])
    assert exc_info.value.code == 'stale_recommendation'
