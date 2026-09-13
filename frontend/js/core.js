// TF-DEV: 모든 페이지 공통 유틸 + 장바구니 상태(tfPlan) — 계약: docs/frontend_외부수정요청.md §A-4, §D-4
// 멀티페이지 구조: 화면 이동은 실제 페이지 이동(location.href)이다. 브라우저에는
// "지금 열어 둔 장바구니 ID"와 사이드바 접힘 상태만 저장하고, 나머지는 페이지를 열 때마다 서버에서 다시 받는다.
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const won=n=>Math.round(n).toLocaleString('ko-KR')+'원';
const money=n=>Number.isFinite(Number(n))?Number(n):0;
const flow=document.getElementById('flow'); // 랜딩 페이지(index.html)에는 없음 — null

const TF_ACTIVE_LIST_KEY='truefit-active-list';
const SIDEBAR_STORE='planbasket-sidebar-collapsed';
// TF-DEV: 페이지별 파일명 매핑 — 화면 로직은 예전과 같은 라우트 이름('conditions' 등)을 쓰고, 실제 이동만 이 표로 변환한다.
const TF_ROUTES={'':'index.html',category:'category.html',conditions:'conditions.html',results:'results.html',logs:'logs.html',confirm:'confirm.html',report:'report.html',login:'login.html',signup:'signup.html',account:'account.html'};
function tfHref(route){return TF_ROUTES[route]||'index.html'}
function go(route){location.href=tfHref(route)}

const tfPlan={listId:null,condition:null,result:null,report:null,lists:null,listsLoaded:false,listsLoading:false,listsError:null,resultMessages:[],pollTimer:null,seq:0,busy:false};
try{tfPlan.listId=localStorage.getItem(TF_ACTIVE_LIST_KEY)||null;localStorage.removeItem('planbasket-demo-v1')}catch{}

