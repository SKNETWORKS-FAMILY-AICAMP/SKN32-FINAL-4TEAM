"""v3 list confirmation on develop purchase_line; no planning.item/RAG fallback."""
from __future__ import annotations
import hashlib
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from psycopg.types.json import Jsonb
from src.auth.deps import Principal
from src.db.base import Repo
from src.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from src.repo.notification_repo import NotificationRepo
from src.services import feedback_service

_PRICE_WATCH_WINDOW_DAYS = 30

def _guest_hash(t): return hashlib.sha256(t.encode()).hexdigest() if t else None
def _iso(v): return v.isoformat() if v is not None else None
def _int(v): return None if v is None else int(v)
def _owned(repo, lid, p, lock=False):
 r=repo._one("""SELECT p.id list_id,p.name list_name,p.owner_user_id,r.*,c.user_id conversation_user_id,c.guest_session_hash,d.code category FROM planning.plan p JOIN planning.plan_revision r ON r.id=p.current_revision_id JOIN identity.conversation c ON c.id=p.conversation_id JOIN config.domain_version dv ON dv.id=r.domain_version_id JOIN config.domain d ON d.id=dv.domain_id WHERE p.id=%s AND p.status='active'"""+(" FOR UPDATE OF p,r" if lock else ""),(lid,))
 if not r or not ((p.user_id and (r['owner_user_id']==p.user_id or r['conversation_user_id']==p.user_id)) or (r['guest_session_hash'] and r['guest_session_hash']==_guest_hash(p.browser_token))): raise NotFound('장바구니를 찾을 수 없습니다.')
 return r
def _report(repo,lid,p):
 r=_owned(repo,lid,p)
 if r['state']!='confirmed': raise NotFound('확정된 리포트가 없습니다.')
 run=repo._one("SELECT input_snapshot FROM engine.recommendation_run WHERE revision_id=%s AND input_snapshot ? 'baby_confirmation' ORDER BY completed_at DESC NULLS LAST LIMIT 1",(r['id'],))
 c=((run or {}).get('input_snapshot') or {}).get('baby_confirmation') or {}; totals=c.get('totals') or {'now':_int(r['confirmed_total']) or 0,'soon':0,'later':0}; items=[]; links=[]
 for x in repo._all('SELECT pack_count,line_amount,snapshot FROM planning.purchase_line WHERE revision_id=%s ORDER BY created_at,id',(r['id'],)):
  s=x['snapshot'] or {}; product=s.get('product') or {}; items.append({'slot':s.get('slot'),'slot_label':s.get('slot_label') or s.get('slot'),'product':product,'price':_int(s.get('unit_price',x['line_amount'])),'qty':int(x['pack_count']),'timing':s.get('timing','now'),'review':s.get('review'),'evidence_text':s.get('evidence_text','')})
  if product.get('purchase_url'): links.append({'name':product.get('name'),'purchase_url':product['purchase_url']})
 o=repo._one('SELECT display_name FROM identity.app_user WHERE id=%s',(r['owner_user_id'],))
 return {'list_id':str(lid),'name':c.get('name',r['name_snapshot']),'category':r['category'],'owner_display_name':o['display_name'] if o else None,'planned_purchase_at':c.get('planned_purchase_at',_iso(r['planned_purchase_at'])),'target_amount':c.get('target_amount',_int(r['target_amount'])),'memo':c.get('memo',r['memo'] or ''),'total':totals['now'],'totals':totals,'confirmed_at':c.get('confirmed_at',_iso(r['confirmed_at'])),'items':items,'buy_links':links,'missing_requirements':c.get('missing_requirements',[]),'owned':c.get('owned',[]),'data_notice':'확정 당시의 상품·가격·조건 스냅샷입니다.'}
def _current_values(repo, revision_id):
 """confirm()의 조건-변경 감지용(P7 review R2) — start_recommendation이 run.input_snapshot에
 얼린 것과 같은 모양으로 지금의 조건을 다시 만든다."""
 return {row['condition_key']:(row['value'] if row['condition_key']=='age_months' else row['value'].get('value')) for row in repo._all("SELECT condition_key,value FROM planning.plan_condition WHERE revision_id=%s AND status='active'",(revision_id,))}
