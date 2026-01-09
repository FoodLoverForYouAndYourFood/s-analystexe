/*
  Content script для парсинга страниц вакансий.
  Пока не используется напрямую — парсинг идёт через chrome.scripting.executeScript
  
  Можно расширить для:
  - Добавления кнопки прямо на страницу вакансии
  - Автоматического анализа при открытии вакансии
  - Подсветки red flags в тексте
*/

console.log('Matcher: content script loaded');

// Пример: добавить кнопку на страницу hh.ru
// function injectButton() {
//   const header = document.querySelector('[data-qa="vacancy-title"]');
//   if (header && !document.getElementById('matcher-btn')) {
//     const btn = document.createElement('button');
//     btn.id = 'matcher-btn';
//     btn.innerText = '🎯 Проверить в Матчере';
//     btn.style.cssText = 'margin-left: 12px; padding: 8px 16px; background: #FCD34D; border: 2px solid #000; border-radius: 8px; font-weight: bold; cursor: pointer;';
//     btn.onclick = () => chrome.runtime.sendMessage({ action: 'openPopup' });
//     header.appendChild(btn);
//   }
// }
// injectButton();
