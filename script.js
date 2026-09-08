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

    const allUploaded = activeItems.every(i => i.status === "UPLOADED" && !i.isDetectingPages);
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

async function saveAllUploadedFiles(activeItems) {
    if (!activeItems || !activeItems.length) return;
    try {
        const db = await openPdfDB();
        if (!db) return;
        const tx = db.transaction(STORE_NAME, "readwrite");
        const store = tx.objectStore(STORE_NAME);
        if (activeItems[0].file) {
            store.put(activeItems[0].file, "currentPdf");
        }
        store.put(activeItems.length, "fileCount");
        activeItems.forEach((item, idx) => {
            if (item.file) {
                store.put(item.file, `file_${idx}`);
                store.put({
                    id: item.id,
                    name: item.name,
                    size: item.size,
                    pages: item.pages || 1,
                    typeCategory: item.typeCategory,
                    sequence: item.sequence,
                    backendPath: item.backendPath
                }, `meta_${idx}`);
            }
        });
    } catch (e) {
        console.warn("saveAllUploadedFiles error:", e);
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
    localStorage.removeItem("lastOrderId");
    localStorage.removeItem("razorpayOrderId");
    localStorage.removeItem("currentCheckoutPaid");
    localStorage.removeItem("newCheckoutPending");

    saveAllUploadedFiles(activeItems);

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
                <span>${item.isDetectingPages ? '<span class="detecting-pages-text">Detecting pages...</span>' : `${item.pages} page${item.pages > 1 ? 's' : ''}`}</span>
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

        const isDocx = (ext === "doc" || ext === "docx");
        const isPdf = (ext === "pdf" || file.type === "application/pdf");
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
            isDetectingPages: isDocx || isPdf,
            backendPath: "",
            xhr: null,
            error: null,
            sequence: nextSequence++
        };

        fileQueue.push(item);
        renderFileRowUI(item);

        if (isPdf) {
            countPdfPages(file).then(pages => {
                item.pages = pages;
                item.isDetectingPages = false;
                renderFileRowUI(item);
                calculateAndUpdateTotalPages();
                saveUploadStateToLocalStorage();
            }).catch(err => {
                item.pages = 1;
                item.isDetectingPages = false;
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

        if (data.page_count !== undefined || data.pages !== undefined) {
            const detected = parseInt(data.page_count !== undefined ? data.page_count : data.pages, 10);
            if (!isNaN(detected) && detected > 0) {
                item.pages = detected;
            }
        }
        item.isDetectingPages = false;

        calculateAndUpdateTotalPages();
        saveUploadStateToLocalStorage();
    } catch (err) {
        item.status = "FAILED";
        item.progress = 0;
        item.error = err.message || "Network error";
        item.isDetectingPages = false;
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

            const isStillUploading = activeItems.some(i => i.status === "UPLOADING" || i.status === "WAITING" || i.isDetectingPages);
            const hasFailed = activeItems.some(i => i.status === "FAILED");
            if (isStillUploading || hasFailed) {
                if (pdfErrorMsg) {
                    pdfErrorMsg.textContent = isStillUploading
                        ? "Please wait for files to finish uploading and detecting pages before continuing"
                        : "Please retry failed uploads before continuing";
                    pdfErrorMsg.style.display = "block";
                }
                return;
            }

            localStorage.removeItem("lastOrderId");
            localStorage.removeItem("razorpayOrderId");
            localStorage.removeItem("currentCheckoutPaid");
            localStorage.removeItem("newCheckoutPending");
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

let livePreviewPages = [];
let livePreviewIndex = 0;
let isPreviewPagesLoading = false;

async function loadAllSavedFiles() {
    if (window.loadedFilesCache && window.loadedFilesCache.length > 0) {
        return window.loadedFilesCache;
    }
    const db = await openPdfDB();
    const files = [];
    if (db) {
        try {
            const tx = db.transaction(STORE_NAME, "readonly");
            const store = tx.objectStore(STORE_NAME);
            const countReq = store.get("fileCount");
            const fileCount = await new Promise(r => { countReq.onsuccess = () => r(countReq.result || 0); countReq.onerror = () => r(0); });
            if (fileCount > 0) {
                for (let i = 0; i < fileCount; i++) {
                    const fReq = store.get(`file_${i}`);
                    const mReq = store.get(`meta_${i}`);
                    const f = await new Promise(r => { fReq.onsuccess = () => r(fReq.result); fReq.onerror = () => r(null); });
                    const m = await new Promise(r => { mReq.onsuccess = () => r(mReq.result); mReq.onerror = () => r(null); });
                    if (f) files.push({ file: f, meta: m || { name: f.name } });
                }
            } else {
                const singleReq = store.get("currentPdf");
                const singleF = await new Promise(r => { singleReq.onsuccess = () => r(singleReq.result); singleReq.onerror = () => r(null); });
                if (singleF) files.push({ file: singleF, meta: { name: singleF.name } });
            }
        } catch (e) {
            console.warn("loadAllSavedFiles IndexedDB note:", e);
        }
    }

    if (!files.length) {
        const detailsStr = localStorage.getItem("fileListDetails");
        const singlePath = localStorage.getItem("backendFilePath");
        let details = [];
        try { details = detailsStr ? JSON.parse(detailsStr) : []; } catch(e) {}
        if (!details.length && singlePath) {
            details.push({ name: localStorage.getItem("fileName") || "document.pdf", path: singlePath });
        }
        for (const d of details) {
            if (d.path) {
                try {
                    const fetchUrl = apiUrl(d.path, d.path);
                    const res = await fetch(fetchUrl);
                    if (res.ok) {
                        const blob = await res.blob();
                        const file = new File([blob], d.name || "file", { type: blob.type });
                        files.push({ file, meta: d });
                    }
                } catch (fetchErr) {
                    console.warn("loadAllSavedFiles backend fetch note:", fetchErr);
                }
            }
        }
    }

    window.loadedFilesCache = files;
    return files;
}

async function prepareRealLivePreviewPages() {
    if (isPreviewPagesLoading) return;
    isPreviewPagesLoading = true;
    livePreviewPages = [];

    const loadingEl = document.getElementById("livePreviewLoading");
    if (loadingEl) {
        loadingEl.textContent = "Rendering real preview...";
        loadingEl.style.display = "block";
    }

    try {
        const fileEntries = await loadAllSavedFiles();
        let overallPageNum = 0;
        for (let fi = 0; fi < fileEntries.length; fi++) {
            const entry = fileEntries[fi];
            const file = entry.file;
            const fileName = entry.meta?.name || file.name || `Document_${fi + 1}`;
            const ext = (fileName || "").split('.').pop().toLowerCase();
            const isImage = file.type.startsWith("image/") || ["jpg", "jpeg", "png", "webp", "bmp"].includes(ext);
            const isPdf = (file.type === "application/pdf") || ext === "pdf";

            if (isImage) {
                overallPageNum++;
                const imgUrl = URL.createObjectURL(file);
                const dims = await new Promise(resolve => {
                    const tempImg = new Image();
                    tempImg.onload = () => resolve({ width: tempImg.naturalWidth || 800, height: tempImg.naturalHeight || 1100 });
                    tempImg.onerror = () => resolve({ width: 800, height: 1100 });
                    tempImg.src = imgUrl;
                });
                livePreviewPages.push({
                    type: "image",
                    title: fileName,
                    src: imgUrl,
                    width: dims.width,
                    height: dims.height,
                    docPageNum: overallPageNum,
                    fileIndex: fi,
                    filePageNum: 1
                });
            } else if (isPdf && typeof pdfjsLib !== "undefined") {
                try {
                    const buffer = await file.arrayBuffer();
                    const pdf = await pdfjsLib.getDocument({ data: buffer }).promise;
                    const numPages = pdf.numPages || 1;

                    // Dynamically calculate scale against the actual available print preview container
                    const previewEl = document.getElementById("paperSheetPreview") || document.querySelector(".paper-sheet");
                    const previewRect = previewEl ? previewEl.getBoundingClientRect() : null;
                    const availableWidth = (previewRect && previewRect.width > 0) ? previewRect.width : (previewEl ? previewEl.clientWidth : 0) || 160;
                    const availableHeight = (previewRect && previewRect.height > 0) ? previewRect.height : (previewEl ? previewEl.clientHeight : 0) || 226;
                    const dpr = Math.max(window.devicePixelRatio || 1, 2);

                    for (let p = 1; p <= numPages; p++) {
                        overallPageNum++;
                        const page = await pdf.getPage(p);
                        const unscaledVp = page.getViewport({ scale: 1.0 });
                        const scaleX = (availableWidth * dpr) / (unscaledVp.width || 1);
                        const scaleY = (availableHeight * dpr) / (unscaledVp.height || 1);
                        const scale = Math.max(scaleX, scaleY, 1.5);
                        const vp = page.getViewport({ scale: scale });
                        const canvas = document.createElement("canvas");
                        canvas.width = Math.round(vp.width);
                        canvas.height = Math.round(vp.height);
                        const ctx = canvas.getContext("2d");
                        await page.render({ canvasContext: ctx, viewport: vp }).promise;
                        livePreviewPages.push({
                            type: "canvas",
                            title: numPages > 1 ? `${fileName} (P.${p})` : fileName,
                            src: canvas.toDataURL("image/png"),
                            width: unscaledVp.width,
                            height: unscaledVp.height,
                            docPageNum: overallPageNum,
                            fileIndex: fi,
                            filePageNum: p
                        });
                    }
                } catch (pdfErr) {
                    console.warn("PDF render warning:", pdfErr);
                }
            } else {
                const docPages = Math.max(1, parseInt(entry.meta?.pages || 1, 10));
                for (let p = 1; p <= docPages; p++) {
                    overallPageNum++;
                    const canvas = document.createElement("canvas");
                    canvas.width = 400;
                    canvas.height = 560;
                    const ctx = canvas.getContext("2d");
                    ctx.fillStyle = "#ffffff";
                    ctx.fillRect(0, 0, 400, 560);
                    ctx.fillStyle = "#1e293b";
                    ctx.font = "bold 16px sans-serif";
                    ctx.fillText(fileName.substring(0, 24), 20, 40);
                    ctx.fillStyle = "#64748b";
                    ctx.font = "12px sans-serif";
                    ctx.fillText(`Format: ${ext.toUpperCase()}${docPages > 1 ? ` (Page ${p} of ${docPages})` : ''}`, 20, 68);
                    ctx.fillStyle = "#cbd5e1";
                    for (let y = 95; y < 500; y += 18) {
                        ctx.fillRect(20, y, Math.random() * 120 + 220, 6);
                    }
                    livePreviewPages.push({
                        type: "canvas",
                        title: docPages > 1 ? `${fileName} (P.${p})` : fileName,
                        src: canvas.toDataURL("image/png"),
                        width: 400,
                        height: 560,
                        docPageNum: overallPageNum,
                        fileIndex: fi,
                        filePageNum: p
                    });
                }
            }
        }
    } catch (err) {
        console.warn("prepareRealLivePreviewPages error:", err);
    } finally {
        isPreviewPagesLoading = false;
        if (loadingEl) loadingEl.style.display = "none";
        renderRealLivePreviewUI();
    }
}

function parseAndValidatePageSelection(selectionType, customStr, totalPages) {
    totalPages = Math.max(1, parseInt(totalPages, 10) || 1);

    if (selectionType === "all") {
        const pages = [];
        for (let i = 1; i <= totalPages; i++) pages.push(i);
        return { isValid: true, pages, error: "", canonicalString: "all" };
    }

    if (selectionType === "even") {
        const pages = [];
        for (let i = 2; i <= totalPages; i += 2) pages.push(i);
        if (pages.length === 0) {
            return { isValid: false, pages: [], error: "No even pages in a 1-page document.", canonicalString: "even" };
        }
        return { isValid: true, pages, error: "", canonicalString: "even" };
    }

    if (selectionType === "odd") {
        const pages = [];
        for (let i = 1; i <= totalPages; i += 2) pages.push(i);
        return { isValid: true, pages, error: "", canonicalString: "odd" };
    }

    if (selectionType === "custom") {
        const input = (customStr || "").trim();
        if (!input) {
            return { isValid: false, pages: [], error: "Please enter page numbers or ranges (e.g. 1,3,5-8)", canonicalString: "" };
        }

        if (!/^[0-9,\-\s]+$/.test(input)) {
            return { isValid: false, pages: [], error: "Invalid characters. Use only numbers, commas, and hyphens (e.g. 1,3,5-8)", canonicalString: input };
        }

        const tokens = input.split(",").map(t => t.trim()).filter(Boolean);
        if (!tokens.length) {
            return { isValid: false, pages: [], error: "Please enter at least one valid page number", canonicalString: input };
        }

        const pageSet = new Set();
        for (const token of tokens) {
            if (token.includes("-")) {
                const parts = token.split("-").map(p => p.trim()).filter(Boolean);
                if (parts.length !== 2) {
                    return { isValid: false, pages: [], error: `Invalid range format: "${token}"`, canonicalString: input };
                }
                const start = parseInt(parts[0], 10);
                const end = parseInt(parts[1], 10);
                if (isNaN(start) || isNaN(end)) {
                    return { isValid: false, pages: [], error: `Invalid range numbers in "${token}"`, canonicalString: input };
                }
                if (start < 1) {
                    return { isValid: false, pages: [], error: `Page number must be at least 1 (found ${start})`, canonicalString: input };
                }
                if (start > totalPages) {
                    return { isValid: false, pages: [], error: `Page ${start} exceeds total document pages (${totalPages})`, canonicalString: input };
                }
                if (end > totalPages) {
                    return { isValid: false, pages: [], error: `Page ${end} exceeds total document pages (${totalPages})`, canonicalString: input };
                }
                if (start > end) {
                    return { isValid: false, pages: [], error: `Invalid range: ${start}-${end}. Start page cannot be greater than end page.`, canonicalString: input };
                }
                for (let p = start; p <= end; p++) {
                    pageSet.add(p);
                }
            } else {
                const p = parseInt(token, 10);
                if (isNaN(p)) {
                    return { isValid: false, pages: [], error: `Invalid page number: "${token}"`, canonicalString: input };
                }
                if (p < 1) {
                    return { isValid: false, pages: [], error: `Page number must be at least 1 (found ${p})`, canonicalString: input };
                }
                if (p > totalPages) {
                    return { isValid: false, pages: [], error: `Page ${p} exceeds total document pages (${totalPages})`, canonicalString: input };
                }
                pageSet.add(p);
            }
        }

        const sortedPages = Array.from(pageSet).sort((a, b) => a - b);
        if (!sortedPages.length) {
            return { isValid: false, pages: [], error: "No valid pages selected", canonicalString: input };
        }

        return { isValid: true, pages: sortedPages, error: "", canonicalString: sortedPages.join(",") };
    }

    return { isValid: true, pages: [1], error: "", canonicalString: "all" };
}

function getEffectivePreviewPages() {
    if (!livePreviewPages || !livePreviewPages.length) return [];

    const manifest = (window.currentFileManifest && window.currentFileManifest.length)
        ? window.currentFileManifest
        : (typeof getStoredFileManifest === "function" ? getStoredFileManifest() : []);
    const activeFile = manifest[window.activePreviewFileIndex || 0] || manifest[0];
    if (!activeFile) return livePreviewPages;

    let filePages = livePreviewPages.filter(p => p.fileIndex === (window.activePreviewFileIndex || 0));
    if (!filePages.length) {
        filePages = livePreviewPages;
    }

    const selectedSet = new Set(activeFile.selectedPages || []);
    const filtered = filePages.filter((p, idx) => {
        const pageNum = p.filePageNum || (idx + 1);
        return selectedSet.has(pageNum);
    });

    return filtered.length ? filtered : filePages;
}

function getDefaultContainerDimensions(isNotebook, paperSize, isLandscape) {
    if (isNotebook) {
        if (paperSize === "letter") return isLandscape ? { w: 152, h: 118 } : { w: 138, h: 178 };
        if (paperSize === "legal") return isLandscape ? { w: 158, h: 96 } : { w: 126, h: 210 };
        return isLandscape ? { w: 152, h: 108 } : { w: 136, h: 192 };
    }
    if (paperSize === "letter") return isLandscape ? { w: 214, h: 165 } : { w: 165, h: 214 };
    if (paperSize === "legal") return isLandscape ? { w: 247, h: 150 } : { w: 150, h: 247 };
    return isLandscape ? { w: 226, h: 160 } : { w: 160, h: 226 };
}

function applyMathematicalPreviewLayout(imgEl, pageData, containerEl) {
    if (!imgEl || !containerEl) return;

    const manifest = (window.currentFileManifest && window.currentFileManifest.length)
        ? window.currentFileManifest
        : (typeof getStoredFileManifest === "function" ? getStoredFileManifest() : []);
    const activeFile = manifest[window.activePreviewFileIndex || 0] || manifest[0] || {};

    const paperSize = (activeFile.paperSize || (document.getElementById("paperSize") ? document.getElementById("paperSize").value : (localStorage.getItem("paperSize") || "a4"))).toLowerCase();
    const orientation = (activeFile.orientation || (document.querySelector('input[name="orientation"]:checked') ? document.querySelector('input[name="orientation"]:checked').value : (localStorage.getItem("orientation") || "portrait"))).toLowerCase();
    const isLandscape = (orientation === "landscape");
    const scaleMode = (activeFile.scaleMode || (document.querySelector('input[name="scaleMode"]:checked') ? document.querySelector('input[name="scaleMode"]:checked').value : (localStorage.getItem("scaleMode") || "fit"))).toLowerCase();

    // Kyocera ECOSYS M2040dn KX real hardware device caps
    let paperW_mm = 210.02;
    let paperH_mm = 296.98;
    let printableW_mm = 201.51;
    let printableH_mm = 288.46;
    let hardMarginLeftMm = 4.19;
    let hardMarginTopMm = 4.19;

    if (paperSize === "letter") {
        paperW_mm = 215.9;
        paperH_mm = 279.4;
        printableW_mm = 207.39;
        printableH_mm = 270.85;
    } else if (paperSize === "legal") {
        paperW_mm = 215.9;
        paperH_mm = 355.6;
        printableW_mm = 207.39;
        printableH_mm = 347.05;
    }

    if (isLandscape) {
        const tmpW = paperW_mm;
        paperW_mm = paperH_mm;
        paperH_mm = tmpW;

        const tmpPrintW = printableW_mm;
        printableW_mm = printableH_mm;
        printableH_mm = tmpPrintW;
    }

    const sheetRect = containerEl ? containerEl.getBoundingClientRect() : null;
    let sheetW = (sheetRect && sheetRect.width > 0) ? sheetRect.width : (containerEl ? containerEl.clientWidth : 0);
    let sheetH = (sheetRect && sheetRect.height > 0) ? sheetRect.height : (containerEl ? containerEl.clientHeight : 0);

    const isNotebook = Boolean(containerEl && containerEl.id && containerEl.id.startsWith("notebook"));
    const defaultDims = getDefaultContainerDimensions(isNotebook, paperSize, isLandscape);
    if (sheetW <= 0 || sheetH <= 0 || (isLandscape && sheetW < sheetH) || (!isLandscape && sheetW > sheetH)) {
        sheetW = defaultDims.w;
        sheetH = defaultDims.h;
    }

    const pxPerMmX = sheetW / paperW_mm;
    const pxPerMmY = sheetH / paperH_mm;

    const printableWidthPx = printableW_mm * pxPerMmX;
    const printableHeightPx = printableH_mm * pxPerMmY;
    const hardMarginLeftPx = hardMarginLeftMm * pxPerMmX;
    const hardMarginTopPx = hardMarginTopMm * pxPerMmY;

    let srcW = (pageData && pageData.width) || imgEl.naturalWidth || 0;
    let srcH = (pageData && pageData.height) || imgEl.naturalHeight || 0;

    if (srcW <= 0 || srcH <= 0) {
        imgEl.onload = () => {
            applyMathematicalPreviewLayout(imgEl, pageData, containerEl);
        };
        return;
    }

    let needRotation = false;
    let effectiveSrcW = srcW;
    let effectiveSrcH = srcH;
    if (isLandscape && srcW < srcH) {
        needRotation = true;
        effectiveSrcW = srcH;
        effectiveSrcH = srcW;
    } else if (!isLandscape && srcW > srcH) {
        needRotation = true;
        effectiveSrcW = srcH;
        effectiveSrcH = srcW;
    }

    let scale;
    if (scaleMode === "actual" || scaleMode === "actual_size") {
        scale = Math.min(1.0, printableWidthPx / effectiveSrcW, printableHeightPx / effectiveSrcH);
    } else {
        scale = Math.min(printableWidthPx / effectiveSrcW, printableHeightPx / effectiveSrcH);
    }

    const scaledW = effectiveSrcW * scale;
    const scaledH = effectiveSrcH * scale;

    const offsetX = (printableWidthPx - scaledW) / 2.0;
    const offsetY = (printableHeightPx - scaledH) / 2.0;

    const left = hardMarginLeftPx + offsetX;
    const top = hardMarginTopPx + offsetY;

    if (needRotation) {
        const rawW = srcW * scale;
        const rawH = srcH * scale;
        imgEl.style.width = Math.round(rawW) + "px";
        imgEl.style.height = Math.round(rawH) + "px";
        imgEl.style.transformOrigin = "center center";
        imgEl.style.transform = "rotate(90deg)";
        const x0 = (left + scaledW / 2.0) - (rawW / 2.0);
        const y0 = (top + scaledH / 2.0) - (rawH / 2.0);
        imgEl.style.left = Math.round(x0) + "px";
        imgEl.style.top = Math.round(y0) + "px";
    } else {
        imgEl.style.transform = "none";
        imgEl.style.width = Math.round(scaledW) + "px";
        imgEl.style.height = Math.round(scaledH) + "px";
        imgEl.style.left = Math.round(left) + "px";
        imgEl.style.top = Math.round(top) + "px";
    }
    imgEl.style.position = "absolute";
    imgEl.style.objectFit = "fill";
}

function renderRealLivePreviewUI() {
    const liveImg = document.getElementById("livePreviewImg");
    const loadingEl = document.getElementById("livePreviewLoading");
    const nupGrid = document.getElementById("nupPreviewGrid");
    const standardContent = document.getElementById("standardPreviewContent");
    const navBar = document.getElementById("previewNavBar");
    const pageIndicator = document.getElementById("previewPageIndicator");
    const prevBtn = document.getElementById("prevPageBtn");
    const nextBtn = document.getElementById("nextPageBtn");

    const manifest = (window.currentFileManifest && window.currentFileManifest.length)
        ? window.currentFileManifest
        : (typeof getStoredFileManifest === "function" ? getStoredFileManifest() : []);
    const activeFile = manifest[window.activePreviewFileIndex || 0] || manifest[0] || {};

    const printSide = activeFile.printSide || "single";
    const duplexBinding = activeFile.duplexBinding || "long_edge";
    const orientation = activeFile.orientation || "portrait";
    const paperSize = activeFile.paperSize || "a4";
    const scaleMode = activeFile.scaleMode || "fit";
    const colorMode = activeFile.colorMode || "black_white";

    const printModeEl = document.querySelector('input[name="printMode"]:checked');
    const printMode = printModeEl ? printModeEl.value : (activeFile.printMode || "standard");
    const pagesPerSheetEl = document.getElementById("pagesPerSheet");
    const pagesPerSheet = (printMode === "micro_xerox") ? (pagesPerSheetEl ? parseInt(pagesPerSheetEl.value, 10) : 2) : 1;
    const pageOrderEl = document.querySelector('input[name="pageOrder"]:checked');
    const pageOrder = pageOrderEl ? pageOrderEl.value : "horizontal";

    const pagesToRender = getEffectivePreviewPages();

    if (!pagesToRender.length) {
        if (loadingEl) {
            loadingEl.textContent = "Document uploaded";
            loadingEl.style.display = "block";
        }
        if (liveImg) liveImg.style.display = "none";
        return;
    }

    if (loadingEl) loadingEl.style.display = "none";

    if (printMode === "micro_xerox") {
        if (standardContent) standardContent.style.display = "none";
        if (nupGrid) {
            nupGrid.style.display = "grid";

            let cols = 1, rows = 1;
            if (pagesPerSheet === 2) {
                if (orientation === "landscape") { cols = 2; rows = 1; }
                else { cols = 1; rows = 2; }
            } else if (pagesPerSheet === 4) {
                cols = 2; rows = 2;
            } else if (pagesPerSheet === 6) {
                if (orientation === "landscape") { cols = 3; rows = 2; }
                else { cols = 2; rows = 3; }
            } else if (pagesPerSheet === 9) {
                cols = 3; rows = 3;
            } else if (pagesPerSheet === 16) {
                cols = 4; rows = 4;
            }

            let gridClass = `nup-grid nup-${pagesPerSheet}`;
            if (pagesPerSheet === 2) {
                gridClass = (orientation === "landscape") ? "nup-grid nup-2-v" : "nup-grid nup-2-h";
            } else if (pagesPerSheet === 6) {
                gridClass = (orientation === "landscape") ? "nup-grid nup-6-land" : "nup-grid nup-6";
            }
            nupGrid.className = gridClass;

            const totalSheets = Math.ceil(pagesToRender.length / pagesPerSheet) || 1;
            let currentSheet = Math.floor(livePreviewIndex / pagesPerSheet);
            if (currentSheet >= totalSheets) {
                currentSheet = Math.max(0, totalSheets - 1);
                livePreviewIndex = currentSheet * pagesPerSheet;
            } else if (currentSheet < 0) {
                currentSheet = 0;
                livePreviewIndex = 0;
            }
            const startIdx = currentSheet * pagesPerSheet;

            let cellsHtml = "";
            let minPageInSheet = 999999;
            let maxPageInSheet = 0;
            for (let r = 0; r < rows; r++) {
                for (let c = 0; c < cols; c++) {
                    const slotIdx = (pageOrder === "vertical") ? (c * rows + r) : (r * cols + c);
                    const pageIdx = startIdx + slotIdx;
                    // CRITICAL FIX: If pageIdx exceeds document pages, MUST BE COMPLETELY BLANK.
                    // NEVER fallback to livePreviewPages[0] or duplicate Page 1.
                    const targetPage = (pageIdx < pagesToRender.length) ? pagesToRender[pageIdx] : null;

                    if (targetPage && targetPage.src) {
                        const docP = targetPage.docPageNum || (pageIdx + 1);
                        if (docP < minPageInSheet) minPageInSheet = docP;
                        if (docP > maxPageInSheet) maxPageInSheet = docP;
                        cellsHtml += `<div class="nup-cell"><span class="nup-page-badge">P.${docP}</span><img src="${targetPage.src}" class="nup-cell-element" alt="${escapeHtml(targetPage.title)}"></div>`;
                    } else {
                        cellsHtml += `<div class="nup-cell nup-blank-slot"></div>`;
                    }
                }
            }
            nupGrid.innerHTML = cellsHtml;

            if (pageIndicator) {
                let rangeStr = "";
                if (maxPageInSheet >= minPageInSheet) {
                    if (minPageInSheet === maxPageInSheet) {
                        rangeStr = ` (Page ${minPageInSheet})`;
                    } else {
                        rangeStr = ` (Pages ${minPageInSheet}–${maxPageInSheet})`;
                    }
                }
                let sideStr = "";
                if (printSide === "double") {
                    sideStr = (currentSheet % 2 === 0) ? " • Front" : " • Back";
                }
                pageIndicator.textContent = `Sheet ${currentSheet + 1} of ${totalSheets}${rangeStr}${sideStr}`;
            }
            if (navBar) {
                navBar.style.display = totalSheets > 1 ? "flex" : "none";
            }
            if (prevBtn) prevBtn.disabled = (currentSheet <= 0);
            if (nextBtn) nextBtn.disabled = (currentSheet >= totalSheets - 1);
        }
    } else {
        const notebookSpread = document.getElementById("notebookSpreadPreview");
        const notebookLeftImg = document.getElementById("notebookLeftImg");
        const notebookLeftBlank = document.getElementById("notebookLeftBlank");
        const notebookLeftTagText = document.getElementById("notebookLeftTagText");
        const notebookRightImg = document.getElementById("notebookRightImg");
        const notebookRightBlank = document.getElementById("notebookRightBlank");
        const notebookRightTagText = document.getElementById("notebookRightTagText");
        const notebookFlipBadge = document.getElementById("notebookFlipBadge");
        const notebookShortEdgeIndicator = document.getElementById("notebookShortEdgeIndicator");
        const paperSheetPreview = document.getElementById("paperSheetPreview");

        if (printSide === "double" && notebookSpread) {
            if (nupGrid) nupGrid.style.display = "none";
            if (standardContent) standardContent.style.display = "none";
            if (paperSheetPreview) paperSheetPreview.style.display = "none";
            notebookSpread.style.display = "flex";

            const totalPages = pagesToRender.length;
            const currentSpreadIndex = Math.floor(livePreviewIndex / 2) * 2;
            const leftIdx = currentSpreadIndex;
            const rightIdx = currentSpreadIndex + 1;

            const leftPage = (leftIdx < totalPages) ? pagesToRender[leftIdx] : null;
            const rightPage = (rightIdx < totalPages) ? pagesToRender[rightIdx] : null;

            // Render Left Page (Front side)
            if (leftPage && notebookLeftImg) {
                notebookLeftImg.src = leftPage.src;
                notebookLeftImg.style.display = "block";
                notebookLeftImg.alt = leftPage.title;
                if (notebookLeftBlank) notebookLeftBlank.style.display = "none";
                const leftLabel = leftPage.docPageNum ? `Page ${leftPage.docPageNum} • Front` : `Page ${leftIdx + 1} • Front`;
                if (notebookLeftTagText) notebookLeftTagText.textContent = leftLabel;
                const leftContainer = document.getElementById("notebookLeftPage") || notebookSpread;
                applyMathematicalPreviewLayout(notebookLeftImg, leftPage, leftContainer);
            } else {
                if (notebookLeftImg) notebookLeftImg.style.display = "none";
                if (notebookLeftBlank) notebookLeftBlank.style.display = "flex";
                if (notebookLeftTagText) notebookLeftTagText.textContent = "Empty";
            }

            // Render Right Page (Back side)
            if (rightPage && notebookRightImg) {
                notebookRightImg.src = rightPage.src;
                notebookRightImg.style.display = "block";
                notebookRightImg.alt = rightPage.title;
                if (notebookRightBlank) notebookRightBlank.style.display = "none";
                const rightLabel = rightPage.docPageNum ? `Page ${rightPage.docPageNum} • Back` : `Page ${rightIdx + 1} • Back`;
                if (notebookRightTagText) notebookRightTagText.textContent = rightLabel;
                const rightContainer = document.getElementById("notebookRightPage") || notebookSpread;
                applyMathematicalPreviewLayout(notebookRightImg, rightPage, rightContainer);

                if (duplexBinding === "short_edge") {
                    if (notebookFlipBadge) notebookFlipBadge.style.display = "inline-block";
                    if (notebookShortEdgeIndicator) notebookShortEdgeIndicator.style.display = "inline-flex";
                } else {
                    if (notebookFlipBadge) notebookFlipBadge.style.display = "none";
                    if (notebookShortEdgeIndicator) notebookShortEdgeIndicator.style.display = "none";
                }
            } else {
                if (notebookRightImg) notebookRightImg.style.display = "none";
                if (notebookRightBlank) notebookRightBlank.style.display = "flex";
                if (notebookRightTagText) notebookRightTagText.textContent = "Blank Back Side";
                if (notebookFlipBadge) notebookFlipBadge.style.display = "none";
                if (notebookShortEdgeIndicator) notebookShortEdgeIndicator.style.display = "none";
            }

            const totalSpreads = Math.ceil(totalPages / 2) || 1;
            const currentSpreadNum = Math.floor(currentSpreadIndex / 2) + 1;

            if (pageIndicator) {
                const leftNum = leftPage ? (leftPage.docPageNum || leftIdx + 1) : (leftIdx + 1);
                const rightNum = rightPage ? (rightPage.docPageNum || rightIdx + 1) : null;
                if (rightPage) {
                    pageIndicator.textContent = `Pages ${leftNum} & ${rightNum} (Spread ${currentSpreadNum} of ${totalSpreads})`;
                } else {
                    pageIndicator.textContent = `Page ${leftNum} (Spread ${currentSpreadNum} of ${totalSpreads})`;
                }
            }
            if (navBar) {
                navBar.style.display = totalSpreads > 1 ? "flex" : "none";
            }
            if (prevBtn) prevBtn.disabled = (currentSpreadIndex <= 0);
            if (nextBtn) nextBtn.disabled = (rightIdx >= totalPages - 1);

        } else {
            if (notebookSpread) notebookSpread.style.display = "none";
            if (paperSheetPreview) paperSheetPreview.style.display = "flex";
            if (nupGrid) nupGrid.style.display = "none";
            if (standardContent) standardContent.style.display = "block";

            const totalPages = pagesToRender.length;
            const pageIdx = Math.max(0, Math.min(livePreviewIndex, totalPages - 1));
            const activePage = pagesToRender[pageIdx];

            if (activePage && liveImg) {
                liveImg.src = activePage.src;
                liveImg.style.display = "block";
                liveImg.alt = activePage.title;
                applyMathematicalPreviewLayout(liveImg, activePage, paperSheetPreview);
            }

            if (pageIndicator) {
                const docNum = activePage?.docPageNum;
                const docSuffix = docNum ? ` (Doc P.${docNum})` : "";
                pageIndicator.textContent = `${activePage?.title || 'Page'} [${pageIdx + 1} of ${totalPages}]${docSuffix}`;
            }
            if (navBar) {
                navBar.style.display = totalPages > 1 ? "flex" : "none";
            }
            if (prevBtn) prevBtn.disabled = (pageIdx <= 0);
            if (nextBtn) nextBtn.disabled = (pageIdx >= totalPages - 1);
        }
    }
}

window.currentFileManifest = [];
window.activePreviewFileIndex = 0;

function getStoredFileManifest() {
    let manifest = [];
    try {
        const storedConfigs = localStorage.getItem("printflowFileConfigs");
        if (storedConfigs) {
            const parsed = JSON.parse(storedConfigs);
            if (Array.isArray(parsed) && parsed.length > 0) {
                manifest = parsed;
            }
        }
    } catch (e) {
        console.warn("getStoredFileManifest config parse note:", e);
    }

    if (!manifest.length) {
        try {
            const storedDetails = localStorage.getItem("fileListDetails");
            if (storedDetails) {
                const parsed = JSON.parse(storedDetails);
                if (Array.isArray(parsed) && parsed.length > 0) {
                    manifest = parsed.map((item, idx) => ({
                        id: item.id || `file_${idx}_${Date.now()}`,
                        name: item.name || `Document ${idx + 1}.pdf`,
                        path: item.path || item.backendPath || "",
                        size: item.size || 0,
                        pages: parseInt(item.pages || 1, 10),
                        sequence: typeof item.sequence === "number" ? item.sequence : idx
                    }));
                }
            }
        } catch (e) {
            console.warn("getStoredFileManifest details parse note:", e);
        }
    }

    if (!manifest.length) {
        const singleName = localStorage.getItem("fileName") || "document.pdf";
        const singlePath = localStorage.getItem("backendFilePath") || "";
        const singlePages = parseInt(localStorage.getItem("pdfPageCount") || "1", 10);
        manifest.push({
            id: `file_0_${Date.now()}`,
            name: singleName,
            path: singlePath,
            size: parseInt(localStorage.getItem("fileSize") || "0", 10),
            pages: singlePages,
            sequence: 0
        });
    }

    // Ensure defaults and compute sheets & price
    manifest = manifest.map((f, idx) => {
        const ensured = ensureFileConfigDefaults(f, idx);
        return computeFileSheetsAndPrice(ensured);
    });

    window.currentFileManifest = manifest;
    return manifest;
}

function ensureFileConfigDefaults(file, idx) {
    const f = { ...file };
    f.id = f.id || `file_${idx}_${Date.now()}`;
    f.name = f.name || `Document ${idx + 1}.pdf`;
    f.path = f.path || f.backendPath || localStorage.getItem("backendFilePath") || "";
    f.pages = Math.max(1, parseInt(f.pages || 1, 10));
    f.sequence = typeof f.sequence === "number" ? f.sequence : idx;

    f.pageSelection = f.pageSelection || "all";
    f.customPagesInput = typeof f.customPagesInput === "string" ? f.customPagesInput : "";
    f.pageRange = f.pageRange || "all";
    f.selectedPagesCount = typeof f.selectedPagesCount === "number" ? f.selectedPagesCount : f.pages;

    f.printSide = f.printSide || (f.pages >= 2 ? "double" : "single");
    f.duplexBinding = f.duplexBinding || "long_edge";
    f.duplex = f.duplex || (f.printSide === "double" ? (f.duplexBinding === "short_edge" ? "duplex_short" : "duplex_long") : "single");

    f.copies = Math.max(1, parseInt(f.copies || 1, 10));
    f.colorMode = f.colorMode || "black_white";
    f.orientation = f.orientation || "portrait";
    f.paperSize = f.paperSize || "a4";
    f.scaleMode = f.scaleMode || "fit";
    f.printMode = f.printMode || "standard";
    f.pagesPerSheet = parseInt(f.pagesPerSheet || 1, 10);

    return f;
}

function computeFileSheetsAndPrice(file) {
    const f = { ...file };
    const totalPages = Math.max(1, parseInt(f.pages || 1, 10));
    const validation = parseAndValidatePageSelection(f.pageSelection, f.customPagesInput, totalPages);

    f.isValid = validation.isValid;
    f.validationError = validation.isValid ? "" : validation.error;
    f.selectedPages = validation.isValid ? validation.pages : Array.from({ length: totalPages }, (_, i) => i + 1);
    f.selectedPagesCount = f.selectedPages.length;
    f.pageRange = validation.isValid ? validation.canonicalString : "all";

    // Duplex resolution
    if (f.printSide === "double") {
        f.duplex = (f.duplexBinding === "short_edge") ? "duplex_short" : "duplex_long";
    } else {
        f.duplex = "single";
    }

    const copies = Math.max(1, parseInt(f.copies || 1, 10));

    // Pricing & sheet calculation:
    if (f.printMode === "micro_xerox" && f.pagesPerSheet > 1) {
        const sheetsPerCopy = Math.ceil(f.selectedPagesCount / f.pagesPerSheet);
        f.calculatedSheets = sheetsPerCopy * copies;
        f.calculatedPrice = parseFloat((sheetsPerCopy * copies * PRICING.micro_xerox_sheet).toFixed(2));
    } else if (f.colorMode === "color") {
        f.calculatedSheets = f.selectedPagesCount * copies;
        f.calculatedPrice = parseFloat((f.selectedPagesCount * copies * PRICING.color_single).toFixed(2));
    } else if (f.printSide === "double") {
        const sheetsPerCopy = Math.ceil(f.selectedPagesCount / 2);
        f.calculatedSheets = sheetsPerCopy * copies;
        f.calculatedPrice = parseFloat((f.selectedPagesCount * copies * PRICING.bw_double).toFixed(2));
    } else {
        // B&W Single
        f.calculatedSheets = f.selectedPagesCount * copies;
        f.calculatedPrice = parseFloat((f.selectedPagesCount * copies * PRICING.bw_single).toFixed(2));
    }

    return f;
}

function saveFileManifest(manifest) {
    window.currentFileManifest = manifest;
    localStorage.setItem("printflowFileConfigs", JSON.stringify(manifest));

    // Keep legacy localStorage keys updated
    const totalSelectedPages = manifest.reduce((acc, f) => acc + (f.selectedPagesCount * f.copies), 0);
    const totalSheets = manifest.reduce((acc, f) => acc + f.calculatedSheets, 0);
    const totalAmount = manifest.reduce((acc, f) => acc + f.calculatedPrice, 0);
    const fileNames = manifest.map(f => f.name).join(", ");

    localStorage.setItem("fileName", fileNames);
    localStorage.setItem("pdfPageCount", String(totalSelectedPages));
    localStorage.setItem("selectedPagesCount", String(totalSelectedPages));
    localStorage.setItem("amount", totalAmount.toFixed(2));
    if (manifest.length > 0 && manifest[0].path) {
        localStorage.setItem("backendFilePath", manifest[0].path);
    }
    // Also sync fileListDetails
    const details = manifest.map((f, idx) => ({
        id: f.id,
        name: f.name,
        path: f.path,
        pages: f.pages,
        sequence: idx,
        status: "UPLOADED",
        selected_pages_count: f.selectedPagesCount,
        page_range: f.pageRange,
        copies: f.copies,
        color_mode: f.colorMode,
        duplex: f.duplex,
        binding: f.duplexBinding,
        orientation: f.orientation,
        paper_size: f.paperSize,
        scale_mode: f.scaleMode,
        print_mode: f.printMode,
        pages_per_sheet: f.pagesPerSheet,
        calculated_sheets: f.calculatedSheets,
        calculated_price: f.calculatedPrice
    }));
    localStorage.setItem("fileListDetails", JSON.stringify(details));
}

function updateGlobalOrderSummary(manifest) {
    const totalFiles = manifest.length;
    let totalSelectedPages = 0;
    let totalSheets = 0;
    let totalAmount = 0;
    let allValid = true;

    manifest.forEach(f => {
        totalSelectedPages += (f.selectedPagesCount * f.copies);
        totalSheets += f.calculatedSheets;
        totalAmount += f.calculatedPrice;
        if (!f.isValid || f.selectedPagesCount <= 0) {
            allValid = false;
        }
    });

    const fileCountBadge = document.getElementById("fileCountBadge");
    if (fileCountBadge) {
        fileCountBadge.textContent = `${totalFiles} Document${totalFiles > 1 ? 's' : ''}`;
    }

    const summaryTotalFiles = document.getElementById("summaryTotalFiles");
    if (summaryTotalFiles) {
        summaryTotalFiles.textContent = `${totalFiles} Document${totalFiles > 1 ? 's' : ''}`;
    }

    const summaryTotalPages = document.getElementById("summaryTotalPages");
    if (summaryTotalPages) {
        summaryTotalPages.textContent = `${totalSelectedPages} Page${totalSelectedPages > 1 ? 's' : ''}`;
    }

    const summaryTotalSheets = document.getElementById("summaryTotalSheets");
    if (summaryTotalSheets) {
        summaryTotalSheets.textContent = `${totalSheets} Sheet${totalSheets > 1 ? 's' : ''}`;
    }

    const totalPriceEl = document.getElementById("totalPrice");
    if (totalPriceEl) {
        totalPriceEl.textContent = `₹${totalAmount.toFixed(2)}`;
    }

    const pageCountEl = document.getElementById("pageCount");
    if (pageCountEl) {
        pageCountEl.textContent = `Total: ${totalFiles} Document${totalFiles > 1 ? 's' : ''} • ${totalSelectedPages} Pages`;
    }

    const fileNameEl = document.getElementById("fileName");
    if (fileNameEl) {
        fileNameEl.textContent = manifest.map(f => f.name).join(", ");
    }

    const paymentBtnEl = document.getElementById("paymentBtn");
    if (paymentBtnEl) {
        paymentBtnEl.disabled = (!allValid || totalSelectedPages <= 0);
    }
}

function updatePrintDetailsAndPreview() {
    const paperSheetPreview = document.getElementById("paperSheetPreview");
    const notebookSpreadPreview = document.getElementById("notebookSpreadPreview");
    const previewLabelBadge = document.getElementById("previewLabelBadge");

    if (!paperSheetPreview && !notebookSpreadPreview) return;

    const manifest = (window.currentFileManifest && window.currentFileManifest.length)
        ? window.currentFileManifest
        : getStoredFileManifest();
    const activeFile = manifest[window.activePreviewFileIndex || 0] || manifest[0];
    if (!activeFile) return;

    const paperSize = activeFile.paperSize || "a4";
    const orientation = activeFile.orientation || "portrait";
    const scaleMode = activeFile.scaleMode || "fit";
    const colorMode = activeFile.colorMode || "black_white";
    const printSide = activeFile.printSide || "single";
    const duplexBinding = activeFile.duplexBinding || "long_edge";

    const colorClass = (colorMode === "color") ? "color-mode" : "bw-mode";
    const edgeClass = (duplexBinding === "short_edge") ? "short-edge" : "long-edge";

    if (paperSheetPreview && notebookSpreadPreview) {
        if (printSide === "double") {
            paperSheetPreview.style.display = "none";
            notebookSpreadPreview.style.display = "flex";
            notebookSpreadPreview.className = `notebook-spread-container size-${paperSize} ${orientation} ${scaleMode} ${colorClass} ${edgeClass}`;
        } else {
            notebookSpreadPreview.style.display = "none";
            paperSheetPreview.style.display = "flex";
            paperSheetPreview.className = `paper-sheet size-${paperSize} ${orientation} ${scaleMode} ${colorClass}`;
        }
    }

    if (previewLabelBadge) {
        if (printSide === "double") {
            previewLabelBadge.textContent = (duplexBinding === "short_edge")
                ? "Double Side • Short Edge (Flip 🗓️)"
                : "Double Side • Long Edge (Booklet 📖)";
        } else {
            previewLabelBadge.textContent = (scaleMode === "actual") ? "Standard (Actual Size)" : "Standard (Full Page)";
        }
    }

    renderRealLivePreviewUI();
}

function renderPerFileConfigCards() {
    const container = document.getElementById("fileConfigsContainer");
    if (!container) return;

    const manifest = getStoredFileManifest();
    container.innerHTML = "";

    manifest.forEach((file, idx) => {
        const card = document.createElement("div");
        card.className = `file-config-card ${idx === window.activePreviewFileIndex ? 'is-active-preview' : ''}`;
        card.dataset.idx = idx;
        card.dataset.fileId = file.id;
        card.draggable = true;

        const isOddDuplex = (file.duplex !== "single" && (file.selectedPagesCount % 2 !== 0));
        const blankSheetNote = isOddDuplex
            ? `<span style="font-size:11px; color:#c2410c; font-weight:700; background:#ffedd5; padding:2px 6px; border-radius:4px; border:1px solid #fdba74;">Sheet ${Math.ceil(file.selectedPagesCount / 2)} Back is Blank</span>`
            : "";

        const sizeStr = file.size ? (file.size > 1048576 ? (file.size / 1048576).toFixed(1) + " MB" : (file.size / 1024).toFixed(0) + " KB") : "";

        card.innerHTML = `
            <div class="file-card-header">
                <div class="file-card-lead">
                    <div class="file-drag-handle" title="Drag to reorder print sequence">⋮⋮</div>
                    <div class="file-reorder-btns">
                        <button type="button" class="btn-move-file btn-move-up" data-idx="${idx}" title="Move Up" ${idx === 0 ? 'disabled' : ''}>▲</button>
                        <button type="button" class="btn-move-file btn-move-down" data-idx="${idx}" title="Move Down" ${idx === manifest.length - 1 ? 'disabled' : ''}>▼</button>
                    </div>
                    <span class="file-sequence-tag">#${idx + 1}</span>
                    <div class="file-info-block">
                        <span class="file-name-heading" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
                        <div class="file-meta-sub">${file.pages} Page${file.pages > 1 ? 's' : ''}${sizeStr ? ' • ' + sizeStr : ''}</div>
                    </div>
                </div>
            </div>

            <div class="file-settings-grid">
                <!-- 1. Pages selection -->
                <div class="file-setting-item" style="grid-column: 1 / -1;">
                    <label class="file-input-label">📄 Pages to Print</label>
                    <div class="pages-radio-grid">
                        <label><input type="radio" name="pageSel_${idx}" value="all" ${file.pageSelection === 'all' ? 'checked' : ''}> All (${file.pages})</label>
                        <label><input type="radio" name="pageSel_${idx}" value="odd" ${file.pageSelection === 'odd' ? 'checked' : ''}> Odd Pages</label>
                        <label><input type="radio" name="pageSel_${idx}" value="even" ${file.pageSelection === 'even' ? 'checked' : ''}> Even Pages</label>
                        <label><input type="radio" name="pageSel_${idx}" value="custom" ${file.pageSelection === 'custom' ? 'checked' : ''}> Custom Range</label>
                    </div>
                    <div class="custom-range-container" style="display: ${file.pageSelection === 'custom' ? 'block' : 'none'}; margin-top: 6px;">
                        <input type="text" class="setting-input custom-page-range-input" data-idx="${idx}" placeholder="e.g. 1-3, 5" value="${escapeHtml(file.customPagesInput || '')}">
                        <div class="custom-range-hint" style="font-size: 11px; color: #78350f; margin-top: 2px;">Enter page numbers or ranges (e.g. 1, 3, 5-8)</div>
                        <div class="custom-range-error" style="color: #dc2626; font-size: 11px; font-weight: 700; display: ${file.validationError ? 'block' : 'none'}; margin-top: 2px;">${escapeHtml(file.validationError || '')}</div>
                    </div>
                </div>

                <!-- 2. Print Side (Single vs Double) -->
                <div class="file-setting-item" style="grid-column: 1 / -1;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <label class="file-input-label" style="margin-bottom: 0;">📖 Print Side</label>
                        <span class="side-status-tag" style="font-size: 11px; color: #ea580c; font-weight: 700;">
                            ${file.printSide === 'double' ? 'Double Side Active (₹1/pg)' : 'Single Side Active (₹2/pg)'}
                        </span>
                    </div>
                    <div class="file-radio-grid side-radio-grid">
                        <label class="file-radio-pill side-pill ${file.printSide === 'single' ? 'is-selected' : ''}">
                            <input type="radio" name="printSide_${idx}" value="single" ${file.printSide === 'single' ? 'checked' : ''}>
                            <span>📄 Single Side (₹2/pg)</span>
                        </label>
                        <label class="file-radio-pill side-pill ${file.printSide === 'double' ? 'is-selected' : ''} ${file.colorMode === 'color' ? 'is-disabled' : ''}" title="${file.colorMode === 'color' ? 'Color print is single-sided only' : ''}">
                            <input type="radio" name="printSide_${idx}" value="double" ${file.printSide === 'double' ? 'checked' : ''} ${file.colorMode === 'color' ? 'disabled' : ''}>
                            <span>📖 Double Side (₹1/pg)</span>
                        </label>
                    </div>

                    <!-- Duplex Flip Direction / Binding Edge -->
                    <div class="file-binding-container" style="display: ${file.printSide === 'double' ? 'block' : 'none'}; margin-top: 8px; padding: 8px 12px; background: #fff7ed; border-radius: 8px; border: 1.5px dashed #fdba74;">
                        <label style="font-size: 11px; font-weight: 800; color: #9a3412; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; display: block;">
                            🔄 Duplex Flip Direction / Binding Edge:
                        </label>
                        <div class="file-radio-grid" style="grid-template-columns: 1fr 1fr;">
                            <label class="file-radio-pill binding-pill ${file.duplexBinding !== 'short_edge' ? 'is-selected' : ''}">
                                <input type="radio" name="duplexBinding_${idx}" value="long_edge" ${file.duplexBinding !== 'short_edge' ? 'checked' : ''}>
                                <span>📖 Long Edge (Booklet)</span>
                            </label>
                            <label class="file-radio-pill binding-pill ${file.duplexBinding === 'short_edge' ? 'is-selected' : ''}">
                                <input type="radio" name="duplexBinding_${idx}" value="short_edge" ${file.duplexBinding === 'short_edge' ? 'checked' : ''}>
                                <span>🗓️ Short Edge (Flip)</span>
                            </label>
                        </div>
                    </div>
                </div>

                <!-- 3. Copies -->
                <div class="file-setting-item">
                    <label class="file-input-label">🔢 Copies</label>
                    <div class="copies-counter-box">
                        <button type="button" class="btn-step-copy step-minus" data-idx="${idx}">-</button>
                        <input type="number" class="setting-input copy-input-num file-copies-input" data-idx="${idx}" min="1" max="99" value="${file.copies || 1}">
                        <button type="button" class="btn-step-copy step-plus" data-idx="${idx}">+</button>
                    </div>
                </div>

                <!-- 4. Color Mode -->
                <div class="file-setting-item">
                    <label class="file-input-label">🎨 Color Mode</label>
                    <select class="setting-select file-color-select" data-idx="${idx}">
                        <option value="black_white" ${file.colorMode === 'black_white' ? 'selected' : ''}>Black & White (B&W)</option>
                        <option value="color" ${file.colorMode === 'color' ? 'selected' : ''}>Color Print (₹6/pg)</option>
                    </select>
                </div>

                <!-- 5. Orientation -->
                <div class="file-setting-item">
                    <label class="file-input-label">🔄 Orientation</label>
                    <select class="setting-select file-orientation-select" data-idx="${idx}">
                        <option value="portrait" ${file.orientation === 'portrait' ? 'selected' : ''}>Portrait (Vertical)</option>
                        <option value="landscape" ${file.orientation === 'landscape' ? 'selected' : ''}>Landscape (Horizontal)</option>
                    </select>
                </div>

                <!-- 6. Paper Size -->
                <div class="file-setting-item">
                    <label class="file-input-label">📏 Paper Size</label>
                    <select class="setting-select file-papersize-select" data-idx="${idx}">
                        <option value="a4" ${file.paperSize === 'a4' ? 'selected' : ''}>A4</option>
                        <option value="letter" ${file.paperSize === 'letter' ? 'selected' : ''}>Letter</option>
                        <option value="legal" ${file.paperSize === 'legal' ? 'selected' : ''}>Legal</option>
                    </select>
                </div>

                <!-- 7. Fit / Scale -->
                <div class="file-setting-item">
                    <label class="file-input-label">📐 Fit / Scale</label>
                    <select class="setting-select file-scale-select" data-idx="${idx}">
                        <option value="fit" ${file.scaleMode === 'fit' ? 'selected' : ''}>Fit to Printable Area</option>
                        <option value="actual" ${file.scaleMode === 'actual' ? 'selected' : ''}>Actual Size (100%)</option>
                    </select>
                </div>
            </div>

            <!-- File Summary Strip -->
            <div class="file-summary-strip">
                <div class="sheet-flow-indicator">
                    <span>📄 Selected: <strong>${file.selectedPagesCount} Page${file.selectedPagesCount > 1 ? 's' : ''}</strong></span>
                    <span>•</span>
                    <span>📑 Physical Sheets: <strong class="sheet-badge">${file.calculatedSheets} Sheet${file.calculatedSheets > 1 ? 's' : ''}</strong></span>
                    ${blankSheetNote}
                </div>
                <div class="file-cost-badge-row">
                    <span style="color:#78350f; font-weight:700; font-size:12px;">File Subtotal:</span>
                    <span class="file-subtotal-badge">₹${file.calculatedPrice.toFixed(2)}</span>
                </div>
            </div>
        `;

        container.appendChild(card);
    });

    attachCardEventListeners();
    updateGlobalOrderSummary(manifest);
    updatePrintDetailsAndPreview();
}

function attachCardEventListeners() {
    const container = document.getElementById("fileConfigsContainer");
    if (!container) return;

    // Card selection for preview
    container.querySelectorAll(".file-config-card").forEach(card => {
        card.addEventListener("click", (e) => {
            if (e.target.closest("button") || e.target.closest("input") || e.target.closest("select")) return;
            const idx = parseInt(card.dataset.idx, 10);
            if (!isNaN(idx) && idx !== window.activePreviewFileIndex) {
                window.activePreviewFileIndex = idx;
                container.querySelectorAll(".file-config-card").forEach((c, i) => {
                    c.classList.toggle("is-active-preview", i === window.activePreviewFileIndex);
                });
                updatePrintDetailsAndPreview();
            }
        });
    });

    // Move buttons
    container.querySelectorAll(".btn-move-up").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.idx, 10);
            if (idx > 0) {
                const manifest = getStoredFileManifest();
                const temp = manifest[idx];
                manifest[idx] = manifest[idx - 1];
                manifest[idx - 1] = temp;
                manifest.forEach((f, i) => { f.sequence = i; });
                window.activePreviewFileIndex = idx - 1;
                saveFileManifest(manifest);
                renderPerFileConfigCards();
            }
        });
    });

    container.querySelectorAll(".btn-move-down").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.idx, 10);
            const manifest = getStoredFileManifest();
            if (idx < manifest.length - 1) {
                const temp = manifest[idx];
                manifest[idx] = manifest[idx + 1];
                manifest[idx + 1] = temp;
                manifest.forEach((f, i) => { f.sequence = i; });
                window.activePreviewFileIndex = idx + 1;
                saveFileManifest(manifest);
                renderPerFileConfigCards();
            }
        });
    });

    // Drag and Drop
    let draggedIndex = null;
    container.querySelectorAll(".file-config-card").forEach(card => {
        card.addEventListener("dragstart", (e) => {
            draggedIndex = parseInt(card.dataset.idx, 10);
            card.classList.add("is-dragging");
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", String(draggedIndex));
        });

        card.addEventListener("dragend", () => {
            card.classList.remove("is-dragging");
            container.querySelectorAll(".file-config-card").forEach(c => {
                c.classList.remove("drag-over-top", "drag-over-bottom");
            });
        });

        card.addEventListener("dragover", (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            const rect = card.getBoundingClientRect();
            const midY = rect.top + rect.height / 2;
            if (e.clientY < midY) {
                card.classList.add("drag-over-top");
                card.classList.remove("drag-over-bottom");
            } else {
                card.classList.add("drag-over-bottom");
                card.classList.remove("drag-over-top");
            }
        });

        card.addEventListener("dragleave", () => {
            card.classList.remove("drag-over-top", "drag-over-bottom");
        });

        card.addEventListener("drop", (e) => {
            e.preventDefault();
            const targetIndex = parseInt(card.dataset.idx, 10);
            card.classList.remove("drag-over-top", "drag-over-bottom");
            if (draggedIndex === null || isNaN(targetIndex) || draggedIndex === targetIndex) return;

            const manifest = getStoredFileManifest();
            const [movedItem] = manifest.splice(draggedIndex, 1);
            manifest.splice(targetIndex, 0, movedItem);
            manifest.forEach((f, i) => { f.sequence = i; });
            window.activePreviewFileIndex = targetIndex;
            saveFileManifest(manifest);
            renderPerFileConfigCards();
        });
    });

    // Page selection radios
    container.querySelectorAll(".pages-radio-grid input[type='radio']").forEach(radio => {
        radio.addEventListener("change", () => {
            const idx = parseInt(radio.name.split("_")[1], 10);
            const manifest = getStoredFileManifest();
            if (manifest[idx]) {
                manifest[idx].pageSelection = radio.value;
                const card = container.querySelector(`.file-config-card[data-idx="${idx}"]`);
                const customContainer = card ? card.querySelector(".custom-range-container") : null;
                if (customContainer) {
                    customContainer.style.display = (radio.value === "custom") ? "block" : "none";
                }
                const updated = computeFileSheetsAndPrice(manifest[idx]);
                manifest[idx] = updated;
                saveFileManifest(manifest);
                updateCardSummaryStrip(card, updated);
                updateGlobalOrderSummary(manifest);
                if (idx === window.activePreviewFileIndex) updatePrintDetailsAndPreview();
            }
        });
    });

    // Custom pages range input
    container.querySelectorAll(".custom-page-range-input").forEach(input => {
        input.addEventListener("input", () => {
            const idx = parseInt(input.dataset.idx, 10);
            const manifest = getStoredFileManifest();
            if (manifest[idx]) {
                manifest[idx].customPagesInput = input.value.trim();
                const updated = computeFileSheetsAndPrice(manifest[idx]);
                manifest[idx] = updated;
                const card = container.querySelector(`.file-config-card[data-idx="${idx}"]`);
                const errEl = card ? card.querySelector(".custom-range-error") : null;
                if (errEl) {
                    errEl.textContent = updated.validationError || "";
                    errEl.style.display = updated.validationError ? "block" : "none";
                }
                saveFileManifest(manifest);
                updateCardSummaryStrip(card, updated);
                updateGlobalOrderSummary(manifest);
                if (idx === window.activePreviewFileIndex) updatePrintDetailsAndPreview();
            }
        });
    });

    // Print Side Radios (Single vs Double)
    container.querySelectorAll(".side-radio-grid input[type='radio']").forEach(radio => {
        radio.addEventListener("change", () => {
            const idx = parseInt(radio.name.split("_")[1], 10);
            const manifest = getStoredFileManifest();
            if (manifest[idx]) {
                const isDouble = (radio.value === "double");
                manifest[idx].printSide = isDouble ? "double" : "single";
                if (isDouble) {
                    manifest[idx].duplexBinding = manifest[idx].duplexBinding || "long_edge";
                    manifest[idx].duplex = (manifest[idx].duplexBinding === "short_edge") ? "duplex_short" : "duplex_long";
                } else {
                    manifest[idx].duplex = "single";
                }
                const updated = computeFileSheetsAndPrice(manifest[idx]);
                manifest[idx] = updated;
                saveFileManifest(manifest);

                const card = container.querySelector(`.file-config-card[data-idx="${idx}"]`);
                if (card) {
                    card.querySelectorAll(".side-pill").forEach(p => {
                        const r = p.querySelector("input[type='radio']");
                        p.classList.toggle("is-selected", r && r.value === radio.value);
                    });
                    const bindingContainer = card.querySelector(".file-binding-container");
                    if (bindingContainer) {
                        bindingContainer.style.display = isDouble ? "block" : "none";
                    }
                    const statusTag = card.querySelector(".side-status-tag");
                    if (statusTag) {
                        statusTag.textContent = isDouble ? "Double Side Active (₹1/pg)" : "Single Side Active (₹2/pg)";
                    }
                    updateCardSummaryStrip(card, updated);
                }
                updateGlobalOrderSummary(manifest);
                if (idx === window.activePreviewFileIndex) updatePrintDetailsAndPreview();
            }
        });
    });

    // Duplex Flip / Binding Radios (Long Edge vs Short Edge)
    container.querySelectorAll(".file-binding-container input[type='radio']").forEach(radio => {
        radio.addEventListener("change", () => {
            const idx = parseInt(radio.name.split("_")[1], 10);
            const manifest = getStoredFileManifest();
            if (manifest[idx]) {
                manifest[idx].duplexBinding = radio.value;
                manifest[idx].duplex = (radio.value === "short_edge") ? "duplex_short" : "duplex_long";
                const updated = computeFileSheetsAndPrice(manifest[idx]);
                manifest[idx] = updated;
                saveFileManifest(manifest);

                const card = container.querySelector(`.file-config-card[data-idx="${idx}"]`);
                if (card) {
                    card.querySelectorAll(".binding-pill").forEach(p => {
                        const r = p.querySelector("input[type='radio']");
                        p.classList.toggle("is-selected", r && r.value === radio.value);
                    });
                    updateCardSummaryStrip(card, updated);
                }
                updateGlobalOrderSummary(manifest);
                if (idx === window.activePreviewFileIndex) updatePrintDetailsAndPreview();
            }
        });
    });

    // Copies stepper
    container.querySelectorAll(".btn-step-copy").forEach(btn => {
        btn.addEventListener("click", () => {
            const idx = parseInt(btn.dataset.idx, 10);
            const card = container.querySelector(`.file-config-card[data-idx="${idx}"]`);
            const input = card ? card.querySelector(".file-copies-input") : null;
            if (!input) return;
            let val = parseInt(input.value || "1", 10);
            if (btn.classList.contains("step-minus")) {
                val = Math.max(1, val - 1);
            } else {
                val = Math.min(99, val + 1);
            }
            input.value = val;
            const manifest = getStoredFileManifest();
            if (manifest[idx]) {
                manifest[idx].copies = val;
                const updated = computeFileSheetsAndPrice(manifest[idx]);
                manifest[idx] = updated;
                saveFileManifest(manifest);
                updateCardSummaryStrip(card, updated);
                updateGlobalOrderSummary(manifest);
            }
        });
    });

    container.querySelectorAll(".file-copies-input").forEach(input => {
        input.addEventListener("input", () => {
            const idx = parseInt(input.dataset.idx, 10);
            let val = parseInt(input.value || "1", 10);
            if (isNaN(val) || val < 1) val = 1;
            const manifest = getStoredFileManifest();
            if (manifest[idx]) {
                manifest[idx].copies = val;
                const updated = computeFileSheetsAndPrice(manifest[idx]);
                manifest[idx] = updated;
                saveFileManifest(manifest);
                const card = container.querySelector(`.file-config-card[data-idx="${idx}"]`);
                updateCardSummaryStrip(card, updated);
                updateGlobalOrderSummary(manifest);
            }
        });
    });

    // Color Mode select
    container.querySelectorAll(".file-color-select").forEach(select => {
        select.addEventListener("change", () => {
            const idx = parseInt(select.dataset.idx, 10);
            const manifest = getStoredFileManifest();
            if (manifest[idx]) {
                manifest[idx].colorMode = select.value;
                const card = container.querySelector(`.file-config-card[data-idx="${idx}"]`);
                if (select.value === "color") {
                    manifest[idx].printSide = "single";
                    manifest[idx].duplex = "single";
                    if (card) {
                        const singleRadio = card.querySelector(`input[name="printSide_${idx}"][value="single"]`);
                        if (singleRadio) singleRadio.checked = true;
                        card.querySelectorAll(".side-pill").forEach(p => {
                            const r = p.querySelector("input[type='radio']");
                            p.classList.toggle("is-selected", r && r.value === "single");
                        });
                        const doublePill = card.querySelectorAll(".side-pill")[1];
                        if (doublePill) {
                            doublePill.classList.add("is-disabled");
                            const dRadio = doublePill.querySelector("input[type='radio']");
                            if (dRadio) dRadio.disabled = true;
                        }
                        const bindingContainer = card.querySelector(".file-binding-container");
                        if (bindingContainer) bindingContainer.style.display = "none";
                        const statusTag = card.querySelector(".side-status-tag");
                        if (statusTag) statusTag.textContent = "Color Print (₹6/pg) • Single Side";
                    }
                } else {
                    if (card) {
                        const doublePill = card.querySelectorAll(".side-pill")[1];
                        if (doublePill) {
                            doublePill.classList.remove("is-disabled");
                            const dRadio = doublePill.querySelector("input[type='radio']");
                            if (dRadio) dRadio.disabled = false;
                        }
                        const statusTag = card.querySelector(".side-status-tag");
                        if (statusTag) {
                            statusTag.textContent = (manifest[idx].printSide === "double") ? "Double Side Active (₹1/pg)" : "Single Side Active (₹2/pg)";
                        }
                    }
                }
                const updated = computeFileSheetsAndPrice(manifest[idx]);
                manifest[idx] = updated;
                saveFileManifest(manifest);
                if (card) updateCardSummaryStrip(card, updated);
                updateGlobalOrderSummary(manifest);
                if (idx === window.activePreviewFileIndex) updatePrintDetailsAndPreview();
            }
        });
    });

    // Orientation select
    container.querySelectorAll(".file-orientation-select").forEach(select => {
        select.addEventListener("change", () => {
            const idx = parseInt(select.dataset.idx, 10);
            const manifest = getStoredFileManifest();
            if (manifest[idx]) {
                manifest[idx].orientation = select.value;
                saveFileManifest(manifest);
                if (idx === window.activePreviewFileIndex) updatePrintDetailsAndPreview();
            }
        });
    });

    // Paper Size select
    container.querySelectorAll(".file-papersize-select").forEach(select => {
        select.addEventListener("change", () => {
            const idx = parseInt(select.dataset.idx, 10);
            const manifest = getStoredFileManifest();
            if (manifest[idx]) {
                manifest[idx].paperSize = select.value;
                saveFileManifest(manifest);
                if (idx === window.activePreviewFileIndex) updatePrintDetailsAndPreview();
            }
        });
    });

    // Scale / Fit select
    container.querySelectorAll(".file-scale-select").forEach(select => {
        select.addEventListener("change", () => {
            const idx = parseInt(select.dataset.idx, 10);
            const manifest = getStoredFileManifest();
            if (manifest[idx]) {
                manifest[idx].scaleMode = select.value;
                saveFileManifest(manifest);
                if (idx === window.activePreviewFileIndex) updatePrintDetailsAndPreview();
            }
        });
    });
}