def confirm(conn,lid,p,*,name,planned_purchase_at:date|None,target_amount,memo,if_match=None):
 if not p.user_id: raise Unauthorized('로그인이 필요합니다.')
 from src.repo.engine_repo import EngineRepo
 from src.repo.material_repo import MaterialRepo
 from src.repo.plan_repo import PlanRepo
 from src.engine.stage2_requirement import load_persisted_baby_requirements
 from src.services.recommendation_service import _baby_items_and_totals
 repo=Repo(conn)
 with conn.transaction():
  r=_owned(repo,lid,p,lock=True)
  if r['owner_user_id']!=p.user_id: raise NotFound('장바구니를 찾을 수 없습니다.')
  if r['state']=='confirmed': return _report(repo,lid,p)
  if if_match is None: raise ValidationFailed('If-Match(lock_version)이 필요합니다.',field='lock_version')
  if if_match!=r['lock_version']: raise Conflict('조건이 변경되어 최신 상태가 아닙니다.',code='stale_version')
  # P7 review R2: the CURRENT run for this revision (whatever its status), not just
  # "the latest completed one" — a newer running/failed run in front of an old
  # completed one must block confirm, not be silently skipped past.
  latest=repo._one("SELECT id,status FROM engine.recommendation_run WHERE revision_id=%s ORDER BY created_at DESC LIMIT 1 FOR UPDATE",(r['id'],))
  if latest is None or latest['status']!='completed': raise ValidationFailed('완료된 추천 결과가 없습니다.',code='no_completed_run')
  run=repo._one("SELECT * FROM engine.recommendation_run WHERE id=%s",(latest['id'],))
  # Conditions may have changed since this run completed without a newer run ever
  # having been started (candidate edits alone also bump lock_version, so comparing
  # lock_version directly would reject valid post-edit confirms too — compare the
  # actual condition values the run was computed against instead).
  if _current_values(repo,r['id'])!=((run['input_snapshot'] or {}).get('values') or {}):
   raise Conflict('추천 이후 조건이 변경되었습니다. 다시 추천을 실행해 주세요.',code='stale_recommendation')
  rows=repo._all("""SELECT c.id candidate_id,c.qty,c.timing,c.reason,c.evidence_refs,req.id requirement_id,req.quantity required_qty,req.unit_code,req.required,req.match_spec,n.template_key slot,n.name slot_label,v.id variant_id,v.pack_quantity unit_qty,p.id db_product_id,p.model product_key,p.name product_name,p.image_url,o.id offer_id,o.variant_id offer_variant_id,o.purchase_url,obs.id observation_id,obs.offer_id observation_offer_id,obs.price,obs.currency,obs.observed_at,obs.stock_status,obs.quality_status FROM engine.recommendation_candidate c JOIN planning.requirement req ON req.id=c.requirement_id AND req.revision_id=%s AND req.status='active' JOIN planning.plan_node n ON n.id=req.node_id JOIN catalog.product_variant v ON v.id=c.variant_id JOIN catalog.product p ON p.id=v.product_id LEFT JOIN catalog.offer_observation obs ON obs.id=c.offer_observation_id LEFT JOIN catalog.offer o ON o.id=obs.offer_id WHERE c.run_id=%s AND c.selected ORDER BY n.position,c.created_at""",(r['id'],run['id']))
  if not rows: raise ValidationFailed('선택된 구매 후보가 없습니다.',code='no_items_selected')
  budget=repo._one("SELECT (value->>'value')::numeric amount FROM planning.plan_condition WHERE revision_id=%s AND condition_key='budget_max' AND status='active'",(r['id'],))
  budget_max=int(budget['amount']) if budget and budget['amount'] is not None else None
  if r['category']=='baby':
   # P7 review R1: re-derive full requirement coverage (all active requirements +
   # validated owned qty + current selections) through the same P4 recalculation the
   # result screen uses — the per-selected-candidate loop below can never notice a
   # mandatory slot with NOTHING selected at all.
   _,_,feasible,_missing=_baby_items_and_totals(conn,PlanRepo(conn),EngineRepo(conn),r['id'],budget_max)
   if not feasible: raise ValidationFailed('예산 안에서 채울 수 없거나 누락된 필수 품목이 있습니다.',code='basket_infeasible')
  material_repo=MaterialRepo(conn)
  totals={'now':0,'soon':0,'later':0}; lines=[]
  for x in rows:
   if not 1<=int(x['qty'])<=99 or x['timing'] not in totals: raise ValidationFailed('구매 후보 수량 또는 시점이 올바르지 않습니다.',code='invalid_purchase_candidate')
   if not (x['offer_id'] and x['observation_id'] and x['price'] is not None and x['quality_status']=='valid' and x['stock_status']=='available' and x['observation_offer_id']==x['offer_id'] and x['offer_variant_id']==x['variant_id']): raise ValidationFailed('검증 가능한 가격 관측값이 없습니다.',code='invalid_observation')
   if r['category']=='baby':
    issues=repo._all("SELECT i FROM engine.validation_result vr, jsonb_array_elements(vr.issues) i WHERE vr.run_id=%s AND i->'target'->>'candidate_id'=%s",(run['id'],str(x['candidate_id'])))
    statuses=[row['i'].get('status') for row in issues]
    if 'fail' in statuses or not statuses or 'unknown' in statuses: raise ValidationFailed('안전 검증이 완료되지 않은 후보입니다.',code='selection_not_allowed')
    # P7 review R5: a stored 'pass' alone is not enough — re-verify right now that
    # the evidence it relied on hasn't since been revoked/unpublished, and still
    # actually applies to this exact product/variant (P3's real-time re-check, done
    # here with local DB reads only — no RAG/embedding call inside this transaction).
    for row in issues:
     if row['i'].get('status')!='pass': continue
     for ref in (row['i'].get('evidence_refs') or []):
      evidence_id=ref.get('evidence_id')
      if not evidence_id: continue
      ev=repo._one("SELECT status,facts FROM evidence.evidence WHERE id=%s",(evidence_id,))
      if ev is None or ev['status']!='active': raise ValidationFailed('안전 근거가 이후 철회되었습니다.',code='evidence_revoked')
      material_revision_id=(ev['facts'] or {}).get('material_revision_id')
      if not material_revision_id: continue
      if not material_repo.is_currently_published(UUID(material_revision_id)): raise ValidationFailed('안전 근거가 이후 철회되었습니다.',code='evidence_revoked')
      if not material_repo.has_current_applicability(UUID(material_revision_id),product_id=x['db_product_id'],variant_id=x['variant_id']): raise ValidationFailed('안전 근거의 적용 범위가 변경되었습니다.',code='evidence_not_applicable')
   amount=int(x['price'])*int(x['qty']); totals[x['timing']]+=amount; spec=(x['match_spec'] or {}).get('baby_requirement') or {}; snap={'version':3,'requirement_id':str(x['requirement_id']),'candidate_id':str(x['candidate_id']),'variant_id':str(x['variant_id']),'slot':x['slot'],'slot_label':x['slot_label'],'product_key':x['product_key'],'unit_price':int(x['price']),'qty':int(x['qty']),'unit_qty':float(x['unit_qty'] or 1),'unit_code':x['unit_code'],'timing':x['timing'],'observed_at':_iso(x['observed_at']),'validation':'pass' if r['category']=='baby' else 'not_applicable','evidence_refs':x['evidence_refs'] or [],'evidence_text':x['reason'] or '','product':{'product_key':x['product_key'],'variant_id':str(x['variant_id']),'name':x['product_name'],'image_url':x['image_url'],'purchase_url':x['purchase_url']}}; lines.append((x,amount,snap,spec))
  if budget_max is not None and totals['now']>budget_max: raise ValidationFailed('현재 구매 합계가 예산을 초과합니다.',code='over_budget')
  for x,a,s,_ in lines: repo._exec('INSERT INTO planning.purchase_line(revision_id,offer_id,selected_observation_id,pack_count,line_amount,currency,snapshot) VALUES(%s,%s,%s,%s,%s,%s,%s)',(r['id'],x['offer_id'],x['observation_id'],x['qty'],a,x['currency'],Jsonb(s)))
  repo._exec('UPDATE planning.plan SET name=%s,owner_user_id=%s,updated_at=now() WHERE id=%s',(name,p.user_id,lid)); updated=repo._one("UPDATE planning.plan_revision SET state='confirmed',name_snapshot=%s,planned_purchase_at=%s,target_amount=%s,memo=%s,confirmed_total=%s,confirmed_at=now(),updated_at=now() WHERE id=%s AND state='draft' RETURNING confirmed_at",(name,planned_purchase_at,target_amount,memo,totals['now'],r['id']))
  # P7 review R4: owned coverage comes from the full requirement set (dedup by
  # (requirement_id, source_condition_id)), not from purchase snapshots that never
  # carried an 'owned' key — a slot fulfilled entirely by ownership (no purchase at
  # all) must still show up here.
  owned_out=[]; seen=set()
  if r['category']=='baby':
   for req in load_persisted_baby_requirements(conn,r['id']):
    for o in req.owned:
     key=(req.id,o.get('source_condition_id'))
     if key in seen: continue
     seen.add(key); owned_out.append({**o,'requirement_id':req.id,'slot_key':req.slot_key})
  inputs=dict(run['input_snapshot'] or {}); inputs['baby_confirmation']={'version':3,'confirmed_at':_iso(updated['confirmed_at']),'name':name,'planned_purchase_at':_iso(planned_purchase_at),'target_amount':target_amount,'memo':memo,'conditions':[dict(z) for z in repo._all("SELECT condition_key,value,origin FROM planning.plan_condition WHERE revision_id=%s AND status='active'",(r['id'],))],'owned':owned_out,'totals':totals,'missing_requirements':[]}; repo._exec("UPDATE engine.recommendation_run SET input_snapshot=%s WHERE id=%s AND NOT(input_snapshot ? 'baby_confirmation')",(Jsonb(inputs),run['id'])); feedback_service.emit_confirmed(conn,plan_id=r['plan_id'],revision_id=r['id'],run_id=run['id'],version=r['lock_version'],user_id=p.user_id); return _report(repo,lid,p)
