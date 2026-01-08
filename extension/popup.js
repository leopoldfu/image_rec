// popup.js

document.getElementById('activate_btn').addEventListener('click', async () => {
    let [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['content.js']
    });

    document.getElementById('status').innerText = "Picker Active...";
    window.close(); // Optional: Keep open or close? User usually wants to click page.
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
    const API_URL = "https://image-rec-439393162392.asia-east1.run.app/analyze"; // Use localhost for dev, or Cloud Run URL

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

        // Use Base64 thumbnail if available (fixes hotlink protection), else fallback to URL
        const imgSrc = res.thumbnail || (res.is_url ? res.filename : '');

        if (res.error) {
            div.innerHTML = `
                <div style="color:#ef4444; font-weight:bold; margin-bottom:0.5rem;">❌ Error</div>
                <div style="font-size:0.8rem; margin-bottom:0.5rem;">${res.error}</div>
                <div class="comp">
                     ${imgSrc ? `<img src="${imgSrc}" style="width:100%; height:auto; border-radius:4px;">` : ''}
                </div>
            `;
        } else if (match) {
            div.innerHTML = `
                <div class="match-badge">✅ ${match.score}</div>
                <div class="comp">
                    <img src="${imgSrc}">
                    <span class="vs">VS</span>
                    <a href="${match.path}" target="_blank"><img src="${match.path}"></a>
                </div>
                <div style="font-size:0.8rem; margin-top:0.5rem; color:#666;">
                    Client: <b>${match.client}</b>
                </div>
            `;
        } else {
            // Unique Case - Ensure image is visible
            div.innerHTML = `
                <div style="color:#10b981; font-weight:bold; margin-bottom:0.5rem;">🎉 Unique</div>
                <div class="comp">
                     <img src="${imgSrc}" style="width:100%; height:auto; border-radius:4px;">
                </div>
            `;
        }
        container.appendChild(div);
    });
}
