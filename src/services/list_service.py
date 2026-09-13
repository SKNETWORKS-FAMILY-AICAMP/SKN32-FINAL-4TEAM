"""Reduced schema list lifecycle: list, rename, delete, confirm and report."""
from __future__ import annotations
import hashlib
from datetime import date
from uuid import UUID
from psycopg.types.json import Jsonb
from src.auth.deps import Principal
from src.db.base import Repo
from src.errors import NotFound, Unauthorized, ValidationFailed

def _guest_hash(token: str | None) -> str | None: return hashlib.sha256(token.encode()).hexdigest() if token else None
def _iso(value): return value.isoformat() if value is not None else None
def _integer(value): return None if value is None else int(value)
def _owned(repo: Repo, list_id: UUID, principal: Principal, *, lock=False) -> dict:
 suffix=" FOR UPDATE OF p, r" if lock else ""
 row=repo._one("""SELECT p.id AS list_id,p.name AS list_name,p.owner_user_id,r.*,c.user_id AS conversation_user_id,c.guest_session_hash,d.code AS category FROM planning.plan p JOIN planning.plan_revision r ON r.id=p.current_revision_id JOIN identity.conversation c ON c.id=p.conversation_id JOIN config.domain d ON d.id=r.domain_id WHERE p.id=%s AND p.status='active'"""+suffix,(list_id,))
 if row is None: raise NotFound("장바구니를 찾을 수 없습니다.")
 if not ((principal.user_id is not None and (row["owner_user_id"]==principal.user_id or row["conversation_user_id"]==principal.user_id)) or (row["guest_session_hash"] is not None and row["guest_session_hash"]==_guest_hash(principal.browser_token))): raise NotFound("장바구니를 찾을 수 없습니다.")
 return row
def _report(repo: Repo,list_id: UUID,principal: Principal)->dict:
 r=_owned(repo,list_id,principal)
 if r["state"]!="confirmed": raise NotFound("확정된 리포트가 없습니다.")
 items=[]; links=[]
 for line in repo._all("SELECT qty AS pack_count,item_spec AS snapshot,price_observation FROM planning.item WHERE revision_id=%s AND selected AND status IN ('to_purchase','purchased') ORDER BY created_at,id",(r["id"],)):
  s=line["snapshot"] or {}; p=s.get("product") or {}; items.append({"slot":s.get("slot"),"slot_label":s.get("slot_label") or s.get("slot"),"product":p,"price":_integer(s.get("price",(line["price_observation"] or {}).get("unit_price", 0))) or 0,"qty":int(line["pack_count"]),"timing":s.get("timing","now"),"review":s.get("review"),"evidence_text":s.get("evidence_text","")})
  if p.get("purchase_url"): links.append({"name":p.get("name"),"purchase_url":p["purchase_url"]})
 owner=repo._one("SELECT display_name FROM identity.app_user WHERE id=%s",(r["owner_user_id"],))
 return {"list_id":str(list_id),"name":r["name_snapshot"],"category":r["category"],"owner_display_name":owner["display_name"] if owner else None,"planned_purchase_at":_iso(r["planned_purchase_at"]),"target_amount":_integer(r["target_amount"]),"memo":r["memo"] or "","total":_integer(r["confirmed_total"]) or 0,"confirmed_at":_iso(r["confirmed_at"]),"items":items,"buy_links":links}
