(function () {
    console.log("Image Rec Grabber content script loaded.");

    // Check if duplicate injector
    if (window.hasImageRecGrabber) return;
    window.hasImageRecGrabber = true;

    alert("【✨ Grabber Active】\nPlease click on a table or image to capture URLs.");
    document.body.style.cursor = 'crosshair';

    // --- Click Logic ---
    function clickHandler(e) {
        e.preventDefault();
        e.stopPropagation();

        let target = e.target;
        let urls = [];

        // 1. Dig deeper if clicked on wrapper
        if (target.tagName !== 'IMG') {
            let innerImg = target.querySelector('img');
            if (innerImg) target = innerImg;
        }

        // A. Single / Class Image
        if (target.tagName === 'IMG' && !target.closest('td')) {
            console.log("Single image mode...");
            let signature = target.className;
            if (signature) {
                let cleanClass = signature.trim().replace(/\s+/g, '.');
                let allImgs = document.querySelectorAll('img.' + cleanClass);
                urls = Array.from(allImgs).map(img => img.src);
            } else {
                urls.push(target.src);
            }
        }
        // B. Table Mode
        else if (target.closest('td')) {
            console.log("Table mode...");
            let cell = target.closest('td');
            let targetIndex = cell.cellIndex;
            let table = cell.closest('table');

            if (table) {
                for (let i = 0; i < table.rows.length; i++) {
                    let row = table.rows[i];
                    if (row.cells.length > targetIndex) {
                        let targetCell = row.cells[targetIndex];
                        let imgsInCell = targetCell.querySelectorAll('img');
                        imgsInCell.forEach(img => {
                            if (img.src) urls.push(img.src);
                        });
                    }
                }
            }
        }

        // --- Filter & Send ---
        let uniqueUrls = [...new Set(urls.filter(u => u && u.startsWith('http')))];

        if (uniqueUrls.length === 0) {
            alert("❌ No image URLs found.");
        } else {
            console.log("Captured URLs:", uniqueUrls);

            // Save to storage for Popup to pick up
            chrome.storage.local.set({ captured_urls: uniqueUrls }, function () {
                alert(`✅ Captured ${uniqueUrls.length} images!\n\n👉 Open the Extension Popup again to see results.`);
            });

            // Still send message if open (rare)
            try {
                chrome.runtime.sendMessage({
                    action: "urls_captured",
                    urls: uniqueUrls
                });
            } catch (e) { }

            // alert(`✅ Captured ${uniqueUrls.length} images! Analysis starting...`); // Removed redundant alert
        }

        cleanup();
    }

    function cleanup() {
        document.body.style.cursor = 'default';
        document.removeEventListener('click', clickHandler, true);
        window.hasImageRecGrabber = false;
    }

    document.addEventListener('click', clickHandler, { capture: true, once: true });

})();
