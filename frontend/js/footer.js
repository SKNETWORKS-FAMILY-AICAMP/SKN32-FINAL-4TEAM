// TF-DEV: 모든 페이지의 <footer>(중복 삽입)가 공유하는 동작 — 안내 다이얼로그, 서비스 바로가기 드롭다운.
const footerDialog=document.querySelector('#footer-info-dialog');
const footerCopy={
 '이용약관':'정식 서비스 이용약관은 준비 중입니다. 현재 페이지는 서비스 흐름을 체험하는 목업이며, 실제 상품 판매나 결제는 진행되지 않습니다.',
 '개인정보 처리방침':'정식 개인정보 처리방침은 준비 중입니다. 이 목업의 표시 이름과 입력 조건, 리스트는 로그인 계정에는 서버에, 비로그인 상태에서는 이 브라우저에 임시로 저장됩니다. 브라우저 사이트 데이터를 삭제하면 비로그인 임시 저장 내용이 지워질 수 있습니다. 글꼴 로딩에는 Google Fonts 연결이 사용됩니다.',
 '제휴 문의':'제휴 문의 채널은 아직 등록되지 않았습니다. 정식 서비스 출시 시 안내할 예정입니다.',
 '고객센터':'고객지원 연락처와 운영시간은 준비 중입니다. 서비스 사용 방법은 하단의 자주 묻는 질문에서 확인할 수 있습니다.'
};
document.querySelectorAll('[data-footer-info]').forEach(b=>b.addEventListener('click',()=>{document.querySelector('#footer-info-title').textContent=b.dataset.footerInfo;document.querySelector('#footer-info-body').textContent=footerCopy[b.dataset.footerInfo];footerDialog.showModal()}));
document.querySelector('#footer-info-close').onclick=()=>footerDialog.close();
document.querySelector('#footer-service').addEventListener('change',e=>{const v=e.target.value;if(v==='pc'||v==='baby')choose(v);else if(v==='report')go(tfPlanRoute());e.target.value=''});
