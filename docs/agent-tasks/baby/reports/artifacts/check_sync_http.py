import json,time,urllib.request,urllib.error,http.cookiejar
from pathlib import Path
base='http://127.0.0.1:18000'
def client():return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def call(c,method,path,data=None):
    req=urllib.request.Request(base+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'},method=method)
    try:
        with c.open(req,timeout=15) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as e:return e.code,json.load(e)
r={};c=client()
r['health']=call(c,'GET','/health')
code,v=call(c,'POST','/session',{});r['baby_create_status']=code;bid=v['list_id']
r['baby_choose_status']=call(c,'POST',f'/session/{bid}/category',{'category':'baby'})[0]
r['baby_message']=call(c,'POST',f'/session/{bid}/message',{'text':'8개월 아기 수유 외출, 예산 30만원'})
for q,values in [('q_health_skin',['특이사항 없음']),('q_owned',['없음'])]:
    code,state=call(c,'POST',f'/session/{bid}/answer',{'question_id':q,'selected':values})
    assert code==200
r['baby_state']=call(c,'GET',f'/session/{bid}')
r['baby_recommend']=call(c,'POST',f'/session/{bid}/recommend',{})
r['other_guest_read_status']=call(client(),'GET',f'/session/{bid}')[0]
r['auth_login_status']=call(c,'POST','/auth/login',{'email':'demo@example.com','password':'Example123'})[0]
pc=client();code,v=call(pc,'POST','/session',{});pid=v['list_id']
assert call(pc,'POST',f'/session/{pid}/category',{'category':'computer'})[0]==200
call(pc,'POST',f'/session/{pid}/message',{'text':'게임 성능 위주 예산 150만원'})
r['pc_accept']=call(pc,'POST',f'/session/{pid}/recommend',{})
for _ in range(50):
    code,result=call(pc,'GET',f'/session/{pid}/result')
    if code==200 and result['status']!='running':break
    time.sleep(.2)
r['pc_result']={'http_status':code,'status':result.get('status'),'items':len(result.get('items',[])),'totals':result.get('totals'),'error':result.get('error')}
# Reproduce current known guest-token rotation limitation without affecting other data.
g=client();_,first=call(g,'POST','/session',{});call(g,'POST','/session',{})
r['same_browser_first_list_after_second_create_status']=call(g,'GET','/session/'+first['list_id'])[0]
Path('/tmp/truefit-sync-http.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in r.items() if k not in ('baby_message','baby_state')},ensure_ascii=False,indent=2))
print('baby_can_recommend',r['baby_state'][1].get('can_recommend'))
print('baby_fields',[(f['key'],f['value']) for f in r['baby_state'][1].get('fields',[])])
assert r['baby_create_status']==200 and r['baby_state'][0]==200 and r['baby_state'][1]['can_recommend']
assert r['baby_recommend'][0]==501
assert r['pc_accept'][0]==202 and r['pc_result']['status']=='done' and r['pc_result']['items']==8
