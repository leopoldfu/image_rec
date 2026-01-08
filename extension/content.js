(function () {
    console.clear();
    // alert("【✨ 抓圖 V5 啟動】\n\n已修正「抓到隔壁行」的問題！\n現在會精準鎖定您點擊的那個表格。");
    // Using a more subtle notification or keeping it as is? User asked for original logic.
    // I'll keep it mostly as is but maybe less invasive alerts if possible, 
    // BUT user said "why not using the original logic", so I should probably respect the alerts too?
    // I'll keep the alerts but maybe update text to mention the extension.

    console.log("Image Rec Grabber V5 Started");

    document.body.style.cursor = 'crosshair';

    // --- 核心：最原始的複製方法 (絕對相容) ---
    function forceCopy(text) {
        var textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.position = "fixed";
        textArea.style.left = "-9999px";
        textArea.style.top = "0";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();

        try {
            var successful = document.execCommand('copy');
            // Logic addition: Send to Extension
            var urlsArray = text.split('\n').filter(u => u);
            sendToExtension(urlsArray);

            if (successful) {
                // alert(`✅ 成功抓取！\n\n已複製 ${urlsArray.length} 個網址。\n精準鎖定單一表格欄位。`);
                // Let the sendToExtension handle the success alert to avoid double alerts?
                // Or just keep this one. 
            } else {
                prompt("瀏覽器限制，請手動複製：", text);
            }
        } catch (err) {
            prompt("複製失敗，請手動複製：", text);
        }
        document.body.removeChild(textArea);
    }

    function sendToExtension(urls) {
        // Save to storage
        if (chrome && chrome.storage) {
            chrome.storage.local.set({ captured_urls: urls }, function () {
                // Use a slightly modified alert to indicate strictly what happened
                alert(`✅ 成功抓取！\n\n已複製 ${urls.length} 個網址。\n👉 請再次點擊擴充功能圖示查看分析結果。`);
            });

            try {
                chrome.runtime.sendMessage({
                    action: "urls_captured",
                    urls: urls
                });
            } catch (e) { }
        } else {
            alert(`✅ 成功抓取！(擴充功能未偵測到)\n\n已複製 ${urls.length} 個網址。`);
        }
    }

    // --- 點擊偵測邏輯 ---
    function clickHandler(e) {
        e.preventDefault();
        e.stopPropagation();

        let target = e.target;
        let urls = [];

        // 1. 如果點到的是格子(td)或連結(a)，往內找圖片，方便判定
        if (target.tagName !== 'IMG') {
            let innerImg = target.querySelector('img');
            if (innerImg) target = innerImg;
        }

        // --- 情況 A: 點到圖片 (且不在表格內，或使用者想抓同類圖) ---
        // 邏輯：如果有 class 就抓同 class，沒有就抓單張
        if (target.tagName === 'IMG' && !target.closest('td')) {
            console.log("偵測到獨立圖片 (非表格模式)...");
            let signature = target.className;
            if (signature) {
                let cleanClass = signature.trim().replace(/\s+/g, '.');
                let allImgs = document.querySelectorAll('img.' + cleanClass);
                urls = Array.from(allImgs).map(img => img.src);
            } else {
                urls.push(target.src); // 沒 class 就只抓這一張
            }
        }
        // --- 情況 B: 點到表格格子 (這是修正重點) ---
        else if (target.closest('td')) {
            console.log("偵測到表格，啟動精準直行抓取...");

            let cell = target.closest('td');
            let targetIndex = cell.cellIndex; // 取得這是這一列的第幾格 (從0開始)
            let table = cell.closest('table'); // ★關鍵修正：鎖定這個表格

            if (!table) {
                alert("❌ 結構異常，找不到所屬表格。");
                cleanup();
                return;
            }

            // 遍歷這個表格的所有列 (Rows)
            for (let i = 0; i < table.rows.length; i++) {
                let row = table.rows[i];
                // 確保這一列有足夠的格子，且對應位置的格子存在
                if (row.cells.length > targetIndex) {
                    let targetCell = row.cells[targetIndex];
                    // 在格子裡找圖片
                    let imgsInCell = targetCell.querySelectorAll('img');
                    imgsInCell.forEach(img => {
                        if (img.src) urls.push(img.src);
                    });
                }
            }
        }
        else {
            alert("❌ 沒抓到！請點擊圖片或表格格子。");
            cleanup();
            return;
        }

        // --- 4. 過濾與輸出 ---
        let uniqueUrls = [...new Set(urls.filter(u => u && u.startsWith('http')))];

        if (uniqueUrls.length === 0) {
            alert("❌ 該區域找不到圖片網址。");
        } else {
            forceCopy(uniqueUrls.join('\n'));
        }

        cleanup();
    }

    function cleanup() {
        document.body.style.cursor = 'default';
        document.removeEventListener('click', clickHandler, true);
    }

    // 啟動監聽
    // Ensure we don't stack listeners if injected multiple times?
    // The user's script didn't check, but 'once: true' helps.
    // I'll stick to the original logic: just add the listener.
    document.addEventListener('click', clickHandler, { capture: true, once: true });
})();
