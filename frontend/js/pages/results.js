// TF-DEV: results.html 전용. 리뷰·후보 비교 등 공용 조각은 js/planner-shell.js에 있다.
// TF-DEV: 03 결과 화면은 카테고리 공용 포맷(채팅 + 장바구니 카드 + 리뷰 슬라이드)을 쓴다.
// 카테고리마다 다른 건 TF_RESULT_CATEGORY_CONFIG의 슬롯 순서·문구뿐이고 나머지 렌더링·동작은
// 전부 공용이다 — 새 카테고리를 추가할 때도 이 표에 한 줄만 추가하면 된다. 유아용품(baby)은
// 추천 파이프라인이 아직 없어 실제로 확인은 못 했지만, 코드 구조는 그대로 탄다.
const TF_RESULT_CATEGORY_CONFIG={
 computer:{slotOrder:['CPU','GPU','RAM','메인보드','저장장치','파워','케이스','쿨러'],heading:'이 조합, 마음에 드세요?',composerPlaceholder:'예: 그래픽카드를 더 저렴한 걸로 바꿔줘'},
 baby:{slotOrder:['수유','수면','위생/기저귀','외출'],heading:'이 준비물, 마음에 드세요?',composerPlaceholder:'예: 기저귀를 더 저렴한 걸로 바꿔줘'},
};
function tfResultCategoryConfig(category){const config=TF_RESULT_CATEGORY_CONFIG[category]||TF_RESULT_CATEGORY_CONFIG.computer;if(!tfIsEnglish())return config;return {...config,heading:category==='baby'?'How does this list look?':'How does this build look?',composerPlaceholder:category==='baby'?'For example: choose cheaper diapers':'For example: make the graphics card cheaper'}}
const TF_CANDIDATE_LABEL_EN={'현재 선택':'Current selection','절약형 후보':'Value candidate','프리미엄 후보':'Premium candidate','동급 후보':'Equivalent candidate'};
function tfCandidateLabel(label){return tfIsEnglish()?(TF_CANDIDATE_LABEL_EN[label]||label||'Candidate'):(label||'후보')}
function tfCandidateSpec(summary){const value=String(summary||'');return tfIsEnglish()?value.replace(/^성능 티어\s*/, 'Performance tier '):value}
function tfResultLanguageNotice(result){
 const expected=window.TF_LOCALE?.get?.()||'ko-KR',actual=result?.content_language||'ko-KR';
 if(expected===actual)return '';
 if(expected==='en-US')return '<div class="demo-note result-language-note" role="status"><span>This recommendation was generated in Korean.</span><button class="btn" type="button" data-plan-rerun data-language-rerun>Recreate recommendation in English</button></div>';
 const generated=actual==='en-US'?'영어':'한국어',target=expected==='en-US'?'영어':'한국어';
 return '<div class="demo-note result-language-note" role="status"><span>이 추천은 '+generated+'로 생성되었습니다.</span><button class="btn" type="button" data-plan-rerun data-language-rerun>'+target+'로 추천 다시 만들기</button></div>';
}
// TF-DEV: 백엔드가 poll마다 items를 다른 순서로 돌려줄 때가 있어(정렬 보장 없음), 그대로 그리면
// 장바구니·채팅 목록이 가만히 있어도 저 혼자 뒤섞이는 것처럼 보인다. 카테고리별 슬롯 순서로
// 프론트에서 항상 같은 순서로 고정한다(슬롯 순서표에 없는 값은 원래 순서를 유지하며 맨 뒤로).
function tfSortResultItems(items,slotOrder){
 const rank=new Map((slotOrder||[]).map((s,i)=>[s,i]));
 return items.map((item,i)=>[item,i]).sort((a,b)=>{
  const ra=rank.has(a[0].slot_label)?rank.get(a[0].slot_label):Infinity,rb=rank.has(b[0].slot_label)?rank.get(b[0].slot_label):Infinity;
  return ra-rb||a[1]-b[1];
 }).map(pair=>pair[0]);
}
// 리뷰·근거 슬라이드가 열려 있는 동안은 tfSchedulePoll이 다시 그리지 않는다(planner-shell.js).
// 그래도 채팅 전송처럼 사용자가 직접 일으킨 다시 그리기에서는 보던 항목을 계속 보여주고 싶어서,
// 어떤 항목이 열려 있었는지 기억해뒀다가 다시 그린 뒤 즉시 복원한다.
let tfOpenReviewItemId=null;
function tfResultChatTurn(role,html){return '<div class="conversation-turn '+(role==='user'?'user':'')+'"><span class="conversation-label">'+(role==='user'?(tfIsEnglish()?'You':'나'):'TrueFit')+'</span><div class="conversation-bubble">'+html+'</div></div>'}
function tfResultSummaryHtml(result){
 const items=(result.items||[]).filter(item=>item.selected),totals=result.totals||{};
 const lines=items.map(item=>'<li>'+esc(tfSlotLabel(item.slot_label))+' · '+esc(item.product?.name)+' · <span class="figure">'+won(Number(item.price||0)*Math.max(1,Number(item.qty)||1))+'</span></li>').join('');
 const total=Number(totals.selected_price||0),budgetMax=result.budget_max;
 const pricey=[...items].sort((a,b)=>Number(b.price||0)-Number(a.price||0))[0];
 const english=window.TF_LOCALE?.isEnglish?.(),summaryPrompt=english?'Give me an overall assessment of this build':'이 구성 총평 알려줘';
 const chips=['<button class="chip-btn" type="button" data-fill="'+esc(summaryPrompt)+'">'+(english?'How does this build look overall?':'이 구성 총평은?')+'</button>'];
 if(pricey){const slotLabel=tfSlotLabel(pricey.slot_label),cheaperPrompt=english?'Make '+slotLabel+' cheaper':pricey.slot_label+' 더 저렴한 걸로 바꿔줘';chips.unshift('<button class="chip-btn" type="button" data-fill="'+esc(cheaperPrompt)+'">'+esc(slotLabel)+(english?' cheaper':' 더 저렴하게')+'</button>')}
 if(english){const budgetLine=budgetMax?' Of the '+won(budgetMax)+' budget, '+won(Math.max(0,budgetMax-total))+' remains.':'';return 'Built a '+items.length+'-part configuration to match your conditions.<ul>'+lines+'</ul>Total <span class="figure">'+won(total)+'</span>.'+budgetLine+' Tell me if you would like to replace any part.<div class="quick-replies">'+chips.join('')+'</div>'}
 const budgetLine=budgetMax?' 예산 '+won(budgetMax)+' 중 '+won(Math.max(0,budgetMax-total))+' 남아요.':'';
 return '조건에 맞춰 '+items.length+'개 부품으로 구성했어요.<ul>'+lines+'</ul>합계 <span class="figure">'+won(total)+'</span>·'+budgetLine+' 마음에 안 드는 부품이 있으면 편하게 말씀해 주세요.<div class="quick-replies">'+chips.join('')+'</div>';
}
function tfShowCartReviewSlide(itemId){
 const item=tfFindItem(itemId);if(!item)return;
 tfOpenReviewItemId=itemId;
 const slide=flow.querySelector('#tfCartReviewSlide'),scrim=flow.querySelector('[data-review-scrim]');if(!slide)return;
 const english=tfIsEnglish(),review=item.review;
 const scoreHtml=review?('<div class="score-row"><div class="score-tile"><div class="num">'+(review.rating_refined!=null?Number(review.rating_refined).toFixed(1):'—')+'</div><div class="lbl">'+(english?'Real-user rating':'실사용 평점')+'</div></div><div class="score-tile"><div class="num">'+Number(review.total_count||0).toLocaleString(english?'en-US':'ko-KR')+'</div><div class="lbl">'+(english?'All reviews':'전체 리뷰')+'</div></div><div class="score-tile"><div class="num">'+Math.round(Number(review.excluded_ratio||0)*100)+'%</div><div class="lbl">'+(english?'Suspected manipulation excluded':'조작 의심 제외')+'</div></div></div>'):'<p class="muted">'+(english?'No aggregated review data is available yet.':'아직 집계된 리뷰 데이터가 없어요.')+'</p>';
 const reasonText=tfLlmText(item.reason,english?'Generating the recommendation reason…':'추천 이유를 정리하는 중이에요…',english?'Could not generate the recommendation reason.':'추천 이유를 만들지 못했어요.');
 const checksText=tfLlmText(item.checks,english?'Generating checks…':'확인할 점을 정리하는 중이에요…',english?'Could not generate checks.':'확인할 점을 만들지 못했어요.');
 // TF-DEV: "구매 시점"은 유아용품처럼 월령에 맞춰 나중에 사도 되는 품목에만 의미가 있다.
 // 컴퓨터(PC)는 항상 바로 구매하는 조합이라 이 선택지가 불필요해 카테고리로 숨긴다.
 const isPc=tfUiCategory(tfPlan.result?.category)==='pc';
 const timingLabels=english?{now:'Now',soon:'Soon (1–3 months)',later:'Later'}:TF_TIMING_LABELS;
 const timingOptions=Object.entries(timingLabels).map(([value,label])=>'<option value="'+value+'" '+(item.timing===value?'selected':'')+'>'+label+'</option>').join('');
 const timingHtml=isPc?'':'<div class="review-timing"><label for="review-timing-select">'+(english?'Purchase timing':'구매 시점')+'</label><select id="review-timing-select" data-plan-timing="'+esc(item.item_id)+'">'+timingOptions+'</select></div>';
 slide.innerHTML='<div class="review-slide-head"><button type="button" class="review-slide-back" data-review-close aria-label="'+(english?'Return to basket':'장바구니로 돌아가기')+'">←</button><div><span class="condition-kicker">'+esc(tfSlotLabel(item.slot_label))+'</span><h3>'+esc(item.product?.name)+'</h3></div></div><div class="review-slide-body">'+scoreHtml+'<div class="evidence"><h4>'+(english?'Recommendation reason':'추천 이유')+'</h4><div class="evidence-card">'+esc(reasonText)+'</div><h4>'+(english?'Before purchasing':'구매 전 확인')+'</h4><div class="evidence-card">'+esc(checksText)+'</div></div>'+timingHtml+(item.alternatives_count?'<button class="btn wide" type="button" data-plan-alternatives="'+esc(item.item_id)+'">'+(english?'View alternatives →':'다른 후보 보기 →')+'</button>':'')+'</div><div class="review-slide-footer"><button type="button" class="review-buy-link" data-plan-product-url="'+esc(item.product?.purchase_url||'')+'">'+(english?'View on product page ↗':'상품 페이지에서 보기 ↗')+'</button></div>';
 slide.classList.add('open');scrim?.classList.add('open');
}
function tfCloseCartReviewSlide(){tfOpenReviewItemId=null;flow.querySelector('#tfCartReviewSlide')?.classList.remove('open');flow.querySelector('[data-review-scrim]')?.classList.remove('open')}
function resultsPage({preserve=false,scrollChat=false}={}){if(!tfPlan.listId)return go('category');const result=tfPlan.result;if(!result||result.list_id!==tfPlan.listId)return tfLoadResult(resultsPage,2);
 const english=tfIsEnglish();
 if(result.status==='none'){shell(heading('03 / YOUR BASKET',english?'No recommendation yet.':'아직 추천 결과가 없어요.')+'<div class="panel empty"><p>'+(english?'Complete the conditions conversation to receive recommendations.':'조건 대화를 마치고 추천을 받아 보세요.')+'</p>'+btn(english?'Enter conditions':'조건 입력하기','conditions','strong')+'</div>',2);return}
 if(result.status==='failed'){shell(heading('03 / YOUR BASKET',english?'Could not generate recommendations.':'추천을 만들지 못했어요.',esc(result.error?.message||(english?'Please try again shortly.':'잠시 후 다시 시도해 주세요.')))+'<div class="panel empty"><div class="row" style="justify-content:center"><button class="btn" data-action="conditions">'+(english?'← Edit conditions':'← 조건 수정')+'</button><button class="btn strong" type="button" data-plan-rerun="">'+(english?'Try again':'다시 추천받기')+'</button></div></div>',2);return}
 if(result.status==='running'){shell(heading('03 / YOUR BASKET',english?'Preparing recommendations.':'추천을 준비하고 있어요.',english?'Finding candidates and checking the configuration. Please wait.':'조건에 맞는 후보를 찾고 조합을 확인하는 중입니다. 잠시만 기다려 주세요.')+'<div class="panel"><div class="timeline">'+(result.progress||[]).map(step=>'<div><span class="tag '+(step.status==='done'?'':'gray')+'">'+(english?(step.status==='done'?'Done':step.status==='running'?'In progress':'Waiting'):(step.status==='done'?'완료':step.status==='running'?'진행 중':'대기'))+'</span><strong>'+esc(step.label)+'</strong></div>').join('')+'</div></div>',2);tfSchedulePoll(()=>resultsPage({preserve:true}));return}
 const scrollY=window.scrollY,chatInput=flow.querySelector('#tf-result-chat-input'),chatDraft=preserve&&chatInput?chatInput.value:'',chatFocused=preserve&&chatInput===document.activeElement;
 const config=tfResultCategoryConfig(result.category);
 const sortedResult={...result,items:tfSortResultItems(result.items||[],config.slotOrder)};
 const toolbarButtons='<button class="btn" data-action="conditions">'+(english?'← Edit conditions':'← 조건 수정')+'</button><button class="btn" data-action="logs">'+(english?'View recommendation process':'추천 과정 보기')+'</button><button class="btn" type="button" data-plan-rerun="alternative">'+(english?'View another build':'다른 구성 보기')+'</button>';
 const feed='<div class="conversation-feed">'+tfResultChatTurn('system',tfResultSummaryHtml(sortedResult))+tfPlan.resultMessages.map(m=>tfResultChatTurn(m.role,esc(m.text))).join('')+'</div>';
 const composer='<div class="conversation-current"><form id="tf-result-chat-form"><div class="chat-compose-grid no-file"><textarea id="tf-result-chat-input" name="message" rows="1" maxlength="300" aria-label="'+(english?'Ask about your recommendation':'추천 결과에 대해 물어보세요')+'" placeholder="'+esc(config.composerPlaceholder)+'" required></textarea><button class="btn strong" type="submit">'+(english?'Send →':'전송 →')+'</button></div><p id="tf-result-chat-error" class="error" role="alert"></p></form></div>';
 const body='<div class="result-toolbar"><div><span class="condition-kicker">03 / YOUR BASKET</span><h1 tabindex="-1">'+(english?'Review your recommended build.':'추천 구성을 확인해 보세요.')+'</h1><p class="muted">'+esc(result.conditions_summary||'')+'</p></div><div class="row">'+toolbarButtons+'</div></div>'+tfResultLanguageNotice(result)+(result.totals?.over_budget?'<div class="demo-note">'+(english?'The current build is over budget. Remove an item or select an alternative.':'현재 선택한 구성이 예산을 초과합니다. 품목을 빼거나 대체 후보를 선택해 주세요.')+'</div>':'')+tfResultInsights(result)+'<div class="result-board"><div class="result-board-main"><section class="condition-card conversation-card result-chat-panel"><h2>'+esc(config.heading)+'</h2>'+feed+composer+'</section></div>'+tfResultCart(sortedResult)+'</div>';
 shell(body,2);
 if(tfOpenReviewItemId&&tfFindItem(tfOpenReviewItemId))tfShowCartReviewSlide(tfOpenReviewItemId);
 if(preserve){
  if(scrollChat)flow.querySelector('.result-chat-panel .conversation-turn:last-child')?.scrollIntoView({behavior:'smooth',block:'end'});
  else window.scrollTo(0,scrollY);
  const input=flow.querySelector('#tf-result-chat-input');if(input&&chatDraft){input.value=chatDraft}if(input&&chatFocused)input.focus({preventScroll:true})
 }
 tfSchedulePoll(()=>resultsPage({preserve:true}))}
