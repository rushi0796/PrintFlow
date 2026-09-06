// ======================================================
// PRINTFLOW - FULL APP & ADMIN DASHBOARD LOGIC
// ======================================================

const DB_NAME = "PrintFlowDB";
const STORE_NAME = "pdfStore";
const isLocalDevelopment = ["localhost", "127.0.0.1"].includes(window.location.hostname) || window.location.protocol === "file:";
const API_BASE = isLocalDevelopment ? "http://127.0.0.1:8000" : "";
const apiUrl = (localPath, productionPath = localPath) => `${API_BASE}${isLocalDevelopment ? localPath : productionPath}`;

function getAuthHeaders(customHeaders = {}) {
    const headers = { ...customHeaders };
    const mobile = (localStorage.getItem("mobileNumber") || "").trim();
    if (mobile) {
        headers["X-Customer-Mobile"] = mobile;
    }
    const isAdminUnlocked = sessionStorage.getItem("printflowAdminUnlocked") === "true";
    if (isAdminUnlocked) {
        headers["X-Admin-Token"] = "Admin@123";
    }
    return headers;
}

async function fetchWithRetry(url, options = {}, retries = 3, backoff = 500) {
    options.headers = getAuthHeaders(options.headers || {});
    for (let i = 0; i < retries; i++) {
        try {
            const res = await fetch(url, options);
            if (res.ok) return res;
            if (i === retries - 1) return res;
        } catch (err) {
            if (i === retries - 1) throw err;
        }
        await new Promise(r => setTimeout(r, backoff * Math.pow(2, i)));
    }
}
const orderUpdateChannel = typeof BroadcastChannel !== "undefined"
    ? new BroadcastChannel("printflow-order-updates")
    : null;

function publishOrderUpdate(order) {
    if (!order) return;
    const message = { order, updatedAt: Date.now() };
    if (orderUpdateChannel) orderUpdateChannel.postMessage(message);
    localStorage.setItem("printflowOrderUpdated", JSON.stringify(message));
}

if (typeof pdfjsLib !== "undefined") {
    pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
}

function openPdfDB() {
    return new Promise((resolve) => {
        if (!window.indexedDB) {
            resolve(null);
            return;
        }
        const request = indexedDB.open(DB_NAME, 1);
        request.onupgradeneeded = (e) => {
            const db = e.target.result;
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME);
            }
        };
        request.onsuccess = (e) => resolve(e.target.result);
        request.onerror = (e) => {
            console.warn("IndexedDB open note:", e.target.error);
            resolve(null);
        };
    });
}

function savePdfFile(file) {
    if (!file) return Promise.resolve(null);
    return new Promise((resolve) => {
        try {
            console.log("Saving PDF to IndexedDB:", file?.name);
            localStorage.setItem("fileName", file.name);
            localStorage.setItem("fileSize", String(file.size));
            localStorage.setItem("fileType", file.type || "application/pdf");
            localStorage.setItem("fileLastModified", String(file.lastModified));

            const reader = new FileReader();
            reader.onload = function (e) {
                try {
                    sessionStorage.setItem("pdfDataUrl", e.target.result);
                } catch (err) {
                    console.warn("sessionStorage quota note:", err);
                }
            };
            reader.readAsDataURL(file);

            openPdfDB().then(db => {
                if (!db) {
                    resolve(file);
                    return;
                }
                const tx = db.transaction(STORE_NAME, "readwrite");
                const store = tx.objectStore(STORE_NAME);
                const putReq = store.put(file, "currentPdf");

                putReq.onsuccess = () => {
                    console.log("PDF successfully stored in IndexedDB");
                };

                tx.oncomplete = () => {
                    resolve(file);
                };

                tx.onerror = () => {
                    resolve(file);
                };
            });
        } catch (err) {
            console.warn("savePdfFile error:", err);
            resolve(file);
        }
    });
}

function getSavedPdfFile() {
    return new Promise((resolve) => {
        if (window.selectedPdfFile) {
            resolve(window.selectedPdfFile);
            return;
        }

        openPdfDB().then(db => {
            if (!db) {
                resolve(null);
                return;
            }
            try {
                const tx = db.transaction(STORE_NAME, "readonly");
                const store = tx.objectStore(STORE_NAME);
                const req = store.get("currentPdf");
                req.onsuccess = (e) => {
                    const fileObj = e.target.result;
                    if (fileObj) {
                        window.selectedPdfFile = fileObj;
                        resolve(fileObj);
                    } else {
                        resolve(null);
                    }
                };
                req.onerror = () => resolve(null);
            } catch (err) {
                resolve(null);
            }
        });
    });
}

function clearSavedPdfFile() {
    return new Promise((resolve) => {
        window.selectedPdfFile = null;
        openPdfDB().then(db => {
            if (!db) {
                resolve();
                return;
            }
            try {
                const tx = db.transaction(STORE_NAME, "readwrite");
                const store = tx.objectStore(STORE_NAME);
                store.delete("currentPdf");
                tx.oncomplete = () => resolve();
                tx.onerror = () => resolve();
            } catch (err) {
                resolve();
            }
        });
    });
}

/* ======================================================
   MULTIPLE FILE UPLOAD ENGINE
   ====================================================== */

let fileQueue = []; // Array of item objects
let isQueueProcessing = false;

function generateFileId(file) {
    const safeName = (file.name || "file").replace(/[^a-zA-Z0-9]/g, "_");
    return `file_${safeName}_${file.size}_${file.lastModified || 0}`;
}

