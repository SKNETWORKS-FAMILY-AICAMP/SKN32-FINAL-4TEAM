// TF-DEV: category.html 전용 화면. 카테고리 선택 동작(tfSetCategory/choose)은 core.js에 있다(푸터·랜딩과 공유).
function categoryPage(){shell(heading('01 / FIND YOUR CATEGORY','어떤 장바구니를 만들까요?','필요한 카테고리를 선택하면, 그에 맞는 조건부터 함께 정리해요.')+`<div class="two">${[['pc','01','컴퓨터','게임, 작업, 일상에 맞는 한 대.','부품 호환성 · 전력 여유 · 예산 내 구성'],['baby','02','유아용품','우리 아이의 지금과 다음을 준비해요.','월령 · 필요한 품목 · 안전 확인 항목']].map(([c,n,t,p,h])=>`<button class="category-card" data-category-choice="${c}"><span class="num">${n} / ${c==='pc'?'COMPUTER':'BABY CARE'}</span><strong>${t} ↗</strong><p>${p}</p><span class="tag">${h}</span></button>`).join('')}</div>`,0)}
categoryPage();
flow.addEventListener('click',e=>{const b=e.target.closest('[data-category-choice]');if(!b)return;tfSetCategory(b.dataset.categoryChoice)});
