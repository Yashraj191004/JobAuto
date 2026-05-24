// minimal background worker — just relays popup → content script clicks
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id) return;
  await chrome.tabs.sendMessage(tab.id, { type: "JA_TOGGLE" });
});