function formatFileSize(bytes) {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

function getFileTypeDetails(file) {
    const ext = (file.name || "").split('.').pop().toLowerCase();
    if (ext === "pdf" || file.type === "application/pdf") {
        return { category: "pdf", icon: "📄", badge: "PDF" };
    }
    if (["png", "jpg", "jpeg", "webp"].includes(ext) || (file.type && file.type.startsWith("image/"))) {
        return { category: "image", icon: "🖼️", badge: "IMG" };
    }
    if (["doc", "docx"].includes(ext)) {
        return { category: "doc", icon: "📝", badge: "DOC" };
    }
    return { category: "txt", icon: "📑", badge: "TXT" };
}

function updateContinueButtonState() {
    const continueBtn = document.getElementById("continueBtn");
    if (!continueBtn) return;

    const activeItems = fileQueue.filter(i => i.status !== "CANCELED");
    if (activeItems.length === 0) {
        continueBtn.disabled = true;
        continueBtn.style.opacity = "0.5";
        continueBtn.style.cursor = "not-allowed";
        return;
    }

    const allUploaded = activeItems.every(i => i.status === "UPLOADED");
    if (allUploaded) {
        continueBtn.disabled = false;
        continueBtn.style.opacity = "1";
        continueBtn.style.cursor = "pointer";
    } else {
        continueBtn.disabled = true;
        continueBtn.style.opacity = "0.5";
        continueBtn.style.cursor = "not-allowed";
    }
}

function updateOverallUploadSummary() {
    const queueCard = document.getElementById("uploadQueueCard");
    const mainStatus = document.getElementById("queueMainStatus");
    const subStatus = document.getElementById("queueSubStatus");
    const statusIcon = document.getElementById("queueSummaryIcon");
    const progressBar = document.getElementById("overallProgressBar");
    const addMoreBtn = document.getElementById("addMoreBtn");

    if (!queueCard) return;

    const activeItems = fileQueue.filter(i => i.status !== "CANCELED");
    if (activeItems.length === 0) {
        queueCard.style.display = "none";
        if (addMoreBtn) addMoreBtn.style.display = "none";
        if (progressBar) progressBar.style.width = "0%";
        updateTotalPagesDisplay(0);
        updateContinueButtonState();
        return;
    }

    queueCard.style.display = "block";
    if (addMoreBtn) addMoreBtn.style.display = "inline-flex";

    const totalCount = activeItems.length;
    const uploadedCount = activeItems.filter(i => i.status === "UPLOADED").length;
    const failedCount = activeItems.filter(i => i.status === "FAILED").length;
    const uploadingIndex = activeItems.findIndex(i => i.status === "UPLOADING");

    let totalProgressSum = 0;
    activeItems.forEach(i => {
        if (i.status === "UPLOADED") totalProgressSum += 100;
        else if (i.status === "UPLOADING") totalProgressSum += (i.progress || 0);
    });
    const overallPct = Math.round(totalProgressSum / totalCount);
    if (progressBar) progressBar.style.width = `${overallPct}%`;

    if (uploadingIndex !== -1) {
        const currentNum = uploadingIndex + 1;
        if (statusIcon) statusIcon.textContent = "⏳";
        if (mainStatus) mainStatus.textContent = `Uploading ${currentNum} of ${totalCount} file${totalCount > 1 ? 's' : ''}...`;
        if (subStatus) subStatus.textContent = `${uploadedCount} of ${totalCount} completed • Uploading ${activeItems[uploadingIndex].name}`;
    } else if (uploadedCount === totalCount) {
        if (statusIcon) statusIcon.textContent = "✓";
        if (mainStatus) mainStatus.textContent = `✓ All ${totalCount} file${totalCount > 1 ? 's' : ''} uploaded successfully`;
        if (subStatus) subStatus.textContent = "All documents ready for print configuration";
    } else if (failedCount > 0) {
        if (statusIcon) statusIcon.textContent = "⚠️";
        if (mainStatus) mainStatus.textContent = `⚠️ ${failedCount} of ${totalCount} file${totalCount > 1 ? 's' : ''} failed to upload`;
        if (subStatus) subStatus.textContent = `${uploadedCount} of ${totalCount} completed • Click Retry on failed file`;
    } else {
        if (statusIcon) statusIcon.textContent = "○";
        if (mainStatus) mainStatus.textContent = `Ready to upload ${totalCount} file${totalCount > 1 ? 's' : ''}`;
        if (subStatus) subStatus.textContent = "Upload starting...";
    }

    calculateAndUpdateTotalPages();
    saveUploadStateToLocalStorage();
    updateContinueButtonState();
}

function calculateAndUpdateTotalPages() {
    const activeItems = fileQueue.filter(i => i.status !== "CANCELED");
    let totalPages = 0;
    activeItems.forEach(item => {
        totalPages += (item.pages || 1);
    });
    updateTotalPagesDisplay(totalPages);
}

function updateTotalPagesDisplay(count) {
    const pageCountDisplay = document.getElementById("pageCount");
    const pageCounterCard = document.getElementById("pageCounterCard");

    if (pageCountDisplay) {
        pageCountDisplay.textContent = count;
    }
    if (pageCounterCard) {
        if (count > 0) pageCounterCard.classList.add("is-visible");
        else pageCounterCard.classList.remove("is-visible");
    }
}

function saveUploadStateToLocalStorage() {
    const activeItems = fileQueue.filter(i => i.status !== "CANCELED");
    if (activeItems.length === 0) {
        localStorage.removeItem("fileName");
        localStorage.removeItem("pdfPageCount");
        localStorage.removeItem("backendFilePath");
        localStorage.removeItem("fileListDetails");
        return;
    }

    const fileNamesStr = activeItems.map(i => i.name).join(", ");
    let totalPages = 0;
    activeItems.forEach(i => { totalPages += (i.pages || 1); });

    const uploadedItems = activeItems.filter(i => i.status === "UPLOADED");
    const primaryPath = uploadedItems.length > 0 ? uploadedItems[0].backendPath : "";

    const detailsList = activeItems.map(i => ({
        name: i.name,
        size: i.size,
        pages: i.pages,
        path: i.backendPath,
        status: i.status,
        sequence: i.sequence
    }));

    localStorage.setItem("fileName", fileNamesStr);
    localStorage.setItem("pdfPageCount", String(totalPages));
    if (primaryPath) {
        localStorage.setItem("backendFilePath", primaryPath);
    }
    localStorage.setItem("fileListDetails", JSON.stringify(detailsList));

    if (activeItems.length > 0 && activeItems[0].file) {
        if (typeof renderPdfFirstPageThumbnail === "function") {
            renderPdfFirstPageThumbnail(activeItems[0].file);
        }
        savePdfFile(activeItems[0].file);
    }
}

function renderFileRowUI(item) {
    const listContainer = document.getElementById("fileQueueList");
    if (!listContainer) return;

    let row = document.getElementById(`row_${item.id}`);
    if (!row) {
        row = document.createElement("div");
        row.id = `row_${item.id}`;
        row.className = "file-row";
        row.setAttribute("data-type", item.typeCategory);
        listContainer.appendChild(row);
    }

    let statusBadgeHtml = "";
    let progressWrapClass = "file-progress-bar-wrap";
    let actionsHtml = "";

    if (item.status === "WAITING") {
        statusBadgeHtml = `<span class="file-status-badge status-waiting">○ Waiting</span>`;
        actionsHtml = `<button type="button" class="btn-remove-file" onclick="removeFileFromQueue('${item.id}')" title="Remove file">✕</button>`;
    } else if (item.status === "UPLOADING") {
        statusBadgeHtml = `<span class="file-status-badge status-uploading">Uploading...</span>`;
        progressWrapClass += " is-active";
        actionsHtml = `<button type="button" class="btn-remove-file" onclick="removeFileFromQueue('${item.id}')" title="Cancel upload">✕</button>`;
    } else if (item.status === "UPLOADED") {
        statusBadgeHtml = `<span class="file-status-badge status-uploaded">✓ Uploaded</span>`;
        actionsHtml = `<button type="button" class="btn-remove-file" onclick="removeFileFromQueue('${item.id}')" title="Remove file">✕</button>`;
    } else if (item.status === "FAILED") {
        const errorText = item.error || "Failed";
        statusBadgeHtml = `<span class="file-status-badge status-failed">✕ ${errorText}</span>`;
        actionsHtml = `
            <button type="button" class="btn-retry-file" onclick="retryFileInQueue('${item.id}')" title="Retry upload">Retry</button>
            <button type="button" class="btn-remove-file" onclick="removeFileFromQueue('${item.id}')" title="Remove file">✕</button>
        `;
    }

    row.innerHTML = `
        <div class="file-icon-badge" aria-hidden="true">${item.typeIcon}</div>
        <div class="file-info-col">
            <span class="file-name-text" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span>
            <div class="file-meta-row">
                <span>${formatFileSize(item.size)}</span>
                <span>•</span>
                <span>${item.pages} page${item.pages > 1 ? 's' : ''}</span>
                <span>•</span>
                ${statusBadgeHtml}
            </div>
            <div class="${progressWrapClass}">
                <div class="file-progress-bar-fill" style="width: ${item.progress}%;"></div>
            </div>
        </div>
        <div class="file-actions-col">
            ${actionsHtml}
        </div>
    `;
}

function updateFileRowProgressUI(fileId, percent) {
    const row = document.getElementById(`row_${fileId}`);
    if (!row) return;
    const progressFill = row.querySelector(".file-progress-bar-fill");
    const statusBadge = row.querySelector(".file-status-badge");
    if (progressFill) progressFill.style.width = `${percent}%`;
    if (statusBadge) statusBadge.textContent = "Uploading...";
}

function escapeHtml(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function countPdfPages(file) {
    if (!file) return 1;
    const isPdf = (file.type === "application/pdf") || ((file.name || "").toLowerCase().endsWith(".pdf"));
    if (!isPdf) return 1;
    if (typeof pdfjsLib === "undefined") return 1;

    try {
        const arrayBuffer = await file.arrayBuffer();
        const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
        return (pdf && pdf.numPages) ? pdf.numPages : 1;
    } catch (err) {
        console.warn("countPdfPages fallback:", err);
        return 1;
    }
}

async function uploadPdfToBackend(file) {
    if (!file) return null;
    const formData = new FormData();
    formData.append("file", file, file.name);
    const response = await fetch(apiUrl("/upload-pdf", "/api/upload-pdf"), {
        method: "POST",
        headers: getAuthHeaders(),
        body: formData
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status !== "success") {
        throw new Error(data.detail || `Upload failed (HTTP ${response.status})`);
    }
    return { ok: true, data };
}

async function handleFileSelection(eventOrFiles) {
    let rawFiles = [];
    if (eventOrFiles && eventOrFiles.target && eventOrFiles.target.files) {
        rawFiles = Array.from(eventOrFiles.target.files);
    } else if (Array.isArray(eventOrFiles)) {
        rawFiles = eventOrFiles;
    } else if (eventOrFiles instanceof FileList) {
        rawFiles = Array.from(eventOrFiles);
    } else if (eventOrFiles instanceof File) {
        rawFiles = [eventOrFiles];
    }
    if (!rawFiles.length) return;

    const pdfErrorMsg = document.getElementById("pdfErrorMsg");
    if (pdfErrorMsg) pdfErrorMsg.style.display = "none";

    const allowedExtensions = ["pdf", "png", "jpg", "jpeg", "webp", "doc", "docx", "txt"];
    let nextSequence = fileQueue.length + 1;

    for (const file of rawFiles) {
        const ext = (file.name || "").split('.').pop().toLowerCase();
        if (!allowedExtensions.includes(ext)) {
            console.warn(`File '${file.name}' rejected: unsupported extension .${ext}`);
            continue;
        }

        const fileId = generateFileId(file);
        if (fileQueue.some(i => i.id === fileId && i.status !== "CANCELED")) {
            console.log(`File '${file.name}' already exists in upload queue.`);
            continue;
        }

        const typeInfo = getFileTypeDetails(file);
        const item = {
            id: fileId,
            file: file,
            name: file.name,
            size: file.size,
            typeCategory: typeInfo.category,
            typeIcon: typeInfo.icon,
            status: "WAITING",
            progress: 0,
            pages: 1,
            backendPath: "",
            xhr: null,
            error: null,
            sequence: nextSequence++
        };

        fileQueue.push(item);
        renderFileRowUI(item);

        if (ext === "pdf" || file.type === "application/pdf") {
            countPdfPages(file).then(pages => {
                item.pages = pages;
                renderFileRowUI(item);
                calculateAndUpdateTotalPages();
                saveUploadStateToLocalStorage();
            }).catch(err => {
                item.pages = 1;
                renderFileRowUI(item);
            });
        }
    }

    updateOverallUploadSummary();
    processUploadQueue();
}
window.handleFileSelection = handleFileSelection;

async function uploadSingleFile(item) {
    item.status = "UPLOADING";
    item.progress = 0;
    renderFileRowUI(item);
    updateOverallUploadSummary();

    const formData = new FormData();
    formData.append("file", item.file, item.name);

    try {
        const response = await fetch(apiUrl("/upload-pdf", "/api/upload-pdf"), {
            method: "POST",
            headers: getAuthHeaders(),
            body: formData
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status !== "success" || !data.file_path) {
            throw new Error(data.detail || `Upload failed (HTTP ${response.status})`);
        }

        item.status = "UPLOADED";
        item.progress = 100;
        item.backendPath = data.file_path;
        item.error = null;
    } catch (err) {
        item.status = "FAILED";
        item.progress = 0;
        item.error = err.message || "Network error";
    }

    renderFileRowUI(item);
    updateOverallUploadSummary();
}

async function processUploadQueue() {
    if (isQueueProcessing) return;

    const nextItem = fileQueue.find(i => i.status === "WAITING");
    if (!nextItem) {
        updateOverallUploadSummary();
        return;
    }

    isQueueProcessing = true;
    try {
        await uploadSingleFile(nextItem);
    } finally {
        isQueueProcessing = false;
    }

    updateOverallUploadSummary();
    processUploadQueue();
}

function removeFileFromQueue(fileId) {
    const idx = fileQueue.findIndex(i => i.id === fileId);
    if (idx === -1) return;

    const item = fileQueue[idx];
    if (item.xhr) {
        try { item.xhr.abort(); } catch(e) {}
    }
    item.status = "CANCELED";

    fileQueue.splice(idx, 1);

    const row = document.getElementById(`row_${fileId}`);
    if (row && row.parentNode) {
        row.parentNode.removeChild(row);
    }

    isQueueProcessing = false;
    updateOverallUploadSummary();
    processUploadQueue();
}
window.removeFileFromQueue = removeFileFromQueue;

function retryFileInQueue(fileId) {
    const item = fileQueue.find(i => i.id === fileId);
    if (!item) return;

    item.status = "WAITING";
    item.progress = 0;
    item.error = null;
    renderFileRowUI(item);
    isQueueProcessing = false;
    updateOverallUploadSummary();
    processUploadQueue();
}
window.retryFileInQueue = retryFileInQueue;

function clearAllFilesFromQueue() {
    fileQueue.forEach(item => {
        if (item.xhr) {
            try { item.xhr.abort(); } catch(e) {}
        }
    });

    fileQueue = [];
    isQueueProcessing = false;
    const listContainer = document.getElementById("fileQueueList");
    if (listContainer) listContainer.innerHTML = "";

    updateOverallUploadSummary();
}
window.clearAllFilesFromQueue = clearAllFilesFromQueue;

// Attach Upload UI Event Listeners
document.addEventListener("DOMContentLoaded", function() {
    const userMobileDisplay = document.getElementById("userMobileDisplay");
    const mobile = (localStorage.getItem("mobileNumber") || "").trim();
    if (userMobileDisplay && mobile) {
        userMobileDisplay.textContent = `+91 ${mobile}`;
    }

    const dropzone = document.getElementById("uploadDropzone");
    const fileInput = document.getElementById("pdfFile");
    const choosePdfBtn = document.getElementById("choosePdfBtn");
    const addMoreBtn = document.getElementById("addMoreBtn");
    const clearAllBtn = document.getElementById("clearAllBtn");
    const toggleQueueBtn = document.getElementById("toggleQueueBtn");
    const continueBtn = document.getElementById("continueBtn");

    if (choosePdfBtn && fileInput) {
        choosePdfBtn.addEventListener("click", function(e) {
            e.stopPropagation();
            fileInput.value = "";
            fileInput.click();
        });
    }

    if (addMoreBtn && fileInput) {
        addMoreBtn.addEventListener("click", function(e) {
            e.stopPropagation();
            fileInput.value = "";
            fileInput.click();
        });
    }

    if (fileInput) {
        fileInput.addEventListener("change", function(e) {
            handleFileSelection(e);
        });
    }

    if (dropzone) {
        dropzone.addEventListener("click", function(e) {
            if (e.target.closest("button")) return;
            if (fileInput) {
                fileInput.value = "";
                fileInput.click();
            }
        });

        ["dragenter", "dragover"].forEach(evtName => {
            dropzone.addEventListener(evtName, function(e) {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.add("is-dragover");
            }, false);
        });

        ["dragleave", "drop"].forEach(evtName => {
            dropzone.addEventListener(evtName, function(e) {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.remove("is-dragover");
            }, false);
        });

        dropzone.addEventListener("drop", function(e) {
            const dt = e.dataTransfer;
            if (dt && dt.files && dt.files.length) {
                handleFileSelection(dt.files);
            }
        }, false);
    }

    if (clearAllBtn) {
        clearAllBtn.addEventListener("click", function(e) {
            e.stopPropagation();
            clearAllFilesFromQueue();
        });
    }

    if (toggleQueueBtn) {
        toggleQueueBtn.addEventListener("click", function(e) {
            e.stopPropagation();
            const queueList = document.getElementById("fileQueueList");
            const toggleText = document.getElementById("toggleQueueText");
            if (queueList) {
                const isExpanded = queueList.classList.contains("is-expanded");
                if (isExpanded) {
                    queueList.classList.remove("is-expanded");
                    queueList.classList.add("is-collapsed");
                    if (toggleText) toggleText.textContent = "▴ Details";
                    toggleQueueBtn.setAttribute("aria-expanded", "false");
                } else {
                    queueList.classList.remove("is-collapsed");
                    queueList.classList.add("is-expanded");
                    if (toggleText) toggleText.textContent = "▾ Details";
                    toggleQueueBtn.setAttribute("aria-expanded", "true");
                }
            }
        });
    }

    if (continueBtn) {
        continueBtn.addEventListener("click", function(e) {
            if (e && e.preventDefault) e.preventDefault();
            const pdfErrorMsg = document.getElementById("pdfErrorMsg");
            const activeItems = fileQueue.filter(i => i.status !== "CANCELED");

            const savedName = localStorage.getItem("fileName");
            if (activeItems.length === 0 && (!savedName || savedName === "No File Selected")) {
                if (pdfErrorMsg) pdfErrorMsg.style.display = "block";
                return;
            }

            const isStillUploading = activeItems.some(i => i.status === "UPLOADING" || i.status === "WAITING");
            const hasFailed = activeItems.some(i => i.status === "FAILED");
            if (isStillUploading || hasFailed) {
                if (pdfErrorMsg) {
                    pdfErrorMsg.textContent = isStillUploading
                        ? "Please wait for files to finish uploading before continuing"
                        : "Please retry failed uploads before continuing";
                    pdfErrorMsg.style.display = "block";
                }
                return;
            }

            window.location.href = "print-details.html";
        });
    }
});

// Centralized Canonical Pricing Rules
const PRICING = {
    bw_single: 2.0,       // ₹2 / page
    bw_double: 1.0,       // ₹1 / page
    color_single: 6.0,    // ₹6 / page
    color_double: null,   // REMOVED
    micro_xerox_sheet: 3.0 // ₹3 / sheet
};

function calculatePrice(pages, copies, colorMode, printSide, printMode, pagesPerSheet) {
    pages = Math.max(1, parseInt(pages || "1", 10));
    copies = Math.max(1, parseInt(copies || "1", 10));
    pagesPerSheet = Math.max(1, parseInt(pagesPerSheet || "1", 10));

    if (printMode === "micro_xerox" && pagesPerSheet > 1) {
        const sheets = Math.ceil(pages / pagesPerSheet);
        return parseFloat((sheets * copies * PRICING.micro_xerox_sheet).toFixed(2));
    }

    if (colorMode === "color") {
        return parseFloat((pages * copies * PRICING.color_single).toFixed(2));
    } else {
        if (printSide === "double") {
            return parseFloat((pages * copies * PRICING.bw_double).toFixed(2));
        } else {
            return parseFloat((pages * copies * PRICING.bw_single).toFixed(2));
        }
    }
}

function updatePrintDetailsAndPreview() {
    const copiesBox = document.getElementById("copies");
    const totalPriceBox = document.getElementById("totalPrice");
    const paperSheetPreview = document.getElementById("paperSheetPreview");
    const standardPreviewContent = document.getElementById("standardPreviewContent");
    const nupPreviewGrid = document.getElementById("nupPreviewGrid");
    const microXeroxSection = document.getElementById("microXeroxSection");
    const previewLabelBadge = document.getElementById("previewLabelBadge");
    const doubleSideLabel = document.getElementById("doubleSideLabel");
    const radioDoubleSide = document.getElementById("radioDoubleSide");

    if (!totalPriceBox && !paperSheetPreview) return;

    const pageCount = Number(localStorage.getItem("pdfPageCount")) || 1;
    const copies = copiesBox ? (Number(copiesBox.value) || 1) : 1;

    const printModeEl = document.querySelector('input[name="printMode"]:checked');
    const printMode = printModeEl ? printModeEl.value : "standard";

    const colorModeEl = document.querySelector('input[name="colorMode"]:checked');
    const colorMode = colorModeEl ? colorModeEl.value : "black_white";

    const printSideEl = document.querySelector('input[name="printSide"]:checked');
    let printSide = printSideEl ? printSideEl.value : "single";

    const orientationEl = document.querySelector('input[name="orientation"]:checked');
    const orientation = orientationEl ? orientationEl.value : "portrait";

    const paperSizeEl = document.getElementById("paperSize");
    const paperSize = paperSizeEl ? paperSizeEl.value : "a4";

    const pagesPerSheetEl = document.getElementById("pagesPerSheet");
    const pagesPerSheet = (printMode === "micro_xerox") ? (pagesPerSheetEl ? parseInt(pagesPerSheetEl.value, 10) : 2) : 1;

    const pageOrderEl = document.querySelector('input[name="pageOrder"]:checked');
    const pageOrder = pageOrderEl ? pageOrderEl.value : "horizontal";

    const scaleModeEl = document.querySelector('input[name="scaleMode"]:checked');
    const scaleMode = scaleModeEl ? scaleModeEl.value : "fit";

    if (colorMode === "color") {
        if (doubleSideLabel) doubleSideLabel.style.opacity = "0.5";
        if (radioDoubleSide) {
            radioDoubleSide.disabled = true;
            if (radioDoubleSide.checked) {
                const singleRadio = document.querySelector('input[name="printSide"][value="single"]');
                if (singleRadio) singleRadio.checked = true;
                printSide = "single";
            }
        }
    } else {
        if (doubleSideLabel) doubleSideLabel.style.opacity = "1";
        if (radioDoubleSide) radioDoubleSide.disabled = false;
    }

    if (microXeroxSection) {
        microXeroxSection.style.display = printMode === "micro_xerox" ? "block" : "none";
    }

    if (paperSheetPreview) {
        paperSheetPreview.className = `paper-sheet size-${paperSize} ${orientation} ${scaleMode}`;
    }

    if (printMode === "micro_xerox") {
        if (previewLabelBadge) previewLabelBadge.textContent = `Micro Xerox ${pagesPerSheet}-Up`;
        if (standardPreviewContent) standardPreviewContent.style.display = "none";
        if (nupPreviewGrid) {
            nupPreviewGrid.style.display = "grid";
            let gridClass = `nup-grid nup-${pagesPerSheet}`;
            if (pagesPerSheet === 2) {
                gridClass = pageOrder === "vertical" ? "nup-grid nup-2-v" : "nup-grid nup-2-h";
            }
            nupPreviewGrid.className = gridClass;
            let cellsHtml = "";
            for (let i = 1; i <= pagesPerSheet; i++) {
                cellsHtml += `<div class="nup-cell">P${i}</div>`;
            }
            nupPreviewGrid.innerHTML = cellsHtml;
        }
    } else {
        if (previewLabelBadge) {
            previewLabelBadge.textContent = (scaleMode === "actual") ? "Standard (Actual Size)" : "Standard (Full Page)";
        }
        if (nupPreviewGrid) nupPreviewGrid.style.display = "none";
        if (standardPreviewContent) standardPreviewContent.style.display = "flex";
    }

    const totalAmount = calculatePrice(pageCount, copies, colorMode, printSide, printMode, pagesPerSheet);
    if (totalPriceBox) {
        totalPriceBox.textContent = "Total: ₹" + totalAmount;
    }

    localStorage.setItem("copies", String(copies));
    localStorage.setItem("amount", String(totalAmount));
    localStorage.setItem("printMode", printMode);
    localStorage.setItem("colorMode", colorMode);
    localStorage.setItem("printSide", printSide);
    localStorage.setItem("orientation", orientation);
    localStorage.setItem("paperSize", paperSize);
    localStorage.setItem("pagesPerSheet", String(pagesPerSheet));
    localStorage.setItem("pageOrder", pageOrder);
    localStorage.setItem("scaleMode", scaleMode);
}

const backBtn = document.getElementById("backBtn");
const paymentBtn = document.getElementById("paymentBtn");
const copiesBox = document.getElementById("copies");
const totalPriceBox = document.getElementById("totalPrice");
const printDetailsFileName = document.getElementById("fileName");

if (printDetailsFileName) {
    const savedName = localStorage.getItem("fileName");
    if (savedName) {
        printDetailsFileName.textContent = savedName;
    }

    getSavedPdfFile().then(selectedFile => {
        if (selectedFile) {
            window.selectedPdfFile = selectedFile;
        }
    });

    const settingsForm = document.getElementById("printDetailsForm");
    if (settingsForm) {
        const savedScale = localStorage.getItem("scaleMode");
        if (savedScale) {
            const scaleVal = (savedScale === "actual") ? "actual" : "fit";
            const scaleRadio = document.querySelector(`input[name="scaleMode"][value="${scaleVal}"]`);
            if (scaleRadio) scaleRadio.checked = true;
        }
        const savedPaper = localStorage.getItem("paperSize");
        const paperEl = document.getElementById("paperSize");
        if (savedPaper && paperEl) paperEl.value = savedPaper;

        const savedOrient = localStorage.getItem("orientation");
        if (savedOrient) {
            const orientRadio = document.querySelector(`input[name="orientation"][value="${savedOrient}"]`);
            if (orientRadio) orientRadio.checked = true;
        }

        const savedCopies = localStorage.getItem("copies");
        const copiesEl = document.getElementById("copies");
        if (savedCopies && copiesEl) copiesEl.value = savedCopies;

        const savedColor = localStorage.getItem("colorMode");
        if (savedColor) {
            const colorRadio = document.querySelector(`input[name="colorMode"][value="${savedColor}"]`);
            if (colorRadio) colorRadio.checked = true;
        }

        const savedSide = localStorage.getItem("printSide");
        if (savedSide) {
            const sideRadio = document.querySelector(`input[name="printSide"][value="${savedSide}"]`);
            if (sideRadio) sideRadio.checked = true;
        }

        const savedPrintMode = localStorage.getItem("printMode");
        if (savedPrintMode) {
            const modeRadio = document.querySelector(`input[name="printMode"][value="${savedPrintMode}"]`);
            if (modeRadio) modeRadio.checked = true;
        }

        settingsForm.addEventListener("change", updatePrintDetailsAndPreview);
        settingsForm.addEventListener("input", updatePrintDetailsAndPreview);
    }
    updatePrintDetailsAndPreview();
}

if (backBtn) {
    backBtn.addEventListener("click", function (e) {
        if (e && e.preventDefault) e.preventDefault();
        window.location.href = "home.html";
    });
}

if (paymentBtn) {
    paymentBtn.addEventListener("click", function (e) {
        if (e && e.preventDefault) e.preventDefault();
        updatePrintDetailsAndPreview();
        window.location.href = "payment.html";
    });
}

// ==========================
// PAYMENT PAGE (payment.html) - RAZORPAY INTEGRATION
// ==========================

const paymentFile = document.getElementById("paymentFile");
const paymentCopies = document.getElementById("paymentCopies");
const paymentColorMode = document.getElementById("paymentColorMode");
const paymentAmount = document.getElementById("paymentAmount");
const paymentSide = document.getElementById("paymentSide");
const paymentOrientation = document.getElementById("paymentOrientation");
const payBtn = document.getElementById("payBtn");
const paymentBackBtn = document.getElementById("paymentBackBtn");

if (paymentFile && paymentCopies && paymentAmount) {
    const fileNameVal = localStorage.getItem("fileName") || "No file selected";
    const copiesVal = localStorage.getItem("copies") || "1";
    const amountVal = localStorage.getItem("amount") || "2";
    const colorModeVal = localStorage.getItem("colorMode") || "black_white";
    const printSideVal = localStorage.getItem("printSide") || "single";
    const orientationVal = localStorage.getItem("orientation") || "portrait";

    paymentFile.textContent = "File: " + fileNameVal;
    paymentCopies.textContent = "Copies: " + copiesVal;
    paymentAmount.textContent = "Total Amount: ₹" + amountVal;

    if (paymentColorMode) {
        paymentColorMode.textContent = "Color Mode: " + (colorModeVal === "color" ? "Color Print 🎨" : "Black & White (B&W)");
    }
    if (paymentSide) {
        paymentSide.textContent = "Print Side: " + (printSideVal === "double" ? "Double Side" : "Single Side");
    }
    if (paymentOrientation) {
        paymentOrientation.textContent = "Orientation: " + (orientationVal === "landscape" ? "Landscape" : "Portrait");
    }

    getSavedPdfFile().then(selectedFile => {
        if (selectedFile) {
            window.selectedPdfFile = selectedFile;
        }
    });
}

if (paymentBackBtn) {
    paymentBackBtn.addEventListener("click", function (e) {
        if (e && e.preventDefault) e.preventDefault();
        window.location.href = "print-details.html";
    });
}

function showPaymentFailedModal(title, description) {
    const overlay = document.getElementById("failedModalOverlay");
    const titleEl = document.getElementById("failedModalTitle");
    const descEl = document.getElementById("failedModalDesc");
    const closeBtn = document.getElementById("failedModalCloseBtn");
    const retryBtn = document.getElementById("failedModalRetryBtn");

    if (!overlay) {
        alert(`${title}: ${description}`);
        return;
    }

    if (titleEl) titleEl.textContent = title || "Payment Failed";
    if (descEl) descEl.textContent = description || "Your payment didn't go through due to a temporary issue. Any debited amount will be refunded in 4-5 business days.";

    overlay.classList.add("is-open");

    const closeModal = () => {
        overlay.classList.remove("is-open");
    };

    if (closeBtn) closeBtn.onclick = closeModal;
    if (retryBtn) {
        retryBtn.onclick = () => {
            closeModal();
            const payBtn = document.getElementById("payBtn");
            if (payBtn) payBtn.click();
        };
    }
    overlay.onclick = (e) => {
        if (e.target === overlay) closeModal();
    };
}

function showPaymentSuccessModal(title, description) {
    const overlay = document.getElementById("successModalOverlay");
    const titleEl = document.getElementById("successModalTitle");
    const descEl = document.getElementById("successModalDesc");

    if (titleEl) titleEl.textContent = title || "Payment Successful!";
    if (descEl) descEl.textContent = description || "✓ Payment verified. Your document is queued for printing.";

    if (overlay) {
        overlay.classList.add("is-open");
    }
}

let isPaymentInFlight = false;

if (payBtn) {
    payBtn.addEventListener("click", async function (e) {
        if (e && e.preventDefault) e.preventDefault();

        if (isPaymentInFlight) return;

        if (typeof Razorpay === "undefined") {
            showPaymentFailedModal("SDK Error", "Razorpay SDK is loading. Please check your internet connection and try again.");
            return;
        }

        isPaymentInFlight = true;
        payBtn.disabled = true;
        const originalText = payBtn.textContent;
        payBtn.textContent = "Processing...";

        const tClick = performance.now();

        try {
            const fileNameVal = localStorage.getItem("fileName") || "document.pdf";
            const copiesVal = parseInt(localStorage.getItem("copies") || "1", 10);
            const pageCountVal = parseInt(localStorage.getItem("pdfPageCount") || "1", 10);
            const colorModeVal = localStorage.getItem("colorMode") || "black_white";
            const printSideVal = localStorage.getItem("printSide") || "single";
            const paperSizeVal = localStorage.getItem("paperSize") || "a4";
            const orientationVal = localStorage.getItem("orientation") || "portrait";
            const scaleModeVal = localStorage.getItem("scaleMode") || "fit";
            const marginsVal = localStorage.getItem("margins") || "normal";
            const printModeVal = localStorage.getItem("printMode") || "standard";
            const pagesPerSheetVal = (printModeVal === "micro_xerox") ? parseInt(localStorage.getItem("pagesPerSheet") || "1", 10) : 1;
            const pageOrderVal = localStorage.getItem("pageOrder") || "horizontal";
            const amountVal = parseFloat(localStorage.getItem("amount") || "2");
            const uploadedPath = localStorage.getItem("backendFilePath") || "";
            const rawMobile = localStorage.getItem("mobileNumber") || "9876543210";
            const cleanContact = rawMobile.replace(/\D/g, "").slice(-10) || "9876543210";

            const payload = {
                amount: amountVal,
                pages: pageCountVal,
                copies: copiesVal,
                color_mode: colorModeVal,
                duplex: printSideVal,
                paper_size: paperSizeVal,
                orientation: orientationVal,
                scale_mode: scaleModeVal,
                margins: marginsVal,
                print_mode: printModeVal,
                pages_per_sheet: pagesPerSheetVal,
                page_order: pageOrderVal,
                file_name: fileNameVal,
                file_path: uploadedPath,
                customer_mobile: cleanContact
            };

            const tReqStart = performance.now();

            const orderRes = await fetch(apiUrl("/api/create-razorpay-order", "/api/create-razorpay-order"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            const tReqEnd = performance.now();
            console.log(`[PAYMENT PERF] Order creation latency: ${(tReqEnd - tReqStart).toFixed(1)}ms (Total since click: ${(tReqEnd - tClick).toFixed(1)}ms)`);

            if (!orderRes.ok) {
                const errText = await orderRes.text();
                let errorDetail = `HTTP ${orderRes.status}`;
                try {
                    const errorData = JSON.parse(errText);
                    errorDetail = errorData.detail || errorDetail;
                } catch (parseError) {
                    if (errText) errorDetail = errText;
                }
                throw new Error(`Order creation failed: ${errorDetail}`);
            }

            const orderData = await orderRes.json();
            if (!orderData || orderData.status === "error" || !orderData.order_id) {
                throw new Error(orderData?.detail || "Invalid Razorpay order payload");
            }

            if (orderData.order_id) {
                localStorage.setItem("lastOrderId", orderData.order_id);
                localStorage.setItem("razorpayOrderId", orderData.order_id);
            }

            const options = {
                "key": orderData.key_id,
                "amount": Math.round(Number(orderData.amount)),
                "currency": orderData.currency || "INR",
                "name": "PrintFlow",
                "description": `Print Order - ${fileNameVal.substring(0, 30)}`,
                "order_id": orderData.order_id,
                "prefill": {
                    "contact": cleanContact,
                    "email": "customer@printflow.in"
                },
                "handler": async function (response) {
                    try {
                        const fullVerificationPayload = {
                            ...payload,
                            ...response,
                            razorpay_payment_id: response.razorpay_payment_id,
                            razorpay_order_id: response.razorpay_order_id || orderData.order_id,
                            razorpay_signature: response.razorpay_signature,
                            print_order_id: orderData.order_id
                        };

                        const verifyRes = await fetch(apiUrl("/api/verify-payment", "/api/verify-payment"), {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(fullVerificationPayload)
                        });

                        const verifyData = await verifyRes.json().catch(() => ({}));
                        if (verifyRes.ok && verifyData.status === "success" && verifyData.order_status === "PRINT_QUEUED") {
                            showPaymentSuccessModal("Payment Successful!", "✓ Payment verified. Your document is queued for printing.");
                            const nextOrderId = verifyData.order_id || orderData.order_id || localStorage.getItem("lastOrderId") || "";
                            setTimeout(() => {
                                window.location.href = "success.html" + (nextOrderId ? `?order_id=${encodeURIComponent(nextOrderId)}` : "");
                            }, 1800);
                        } else {
                            showPaymentFailedModal("Verification Error", verifyData.detail || "Payment verification failed.");
                            isPaymentInFlight = false;
                            payBtn.disabled = false;
                            payBtn.textContent = originalText;
                        }
                    } catch (vErr) {
                        showPaymentFailedModal("Verification Error", vErr.message || "Payment verification error occurred.");
                        isPaymentInFlight = false;
                        payBtn.disabled = false;
                        payBtn.textContent = originalText;
                    }
                },
                "theme": {
                    "color": "#ea580c"
                },
                "modal": {
                    "escape": true,
                    "backdropclose": false,
                    "ondismiss": function() {
                        isPaymentInFlight = false;
                        payBtn.disabled = false;
                        payBtn.textContent = originalText;
                    }
                }
            };

            const rzp = new Razorpay(options);
            rzp.on("payment.failed", function (response) {
                const errorDesc = response?.error?.description || "Payment failed or cancelled.";
                showPaymentFailedModal("Payment Failed", errorDesc);
                isPaymentInFlight = false;
                payBtn.disabled = false;
                payBtn.textContent = originalText;
            });

            const tOpen = performance.now();
            console.log(`[PAYMENT PERF] Razorpay checkout.open() invoked at ${(tOpen - tClick).toFixed(1)}ms total`);

            rzp.open();
            isPaymentInFlight = false;

        } catch (err) {
            console.error("[PAYMENT ERROR]:", err);
            showPaymentFailedModal("Payment Error", "Unable to start payment: " + (err.message || "Please try again."));
            isPaymentInFlight = false;
            payBtn.disabled = false;
            payBtn.textContent = originalText;
        }
    });
}

// ==========================
// ADMIN DASHBOARD LOGIC (admin.html)
// ==========================

const adminLockForm = document.getElementById("adminLockForm");
const adminAccessCode = document.getElementById("adminAccessCode");
const adminLockError = document.getElementById("adminLockError");
const lockPortalBtn = document.getElementById("lockPortalBtn");
const toggleCodeBtn = document.getElementById("toggleCodeBtn");
const ADMIN_ACCESS_CODE = "Admin@123";
let adminPortalUnlocked = sessionStorage.getItem("printflowAdminUnlocked") === "true";

function setAdminLockState(isUnlocked) {
    adminPortalUnlocked = isUnlocked;
    document.body.classList.toggle("admin-locked", !isUnlocked);
    if (isUnlocked) {
        sessionStorage.setItem("printflowAdminUnlocked", "true");
    } else {
        sessionStorage.removeItem("printflowAdminUnlocked");
    }
}

if (adminLockForm) {
    setAdminLockState(adminPortalUnlocked);
    adminLockForm.addEventListener("submit", function (event) {
        event.preventDefault();
        if (adminAccessCode && adminAccessCode.value === ADMIN_ACCESS_CODE) {
            if (adminLockError) adminLockError.textContent = "";
            adminAccessCode.value = "";
            setAdminLockState(true);
            fetchAdminOrders();
            return;
        }
        if (adminLockError) adminLockError.textContent = "Incorrect admin access code.";
        if (adminAccessCode) {
            adminAccessCode.value = "";
            adminAccessCode.focus();
        }
    });
}

if (lockPortalBtn) {
    lockPortalBtn.addEventListener("click", function () {
        setAdminLockState(false);
        if (adminAccessCode) adminAccessCode.focus();
    });
}

if (toggleCodeBtn && adminAccessCode) {
    toggleCodeBtn.addEventListener("click", function () {
        const isPassword = adminAccessCode.type === "password";
        adminAccessCode.type = isPassword ? "text" : "password";
        toggleCodeBtn.textContent = isPassword ? "Hide" : "Show";
        toggleCodeBtn.setAttribute("aria-label", `${isPassword ? "Hide" : "Show"} access code`);
        adminAccessCode.focus();
    });
}

const adminOrdersTableBody = document.getElementById("adminOrdersTableBody");
const refreshOrdersBtn = document.getElementById("refreshOrdersBtn");
const adminSearchInput = document.getElementById("adminSearchInput");
const totalEarnings = document.getElementById("totalEarnings");
const totalOrdersCount = document.getElementById("totalOrdersCount");
const totalPagesPrinted = document.getElementById("totalPagesPrinted");
const pendingOrdersCount = document.getElementById("pendingOrdersCount");

let allAdminOrders = [];

function handleOrderUpdate(message) {
    if (!adminPortalUnlocked || !message || !message.order) return;
    const incomingOrder = message.order;
    allAdminOrders = [
        incomingOrder,
        ...allAdminOrders.filter(order => order.order_id !== incomingOrder.order_id)
    ];
    renderAdminOrders(allAdminOrders);
}

if (orderUpdateChannel) {
    orderUpdateChannel.addEventListener("message", event => handleOrderUpdate(event.data));
}

window.addEventListener("storage", event => {
    if (event.key === "printflowOrderUpdated" && event.newValue) {
        try {
            handleOrderUpdate(JSON.parse(event.newValue));
        } catch (error) {
            console.warn("Order update event error:", error);
        }
    }
});

async function fetchAdminOrders() {
    if (!adminOrdersTableBody || !adminPortalUnlocked) return;

    try {
        const res = await fetch(apiUrl("/api/orders", "/api/orders"), {
            headers: getAuthHeaders()
        });
        const data = await res.json();

        if (data && data.orders) {
            allAdminOrders = data.orders;
            renderAdminOrders(allAdminOrders);
        }
    } catch (err) {
        if (adminOrdersTableBody) {
            adminOrdersTableBody.innerHTML = `
                <tr>
                    <td colspan="7" style="text-align: center; color: #ef4444; padding: 20px; font-weight: 600;">
                        Could not load admin orders. Check backend connection.
                    </td>
                </tr>
            `;
        }
    }
}

function renderAdminOrders(orders) {
    if (!adminOrdersTableBody) return;

    let earningsSum = 0;
    let pagesSum = 0;
    let pendingCount = 0;

    orders.forEach(order => {
        earningsSum += (order.amount || 0);
        pagesSum += ((order.pages || 1) * (order.copies || 1));
        if (order.status === "Pending") pendingCount++;
    });

    if (totalEarnings) totalEarnings.textContent = `₹${earningsSum}`;
    if (totalOrdersCount) totalOrdersCount.textContent = String(orders.length);
    if (totalPagesPrinted) totalPagesPrinted.textContent = String(pagesSum);
    if (pendingOrdersCount) pendingOrdersCount.textContent = String(pendingCount);

    if (orders.length === 0) {
        adminOrdersTableBody.innerHTML = `
            <tr>
                <td colspan="7" style="text-align: center; padding: 30px; color: #94a3b8; font-weight: 600;">
                    No print orders received yet.
                </td>
            </tr>
        `;
        return;
    }

    let html = "";
    orders.forEach(order => {
        const isPending = order.status === "Pending" || order.status === "PRINT_QUEUED";
        const isPrinting = order.status === "PRINTING";
        const isFailed = order.status === "FAILED";
        const fileUrl = order.file_path ? `${API_BASE}${order.file_path}` : "#";

        let badgeClass = "badge-completed";
        if (isPending) badgeClass = "badge-pending";
        if (isPrinting) badgeClass = "badge-pending";
        if (isFailed) badgeClass = "badge-pending";

        html += `
            <tr>
                <td><strong>${order.order_id}</strong><br><small style="color: #64748b;">${order.timestamp || ''}</small></td>
                <td>${order.customer_mobile || 'Guest'}</td>
                <td><strong class="admin-file-name" title="${order.file_name}">${order.file_name}</strong><br><small style="color: #ea580c;">${order.pages || 1} Pages</small></td>
                <td>${order.copies || 1} Copies (${order.duplex === 'double' ? 'Double' : 'Single'} Side)</td>
                <td><strong>₹${order.amount || 2}</strong></td>
                <td>
                    <span class="${badgeClass}">
                        ${order.status || 'Pending'}
                    </span>
                </td>
                <td>
                    <div class="action-btn-row">
                        ${order.file_path ? `<a href="${fileUrl}" target="_blank" class="btn-download">⬇️ View</a>` : ''}
                        ${(isPending || isFailed) ? `<button type="button" class="btn-complete" style="background:#e0f2fe; color:#0369a1; border-color:#bae6fd;" onclick="retryOrder('${order.order_id}')">🔄 Retry</button>` : ''}
                        ${order.status !== 'Completed' ? `<button type="button" class="btn-complete" onclick="markOrderCompleted('${order.order_id}')">✅ Complete</button>` : ''}
                    </div>
                </td>
            </tr>
        `;
    });

    adminOrdersTableBody.innerHTML = html;
}

window.retryOrder = async function (orderId) {
    if (!orderId) return;
    try {
        const res = await fetch(apiUrl(`/api/orders/${orderId}/retry`, `/api/orders/${orderId}/retry`), { method: "POST" });
        const data = await res.json();
        alert(`🔄 ${data.message || 'Order reset to PRINT_QUEUED'}`);
        fetchAdminOrders();
    } catch (err) {
        console.warn("Retry order error:", err);
    }
};

const agentStatusBadge = document.getElementById("agentStatusBadge");
const testPrintBtn = document.getElementById("testPrintBtn");
const bwPrinterName = document.getElementById("bwPrinterName");
const colorPrinterName = document.getElementById("colorPrinterName");
const refreshPrintersBtn = document.getElementById("refreshPrintersBtn");

async function fetchConnectedPrinters() {
    if (!bwPrinterName && !colorPrinterName && !agentStatusBadge) return;
    try {
        const res = await fetch(apiUrl("/api/agent/status", "/api/agent/status"));
        const data = await res.json();
        if (data && data.status === "success") {
            const isOnline = data.agent_online;
            if (agentStatusBadge) {
                agentStatusBadge.textContent = isOnline ? "● Agent Online" : "● Agent Offline";
                agentStatusBadge.style.background = isOnline ? "#dcfce7" : "#fee2e2";
                agentStatusBadge.style.color = isOnline ? "#16a34a" : "#dc2626";
            }

            const cfg = data.config || {};
            const printers = data.discovered_printers || [];
            
            const bwTarget = cfg.bw_printer || (printers.find(p => p.is_default) || printers[0] || {}).name || "System Default B&W";
            const colorTarget = cfg.color_printer || (printers.find(p => p.name && p.name.toLowerCase().includes("color")) || printers[0] || {}).name || "System Default Color";
            
            if (bwPrinterName) bwPrinterName.textContent = bwTarget;
            if (colorPrinterName) colorPrinterName.textContent = colorTarget;
        }
    } catch (err) {
        console.warn("Agent status fetch error:", err);
    }
}

if (testPrintBtn) {
    testPrintBtn.addEventListener("click", async function () {
        try {
            const res = await fetch(apiUrl("/api/agent/test-print", "/api/agent/test-print"), { method: "POST" });
            const data = await res.json();
            alert(`🖨️ ${data.message || 'Test print queued!'}`);
            fetchAdminOrders();
        } catch (err) {
            alert("⚠️ Failed to trigger test print");
        }
    });
}

if (refreshPrintersBtn) {
    refreshPrintersBtn.addEventListener("click", fetchConnectedPrinters);
}

window.markOrderCompleted = async function (orderId) {
    try {
        const res = await fetch(apiUrl(`/api/orders/${orderId}/complete`, `/api/orders/${orderId}/complete`), {
            method: "POST"
        });
        const data = await res.json();
        console.log("Order completed:", data);
        fetchAdminOrders();
    } catch (err) {
        console.warn("Mark complete error:", err);
    }
};

if (refreshOrdersBtn) {
    refreshOrdersBtn.addEventListener("click", fetchAdminOrders);
}

if (adminSearchInput) {
    adminSearchInput.addEventListener("input", function () {
        const query = this.value.toLowerCase().trim();
        const filtered = allAdminOrders.filter(o =>
            (o.file_name && o.file_name.toLowerCase().includes(query)) ||
            (o.customer_mobile && o.customer_mobile.toLowerCase().includes(query)) ||
            (o.order_id && o.order_id.toLowerCase().includes(query))
        );
        renderAdminOrders(filtered);
    });
}

if (adminOrdersTableBody && adminPortalUnlocked) {
    fetchAdminOrders();
    fetchConnectedPrinters();
    setInterval(fetchAdminOrders, 2000);
}

// ======================================================
// USER DOCUMENT SESSION CLEANUP (Logout / Re-login privacy)
// ======================================================

function clearUserDocumentSession() {
    console.log("[PRIVACY] Purging all temporary user document session state...");
    const keysToRemove = [
        "fileName", "fileSize", "fileType", "fileLastModified",
        "uploadedFileName", "backendFilePath", "pdfPageCount", "copies",
        "amount", "printSide", "colorMode", "orientation", "paperSize",
        "scaleMode", "margins", "printMode", "pagesPerSheet", "pageOrder",
        "pdfDataUrl", "selectedPdfFile"
    ];
    keysToRemove.forEach(k => {
        localStorage.removeItem(k);
        sessionStorage.removeItem(k);
    });
    if (window.clearSavedPdfFile) {
        window.clearSavedPdfFile();
    }
}
window.clearUserDocumentSession = clearUserDocumentSession;

// ======================================================
// PREMIUM RECEIPT PRINTER SUCCESS PAGE LOGIC (success.html)
// ======================================================

let successPollingInterval = null;

async function logoutAfterPrint() {
    try {
        await fetch(apiUrl("/api/logout", "/api/logout"), {
            method: "POST",
            headers: getAuthHeaders()
        });
    } catch (err) {
        console.error("PrintFlow logout request error:", err);
    }

    try {
        clearUserDocumentSession();
        localStorage.removeItem("mobileNumber");
        localStorage.removeItem("loggedIn");
        localStorage.removeItem("isAuthenticated");
        localStorage.removeItem("user");
        sessionStorage.clear();
    } catch (err) {
        console.warn("Client session cleanup warning:", err);
    }

    window.location.replace("login.html?logout=true");
}
window.logoutAfterPrint = logoutAfterPrint;

let logoutCountdownInterval = null;
function startAutoLogoutCountdown(seconds) {
    if (logoutCountdownInterval) clearInterval(logoutCountdownInterval);
    let remaining = seconds;
    const timerEl = document.getElementById("autoLogoutTimerText");
    const bannerEl = document.getElementById("autoLogoutBanner");
    if (bannerEl) bannerEl.style.display = "flex";
    if (timerEl) timerEl.textContent = `Automatic security logout in ${remaining}s...`;

    logoutCountdownInterval = setInterval(async () => {
        remaining--;
        if (timerEl) timerEl.textContent = `Automatic security logout in ${remaining}s...`;
        if (remaining <= 0) {
            clearInterval(logoutCountdownInterval);
            if (successPollingInterval) clearInterval(successPollingInterval);
            await logoutAfterPrint();
        }
    }, 1000);
}

function initSuccessReceiptPage() {
    const printer = document.getElementById("receiptPrinter") || document.querySelector(".machine-unit");
    const paperViewport = document.getElementById("paperViewport") || document.querySelector(".paper-viewport");
    const rcptPaper = document.getElementById("receiptPaper");
    const rcptOrderId = document.getElementById("rcptOrderId");
    const receiptOrder = document.getElementById("receiptOrder");
    const rcptFileName = document.getElementById("rcptFileName");
    const rcptPages = document.getElementById("rcptPages");
    const receiptPages = document.getElementById("receiptPages");
    const rcptCopies = document.getElementById("rcptCopies");
    const receiptCopies = document.getElementById("receiptCopies");
    const rcptPrintMode = document.getElementById("rcptPrintMode");
    const rcptColorMode = document.getElementById("rcptColorMode");
    const rcptSides = document.getElementById("rcptSides");
    const rcptPaperSize = document.getElementById("rcptPaperSize");
    const rcptOrientation = document.getElementById("rcptOrientation");
    const rcptAmount = document.getElementById("rcptAmount");
    const rcptStatusBadge = document.getElementById("rcptStatusBadge");
    const statusHeadline = document.getElementById("statusHeadline");
    const statusSubtext = document.getElementById("statusSubtext");
    const ledDot = document.getElementById("ledDot") || document.getElementById("printerStatusDot");
    const agentStateText = document.getElementById("agentStateText") || document.getElementById("printerStatusText");
    const privacyToast = document.getElementById("privacyToast");
    const finalSuccess = document.getElementById("finalSuccess");

    if (!printer && !rcptPaper && !rcptOrderId && !receiptOrder) return;

    const params = new URLSearchParams(window.location.search);
    const orderId = params.get("order_id") || localStorage.getItem("lastOrderId") || localStorage.getItem("razorpayOrderId") || `PF-${Math.floor(100000 + Math.random() * 900000)}`;
    const fileName = localStorage.getItem("fileName") || "document.pdf";
    const pages = localStorage.getItem("pdfPageCount") || "1";
    const copies = localStorage.getItem("copies") || "1";
    const isMicro = localStorage.getItem("printMode") === "micro_xerox" && parseInt(localStorage.getItem("pagesPerSheet") || "1", 10) > 1;
    const printMode = isMicro ? "Micro Xerox" : "Standard";
    const colorMode = (localStorage.getItem("colorMode") === "color" || localStorage.getItem("colorMode") === "colour") ? "Color Print 🎨" : "Black & White";
    const sides = (localStorage.getItem("printSide") === "double" || localStorage.getItem("duplex") === "double") ? "Double Side" : "Single Side";
    const paperSize = (localStorage.getItem("paperSize") || "A4").toUpperCase();
    const orientation = ((localStorage.getItem("orientation") || "portrait").toLowerCase() === "landscape") ? "Landscape" : "Portrait";
    const amount = localStorage.getItem("amount") || "2.00";

    if (rcptOrderId) rcptOrderId.textContent = orderId;
    if (receiptOrder) receiptOrder.textContent = orderId;
    if (rcptFileName) rcptFileName.textContent = fileName;
    if (rcptPages) rcptPages.textContent = pages;
    if (receiptPages) receiptPages.textContent = pages;
    if (rcptCopies) rcptCopies.textContent = copies;
    if (receiptCopies) receiptCopies.textContent = copies;
    if (rcptPrintMode) rcptPrintMode.textContent = printMode;
    if (rcptColorMode) rcptColorMode.textContent = colorMode;
    if (rcptSides) rcptSides.textContent = sides;
    if (rcptPaperSize) rcptPaperSize.textContent = paperSize;
    if (rcptOrientation) rcptOrientation.textContent = orientation;
    if (rcptAmount) rcptAmount.textContent = `₹${parseFloat(amount).toFixed(2)}`;

    let hasTriggeredCompletedSequence = false;

    async function pollStatus() {
        try {
            const res = await fetch(apiUrl(`/api/orders/${orderId}/status`, `/api/orders/${orderId}/status`), {
                headers: getAuthHeaders()
            });

            if (res.status === 401 || res.status === 403 || res.status === 404) {
                if (successPollingInterval) clearInterval(successPollingInterval);
                const container = document.getElementById("successPage") || document.querySelector(".receipt-page-container") || document.body;
                container.innerHTML = `
                    <div class="card" style="text-align:center; padding:30px; margin: 40px auto; max-width: 480px; background: white; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                        <div style="font-size: 48px; margin-bottom: 16px;">🔒</div>
                        <h2 style="color: #dc2626; margin-bottom: 8px;">Access Denied</h2>
                        <p style="color: #4b5563; font-size: 15px; margin-bottom: 20px;">You are not authorized to view this order receipt.</p>
                        <a href="home.html" style="display:inline-block; padding: 10px 20px; background: #2563eb; color: white; border-radius: 8px; text-decoration: none; font-weight: 600;">Go to Home</a>
                    </div>
                `;
                return;
            }

            const data = await res.json();
            if (data && data.status === "success") {
                const orderState = data.order_status || "PRINT_QUEUED";

                if (agentStateText) agentStateText.textContent = orderState;
                if (rcptStatusBadge) {
                    rcptStatusBadge.textContent = orderState;
                    rcptStatusBadge.className = `receipt-status-badge status-${orderState.toLowerCase()}`;
                }

                if (orderState === "PRINT_QUEUED") {
                    if (ledDot) {
                        ledDot.className = "led-dot";
                        ledDot.style.background = "#eab308";
                        ledDot.style.boxShadow = "0 0 8px #eab308";
                    }
                    if (statusHeadline) statusHeadline.textContent = "Preparing your print...";
                    if (statusSubtext) statusSubtext.textContent = "Your payment has been received. Queueing document for physical printer.";
                } else if (orderState === "PRINTING") {
                    if (ledDot) {
                        ledDot.className = "led-dot";
                        ledDot.style.background = "#ea580c";
                        ledDot.style.boxShadow = "0 0 8px #ea580c";
                    }
                    if (statusHeadline) statusHeadline.textContent = "Printing your document...";
                    if (statusSubtext) statusSubtext.textContent = "The physical printer is actively printing your file.";
                } else if (orderState === "COMPLETED" || orderState === "PRINTED") {
                    if (successPollingInterval) {
                        clearInterval(successPollingInterval);
                        successPollingInterval = null;
                    }

                    if (!hasTriggeredCompletedSequence) {
                        hasTriggeredCompletedSequence = true;

                        // 1. Printer success state appears
                        if (ledDot) {
                            ledDot.className = "led-dot online";
                            ledDot.style.background = "#22c55e";
                            ledDot.style.boxShadow = "0 0 8px #22c55e";
                        }
                        if (agentStateText) agentStateText.textContent = "COMPLETED";
                        if (rcptStatusBadge) {
                            rcptStatusBadge.textContent = "COMPLETED";
                            rcptStatusBadge.className = "receipt-status-badge status-completed";
                        }
                        if (statusHeadline) statusHeadline.textContent = "Print finished on printer";
                        if (statusSubtext) statusSubtext.textContent = "Dispensing physical print receipt...";

                        // 2. Small delay before receipt begins emerging from the printer slot (500ms)
                        setTimeout(() => {
                            // 3. Receipt begins emerging FROM THE PRINTER SLOT & slowly feeds downward
                            if (paperViewport) {
                                paperViewport.classList.add("settled");
                            }
                            if (rcptPaper) {
                                rcptPaper.classList.add("emerging");
                                requestAnimationFrame(() => {
                                    rcptPaper.classList.add("settled");
                                });
                            }

                            // 4. Receipt reaches final position after feeding downward (2.8s)
                            setTimeout(() => {
                                // 5. Short pause (600ms) after receipt reaches final position
                                setTimeout(() => {
                                    // 6. "Print Completed!" success section appears
                                    if (statusHeadline) statusHeadline.textContent = "Print Completed! 🎉";
                                    if (statusSubtext) statusSubtext.textContent = "Your document has been printed successfully.";
                                    if (privacyToast) privacyToast.style.display = "flex";

                                    if (printer) {
                                        printer.classList.remove("receipt-animation-started");
                                        void printer.offsetWidth;
                                        printer.classList.add("receipt-animation-started");
                                    }
                                    if (finalSuccess) {
                                        finalSuccess.classList.remove("receipt-animation-started");
                                        void finalSuccess.offsetWidth;
                                        finalSuccess.classList.add("receipt-animation-started");
                                    }

                                    // Start 60-second automatic security logout countdown after print completion
                                    startAutoLogoutCountdown(60);
                                }, 600);
                            }, 2800);
                        }, 500);
                    }
                } else if (orderState === "FAILED") {
                    if (ledDot) {
                        ledDot.className = "led-dot failed";
                        ledDot.style.background = "#ef4444";
                        ledDot.style.boxShadow = "0 0 8px #ef4444";
                    }
                    if (statusHeadline) statusHeadline.textContent = "Printing Failed";
                    if (statusSubtext) statusSubtext.textContent = "We couldn't complete your print job on the physical printer.";
                    const retryBtn = document.getElementById("retryBtn");
                    if (retryBtn) retryBtn.style.display = "inline-block";
                    if (successPollingInterval) clearInterval(successPollingInterval);
                }
            }
        } catch (err) {
            console.warn("Receipt status poll error:", err);
        }
    }

    pollStatus();
    if (successPollingInterval) clearInterval(successPollingInterval);
    successPollingInterval = setInterval(pollStatus, 1500);
}
window.initSuccessReceiptPage = initSuccessReceiptPage;

window.retryPrintJob = async function() {
    const orderId = localStorage.getItem("lastOrderId") || localStorage.getItem("razorpayOrderId");
    if (!orderId) return;
    const retryBtn = document.getElementById("retryBtn");
    if (retryBtn) retryBtn.disabled = true;

    try {
        const res = await fetch(apiUrl(`/api/orders/${orderId}/retry`, `/api/orders/${orderId}/retry`), {
            method: "POST",
            headers: getAuthHeaders()
        });
        const data = await res.json();
        if (data.status === "success") {
            if (retryBtn) retryBtn.style.display = "none";
            initSuccessReceiptPage();
        }
    } catch (err) {
        alert("Retry failed. Please check network connection.");
    } finally {
        if (retryBtn) retryBtn.disabled = false;
    }
};

window.clearSessionAndReturnHome = function() {
    if (successPollingInterval) clearInterval(successPollingInterval);
    clearUserDocumentSession();
    window.location.href = "home.html";
};