async function tfShowAlternatives(itemId){const item=tfFindItem(itemId);if(!item)return;const english=tfIsEnglish(),slot=tfSlotLabel(item.slot_label),head=tfOverlayHead('CHOOSE AN ALTERNATIVE',english?slot+' alternatives':item.slot_label+' 후보 비교');showResultOverlay(head+'<div class="result-overlay-body"><p class="muted">'+(english?'Loading alternatives…':'다른 후보를 불러오는 중이에요…')+'</p></div>');let data;try{data=tfRequire(await TF_PLAN.alternatives(tfPlan.listId,itemId))}catch(err){const body=flow.querySelector('.result-overlay .result-overlay-body');if(body)body.innerHTML='<p class="error">'+esc(tfAuthErrorMessage(err))+'</p>';return}const body=flow.querySelector('.result-overlay .result-overlay-body');if(!body)return;const cards=(data.items||[]).map(candidate=>'<button type="button" class="candidate-card '+(candidate.current?'current':'')+'" '+(candidate.current?'data-overlay-close':'data-plan-swap-item="'+esc(itemId)+'" data-plan-swap-candidate="'+esc(candidate.candidate_id)+'"')+'><span class="tag">'+esc(tfCandidateLabel(candidate.label))+(candidate.current?(english?' · Currently selected':' · 현재 선택'):'')+'</span><span class="candidate-name">'+esc(candidate.product?.name)+'</span><span class="candidate-spec">'+esc(tfCandidateSpec(candidate.product?.spec_summary))+'</span><span class="candidate-price">'+won(candidate.price)+'</span>'+(candidate.price_delta?'<span class="muted">'+(english?'Compared with current ':'현재 대비 ')+(candidate.price_delta>0?'+':'−')+won(Math.abs(candidate.price_delta))+'</span>':'')+'<span class="candidate-action">'+(candidate.current?(english?'Keep current candidate':'현재 후보 유지'):(english?'Switch to this candidate':'이 후보로 교체'))+' →</span></button>').join('');body.innerHTML=cards?'<p class="muted">'+(english?'Compare prices and specifications, then choose one.':'가격과 규격을 비교해 하나를 선택하세요.')+'</p><div class="candidate-grid">'+cards+'</div><p id="tf-swap-error" class="error" role="alert"></p>':'<p class="muted">'+(english?'No alternative candidates are available.':'바꿀 수 있는 다른 후보가 없어요.')+'</p>'}
function applyAndRerender(data){tfApplyResult(data,()=>resultsPage({preserve:true}))}
resultsPage();
flow.addEventListener('click',e=>{
 const reviewSlide=e.target.closest('[data-plan-review-slide]');if(reviewSlide){e.preventDefault();tfShowCartReviewSlide(reviewSlide.dataset.planReviewSlide);return}
 if(e.target.closest('[data-review-close]')||e.target.closest('[data-review-scrim]')){tfCloseCartReviewSlide();return}
 const chip=e.target.closest('[data-fill]');if(chip){const input=flow.querySelector('#tf-result-chat-input');if(input){input.value=chip.dataset.fill;input.closest('form')?.requestSubmit()}return}
 const alternatives=e.target.closest('[data-plan-alternatives]');if(alternatives){e.preventDefault();tfShowAlternatives(alternatives.dataset.planAlternatives);return}
 const remove=e.target.closest('[data-plan-remove]');if(remove){tfResultAction(listId=>TF_PLAN.updateItem(listId,remove.dataset.planRemove,{selected:false})).then(applyAndRerender);return}
 const qty=e.target.closest('[data-plan-qty]');if(qty){const item=tfFindItem(qty.dataset.planItem);if(item){const nextQty=Math.max(1,Math.min(99,(Number(item.qty)||1)+Number(qty.dataset.planQty)));tfResultAction(listId=>TF_PLAN.updateItem(listId,item.item_id,{qty:nextQty})).then(applyAndRerender)}return}
 const swap=e.target.closest('[data-plan-swap-candidate]');if(swap){const itemId=swap.dataset.planSwapItem;tfResultAction(listId=>TF_PLAN.swap(listId,itemId,swap.dataset.planSwapCandidate),{errorTarget:'#tf-swap-error'}).then(data=>{if(data){closeResultOverlay();applyAndRerender(data);toast(tfIsEnglish()?'Switched to the selected candidate.':'선택한 후보로 바꿨어요.')}});return}
 const rerun=e.target.closest('[data-plan-rerun]');if(rerun){tfStartRecommend(rerun,rerun.dataset.planRerun||undefined);return}
});
flow.addEventListener('change',e=>{
 const timing=e.target.closest('[data-plan-timing]');if(timing){tfResultAction(listId=>TF_PLAN.updateItem(listId,timing.dataset.planTiming,{timing:timing.value})).then(data=>data?applyAndRerender(data):resultsPage({preserve:true}))}
});
flow.addEventListener('submit',e=>{if(e.target.id!=='tf-result-chat-form')return;e.preventDefault();const input=e.target.querySelector('#tf-result-chat-input'),text=String(input?.value||'').trim(),button=e.target.querySelector('button[type=submit]');if(!text)return;tfBusy(button,true,tfIsEnglish()?'Sending…':'보내는 중…');tfResultAction(listId=>TF_PLAN.resultMessage(listId,text),{errorTarget:'#tf-result-chat-error'}).then(data=>{if(!data){tfBusy(button,false);return}tfPlan.resultMessages.push({role:'user',text},{role:'system',text:data.reply||''});tfApplyResult(data.result,()=>resultsPage({preserve:true,scrollChat:true}))})});
// TF-DEV: textarea는 Enter=전송(개행 없음), Shift+Enter=줄바꿈. 입력에 따라 높이도 늘어난다(최대 168px, 그 이상은 내부 스크롤).
flow.addEventListener('keydown',e=>{if(e.target.id==='tf-result-chat-input'&&e.key==='Enter'&&!e.shiftKey){e.preventDefault();e.target.closest('form')?.requestSubmit()}});
flow.addEventListener('input',e=>{if(e.target.id==='tf-result-chat-input'){e.target.style.height='auto';e.target.style.height=Math.min(e.target.scrollHeight,168)+'px'}});
document.addEventListener('keydown',e=>{if(e.key==='Escape')tfCloseCartReviewSlide()});

// TF-DEV: tfStartRecommend()는 조건 대화 화면(conditions.js)에도 있는 소스와 동일 — "다른 구성 보기" 버튼용으로 이 페이지에도 둔다.
async function tfStartRecommend(button,strategy){if(tfPlan.busy)return;const listId=tfPlan.listId;tfPlan.busy=true;tfBusy(button,true,tfIsEnglish()?'Recalculating…':'다시 계산하는 중…');try{await TF_PLAN.recommend(listId,strategy);if(listId!==tfPlan.listId)return;tfPlan.result=null;tfPlan.resultMessages=[];tfPlan.pollAttempts=0;resultsPage()}catch(err){tfBusy(button,false);if(tfListGone(err))return;if(err.code==='run_in_progress'){resultsPage();return}toast(tfAuthErrorMessage(err))}finally{tfPlan.busy=false}}
