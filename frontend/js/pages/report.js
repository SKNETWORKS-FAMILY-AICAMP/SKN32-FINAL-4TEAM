// TF-DEV: report.html 전용 — 리스트 리포트(05) 화면. 로그인 필요 — 서버 로그인 확인이 끝난 뒤 그린다.

// TF-DEV: 확정 리스트의 조립·설치 가이드 — report.care_guide(TextStatusOut)를 패널로 그린다.
// 필드 자체가 없는 구버전 리스트는 섹션을 숨긴다. 서버가 실제로 생성해 준 문장만 보여주고
// (가짜 데이터 금지), 리포트 인쇄(window.print())가 이 패널까지 그대로 PDF에 담아준다.
function tfCareGuideSection(guide){
 if(!guide)return '';
 const english=tfIsEnglish(),title=english?'Assembly & setup guide':'조립·설치 가이드';
 if(guide.status==='ready'){
  const paragraphs=(guide.text||'').split('\n').filter(line=>line.trim()).map(line=>'<p>'+esc(line)+'</p>').join('');
  return '<div class="panel"><h2>'+title+'</h2>'+paragraphs+'</div>';
 }
 const message=guide.status==='failed'
  ?(english?'The guide could not be prepared.':'가이드를 준비하지 못했어요.')
  :(english?'Preparing the guide…':'가이드를 준비하는 중이에요…');
 return '<div class="panel"><h2>'+title+'</h2><p class="muted">'+esc(message)+'</p></div>';
}
function tfReportEvidence(item){
 const text=String(item.evidence_text||'');
 if(!tfIsEnglish()||!/[가-힣]/.test(text))return text;
 const name=item.product?.name||'This product',slot=tfSlotLabel(item.slot_label||item.slot)||'selected';
 return name+' was selected for the '+slot+' slot based on the recommendation conditions.';
}
function reportPage(){
 if(!tfPlan.listId)return go('category');
 const r=tfPlan.report;
 if(!r||r.list_id!==tfPlan.listId){
  tfLoadThen(reportPage,4,()=>TF_PLAN.report(tfPlan.listId).then(data=>{tfPlan.report=tfRequire(data)}).catch(err=>{if(err.status===404&&err.code==='not_found'){tfPlan.report={list_id:tfPlan.listId,status:'none'};return}if(err.code==='unauthorized'){TF_AUTH._set(null);tfSendToLogin('report.html');return}throw err}));
  return;
 }
 const english=tfIsEnglish();
 if(r.status==='none'){
  shell(heading('05 / MY REPORT',english?'No saved report.':'저장된 리포트가 없어요.')+'<div class="panel empty"><p>'+(english?'Confirm a recommendation list to review your purchase plan.':'추천 리스트를 확정하면 구매 계획을 다시 볼 수 있어요.')+'</p>'+btn(english?'View recommendations':'추천 결과 보기','results','strong')+'</div>',4);
  return;
 }
 const items=r.items||[];
 const rows=items.map(item=>{
  const name=esc(item.product?.name),slot=esc(tfSlotLabel(item.slot_label)),productPage=english?'Product page ↗':'상품 페이지 ↗';
  return '<tr><td class="report-photo-cell">'+partThumbnail(item.slot_label,item.product?.image_url)+'</td><td><strong>'+slot+'</strong><br>'+name+(Number(item.qty)>1?' × '+Number(item.qty):'')+'<br><button class="report-product-link" type="button" data-plan-product-url="'+esc(item.product?.purchase_url||'')+'" aria-label="'+(english?'Open '+name+' product page':name+' 상품 페이지 열기')+'">'+productPage+'</button></td><td>'+won(Number(item.price||0)*Math.max(1,Number(item.qty)||1))+'</td><td><div class="report-review-metric">'+tfReviewMetric(item.review)+'</div></td><td>'+esc(tfReportEvidence(item))+'</td></tr>';
 }).join('');
 const owner=r.owner_display_name||(english?'Member':'회원'),planLine=english?(esc(owner)+"'s plan · Planned purchase: "+esc(r.planned_purchase_at)):(esc(owner)+'님의 계획 · '+esc(r.planned_purchase_at)+' 구매 예정');
 const confirmed=r.confirmed_at?(english?'Confirmed '+esc(new Date(r.confirmed_at).toLocaleString('en-US')):'확정 시점 '+esc(new Date(r.confirmed_at).toLocaleString('ko-KR'))):'';
 shell('<div class="report-banner"><div class="flow-logo" style="color:#e4dccf">PLAN SAVED / MY REPORT</div><h1 tabindex="-1">'+esc(r.name)+'</h1><p class="muted">'+planLine+'</p><div class="row spread"><div><div class="muted">'+(english?'Estimated total':'예상 총액')+'</div><div class="sum">'+won(r.total)+'</div></div><div><div class="muted">'+(english?'Target price':'목표 가격')+'</div><div class="sum">'+won(r.target_amount)+'</div></div></div></div><div class="row no-print" style="margin-bottom:22px">'+btn(english?'Print report / PDF':'리포트 인쇄 / PDF','print')+btn(english?'Save list file':'리스트 파일 저장','download')+btn(english?'View recommendations again':'추천 다시 보기','results')+'</div><div class="panel"><h2>'+(english?'Purchase list':'구매 리스트')+'</h2><div class="table-wrap"><table class="report-product-table"><thead><tr><th>'+(english?'Product image':'제품 사진')+'</th><th>'+(english?'Product':'제품')+'</th><th>'+(english?'Price':'가격')+'</th><th>'+(english?'Reviews':'리뷰')+'</th><th>'+(english?'Recommendation basis':'추천 근거')+'</th></tr></thead><tbody>'+rows+'</tbody><tfoot><tr><th colspan="2">'+(english?'Total price':'전체 가격')+'</th><td colspan="3"><strong class="report-total-price">'+won(r.total)+'</strong></td></tr></tfoot></table></div><p class="muted">'+esc(r.memo||(english?'No additional notes.':'추가 메모가 없습니다.'))+'</p></div>'+tfCareGuideSection(r.care_guide)+'<p class="muted">'+confirmed+'</p>',4);
}

// 로그인 필요 화면 — 서버에서 로그인 상태를 확인할 때까지 기다린 뒤 그리거나 로그인으로 보낸다.
shell(tfStatusPanel(tfIsEnglish()?'Checking sign-in status…':'로그인 상태를 확인하고 있어요…'),4);
TF_AUTH.ready.then(()=>{if(!readAuthSession()){toast(tfIsEnglish()?'Please sign in to continue.':'로그인 후 이용해 주세요.',true);tfSendToLogin('report.html');return}reportPage()});
