"""Only regressions found by P1234-completion-review; DB writes roll back."""
import os
import psycopg
import pytest
from src.auth.deps import Principal
from src.dto import BabyRequirement, BabyCandidate, BasketItem, CandidateCheck
from src.repo.plan_repo import PlanRepo
from src.services import session_service as ss
from src.engine.stage2_requirement import build_baby_requirements, load_baby_rules_snapshot, persist_baby_requirements, load_persisted_baby_requirements
from src.engine.stage3b_rank import rank_baby_candidates
from src.engine.stage3c_verify import verify_baby_candidate
from src.engine.stage4_optimize import optimize_baby, recalculate_basket

@pytest.fixture
def conn():
    dsn=os.getenv('RAG_TEST_DATABASE_URL')
    if not dsn: pytest.skip('requires isolated PostgreSQL')
    with psycopg.connect(dsn) as c:
        yield c
        c.rollback()


def session(c):
    result=ss.create_session(c,Principal(user_id=None,browser_token=None))
    who=Principal(user_id=None,browser_token=result['browser_token'])
    ss.choose_category(c,result['list_id'],'baby','born',who)
    return result['list_id'],who,PlanRepo(c).get_current_revision(result['list_id'])


def test_chip_metadata_survives_official_normalization(conn):
    lid,who,rev=session(conn)
    ss.handle_answer(conn,lid,'q_age',[5],who)
    values,_=ss._current_values(PlanRepo(conn),rev['id'])
    assert ss.normalize_baby_conditions(values)['age_stage']['exact'] is False
    ss.handle_message(conn,lid,'8개월',who)
    values,_=ss._current_values(PlanRepo(conn),rev['id'])
    age = ss.normalize_baby_conditions(values)['age_stage']
    assert age['months'] == 8 and age['exact'] is True


def test_partial_owned_survives_storage_and_recalculation(conn):
    lid,who,rev=session(conn)
    # v3: owned refs point at a real plan_condition row (DEVELOP_DB_TRANSITION.md) —
    # persist_baby_requirements needs an actual persisted owned_items condition, not
    # just the value passed to build_baby_requirements.
    ss.handle_answer(conn,lid,'q_owned',['젖병'],who)
    cond={'revision_id':str(rev['id']),'mode':'born','age_stage':{'months':8,'exact':True},'needs':['수유'],'owned_items':['젖병']}
    pure=build_baby_requirements(cond,{'reference_date':'2026-09-13','baby_rules_snapshot':load_baby_rules_snapshot()})
    raw=[r for r in pure if r.slot_key=='bottle']
    persisted=persist_baby_requirements(conn,rev['id'],raw)
    assert len(persisted)==1
    r=persisted[0]
    assert (r.required_qty,r.fulfilled_qty)==(2,1)
    assert load_persisted_baby_requirements(conn,rev['id'])==persisted
    assert persist_baby_requirements(conn,rev['id'],persisted)==persisted
    rank=rank_baby_candidates(persisted,[],[],{'weights':{'price':1}})
    empty=optimize_baby(persisted,rank,[],100)
    assert not empty.feasible
    assert sum(i.qty for i in empty.items if i.status=='owned')==1
    c=BabyCandidate(candidate_id='candidate',requirement_id=r.id,product_id='p',product_key='p',name='bottle',slot_key='bottle',price=10)
    check=CandidateCheck(candidate_id='candidate',requirement_id=r.id,eligibility='pass',verification='verified',coverage='full',selection_allowed=True)
    ranked=rank_baby_candidates(persisted,[c],[check],{'weights':{'price':1}})
    good=optimize_baby(persisted,ranked,[],100)
    assert good.feasible and good.totals['selected_price']==10
    assert sum(i.qty for i in good.items if i.status=='to_purchase')==1
    assert recalculate_basket(good.items,load_persisted_baby_requirements(conn,rev['id']),100,[check]).feasible
    no_owned=[r.model_copy(update={'owned':[],'fulfilled_qty':0})]
    changed=persist_baby_requirements(conn,rev['id'],no_owned)
    assert changed[0].owned==[]
    assert changed[0].fulfilled_qty==0
    stored=conn.execute("SELECT match_spec->'baby_requirement'->'owned' FROM planning.requirement WHERE id=%s",(r.id,)).fetchone()[0]
    assert stored==[]


@pytest.mark.parametrize('slot',['car_seat','high_chair','bottle','diaper'])
def test_missing_reviewed_safety_rule_is_not_a_pass(slot):
    check=verify_baby_candidate(None,{'candidate_id':'c','requirement_id':'r','slot_key':slot,'facts':{}}, {}, {})
    assert check.eligibility=='unknown' and not check.selection_allowed


@pytest.mark.parametrize('change',[
    {'candidate_id':None}, {'unit_code':'kg'}, {'qty':0.5}, {'unit_qty':float('nan')},
    {'requirement_id':'other'}, {'status':'owned','unit_code':'kg'},
])
def test_edit_validation_rejects_invalid_coverage(change):
    r=BabyRequirement(id='r',revision_id='rev',slot_key='bottle')
    i=BasketItem(item_id='i',requirement_id='r',candidate_id='c',status='to_purchase',selected=True,unit_price=10).model_copy(update=change)
    check=CandidateCheck(candidate_id='c',requirement_id='r',eligibility='pass',verification='verified',coverage='full',selection_allowed=True)
    out=recalculate_basket([i],[r],100,[check])
    assert not out.feasible
    assert out.items[0].validation['issues']


def test_cross_requirement_check_and_over_budget_are_infeasible():
    r=BabyRequirement(id='r',revision_id='rev',slot_key='bottle')
    i=BasketItem(item_id='i',requirement_id='r',candidate_id='c',status='to_purchase',selected=True,unit_price=10)
    check=CandidateCheck(candidate_id='c',requirement_id='other',eligibility='pass',verification='verified',coverage='full',selection_allowed=True)
    assert not recalculate_basket([i],[r],100,[check]).feasible
    check=check.model_copy(update={'requirement_id':'r'})
    assert not recalculate_basket([i],[r],5,[check]).feasible
