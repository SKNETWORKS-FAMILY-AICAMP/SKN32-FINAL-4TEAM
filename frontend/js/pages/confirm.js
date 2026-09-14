const TF_CONFIRM_DRAFT_KEY = 'truefit-confirm-draft';

function tfConfirmDefaultName(name, isPc, english) {
  if (!english) {
    return name || (isPc ? '나의 첫 컴퓨터' : '우리 아이 준비 리스트');
  }

  if (!name || ['새 추천', '컴퓨터 장바구니', '유아용품 장바구니'].includes(name)) {
    return isPc ? 'My first computer' : 'Baby preparation list';
  }

  return name;
}

function confirmPage() {
  if (!tfPlan.listId) return go('category');

  const result = tfPlan.result;
  if (!result || result.list_id !== tfPlan.listId) {
    return tfLoadResult(confirmPage, 3);
  }
  if (result.status !== 'done' || !(result.totals && result.totals.selected_units)) {
    return go('results');
  }

  const english = tfIsEnglish();
  const auth = readAuthSession();
  const summary = tfListSummary();
  const isPc = summary.category === 'computer';
  const today = new Date().toISOString().slice(0, 10);
  let draft = {};

  try {
    draft = JSON.parse(sessionStorage.getItem(TF_CONFIRM_DRAFT_KEY) || '{}');
  } catch (_) {
    draft = {};
  }

  const defaultName = tfConfirmDefaultName(draft.name || tfPlan.name, isPc, english);
  const accountName = esc((auth && auth.name) || (english ? 'Member' : '회원'));
  const notice = auth
    ? (english ? `Save to ${accountName}'s account.` : `${accountName}님 계정에 저장합니다.`)
    : (english
      ? 'You can review the list first, then sign in to save it.'
      : '먼저 리스트를 확인한 뒤 로그인하여 저장할 수 있어요.');

  const body =
    heading(
      english ? 'Ready to save this list?' : '이 장바구니로 준비할까요?',
      english
        ? 'Review the list name and target date before confirming.'
        : '리스트 이름과 목표일을 확인한 뒤 확정해 주세요.'
    ) +
    '<form class="tf-confirm-form" onsubmit="tfSubmitConfirm(this);return false">' +
      field(
        english ? 'List name' : '리스트 이름',
        'name',
        defaultName,
        english ? 'For example: My first computer' : '예: 나의 첫 컴퓨터'
      ) +
      field(english ? 'Target date' : '목표일', 'target_date', draft.target_date || today, '', 'date') +
      '<p class="tf-save-notice">' + notice + '</p>' +
      '<div class="tf-actions">' +
        '<button type="button" class="tf-btn tf-btn-secondary" onclick="go(\'results\')">← ' +
          (english ? 'Look again' : '다시 보기') +
        '</button>' +
        '<button type="submit" class="tf-btn tf-btn-primary">' +
          (english ? 'Confirm list →' : '리스트 확정하기 →') +
        '</button>' +
      '</div>' +
    '</form>';

  shell(body, 3);
}

async function tfSubmitConfirm(form) {
  const english = tfIsEnglish();
  const name = form.name.value.trim();
  const targetDate = form.target_date.value;
  const submitButton = form.querySelector('[type="submit"]');

  if (!name) {
    alert(english ? 'Please enter a list name.' : '리스트 이름을 입력해 주세요.');
    return;
  }
  if (!targetDate) {
    alert(english ? 'Please select a target date.' : '목표일을 선택해 주세요.');
    return;
  }

  const draft = { name, target_date: targetDate };
  sessionStorage.setItem(TF_CONFIRM_DRAFT_KEY, JSON.stringify(draft));
  submitButton.disabled = true;
  submitButton.textContent = english ? 'Saving…' : '저장하는 중…';

  try {
    const response = await TF_PLAN.confirm({
      list_id: tfPlan.listId,
      name,
      target_date: targetDate,
    });

    tfPlan.name = response.name || name;
    tfPlan.result = { ...(tfPlan.result || {}), ...response, status: response.status || 'done' };
    tfPlan.save();
    sessionStorage.removeItem(TF_CONFIRM_DRAFT_KEY);
    go('report');
  } catch (error) {
    submitButton.disabled = false;
    submitButton.textContent = english ? 'Confirm list →' : '리스트 확정하기 →';
    alert(
      english
        ? (error.message || 'Could not save the list. Please try again.')
        : (error.message || '리스트를 저장하지 못했습니다. 다시 시도해 주세요.')
    );
  }
}

shell(tfStatusPanel(tfIsEnglish() ? 'Checking sign-in status…' : '로그인 상태를 확인하고 있어요…'), 3);
TF_AUTH.ready.then(() => confirmPage());
flow.addEventListener('tf-auth-changed', () => confirmPage());
