// TF-DEV: index.html 전용 — 히어로 배경 전환, 소개 섹션 등장 애니메이션, 계정 헤더, 카테고리 퀵스타트.
const scene=$('.visual'),secondScene=$('.scene-secondary'),motionPreference=window.matchMedia('(prefers-reduced-motion: reduce)');let sceneTimer;
function startSceneRotation(){clearInterval(sceneTimer);if(motionPreference.matches){scene.classList.remove('show-second');return}sceneTimer=setInterval(()=>{if(!document.hidden)scene.classList.toggle('show-second')},2500)}
if(secondScene.complete&&secondScene.naturalWidth)startSceneRotation();else secondScene.addEventListener('load',startSceneRotation,{once:true});motionPreference.addEventListener('change',startSceneRotation);
document.querySelectorAll('[data-start]').forEach(b=>b.onclick=()=>go('category'));
document.querySelectorAll('[data-category]').forEach(b=>b.onclick=e=>{e.preventDefault();choose(b.dataset.category==='컴퓨터'?'pc':'baby')});

function bindAuthButtons(){document.querySelectorAll('[data-auth]').forEach(b=>b.onclick=()=>{if(b.dataset.auth==='회원가입'){go('signup');return}go('login')})}
function renderAccountHeader(){const nav=$('.account-nav');if(!nav)return;const session=readAuthSession();if(!session){nav.innerHTML='<button type="button" data-auth="로그인">로그인</button><button type="button" data-auth="회원가입">회원가입</button>';bindAuthButtons();return}nav.innerHTML='<span class="account-user-name">'+esc(session.name||'회원')+'님</span><div class="service-menu mypage-menu"><button type="button" class="service-trigger" aria-haspopup="true">마이페이지</button><div class="service-dropdown" aria-label="마이페이지 메뉴"><a href="'+tfHref(tfPlanRoute())+'" data-account-basket>장바구니</a><a href="account.html">회원정보 수정</a><a href="#" data-account-logout>로그아웃</a></div></div>';nav.querySelector('[data-account-logout]').onclick=async e=>{e.preventDefault();if(await tfLogout())location.reload()}}
renderAccountHeader(); // 즉시 1차 표시(비로그인 가정); TF_AUTH.ready 완료 시 api.js가 다시 호출해 갱신한다.
$('.brand').href='index.html';

// Reveal once when each column enters the viewport; preserve readable fallback.
const revealTargets=[...document.querySelectorAll('.about-category-grid > .about-category')];
const principles=document.querySelector('.about-principles');
if(principles)revealTargets.push(...principles.parentElement.children);
if('IntersectionObserver' in window && !motionPreference.matches){
 const revealObserver=new IntersectionObserver(entries=>{entries.forEach(entry=>{
  if(entry.isIntersecting){entry.target.classList.remove('reveal-wait');revealObserver.unobserve(entry.target);}
 });},{threshold:.12});
 revealTargets.forEach((el,i)=>{el.style.setProperty('--reveal-x',i%2===0?'-55px':'55px');el.classList.add('reveal-side','reveal-wait');revealObserver.observe(el);});
 motionPreference.addEventListener('change',e=>{if(e.matches){revealTargets.forEach(el=>el.classList.remove('reveal-wait'));revealObserver.disconnect();}});
}
