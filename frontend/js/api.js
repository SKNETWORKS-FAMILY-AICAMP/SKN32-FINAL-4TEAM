// TF-DEV: 서버 API 공통 호출 — 계약: docs/frontend_외부수정요청.md §A-4, §D-4
// TF-DEV: ?api=http://host:port 로 한 번 열면 이후 페이지 이동에도(멀티페이지라 매번 쿼리스트링을 못 붙임) 같은 브라우저 탭에서 유지된다. 지우려면 sessionStorage의 truefit-api-override를 비우면 됨.
const TF_API_BASE=(()=>{const params=new URLSearchParams(location.search),queryOverride=params.get('api');if(queryOverride){try{sessionStorage.setItem('truefit-api-override',queryOverride)}catch{}}let override=queryOverride;if(!override)try{override=sessionStorage.getItem('truefit-api-override')||''}catch{}if(override)return override.replace(/\/+$/,'');const value=(document.querySelector('meta[name="truefit-api-base"]')?.content||'auto').trim();if(value!=='auto')return value.replace(/\/+$/,'');return location.port==='5500'?location.protocol+'//'+location.hostname+':8000':''})();
class TF_ApiError extends Error{constructor(status,code,message,field=null){super(message);this.name='TF_ApiError';this.status=status;this.code=code;this.field=field}}
const TF_API={
 async request(method,path,body){
  const headers={Accept:'application/json'};if(body!==undefined)headers['Content-Type']='application/json';
  let response;
  try{response=await fetch(TF_API_BASE+path,{method,credentials:'include',headers,body:body===undefined?undefined:JSON.stringify(body)})}catch{throw new TF_ApiError(0,'network_error','서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.')}
  if(response.status===204)return null;
  let data=null;try{data=await response.json()}catch{}
  if(response.ok)return data;
  const envelope=data&&data.error;
  if(envelope&&envelope.code&&envelope.code!=='not_implemented')throw new TF_ApiError(response.status,envelope.code,envelope.message||'요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.',envelope.field||null);
  if(response.status===501||response.status===404||response.status===405)throw new TF_ApiError(response.status,'not_ready','서버 기능이 아직 준비 중이에요.');
  if(response.status===422)throw new TF_ApiError(422,'validation_failed','입력값을 다시 확인해 주세요.');
  if(response.status===401)throw new TF_ApiError(401,'unauthorized','로그인이 필요합니다.');
  throw new TF_ApiError(response.status,'server_error','요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.')
 },
 get(path){return this.request('GET',path)},
 post(path,body={}){return this.request('POST',path,body)},
 patch(path,body={}){return this.request('PATCH',path,body)},
 del(path){return this.request('DELETE',path)}
};
// TF-DEV: 인증 어댑터 — 로그인 상태는 서버 httpOnly 쿠키로만 판단하고 화면은 TF_AUTH.user만 본다
const TF_AUTH={
 user:null,loaded:false,ready:null,
 _set(user){this.user=user?{id:user.id,email:user.email,name:user.display_name,marketing:!!user.marketing_agreed,createdAt:user.created_at}:null;this.loaded=true;if(typeof renderAccountHeader==='function')renderAccountHeader();if(typeof tfOnAuthChange==='function')tfOnAuthChange();return this.user},
 async refresh(){try{const data=await TF_API.get('/auth/me');return this._set(data&&data.user)}catch(error){return this._set(null)}},
 me(){return this.refresh()},
 async signup({email,password,displayName,termsAgreed,privacyAgreed,marketingAgreed}){const data=await TF_API.post('/auth/signup',{email,password,display_name:displayName,terms_agreed:!!termsAgreed,privacy_agreed:!!privacyAgreed,marketing_agreed:!!marketingAgreed});return this._set(data&&data.user)},
 async login({email,password,remember}){const data=await TF_API.post('/auth/login',{email,password,remember:!!remember});return this._set(data&&data.user)},
 async logout(){await TF_API.post('/auth/logout');this._set(null)},
 async updateProfile({displayName,email,marketingAgreed}){const body={};if(displayName!==undefined)body.display_name=displayName;if(email!==undefined)body.email=email;if(marketingAgreed!==undefined)body.marketing_agreed=!!marketingAgreed;const data=await TF_API.patch('/auth/me',body);return this._set(data&&data.user)},
 async changePassword({currentPassword,newPassword}){await TF_API.post('/auth/password',{current_password:currentPassword,new_password:newPassword})},
 async withdraw({password}){await TF_API.post('/auth/withdraw',{password});this._set(null)},
 async checkEmail(email){const data=await TF_API.get('/auth/email-availability?email='+encodeURIComponent(email));return !!(data&&data.available)}
};
function tfAuthErrorMessage(error,fallback){return ({invalid_credentials:'이메일 또는 비밀번호가 올바르지 않습니다.',account_locked:'로그인 시도가 여러 번 실패해 잠시 잠겼어요. 15분 후 다시 시도해 주세요.',email_taken:'이미 가입된 이메일입니다.',weak_password:'비밀번호는 영문과 숫자를 포함해 8자 이상이어야 합니다.',terms_required:'필수 약관에 동의해 주세요.',invalid_password:'현재 비밀번호가 일치하지 않습니다.',rate_limited:'요청이 많아요. 잠시 후 다시 시도해 주세요.',unauthorized:'로그인이 필요합니다.'})[error&&error.code]||(error&&error.message)||fallback||'요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.'}
function tfBusy(button,busy,label){if(!button)return;if(busy){if(!button.dataset.idleLabel)button.dataset.idleLabel=button.textContent;button.disabled=true;button.textContent=label||'처리 중…'}else{button.disabled=false;if(button.dataset.idleLabel)button.textContent=button.dataset.idleLabel;delete button.dataset.idleLabel}}
