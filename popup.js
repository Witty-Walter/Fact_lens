const checkFactBtn = document.getElementById("checkFactBtn");
const checkImageBtn = document.getElementById("checkImageBtn");
const imageInput = document.getElementById("imageInput");

const statusDiv = document.getElementById("status");
const selectedTextBox = document.getElementById("selectedTextBox");
const verdictSpan = document.getElementById("verdict");
const confidenceSpan = document.getElementById("confidence");
const explanationSpan = document.getElementById("explanation");
const sourcesBox = document.getElementById("sourcesBox");
const imagesBox = document.getElementById("imagesBox");

function resetResultUI() {
  verdictSpan.textContent = "-";
  confidenceSpan.textContent = "-";
  explanationSpan.textContent = "-";
  sourcesBox.innerHTML = "-";
  imagesBox.innerHTML = "-";
}

function renderSources(sources) {
  if (!Array.isArray(sources) || sources.length === 0) {
    sourcesBox.textContent = "No sources available.";
    return;
  }

  sourcesBox.innerHTML = sources
    .map((source) => {
      if (typeof source === "string") {
        return `<div><a href="${source}" target="_blank">${source}</a></div>`;
      }

      const title = source.title || source.url || "Untitled Source";
      const url = source.url || "#";

      return `<div><a href="${url}" target="_blank">${title}</a></div>`;
    })
    .join("");
}

function renderImages(images) {
  if (!Array.isArray(images) || images.length === 0) {
    imagesBox.textContent = "No images available.";
    return;
  }

  imagesBox.innerHTML = images
    .map((url) => {
      return `
        <div class="image-card">
          <a href="${url}" target="_blank">
            <img src="${url}" alt="Related image" />
          </a>
        </div>
      `;
    })
    .join("");
}

async function handleTextFactCheck(text) {
  selectedTextBox.textContent = text;
  statusDiv.textContent = "Sending text to backend...";

  try {
    const backendResponse = await fetch("http://127.0.0.1:5000/check", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ text })
    });

    const data = await backendResponse.json();

    if (!backendResponse.ok) {
      statusDiv.textContent = "Backend returned an error.";
      verdictSpan.textContent = "Error";
      explanationSpan.textContent = data.error || "Unknown backend error.";
      renderSources([]);
      renderImages([]);
      return;
    }

    verdictSpan.textContent = data.verdict || "-";
    confidenceSpan.textContent =
      data.confidence !== undefined ? data.confidence : "-";
    explanationSpan.textContent = data.explanation || "-";

    renderSources(data.sources);
    renderImages(data.images);

    statusDiv.textContent = "Fact check completed.";
  } catch (error) {
    console.error("Fetch error:", error);
    statusDiv.textContent = "Could not connect to Flask backend.";
    verdictSpan.textContent = "Error";
    confidenceSpan.textContent = "-";
    explanationSpan.textContent =
      "Make sure Flask is running on http://127.0.0.1:5000";
    renderSources([]);
    renderImages([]);
  }
}

checkFactBtn.addEventListener("click", async () => {
  statusDiv.textContent = "Capturing selected text...";
  selectedTextBox.textContent = "Loading...";
  resetResultUI();

  try {
    const tabs = await chrome.tabs.query({
      active: true,
      currentWindow: true
    });

    const activeTab = tabs[0];

    if (!activeTab || !activeTab.id) {
      statusDiv.textContent = "Could not find active tab.";
      selectedTextBox.textContent = "No tab found.";
      return;
    }

    chrome.tabs.sendMessage(
      activeTab.id,
      { action: "GET_SELECTED_TEXT" },
      async (response) => {
        if (chrome.runtime.lastError) {
          console.error("Message error:", chrome.runtime.lastError.message);
          statusDiv.textContent = "Content script not available on this page.";
          selectedTextBox.textContent = "Refresh the webpage and try again.";
          return;
        }

        if (!response) {
          statusDiv.textContent = "No response received from page.";
          selectedTextBox.textContent = "Could not capture text.";
          return;
        }

        const selectedText = response.selectedText?.trim() || "";

        if (!selectedText) {
          statusDiv.textContent = "No text selected on the page.";
          selectedTextBox.textContent = "Please highlight some text first.";
          return;
        }

        await handleTextFactCheck(selectedText);
      }
    );
  } catch (error) {
    console.error("Unexpected error:", error);
    statusDiv.textContent = "Something went wrong.";
    selectedTextBox.textContent = error.message;
    verdictSpan.textContent = "Error";
    confidenceSpan.textContent = "-";
    explanationSpan.textContent = error.message;
    renderSources([]);
    renderImages([]);
  }
});

checkImageBtn.addEventListener("click", async () => {
  resetResultUI();

  const file = imageInput.files[0];

  if (!file) {
    statusDiv.textContent = "Please choose an image first.";
    selectedTextBox.textContent = "No image selected.";
    return;
  }

  statusDiv.textContent = "Uploading image and extracting text...";
  selectedTextBox.textContent = "Running OCR...";

  try {
    const formData = new FormData();
    formData.append("image", file);

    const backendResponse = await fetch("http://127.0.0.1:5000/check-image", {
      method: "POST",
      body: formData
    });

    const data = await backendResponse.json();

    if (!backendResponse.ok) {
      statusDiv.textContent = "Backend returned an error.";
      verdictSpan.textContent = "Error";
      confidenceSpan.textContent = "-";
      explanationSpan.textContent = data.error || "Unknown backend error.";
      selectedTextBox.textContent = "Could not extract text from image.";
      renderSources([]);
      renderImages([]);
      return;
    }

    selectedTextBox.textContent = data.extracted_text || "No text extracted.";
    verdictSpan.textContent = data.verdict || "-";
    confidenceSpan.textContent =
      data.confidence !== undefined ? data.confidence : "-";
    explanationSpan.textContent = data.explanation || "-";

    renderSources(data.sources);
    renderImages(data.images);

    statusDiv.textContent = "Image text fact check completed.";
  } catch (error) {
    console.error("Image fetch error:", error);
    statusDiv.textContent = "Could not connect to Flask backend.";
    verdictSpan.textContent = "Error";
    confidenceSpan.textContent = "-";
    explanationSpan.textContent =
      "Make sure Flask is running on http://127.0.0.1:5000";
    selectedTextBox.textContent = "Image OCR failed.";
    renderSources([]);
    renderImages([]);
  }
});