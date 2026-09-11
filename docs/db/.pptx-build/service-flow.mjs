import fs from 'node:fs/promises';
import { Presentation, PresentationFile, FileBlob } from '@oai/artifact-tool';
import { finalizePresentation } from 'file:///C:/Users/playdata2/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations/container_tools/artifact_tool_utils.mjs';
const root='C:/project_workspace/TrueFit';
const build=root+'/docs/db/.pptx-build';
const out=root+'/docs/service-flow';
const skill='C:/Users/playdata2/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations';
await fs.mkdir(out,{recursive:true});
const p=Presentation.create({slideSize:{width:1920,height:1080}});
const C={ink:'#183846',muted:'#5d7080',blue:'#e9f1f6',line:'#91a8b6',green:'#e5f1ea',orange:'#fff1df',bg:'#fafcfd',accent:'#176878'};
function text(s,x,y,w,h,t,size=27,bold=false,color=C.ink,align='left'){
 const z=s.shapes.add({name:t,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 z.text=t;z.text.style={typeface:'Malgun Gothic',fontSize:size,bold,color,alignment:align,verticalAlignment:'top',autoFit:'none',wrap:'word',insets:{left:0,right:0,top:0,bottom:0}};return z;
}
function box(s,x,y,w,h,title,body='',fill=C.blue){
 const z=s.shapes.add({name:title,geometry:'roundRect',position:{left:x,top:y,width:w,height:h},fill,line:{fill:'#bdcdd7',width:1.5}});
 text(s,x+20,y+20,w-40,44,title,30,true);
 if(body)text(s,x+20,y+76,w-40,h-87,body,25,false,C.muted);
 return z;
}
function connect(s,a,b,from='right',to='left',color=C.line){return s.shapes.connect(a,b,{kind:from==='right'&&to==='left'?'straight':'elbow',fromSide:from,toSide:to,line:{fill:color,width:3},tail:{type:'triangle',width:'med',length:'med'}});}
function path(s,pts,color=C.line,dash=false){for(let i=1;i<pts.length;i++){let [x,y]=pts[i-1],[xx,yy]=pts[i];s.shapes.add({name:'흐름 연결선',geometry:'line',position:{left:Math.min(x,xx),top:Math.min(y,yy),width:Math.abs(xx-x),height:Math.abs(yy-y)},fill:'none',line:{fill:color,width:3,style:dash?'dash':'solid'}});}}
function arrow(s,x,y,dir='down',color=C.line){s.shapes.add({name:'흐름 방향',geometry:dir==='left'?'leftArrow':dir==='right'?'rightArrow':dir==='up'?'upArrow':'downArrow',position:{left:x-9,top:y-9,width:18,height:18},fill:color,line:{fill:color,width:0}});}
function slide(title,sub,n){const s=p.slides.add();s.background.fill=C.bg;text(s,60,38,1750,70,title,48,true);text(s,60,120,1780,54,sub,26,false,C.muted);path(s,[[60,1000],[1860,1000]],'#d9e3e9');text(s,60,1020,1700,35,'TrueFit  ·  전체 서비스 기획',22,false,C.muted);text(s,1760,1020,100,35,`${n} / 3`,22,false,C.muted,'right');return s;}
const sources='기준: 프로젝트_기획서_v2.md; 기술기획서_데모+최종.md; docs/db/table_spec.md v4. 전체 서비스 완성 시점을 표현한다. 현행 개발 단계와 구분하지 않는다. 기술기획서 최종 범위의 사후 개선 배치를 포함하되, 원문 보관·리뷰 평가·합성 데이터 격리는 v4 정책을 따른다. 요리 도메인은 포함하지 않는다.';

// 1. Customer journey, left to right, with explicit optional price-watch branch.
{
 const s=slide('목적 입력부터 구매 이후까지','가입 없이 추천과 근거를 살펴보고, 마음에 드는 구성을 저장해 구매와 사용으로 이어갑니다.',1);
 text(s,60,207,1010,38,'대화 · 추천 · 근거 확인은 비로그인으로 이용',25,true,C.accent);
 text(s,1110,207,750,38,'저장 · 확정 · 알림 · 리뷰 작성은 로그인 후 이용',25,true,C.accent);
 const titles=['목적 선택','조건 대화','추천 생성','비교·수정','로그인·확정','리포트·구매','사용 리뷰'];
 const bodies=['PC / 유아용품\n신규 / 업그레이드','예산·용도·월령\n부족한 조건 질문','필요 품목 구성\n검증·예산 배분','근거·리뷰·대안\n항목 교체·제외','이메일 코드 인증\n이름·구매일 저장','확정 구성 확인\n외부 쇼핑몰 이동','부품 / 전체 구성\n실제 PC 사용 경험'];
 const nodes=titles.map((t,i)=>box(s,60+i*260,285,240,195,t,bodies[i],i>=4?C.green:C.blue));
 for(let i=1;i<nodes.length;i++)connect(s,nodes[i-1],nodes[i]);
 path(s,[[960,285],[960,260],[440,260],[440,285]],C.accent);arrow(s,440,282,'down',C.accent);
 text(s,530,224,460,35,'조건 변경·재추천',22,false,C.accent,'center');
 text(s,1375,505,390,44,'결제는 외부 쇼핑몰에서 진행',23,false,C.muted);
 const watch=box(s,790,630,315,170,'가격 추적 설정','전체 구성 / 개별 항목\n목표가·종료일 지정',C.green);
 const poll=box(s,1160,630,315,170,'가격·재고 확인','배송·할인 포함 비교\n조회 실패 시 판정 보류',C.green);
 const notice=box(s,1530,630,315,170,'목표가 알림','목표 도달 시 이메일\n리포트에서 구매 링크',C.green);
 path(s,[[1220,480],[1220,565],[947,565],[947,630]],C.accent);arrow(s,947,627,'down',C.accent);
 text(s,795,527,430,38,'확정 후 선택하는 가격 알림',25,true,C.accent);
 connect(s,watch,poll);connect(s,poll,notice);
 path(s,[[1687,630],[1687,575],[1480,575],[1480,480]],C.accent);
 // Upward endpoint uses a native triangle, rotated to point toward the report.
 const up=s.shapes.add({name:'리포트로 돌아가기',geometry:'upArrow',position:{left:1471,top:476,width:18,height:18},fill:C.accent,line:{fill:'none',width:0}});
 text(s,1550,580,300,34,'알림에서 리포트 열기',22,false,C.accent);
 text(s,60,640,625,54,'사용자가 언제든 다시 조정',31,true);
 text(s,60,708,620,128,'확정본을 수정하면 새 초안을 만듭니다.\n기존 구성과 근거는 보존하고,\n재확정한 구성에 가격 추적을 연결합니다.',27,false,C.muted);
 text(s,60,895,1760,64,'대화 1건 = 리스트 1건     /     화면은 대화·추천 결과·물품 리스트를 함께 보여줍니다.',27,true);
 s.speakerNotes.textFrame.setText(sources+' 사용자 흐름: 기술기획서 2~3절. 가격 추적·재편집: 테이블 명세 51~53, 8~9절. 외부 구매 링크 클릭만으로 구매 완료를 판정하지 않으며 직접 작성 전체 PC 리뷰에는 자기신고 구성과 공개 동의가 필요하다.');
}

// 2. Common preparation and domain-specific recommendation order.
{
 const s=slide('추천 엔진의 판단 흐름','PC는 완성된 부품 조합을 검증하고, 유아용품은 품목별 검증을 마친 뒤 예산을 배분합니다.',2);
 const prep=[box(s,60,210,360,140,'조건 정리','명시 입력·추정·누락 구분'),box(s,530,210,360,140,'요구사항 변환','필수 슬롯·수량·제약 정의'),box(s,1000,210,360,140,'후보 수집·필터','상품 규격·가격·재고 확인'),box(s,1470,210,360,140,'적합도 순위','가격·성능·리뷰·밸런스')];
 prep.slice(1).forEach((n,i)=>connect(s,prep[i],n));
 text(s,60,430,240,50,'PC 본체 조립',32,true,C.accent);
 text(s,60,494,250,94,'신규 구성 또는\n보유 구성 업그레이드',24,false,C.muted);
 const pcA=box(s,345,420,345,160,'세트 최적화','부품 조합·예산 조정\n소켓·전력·공간 제약');
 const pcB=box(s,780,420,360,160,'전체 조합 검증','도구 관측값 + 자료 근거\n충돌·병목·미확인 확인');
 connect(s,pcA,pcB);
 text(s,60,706,240,50,'유아용품 준비',32,true,C.accent);
 text(s,60,770,250,94,'월령·발달 조건\n보유품·필요 시점',24,false,C.muted);
 const bA=box(s,345,700,345,160,'품목별 근거 검증','월령·사용 조건\n인증·리콜·위험 확인',C.green);
 const bB=box(s,780,700,360,160,'시점별 예산 배분','지금 / 곧 / 나중\n보유 충족·필수품 우선',C.green);
 connect(s,bA,bB);
 const result=box(s,1430,565,400,185,'추천 결과·근거 설명','선택 이유·계산 기여도\n대안·주의사항·인용 출처\n사용자가 비교 후 선택',C.orange);
 path(s,[[1650,350],[1650,382],[305,382],[305,780]],C.line);
 path(s,[[305,500],[345,500]]);arrow(s,340,500,'right');
 path(s,[[305,780],[345,780]]);arrow(s,340,780,'right');
 connect(s,pcB,result,'right','top');connect(s,bB,result,'right','bottom');
 path(s,[[960,580],[960,624],[517,624],[517,580]],C.accent);arrow(s,517,583,'up',C.accent);
 text(s,420,632,690,36,'기준 미달: 후보를 바꿔 재구성·재검증',23,false,C.accent);
 path(s,[[517,860],[517,915],[290,915],[290,650],[345,650],[345,700]],C.accent);arrow(s,345,695,'down',C.accent);
 text(s,550,891,780,48,'품목 기준 미달: 다음 후보로 재검증',23,false,C.accent);
 text(s,1230,840,615,90,'근거가 없으면 미확인으로 표시합니다.\n재탐색 한도 후에도 남는 위험은 드러냅니다.',25,true,C.ink);
 s.speakerNotes.textFrame.setText(sources+' 엔진: 기술기획서 4~11절. 규칙 기반 필터·점수·최적화와 LLM의 조건 추출·근거 문장화를 구분한다. 적대적 디베이트는 폐기한 기획이므로 포함하지 않는다. PC 세트 검증과 유아 품목별 검증의 순서를 보존했다. 재탐색은 설정된 한도 내 수행하며 유아 안전축 미해결 후보는 제외한다. 숫자 임계값은 운영 보정 대상이므로 본 도식에서는 기준 미달로 표현했다.');
}

// 3. Supporting evidence, real reviews, and separated learning data.
{
 const s=slide('근거와 피드백이 추천에 반영되는 흐름','자료 검색과 리뷰 분석은 추천을 뒷받침하고, 사용 이후의 피드백은 검토를 거쳐 다음 추천을 개선합니다.',3);
 text(s,60,225,245,52,'상품 자료',32,true,C.accent);
 text(s,60,286,230,86,'설명서·사양표\n이미지·공식 정보',24,false,C.muted);
 const a=box(s,330,220,350,160,'자료 수집·권한 확인','원본·버전·적용 상품\n객체 저장소에 보관');
 const b=box(s,785,220,350,160,'검색 자료 준비','추출·OCR·청크화\n임베딩·게시');
 const c=box(s,1240,220,350,160,'근거 검색·인용','상품·조건에 맞게 검색\n출처·원문 위치 제시');
 connect(s,a,b);connect(s,b,c);
 text(s,1640,247,225,106,'추천 검증과\n선택 이유에\n함께 사용',26,true);
 path(s,[[1590,300],[1620,300]]);arrow(s,1616,300,'right');
 text(s,60,460,245,52,'실제 리뷰',32,true,C.accent);
 text(s,60,521,235,92,'외부 리뷰\n서비스 작성 리뷰',24,false,C.muted);
 const d=box(s,330,455,350,180,'대상·출처 구분','부품 / 전체 PC 구분\n본문 편집 버전 연결\n전체 PC는 사용 구성 고정',C.green);
 const e=box(s,785,455,350,180,'신호 분석·검토','관측 가능한 근거 수집\n의심·불충분 신호 검토\n제외 이유와 문맥 보존',C.green);
 const f=box(s,1240,455,350,180,'요약·통계 제공','중복 없이 평점 집계\n전후 통계·대표 요약\n리뷰 근거 카드 제공',C.green);
 connect(s,d,e);connect(s,e,f);
 text(s,1640,495,230,110,'후보 비교와\n근거 검증에\n반영',26,true);
 path(s,[[1590,540],[1620,540]]);arrow(s,1616,540,'right');
 text(s,60,716,245,52,'지속 개선',32,true,C.accent);
 text(s,60,777,230,92,'추천 중 행동\n사용 후 피드백',24,false,C.muted);
 const g=box(s,330,710,350,180,'행동·사용 경험 수집','노출·교체·제외·확정\n리뷰·오류·이슈 제보',C.orange);
 const h=box(s,785,710,350,180,'학습·평가·검수','실제 표본과 증강 구분\n정답 라벨·분할 관리\n독립 평가·변경 검토',C.orange);
 const j=box(s,1240,710,350,180,'추천 기준 개선','가중치·예산 프로필\n규격·근거 자료 갱신\n검토·승인 후 반영',C.orange);
 connect(s,g,h);connect(s,h,j);
 text(s,1640,750,230,110,'다음 추천의\n조건 해석·순위·\n검증에 반영',26,true);
 path(s,[[1590,800],[1620,800]]);arrow(s,1616,800,'right');
 text(s,330,928,1500,42,'합성 표본은 학습·평가용으로 격리합니다. 운영 후기 수·평균에는 실제 리뷰만 포함합니다.',25,true);
 s.speakerNotes.textFrame.setText(sources+' 자료: 명세 8.1~8.3절. 외부 리뷰 원문은 저장하지 않고 허용된 요약·출처·비원문 분석값을 사용하며 직접 작성 본문은 버전 관리한다. 리뷰: 명세 8.4~8.6절. 실구매 표시는 진실성 정답이 아니며 supported/manipulation_indicators/undetermined 근거 판정과 분리한다. 실제 train 부모 하나에서 증강하고 평가용 실제 표본은 사람 승인 라벨을 사용한다. 사후 개선: 기술기획서 12절의 최종 서비스 배치 흐름. 실구매 인증을 서비스가 자동 수행한다는 의미는 포함하지 않는다.');
}
const candidate=build+'/service-flow-candidate.pptx';
await (await PresentationFile.exportPptx(p)).save(candidate);
const finalPath=out+'/truefit-service-flow-editable.pptx';
await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath,pythonExecutable:'C:/Users/playdata2/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','18288000,10287000','--validate-heading-fit'],explicitTotalSlideCount:3,fontPolicy:{basis:'design',families:['Malgun Gothic']},verifyArtifactToolImport:true,receiptPath:build+'/service-flow-final-validation.json'});
const loaded=await PresentationFile.importPptx(await FileBlob.load(finalPath));
for(let i=0;i<loaded.slides.items.length;i++){const blob=await loaded.export({slide:loaded.slides.items[i],format:'png',scale:0.8});await fs.writeFile(build+`/service-flow-slide-${i+1}.png`,new Uint8Array(await blob.arrayBuffer()));}
console.log(finalPath);


