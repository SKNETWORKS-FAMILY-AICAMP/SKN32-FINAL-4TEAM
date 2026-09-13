/* ==== Bilingual layer (Korean <-> English). Added without touching the KR logic. ==== */
(function(){
 "use strict";
 var LS='planbasket-lang';
 var lang='ko';
 try{ var st=localStorage.getItem(LS); if(st==='en'||st==='ko') lang=st; }catch(e){}

 /* ---- exact / substring dictionary (Korean source -> English) ---- */
 var DICT={
  /* TF-DEV: 장바구니·추천 API 연결 문구 */
  "불러오는 중이에요…":"Loading…","정보를 불러오지 못했어요.":"Couldn't load this information.","다시 시도":"Try again",
  "장바구니를 불러오는 중…":"Loading baskets…","장바구니는 서버에 저장됩니다.":"Baskets are saved on the server.","로그인하지 않으면 이 브라우저에서만 이어볼 수 있어요.":"Without signing in, you can continue only in this browser.",
  "장바구니를 찾을 수 없어 새로 시작합니다.":"Basket not found. Starting a new one.",
  "카테고리를 바꾸면 지금까지의 조건과 추천 결과가 초기화돼요. 계속할까요?":"Changing the category resets your conditions and results. Continue?",
  "사양 인식을 위해 첨부한 파일 내용을 서버로 전송합니다. 텍스트 기반 사양 파일(1MB 이하)을 지원합니다.":"To read your specs, the attached file is sent to the server. Text-based spec files up to 1MB are supported.",
  "1MB 이하의 텍스트 기반 사양 파일을 첨부해 주세요.":"Please attach a text-based spec file up to 1MB.",
  "선택 완료":"Done","하나 이상 선택해 주세요.":"Please select at least one.","추정":"Assumed","수정 중…":"Updating…","초기화 중…":"Resetting…","보내는 중…":"Sending…","추천을 시작하는 중…":"Starting recommendation…",
  "아직 확인되지 않은 조건이 있어요. 대화로 조건을 채워 주세요.":"Some conditions are still missing. Please continue the conversation.",
  "추천을 준비하고 있어요.":"Preparing your recommendation.","조건에 맞는 후보를 찾고 조합을 확인하는 중입니다. 잠시만 기다려 주세요.":"Finding candidates and checking the combination. Please wait a moment.",
  "완료":"Done","진행 중":"In progress","대기":"Waiting",
  "아직 추천 결과가 없어요.":"No recommendation yet.","조건 대화를 마치고 추천을 받아 보세요.":"Finish the conversation to get a recommendation.",
  "추천을 만들지 못했어요.":"We couldn't create a recommendation.","다시 추천받기":"Recommend again","추천 과정 보기":"View recommendation steps","다른 구성 보기":"See another build",
  "추천 요약":"Summary","추천 설명을 만드는 중이에요…":"Writing the explanation…","추천 설명을 만들지 못했어요.":"Couldn't write the explanation.",
  "추천 이유를 정리하는 중이에요…":"Writing the reason…","추천 이유를 만들지 못했어요.":"Couldn't write the reason.","확인할 점을 정리하는 중이에요…":"Writing things to check…","확인할 점을 만들지 못했어요.":"Couldn't write things to check.",
  "리뷰 정보 없음":"No review data","리뷰 정보를 불러오는 중이에요…":"Loading reviews…","이 상품의 리뷰 정보가 아직 없어요.":"No reviews for this product yet.",
  "다른 후보를 불러오는 중이에요…":"Loading alternatives…","가격과 규격을 비교해 하나를 선택하세요.":"Compare price and specs, then pick one.","바꿀 수 있는 다른 후보가 없어요.":"No other candidates available.","선택한 후보로 바꿨어요.":"Switched to the selected candidate.",
  "판매처 링크가 아직 연결되지 않았어요.":"The seller link isn't connected yet.","결제는 각 판매처에서 진행됩니다.":"Payment happens at each seller.",
  "현재 선택한 구성이 예산을 초과합니다. 품목을 빼거나 대체 후보를 선택해 주세요.":"Your current build is over budget. Remove items or choose alternatives.",
  "현재 선택한 품목이 예산을 초과합니다. 품목을 빼거나 대체 후보를 선택해 주세요.":"Your selected items are over budget. Remove items or choose alternatives.",
  "추천 엔진이 단계별로 남긴 기록입니다.":"Step-by-step records from the recommendation engine.","기록된 단계가 없어요.":"No steps recorded.","확인된 쟁점이 없어요.":"No issues found.",
  "저장하는 중…":"Saving…","리스트 이름을 입력해 주세요.":"Please enter a list name.","구매 예정일을 선택해 주세요.":"Please choose a purchase date.","목표 총액을 입력해 주세요.":"Please enter a target total.","장바구니에 담긴 품목이 없어요.":"Your basket is empty.",
  "추천 결과 보기":"View recommendation","목표가 도달 시 알림 받기":"Notify me when the target price is reached","목표가 알림을 켰어요.":"Price alert on.","목표가 알림을 껐어요.":"Price alert off.",
  "장바구니 이름을 바꿨어요.":"Basket renamed.","대화를 처음부터 다시 시작할까요? 입력한 조건과 추천 결과가 초기화돼요.":"Start the conversation over? Your conditions and results will be reset.",
  /* TF-DEV: 인증 API 연결 문구 */
  "로그인 상태를 확인하고 있어요…":"Checking your sign-in status…",
  "비밀번호 재설정은 아직 준비 중이에요.":"Password reset isn't available yet.",
  "로그인 중…":"Signing in…","가입 중…":"Creating account…","저장 중…":"Saving…","변경 중…":"Updating…","처리 중…":"Processing…","로그아웃 중…":"Signing out…","탈퇴 처리 중…":"Deleting account…",
  "서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.":"Can't reach the server. Please try again shortly.",
  "서버 기능이 아직 준비 중이에요.":"This feature isn't available on the server yet.",
  "입력값을 다시 확인해 주세요.":"Please check your input.",
  "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.":"We couldn't process your request. Please try again shortly.",
  "로그인이 필요합니다.":"Please sign in.",
  "이메일 또는 비밀번호가 올바르지 않습니다.":"Incorrect email or password.",
  "로그인 시도가 여러 번 실패해 잠시 잠겼어요. 15분 후 다시 시도해 주세요.":"Too many failed attempts. Please try again in 15 minutes.",
  "이미 가입된 이메일입니다.":"This email is already registered.",
  "비밀번호는 영문과 숫자를 포함해 8자 이상이어야 합니다.":"Password must be at least 8 characters and include letters and numbers.",
  "필수 약관에 동의해 주세요.":"Please agree to the required terms.",
  "현재 비밀번호가 일치하지 않습니다.":"Your current password is incorrect.",
  "요청이 많아요. 잠시 후 다시 시도해 주세요.":"Too many requests. Please try again shortly.",
  "지금은 중복 확인을 할 수 없어요. 가입할 때 다시 확인합니다.":"Can't check this email right now. We'll check again when you sign up.",
  "지금은 중복 확인을 할 수 없어요. 저장할 때 다시 확인합니다.":"Can't check this email right now. We'll check again when you save.",
  "이미 사용 중인 이메일입니다.":"This email is already in use.",
  "현재 비밀번호와 다른 비밀번호를 입력해 주세요.":"Choose a password different from your current one.",
  "리스트 확정 계속하기 →":"Continue confirming your list →",
  "탈퇴하면 이메일·이름·비밀번호 등 계정 정보가 삭제되고 이 계정으로 다시 로그인할 수 없어요. 같은 이메일로는 다시 가입할 수 있습니다.":"Deleting your account removes your email, name and password, and you won't be able to sign in with it again. You can sign up again with the same email.",
  "탈퇴하려면 비밀번호를 입력해 주세요":"Enter your password to delete your account",
  "탈퇴하기":"Delete account",
  "회원 탈퇴가 완료되었습니다.":"Your account has been deleted.",
  "로그아웃하지 못했어요.":"Couldn't sign out.",
  "비밀번호가 변경되었습니다.":"Your password has been changed.",
  "※ 위 내용은 화면 구성을 위한 예시 문안이며, 정식 처리방침은 서비스 출시 시 안내됩니다.":"※ This is sample text for the screen layout. The official privacy policy will be provided at launch.",
  /* head + header */
  "TrueFit — 잘 고르는 시작":"TrueFit — a better way to start choosing",
  "TrueFit 홈":"TrueFit home",
  "회원 및 서비스 메뉴":"Account and service menu",
  "로그인":"Log in",
  "회원가입":"Sign up",
  "서비스 소개":"About",
  "서비스 시작하기":"Get started",
  "컴퓨터":"Computer",
  "유아용품":"Baby care",
  "내 리포트":"My report",
  "닫기":"Close",

  /* landing: about opening */
  "검색은 줄이고,":"Less searching,",
  "내게 맞는 선택에 가까이.":"closer to the right choice.",
  "무엇을 사야 할지보다,":"Rather than what to buy,",
  "어떤 생활을 원하는지부터 시작해요.":"we start from the life you want.",
  "TrueFit은 예산과 사용 목적을 바탕으로 필요한 제품을 함께 정리하는 구매 계획 서비스입니다. 컴퓨터 한 대를 구성할 때도, 아이를 위한 용품을 준비할 때도 선택의 이유와 확인할 점을 한곳에서 살펴볼 수 있어요.":"TrueFit is a purchase-planning service that organizes the products you need based on your budget and how you'll use them. Whether you're building a computer or preparing baby gear, you can review the reasons for each choice and the things to check, all in one place.",
  "나의 계획 시작하기 ↗":"Start my plan ↗",

  /* landing: two ways */
  "서로 다른 준비, 그에 맞는 기준.":"Different plans, standards that fit each.",
  "부품 하나보다,":"More than a single part,",
  "함께 작동하는 한 대를 봅니다.":"we look at one machine working together.",
  "게임·작업·학습 등 주로 하는 일과 예산을 알려주세요. 프로세서부터 케이스까지 필요한 구성을 모으고, 부품 간 호환성과 전체 조합의 확인 사항을 살펴보는 흐름입니다.":"Tell us what you mainly do — gaming, work, study — and your budget. We gather the parts you need from the processor to the case, then review compatibility between parts and checkpoints for the whole build.",
  "용도·해상도·예산에 맞는 구성":"A build matched to use, resolution and budget",
  "소켓·메모리 규격과 전력 여유 검토":"Checks on socket, memory spec and power headroom",
  "대체 후보 비교와 세트 가격 확인":"Compare alternatives and check the set price",
  "컴퓨터 구성 시작하기 →":"Start building a computer →",
  "아이의 지금과,":"Your child's present,",
  "다가올 일상을 준비합니다.":"and the days ahead.",
  "아이의 월령과 필요한 품목, 생활 환경을 알려주세요. 제품마다 확인할 안전 정보와 사용 조건을 구분하고, 지금 필요한 것과 나중에 준비할 것을 나눠봅니다.":"Tell us your child's age in months, the items you need and your living situation. We separate the safety information and usage conditions to check for each product, and split what you need now from what to prepare later.",
  "월령·생활 환경에 따른 품목 정리":"Items organized by age in months and living situation",
  "인증·리콜·사용 조건 확인 항목":"Checklist for certification, recalls and usage conditions",
  "품목별 예산과 구매 시점 배분":"Budget and purchase timing split by item",
  "유아용품 준비 시작하기 →":"Start preparing baby gear →",

  /* landing: how it works */
  "이야기에서 시작해, 나만의 리스트로.":"Start from a conversation, end with your own list.",
  "조건을 바꾸고 후보를 비교하면서, 납득할 수 있는 장바구니를 만들어보세요.":"Change conditions and compare candidates to build a basket you can stand behind.",
  "계획 이야기하기":"Talk through your plan",
  "카테고리를 고르고 예산·사용 목적·월령 등 필요한 조건을 입력해요.":"Pick a category and enter the conditions you need — budget, purpose, age in months, and so on.",
  "추천 살펴보기":"Review recommendations",
  "후보별 가격과 선택 이유를 살펴보고, 원하는 제품으로 바꿔봐요.":"Look at each candidate's price and reasoning, and swap in the products you want.",
  "확인하고 비교하기":"Check and compare",
  "리뷰 요약과 검증 과정을 읽고, 아직 확인되지 않은 정보도 함께 체크해요.":"Read the review summary and verification steps, and note what hasn't been confirmed yet.",
  "리스트로 남기기":"Save it as a list",
  "구매 시점과 목표 가격을 정해 저장하고, 리포트로 다시 확인해요.":"Set a purchase time and target price, save it, and revisit it as a report.",

  /* landing: clearer reason */
  "추천의 이유도,":"The reasons for a recommendation,",
  "모르는 부분도 함께.":"and what's still unknown.",
  "좋아 보이는 결과만 보여주기보다, 선택을 뒷받침할 정보가 무엇인지 구분하는 것을 목표로 합니다.":"Rather than only showing results that look good, the aim is to distinguish what information actually backs a choice.",
  "조건에 맞는지 먼저":"Conditions first",
  "컴퓨터는 조합 전체를, 유아용품은 각 품목을 기준으로 필요한 조건을 살펴봅니다.":"For computers we review the whole build; for baby gear we review each item against its own conditions.",
  "근거를 확인할 수 있게":"So the evidence is checkable",
  "문서 출처와 조회 시점을 함께 제공합니다. 정보가 없으면 검증 불가로 표시합니다.":"Document sources and lookup dates are provided together. When information is unavailable, it is marked as not verifiable.",
  "리뷰는 어떻게 클렌징하나요?":"How are reviews cleansed?",
  "조작이 의심되거나 중복된 리뷰를 제외하고, 클렌징 전후 평점과 평점 분포를 비교해 보여드립니다.":"Suspected manipulated or duplicate reviews are removed, and ratings and rating distributions before and after cleansing are compared.",

  /* landing: FAQ */
  "시작 전에 알아두세요.":"Before you start.",
  "지금 어떤 기능을 사용할 수 있나요?":"What can I use right now?",
  "이 페이지는 서비스 흐름을 체험하는 HTML 목업입니다. 조건 입력, 예시 추천, 후보 교체, 장바구니 구성, 리스트 저장과 리포트 인쇄를 사용할 수 있습니다.":"This page is an HTML mockup for experiencing the service flow. You can enter conditions, see sample recommendations, swap candidates, build a basket, save a list and print a report.",
  "상품 가격과 안전 검증 결과는 실제 정보인가요?":"Are the product prices and safety checks real?",
  "아닙니다. 상품·가격·리뷰는 화면 설명을 위한 가상 예시이며, 실제 AI 검색이나 인증·리콜 조회는 연결되어 있지 않습니다. 구매 판단을 위한 실제 검증 결과로 사용할 수 없습니다.":"No. Products, prices and reviews are fictional samples for illustration, and no real AI search or certification/recall lookup is connected. They can't be used as real verification for a purchase decision.",
  "최종 리스트업한 제품은 어떻게 구매하나요?":"How do I purchase products from the final list?",
  "최종 리스트에 추천된 각 제품의 상품 페이지 링크를 제공합니다. 링크를 선택하면 해당 판매 페이지로 이동해 제품 정보를 확인하고 구매할 수 있습니다.":"A product-page link is provided for each recommendation in the final list. Select a link to view product details and purchase it on the seller's page.",

  /* footer */
  "하단 메뉴":"Footer menu",
  "이용약관":"Terms of use",
  "개인정보 처리방침":"Privacy policy",
  "자주 묻는 질문":"FAQ",
  "제휴 문의":"Partnerships",
  "고객센터":"Support",
  "서비스 바로가기":"Go to a service",
  "나의 계획에서 시작하는 선택.":"Choices that start from your plan.",
  "TrueFit 서비스 정보":"About TrueFit",
  "TrueFit 서비스 정보":"About TrueFit",
  "컴퓨터 구성과 유아용품 준비를 돕는 구매 계획 서비스":"A purchase-planning service for building computers and preparing baby gear",
  "운영사 · 대표자 · 사업자등록번호 : 미등록":"Operator · representative · business registration no.: not registered",
  "사업장 주소 · 통신판매업 신고번호 : 미등록":"Business address · e-commerce filing no.: not registered",
  "정식 운영 정보는 서비스 출시 시 안내됩니다.":"Official operating details will be provided at launch.",
  "문의 채널 · 운영시간 : 준비 중":"Contact channels · hours: coming soon",
  "자주 묻는 질문 보기 →":"See the FAQ →",
  "현재는 화면 체험용 목업입니다.":"This is currently a mockup for screen experience.",
  "현재 제공되는 상품·가격·리뷰는 가상의 예시입니다. 실제 상품 판매, 결제, 인증 조회 및 이메일 발송은 이루어지지 않습니다.":"The products, prices and reviews shown are fictional samples. No real product sales, payment, certification lookup or email sending takes place.",
  "입력한 리스트는 현재 브라우저에 저장되며, 브라우저 데이터를 삭제하면 함께 사라질 수 있습니다.":"Lists you enter are saved in your current browser and can be lost if you clear browser data.",
  "이용약관":"Terms of use",
  "정식 서비스 이용약관은 준비 중입니다. 현재 페이지는 서비스 흐름을 체험하는 목업이며, 실제 상품 판매나 결제는 진행되지 않습니다.":"The formal terms of use are being prepared. This page is a mockup for experiencing the flow; no real sales or payment take place.",
  "정식 개인정보 처리방침은 준비 중입니다. 이 목업의 표시 이름과 입력 조건, 리스트는 현재 브라우저의 로컬 저장소에 저장됩니다. 실제 계정 인증이나 이메일 발송은 하지 않습니다. 브라우저 사이트 데이터를 삭제하면 저장 내용이 지워집니다. 글꼴 로딩에는 Google Fonts 연결이 사용됩니다.":"The formal privacy policy is being prepared. In this mockup, your display name, entered conditions and lists are stored in your browser's local storage. No real account sign-in or email sending is performed. Clearing browser site data erases what's stored. Google Fonts is used to load fonts.",
  "제휴 문의 채널은 아직 등록되지 않았습니다. 정식 서비스 출시 시 안내할 예정입니다.":"A partnerships channel isn't set up yet. It will be announced at official launch.",
  "고객지원 연락처와 운영시간은 준비 중입니다. 서비스 사용 방법은 하단의 자주 묻는 질문에서 확인할 수 있습니다.":"Support contact and hours are being prepared. You can find how to use the service in the FAQ below.",

  /* planner chrome */
  "화면 체험용 · 상품명·가격·리뷰·검증 결과는 가상의 예시입니다. 실제 AI 검색, 인증 조회, 구매 및 이메일 발송은 연결되지 않았습니다.":"Screen demo · product names, prices, reviews and verification results are fictional samples. No real AI search, certification lookup, purchase or email sending is connected.",
  "장바구니 만들기 단계":"Basket-building steps",
  "카테고리":"Category",
  "조건 입력":"Conditions",
  "추천 결과":"Recommendations",
  "리스트 확정":"Confirm list",
  "리포트":"Report",
  "새 장바구니":"New basket",
  "＋ 새 장바구니":"＋ New basket",
  "내 장바구니":"My baskets",
  "아직 저장된 장바구니가 없어요":"No saved baskets yet",
  "화면 체험용 목업입니다.":"This is a demo mockup.",
  "입력 내용은 현재 브라우저에만 저장됩니다.":"Your input is saved only in this browser.",
  "사이드바 열기":"Open sidebar",
  "사이드바 접기":"Collapse sidebar",
  "장바구니 이름 변경":"Rename basket",
  "장바구니 삭제":"Delete basket",
  "장바구니 이름":"Basket name",
  "저장":"Save",
  "취소":"Cancel",
  "대화 다시 시작":"Restart chat",
  "← 카테고리 변경":"← Change category",
  "카테고리 변경":"Change category",
  "컴퓨터 장바구니":"Computer basket",
  "유아용품 장바구니":"Baby-care basket",
  "나의 장바구니":"My basket",
  "저장한 장바구니":"Saved basket",

  /* category page */
  "어떤 장바구니를 만들까요?":"Which basket shall we build?",
  "필요한 카테고리를 선택하면, 그에 맞는 조건부터 함께 정리해요.":"Choose the category you need and we'll organize the matching conditions with you.",
  "게임, 작업, 일상에 맞는 한 대.":"One machine for gaming, work and everyday use.",
  "부품 호환성 · 전력 여유 · 예산 내 구성":"Part compatibility · power headroom · a build within budget",
  "우리 아이의 지금과 다음을 준비해요.":"Prepare for your child's now and next.",
  "월령 · 필요한 품목 · 안전 확인 항목":"Age in months · needed items · safety checklist",
  "나의 장바구니 만들기":"Build my basket",

  /* conditions (chat) */
  "어떤 컴퓨터가 필요한가요?":"What kind of computer do you need?",
  "어떤 유아용품이 필요한가요?":"What baby gear do you need?",
  "어떤 육아용품이 필요한가요?":"What baby gear do you need?",
  "육아용품":"baby gear",
  "아이에게 필요한 준비를 알려주세요.":"Tell us what your child needs.",
  "무엇을 살지 막막할 땐, 대화부터 시작해 보세요.":"Not sure what to buy? Start with a conversation.",
  "예산과 사용 목적을 알려주시면 한 대의 구성으로 연결해 드려요.":"Tell us your budget and purpose and we'll turn it into one build.",
  "아이의 월령과 필요한 품목을 알려주시면 준비 시점까지 함께 정리해 드려요.":"Tell us your child's age in months and needed items and we'll organize the timing too.",
  "필요한 컴퓨터에 대해 먼저 이야기해 주세요":"Tell us about the computer you need first",
  "필요한 육아용품에 대해 먼저 이야기해 주세요":"Tell us about the baby gear you need first",
  "답변을 입력해 주세요":"Type your answer",
  "추가 조건이나 변경할 내용을 입력해 주세요":"Add another condition or a change",
  "컴퓨터 조건 대화 입력":"Computer condition chat input",
  "육아용품 조건 대화 입력":"Baby-gear condition chat input",
  "전송 →":"Send →",
  "전송":"Send",
  "＋ 파일 첨부":"＋ Attach file",
  "＋ 사양 파일":"＋ Spec file",
  "첨부 파일은 이 브라우저 안에서만 읽으며 외부로 전송하지 않습니다. 텍스트 기반 사양 파일을 지원합니다.":"Attached files are read only inside this browser and never sent anywhere. Text-based spec files are supported.",
  "조건을 모두 확인했어요.":"All conditions are set.",
  "오른쪽에 정리된 답변을 확인한 뒤 추천 결과로 이동해 보세요.":"Review the answers on the right, then move to the recommendations.",
  "이 조건으로 추천 보기 →":"See recommendations with these conditions →",
  "YOUR CHOICES":"YOUR CHOICES",
  "선택한 조건 확인":"Your chosen conditions",
  "답변이 모두 반영됐습니다. 추천 결과로 이동할 수 있어요.":"All answers are in. You can move to the recommendations.",
  "챗봇이 부족한 정보를 이어서 질문합니다.":"The chatbot will keep asking for missing details.",
  "컴퓨터에 대한 이야기를 먼저 들려주세요.":"Tell us about the computer first.",
  "구성 방식":"Build type",
  "새 컴퓨터":"New computer",
  "업그레이드":"Upgrade",
  "첨부 사양 파일":"Attached spec file",
  "현재 사양":"Current specs",
  "업그레이드 부품":"Parts to upgrade",
  "주요 용도":"Main use",
  "예산":"Budget",
  "우선순위":"Priority",
  "아이 연령대":"Child's age group",
  "필요한 영역":"Areas needed",
  "건강·피부 특성":"Health / skin traits",
  "이미 보유한 물품":"Items already owned",
  "아직 확인되지 않았어요":"Not confirmed yet",
  "아직 답하지 않았어요":"Not answered yet",
  "수정하기":"Edit",
  "사양 항목 확인 필요":"spec items need checking",

  /* chatbot questions / replies */
  "새 컴퓨터를 맞추려는 건가요, 기존 컴퓨터를 업그레이드하려는 건가요?":"Are you building a new computer, or upgrading an existing one?",
  "현재 컴퓨터 사양을 확인할 수 있는 TXT, JSON, CSV 또는 NFO 파일을 첨부해 주세요.":"Please attach a TXT, JSON, CSV or NFO file that shows your current computer's specs.",
  "파일에서 사양 항목을 찾지 못했어요. CPU, GPU, RAM처럼 현재 사양을 채팅으로 알려주세요.":"I couldn't find spec fields in the file. Please tell me your current specs in chat, like CPU, GPU, RAM.",
  "어떤 부품을 업그레이드하고 싶나요?":"Which parts do you want to upgrade?",
  "주로 어떤 용도로 사용하나요?":"What will you mainly use it for?",
  "예산은 얼마까지 생각하시나요?":"What budget do you have in mind?",
  "무엇을 가장 우선하고 싶나요?":"What matters most to you?",
  "예산을 정확히 반영하려면 “150만원” 또는 “1,500,000원”처럼 금액을 알려주세요.":"To capture the budget exactly, give an amount like “1,500,000” or “1.5M”.",
  "예산을 정확히 반영하려면 “50만원” 또는 “500,000원”처럼 금액을 알려주세요.":"To capture the budget exactly, give an amount like “500,000” or “0.5M”.",
  "좋아요. 필요한 정보를 모두 확인했어요. 오른쪽에서 정리된 조건을 확인해 주세요.":"Great — I have everything I need. Please review the organized conditions on the right.",
  "파일은 읽었지만 사양 항목을 찾지 못했어요. ":"I read the file but couldn't find spec fields. ",
  "3MB 이하의 텍스트 기반 사양 파일을 첨부해 주세요.":"Please attach a text-based spec file of 3MB or less.",
  "TXT, JSON, CSV, MD, LOG, NFO 또는 XML 파일을 첨부해 주세요.":"Please attach a TXT, JSON, CSV, MD, LOG, NFO or XML file.",
  "파일을 읽지 못했습니다. 다른 텍스트 파일을 선택해 주세요.":"Couldn't read the file. Please choose another text file.",
  "아이의 연령대는 어떻게 되나요? 예: 신생아, 이유식기, 걸음마기":"What's your child's age group? e.g. newborn, weaning stage, toddler stage",
  "아이의 연령대나 개월 수는 어떻게 되나요?":"What's your child's age group or age in months?",
  "어떤 영역의 육아용품이 필요한가요? 예: 수유, 수면, 외출, 목욕, 놀이":"Which areas of baby gear do you need? e.g. feeding, sleep, outings, bath, play",
  "어떤 영역의 육아용품이 필요한가요? 예: 수유, 수면, 외출·이동":"Which areas of baby gear do you need? e.g. feeding, sleep, outings",
  "알레르기, 아토피, 민감성 피부 등 건강·피부 특성이 있나요? 없다면 “특이사항 없음”이라고 알려주세요.":"Any health or skin traits such as allergies, atopic dermatitis or sensitive skin? If none, say “none noted”.",
  "이미 보유한 육아용품은 무엇인가요? 없다면 “없음”이라고 답해 주세요.":"What baby gear do you already own? If none, answer “none”.",
  "전체 예산은 얼마까지 생각하시나요?":"What total budget do you have in mind?",

  /* conditions v1/v2 form (older path, still translated for safety) */
  "주로 하는 작업과 예산을 알려주세요. 본체 부품 7개를 한 세트로 구성하는 예시를 보여드릴게요.":"Tell us your main tasks and budget. We'll show a sample set of 7 core parts.",
  "아이의 월령과 필요한 품목을 알려주세요. 품목별 선택과 구매 시점을 나눠볼게요.":"Tell us your child's age in months and needed items. We'll split the choices and timing by item.",
  "전체 예산 (원) *":"Total budget (KRW) *",
  "주요 용도 *":"Main use *",
  "아이의 월령 (개월) *":"Child's age (months) *",
  "목표 해상도":"Target resolution",
  "우선순위":"Priority",
  "더 원하는 점":"Anything else you want",
  "공간, 사용 환경, 선호하는 점 등을 적어주세요.":"Note your space, environment, preferences, and so on.",
  "추가 조건":"Extra conditions",
  "예: 조용한 환경에서 쓰고 싶어요. 보관 공간이 작아요.":"e.g. I want it quiet. Storage space is small.",
  "입력한 내용도 추천 조건과 함께 저장됩니다.":"What you enter is saved along with the recommendation conditions.",
  "대화로 조건을 더 알려주세요":"Tell us more conditions by chat",
  "필수 조건을 입력하고, 더 원하는 점은 자유롭게 이야기해 주세요.":"Enter the required conditions, and freely tell us anything more you want.",
  "조건을 더 정리해볼까요?":"Shall we refine the conditions?",
  "추가 질문":"Follow-up question",
  "예: 어떤 조건을 더 적으면 좋을까요?":"e.g. What other conditions should I add?",
  "질문하기":"Ask",
  "실제 AI 대신 카테고리별 안내 문장을 보여주는 대화 예시입니다.":"A sample conversation that shows category guidance instead of a real AI.",
  "선택 전에 확인해요":"Check before choosing",
  "소켓·메모리 규격을 먼저 맞추고, 예산 안에서 세트를 구성한 뒤 전체 조합을 검토해요.":"Match socket and memory specs first, build the set within budget, then review the whole combination.",
  "품목마다 월령·인증·리콜 확인 항목을 검토한 뒤, 예산과 구매 시점을 나눠요.":"Review age, certification and recall checkpoints for each item, then split budget and timing.",
  "리뷰의 장점뿐 아니라 아쉬운 점과 확인되지 않은 정보도 함께 표시합니다.":"We show downsides and unconfirmed information, not just the strengths in reviews.",
  "조건을 바꾸면 이곳에 바로 반영됩니다. 준비가 되면 추천 결과로 이동하세요.":"Changes to conditions show here right away. When ready, move to the recommendations.",
  "이 조건으로 추천 보기":"See recommendations with these conditions",
  "필요한 품목을 하나 이상 골라주세요.":"Please pick at least one item you need.",
  "예산을 “150만원” 또는 “1500000”처럼 입력해 주세요.":"Enter the budget like “1.5M” or “1500000”.",
  "안내 예시: 주로 쓰는 프로그램, 게임 이름, 해상도와 소음 선호를 추가해 주세요.":"Guidance sample: add the programs you use most, game names, resolution and noise preference.",
  "안내 예시: 아이의 월령, 필요한 품목, 보관 공간과 구매 시점을 추가해 주세요.":"Guidance sample: add your child's age in months, needed items, storage space and purchase timing.",

  /* select option values */
  "게임":"Gaming",
  "영상 편집":"Video editing",
  "개발 / 업무":"Dev / work",
  "일상 / 학습":"Everyday / study",
  "가격 균형":"Price balance",
  "성능":"Performance",
  "조용한 사용":"Quiet operation",
  "지금":"Now",
  "곧 (1~3 months)":"Soon (1–3 months)",
  "나중":"Later",
  "유모차":"Stroller",
  "모빌":"Mobile",
  "젖병":"Bottle",
  "구매 시점":"Purchase timing",
  "필요한 품목 (1개 이상) *":"Needed items (one or more) *",

  /* detector canonical outputs (surfaced by the EN chat helpers) */
  "신생아":"Newborn",
  "영아":"Infant",
  "유아":"Toddler",
  "이유식기":"Weaning stage",
  "걸음마기":"Toddler stage",
  "초등학생":"Primary-school age",
  "중학생":"Middle-school age",
  "고등학생":"High-school age",
  "수유":"Feeding",
  "이유식·식사":"Weaning & meals",
  "수면":"Sleep",
  "외출":"Outings",
  "외출·이동":"Outings & travel",
  "목욕·위생":"Bath & hygiene",
  "위생·피부관리":"Hygiene & skin care",
  "기저귀·배변":"Diapering",
  "의류":"Clothing",
  "놀이":"Play",
  "놀이·발달":"Play & development",
  "안전·건강":"Safety & health",
  "알레르기":"Allergies",
  "아토피":"Atopic dermatitis",
  "민감성 피부":"Sensitive skin",
  "건조한 피부":"Dry skin",
  "습진":"Eczema",
  "두드러기":"Hives",
  "특이사항 없음":"None noted",
  "없음":"None",
  "카시트":"car seat",
  "아기띠":"carrier",
  "유축기":"breast pump",
  "아기침대":"crib",
  "장난감":"toys",
  "기저귀":"diapers",
  "욕조":"bathtub",
  "로션":"lotion",
  "분유포트":"formula kettle",

  /* results (baby form path) */
  "아직 추천 결과가 없어요.":"No recommendations yet.",
  "카테고리와 조건부터 입력해 주세요.":"Please enter a category and conditions first.",
  "조건 입력하기":"Enter conditions",
  "함께 쓸 때 더 좋은 구성.":"A build that's better together.",
  "우리 아이를 위한 준비 리스트.":"A preparation list for your child.",
  "본체 구성 7개":"7 core parts",
  "품목별 추천":"Recommendations by item",
  "실제 검증 전":"Before real verification",
  "규격이 맞는 가상 후보로 구성했습니다. 실제 제품의 호환성·BIOS·전력 여유는 별도 검증이 필요합니다.":"Built from fictional candidates with matching specs. Real compatibility, BIOS and power headroom need separate verification.",
  "월령과 안전 확인 절차를 보여주는 예시입니다. KC 인증·리콜·사용 가능 월령은 확인되지 않았습니다.":"A sample showing age and safety checks. KC certification, recalls and usable age range are not confirmed.",
  "리뷰 진위: 미확인":"Review authenticity: unverified",
  "실물 조합 검증 필요":"Physical build check needed",
  "인증·리콜 확인 필요":"Certification/recall check needed",
  "리뷰·근거 상세 ↗":"Reviews & evidence ↗",
  "리뷰·근거 상세":"Reviews & evidence",
  "후보 교체":"Swap candidate",
  "다른 후보로 교체":"Swap for another candidate",
  "예산과 구매 시점":"Budget and purchase timing",
  "품목":"Item",
  "예산 비중":"Budget share",
  "이 예시 세트는 예산을 초과합니다. 품목을 줄이거나 조건을 수정해 주세요. 더 낮은 가격의 후보로 재구성할 수도 있습니다.":"This sample set is over budget. Remove items or adjust conditions. You can also rebuild with lower-priced candidates.",
  "← 조건 수정":"← Edit conditions",
  "검증 과정 보기":"View verification steps",
  "다른 후보로 재구성":"Rebuild with other candidates",
  "다른 후보 재탐색":"Search other candidates",
  "입력한 용도와 예산에 맞춰 배분한 예시 후보입니다.":"A sample candidate allocated to your entered use and budget.",

  /* results V2 (computer) */
  "추천 구성을 확인해 보세요.":"Review the recommended build.",
  "사용 목적 미입력":"purpose not entered",
  "다른 구성 보기":"See another build",
  "현재 전체 후보 가격이 예산을 초과합니다. 품목을 빼거나 대체 후보를 선택해 주세요.":"The current candidate total is over budget. Remove items or pick alternative candidates.",
  "추천 부품 목록":"Recommended parts list",
  "입력한 용도와 예산에 맞춰 구성한 가상 후보입니다.":"A fictional candidate built to your entered use and budget.",
  "장바구니에 담기":"Add to basket",
  "장바구니에서 빼기":"Remove from basket",
  "추천 결과에 대해 더 물어보세요":"Ask more about the recommendations",
  "예: 그래픽카드 예산을 조금 낮춰줘":"e.g. lower the graphics-card budget a bit",
  "나의 장바구니":"My basket",
  "예상 합계":"Estimated total",
  "예상 총액":"Estimated total",
  "목표 가격":"Target price",
  "이 리스트로 확정하기 →":"Confirm this list →",
  "요청을 확인했어요. 각 부품을 펼쳐 두 후보를 비교하거나 장바구니 구성을 조정해 보세요.":"Got it. Expand each part to compare the two candidates, or adjust the basket.",
  "제품 이미지":"product image",
  "제품 이미지 영역":"product image area",
  "이미지":"image",
  "수량 늘리기":"Increase quantity",
  "수량 줄이기":"Decrease quantity",
  "현재 수량":"Current quantity",
  "수량":"quantity",
  "장바구니에서 삭제":"remove from basket",
  "개당":"each",
  "상품 페이지 ↗":"Product page ↗",
  "상품 페이지 링크는 아직 연결되지 않았습니다.":"The product-page link isn't connected yet.",

  /* review overlay */
  "REVIEW & EVIDENCE":"REVIEW & EVIDENCE",
  "리뷰·근거 상세 보기":"view reviews and evidence",
  "리뷰와 근거 상세 보기":"view reviews and evidence",
  "후보 2개 비교":"compare 2 candidates",
  "CHOOSE AN ALTERNATIVE":"CHOOSE AN ALTERNATIVE",
  "두 후보는 화면 구성을 위한 예시입니다. 가격과 규격을 비교해 하나를 선택하세요.":"The two candidates are samples for the screen. Compare price and spec, then pick one.",
  "균형형 후보":"Balanced pick",
  "절약형 후보":"Budget pick",
  "가격 절감형":"cost-reduced",
  "현재 선택":"current pick",
  "현재 후보 유지":"Keep current candidate",
  "이 후보로 교체":"Swap to this candidate",
  "리뷰를 읽기 전에":"Before reading reviews",
  "수집된 실제 리뷰가 없습니다. 아래 문장은 화면 구성을 위한 예시이며 평점·진위 확률을 산출하지 않았습니다.":"No real reviews were collected. The text below is a sample for the screen; no rating or authenticity probability was computed.",
  "정제 평점":"Refined rating",
  "검증한 리뷰":"Verified reviews",
  "항목별 요약 예시":"Sample summary by topic",
  "사용성":"Usability",
  "아쉬운 점":"Downsides",
  "구매 전 확인":"Check before buying",
  "일상 작업에서의 반응성을 살펴보세요.":"Look at responsiveness in everyday tasks.",
  "접기·세척·보관 방식이 생활에 맞는지 살펴보세요.":"Check whether folding, cleaning and storage fit your life.",
  "고부하 소음과 발열은 실측이 필요합니다.":"High-load noise and heat need real measurement.",
  "크기와 무게는 직접 확인이 필요합니다.":"Size and weight need to be checked in person.",
  "부품 규격과 제조사 지원 목록을 확인하세요.":"Check part specs and the maker's support list.",
  "제조사 사용 설명서와 인증·리콜 정보를 확인하세요.":"Check the maker's manual and certification/recall information.",
  "화면용 문장 · 출처 없음":"screen text · no source",
  "근거 문서":"Evidence documents",
  "근거 0건 · 검증 불가":"0 sources · not verifiable",
  "검색 근거 0건 · 검증 불가. 실제 문서가 연결되면 출처와 조회 시점을 함께 표시합니다.":"0 search sources · not verifiable. When real documents are connected, the source and lookup time are shown too.",
  "문서명, 인용 구간, 출처 링크, 게시·조회 시점은 실제 검색이 연결된 뒤 표시됩니다. 원문은 저장하지 않습니다.":"Document name, quoted passage, source link and post/lookup time appear once real search is connected. Original text is not stored.",
  "연결된 문서가 없습니다. 실제 서비스에서는 출처와 조회 시점을 함께 표시합니다.":"No documents are connected. A real service would show the source and lookup time.",
  "추천한 이유":"Why it was recommended",
  "입력한 용도와 예산을 기준으로 배분한 예시 후보입니다. 실제 성능 수치와 조합 호환성은 별도 확인이 필요합니다.":"A sample candidate allocated by your entered use and budget. Real performance figures and build compatibility need separate checking.",
  "실측 발열·소음, 제조사 지원 목록과 다른 부품의 규격을 함께 확인하세요.":"Check measured heat and noise, the maker's support list and the specs of other parts.",
  "리뷰 상태":"Review status",
  "수집된 실제 리뷰가 없어 평점과 리뷰 진위 여부는 확인되지 않았습니다.":"No real reviews were collected, so the rating and authenticity are unconfirmed.",
  "이 내용은 화면 체험을 위한 예시이며 실제 구매 판단용 검증 결과가 아닙니다.":"This content is a sample for screen experience, not real verification for a purchase decision.",
  "리뷰 수, 제외 비율과 평점은 화면 체험을 위한 가상의 예시이며 실제 검증 결과가 아닙니다.":"Review count, exclusion rate and rating are fictional samples for the screen, not real verification results.",
  "입력한 용도와 예산 안에서 부품 간 균형을 고려한 화면용 추천 후보입니다.":"A screen recommendation that balances the parts within your entered use and budget.",
  "아이 연령대와 필요한 영역, 건강·피부 특성 및 보유 물품을 반영한 화면용 추천 후보입니다.":"A screen recommendation reflecting the child's age group, needed areas, health/skin traits and owned items.",
  "실측 성능과 발열·소음, 부품 호환성 및 제조사 지원 목록을 구매 전에 확인하세요.":"Check measured performance, heat and noise, part compatibility and the maker's support list before buying.",
  "사용 가능 연령, 소재와 세척 방법, 안전 인증·리콜 정보 및 피부 적합성을 구매 전에 확인하세요.":"Check the usable age range, materials and cleaning method, safety certification/recall information and skin suitability before buying.",

  /* decision trace */
  "추천 과정을 한눈에.":"The recommendation process at a glance.",
  "설명용 단계 로그입니다. 실제 모델의 내부 추론이나 실행 로그가 아닙니다.":"An illustrative step log. Not a real model's internal reasoning or execution log.",
  "조건 정리":"Organize conditions",
  "요구사항 구성":"Assemble requirements",
  "예시 후보를 가격과 구성 기준으로 배치했습니다. 실제 데이터가 없어 상태는 Pending입니다.":"Sample candidates arranged by price and build. With no real data, status is Pending.",
  "예산 내 세트 구성":"Assemble a set within budget",
  "가상 후보의 합계를 계산해 한 세트로 구성합니다.":"Sum the fictional candidates into one set.",
  "완성 조합 검증":"Verify the finished build",
  "전력·병목·BIOS·발열·물리적 간섭 검증은 연결되지 않았습니다.":"Power, bottleneck, BIOS, heat and physical-clearance checks are not connected.",
  "품목별 검증":"Verify by item",
  "월령 적합성·KC 인증·리콜 이력·리뷰 진위를 각각 확인해야 합니다.":"Age suitability, KC certification, recall history and review authenticity each need checking.",
  "예산 배분":"Budget allocation",
  "품목별 금액과 지금 / 곧 / 나중 시점을 나눴습니다.":"Split amounts by item and timing into now / soon / later.",
  "근거 검색 및 설명":"Evidence search and explanation",
  "통과 / 탈락 / 확인 대기 기준":"Pass / fail / pending criteria",
  "Pass: 필수 조건 충족 확인 · Fail: 필수 조건 불충족 확인 · Pending: 정보 부족. 이 목업의 모든 안전·호환 검증은 Pending입니다.":"Pass: required conditions confirmed met · Fail: confirmed not met · Pending: not enough information. Every safety/compatibility check in this mockup is Pending.",
  "근거 기반 검토와 후보 교체":"Evidence-based review and candidate swapping",
  "컴퓨터는 조합 전체, 유아용품은 품목별로 반대 근거를 검토합니다. 실제 신뢰도 계산은 연결되지 않았으며, 신뢰도 80 미만 재탐색 흐름은 ‘다른 후보 재탐색’으로 체험할 수 있습니다.":"Computers are reviewed as a whole build, baby gear item by item, for counter-evidence. Real confidence scoring isn't connected; the “below-80 re-search” flow can be tried via “Search other candidates”.",

  /* confirm + auth */
  "이 장바구니로 준비할까요?":"Prepare with this basket?",
  "이름과 구매 예정일, 목표 가격을 정해 나만의 계획으로 저장해요.":"Set a name, planned purchase date and target price, and save it as your own plan.",
  "리스트 이름 *":"List name *",
  "구매 예정일 *":"Planned purchase date *",
  "목표 총액 (원) *":"Target total (KRW) *",
  "메모":"Memo",
  "나의 첫 컴퓨터":"My first computer",
  "우리 아이 준비 리스트":"My child's prep list",
  "체험 사용자로 저장합니다.":"Saving as a demo user.",
  "리스트 확정 단계에서 체험 로그인을 진행합니다. 실제 계정이나 비밀번호는 필요하지 않습니다.":"A demo sign-in happens at the confirm step. No real account or password is needed.",
  "← 다시 살펴보기":"← Look again",
  "리스트 확정하기":"Confirm list",
  "체험 로그인 후 확정하기":"Sign in (demo) and confirm",
  "실제 결제는 진행되지 않습니다.":"No real payment is made.",
  "예산을 초과했습니다. 추천 결과에서 구성을 조정해 주세요.":"Over budget. Adjust the build in the recommendations.",
  "체험용으로 계속할게요.":"Continuing in demo mode.",
  "실제 회원가입이나 인증 대신, 이 브라우저에서 사용할 이름만 입력하세요.":"Instead of real sign-up or verification, just enter a name to use in this browser.",
  "표시 이름":"Display name",
  "체험 사용자":"Demo user",
  "비밀번호와 개인정보는 입력하지 마세요. 입력 내용과 리스트는 이 브라우저에만 저장됩니다.":"Don't enter passwords or personal data. Your input and lists are saved only in this browser.",
  "체험 시작하기 →":"Start demo →",

  /* report */
  "저장된 리포트가 없어요.":"No saved report.",
  "추천 리스트를 확정하면 구매 계획을 다시 볼 수 있어요.":"Confirm a recommendation list to revisit your purchase plan.",
  "장바구니 만들기":"Build a basket",
  "리포트 인쇄 / PDF":"Print report / PDF",
  "리스트 파일 저장":"Save list file",
  "추천 다시 보기":"See recommendations again",
  "구매 리스트":"Purchase list",
  "품목 / 제품":"Item / product",
  "시점":"Timing",
  "예시 가격":"Sample price",
  "구매 연결":"Purchase link",
  "실제 판매처 미연결":"No real seller connected",
  "추가 메모가 없습니다.":"No additional memo.",
  "가격 추적":"Price tracking",
  "실시간 가격 수집은 연결되지 않았습니다. 목표가 도달 상태를 예시로 확인할 수 있어요.":"Live price collection isn't connected. You can preview a “target reached” state as a sample.",
  "목표가 도달 예시 · 실제 가격 아님":"Target-reached sample · not a real price",
  "추적 대기 · 수집된 가격 없음":"Awaiting tracking · no prices collected",
  "목표가 도달 예시 보기":"Preview target-reached sample",
  "알림 설정":"Alert settings",
  "목표가 알림 사용 (설정 예시)":"Use target-price alerts (setting sample)",
  "설정만 이 브라우저에 저장합니다. 이메일 발송과 백그라운드 추적은 실행되지 않습니다.":"Only the setting is saved in this browser. No email sending or background tracking runs.",
  "제품":"Product",
  "가격":"Price",
  "스펙":"Spec",
  "리뷰 지표 · 상세 리뷰":"Review metrics · detailed review",
  "추천 근거":"Recommendation basis",
  "확인 필요":"Check needed",
  "성능과 가격 균형에 대한 긍정 평가가 많으며, 발열·소음과 부품 호환성은 구매 전 확인이 필요합니다.":"Mostly positive on performance and price balance; heat, noise and part compatibility need checking before purchase.",
  "사용 편의성에 대한 긍정 평가가 많으며, 월령 적합성·세척 편의·안전성은 구매 전 확인이 필요합니다.":"Mostly positive on ease of use; age suitability, cleaning ease and safety need checking before purchase.",
  " 근거 문서는 아직 연결되지 않아 구매 전 확인이 필요합니다.":" Evidence documents aren't connected yet, so check before purchase.",
  "님의 계획":"'s plan",

  /* toasts / misc */
  "대체 후보 예시로 교체했습니다.":"Swapped to the alternative sample candidate.",
  "선택한 후보로 장바구니를 업데이트했습니다.":"Updated the basket with the selected candidate.",
  "장바구니를 삭제했습니다.":"Basket deleted.",
  "가격을 낮춘 대체 후보 예시로 재구성했습니다.":"Rebuilt with lower-priced sample candidates.",
  "기본 후보 예시로 재구성했습니다.":"Rebuilt with the default sample candidates.",
  "알림 설정 예시를 저장했습니다. 실제 이메일은 발송되지 않습니다.":"Saved the alert-setting sample. No real email is sent.",
  "브라우저 저장이 제한되어 이번 창에서만 유지됩니다. 파일로 저장해 주세요.":"Browser storage is restricted, so this is kept only for this window. Please save to a file.",
  "미입력":"not entered",
  "선택 전":"not selected",
  "나: ":"You: ",
  "오전":"AM",
  "오후":"PM",
  " 남아요.":" remaining.",
  "남아요.":"remaining.",
  "말씀하신 ":"For your stated ",
  " 조건에 맞춰 고른 육아용품 후보입니다.":" conditions, this is a chosen baby-gear candidate.",
  " 조건에 맞춰 구성한 합리적인 조합입니다.":" conditions, this is a sensible build.",
  "우리 아이 준비 리스트":"My child's prep list",
  "나의 첫 컴퓨터":"My first computer",

  /* hero + brand tagline */
  "잘 고르는 시작,":"A better way to start,",
  "진짜 나에게 맞는 조합을 찾아드립니다.":"We find the combination that truly fits you.",
  "어떻게 골라주나요?":"How does it choose?",
  "블루와 퍼플 조명이 비추는 집 안의 데스크톱 컴퓨터 공간":"A desktop computer setup in a home lit in blue and purple",

  /* sample product specs + names */
  "· 예시":"· sample",
  " 예시":" sample",
  "(예시)":"(sample)",
  " 인식":" detected",
  "6코어 · 소켓 A":"6 cores · socket A",
  "6코어":"6 cores",
  "자유 입력":"free notes",
  "자유 입력: ":"Free notes: ",
  "소켓 A · DDR5":"socket A · DDR5",
  "FHD용 가상 구성":"fictional FHD build",
  "정격 650W":"650W rated",
  "ATX · 여유 길이 340mm":"ATX · up to 340mm length",
  "공랭식 · 높이 155mm":"air cooling · 155mm height",
  "접이식 · 무게 6.8kg":"foldable · 6.8kg",
  "스탠드형 · 패브릭 장식":"stand type · fabric trim",
  "240ml · 2개 구성":"240ml · set of 2",

  /* part slot names not handled by displayPartSlot() */
  "메인보드":"Motherboard",
  "전원공급장치":"Power supply",
  "파워":"PSU",
  "케이스":"Case",
  "쿨러":"Cooler",
  "프로세서":"Processor",
  "그래픽카드":"Graphics card",
  "저장장치":"Storage",

  /* review score strip fragments */
  "리뷰 ":"Reviews ",
  "리뷰":"Reviews",
  "조작 의심 ":"suspected manipulation ",
  "% 제외":"% excluded",
  "% 제외 · 실사용 평점 ":"% excluded · real-user rating ",
  "건 · 조작 의심 ":" reviews · suspected manipulation ",
  " · 조작 의심 ":" · suspected manipulation ",
  "실사용 평점 ":"real-user rating ",
  "실사용 평점":"real-user rating",
  " / 상세 리뷰: ":" / detailed review: ",

  /* chat replies / notices not yet covered */
  "필요한 정보를 모두 확인했어요.":"I have everything I need.",
  "사양 파일 첨부: ":"Spec file attached: ",
  "조건을 변경했어요. 오른쪽에서 변경된 내용을 확인해 주세요.":"Conditions updated. Check the changes on the right.",
  "추가 조건이나 변경할 내용이 있다면 아래 대화창에 입력해 주세요.":"If you have more conditions or changes, type them in the chat below.",
  "추가 요청으로 저장했어요. 다른 조건을 바꾸려면 “예산을 150만원으로 변경해줘”처럼 말씀해 주세요.":"Saved as an extra request. To change another condition, say something like “change the budget to 1.5M”.",
  "추천 범위: 본체 부품 7개. 모니터·주변기기·운영체제·조립비는 포함하지 않는 예시입니다.":"Scope: 7 core parts. Monitor, peripherals, OS and assembly fee are not included in this sample.",
  "추천의 장점과 확인할 점을 함께 살펴보세요.":"Review both the strengths and the things to check.",
  "입력하신 사용 목적":"your stated purpose",

  /* decision trace fragments */
  "본체 7개 슬롯 / 용도 ":"7 core-part slots / use ",
  "필요 품목 ":"Needed items ",
  "필요 품목":"Needed items",
  "하드 필터 · 후보 순위":"Hard filter · candidate ranking",

  /* sidebar / report leftovers */
  "추천 장바구니":"recommended basket",
  "현재 상태: ":"Current status: ",
  "저장된 리포트가 없어요.":"No saved report.",
  "님의 계획 · ":"'s plan · ",
  " 구매 예정":" — planned purchase",
  " 품목을 포함한 예시 후보입니다.":" item.",
  "선택한 ":"A sample candidate including the selected ",
  "입력 용도와 예산에 맞춰 배분한 예시 후보입니다.":"A sample candidate allocated to the entered use and budget.",

  "나":"You"
 };

 /* ---- parametric patterns (run after digit-unit normalisation) ---- */
 var RX=[
  [/^(\d[\d,]*) months$/, "$1 months"],
  [/^([\d,]+)건$/, "$1"],
  [/^(.+?)님의 계획 · (.+?) 구매 예정$/, "$1's plan · buying around $2"],
  [/^저장 위치: 현재 브라우저 · 저장 시점 (.+?) · 인증·리콜·호환성 검증 전$/, "Stored in: this browser · saved $1 · before certification/recall/compatibility checks"],
  [/^입력 예산 (.+)$/, "Entered budget $1"],
  [/^파일에서 (.+?) 정보를 읽었어요\. (.+)$/, "Read $1 from the file. $2"],
  [/^(.+?)개월 \/ (.+)$/, "$1 months / $2"],
  [/^예산을 (.+?) 초과했어요\.$/, "Over budget by $1."],
  [/^(.+?) 초과했어요\.$/, "Over budget by $1."],
  [/^(.+) 제품 이미지 영역$/, "$1 product image area"],
  [/^(.+) 이미지$/, "$1 image"],
  [/^(.+) 수량$/, "$1 quantity"],
  [/^(.+) 장바구니에서 삭제$/, "Remove $1 from basket"],
  [/^(.+) 구매 시점$/, "$1 purchase timing"],
  [/^(.+) 리뷰와 근거 상세 보기$/, "View reviews and evidence for $1"],
  [/^(.+) 상품 페이지 열기$/, "Open the $1 product page"],
  [/^(.+) 이름 변경$/, "Rename $1"],
  [/^(.+) 삭제$/, "Delete $1"],
  [/^리뷰 (.+?)건 · 조작 의심 (.+?)% 제외 · 실사용 평점 (.+?) \/ 상세 리뷰: (.+)$/, "$1 reviews · $2% suspected-manipulation excluded · real-user rating $3 / detailed review: $4"],
  [/^(.+?)개월$/, "$1 months"]
 ];

 var KEYS=Object.keys(DICT).filter(function(k){return k.length>=2;})
   .sort(function(a,b){return b.length-a.length;});
 var HAN=/[가-힣]/;

 function subclean(x){
  if(!HAN.test(x)) return x;
  for(var j=0;j<KEYS.length;j++){ var k=KEYS[j]; if(x.indexOf(k)>=0) x=x.split(k).join(DICT[k]); }
  return x;
 }
 function tstr(s){
  if(s==null) return s;
  var str=String(s);
  if(!HAN.test(str)) return str;
  str=str.replace(/(\d[\d,]*)\s*원/g,"₩$1").replace(/(\d+)\s*개월/g,"$1 months");
  var key=str.trim();
  if(!HAN.test(key)) return str;
  var body=key;
  if(Object.prototype.hasOwnProperty.call(DICT,key)) body=DICT[key];
  else { for(var i=0;i<RX.length;i++){ if(RX[i][0].test(key)){ body=key.replace(RX[i][0],RX[i][1]); break; } } }
  body=subclean(body);
  if(body===key) return str;
  return str.replace(key,body);
 }

 var SKIP={SCRIPT:1,STYLE:1,NOSCRIPT:1,TEXTAREA:0};
 var ATTRS=["aria-label","placeholder","title","alt"];
 function translateTree(root){
  if(!root) return;
  if(root.nodeType===1){
   if(HAN.test(root.getAttribute&&(root.getAttribute("aria-label")||"")+" ")||true){
    for(var a=0;a<ATTRS.length;a++){
     if(root.hasAttribute&&root.hasAttribute(ATTRS[a])){
      var av=root.getAttribute(ATTRS[a]); if(HAN.test(av)){ var nv=tstr(av); if(nv!==av) root.setAttribute(ATTRS[a],nv); }
     }
    }
   }
   var kids=root.querySelectorAll?root.querySelectorAll("["+ATTRS.join("],[")+"]"):[];
   for(var q=0;q<kids.length;q++){
    var el=kids[q];
    for(var b=0;b<ATTRS.length;b++){
     if(el.hasAttribute(ATTRS[b])){
      var v=el.getAttribute(ATTRS[b]); if(HAN.test(v)){ var w=tstr(v); if(w!==v) el.setAttribute(ATTRS[b],w); }
     }
    }
   }
   /* default (un-typed) values on text inputs: only when the whole value is a known phrase */
   var ins=root.querySelectorAll?root.querySelectorAll("input:not([type]),input[type=text]"):[];
   for(var p=0;p<ins.length;p++){
    var iv=ins[p].value;
    if(iv && HAN.test(iv) && Object.prototype.hasOwnProperty.call(DICT,iv.trim())){
     ins[p].value=iv.replace(iv.trim(),DICT[iv.trim()]);
    }
   }
  }
  var tw=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode:function(n){
   return n.parentNode && !SKIP[n.parentNode.nodeName] && HAN.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
  }});
  var list=[],cur;
  while((cur=tw.nextNode())) list.push(cur);
  for(var t=0;t<list.length;t++){ var val=tstr(list[t].nodeValue); if(val!==list[t].nodeValue) list[t].nodeValue=val; }
 }

 /* ---- English-aware chat detectors (only when EN is active) ---- */
 function enableEnglishDetectors(){
  try{
   if(typeof buildModeFromMessage==="function"){ var _bm=buildModeFromMessage; buildModeFromMessage=function(v){ var t=String(v||""); if(/upgrad|replace|existing|\bcurrent\b.{0,15}\b(pc|computer|rig)|swap/i.test(t)) return "upgrade"; if(/\bnew\b.{0,15}\b(build|pc|computer|rig)|from scratch|build (a |an )?(pc|computer|rig)|assemble|first (pc|computer|build)/i.test(t)) return "new"; return _bm(v); }; }
   if(typeof upgradePartsFromMessage==="function"){ var _up=upgradePartsFromMessage; upgradePartsFromMessage=function(v){ var t=String(v||""); var p=_up(v)||[]; var add=function(re,l){ if(re.test(t)&&p.indexOf(l)<0) p.push(l); }; add(/\bcpu|processor\b/i,"CPU"); add(/\bgpu|graphics/i,"GPU"); add(/\bram|memory\b/i,"RAM"); add(/\bssd|hdd|storage|disk\b/i,"저장장치"); add(/motherboard|mainboard/i,"메인보드"); add(/\bpsu|power supply\b/i,"파워"); add(/\bcase|chassis\b/i,"케이스"); add(/cooler|cooling/i,"쿨러"); return p; }; }
   if(typeof usageFromMessage==="function"){ var _us=usageFromMessage; usageFromMessage=function(v){ var t=String(v||""); var f=[]; if(/gam(e|ing)/i.test(t)) f.push("게임"); if(/video|edit|premiere|after ?effect|render/i.test(t)) f.push("영상 편집"); if(/dev|coding|program|work|office/i.test(t)) f.push("개발 / 업무"); if(/study|class|lecture|everyday|browsing|internet|daily/i.test(t)) f.push("일상 / 학습"); var r=f.filter(function(x,i){return f.indexOf(x)===i;}).join(" · "); return r||_us(v); }; }
   if(typeof priorityFromMessage==="function"){ var _pr=priorityFromMessage; priorityFromMessage=function(v){ var t=String(v||""); if(/quiet|silent|noise/i.test(t)) return "조용한 사용"; if(/value|price|budget|cheap|balance/i.test(t)) return "가격 균형"; if(/performance|fast|high[- ]?end|fps|frame/i.test(t)) return "성능"; return _pr(v); }; }
   if(typeof budgetFromMessage==="function"){ var _bf=budgetFromMessage; budgetFromMessage=function(v){ var t=String(v||""); var m=t.match(/\$?\s*([\d,.]+)\s*(million|thousand|m|k)\b(?![a-rt-z])/i); if(m){ var n=parseFloat(m[1].replace(/,/g,"")); if(isFinite(n)&&n>0){ var u=m[2].toLowerCase(); n*=(u.charAt(0)==="m"?1e6:1e3); return Math.round(n); } } var nums=(t.match(/[\d,]{2,}(?:\.\d+)?/g)||[]).map(function(x){return parseFloat(x.replace(/,/g,""));}).filter(function(n){return isFinite(n)&&n>=10000;}); if(nums.length) return Math.round(Math.max.apply(null,nums)); return _bf(v); }; }
   if(typeof babyUnknownAnswer==="function"){ var _bu=babyUnknownAnswer; babyUnknownAnswer=function(v){ return /^(i\s*)?(don'?t know|do not know|not sure|no idea|dunno|unsure)\b/i.test(String(v||"").trim())||_bu(v); }; }
   if(typeof babyAgeFromMessage==="function"){ var _ba=babyAgeFromMessage; babyAgeFromMessage=function(v){ var t=String(v||""); var m=t.match(/(\d{1,2})\s*(months?|mos?|mo)\b/i); if(m) return m[1]+"개월"; m=t.match(/(\d{1,2})\s*(years?|yrs?|y)\b/i); if(m) return (Number(m[1])*12)+"개월"; if(/newborn/i.test(t)) return "신생아"; if(/weaning/i.test(t)) return "이유식기"; if(/toddler|walking/i.test(t)) return "걸음마기"; if(/infant/i.test(t)) return "영아"; return _ba(v); }; }
   if(typeof babyNeedsFromMessage==="function"){ var _bn=babyNeedsFromMessage; babyNeedsFromMessage=function(v){ var t=String(v||""); var r=_bn(v); var parts=r?r.split(", "):[]; var add=function(re,l){ if(re.test(t)&&parts.indexOf(l)<0) parts.push(l); }; add(/feed|bottle|formula|nursing|breast/i,"수유"); add(/meal|solid|weaning|utensil|snack/i,"이유식·식사"); add(/sleep|crib|bed|nap|blanket/i,"수면"); add(/outing|stroller|car ?seat|carrier|travel|trip/i,"외출"); add(/bath|hygiene|lotion|wash|shampoo/i,"목욕·위생"); add(/diaper|potty/i,"기저귀·배변"); add(/cloth|apparel|wear|shoe/i,"의류"); add(/play|develop|toy|book|mobile/i,"놀이"); add(/safety|health|fever|medicine|steriliz/i,"안전·건강"); return parts.join(", "); }; }
   if(typeof babyHealthFromMessage==="function"){ var _bh=babyHealthFromMessage; babyHealthFromMessage=function(v,b){ var t=String(v||""); if(/allerg|atopic|atopy|sensitiv|eczema|rash|hives|dry skin/i.test(t)){ var tr=[]; if(/allerg/i.test(t)) tr.push("알레르기"); if(/atopic|atopy/i.test(t)) tr.push("아토피"); if(/sensitiv/i.test(t)) tr.push("민감성 피부"); if(/dry/i.test(t)) tr.push("건조한 피부"); if(/eczema/i.test(t)) tr.push("습진"); if(/rash|hives/i.test(t)) tr.push("두드러기"); if(tr.length) return tr.filter(function(x,i){return tr.indexOf(x)===i;}).join(", "); } if(/\b(no|none|nothing|healthy|normal skin|no issues?)\b/i.test(t)) return "특이사항 없음"; return _bh(v,b); }; }
   if(typeof babyOwnedFromMessage==="function"){ var _bo=babyOwnedFromMessage; babyOwnedFromMessage=function(v,b){ var t=String(v||""); if(/\b(no|none|nothing|don'?t have|haven'?t|not yet)\b/i.test(t)) return "없음"; var map=[["유모차",/stroller/i],["카시트",/car ?seat/i],["아기띠",/carrier/i],["젖병",/bottle/i],["유축기",/breast ?pump/i],["아기침대",/crib|cot/i],["모빌",/mobile/i],["장난감",/toy/i],["기저귀",/diaper/i],["욕조",/bath ?tub|\btub\b/i],["로션",/lotion/i],["의류",/clothes|clothing/i]]; var f=map.filter(function(p){return p[1].test(t);}).map(function(p){return p[0];}); if(f.length) return f.filter(function(x,i){return f.indexOf(x)===i;}).join(", "); return _bo(v,b); }; }
  }catch(e){}
 }

 /* ---- toggle button ---- */
 function addToggle(){
  var b=document.createElement("button");
  b.id="lang-switch"; b.type="button";
  b.textContent = (lang==="en") ? "한국어" : "ENGLISH";
  b.setAttribute("aria-label", lang==="en" ? "한국어로 보기" : "View in English");
  b.style.cssText="position:fixed;right:18px;bottom:18px;z-index:99999;border:1px solid #314633;background:#fff;color:#222c23;border-radius:999px;padding:10px 17px;font-family:Arial,system-ui,sans-serif;font-weight:700;font-size:13px;line-height:1;letter-spacing:.3px;box-shadow:0 8px 24px rgba(24,35,25,.22);cursor:pointer";
  b.addEventListener("click",function(){
   try{ localStorage.setItem(LS, lang==="en" ? "ko" : "en"); }catch(e){}
   location.reload();
  });
  (document.body||document.documentElement).appendChild(b);
 }

 function boot(){
  addToggle();
  if(lang!=="en") return;
  document.documentElement.lang="en";
  enableEnglishDetectors();
  if(window.confirm){
   var _c=window.confirm.bind(window);
   window.confirm=function(m){ m=String(m||""); var mm=m.match(/^“(.+)” 장바구니를 삭제할까요\?$/); return _c(mm?('Delete the “'+tstr(mm[1])+'” basket?'):tstr(m)); };
  }
  try{ document.title=tstr(document.title); }catch(e){}
  translateTree(document.body);
  var timer=null, OPT={subtree:true,childList:true,characterData:true};
  function flush(){
   timer=null; mo.disconnect();
   try{ translateTree(document.body); }
   catch(e){}
   finally{ mo.observe(document.body,OPT); }
  }
  function schedule(){ if(timer) return; timer=setTimeout(flush,60); }
  var mo=new MutationObserver(schedule);
  mo.observe(document.body,OPT);
  window.addEventListener("hashchange",function(){ setTimeout(flush,0); setTimeout(flush,150); });
 }

 if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",boot);
 else boot();
})();
