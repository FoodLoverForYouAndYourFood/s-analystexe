/*
  Матчер вакансий — Chrome Extension
  Работает полностью на клиенте с GigaChat API
*/

// ===== State =====
let profile = null;
let settings = null;
let resumeFile = null;
let resumeText = null;
let gigaChatToken = null;
let gigaChatTokenExpires = 0;

// ===== Init =====
document.addEventListener('DOMContentLoaded', async () => {
  await loadSettings();
  await loadProfile();
  initTabs();
  initButtons();
  initFileUpload();
  checkProfileExists();
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

// ===== Settings =====
async function loadSettings() {
  return new Promise((resolve) => {
    chrome.storage.local.get(['matcherSettings'], (result) => {
      if (result.matcherSettings) {
        settings = result.matcherSettings;
        document.getElementById('gigachat-auth-key').value = settings.authKey || '';
      }
      resolve();
    });
  });
}

function saveSettings() {
  settings = {
    authKey: document.getElementById('gigachat-auth-key').value.trim()
  };
  
  // Сбрасываем токен при смене ключа
  gigaChatToken = null;
  gigaChatTokenExpires = 0;
  
  chrome.storage.local.set({ matcherSettings: settings }, () => {
    const status = document.getElementById('settings-save-status');
    status.style.display = 'block';
    setTimeout(() => { status.style.display = 'none'; }, 2000);
    checkProfileExists();
  });
}

async function testApiConnection() {
  const btn = document.getElementById('test-api-btn');
  const status = document.getElementById('api-status');
  
  btn.disabled = true;
  btn.textContent = 'Проверяю...';
  status.style.display = 'block';
  status.className = 'api-status loading';
  status.textContent = '🔄 Подключаюсь к GigaChat...';
  
  try {
    const authKey = document.getElementById('gigachat-auth-key').value.trim();
    
    if (!authKey) {
      throw new Error('Введи Authorization Key');
    }
    
    // Получаем токен
    const token = await getGigaChatToken(authKey);
    
    if (token) {
      status.className = 'api-status success';
      status.textContent = '✅ Подключение успешно!';
    }
  } catch (error) {
    console.error(error);
    status.className = 'api-status error';
    status.textContent = '❌ ' + (error.message || 'Ошибка подключения');
  }
  
  btn.disabled = false;
  btn.textContent = '🧪 Проверить подключение';
}

// ===== GigaChat API =====
async function getGigaChatToken(authKey) {
  // Если токен ещё валиден — возвращаем его
  if (gigaChatToken && Date.now() < gigaChatTokenExpires - 60000) {
    return gigaChatToken;
  }
  
  const response = await fetch('https://ngw.devices.sberbank.ru:9443/api/v2/oauth', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Accept': 'application/json',
      'RqUID': crypto.randomUUID(),
      'Authorization': `Basic ${authKey}`
    },
    body: 'scope=GIGACHAT_API_PERS'
  });
  
  if (!response.ok) {
    const text = await response.text();
    console.error('OAuth error:', text);
    throw new Error('Ошибка авторизации. Проверь ключ.');
  }
  
  const data = await response.json();
  gigaChatToken = data.access_token;
  gigaChatTokenExpires = data.expires_at;
  
  return gigaChatToken;
}

async function callGigaChat(messages) {
  const token = await getGigaChatToken(settings.authKey);
  
  const response = await fetch('https://gigachat.devices.sberbank.ru/api/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({
      model: 'GigaChat',
      messages: messages,
      temperature: 0.3,
      max_tokens: 2000
    })
  });
  
  if (!response.ok) {
    const text = await response.text();
    console.error('GigaChat error:', text);
    throw new Error('Ошибка GigaChat API');
  }
  
  const data = await response.json();
  return data.choices[0].message.content;
}

// ===== File Upload =====
function initFileUpload() {
  const uploadArea = document.getElementById('file-upload-area');
  const fileInput = document.getElementById('resume-file');
  const removeBtn = document.getElementById('remove-file-btn');
  
  uploadArea.addEventListener('click', (e) => {
    if (e.target.id !== 'remove-file-btn') {
      fileInput.click();
    }
  });
  
  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      handleFile(e.target.files[0]);
    }
  });
  
  uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.classList.add('dragover');
  });
  
  uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('dragover');
  });
  
  uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  });
  
  removeBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    removeFile();
  });
}

