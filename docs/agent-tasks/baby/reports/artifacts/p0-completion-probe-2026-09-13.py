import os,json
from uuid import uuid4
import psycopg
from fastapi.testclient import TestClient
from src.api import app
from src.repo.plan_repo import PlanRepo
out={}
with TestClient(app,raise_server_exceptions=False) as client:
 r=client.post('/session');out['create_session']=r.status_code
 lid=r.json()['list_id'];out['category']=client.post(f'/session/{lid}/category',json={'category':'baby','mode':'born'}).status_code
 for name,method,url,data in [('lists','get','/lists',None),('rename','patch',f'/lists/{lid}',{'name':'P0 review'}),('delete','delete',f'/lists/{lid}',None)]:
  r=getattr(client,method)(url,**({'json':data} if data else {}));out[name]={'status':r.status_code,'body':r.text[:200]}
with psycopg.connect(os.environ['DATABASE_URL']) as c:
 out['table_count']=c.execute("select count(*) from information_schema.tables where table_type='BASE TABLE' and table_schema not in ('pg_catalog','information_schema','_migrations')").fetchone()[0]
 out['review_metadata_columns']=[r[0] for r in c.execute("select column_name from information_schema.columns where table_schema='evidence' and table_name='review_summary' and column_name in ('author_ref','review_posted_at') order by 1")]
 out['orphan_item_accepted']=bool(c.execute("insert into planning.item(revision_id,variant_id,status,qty) values (%s,%s,'owned',1) returning id",(uuid4(),uuid4())).fetchone())
 repo=PlanRepo(c);rev=repo.get_current_revision(lid);req=repo.ensure_requirement(rev['id'],'stroller',{})
 out['nonexistent_fulfillment_accepted']=bool(c.execute('update planning.requirement set fulfilled_by_item_id=%s where id=%s returning id',(uuid4(),req)).fetchone())
 out['item_foreign_keys']=c.execute("select count(*) from pg_constraint where conrelid='planning.item'::regclass and contype='f'").fetchone()[0]
 c.rollback()
print(json.dumps(out,ensure_ascii=False,indent=2))
