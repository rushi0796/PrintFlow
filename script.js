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
        for (let fi = 0; fi < fileEntries.length; fi++) {
            const entry = fileEntries[fi];
            const file = entry.file;
            const fileName = entry.meta?.name || file.name || `Document_${fi + 1}`;
            const ext = (fileName || "").split('.').pop().toLowerCase();
            const isImage = file.type.startsWith("image/") || ["jpg", "jpeg", "png", "webp", "bmp"].includes(ext);
            const isPdf = (file.type === "application/pdf") || ext === "pdf";

            if (isImage) {
                const imgUrl = URL.createObjectURL(file);
                livePreviewPages.push({
                    type: "image",
                    title: fileName,
                    src: imgUrl,
                    docPageNum: fi + 1
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
                            title: `${fileName} (P.${p})`,
                            src: canvas.toDataURL("image/png"),
                            width: vp.width,
                            height: vp.height,
                            docPageNum: p
                        });
                    }
                } catch (pdfErr) {
                    console.warn("PDF render warning:", pdfErr);
                }
            } else {
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
                ctx.fillText(`Format: ${ext.toUpperCase()}`, 20, 68);
                ctx.fillStyle = "#cbd5e1";
                for (let y = 95; y < 500; y += 18) {
                    ctx.fillRect(20, y, Math.random() * 120 + 220, 6);
                }
                livePreviewPages.push({
                    type: "canvas",
                    title: fileName,
                    src: canvas.toDataURL("image/png"),
                    docPageNum: fi + 1
                });
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
    const pageSelEl = document.querySelector('input[name="pageSelection"]:checked');
    const pageSelection = pageSelEl ? pageSelEl.value : "all";
    const customInputEl = document.getElementById("customPagesInput");
    const customStr = customInputEl ? customInputEl.value.trim() : "";
    const totalPages = livePreviewPages.length;

    const validation = parseAndValidatePageSelection(pageSelection, customStr, totalPages);
    if (!validation.isValid || !validation.pages.length) {
        return livePreviewPages;
    }
    const pageSet = new Set(validation.pages);
    return livePreviewPages.filter(p => pageSet.has(p.docPageNum || 1));
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

    const printModeEl = document.querySelector('input[name="printMode"]:checked');
    const printMode = printModeEl ? printModeEl.value : "standard";
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
            const orientationEl = document.querySelector('input[name="orientation"]:checked');
            const orientation = orientationEl ? orientationEl.value : "portrait";

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
            const currentSheet = Math.floor(livePreviewIndex / pagesPerSheet);
            const startIdx = currentSheet * pagesPerSheet;

            let cellsHtml = "";
            for (let r = 0; r < rows; r++) {
                for (let c = 0; c < cols; c++) {
                    const slotIdx = (pageOrder === "vertical") ? (c * rows + r) : (r * cols + c);
                    const pageIdx = startIdx + slotIdx;
                    // CRITICAL FIX: If pageIdx exceeds document pages, MUST BE COMPLETELY BLANK.
                    // NEVER fallback to livePreviewPages[0] or duplicate Page 1.
                    const targetPage = (pageIdx < pagesToRender.length) ? pagesToRender[pageIdx] : null;

                    if (targetPage && targetPage.src) {
                        cellsHtml += `<div class="nup-cell"><img src="${targetPage.src}" class="nup-cell-element" alt="${escapeHtml(targetPage.title)}"></div>`;
                    } else {
                        cellsHtml += `<div class="nup-cell nup-blank-slot"></div>`;
                    }
                }
            }
            nupGrid.innerHTML = cellsHtml;

            if (pageIndicator) {
                pageIndicator.textContent = `Sheet ${currentSheet + 1} of ${totalSheets}`;
            }
            if (navBar) {
                navBar.style.display = totalSheets > 1 ? "flex" : "none";
            }
            if (prevBtn) prevBtn.disabled = (currentSheet <= 0);
            if (nextBtn) nextBtn.disabled = (currentSheet >= totalSheets - 1);
        }
    } else {
        const printSideEl = document.querySelector('input[name="printSide"]:checked');
        const printSide = printSideEl ? printSideEl.value : "single";
        const bindingEl = document.querySelector('input[name="duplexBinding"]:checked');
        const duplexBinding = bindingEl ? bindingEl.value : "long_edge";

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

function updatePrintDetailsAndPreview() {
    const copiesBox = document.getElementById("copies");
    const totalPriceBox = document.getElementById("totalPrice");
    const paperSheetPreview = document.getElementById("paperSheetPreview");
    const microXeroxSection = document.getElementById("microXeroxSection");
    const previewLabelBadge = document.getElementById("previewLabelBadge");
    const doubleSideLabel = document.getElementById("doubleSideLabel");
    const radioDoubleSide = document.getElementById("radioDoubleSide");
    const paymentBtnEl = document.getElementById("paymentBtn");

    if (!totalPriceBox && !paperSheetPreview) return;

    const totalDocPages = Number(localStorage.getItem("pdfPageCount")) || (livePreviewPages.length ? livePreviewPages.length : 1);
    const copies = copiesBox ? (Number(copiesBox.value) || 1) : 1;

    // Pages Selection Handling
    const pageSelEl = document.querySelector('input[name="pageSelection"]:checked');
    const pageSelection = pageSelEl ? pageSelEl.value : "all";
    const customInputEl = document.getElementById("customPagesInput");
    const customPagesVal = customInputEl ? customInputEl.value.trim() : "";
    const customContainer = document.getElementById("customPagesContainer");
    const customErrorEl = document.getElementById("customPagesError");

    if (customContainer) {
        customContainer.style.display = (pageSelection === "custom") ? "block" : "none";
    }

    const validation = parseAndValidatePageSelection(pageSelection, customPagesVal, totalDocPages);
    if (customErrorEl) {
        if (!validation.isValid && pageSelection === "custom") {
            customErrorEl.textContent = validation.error;
            customErrorEl.style.display = "block";
        } else {
            customErrorEl.textContent = "";
            customErrorEl.style.display = "none";
        }
    }

    if (paymentBtnEl) {
        paymentBtnEl.disabled = (!validation.isValid && pageSelection === "custom");
    }

    const effectivePagesCount = validation.isValid ? validation.pages.length : totalDocPages;
    const pageCountEl = document.getElementById("pageCount");
    if (pageCountEl) {
        if (pageSelection !== "all" && validation.isValid) {
            pageCountEl.textContent = `Total: ${totalDocPages} Pages | ${effectivePagesCount} Selected`;
        } else {
            pageCountEl.textContent = `Total: ${totalDocPages} Page${totalDocPages > 1 ? 's' : ''}`;
        }
    }

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

    const bindingSection = document.getElementById("bindingSection");
    const bindingLongRadio = document.getElementById("bindingLong");
    const bindingShortRadio = document.getElementById("bindingShort");
    const bindingEl = document.querySelector('input[name="duplexBinding"]:checked');
    let duplexBinding = bindingEl ? bindingEl.value : "long_edge";

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
        if (bindingSection) bindingSection.style.display = "none";
        duplexBinding = "";
    } else {
        if (doubleSideLabel) doubleSideLabel.style.opacity = "1";
        if (radioDoubleSide) radioDoubleSide.disabled = false;
        if (printSide === "double") {
            if (bindingSection) bindingSection.style.display = "block";
            if (!duplexBinding) {
                duplexBinding = "long_edge";
                if (bindingLongRadio) bindingLongRadio.checked = true;
            }
        } else {
            if (bindingSection) bindingSection.style.display = "none";
            duplexBinding = "";
        }
    }

    let canonicalDuplex = "single";
    if (colorMode !== "color" && printSide === "double") {
        canonicalDuplex = (duplexBinding === "short_edge") ? "duplex_short" : "duplex_long";
    }

    if (microXeroxSection) {
        microXeroxSection.style.display = printMode === "micro_xerox" ? "block" : "none";
    }

    const notebookSpreadPreview = document.getElementById("notebookSpreadPreview");
    const rightPageEl = document.getElementById("notebookRightPage");
    if (rightPageEl) rightPageEl.classList.remove("unflipped");

    if (paperSheetPreview && notebookSpreadPreview) {
        const colorClass = (colorMode === "color") ? "color-mode" : "bw-mode";
        const edgeClass = (duplexBinding === "short_edge") ? "short-edge" : "long-edge";

        if (printMode === "micro_xerox") {
            notebookSpreadPreview.style.display = "none";
            paperSheetPreview.style.display = "flex";
            paperSheetPreview.className = `paper-sheet size-${paperSize} ${orientation} ${scaleMode} ${colorClass}`;
        } else if (printSide === "double") {
            paperSheetPreview.style.display = "none";
            notebookSpreadPreview.style.display = "flex";
            notebookSpreadPreview.className = `notebook-spread-container size-${paperSize} ${orientation} ${scaleMode} ${colorClass} ${edgeClass}`;
        } else {
            notebookSpreadPreview.style.display = "none";
            paperSheetPreview.style.display = "flex";
            paperSheetPreview.className = `paper-sheet size-${paperSize} ${orientation} ${scaleMode} ${colorClass}`;
        }
    } else if (paperSheetPreview) {
        const colorClass = (colorMode === "color") ? "color-mode" : "bw-mode";
        paperSheetPreview.className = `paper-sheet size-${paperSize} ${orientation} ${scaleMode} ${colorClass}`;
    }

    if (previewLabelBadge) {
        if (printMode === "micro_xerox") {
            previewLabelBadge.textContent = `Micro Xerox ${pagesPerSheet}-Up`;
        } else if (printSide === "double") {
            previewLabelBadge.textContent = (duplexBinding === "short_edge")
                ? "Double Side • Short Edge (Flip 🗓️)"
                : "Double Side • Long Edge (Booklet 📖)";
        } else {
            previewLabelBadge.textContent = (scaleMode === "actual") ? "Standard (Actual Size)" : "Standard (Full Page)";
        }
    }

    renderRealLivePreviewUI();

    const totalAmount = calculatePrice(effectivePagesCount, copies, colorMode, printSide, printMode, pagesPerSheet);
    if (totalPriceBox) {
        totalPriceBox.textContent = "Total: ₹" + totalAmount;
    }

    localStorage.setItem("copies", String(copies));
    localStorage.setItem("amount", String(totalAmount));
    localStorage.setItem("printMode", printMode);
    localStorage.setItem("colorMode", colorMode);
    localStorage.setItem("printSide", printSide);
    localStorage.setItem("duplex", canonicalDuplex);
    localStorage.setItem("duplexBinding", duplexBinding);
    localStorage.setItem("binding", duplexBinding);
    localStorage.setItem("orientation", orientation);
    localStorage.setItem("paperSize", paperSize);
    localStorage.setItem("pagesPerSheet", String(pagesPerSheet));
    localStorage.setItem("pageOrder", pageOrder);
    localStorage.setItem("scaleMode", scaleMode);
    localStorage.setItem("pageSelection", pageSelection);
    localStorage.setItem("customPagesInput", customPagesVal);
    localStorage.setItem("pageRange", validation.isValid ? validation.canonicalString : "all");
    localStorage.setItem("selectedPagesCount", String(effectivePagesCount));
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

    const prevPageBtn = document.getElementById("prevPageBtn");
    const nextPageBtn = document.getElementById("nextPageBtn");

    if (prevPageBtn) {
        prevPageBtn.addEventListener("click", function() {
            const printModeEl = document.querySelector('input[name="printMode"]:checked');
            const printMode = printModeEl ? printModeEl.value : "standard";
            const printSideEl = document.querySelector('input[name="printSide"]:checked');
            const printSide = printSideEl ? printSideEl.value : "single";
            const pagesPerSheetEl = document.getElementById("pagesPerSheet");
            let step = 1;
            if (printMode === "micro_xerox" && pagesPerSheetEl) {
                step = parseInt(pagesPerSheetEl.value, 10);
            } else if (printSide === "double") {
                step = 2;
            }
            livePreviewIndex = Math.max(0, livePreviewIndex - step);
            renderRealLivePreviewUI();
        });
    }

    if (nextPageBtn) {
        nextPageBtn.addEventListener("click", function() {
            const printModeEl = document.querySelector('input[name="printMode"]:checked');
            const printMode = printModeEl ? printModeEl.value : "standard";
            const printSideEl = document.querySelector('input[name="printSide"]:checked');
            const printSide = printSideEl ? printSideEl.value : "single";
            const pagesPerSheetEl = document.getElementById("pagesPerSheet");
            let step = 1;
            if (printMode === "micro_xerox" && pagesPerSheetEl) {
                step = parseInt(pagesPerSheetEl.value, 10);
            } else if (printSide === "double") {
                step = 2;
            }
            const pagesToRender = getEffectivePreviewPages();
            if (livePreviewIndex + step < pagesToRender.length) {
                livePreviewIndex += step;
            }
            renderRealLivePreviewUI();
        });
    }

    const notebookRightPage = document.getElementById("notebookRightPage");
    if (notebookRightPage) {
        notebookRightPage.addEventListener("click", function() {
            const bindingEl = document.querySelector('input[name="duplexBinding"]:checked');
            const duplexBinding = bindingEl ? bindingEl.value : "long_edge";
            if (duplexBinding === "short_edge") {
                notebookRightPage.classList.toggle("unflipped");
                const flipBadge = document.getElementById("notebookFlipBadge");
                if (flipBadge) {
                    flipBadge.textContent = notebookRightPage.classList.contains("unflipped")
                        ? "👀 Upright"
                        : "🔄 180° Flip";
                }
            }
        });
    }

    prepareRealLivePreviewPages();

    const settingsForm = document.getElementById("printDetailsForm");
    if (settingsForm) {
        const savedPageSel = localStorage.getItem("pageSelection");
        if (savedPageSel) {
            const selRadio = document.querySelector(`input[name="pageSelection"][value="${savedPageSel}"]`);
            if (selRadio) selRadio.checked = true;
        }
        const savedCustomPages = localStorage.getItem("customPagesInput");
        const customInputEl = document.getElementById("customPagesInput");
        if (savedCustomPages && customInputEl) {
            customInputEl.value = savedCustomPages;
        }
        if (customInputEl) {
            customInputEl.addEventListener("input", updatePrintDetailsAndPreview);
        }

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

        const savedBinding = localStorage.getItem("duplexBinding") || localStorage.getItem("binding");
        if (savedBinding) {
            const bindRadio = document.querySelector(`input[name="duplexBinding"][value="${savedBinding}"]`);
            if (bindRadio) bindRadio.checked = true;
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
const paymentPages = document.getElementById("paymentPages");
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
    const duplexBindingVal = localStorage.getItem("duplexBinding") || localStorage.getItem("binding") || "long_edge";
    const duplexVal = localStorage.getItem("duplex") || "single";
    const orientationVal = localStorage.getItem("orientation") || "portrait";
    const pageRangeVal = localStorage.getItem("pageRange") || "all";
    const pageSelectionVal = localStorage.getItem("pageSelection") || "all";
    const selectedCountVal = localStorage.getItem("selectedPagesCount") || localStorage.getItem("pdfPageCount") || "1";

    paymentFile.textContent = "File: " + fileNameVal;
    if (paymentPages) {
        if (pageSelectionVal === "all") {
            paymentPages.textContent = "Pages: All Pages";
        } else if (pageSelectionVal === "even") {
            paymentPages.textContent = `Pages: Even Pages (${selectedCountVal} selected)`;
        } else if (pageSelectionVal === "odd") {
            paymentPages.textContent = `Pages: Odd Pages (${selectedCountVal} selected)`;
        } else {
            paymentPages.textContent = `Pages: Custom (${pageRangeVal})`;
        }
    }
    paymentCopies.textContent = "Copies: " + copiesVal;
    paymentAmount.textContent = "Total Amount: ₹" + amountVal;

    if (paymentColorMode) {
        paymentColorMode.textContent = "Color Mode: " + (colorModeVal === "color" ? "Color Print 🎨" : "Black & White (B&W)");
    }
    if (paymentSide) {
        if (colorModeVal === "color" || printSideVal === "single" || duplexVal === "single") {
            paymentSide.textContent = "Print Side: Single Side";
        } else {
            if (duplexBindingVal === "short_edge" || duplexVal === "duplex_short") {
                paymentSide.textContent = "Print Side: Double Side (Short Edge - Flip 🗓️)";
            } else {
                paymentSide.textContent = "Print Side: Double Side (Long Edge - Booklet 📖)";
            }
        }
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
            const pageCountVal = parseInt(localStorage.getItem("selectedPagesCount") || localStorage.getItem("pdfPageCount") || "1", 10);
            const pageRangeVal = localStorage.getItem("pageRange") || "all";
            const colorModeVal = localStorage.getItem("colorMode") || "black_white";
            const printSideVal = localStorage.getItem("printSide") || "single";
            const duplexBindingVal = (colorModeVal === "color" || printSideVal === "single") ? null : (localStorage.getItem("duplexBinding") || localStorage.getItem("binding") || "long_edge");
            let canonicalDuplex = "single";
            if (colorModeVal !== "color" && printSideVal === "double") {
                canonicalDuplex = (duplexBindingVal === "short_edge") ? "duplex_short" : "duplex_long";
            }
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
                page_range: pageRangeVal,
                copies: copiesVal,
                color_mode: colorModeVal,
                duplex: canonicalDuplex,
                binding: duplexBindingVal,
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
                    try {
                        const fullVerificationPayload = {
                            ...payload,
                            ...response,
                            razorpay_payment_id: response.razorpay_payment_id,
                            razorpay_order_id: response.razorpay_order_id || orderData.order_id,
                            razorpay_signature: response.razorpay_signature,
                            print_order_id: activePfOrderId || orderData.order_id
                        };

                        const verifyRes = await fetch(apiUrl("/api/verify-payment", "/api/verify-payment"), {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(fullVerificationPayload)
                        });

                        const verifyData = await verifyRes.json().catch(() => ({}));
                        if (verifyRes.ok && verifyData.status === "success" && (verifyData.order_status === "PRINT_QUEUED" || verifyData.order_status === "PRINTING" || verifyData.order_status === "COMPLETED")) {
                            showPaymentSuccessModal("Payment Successful!", "✓ Payment verified. Your document is queued for printing.");
                            const nextOrderId = verifyData.order_id || activePfOrderId || orderData.order_id || localStorage.getItem("lastOrderId") || "";
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
        "amount", "printSide", "duplex", "duplexBinding", "binding", "colorMode", "orientation", "paperSize",
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

// ======================================================
// THERMAL RECEIPT PRINTER SYNTHESIZED AUDIO ENGINE (Web Audio API)
// ======================================================

class ThermalPrinterAudio {
    constructor() {
        this.ctx = null;
        this.activeNodes = null;
        this.isPlaying = false;
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

            const t = this.ctx.currentTime;
            this.isPlaying = true;

            // Master Gain node with smooth attack
            const masterGain = this.ctx.createGain();
            masterGain.gain.setValueAtTime(0.0001, t);
            masterGain.gain.exponentialRampToValueAtTime(0.22, t + 0.05);
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
            motorFilter.frequency.setValueAtTime(460, t);
            osc.connect(motorFilter);

            const motorGain = this.ctx.createGain();
            motorGain.gain.setValueAtTime(0.18, t);
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
            noiseGain.gain.setValueAtTime(0.09, t);

            whiteNoise.connect(noiseFilter);
            noiseFilter.connect(noiseGain);
            noiseGain.connect(masterGain);

            // Start audio sources
            osc.start(t);
            lfo.start(t);
            whiteNoise.start(t);

            this.activeNodes = { masterGain, osc, lfo, whiteNoise };
        } catch (e) {
            console.warn("[ThermalPrinterAudio] Audio context unlock note:", e);
        }
    }

    stop() {
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
["click", "touchstart", "keydown"].forEach(evt => {
    window.addEventListener(evt, () => {
        thermalAudio.init();
    }, { once: true });
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