async function handleFile(file) {
  const allowedTypes = ['application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain'];
  
  if (!allowedTypes.includes(file.type) && !file.name.match(/\.(pdf|doc|docx|txt)$/i)) {
    alert('Формат не поддерживается. Используй PDF, DOCX или TXT.');
    return;
  }
  
  resumeFile = file;
  
  document.getElementById('file-upload-content').style.display = 'none';
  document.getElementById('file-uploaded').style.display = 'flex';
  document.getElementById('uploaded-filename').textContent = file.name;
  
  await extractTextFromFile(file);
}

async function extractTextFromFile(file) {
  const preview = document.getElementById('parsed-preview');
  const content = document.getElementById('parsed-content');
  
  content.innerHTML = '<div style="color: #666;">📄 Читаю файл...</div>';
  preview.style.display = 'block';
  
  try {
    if (file.type === 'text/plain' || file.name.endsWith('.txt')) {
      // TXT — просто читаем
      resumeText = await file.text();
      
    } else if (file.type === 'application/pdf' || file.name.endsWith('.pdf')) {
      // PDF — пока просим конвертировать
      content.innerHTML = `
        <div style="color: #ca8a04;">
          ⚠️ PDF пока не поддерживается напрямую.<br>
          Открой PDF, выдели весь текст (Ctrl+A), скопируй и сохрани как TXT.
        </div>
      `;
      return;
      
    } else if (file.name.match(/\.docx?$/i)) {
      // DOCX — тоже просим конвертировать
      content.innerHTML = `
        <div style="color: #ca8a04;">
          ⚠️ DOCX пока не поддерживается напрямую.<br>
          Сохрани как TXT (Файл → Сохранить как → Тип: Обычный текст).
        </div>
      `;
      return;
    }
    
    if (resumeText && resumeText.length > 50) {
      const shortText = resumeText.substring(0, 300) + (resumeText.length > 300 ? '...' : '');
      content.innerHTML = `
        <div style="font-size: 12px; color: #666; margin-bottom: 8px;">✅ Текст извлечён (${resumeText.length} символов)</div>
        <div style="white-space: pre-wrap; font-size: 11px; max-height: 80px; overflow: auto; background: #f9f9f9; padding: 8px; border-radius: 6px;">${escapeHtml(shortText)}</div>
      `;
    } else {
      content.innerHTML = '<div style="color: #dc2626;">❌ Не удалось извлечь текст. Попробуй другой файл.</div>';
    }
    
  } catch (e) {
    console.error(e);
    content.innerHTML = '<div style="color: #dc2626;">❌ Ошибка чтения файла</div>';
  }
}

function removeFile() {
  resumeFile = null;
  resumeText = null;
  
  document.getElementById('file-upload-content').style.display = 'block';
  document.getElementById('file-uploaded').style.display = 'none';
  document.getElementById('resume-file').value = '';
  document.getElementById('parsed-preview').style.display = 'none';
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
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
  document.getElementById('salary-min').value = p.salary_min || '';
  document.getElementById('red-flags').value = (p.red_flags || []).join(', ');
  document.getElementById('must-have').value = (p.must_have || []).join(', ');
  
  document.getElementById('pref-remote').checked = (p.work_format || []).includes('remote');
  document.getElementById('pref-hybrid').checked = (p.work_format || []).includes('hybrid');
  document.getElementById('pref-office').checked = (p.work_format || []).includes('office');
  
  if (p.resume_text) {
    resumeText = p.resume_text;
    document.getElementById('file-upload-content').style.display = 'none';
    document.getElementById('file-uploaded').style.display = 'flex';
    document.getElementById('uploaded-filename').textContent = p.resume_filename || 'Резюме загружено';
    
    const preview = document.getElementById('parsed-preview');
    const content = document.getElementById('parsed-content');
    const shortText = resumeText.substring(0, 200) + '...';
    content.innerHTML = `<div style="font-size: 11px; color: #666;">${escapeHtml(shortText)}</div>`;
    preview.style.display = 'block';
  }
}

