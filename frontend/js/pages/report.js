function tfReportText(ko,en){return TF_LOCALE.isEnglish()?en:ko}
// TF-DEV: report.html 전용 — 리스트 리포트(05) 화면. 로그인 필요 — 서버 로그인 확인이 끝난 뒤 그린다.

// TF-DEV: 확정 리스트의 조립·설치 가이드 — report.care_guide(TextStatusOut)를 패널로 그린다.
// 필드 자체가 없는 구버전 리스트는 섹션을 숨긴다. 서버가 실제로 생성해 준 문장만 보여주고
// (가짜 데이터 금지), 리포트 인쇄(window.print())가 이 패널까지 그대로 PDF에 담아준다.
function tfCareGuideSection(guide) {
  if (!guide) return '';
  if (guide.status === 'ready') {
    const paragraphs = (guide.text || '')
      .split('\n')
      .filter(line => line.trim())
      .map(line => '<p>' + esc(line) + '</p>')
      .join('');
    return '<div class="panel"><h2>'+tfReportText('조립·설치 가이드','Assembly & setup guide')+'</h2>' + paragraphs + '</div>';
  }
  const message = guide.status === 'failed'
    ? tfReportText('가이드를 준비하지 못했어요.','Could not prepare the guide.')
    : tfReportText('가이드를 준비하는 중이에요…','Preparing the guide…');
  return '<div class="panel"><h2>'+tfReportText('조립·설치 가이드','Assembly & setup guide')+'</h2><p class="muted">' + esc(message) + '</p></div>';
}

function reportPage(){if(!tfPlan.listId)return go('category');const r=tfPlan.report;if(!r||r.list_id!==tfPlan.listId){tfLoadThen(reportPage,4,()=>TF_PLAN.report(tfPlan.listId).then(data=>{tfPlan.report=tfRequire(data)}).catch(err=>{if(err.status===404&&err.code==='not_found'){tfPlan.report={list_id:tfPlan.listId,status:'none'};return}if(err.code==='unauthorized'){TF_AUTH._set(null);tfSendToLogin('report.html');return}throw err}));return}
 if(r.status==='none'){shell(heading('05 / MY REPORT',tfReportText('저장된 리포트가 없어요.','No saved report.'))+`<div class="panel empty"><p>추천 리스트를 확정하면 구매 계획을 다시 볼 수 있어요.</p>${btn(tfReportText('추천 결과 보기','View recommendations'),'results','strong')}</div>`,4);return}
 const items=r.items||[];
 const rows=items.map(item=>'<tr><td class="report-photo-cell">'+partThumbnail(item.slot_label,item.product?.image_url)+'</td><td><strong>'+esc(item.slot_label)+'</strong><br>'+esc(item.product?.name)+(Number(item.qty)>1?' × '+Number(item.qty):'')+'<br><button class="report-product-link" type="button" data-plan-product-url="'+esc(item.product?.purchase_url||'')+'" aria-label="'+esc(item.product?.name)+' '+tfReportText('상품 페이지 열기','Open product page')+'">'+tfReportText('상품 페이지 ↗','Product page ↗')+'</button></td><td>'+won(Number(item.price||0)*Math.max(1,Number(item.qty)||1))+'</td><td><div class="report-review-metric">'+tfReviewMetric(item.review)+'</div></td><td>'+esc(item.evidence_text||'')+'</td></tr>').join('');
 shell(`<div class="report-banner"><div class="flow-logo" style="color:#e4dccf">PLAN SAVED / MY REPORT</div><h1 tabindex="-1">${esc(r.name)}</h1><p class="muted">${esc(r.owner_display_name||tfReportText('회원','Member'))} · ${tfReportText('구매 예정','Planned purchase')}: ${esc(r.planned_purchase_at)}</p><div class="row spread"><div><div class="muted">${tfReportText('예상 총액','Estimated total')}</div><div class="sum">${won(r.total)}</div></div><div><div class="muted">${tfReportText('목표 가격','Target price')}</div><div class="sum">${won(r.target_amount)}</div></div></div></div><div class="row no-print" style="margin-bottom:22px">${btn(tfReportText('리포트 인쇄 / PDF','Print report / PDF'),'print')}${btn(tfReportText('리스트 파일 저장','Download list'),'download')}${btn(tfReportText('추천 다시 보기','View recommendations again'),'results')}</div><div class="panel"><h2>${tfReportText('구매 리스트','Purchase list')}</h2><div class="table-wrap"><table class="report-product-table"><thead><tr><th>${tfReportText('제품 사진','Product image')}</th><th>${tfReportText('제품','Product')}</th><th>${tfReportText('가격','Price')}</th><th>${tfReportText('리뷰','Reviews')}</th><th>${tfReportText('추천 근거','Recommendation basis')}</th></tr></thead><tbody>${rows}</tbody><tfoot><tr><th colspan="2">${tfReportText('전체 가격','Total price')}</th><td colspan="3"><strong class="report-total-price">${won(r.total)}</strong></td></tr></tfoot></table></div><p class="muted">${esc(r.memo||tfReportText('추가 메모가 없습니다.','No additional notes.'))}</p></div>${tfCareGuideSection(r.care_guide)}<p class="muted">${r.confirmed_at?tfReportText('확정 시점 ','Confirmed on ')+esc(new Date(r.confirmed_at).toLocaleString(TF_LOCALE.get())):''}</p>`,4)}

// 로그인 필요 화면 — 서버에서 로그인 상태를 확인할 때까지 기다린 뒤 그리거나 로그인으로 보낸다.
shell(tfStatusPanel(tfReportText('로그인 상태를 확인하고 있어요…','Checking sign-in status…')),4);
TF_AUTH.ready.then(()=>{if(!readAuthSession()){toast(tfReportText('로그인 후 이용해 주세요.','Please sign in.'),true);tfSendToLogin('report.html');return}reportPage()});
