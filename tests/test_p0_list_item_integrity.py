"""P0 list SQL and item reference regressions on a real disposable database."""
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

DSN = os.getenv('RAG_TEST_DATABASE_URL')
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
        assert a.post(f'/session/{lid}/category', json={'category':'baby','mode':'born'}).status_code == 200
        assert lid in [x['list_id'] for x in a.get('/lists').json()['items']]
        with TestClient(app) as b:
            assert b.patch(f'/lists/{lid}', json={'name':'intruder'}).status_code == 404
            assert b.delete(f'/lists/{lid}').status_code == 404
        assert a.patch(f'/lists/{lid}', json={'name':'Renamed'}).json()['name'] == 'Renamed'
        assert a.post(f'/lists/{lid}/confirm', json={'name':'Confirm'}).status_code == 401
        assert a.delete(f'/lists/{lid}').status_code == 204
        assert lid not in [x['list_id'] for x in a.get('/lists').json()['items']]
        assert a.patch(f'/lists/{lid}', json={'name':'Deleted'}).status_code == 404


@pytest.mark.parametrize('field', ['revision_id','variant_id','offer_id','offer_observation_id'])
def test_missing_item_reference_rejected(conn, field):
    _, rev = revision(conn)
    offer = conn.execute('SELECT o.id, o.variant_id, obs.id AS observation_id FROM catalog.offer o JOIN catalog.offer_observation obs ON obs.offer_id=o.id LIMIT 1').fetchone()
    values = dict(revision_id=rev['id'], variant_id=offer['variant_id'], offer_id=offer['id'], offer_observation_id=offer['observation_id'])
    values[field] = uuid4()
    with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
        conn.execute("INSERT INTO planning.item(revision_id,variant_id,offer_id,offer_observation_id,status,qty) VALUES (%(revision_id)s,%(variant_id)s,%(offer_id)s,%(offer_observation_id)s,'owned',1)", values)


def test_fulfillment_same_revision_and_parent_updates(conn):
    _, a = revision(conn); _, b = revision(conn)
    req = PlanRepo(conn).ensure_requirement(a['id'], 'stroller', {})
    item = conn.execute("INSERT INTO planning.item(revision_id,status,qty) VALUES (%s,'owned',1) RETURNING id", (a['id'],)).fetchone()['id']
    other = conn.execute("INSERT INTO planning.item(revision_id,status,qty) VALUES (%s,'owned',1) RETURNING id", (b['id'],)).fetchone()['id']
    for invalid in [uuid4(), other]:
        with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
            conn.execute('UPDATE planning.requirement SET fulfilled_by_item_id=%s WHERE id=%s', (invalid,req))
    conn.execute('UPDATE planning.requirement SET fulfilled_by_item_id=%s WHERE id=%s', (item,req))
    with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
        conn.execute('UPDATE planning.item SET revision_id=%s WHERE id=%s', (b['id'],item))


def test_offer_and_observation_must_belong_to_item_variant(conn):
    _, rev = revision(conn)
    offers = conn.execute('SELECT o.id,o.variant_id,obs.id AS observation_id FROM catalog.offer o JOIN catalog.offer_observation obs ON obs.offer_id=o.id ORDER BY o.id').fetchall()
    a = offers[0]; b = next(o for o in offers if o['variant_id'] != a['variant_id'])
    for variant, offer, obs in [(b['variant_id'],a['id'],a['observation_id']), (a['variant_id'],a['id'],b['observation_id'])]:
        with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
            conn.execute("INSERT INTO planning.item(revision_id,variant_id,offer_id,offer_observation_id,status,qty) VALUES (%s,%s,%s,%s,'to_purchase',1)",(rev['id'],variant,offer,obs))


def test_confirm_reads_item_snapshot_and_is_repeatable(conn):
    key = uuid4().hex
    user = conn.execute("INSERT INTO identity.app_user(email_normalized,auth_subject,display_name) VALUES (%s,%s,'Reviewer') RETURNING id",(key+'@example.test',key)).fetchone()['id']
    principal = Principal(user_id=user,browser_token=None)
    lid, rev = revision(conn,principal)
    req = PlanRepo(conn).ensure_requirement(rev['id'],'CPU',{})
    offer = conn.execute('SELECT o.id,o.variant_id,obs.id AS observation_id FROM catalog.offer o JOIN catalog.offer_observation obs ON obs.offer_id=o.id WHERE obs.price IS NOT NULL LIMIT 1').fetchone()
    engine = EngineRepo(conn)
    run = engine.start_run(rev['id'],rev['domain_id'],input_snapshot={},input_hash='0'*64,draft_lock_version=rev['lock_version'],engine_versions={})
    engine.add_candidate(run,req,offer['variant_id'],result='selected',reason='fixture',offer_observation_id=offer['observation_id'])
    engine.complete_run(run)
    args=dict(name='Snapshot',planned_purchase_at=None,target_amount=None,memo='')
    report = list_service.confirm(conn,lid,principal,**args)
    assert len(report['items']) == 1
    assert list_service.confirm(conn,lid,principal,**args) == report
    assert conn.execute('SELECT count(*) AS n FROM planning.item WHERE revision_id=%s AND selected',(rev['id'],)).fetchone()['n'] == 1
    conn.execute('UPDATE catalog.offer_observation SET price=price+100 WHERE id=%s',(offer['observation_id'],))
    list_service.rename(conn,lid,principal,name='New title')
    assert list_service.get_report(conn,lid,principal) == report

@pytest.mark.parametrize('missing', ['variant_id','offer_id'])
def test_optional_reference_cannot_bypass_relationship_check(conn, missing):
    _, rev = revision(conn)
    row = conn.execute('SELECT o.id AS offer_id,o.variant_id,obs.id AS offer_observation_id FROM catalog.offer o JOIN catalog.offer_observation obs ON obs.offer_id=o.id LIMIT 1').fetchone()
    row[missing] = None
    row['revision_id'] = rev['id']
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute("INSERT INTO planning.item(revision_id,variant_id,offer_id,offer_observation_id,status,qty) VALUES (%(revision_id)s,%(variant_id)s,%(offer_id)s,%(offer_observation_id)s,'owned',1)",row)