const tfSeg=value=>encodeURIComponent(String(value));
const TF_PLAN={
 createSession(){return TF_API.post('/session')},
 condition(id){return TF_API.get('/session/'+tfSeg(id))},
 chooseCategory(id,category){return TF_API.post('/session/'+tfSeg(id)+'/category',{category})},
 message(id,text){return TF_API.post('/session/'+tfSeg(id)+'/message',{text})},
 answer(id,questionId,selected){return TF_API.post('/session/'+tfSeg(id)+'/answer',{question_id:questionId,selected})},
 clearSlot(id,field){return TF_API.patch('/session/'+tfSeg(id)+'/slot',{field,value:null})},
 reset(id){return TF_API.post('/session/'+tfSeg(id)+'/reset')},
 specFile(id,fileName,content){return TF_API.post('/session/'+tfSeg(id)+'/spec-file',{file_name:fileName,content})},
 recommend(id,strategy){return TF_API.post('/session/'+tfSeg(id)+'/recommend',strategy?{strategy}:{})},
 result(id){return TF_API.get('/session/'+tfSeg(id)+'/result')},
 updateItem(id,itemId,changes){return TF_API.patch('/session/'+tfSeg(id)+'/items/'+tfSeg(itemId),changes)},
 alternatives(id,itemId){return TF_API.get('/session/'+tfSeg(id)+'/items/'+tfSeg(itemId)+'/alternatives')},
 swap(id,itemId,candidateId){return TF_API.post('/session/'+tfSeg(id)+'/items/'+tfSeg(itemId)+'/swap',{candidate_id:candidateId})},
 resultMessage(id,text){return TF_API.post('/session/'+tfSeg(id)+'/result-message',{text})},
 reviewSummary(productKey){return TF_API.get('/reviews/summary/'+tfSeg(productKey))},
 lists(){return TF_API.get('/lists')},
 renameList(id,name){return TF_API.patch('/lists/'+tfSeg(id),{name})},
 deleteList(id){return TF_API.del('/lists/'+tfSeg(id))},
 confirm(id,body){return TF_API.post('/lists/'+tfSeg(id)+'/confirm',body)},
 report(id){return TF_API.get('/lists/'+tfSeg(id)+'/report')},
 alert(id,body){return TF_API.post('/lists/'+tfSeg(id)+'/alert',body)}
};
function tfUiCategory(category){return category==='computer'?'pc':category||''}
function tfApiCategory(category){return category==='pc'?'computer':category}
function tfListSummary(id=tfPlan.listId){return (tfPlan.lists||[]).find(item=>item.list_id===id)||null}
function tfStageRoute(stage){return ['category','conditions','results','report'].includes(stage)?stage:'conditions'}
function tfPlanRoute(){const summary=tfListSummary();if(!tfPlan.listId)return 'category';if(tfPlan.report||summary?.stage==='report')return 'report';if(tfPlan.result||summary?.stage==='results')return 'results';if(tfPlan.condition?.category||summary?.category)return 'conditions';return 'category'}
function tfSelectList(id){tfStopPoll();tfPlan.listId=id||null;tfPlan.condition=null;tfPlan.result=null;tfPlan.report=null;tfPlan.resultMessages=[];try{id?localStorage.setItem(TF_ACTIVE_LIST_KEY,id):localStorage.removeItem(TF_ACTIVE_LIST_KEY)}catch{}}
// TF-DEV: "대화 다시 시작" 이후에도 서버는 실제 대화 기록을 계속 보관한다(질문·답변은 그대로 남고 조건 값만 비움).
// 새로고침해도 화면이 다시 "처음부터"로 보이도록, 리셋 시점의 메시지 개수와 그때 다시 물은 질문 문구를 저장해두고
// 그 이전 메시지는 화면에서만 가린다(서버 데이터를 지우지 않음). 질문 문구를 같이 고정해야 이후 답변이 쌓여도
// 재시작 안내 문구가 "현재" 질문으로 계속 바뀌지 않고 리셋 당시 질문("주로 어떤 용도로...") 그대로 유지된다.
const TF_RESET_MARK_KEY='truefit-condition-reset';
function tfResetMarks(){try{return JSON.parse(localStorage.getItem(TF_RESET_MARK_KEY)||'{}')}catch{return {}}}
function tfResetMark(listId){return tfResetMarks()[listId]||null}
function tfSetResetMark(listId,count,text){try{const marks=tfResetMarks();marks[listId]={count,text};localStorage.setItem(TF_RESET_MARK_KEY,JSON.stringify(marks))}catch{}}
function tfClearResetMark(listId){try{const marks=tfResetMarks();delete marks[listId];localStorage.setItem(TF_RESET_MARK_KEY,JSON.stringify(marks))}catch{}}
function tfOnAuthChange(){tfPlan.lists=null;tfPlan.listsLoaded=false;tfPlan.report=null}
function tfListGone(err){if(err&&err.status===404&&err.code==='not_found'){tfSelectList(null);tfPlan.listsLoaded=false;toast('장바구니를 찾을 수 없어 새로 시작합니다.');go('category');return true}return false}
function tfStopPoll(){clearTimeout(tfPlan.pollTimer);tfPlan.pollTimer=null}
function toast(t,centered=false){let el=$('.toast');if(el)el.remove();el=document.createElement('div');el.className='toast'+(centered?' toast-center':'');el.setAttribute('role','status');el.textContent=t;document.body.append(el);setTimeout(()=>el.remove(),3500)}
function btn(t,a,cl=''){return `<button class="btn ${cl}" data-action="${a}">${t}</button>`}
function heading(k,t,p=''){return `<div class="flow-head"><div class="flow-logo">${k}</div><h1 tabindex="-1">${t}</h1>${p?`<p class="muted">${p}</p>`:''}</div>`}
function field(label,name,type,value,extra=''){return `<label for="f-${name}">${label}</label><input id="f-${name}" name="${name}" type="${type}" value="${esc(value)}" ${extra}>`}
function tfRequire(data){if(!data||typeof data!=='object')throw new TF_ApiError(0,'bad_response','서버 응답이 올바르지 않아요.');return data}
function tfStatusPanel(title,message='',actions=''){return `<div class="panel empty"><h2>${esc(title)}</h2>${message?`<p class="muted">${esc(message)}</p>`:''}${actions}</div>`}
function readAuthSession(){return TF_AUTH.user}
// TF-DEV: 서버 로그인 상태 확인 — 모든 페이지에서 한 번 실행. 결과가 필요한 페이지는 TF_AUTH.ready.then(...)으로 이어 붙인다.
TF_AUTH.ready=TF_AUTH.refresh();
// TF-DEV: 카테고리 선택은 index.html 퀵스타트 카드·category.html·푸터 바로가기 모두에서 쓰여 core.js에 둔다.
async function tfSetCategory(c,{fresh=false}={}){if(tfPlan.busy)return;const category=tfApiCategory(c);tfPlan.busy=true;try{let known=tfPlan.condition?.category||tfListSummary()?.category||null;if(!fresh&&tfPlan.listId&&known==null){try{known=tfRequire(await TF_PLAN.condition(tfPlan.listId)).category||null}catch(err){if(tfListGone(err))return;known=null}}if(!fresh&&tfPlan.listId&&known===category){go('conditions');return}if(!fresh&&tfPlan.listId&&known&&known!==category){if(!window.confirm('다른 카테고리를 선택하면 새 장바구니를 만들어요. 지금 대화는 사이드바에 그대로 남아요. 계속할까요?'))return;fresh=true}if(fresh||!tfPlan.listId){const created=tfRequire(await TF_PLAN.createSession());tfSelectList(created.list_id)}const state=tfRequire(await TF_PLAN.chooseCategory(tfPlan.listId,category));tfPlan.condition=state;tfPlan.result=null;tfPlan.report=null;tfPlan.resultMessages=[];tfPlan.listsLoaded=false;go('conditions')}catch(err){if(!tfListGone(err))toast(tfAuthErrorMessage(err))}finally{tfPlan.busy=false}}
function choose(c){return tfSetCategory(c,{fresh:true})}
// TF-DEV: 로그인 필요 화면(account/confirm/report)과 로그아웃 버튼(사이드바·헤더·회원정보)이 공유 — core.js에 둔다.
function tfSendToLogin(returnPage){try{sessionStorage.setItem('truefit-login-return',returnPage)}catch{}go('login')}
async function tfLogout(){try{await TF_AUTH.logout();toast('로그아웃되었습니다.');return true}catch(error){toast(tfAuthErrorMessage(error,'로그아웃하지 못했어요.'));return false}}