def confirm(conn,list_id:UUID,principal:Principal,*,name:str,planned_purchase_at:date|None,target_amount:int|None,memo:str)->dict:
 if principal.user_id is None: raise Unauthorized("로그인이 필요합니다.")
 repo=Repo(conn); r=_owned(repo,list_id,principal,lock=True)
 if r["state"]=="confirmed": return _report(repo,list_id,principal)
 candidates=repo._all("""SELECT c.id AS candidate_id,c.reason,req.slot_key AS slot,req.slot_key AS slot_label,p.model AS product_key,p.name AS product_name,p.image_url,v.id AS variant_id,o.id AS offer_id,o.purchase_url,obs.id AS observation_id,obs.price FROM engine.recommendation_candidate c JOIN planning.requirement req ON req.id=c.requirement_id JOIN catalog.product_variant v ON v.id=c.variant_id JOIN catalog.product p ON p.id=v.product_id JOIN catalog.offer_observation obs ON obs.id=c.offer_observation_id JOIN catalog.offer o ON o.id=obs.offer_id WHERE c.run_id=(SELECT id FROM engine.recommendation_run WHERE revision_id=%s AND status='completed' ORDER BY completed_at DESC NULLS LAST,created_at DESC LIMIT 1) AND c.result='selected' AND obs.price IS NOT NULL ORDER BY req.position,c.created_at""",(r["id"],))
 if not candidates: raise ValidationFailed("선택된 품목이 없습니다.",code="no_items_selected")
 total=sum(int(x["price"]) for x in candidates); budget=repo._one("SELECT (value->>'value')::numeric AS amount FROM planning.plan_condition WHERE revision_id=%s AND condition_key='budget_max' AND status='active'",(r["id"],))
 if budget and budget["amount"] is not None and total>int(budget["amount"]): raise ValidationFailed("예산을 초과했습니다.",code="over_budget")
 for x in candidates:
  s={"candidate_id":str(x["candidate_id"]),"slot":x["slot"],"slot_label":x["slot_label"],"price":int(x["price"]),"timing":"now","review":None,"evidence_text":x["reason"] or "","product":{"product_key":x["product_key"],"variant_id":str(x["variant_id"]),"name":x["product_name"],"image_url":x["image_url"],"purchase_url":x["purchase_url"]}}
  repo._exec("INSERT INTO planning.item (revision_id,variant_id,offer_id,offer_observation_id,status,qty,selected,price_observation,item_spec) VALUES (%s,%s,%s,%s,'to_purchase',1,true,%s,%s)",(r["id"],x["variant_id"],x["offer_id"],x["observation_id"],Jsonb({"unit_price":int(x["price"]),"currency":"KRW"}),Jsonb(s)))
 repo._exec("UPDATE planning.plan SET name=%s,owner_user_id=%s,updated_at=now() WHERE id=%s",(name,principal.user_id,list_id)); repo._exec("UPDATE planning.plan_revision SET state='confirmed',name_snapshot=%s,planned_purchase_at=%s,target_amount=%s,memo=%s,confirmed_total=%s,confirmed_at=now(),updated_at=now() WHERE id=%s AND state='draft'",(name,planned_purchase_at,target_amount,memo,total,r["id"]))
 return _report(repo,list_id,principal)
def get_report(conn,list_id:UUID,principal:Principal)->dict:
 if principal.user_id is None: raise Unauthorized("로그인이 필요합니다.")
 return _report(Repo(conn),list_id,principal)
def list_conversations(conn,principal:Principal)->list[dict]:
 h=_guest_hash(principal.browser_token); rows=Repo(conn)._all("""SELECT p.id AS list_id,p.name,p.updated_at,r.state,d.code AS category,EXISTS(SELECT 1 FROM engine.recommendation_run run WHERE run.revision_id=r.id AND run.status='completed') AS has_result FROM planning.plan p JOIN planning.plan_revision r ON r.id=p.current_revision_id JOIN identity.conversation c ON c.id=p.conversation_id JOIN config.domain d ON d.id=r.domain_id WHERE p.status='active' AND ((%s::uuid IS NOT NULL AND (p.owner_user_id=%s OR c.user_id=%s)) OR (%s::text IS NOT NULL AND c.guest_session_hash=%s)) ORDER BY p.updated_at DESC,p.id""",(principal.user_id,principal.user_id,principal.user_id,h,h)); return [{"list_id":str(x["list_id"]),"name":x["name"],"category":x["category"],"stage":"report" if x["state"]=="confirmed" else ("results" if x["has_result"] else "conditions"),"updated_at":_iso(x["updated_at"])} for x in rows]
def rename(conn,list_id:UUID,principal:Principal,*,name:str)->dict:
 repo=Repo(conn); r=_owned(repo,list_id,principal,lock=True); repo._exec("UPDATE planning.plan SET name=%s,updated_at=now() WHERE id=%s",(name,list_id))
 if r["state"]=="draft": repo._exec("UPDATE planning.plan_revision SET name_snapshot=%s,updated_at=now() WHERE id=%s",(name,r["id"]))
 return next(x for x in list_conversations(conn,principal) if x["list_id"]==str(list_id))
def delete(conn,list_id:UUID,principal:Principal)->None:
 repo=Repo(conn); _owned(repo,list_id,principal,lock=True); repo._exec("UPDATE planning.plan SET status='deleted',deleted_at=now(),updated_at=now() WHERE id=%s",(list_id,))