// Global page initialization
const backBtn = document.getElementById("backBtn");
const paymentBtn = document.getElementById("paymentBtn");
const printDetailsFileName = document.getElementById("fileName");

if (printDetailsFileName || document.getElementById("fileConfigsContainer")) {
    const prevPageBtn = document.getElementById("prevPageBtn");
    const nextPageBtn = document.getElementById("nextPageBtn");

    if (prevPageBtn) {
        prevPageBtn.addEventListener("click", function(e) {
            if (e && e.preventDefault) e.preventDefault();
            const pagesToRender = getEffectivePreviewPages();
            if (!pagesToRender.length) return;

            const manifest = (window.currentFileManifest && window.currentFileManifest.length) ? window.currentFileManifest : getStoredFileManifest();
            const activeFile = manifest[window.activePreviewFileIndex || 0] || manifest[0];
            const isDouble = activeFile && activeFile.printSide === "double";

            if (isDouble) {
                const currentSpread = Math.floor(livePreviewIndex / 2);
                if (currentSpread > 0) {
                    livePreviewIndex = (currentSpread - 1) * 2;
                }
            } else {
                if (livePreviewIndex > 0) {
                    livePreviewIndex--;
                }
            }
            renderRealLivePreviewUI();
        });
    }

    if (nextPageBtn) {
        nextPageBtn.addEventListener("click", function(e) {
            if (e && e.preventDefault) e.preventDefault();
            const pagesToRender = getEffectivePreviewPages();
            if (!pagesToRender.length) return;

            const manifest = (window.currentFileManifest && window.currentFileManifest.length) ? window.currentFileManifest : getStoredFileManifest();
            const activeFile = manifest[window.activePreviewFileIndex || 0] || manifest[0];
            const isDouble = activeFile && activeFile.printSide === "double";

            if (isDouble) {
                const totalSpreads = Math.ceil(pagesToRender.length / 2) || 1;
                const currentSpread = Math.floor(livePreviewIndex / 2);
                if (currentSpread < totalSpreads - 1) {
                    livePreviewIndex = (currentSpread + 1) * 2;
                }
            } else {
                if (livePreviewIndex < pagesToRender.length - 1) {
                    livePreviewIndex++;
                }
            }
            renderRealLivePreviewUI();
        });
    }

    const notebookRightPage = document.getElementById("notebookRightPage");
    if (notebookRightPage) {
        notebookRightPage.addEventListener("click", function() {
            notebookRightPage.classList.toggle("unflipped");
            const flipBadge = document.getElementById("notebookFlipBadge");
            if (flipBadge) {
                flipBadge.textContent = notebookRightPage.classList.contains("unflipped")
                    ? "👀 Upright"
                    : "🔄 180° Flip";
            }
        });
    }

    prepareRealLivePreviewPages().then(() => {
        renderPerFileConfigCards();
    });
    fetchConnectedPrinters();
    renderPerFileConfigCards();
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
        const manifest = getStoredFileManifest();
        saveFileManifest(manifest);
        // Clear old checkout state
        localStorage.removeItem("lastOrderId");
        localStorage.removeItem("razorpayOrderId");
        localStorage.removeItem("currentCheckoutPaid");
        localStorage.setItem("newCheckoutPending", "true");
        window.location.href = "payment.html";
    });
}

