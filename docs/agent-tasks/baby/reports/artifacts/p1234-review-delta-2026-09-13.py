import os,json
from uuid import uuid4
import psycopg
from src.dto import BabyRequirement,BasketItem,CandidateCheck,RankedCandidates
from src.engine.stage2_requirement import build_baby_requirements,load_baby_rules_snapshot,persist_baby_requirements
from src.engine.stage3c_verify import verify_baby_candidate
from src.engine.stage4_optimize import optimize_baby,recalculate_basket
from src.repo.plan_repo import PlanRepo
from src.services.session_service import create_session
from src.auth.deps import Principal
out={}
# New boundary: certificate fact is missing entirely, rather than the existing unknown fixture.
c={'candidate_id':'cert-missing','requirement_id':'r','slot_key':'car_seat','product_key':'test','variant_key':'test','corpus':'synthetic','facts':{}}
out['missing_certificate_fact']=verify_baby_candidate(None,c,{},{}).model_dump()
req=BabyRequirement(id='r',revision_id='v',slot_key='bottle',required_qty=1,unit_code='each')
item=BasketItem(item_id='i',requirement_id='r',status='to_purchase',selected=True,candidate_id=None,unit_price=10)
out['selected_without_candidate_or_check']=recalculate_basket([item],[req],100,[]).model_dump()
owned=BasketItem(item_id='i2',requirement_id='r',status='owned',qty=1,unit_code='kg')
out['recalculate_wrong_unit']=recalculate_basket([owned],[req],100,[]).model_dump()
# New integration case: partial ownership (bottle needs2, owns1); no full report tests rerun.
with psycopg.connect(os.environ['DATABASE_URL']) as conn:
 try:
  ss=create_session(conn,Principal(user_id=None,browser_token=None))
  rev=PlanRepo(conn).get_current_revision(ss['list_id'])
  cond={'revision_id':str(rev['id']),'mode':'born','age_stage':{'months':8,'exact':True},'needs':['수유'],'owned_items':['젖병']}
  pure=build_baby_requirements(cond,{'reference_date':'2026-09-13','baby_rules_snapshot':load_baby_rules_snapshot()})
  bottles=[r for r in pure if r.slot_key=='bottle']
  persisted=persist_baby_requirements(conn,rev['id'],bottles)
  decision=optimize_baby(persisted,RankedCandidates(profile_version='review',weights={},by_requirement={}),[],100)
  out['partial_owned_after_persistence']={'requirements':[r.model_dump() for r in persisted],'decision':decision.model_dump()}
 finally: conn.rollback()
print(json.dumps(out,ensure_ascii=False,indent=2))
