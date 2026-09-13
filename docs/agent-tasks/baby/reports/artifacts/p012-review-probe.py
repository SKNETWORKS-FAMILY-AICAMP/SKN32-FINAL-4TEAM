import os,sys,json
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path.cwd()));sys.path.insert(0,str(Path.cwd()/'scripts'))
import psycopg
from src.services.session_service import normalize_baby_conditions,create_session,choose_category,handle_answer,_current_values
from src.auth.deps import Principal
from src.repo.plan_repo import PlanRepo
from src.engine.stage2_requirement import build_baby_requirements
from src.engine.stage3_0_candidates import get_baby_candidates
from seed_baby_catalog import load_input,seed_catalog
out={}
normalized=normalize_baby_conditions({'mode':'born','age_months':8,'needs':['수유'],'owned_items':[]})
try: build_baby_requirements(normalized,{'reference_date':'2026-09-13'});out['normalized_to_requirements']='pass'
except ValueError as e: out['normalized_to_requirements']=str(e)
out['representative_age_after_current_values_unwrap']=normalize_baby_conditions({'mode':'born','age_months':5})['age_stage']
with psycopg.connect(os.environ['DATABASE_URL']) as c:
 out['orphan_item_accepted']=bool(c.execute("insert into planning.item(revision_id,variant_id,status,qty) values (%s,%s,'owned',1) returning id",(uuid4(),uuid4())).fetchone())
 ss=create_session(c,Principal(user_id=None,browser_token=None)); principal=Principal(user_id=None,browser_token=ss['browser_token']); choose_category(c,ss['list_id'],'baby','born',principal); handle_answer(c,ss['list_id'],'q_age',[5],principal);rev=PlanRepo(c).get_current_revision(ss['list_id']);req=PlanRepo(c).ensure_requirement(rev['id'],'stroller',{})
 out['nonexistent_fulfillment_accepted']=bool(c.execute('update planning.requirement set fulfilled_by_item_id=%s where id=%s returning id',(uuid4(),req)).fetchone())
 values,_=_current_values(PlanRepo(c),rev['id']); out['actual_stored_age']=c.execute("select value from planning.plan_condition where revision_id=%s and condition_key='age_months' and status='active'",(rev['id'],)).fetchone()[0]; out['actual_normalized_age']=normalize_baby_conditions(values)['age_stage']
 manifest,records=load_input(Path('data/baby/catalog_demo_v1.json'));seed_catalog(c,records,dataset_version=manifest['dataset_version'],corpus='synthetic')
 conditions={'revision_id':str(rev['id']),'mode':'born','age_months':8,'needs':['기저귀·배변','외출'],'owned_items':['유모차']}
 reqs=build_baby_requirements(conditions,{'reference_date':'2026-09-13'});cands=get_baby_candidates(c,reqs,corpus='synthetic')
 out['owned_fulfillment_ids']=[r.fulfilled_by_item_id for r in reqs if r.fulfilled_by_item_id]
 out['diaper_fixture_unit_qty']=next(r['unit_qty'] for r in records if r['product_key']=='SYN-DIAPER-CA03-001')
 out['diaper_candidate_unit_qty']=[x.unit_qty for xs in cands.values() for x in xs if x.product_key=='SYN-DIAPER-CA03-001']
 c.rollback()
print(json.dumps(out,ensure_ascii=False,indent=2))
Path('/tmp/p012_review_probe.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
