/*
  Матчер вакансий — Chrome Extension
  Работает через локальный сервер API
*/

// ===== Config =====
const API_URL = 'https://d.analystexe.ru';
const MATCHER_WEB_URL = 'https://d.analystexe.ru';

// ===== State =====
let profile = null;

// ===== Init =====
document.addEventListener('DOMContentLoaded', async () => {
  await loadProfile();
  initTabs();
  initButtons();
  checkProfileExists();

  // Автоматически очистить поле при переходе на новую вакансию
  let lastUrl = '';
  setInterval(async () => {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (tab && tab.url !== lastUrl) {
        lastUrl = tab.url;
        // Очистить результаты при смене страницы
        document.getElementById('results').style.display = 'none';
      }
    } catch (e) {
      // Игнорируем ошибки
    }
  }, 1000);
});

// ===== Tabs =====
function initTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const tabName = tab.dataset.tab;

      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');

      document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
      document.getElementById(`${tabName}-section`).classList.add('active');
    });
  });
}

// ===== API Calls =====
async function analyzeVacancyAPI(vacancyText, profile) {
  const headers = {
    'Content-Type': 'application/json'
  };
  if (profile?.api_key) {
    headers.Authorization = `Bearer ${profile.api_key}`;
  }

  const response = await fetch(`${API_URL}/api/analyze`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      vacancy_text: vacancyText,
      profile: {
        resume_text: profile.resume_text,
        salary_min: profile.salary_min,
        work_format: profile.work_format,
        red_flags: profile.red_flags,
        must_have: profile.must_have
      }
    })
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Server error');
  }

  return await response.json();
}


// ===== Profile =====
async function loadProfile() {
  return new Promise((resolve) => {
    chrome.storage.local.get(['matcherProfile'], (result) => {
      if (result.matcherProfile) {
        profile = result.matcherProfile;
        fillProfileForm(profile);
      }
      resolve();
    });
  });
}

function fillProfileForm(p) {
  document.getElementById('resume-text').value = p.resume_text || '';
  document.getElementById('api-key').value = p.api_key || '';
  document.getElementById('salary-min').value = p.salary_min || '';
  document.getElementById('red-flags').value = (p.red_flags || []).join(', ');
  document.getElementById('must-have').value = (p.must_have || []).join(', ');

  document.getElementById('pref-remote').checked = (p.work_format || []).includes('remote');
  document.getElementById('pref-hybrid').checked = (p.work_format || []).includes('hybrid');
  document.getElementById('pref-office').checked = (p.work_format || []).includes('office');
}

function saveProfile() {
  const resumeText = document.getElementById('resume-text').value.trim();

  if (!resumeText || resumeText.length < 50) {
    alert('Добавь текст резюме (минимум 50 символов)');
    return;
  }

  const work_format = [];
  if (document.getElementById('pref-remote').checked) work_format.push('remote');
  if (document.getElementById('pref-hybrid').checked) work_format.push('hybrid');
  if (document.getElementById('pref-office').checked) work_format.push('office');

  profile = {
    resume_text: resumeText,
    api_key: document.getElementById('api-key').value.trim(),
    salary_min: document.getElementById('salary-min').value.trim(),
    work_format,
    red_flags: document.getElementById('red-flags').value.split(',').map(s => s.trim()).filter(Boolean),
    must_have: document.getElementById('must-have').value.split(',').map(s => s.trim()).filter(Boolean)
  };

  chrome.storage.local.set({ matcherProfile: profile }, () => {
    const status = document.getElementById('save-status');
    status.style.display = 'block';
    setTimeout(() => { status.style.display = 'none'; }, 2000);
    checkProfileExists();
  });
}

function checkProfileExists() {
  const warning = document.getElementById('no-profile-warning');
  const analyzeBtn = document.getElementById('analyze-btn');

  if (!profile || !profile.api_key) {
    warning.textContent = 'Добавь API key в профиле';
    warning.style.display = 'block';
    analyzeBtn.disabled = true;
  } else if (!profile.resume_text) {
    warning.textContent = 'Загрузи резюме в 👤 Профиль';
    warning.style.display = 'block';
    analyzeBtn.disabled = true;
  } else {
    warning.style.display = 'none';
    analyzeBtn.disabled = false;
  }
}

// ===== Buttons =====
function initButtons() {
  document.getElementById('save-profile-btn').addEventListener('click', saveProfile);
  document.getElementById('grab-btn').addEventListener('click', grabFromPage);
  document.getElementById('analyze-btn').addEventListener('click', analyzeVacancy);
  document.getElementById('open-matcher-btn').addEventListener('click', () => {
    chrome.tabs.create({ url: MATCHER_WEB_URL });
  });
}

// ===== Grab from page =====
async function grabFromPage() {
  const btn = document.getElementById('grab-btn');
  btn.disabled = true;
  btn.textContent = 'Получаю...';

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      function: extractVacancyText
    });

    if (results && results[0] && results[0].result) {
      document.getElementById('vacancy-text').value = results[0].result;
    } else {
      document.getElementById('vacancy-text').value = 'Не удалось получить текст. Вставь вручную.';
    }
  } catch (e) {
    console.error(e);
    document.getElementById('vacancy-text').value = 'Ошибка. Вставь текст вручную.';
  }

  btn.disabled = false;
  btn.textContent = '📋 Взять со страницы';
}

