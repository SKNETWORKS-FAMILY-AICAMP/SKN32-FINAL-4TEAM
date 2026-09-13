// TF-DEV: category.html 전용 화면. 카테고리 선택 동작(tfSetCategory/choose)은 core.js에 있다(푸터·랜딩과 공유).
// TF-DEV: 컴퓨터는 서버 조건 요약("구성 방식")이 build/upgrade 값을 요구하는데, 이걸 고를 화면이 없어서
// 항상 "아직 확인되지 않았어요"로 남아있었다. tfSetCategory가 mode 없이 컴퓨터를 고르려 하면 이 페이지의
// tfShowPcModeStep을 불러 여기서 먼저 고르게 한다(core.js 참고).
const TF_PC_MODES=[
 ['build','01','새 컴퓨터 조립','부품을 처음부터 골라 구성해요.'],
 ['upgrade','02','기존 컴퓨터 업그레이드','지금 쓰는 부품 중 바꿀 것만 골라요.'],
];
let tfPcModeFresh=false;
function categoryPage(){shell(heading('01 / FIND YOUR CATEGORY','어떤 장바구니를 만들까요?','필요한 카테고리를 선택하면, 그에 맞는 조건부터 함께 정리해요.')+`<div class="two">${[['pc','01','컴퓨터','게임, 작업, 일상에 맞는 한 대.','부품 호환성 · 전력 여유 · 예산 내 구성'],['baby','02','유아용품','우리 아이의 지금과 다음을 준비해요.','월령 · 필요한 품목 · 안전 확인 항목']].map(([c,n,t,p,h])=>`<button class="category-card" data-category-choice="${c}"><span class="num">${n} / ${c==='pc'?'COMPUTER':'BABY CARE'}</span><strong>${t} ↗</strong><p>${p}</p><span class="tag">${h}</span></button>`).join('')}</div>`,0)}
function categoryPcModePage(fresh=false){
 tfPcModeFresh=fresh;
 shell(heading('01 / FIND YOUR CATEGORY','새로 만들까요, 업그레이드할까요?','컴퓨터 구성 방식을 골라주세요. 이후 질문이 이 선택에 맞춰 달라져요.')+`<div class="two">${TF_PC_MODES.map(([m,n,t,p])=>`<button class="category-card" data-pc-mode-choice="${m}"><span class="num">${n} / ${m==='build'?'BUILD':'UPGRADE'}</span><strong>${t} ↗</strong><p>${p}</p></button>`).join('')}</div><div style="margin-top:28px"><button class="btn" type="button" data-pc-mode-back>← 카테고리 다시 선택</button></div>`,0);
}
// core.js의 tfSetCategory가 컴퓨터를 mode 없이 고르려 할 때 부른다.
function tfShowPcModeStep(fresh){categoryPcModePage(fresh)}
categoryPage();
flow.addEventListener('click',e=>{
 const back=e.target.closest('[data-pc-mode-back]');
 if(back){categoryPage();return}
 const modeChoice=e.target.closest('[data-pc-mode-choice]');
 if(modeChoice){tfSetCategory('pc',{fresh:tfPcModeFresh,mode:modeChoice.dataset.pcModeChoice});return}
 const b=e.target.closest('[data-category-choice]');
 if(!b)return;
 tfSetCategory(b.dataset.categoryChoice)
});