def get_report(conn,lid,p):
 if not p.user_id: raise Unauthorized('로그인이 필요합니다.')
 return _report(Repo(conn),lid,p)
def _price_watch_out(watch,confirmed_target):
 if watch is None: return {'enabled':False,'target_amount':confirmed_target,'status':'waiting','latest_total':None,'observed_at':None}
 status='reached' if watch['last_condition_state']=='reached' else('tracking' if watch['state']=='active' else 'waiting')
 return {'enabled':watch['state']=='active','target_amount':_int(watch['target_amount']),'status':status,'latest_total':None,'observed_at':None}
def set_alert(conn,lid,p,*,enabled,target_amount):
 """develop `da79839` 목표가 추적 생성/갱신 (P0 review R3 — 삭제됐던 경로 복원). 확정된
 목록에만 적용되며 유아 발송 신규 구현은 이 범위가 아니다(notification.price_watch 존재/
 상태 전환만 보존)."""
 if not p.user_id: raise Unauthorized('로그인이 필요합니다.')
 repo=Repo(conn); r=_owned(repo,lid,p,lock=True)
 if r['owner_user_id']!=p.user_id or r['state']!='confirmed': raise NotFound('확정된 목록을 찾을 수 없습니다.')
 nrepo=NotificationRepo(conn); existing=nrepo.get_for_revision(r['id']); confirmed_target=_int(r['target_amount'])
 if not enabled:
  if existing is not None and existing['state']=='active':
   nrepo.pause(existing['id']); existing=nrepo.get_for_revision(r['id'])
  return {'price_watch':_price_watch_out(existing,confirmed_target)}
 amount=target_amount
 if amount is None and existing is not None: amount=existing['target_amount']
 if amount is None: amount=r['target_amount']
 if amount is None: raise ValidationFailed('목표 금액을 입력해 주세요.',field='target_amount')
 ends_at=datetime.now(timezone.utc)+timedelta(days=_PRICE_WATCH_WINDOW_DAYS)
 watch=nrepo.upsert_active(r['id'],target_amount=amount,ends_at=ends_at)
 return {'price_watch':_price_watch_out(watch,confirmed_target)}
