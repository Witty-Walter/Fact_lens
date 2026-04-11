console.log("FactLens content script loaded on:", window.location.href);

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "GET_SELECTED_TEXT") {
    const selectedText = window.getSelection().toString().trim();

    sendResponse({
      selectedText: selectedText
    });
  }
});