function extractVacancyText() {
  const selectors = [
    '[data-qa="vacancy-description"]',
    '.vacancy-description',
    '.jobs-description',
    '.jobs-box__html-content',
    '.vacancy-description__text',
    '.job_show_description',
    '[class*="vacancy"]',
    '[class*="job-description"]',
    'article',
    'main'
  ];

  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el && el.innerText.length > 200) {
      return el.innerText.trim();
    }
  }

  const selection = window.getSelection().toString();
  if (selection.length > 100) {
    return selection;
  }

  return document.body.innerText.substring(0, 5000);
}

// ===== Analyze =====
async function analyzeVacancy() {
  const vacancy = document.getElementById('vacancy-text').value.trim();

  if (!vacancy) {
    alert('Вставь текст вакансии');
    return;
  }

  if (vacancy.length < 100) {
    alert('Текст слишком короткий. Нужен полный текст вакансии.');
    return;
  }

  const status = document.getElementById('status-message');
  const results = document.getElementById('results');
  const btn = document.getElementById('analyze-btn');

  btn.disabled = true;
  status.style.display = 'block';
  status.className = 'status loading';
  status.textContent = '🔍 Анализирую вакансию...';
  results.style.display = 'none';

  try {
    const data = await analyzeVacancyAPI(vacancy, profile);
    displayResults(data);

    status.style.display = 'none';
    results.style.display = 'block';

  } catch (error) {
    console.error(error);
    status.className = 'status error';
    status.textContent = '❌ ' + (error.message || 'Ошибка анализа. Проверь что сервер запущен на localhost:5000');
  }

  btn.disabled = false;
}

// ===== Display Results =====
function displayResults(data) {
  const container = document.getElementById('results');

  const scoreColor = data.score >= 7 ? 'match' : data.score >= 5 ? 'partial' : 'gap';

  // Компания
  let companyHtml = '';
  if (data.company && data.company.name !== 'не указано') {
    companyHtml = `
      <div class="info-section">
        <div class="info-title">🏢 ${data.company.name}</div>
        <div class="info-text">${data.company.info || ''}</div>
      </div>
    `;
  }

  // Совпадения
  let matchesHtml = (data.matches || []).map(m => {
    const icon = m.status === 'match' ? '✅' : m.status === 'partial' ? '🟡' : '❌';
    const colorClass = m.status;
    return `
      <div class="match-row">
        <span class="match-icon">${icon}</span>
        <div class="match-content">
          <div class="match-label ${colorClass}">${m.item}</div>
          <div class="match-comment">${m.comment}</div>
        </div>
      </div>
    `;
  }).join('');

  // Детали
  let detailsHtml = '';
  if (data.details) {
    const items = [];
    if (data.details.career && data.details.career !== 'не указано') {
      items.push(`<div class="detail-item"><b>Карьера:</b> ${data.details.career}</div>`);
    }
    if (data.details.stack && data.details.stack !== 'не указано') {
      items.push(`<div class="detail-item"><b>Стек:</b> ${data.details.stack}</div>`);
    }
    if (data.details.team && data.details.team !== 'не указано') {
      items.push(`<div class="detail-item"><b>Команда:</b> ${data.details.team}</div>`);
    }

    if (items.length > 0) {
      detailsHtml = `
        <div class="info-section">
          <div class="info-title">📋 Детали</div>
          ${items.join('')}
        </div>
      `;
    }
  }

  // Плюсы и минусы
  let prosConsHtml = '';
  if (data.pros_cons && (data.pros_cons.pros?.length || data.pros_cons.cons?.length)) {
    const prosHtml = (data.pros_cons.pros || []).map(p => `<div class="pc-item pros">✓ ${p}</div>`).join('');
    const consHtml = (data.pros_cons.cons || []).map(c => `<div class="pc-item cons">✗ ${c}</div>`).join('');

    prosConsHtml = `
      <div class="pros-cons">
        <div class="pc-col">
          <div class="pc-title pros-title">Плюсы</div>
          ${prosHtml}
        </div>
        <div class="pc-col">
          <div class="pc-title cons-title">Минусы</div>
          ${consHtml}
        </div>
      </div>
    `;
  }

  // Рекомендация
  let recommendationHtml = '';
  if (data.recommendation) {
    const actionsHtml = (data.recommendation.actions || []).map((a, i) => `
      <div class="action-item">
        <span class="action-num">${i + 1}</span>
        <span class="action-text">${a}</span>
      </div>
    `).join('');

    recommendationHtml = `
      <div class="recommendation">
        <div class="rec-decision">${data.recommendation.decision || 'Рекомендация'}</div>
        ${actionsHtml}
      </div>
    `;
  }

  container.innerHTML = `
    <div class="result-score-card">
      <div class="score-big ${scoreColor}">${data.score}/10</div>
      <div class="verdict">${data.verdict}</div>
    </div>

    ${companyHtml}

    <div class="matches-card">
      ${matchesHtml}
    </div>

    ${detailsHtml}
    ${prosConsHtml}
    ${recommendationHtml}

    <button class="btn btn-secondary" style="margin-top: 16px;" onclick="resetAnalysis()">
      ← Проверить другую
    </button>
  `;
}

function resetAnalysis() {
  document.getElementById('vacancy-text').value = '';
  document.getElementById('results').style.display = 'none';
}

window.resetAnalysis = resetAnalysis;