def list_conversations(conn,p):
 h=_guest_hash(p.browser_token); rows=Repo(conn)._all("""SELECT p.id list_id,p.name,p.updated_at,r.state,d.code category,EXISTS(SELECT 1 FROM engine.recommendation_run x WHERE x.revision_id=r.id AND x.status='completed') has_result FROM planning.plan p JOIN planning.plan_revision r ON r.id=p.current_revision_id JOIN identity.conversation c ON c.id=p.conversation_id JOIN config.domain_version dv ON dv.id=r.domain_version_id JOIN config.domain d ON d.id=dv.domain_id WHERE p.status='active' AND ((%s::uuid IS NOT NULL AND(p.owner_user_id=%s OR c.user_id=%s)) OR(%s::text IS NOT NULL AND c.guest_session_hash=%s)) ORDER BY p.updated_at DESC,p.id""",(p.user_id,p.user_id,p.user_id,h,h)); return [{'list_id':str(x['list_id']),'name':x['name'],'category':x['category'],'stage':'report' if x['state']=='confirmed' else ('results' if x['has_result'] else 'conditions'),'updated_at':_iso(x['updated_at'])} for x in rows]
def rename(conn,lid,p,*,name):
 repo=Repo(conn); r=_owned(repo,lid,p,lock=True); repo._exec('UPDATE planning.plan SET name=%s,updated_at=now() WHERE id=%s',(name,lid));
 if r['state']=='draft': repo._exec('UPDATE planning.plan_revision SET name_snapshot=%s,updated_at=now() WHERE id=%s',(name,r['id']))
 return next(x for x in list_conversations(conn,p) if x['list_id']==str(lid))
def delete(conn,lid,p):
 repo=Repo(conn); _owned(repo,lid,p,lock=True); repo._exec("UPDATE planning.plan SET status='deleted',deleted_at=now(),updated_at=now() WHERE id=%s",(lid,))