// ==========================
// PAYMENT PAGE (payment.html) - RAZORPAY INTEGRATION
// ==========================

const paymentFileList = document.getElementById("paymentFileList");
const paymentTotalSheetsBadge = document.getElementById("paymentTotalSheetsBadge");
const paymentAmount = document.getElementById("paymentAmount");
const payBtn = document.getElementById("payBtn");
const paymentBackBtn = document.getElementById("paymentBackBtn");

if (paymentFileList && paymentAmount) {
    const manifest = getStoredFileManifest();
    paymentFileList.innerHTML = "";

    let totalSheetsAll = 0;
    let totalAmountAll = 0;

    manifest.forEach((file, idx) => {
        totalSheetsAll += file.calculatedSheets;
        totalAmountAll += file.calculatedPrice;

        const fileCard = document.createElement("div");
        fileCard.className = "payment-file-item";
        fileCard.style.cssText = "background: #ffffff; border: 1.5px solid #fed7aa; border-radius: 12px; padding: 12px; margin-bottom: 10px;";

        const isDuplex = (file.duplex !== "single");
        const sideDesc = isDuplex
            ? (file.duplexBinding === "short_edge" ? "Double Side • Short Edge (Flip 🗓️)" : "Double Side • Long Edge (Booklet 📖)")
            : "Single Side (1-sided)";
        const colorDesc = (file.colorMode === "color") ? "Color 🎨" : "Black & White (B&W)";
        const orientDesc = (file.orientation === "landscape") ? "Landscape" : "Portrait";
        const paperDesc = (file.paperSize || "a4").toUpperCase();

        // Sheet breakdown chips
        let sheetsHtml = "";
        if (isDuplex) {
            const numSheets = Math.ceil(file.selectedPagesCount / 2);
            for (let s = 1; s <= numSheets; s++) {
                const p1 = file.selectedPages[2 * s - 2];
                const p2 = file.selectedPages[2 * s - 1];
                if (p2 !== undefined) {
                    sheetsHtml += `<span style="background: #ffedd5; color: #7c2d12; font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 6px; border: 1px solid #fed7aa;">Sheet ${s}: P.${p1} ↔ P.${p2}</span>`;
                } else {
                    sheetsHtml += `<span style="background: #fef2f2; color: #b91c1c; font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 6px; border: 1px dashed #fca5a5;">Sheet ${s}: P.${p1} ↔ [BLANK]</span>`;
                }
            }
        } else {
            for (let s = 1; s <= file.selectedPagesCount; s++) {
                const p1 = file.selectedPages[s - 1];
                sheetsHtml += `<span style="background: #ffedd5; color: #7c2d12; font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 6px; border: 1px solid #fed7aa;">Sheet ${s}: P.${p1}</span>`;
            }
        }

        fileCard.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px dashed #fed7aa; padding-bottom: 6px; margin-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 6px; min-width: 0;">
                    <span style="background: #fed7aa; color: #7c2d12; font-size: 10px; font-weight: 800; padding: 1px 6px; border-radius: 4px;">#${idx + 1}</span>
                    <strong style="font-size: 13.5px; color: #1e293b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 220px;" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</strong>
                </div>
                <strong style="font-size: 14px; color: #ea580c; white-space: nowrap;">₹${file.calculatedPrice.toFixed(2)}</strong>
            </div>
            <div style="font-size: 11.5px; color: #475569; display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; font-weight: 600;">
                <span>📄 Pages: <strong>${file.selectedPagesCount} (${file.pageRange === 'all' ? 'All' : file.pageRange})</strong></span>
                <span>•</span>
                <span>📖 ${sideDesc}</span>
                <span>•</span>
                <span>🔢 ${file.copies} Cop${file.copies > 1 ? 'ies' : 'y'}</span>
                <span>•</span>
                <span>${colorDesc}</span>
                <span>•</span>
                <span>${orientDesc} • ${paperDesc}</span>
            </div>
            <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 5px; font-size: 11px;">
                <span style="font-weight: 800; color: #78350f;">Sheet Flow:</span>
                ${sheetsHtml}
            </div>
        `;
        paymentFileList.appendChild(fileCard);
    });

    if (paymentTotalSheetsBadge) {
        paymentTotalSheetsBadge.textContent = `${totalSheetsAll} Physical Sheet${totalSheetsAll > 1 ? 's' : ''}`;
    }

    if (paymentAmount) {
        paymentAmount.textContent = `₹${totalAmountAll.toFixed(2)}`;
    }

    // Fresh checkout guarantee
    localStorage.removeItem("newCheckoutPending");
    localStorage.removeItem("lastOrderId");
    localStorage.removeItem("razorpayOrderId");
    localStorage.removeItem("currentCheckoutPaid");

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

async function reconcilePaymentWithBackend(orderId, maxAttempts = 5, delayMs = 1500) {
    if (!orderId) return { paid: false };
    console.log(`[PAYMENT RECONCILE] Checking backend reconciliation for ${orderId} (max ${maxAttempts} attempts)...`);
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
            const res = await fetch(apiUrl(`/api/payment-status/${orderId}`, `/api/payment-status/${orderId}`));
            if (res.ok) {
                const data = await res.json();
                if (data && data.paid === true) {
                    console.log(`[PAYMENT RECONCILE] Payment confirmed captured on attempt ${attempt}:`, data);
                    return { paid: true, data };
                }
            }
        } catch (netErr) {
            console.warn(`[PAYMENT RECONCILE] Attempt ${attempt} network error:`, netErr);
        }
        if (attempt < maxAttempts) {
            await new Promise(r => setTimeout(r, delayMs));
        }
    }
    return { paid: false };
}

let isPaymentInFlight = false;
let paymentVerifiedSuccess = false;

if (payBtn) {
    payBtn.addEventListener("click", async function (e) {
        if (e && e.preventDefault) e.preventDefault();

        if (isPaymentInFlight) return;

        paymentVerifiedSuccess = false;

        // Double payment protection: check if CURRENT checkout was already paid
        const isCheckoutPaid = (localStorage.getItem("currentCheckoutPaid") === "true");
        const currentSavedOrderId = localStorage.getItem("lastOrderId");
        if (isCheckoutPaid && currentSavedOrderId && currentSavedOrderId.startsWith("PF-")) {
            try {
                const quickCheck = await fetch(apiUrl(`/api/orders/${currentSavedOrderId}/status`, `/api/orders/${currentSavedOrderId}/status`));
                if (quickCheck.ok) {
                    const qcData = await quickCheck.json();
                    if (qcData && ["PRINT_QUEUED", "PRINTING", "COMPLETED"].includes(qcData.order_status)) {
                        showPaymentSuccessModal("Payment Already Confirmed", "This order is already queued for printing. Redirecting...");
                        setTimeout(() => {
                            window.location.replace(`success.html?order_id=${encodeURIComponent(currentSavedOrderId)}`);
                        }, 400);
                        return;
                    }
                }
            } catch (e) {}
        }

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
            const manifest = getStoredFileManifest();
            let totalSelectedPages = 0;
            let totalAmountVal = 0;
            manifest.forEach(f => {
                totalSelectedPages += (f.selectedPagesCount * f.copies);
                totalAmountVal += f.calculatedPrice;
            });

            const uploadedPath = localStorage.getItem("backendFilePath") || (manifest.length > 0 ? manifest[0].path : "");
            const effectivePath = (manifest.length > 0 && manifest[0].path) ? manifest[0].path : uploadedPath;
            const effectiveName = manifest.map(f => f.name).join(", ") || "document.pdf";

            const rawMobile = localStorage.getItem("mobileNumber") || localStorage.getItem("customerMobile") || "9876543210";
            const cleanContact = rawMobile.replace(/\D/g, "").slice(-10) || "9876543210";

            // Preflight validation to prevent uncaught runtime errors
            if (!effectivePath && manifest.length === 0) {
                isPaymentInFlight = false;
                payBtn.disabled = false;
                payBtn.textContent = originalText;
                showPaymentFailedModal("No Document Found", "Please select and upload a document before proceeding to payment.");
                return;
            }

            if (isNaN(totalAmountVal) || totalAmountVal <= 0) {
                isPaymentInFlight = false;
                payBtn.disabled = false;
                payBtn.textContent = originalText;
                showPaymentFailedModal("Invalid Amount", "Unable to calculate payment amount. Please return to print settings and try again.");
                return;
            }

            const payloadFiles = manifest.map((f, idx) => ({
                id: f.id,
                name: f.name,
                path: f.path,
                pages: f.pages,
                sequence: idx,
                selected_pages_count: f.selectedPagesCount,
                page_range: f.pageRange,
                copies: f.copies,
                color_mode: f.colorMode,
                duplex: f.duplex,
                binding: f.duplexBinding,
                orientation: f.orientation,
                paper_size: f.paperSize,
                scale_mode: f.scaleMode,
                print_mode: f.printMode || "standard",
                pages_per_sheet: f.pagesPerSheet || 1,
                calculated_sheets: f.calculatedSheets,
                calculated_price: f.calculatedPrice
            }));

            const primaryFile = manifest[0] || {};
            const payload = {
                amount: totalAmountVal,
                pages: totalSelectedPages,
                page_range: "per_file",
                copies: primaryFile.copies || 1,
                color_mode: manifest.some(f => f.colorMode === "color") ? "color" : "black_white",
                duplex: manifest.some(f => f.duplex !== "single") ? "duplex_long" : "single",
                binding: primaryFile.duplexBinding || "long_edge",
                paper_size: primaryFile.paperSize || "a4",
                orientation: primaryFile.orientation || "portrait",
                scale_mode: primaryFile.scaleMode || "fit",
                margins: "normal",
                print_mode: primaryFile.printMode || "standard",
                pages_per_sheet: primaryFile.pagesPerSheet || 1,
                page_order: "horizontal",
                file_name: effectiveName,
                file_path: effectivePath,
                files: payloadFiles,
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
            if (orderData && orderData.status === "already_paid") {
                const pfId = orderData.pf_order_id || orderData.print_order_id || currentSavedOrderId;
                localStorage.setItem("lastOrderId", pfId);
                showPaymentSuccessModal("Payment Confirmed", "Your print order is already confirmed and in queue.");
                setTimeout(() => {
                    window.location.replace(`success.html?order_id=${encodeURIComponent(pfId)}`);
                }, 400);
                return;
            }
            if (!orderData || orderData.status === "error" || !orderData.order_id) {
                throw new Error(orderData?.detail || "Invalid Razorpay order payload");
            }

            const activePfOrderId = orderData.pf_order_id || orderData.print_order_id || "";
            if (activePfOrderId) {
                localStorage.setItem("lastOrderId", activePfOrderId);
            } else if (orderData.order_id) {
                localStorage.setItem("lastOrderId", orderData.order_id);
            }
            if (orderData.order_id) {
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
                    paymentVerifiedSuccess = true;
                    isPaymentInFlight = true;
                    if (payBtn) {
                        payBtn.disabled = true;
                        payBtn.textContent = "Payment Received. Verifying...";
                    }
                    showPaymentSuccessModal("Verifying Payment...", "Money received. Confirming your print order with the printer queue...");

                    const canonicalOrderId = activePfOrderId || orderData.order_id;
                    const fullVerificationPayload = {
                        print_order_id: canonicalOrderId,
                        razorpay_payment_id: response.razorpay_payment_id,
                        razorpay_order_id: response.razorpay_order_id || orderData.order_id,
                        razorpay_signature: response.razorpay_signature
                    };

                    let verified = false;
                    let nextOrderId = canonicalOrderId;

                    for (let attempt = 1; attempt <= 3; attempt++) {
                        try {
                            const verifyRes = await fetch(apiUrl("/api/verify-payment", "/api/verify-payment"), {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify(fullVerificationPayload)
                            });
                            const verifyData = await verifyRes.json().catch(() => ({}));
                            if (verifyRes.ok && verifyData.status === "success" && (verifyData.order_status === "PRINT_QUEUED" || verifyData.order_status === "PRINTING" || verifyData.order_status === "COMPLETED")) {
                                verified = true;
                                nextOrderId = verifyData.order_id || verifyData.print_order_id || canonicalOrderId;
                                break;
                            }
                        } catch (netErr) {
                            console.warn(`[VERIFICATION RETRY] Attempt ${attempt} failed:`, netErr);
                            if (attempt < 3) await new Promise(r => setTimeout(r, 1000));
                        }
                    }

                    if (!verified) {
                        try {
                            const checkRes = await fetch(apiUrl(`/api/orders/${canonicalOrderId}/status`, `/api/orders/${canonicalOrderId}/status`));
                            const checkData = await checkRes.json().catch(() => ({}));
                            if (checkRes.ok && checkData.status === "success" && ["PRINT_QUEUED", "PRINTING", "COMPLETED"].includes(checkData.order_status)) {
                                verified = true;
                                nextOrderId = checkData.order_id || canonicalOrderId;
                            }
                        } catch (e) {}
                    }

                    // Fallback to server-to-server Razorpay reconciliation if signature verification is inconclusive/times out
                    if (!verified) {
                        console.log("[PAYMENT RECONCILE] Fallback to backend reconciliation for:", canonicalOrderId);
                        showPaymentSuccessModal("Payment Received", "Confirming payment with payment gateway. Please wait...");
                        const reconResult = await reconcilePaymentWithBackend(canonicalOrderId, 5, 1500);
                        if (reconResult && reconResult.paid === true) {
                            verified = true;
                            nextOrderId = reconResult.data?.order_id || canonicalOrderId;
                        }
                    }

                    if (verified) {
                        paymentVerifiedSuccess = true;
                        localStorage.setItem("currentCheckoutPaid", "true");
                        localStorage.setItem("lastOrderId", nextOrderId);
                        showPaymentSuccessModal("Payment Successful!", "✓ Payment verified. Your document is queued for printing.");
                        setTimeout(() => {
                            window.location.replace("success.html" + (nextOrderId ? `?order_id=${encodeURIComponent(nextOrderId)}` : ""));
                        }, 500);
                    } else {
                        paymentVerifiedSuccess = false;
                        isPaymentInFlight = false;
                        if (payBtn) {
                            payBtn.disabled = false;
                            payBtn.textContent = originalText;
                        }
                        showPaymentFailedModal("Verification Error", "Payment verification could not be confirmed. If your account was debited, please contact support.");
                    }
                },
                "theme": {
                    "color": "#ea580c"
                },
                "modal": {
                    "escape": true,
                    "backdropclose": false,
                    "ondismiss": async function() {
                        if (paymentVerifiedSuccess) return;

                        const canonicalOrderId = activePfOrderId || orderData.order_id;
                        console.log(`[PAYMENT DISMISS] Modal dismissed/switched apps for ${canonicalOrderId}. Checking reconciliation...`);

                        // Give external UPI app (PhonePe, GPay, Paytm, BHIM) time to complete & reconcile with backend
                        showPaymentSuccessModal("Payment Received – Confirming...", "Checking payment confirmation with your payment app. Please wait...");
                        if (payBtn) {
                            payBtn.disabled = true;
                            payBtn.textContent = "Confirming payment...";
                        }

                        const reconResult = await reconcilePaymentWithBackend(canonicalOrderId, 5, 1200);
                        if (reconResult && reconResult.paid === true) {
                            paymentVerifiedSuccess = true;
                            const nextOrderId = reconResult.data?.order_id || canonicalOrderId;
                            localStorage.setItem("currentCheckoutPaid", "true");
                            localStorage.setItem("lastOrderId", nextOrderId);
                            showPaymentSuccessModal("Payment Successful!", "✓ Payment verified. Your document is queued for printing.");
                            setTimeout(() => {
                                window.location.replace("success.html" + (nextOrderId ? `?order_id=${encodeURIComponent(nextOrderId)}` : ""));
                            }, 500);
                        } else {
                            // Confirmed not paid / user cancelled checkout modal
                            const successOverlay = document.getElementById("successModalOverlay");
                            if (successOverlay) successOverlay.classList.remove("is-open");
                            isPaymentInFlight = false;
                            if (payBtn) {
                                payBtn.disabled = false;
                                payBtn.textContent = originalText;
                            }
                        }
                    }
                }
            };

            const rzp = new Razorpay(options);
            rzp.on("payment.failed", async function (response) {
                if (paymentVerifiedSuccess) return;
                const canonicalOrderId = activePfOrderId || orderData.order_id;

                // Before declaring failure, verify with backend reconciliation to avoid false negative
                const reconResult = await reconcilePaymentWithBackend(canonicalOrderId, 2, 800);
                if (reconResult && reconResult.paid === true) {
                    paymentVerifiedSuccess = true;
                    const nextOrderId = reconResult.data?.order_id || canonicalOrderId;
                    localStorage.setItem("currentCheckoutPaid", "true");
                    localStorage.setItem("lastOrderId", nextOrderId);
                    showPaymentSuccessModal("Payment Successful!", "✓ Payment verified. Your document is queued for printing.");
                    setTimeout(() => {
                        window.location.replace("success.html" + (nextOrderId ? `?order_id=${encodeURIComponent(nextOrderId)}` : ""));
                    }, 500);
                    return;
                }

                const errorDesc = response?.error?.description || "Payment failed or cancelled.";
                showPaymentFailedModal("Payment Failed", errorDesc);
                isPaymentInFlight = false;
                if (payBtn) {
                    payBtn.disabled = false;
                    payBtn.textContent = originalText;
                }
            });

            const tOpen = performance.now();
            console.log(`[PAYMENT PERF] Razorpay checkout.open() invoked at ${(tOpen - tClick).toFixed(1)}ms total`);

            rzp.open();

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

        let sideText = "Single Side";
        if (order.color_mode !== "color" && order.color_mode !== "colour") {
            if (order.duplex === "duplex_short" || order.binding === "short_edge") {
                sideText = "Double (Short Edge)";
            } else if (order.duplex === "duplex_long" || order.duplex === "double" || order.binding === "long_edge") {
                sideText = "Double (Long Edge)";
            }
        }

        html += `
            <tr>
                <td><strong>${order.order_id}</strong><br><small style="color: #64748b;">${order.timestamp || ''}</small></td>
                <td>${order.customer_mobile || 'Guest'}</td>
                <td><strong class="admin-file-name" title="${order.file_name}">${order.file_name}</strong><br><small style="color: #ea580c;">${order.pages || 1} Pages</small></td>
                <td>${order.copies || 1} Copies (${sideText})</td>
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
    try {
        const res = await fetch(apiUrl("/api/agent/status", "/api/agent/status"));
        const data = await res.json();
        if (data && data.status === "success") {
            const isOnline = data.agent_online;
            window.discoveredPrinters = data.discovered_printers || [];
            window.agentConfig = data.config || {};

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

            if (typeof renderPrintSettings === "function") {
                renderPrintSettings();
            }
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
        "amount", "printSide", "duplex", "duplexBinding", "binding", "colorMode", "orientation", "paperSize",
        "scaleMode", "margins", "printMode", "pagesPerSheet", "pageOrder",
        "pdfDataUrl", "selectedPdfFile", "lastOrderId", "razorpayOrderId",
        "currentCheckoutPaid", "newCheckoutPending"
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

// ======================================================
// THERMAL RECEIPT PRINTER SYNTHESIZED AUDIO ENGINE (Web Audio API)
// ======================================================

class ThermalPrinterAudio {
    constructor() {
        this.ctx = null;
        this.activeNodes = null;
        this.isPlaying = false;
        this.pendingStart = false;
    }

    init() {
        if (!this.ctx) {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (AudioCtx) {
                this.ctx = new AudioCtx();
            }
        }
        if (this.ctx && this.ctx.state === "suspended") {
            this.ctx.resume().catch(() => {});
        }
    }

    start() {
        try {
            this.init();
            if (!this.ctx) return;
            if (this.isPlaying) this.stop();

            if (this.ctx.state === "suspended") {
                this.pendingStart = true;
                this.ctx.resume().then(() => {
                    if (this.pendingStart) {
                        this.pendingStart = false;
                        this.start();
                    }
                }).catch(() => {});
                return;
            }

            const t = this.ctx.currentTime;
            this.isPlaying = true;
            this.pendingStart = false;

            // Master Gain node with clear, audibly rich mechanical volume (0.85)
            const masterGain = this.ctx.createGain();
            masterGain.gain.setValueAtTime(0.0001, t);
            masterGain.gain.exponentialRampToValueAtTime(0.85, t + 0.05);
            masterGain.connect(this.ctx.destination);

            // 1. Mechanical Stepper Motor Core (Sawtooth oscillator)
            const osc = this.ctx.createOscillator();
            osc.type = "sawtooth";
            osc.frequency.setValueAtTime(145, t);

            // Stepper motor pulse vibrato (LFO) simulating rapid mechanical gear indexing
            const lfo = this.ctx.createOscillator();
            lfo.type = "square";
            lfo.frequency.setValueAtTime(38, t); // 38 steps / pulses per second
            const lfoGain = this.ctx.createGain();
            lfoGain.gain.setValueAtTime(35, t);
            lfo.connect(lfoGain);
            lfoGain.connect(osc.frequency);

            // Motor tone shaping filter (warm mechanical lowpass)
            const motorFilter = this.ctx.createBiquadFilter();
            motorFilter.type = "lowpass";
            motorFilter.frequency.setValueAtTime(520, t);
            osc.connect(motorFilter);

            const motorGain = this.ctx.createGain();
            motorGain.gain.setValueAtTime(0.45, t);
            motorFilter.connect(motorGain);
            motorGain.connect(masterGain);

            // 2. Paper Feed Roller Friction (White noise with bandpass filter)
            const bufferSize = this.ctx.sampleRate * 2;
            const noiseBuffer = this.ctx.createBuffer(1, bufferSize, this.ctx.sampleRate);
            const output = noiseBuffer.getChannelData(0);
            for (let i = 0; i < bufferSize; i++) {
                output[i] = Math.random() * 2 - 1;
            }

            const whiteNoise = this.ctx.createBufferSource();
            whiteNoise.buffer = noiseBuffer;
            whiteNoise.loop = true;

            const noiseFilter = this.ctx.createBiquadFilter();
            noiseFilter.type = "bandpass";
            noiseFilter.frequency.setValueAtTime(1900, t);
            noiseFilter.Q.setValueAtTime(1.8, t);

            const noiseGain = this.ctx.createGain();
            noiseGain.gain.setValueAtTime(0.35, t);

            whiteNoise.connect(noiseFilter);
            noiseFilter.connect(noiseGain);
            noiseGain.connect(masterGain);

            // Start audio sources
            osc.start(t);
            lfo.start(t);
            whiteNoise.start(t);

            this.activeNodes = { masterGain, osc, lfo, whiteNoise };
        } catch (e) {
            console.warn("[ThermalPrinterAudio] Audio start note:", e);
        }
    }

    stop() {
        this.pendingStart = false;
        if (!this.isPlaying || !this.ctx || !this.activeNodes) return;
        try {
            const t = this.ctx.currentTime;
            const { masterGain, osc, lfo, whiteNoise } = this.activeNodes;
            masterGain.gain.setValueAtTime(masterGain.gain.value, t);
            masterGain.gain.exponentialRampToValueAtTime(0.0001, t + 0.04);

            setTimeout(() => {
                try {
                    osc.stop();
                    lfo.stop();
                    whiteNoise.stop();
                    osc.disconnect();
                    lfo.disconnect();
                    whiteNoise.disconnect();
                    masterGain.disconnect();
                } catch (err) {}
                this.isPlaying = false;
                this.activeNodes = null;
            }, 50);
        } catch (e) {
            this.isPlaying = false;
        }
    }
}

const thermalAudio = new ThermalPrinterAudio();
const unlockThermalAudio = () => {
    thermalAudio.init();
    if (thermalAudio.ctx && thermalAudio.ctx.state === "suspended") {
        thermalAudio.ctx.resume().catch(() => {});
    }
    if (thermalAudio.pendingStart) {
        thermalAudio.pendingStart = false;
        thermalAudio.start();
    }
};
["click", "pointerdown", "mousedown", "touchstart", "keydown", "mousemove"].forEach(evt => {
    window.addEventListener(evt, unlockThermalAudio, { passive: true });
});

function initSuccessReceiptPage() {
    thermalAudio.init();
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
    const queueCard = document.getElementById("queueCard");
    const queuePosBadge = document.getElementById("queuePosBadge");
    const queueAheadText = document.getElementById("queueAheadText");
    const queueWaitText = document.getElementById("queueWaitText");

    if (!printer && !rcptPaper && !rcptOrderId && !receiptOrder) return;

    const params = new URLSearchParams(window.location.search);
    const orderId = params.get("order_id") || localStorage.getItem("lastOrderId") || localStorage.getItem("razorpayOrderId") || `PF-${Math.floor(100000 + Math.random() * 900000)}`;
    const fileName = localStorage.getItem("fileName") || "document.pdf";
    const pages = localStorage.getItem("selectedPagesCount") || localStorage.getItem("pdfPageCount") || "1";
    const pageRange = localStorage.getItem("pageRange") || "all";
    const displayPages = (pageRange && pageRange !== "all") ? `${pages} (${pageRange})` : pages;
    const copies = localStorage.getItem("copies") || "1";
    const isMicro = localStorage.getItem("printMode") === "micro_xerox" && parseInt(localStorage.getItem("pagesPerSheet") || "1", 10) > 1;
    const printMode = isMicro ? "Micro Xerox" : "Standard";

    const rawColor = localStorage.getItem("colorMode") || "";
    const isColor = rawColor === "color" || rawColor === "colour";
    const colorMode = isColor ? "Color Print 🎨" : "Black & White";

    let sides = "Single Side";
    if (!isColor) {
        const storedSide = (localStorage.getItem("printSide") || "").toLowerCase();
        const storedDuplex = (localStorage.getItem("duplex") || "").toLowerCase();
        const storedBinding = (localStorage.getItem("duplexBinding") || localStorage.getItem("binding") || "").toLowerCase();
        if (storedSide === "double" || storedDuplex.startsWith("duplex")) {
            if (storedBinding === "short_edge" || storedDuplex === "duplex_short") {
                sides = "Double Side (Short Edge)";
            } else {
                sides = "Double Side (Long Edge)";
            }
        }
    }

    const paperSize = (localStorage.getItem("paperSize") || "A4").toUpperCase();
    const orientation = ((localStorage.getItem("orientation") || "portrait").toLowerCase() === "landscape") ? "Landscape" : "Portrait";
    const amount = localStorage.getItem("amount") || "2.00";

    if (rcptOrderId) rcptOrderId.textContent = orderId;
    if (receiptOrder) receiptOrder.textContent = orderId;
    if (rcptFileName) rcptFileName.textContent = fileName;
    if (rcptPages) rcptPages.textContent = displayPages;
    if (receiptPages) receiptPages.textContent = displayPages;
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
                const jobsAhead = typeof data.jobs_ahead === "number" ? data.jobs_ahead : 0;
                const queuePosition = data.queue_position || 1;
                const estimatedWait = data.estimated_wait || "";

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

                    if (jobsAhead > 0) {
                        // There ARE other jobs ahead -> Show Queue Position, Orders Ahead, and Estimated Wait
                        if (queueCard) {
                            queueCard.style.display = "block";
                            if (queuePosBadge) queuePosBadge.textContent = `Queue Position: #${queuePosition}`;
                            if (queueAheadText) queueAheadText.textContent = `${jobsAhead} order${jobsAhead > 1 ? "s" : ""} ahead`;
                            if (queueWaitText) queueWaitText.textContent = `Estimated Wait: ${estimatedWait || "~1 min"}`;
                        }
                        if (statusHeadline) statusHeadline.textContent = "Your print is in queue";
                        if (statusSubtext) statusSubtext.textContent = `There ${jobsAhead === 1 ? "is 1 order" : `are ${jobsAhead} orders`} ahead of yours. Your document will print automatically.`;
                    } else {
                        // NO other pending/printing jobs ahead:
                        // DO NOT SHOW: Queue Position, Orders Ahead, Waiting Time
                        // Instead show directly: "Your print is starting..."
                        if (queueCard) queueCard.style.display = "none";
                        if (statusHeadline) statusHeadline.textContent = "Your print is starting...";
                        if (statusSubtext) statusSubtext.textContent = "Connecting to physical printer...";
                    }
                } else if (orderState === "PRINTING") {
                    // Automatically remove queue/waiting information and transition to: "Printing..."
                    if (queueCard) queueCard.style.display = "none";
                    if (ledDot) {
                        ledDot.className = "led-dot";
                        ledDot.style.background = "#ea580c";
                        ledDot.style.boxShadow = "0 0 8px #ea580c";
                    }
                    if (statusHeadline) statusHeadline.textContent = "Printing...";
                    if (statusSubtext) statusSubtext.textContent = "The physical printer is actively printing your document.";
                } else if (orderState === "COMPLETED" || orderState === "PRINTED") {
                    if (queueCard) queueCard.style.display = "none";
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
                        if (statusHeadline) statusHeadline.textContent = "✓ Print Completed";
                        if (statusSubtext) statusSubtext.textContent = "Dispensing physical print receipt...";

                        // 2. Small delay before receipt begins emerging from the printer slot (500ms)
                        setTimeout(() => {
                            // Start synchronized mechanical motor and roller feed sound
                            thermalAudio.start();

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
                                // Stop sound immediately when paper reaches final position
                                thermalAudio.stop();

                                // 5. Short pause (600ms) after receipt reaches final position
                                setTimeout(() => {
                                    // 6. "✓ Print Completed" success section appears
                                    if (statusHeadline) statusHeadline.textContent = "✓ Print Completed";
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
                    thermalAudio.stop();
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