function saveProfile() {
  const work_format = [];
  if (document.getElementById('pref-remote').checked) work_format.push('remote');
  if (document.getElementById('pref-hybrid').checked) work_format.push('hybrid');
  if (document.getElementById('pref-office').checked) work_format.push('office');
  
  profile = {
    resume_text: resumeText,
    resume_filename: resumeFile?.name || profile?.resume_filename,
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
  
  if (!settings?.authKey) {
    warning.textContent = 'Сначала настрой API в ⚙️';
    warning.style.display = 'block';
    analyzeBtn.disabled = true;
  } else if (!profile || !profile.resume_text) {
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
  document.getElementById('save-settings-btn').addEventListener('click', saveSettings);
  document.getElementById('test-api-btn').addEventListener('click', testApiConnection);
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
    const prompt = buildAnalysisPrompt(vacancy);
    const response = await callGigaChat([
      { role: 'user', content: prompt }
    ]);
    
    // Парсим JSON из ответа
    const jsonMatch = response.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      throw new Error('Не удалось получить структурированный ответ');
    }
    
    const data = JSON.parse(jsonMatch[0]);
    displayResults(data);
    
    status.style.display = 'none';
    results.style.display = 'block';
    
  } catch (error) {
    console.error(error);
    status.className = 'status error';
    status.textContent = '❌ ' + (error.message || 'Ошибка анализа');
  }
  
  btn.disabled = false;
}

function buildAnalysisPrompt(vacancy) {
  const workFormatText = profile.work_format?.length 
    ? profile.work_format.map(f => f === 'remote' ? 'удалёнка' : f === 'hybrid' ? 'гибрид' : 'офис').join(', ')
    : 'не указан';
  
  return `Ты — карьерный консультант. Проанализируй, насколько вакансия подходит кандидату.

ПРОФИЛЬ КАНДИДАТА:

Резюме:
${profile.resume_text}

Минимальная зарплата: ${profile.salary_min || 'не указана'}
Желаемый формат работы: ${workFormatText}
Red flags (не хочет): ${profile.red_flags?.join(', ') || 'нет'}
Must have (обязательно): ${profile.must_have?.join(', ') || 'нет'}

ВАКАНСИЯ:
${vacancy}

Проанализируй и ответь СТРОГО в формате JSON без дополнительного текста:

{
  "score": <число от 1 до 10>,
  "verdict": "<краткий вывод в 1 предложение>",
  "matches": [
    {"item": "<что проверял>", "status": "<match|partial|gap>", "comment": "<пояснение>"}
  ],
  "quick_wins": ["<совет 1>", "<совет 2>"]
}

Обязательно проверь:
1. Совпадение навыков из резюме с требованиями
2. Зарплату (если указана в вакансии)
3. Формат работы (удалёнка/офис/гибрид)
4. Наличие red flags кандидата в тексте вакансии
5. Наличие must have кандидата в вакансии

status значения:
- match = полное совпадение
- partial = частичное совпадение или требует уточнения
- gap = не совпадает или red flag`;
}

// ===== Display Results =====
function displayResults(data) {
  const container = document.getElementById('results');
  
  const scoreColor = data.score >= 7 ? 'match' : data.score >= 5 ? 'partial' : 'gap';
  
  let matchesHtml = data.matches.map(m => {
    const icon = m.status === 'match' ? '✅' : m.status === 'partial' ? '🟡' : '❌';
    const colorClass = m.status;
    return `
      <div class="result-item">
        <span class="result-icon">${icon}</span>
        <div>
          <span class="${colorClass}" style="font-weight: 600;">${m.item}</span>
          <div style="color: #666; font-size: 12px;">${m.comment}</div>
        </div>
      </div>
    `;
  }).join('');
  
  let quickWinsHtml = data.quick_wins.map((w, i) => `
    <div class="quick-win-item">
      <span class="quick-win-num">${i + 1}</span>
      <span>${w}</span>
    </div>
  `).join('');
  
  container.innerHTML = `
    <div class="result-card">
      <div class="result-header">
        <span class="result-score ${scoreColor}">${data.score}/10</span>
        <span class="result-verdict">${data.verdict}</span>
      </div>
      ${matchesHtml}
    </div>
    
    <div class="quick-wins">
      <div class="quick-wins-title">⚡ Что сделать</div>
      ${quickWinsHtml}
    </div>
    
    <button class="btn btn-secondary" style="margin-top: 12px;" onclick="resetAnalysis()">
      ← Проверить другую
    </button>
  `;
}

function resetAnalysis() {
  document.getElementById('vacancy-text').value = '';
  document.getElementById('results').style.display = 'none';
}

window.resetAnalysis = resetAnalysis;
