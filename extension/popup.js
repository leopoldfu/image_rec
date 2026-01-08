// popup.js

document.getElementById('activate_btn').addEventListener('click', async () => {
    let [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['content.js']
    });

    document.getElementById('status').innerText = "Picker Active...";
    window.close(); // Optional: Keep open or close? User usually wants to click page.
    // Actually, closing is better for UX if they need to click the page.
    // BUT, we need to receive the message. If popup closes, we lose context?
    // No, content script sends message to runtime. We can listen in background or keep popup open.
    // If we rely on popup to display results, we MUST keep popup open or use background script to open it again.
    // HOWEVER, clicking on the page usually closes the popup.
    // FIX: We probably need a background script to handle the message and store results/badge, 
    // OR we just tell the user "Click results here".
    // AND chrome.runtime.sendMessage from content script goes to background/popup.

    // BETTER UX for this specific "Grabber":
    // 1. Popup stays open? No, impossible if user clicks page.
    // 2. So content script runs -> sends message to BACKGROUND -> Background opens new tab or notification?
    // OR we use "sidepanel".

    // SIMPLE PLAN:
    // The user clicks "Activate". Popup sends script. Popup CLOSES.
    // User clicks table. Content script Gets URLs.
    // Content script uses `alert` to say "Captured!".
    // Content script could `window.open` the results? 
    // OR content script sends to background, background analyzes and shows notification?

    // Let's stick to the simplest flow that matches the user request: popup triggers, extension grabs.
    // Wait, the user said "Match Cards appear right inside the Extension Popup".
    // This implies the popup receives the data.
    // But if I click the page, popup closes.
    // Solution: The user clicks the extension icon *again* after capturing?

    // ALTERNATIVE: Use `chrome.storage.local`.
    // 1. Activate -> Inject.
    // 2. Content script saves URLs to storage.
    // 3. User opens Popup again -> Popup checks storage -> If URLs found, analyze.
});

// Listen for messages (just in case popup is open)
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "urls_captured") {
        const urls = request.urls;
        analyzeUrls(urls);
    }
});

// Check storage on load (Auto-Resume)
chrome.storage.local.get(['captured_urls'], (result) => {
    if (result.captured_urls) {
        console.log("Found cached URLs, analyzing...");
        analyzeUrls(result.captured_urls);
        // Clear after reading
        chrome.storage.local.remove('captured_urls');
    }
});

async function analyzeUrls(urls) {
    const loader = document.getElementById('loader');
    const container = document.getElementById('results');
    const btn = document.getElementById('activate_btn');

    loader.style.display = 'block';
    container.innerHTML = '';
    btn.style.display = 'none';

    // Call Backend
    const API_URL = "http://localhost:8080/analyze"; // Use localhost for dev, or Cloud Run URL

    try {
        const formData = new FormData();
        formData.append('urls', urls.join('\n'));

        const resp = await fetch(API_URL, {
            method: 'POST',
            body: formData
        });

        const results = await resp.json();
        renderResults(results);

    } catch (e) {
        container.innerHTML = `<div class="error">Error: ${e.message}<br>Make sure backend is running on port 8080.</div>`;
    } finally {
        loader.style.display = 'none';
        btn.style.display = 'block';
        btn.innerText = "Scan Again";
    }
}

function renderResults(results) {
    const container = document.getElementById('results');

    if (results.error) {
        container.innerHTML = `<div class="error">${results.error}</div>`;
        return;
    }

    results.forEach(res => {
        const match = res.matches && res.matches.length > 0 ? res.matches[0] : null;
        const div = document.createElement('div');
        div.className = 'result-card';

        if (match) {
            div.innerHTML = `
                <div class="match-badge">✅ ${match.score}</div>
                <div class="comp">
                    <img src="${res.is_url ? res.filename : ''}">
                    <span class="vs">VS</span>
                    <a href="${match.path}" target="_blank"><img src="${match.path}"></a>
                </div>
                <div style="font-size:0.8rem; margin-top:0.5rem; color:#666;">
                    Client: <b>${match.client}</b>
                </div>
            `;
        } else {
            div.innerHTML = `
                <div style="color:#10b981; font-weight:bold; margin-bottom:0.5rem;">🎉 Unique</div>
                <div class="comp">
                     <img src="${res.is_url ? res.filename : ''}">
                </div>
            `;
        }
        container.appendChild(div);
    });
}
