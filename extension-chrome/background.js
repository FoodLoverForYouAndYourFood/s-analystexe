// Открытие боковой панели при клике на иконку расширения
chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ tabId: tab.id });
});
