// ======================================================
// PRINTFLOW - FULL APP & ADMIN DASHBOARD LOGIC
// ======================================================

const DB_NAME = "PrintFlowDB";
const STORE_NAME = "pdfStore";
const isLocalDevelopment = ["localhost", "127.0.0.1"].includes(window.location.hostname) || window.location.protocol === "file:";
const API_BASE = isLocalDevelopment ? "http://127.0.0.1:8000" : "";
const apiUrl = (localPath, productionPath = localPath) => `${API_BASE}${isLocalDevelopment ? localPath : productionPath}`;

async function fetchWithRetry(url, options = {}, retries = 3, backoff = 500) {
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

// Initialize PDF.js worker if available
if (typeof pdfjsLib !== "undefined") {
    pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
}

// Open / initialize IndexedDB for robust multi-megabyte PDF file storage
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

// Save selected PDF File object directly to IndexedDB, resolving ONLY after tx.oncomplete
function savePdfFile(file) {
    if (!file) return Promise.resolve(null);
    return new Promise((resolve) => {
        try {
            console.log("Saving PDF to IndexedDB:", file?.name);
            localStorage.setItem("fileName", file.name);
            localStorage.setItem("fileSize", String(file.size));
            localStorage.setItem("fileType", file.type || "application/pdf");
            localStorage.setItem("fileLastModified", String(file.lastModified));

            // Read DataURL for fallback
            const reader = new FileReader();
            reader.onload = function (e) {
                try {
                    sessionStorage.setItem("pdfDataUrl", e.target.result);
                } catch (err) {
                    console.warn("sessionStorage quota note:", err);
                }
            };
            reader.readAsDataURL(file);

            // Store File object directly in IndexedDB and WAIT for transaction completion
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

                tx.onerror = (e) => {
                    console.warn("IndexedDB transaction error:", e.target.error);
                    resolve(file);
                };
            }).catch(err => {
                console.warn("IndexedDB open error:", err);
                resolve(file);
            });
        } catch (err) {
            console.error("Error saving PDF file metadata:", err);
            resolve(file);
        }
    });
}

// Retrieve PDF File object from IndexedDB
async function getSavedPdfFile() {
    try {
        const db = await openPdfDB();
        if (!db) return null;
        return new Promise((resolve) => {
            const tx = db.transaction(STORE_NAME, "readonly");
            const store = tx.objectStore(STORE_NAME);
            const request = store.get("currentPdf");
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => resolve(null);
        });
    } catch (err) {
        console.warn("Could not retrieve file from IndexedDB:", err);
        return null;
    }
}

// Clear PDF file from IndexedDB
async function clearSavedPdfFile() {
    try {
        const db = await openPdfDB();
        if (!db) return;
        const tx = db.transaction(STORE_NAME, "readwrite");
        const store = tx.objectStore(STORE_NAME);
        store.delete("currentPdf");
    } catch (err) {
        console.warn("Error clearing IndexedDB:", err);
    }
}

// Send real PDF File object using FormData to FastAPI backend and return structured result
async function uploadPdfToBackend(file) {
    if (!file) return { success: false, error: "No file provided" };
    const formData = new FormData();
    formData.append("file", file);

    try {
        console.log("Uploading PDF:", file?.name);
        const response = await fetch(apiUrl("/upload-pdf", "/api/upload-pdf"), {
            method: "POST",
            body: formData
        });

        if (!response.ok) {
            console.warn("Backend upload failed with HTTP status:", response.status);
            return { success: false, error: "HTTP error " + response.status };
        }

        const data = await response.json();
        console.log("Backend upload response:", data);

        if (data && (data.status === "success" || data.file_path)) {
            if (data.file_path) {
                localStorage.setItem("backendFilePath", data.file_path);
            }
            if (data.file_name) {
                localStorage.setItem("uploadedFileName", data.file_name);
            }
            return { success: true, data: data };
        } else {
            return { success: false, error: data?.message || "Invalid upload response" };
        }
    } catch (err) {
        console.warn("Backend upload network error:", err);
        return { success: false, error: err.message || "Network error" };
    }
}

// Render First Page Thumbnail & Count Pages using PDF.js
function renderPdfPreviewAndCount(file) {
    if (!file || typeof pdfjsLib === "undefined") return;

    const reader = new FileReader();
    reader.onload = function (e) {
        const typedarray = new Uint8Array(e.target.result);
        pdfjsLib.getDocument(typedarray).promise.then(function (pdf) {
            console.log("PDF loaded. Total Pages:", pdf.numPages);
            localStorage.setItem("pdfPageCount", String(pdf.numPages));

            const pageCountElem = document.getElementById("pageCount");
            const pageCounterCard = document.getElementById("pageCounterCard");
            if (pageCountElem) {
                pageCountElem.textContent = String(pdf.numPages);
            }
            if (pageCounterCard) {
                pageCounterCard.classList.remove("is-visible");
                void pageCounterCard.offsetWidth;
                pageCounterCard.classList.add("is-visible");
            }

            // Render first page thumbnail onto canvas
            pdf.getPage(1).then(function (page) {
                const canvas = document.getElementById("pdfCanvas");
                const previewContainer = document.getElementById("pdfPreviewContainer");
                if (canvas && previewContainer) {
                    const viewport = page.getViewport({ scale: 0.5 });
                    const context = canvas.getContext("2d");
                    canvas.height = viewport.height;
                    canvas.width = viewport.width;

                    const renderContext = {
                        canvasContext: context,
                        viewport: viewport
                    };
                    page.render(renderContext).promise.then(function () {
                        previewContainer.style.display = "block";
                    });
                }
            });
        }).catch(function (err) {
            console.warn("PDF.js render note:", err);
        });
    };
    reader.readAsArrayBuffer(file);
}

// ==========================
// PDF UPLOAD PAGE (home.html)
// ==========================

const choosePdfBtn = document.getElementById("choosePdfBtn");
const pdfFile = document.getElementById("pdfFile");
const fileName = document.getElementById("fileName");
const pageCountDisplay = document.getElementById("pageCount");
const pageCounterCard = document.getElementById("pageCounterCard");
const continueBtn = document.getElementById("continueBtn");
const pdfErrorMsg = document.getElementById("pdfErrorMsg");

function showPdfError(msg) {
    if (pdfErrorMsg) {
        pdfErrorMsg.textContent = msg || "📄 Please select a PDF file first";
        pdfErrorMsg.style.display = "block";
    }
}

function hidePdfError() {
    if (pdfErrorMsg) {
        pdfErrorMsg.style.display = "none";
    }
}

// Restore filename display on load if previously selected
if (fileName) {
    const savedName = localStorage.getItem("fileName");
    const savedPages = localStorage.getItem("pdfPageCount");
    if (savedName && savedName !== "No PDF Selected" && savedName !== "No file selected") {
        fileName.textContent = savedName;
    }
    if (savedPages && pageCountDisplay) {
        pageCountDisplay.textContent = savedPages;
        if (pageCounterCard) pageCounterCard.classList.add("is-visible");
    }
}

// File Selection Handler - Supports PDF, Images, Documents, and Multiple Files
window.handleFileSelection = function (event) {
    const input = document.getElementById("pdfFile");
    const files = (event && event.target && event.target.files) || (input && input.files);
    const nameDisplay = document.getElementById("fileName");

    if (!files || files.length === 0) {
        if (!window.selectedPdfFile && !localStorage.getItem("fileName")) {
            if (nameDisplay) nameDisplay.textContent = "No File Selected";
        }
        return;
    }

    const allowedExts = [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx", ".txt"];
    let validFiles = [];
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const ext = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();
        if (allowedExts.includes(ext) || file.type.startsWith("image/") || file.type === "application/pdf") {
            validFiles.push(file);
        }
    }

    if (validFiles.length === 0) {
        if (input) input.value = "";
        window.selectedPdfFile = null;
        if (nameDisplay) nameDisplay.textContent = "No File Selected";
        showPdfError("📄 Please select valid printable files (.pdf, .png, .jpg, .doc, .txt)");
        return;
    }

    window.selectedPdfFiles = validFiles;
    window.selectedPdfFile = validFiles[0];

    const displayTitle = validFiles.length === 1 ? validFiles[0].name : `${validFiles.length} Files Selected`;
    if (nameDisplay) nameDisplay.textContent = displayTitle;
    localStorage.setItem("fileName", displayTitle);

    const uploadConfirmation = document.getElementById("uploadConfirmation");
    if (uploadConfirmation) {
        uploadConfirmation.textContent = `Selected: ${displayTitle}`;
        uploadConfirmation.classList.add("is-visible");
    }

    hidePdfError();

    let totalPagesCalculated = 0;
    let processedCount = 0;

    validFiles.forEach((file) => {
        const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
        if (isPdf && typeof pdfjsLib !== "undefined") {
            const reader = new FileReader();
            reader.onload = function (e) {
                const typedarray = new Uint8Array(e.target.result);
                pdfjsLib.getDocument(typedarray).promise.then(function (pdf) {
                    totalPagesCalculated += (pdf.numPages || 1);
                    processedCount++;
                    if (processedCount === validFiles.length) {
                        updateTotalPagesDisplay(totalPagesCalculated);
                    }
                }).catch(function() {
                    totalPagesCalculated += 1;
                    processedCount++;
                    if (processedCount === validFiles.length) {
                        updateTotalPagesDisplay(totalPagesCalculated);
                    }
                });
            };
            reader.readAsArrayBuffer(file);
        } else {
            totalPagesCalculated += 1;
            processedCount++;
            if (processedCount === validFiles.length) {
                updateTotalPagesDisplay(totalPagesCalculated);
            }
        }
    });

    function updateTotalPagesDisplay(pages) {
        const pageCountDisplay = document.getElementById("pageCount");
        const pageCounterCard = document.getElementById("pageCounterCard");
        if (pageCountDisplay) pageCountDisplay.textContent = String(pages);
        if (pageCounterCard) pageCounterCard.classList.add("is-visible");
        localStorage.setItem("pdfPageCount", String(pages));
    }

    savePdfFile(validFiles[0]);
};

if (choosePdfBtn && pdfFile) {
    choosePdfBtn.addEventListener("click", function () {
        try {
            pdfFile.value = "";
            pdfFile.click();
        } catch (err) {
            console.warn("pdfFile click note:", err);
        }
    });

    pdfFile.addEventListener("change", window.handleFileSelection);
    pdfFile.addEventListener("input", window.handleFileSelection);
}

if (continueBtn) {
    continueBtn.addEventListener("click", async function (e) {
        if (e && e.preventDefault) e.preventDefault();

        const input = document.getElementById("pdfFile");
        const selectedFile = window.selectedPdfFile || ((input && input.files && input.files.length > 0) ? input.files[0] : null);
        const storedName = localStorage.getItem("fileName");
        const hasValidStoredName = storedName && storedName !== "No PDF Selected" && storedName !== "No file selected";

        console.log("Selected REAL PDF:", selectedFile);

        if (!selectedFile && !hasValidStoredName) {
            showPdfError("📄 Please select a PDF file first");
            return;
        }

        hidePdfError();

        if (selectedFile) {
            continueBtn.disabled = true;
            const originalText = continueBtn.textContent;
            continueBtn.textContent = "Uploading PDF...";

            try {
                // 1. Save File object to IndexedDB and WAIT for tx.oncomplete
                await savePdfFile(selectedFile);

                // 2. Perform real FormData HTTP POST upload to FastAPI backend and AWAIT structured result
                const uploadResult = await uploadPdfToBackend(selectedFile);

                if (!uploadResult || !uploadResult.success) {
                    console.warn("Backend upload failed, stopping redirection:", uploadResult);
                    showPdfError("📄 PDF upload failed. Please check connection and try again.");
                    continueBtn.disabled = false;
                    continueBtn.textContent = originalText;
                    return;
                }
                const uploadConfirmation = document.getElementById("uploadConfirmation");
                if (uploadConfirmation) {
                    const uploadedName = uploadResult.data?.file_name || selectedFile.name;
                    uploadConfirmation.textContent = `Uploaded PDF: ${uploadedName}`;
                    uploadConfirmation.classList.add("is-visible");
                }
            } catch (err) {
                console.error("PDF Upload execution error:", err);
                showPdfError("📄 PDF upload error occurred. Please try again.");
                continueBtn.disabled = false;
                continueBtn.textContent = originalText;
                return;
            } finally {
                continueBtn.disabled = false;
                continueBtn.textContent = originalText;
            }
        }

        // 3. Redirect ONLY AFTER backend PDF upload has successfully finished
        window.location.href = "print-details.html";
    });
}

// ==============================
// PRINT DETAILS PAGE (print-details.html)
// ==============================

const backBtn = document.getElementById("backBtn");
const paymentBtn = document.getElementById("paymentBtn");
const copiesBox = document.getElementById("copies");
const totalPriceBox = document.getElementById("totalPrice");
const printDetailsFileName = document.getElementById("fileName");
const paperSizeBox = document.getElementById("paperSize");
const pageRangeModeBox = document.getElementById("pageRangeMode");
const pageRangeBox = document.getElementById("pageRange");
const scalingBox = document.getElementById("scaling");
const customScaleBox = document.getElementById("customScale");
const marginsBox = document.getElementById("margins");
const previewSummary = document.getElementById("previewSummary");
const microXeroxSettings = document.getElementById("microXeroxSettings");
const pagesPerSheetBox = document.getElementById("pagesPerSheet");
const pageOrderBox = document.getElementById("pageOrder");
const microSummary = document.getElementById("microSummary");
const previewLayout = document.getElementById("previewLayout");

function countSelectedPages(pageRange, totalPages) {
    if (!pageRange || pageRange === "all") return totalPages;
    const selected = new Set();
    for (const part of pageRange.split(",")) {
        const value = part.trim();
        if (!value) continue;
        const bounds = value.split("-").map(item => Number(item.trim()));
        const start = Math.max(1, bounds[0]);
        const end = Math.min(totalPages, bounds.length > 1 ? bounds[1] : start);
        if (!Number.isInteger(start) || !Number.isInteger(end) || end < start) continue;
        for (let page = start; page <= end; page++) selected.add(page);
    }
    return selected.size || totalPages;
}

// Restore selected file display & calculate dynamic price on Print Details page
if (printDetailsFileName) {
    const savedName = localStorage.getItem("fileName");
    if (savedName) {
        printDetailsFileName.textContent = savedName;
    }

    getSavedPdfFile().then(selectedFile => {
        console.log("PDF retrieved on print-details:", selectedFile);
        if (selectedFile) {
            window.selectedPdfFile = selectedFile;
        }
    });
}

if (copiesBox && totalPriceBox) {
    function getSelectedColorMode() {
        const selected = document.querySelector('input[name="colorMode"]:checked')?.value;
        return ["black_white", "color", "micro_xerox"].includes(selected)
            ? selected
            : "black_white";
    }

    function getSelectedPagesPerSheet() {
        const value = Number(pagesPerSheetBox?.value);
        return [2, 4, 6, 9, 16].includes(value) ? value : 4;
    }

    function updateMicroPreview(pagesPerSheet, pageOrder, colorMode) {
        if (!previewLayout) return;

        const previewPages = colorMode === "micro_xerox" ? pagesPerSheet : 1;
        const columns = previewPages >= 9 ? 4 : previewPages >= 4 ? 2 : previewPages;

        previewLayout.classList.toggle(
            "page-order-horizontal",
            pageOrder !== "vertical"
        );
        previewLayout.classList.toggle(
            "page-order-vertical",
            pageOrder === "vertical"
        );
        previewLayout.style.gridTemplateColumns =
            `repeat(${columns}, minmax(0, 1fr))`;

        previewLayout.innerHTML = Array.from(
            { length: previewPages },
            (_, index) =>
                `<span class="preview-page" title="Page ${index + 1}">${index + 1}</span>`
        ).join("");
    }

    function updateTotalPrice() {
        const copies = Math.min(999, Math.max(1, Number(copiesBox.value) || 1));
        copiesBox.value = copies;

        const totalPages = Number(localStorage.getItem("pdfPageCount")) || 1;
        const pageRange = pageRangeModeBox?.value === "custom"
            ? (pageRangeBox?.value.trim() || "all")
            : "all";
        const pageCount = countSelectedPages(pageRange, totalPages);
        const colorMode = getSelectedColorMode();
        const pagesPerSheet = getSelectedPagesPerSheet();
        const pageOrder = pageOrderBox?.value === "vertical"
            ? "vertical"
            : "horizontal";

        const physicalPapersPerCopy = Math.ceil(pageCount / pagesPerSheet);
        const physicalPapers = physicalPapersPerCopy * copies;

        let totalAmount;
        if (colorMode === "micro_xerox") {
            totalAmount = physicalPapers * 3;
        } else {
            const pricePerPage = colorMode === "color" ? 6 : 2;
            totalAmount = pageCount * copies * pricePerPage;
        }

        totalPriceBox.textContent = `Total: ₹${totalAmount}`;
        localStorage.setItem("amount", String(totalAmount));

        if (microXeroxSettings) {
            microXeroxSettings.hidden = colorMode !== "micro_xerox";
        }

        if (microSummary) {
            microSummary.innerHTML = `
                <div>PDF Pages<strong>${pageCount}</strong></div>
                <div>Pages / Sheet<strong>${pagesPerSheet}</strong></div>
                <div>Physical Papers<strong>${physicalPapers}</strong></div>
                <div>Copies<strong>${copies}</strong></div>
                <div>Total Price<strong>₹${totalAmount}</strong></div>
            `;
        }

        if (previewSummary) {
            const paper = paperSizeBox?.value || "A4";
            const orientation =
                document.querySelector('input[name="orientation"]:checked')?.value ||
                "portrait";
            const side =
                document.querySelector('input[name="printSide"]:checked')?.value ||
                "double";
            const colorLabel = colorMode === "color"
                ? "Color"
                : colorMode === "micro_xerox"
                    ? "Micro Xerox"
                    : "Black & White";

            previewSummary.textContent = colorMode === "micro_xerox"
                ? `${paper} · ${orientation} · ${colorLabel} · ${pagesPerSheet} pages/sheet · ${pageOrder} order · ${copies} ${copies === 1 ? "copy" : "copies"} · ₹${totalAmount}`
                : `${paper} · ${orientation} · ${colorLabel} · ${side} · ${copies} ${copies === 1 ? "copy" : "copies"} · ₹${totalAmount}`;
        }

        updateMicroPreview(pagesPerSheet, pageOrder, colorMode);
    }

    copiesBox.addEventListener("input", updateTotalPrice);

    document
        .querySelectorAll('input[name="colorMode"], input[name="orientation"], input[name="printSide"]')
        .forEach(input => input.addEventListener("change", updateTotalPrice));

    [
        paperSizeBox,
        pageRangeModeBox,
        pageRangeBox,
        scalingBox,
        customScaleBox,
        marginsBox,
        pagesPerSheetBox,
        pageOrderBox
    ].forEach(input => {
        input?.addEventListener("input", updateTotalPrice);
        input?.addEventListener("change", updateTotalPrice);
    });

    updateTotalPrice();
}

pageRangeModeBox?.addEventListener("change", () => {
    const custom = pageRangeModeBox.value === "custom";
    if (pageRangeBox) pageRangeBox.style.display = custom ? "block" : "none";
});

scalingBox?.addEventListener("change", () => {
    if (customScaleBox) customScaleBox.style.display = scalingBox.value === "custom" ? "block" : "none";
});

if (backBtn) {
    backBtn.addEventListener("click", function (e) {
        if (e && e.preventDefault) e.preventDefault();
        window.location.href = "home.html";
    });
}

if (paymentBtn) {
    paymentBtn.addEventListener("click", function (e) {
        if (e && e.preventDefault) e.preventDefault();
        const copies = Math.min(999, Math.max(1, Number(copiesBox?.value) || 1));
        const totalPages = Number(localStorage.getItem("pdfPageCount")) || 1;
        const pageRange = pageRangeModeBox?.value === "custom" ? (pageRangeBox?.value.trim() || "all") : "all";
        const pageCount = countSelectedPages(pageRange, totalPages);
        const colorMode = document.querySelector('input[name="colorMode"]:checked')?.value || "black_white";
        const pagesPerSheet = Number(pagesPerSheetBox?.value) || 4;
        const amount = colorMode === "micro_xerox" ? Math.ceil(pageCount / pagesPerSheet) * copies * 3 : copies * pageCount * (colorMode === "color" ? 6 : 2);

        localStorage.setItem("copies", copies);
        localStorage.setItem("amount", amount);

        const selectedSide = document.querySelector(
            'input[name="printSide"]:checked'
        );

        if (selectedSide) {
            localStorage.setItem("printSide", selectedSide.value);
        }

        const selectedColor = document.querySelector(
            'input[name="colorMode"]:checked'
        );
        if (selectedColor) {
            localStorage.setItem("colorMode", selectedColor.value);
        }

        const selectedOrientation = document.querySelector(
            'input[name="orientation"]:checked'
        );

        if (selectedOrientation) {
            localStorage.setItem("orientation", selectedOrientation.value);
        }

        localStorage.setItem("paperSize", paperSizeBox?.value || "A4");
        localStorage.setItem("pageRange", pageRangeModeBox?.value === "custom" ? (pageRangeBox?.value.trim() || "all") : "all");
        localStorage.setItem("pagesPerSheet", pagesPerSheet);
        localStorage.setItem("pageOrder", pageOrderBox?.value || "horizontal");
        localStorage.setItem("scaling", scalingBox?.value || "actual_size");
        localStorage.setItem("customScale", customScaleBox?.value || "100");
        localStorage.setItem("margins", marginsBox?.value || "default");

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
    const paperSizeVal = localStorage.getItem("paperSize") || "A4";
    const pageRangeVal = localStorage.getItem("pageRange") || "all";
    const pagesPerSheetVal = localStorage.getItem("pagesPerSheet") || "4";
    const pageOrderVal = localStorage.getItem("pageOrder") || "horizontal";
    const scalingVal = localStorage.getItem("scaling") || "actual_size";
    const customScaleVal = localStorage.getItem("customScale") || "100";
    const marginsVal = localStorage.getItem("margins") || "default";

    paymentFile.textContent = "File: " + fileNameVal;
    paymentCopies.textContent = "Copies: " + copiesVal;
    paymentAmount.textContent = "Total Amount: ₹" + amountVal;

    if (paymentColorMode) {
        const colorModeLabel = colorModeVal === "color"
            ? "Color Print 🎨"
            : colorModeVal === "micro_xerox"
                ? `Micro Xerox (${pagesPerSheetVal} pages/sheet, ${pageOrderVal} order)`
                : "Black & White (B&W)";

        paymentColorMode.textContent = "Color Mode: " + colorModeLabel;
    }

    getSavedPdfFile().then(selectedFile => {
        console.log("File available on payment page:", selectedFile);
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

// ======================================================
// CUSTOM ANIMATED PAYMENT FAILED MODAL HELPER
// ======================================================

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

    if (closeBtn) {
        closeBtn.onclick = closeModal;
    }
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

if (payBtn) {
    payBtn.addEventListener("click", async function (e) {
        if (e && e.preventDefault) e.preventDefault();

        const amountVal = localStorage.getItem("amount") || "2";

        payBtn.disabled = true;
        payBtn.textContent = "Processing Payment...";

        try {
            const selectedFile = window.selectedPdfFile || await getSavedPdfFile();
            let uploadedPath = localStorage.getItem("backendFilePath") || "";

            if (selectedFile) {
                const uploadRes = await uploadPdfToBackend(selectedFile);
                if (uploadRes && uploadRes.data && uploadRes.data.file_path) {
                    uploadedPath = uploadRes.data.file_path;
                }
            }

            // Create Order Record in Backend Database for Admin Dashboard
            const fileNameVal = localStorage.getItem("fileName") || "document.pdf";
            const copiesVal = parseInt(localStorage.getItem("copies") || "1", 10);
            const totalPagesVal = parseInt(localStorage.getItem("pdfPageCount") || "1", 10);
            const pageRangeVal = localStorage.getItem("pageRange") || "all";
            const pageCountVal = pageRangeVal === "all" ? totalPagesVal : countSelectedPages(pageRangeVal, totalPagesVal);
            const colorModeVal = localStorage.getItem("colorMode") || "black_white";
            const printSideVal = localStorage.getItem("printSide") || "double";
            const orientationVal = localStorage.getItem("orientation") || "portrait";
            const paperSizeVal = localStorage.getItem("paperSize") || "A4";
            const pagesPerSheetVal = parseInt(localStorage.getItem("pagesPerSheet") || "4", 10);
            const pageOrderVal = localStorage.getItem("pageOrder") || "horizontal";
            const scalingVal = localStorage.getItem("scaling") || "actual_size";
            const customScaleVal = parseFloat(localStorage.getItem("customScale") || "100");
            const marginsVal = localStorage.getItem("margins") || "default";
            const rawMobile = localStorage.getItem("mobileNumber") || "9876543210";
            const cleanContact = rawMobile.replace(/\D/g, "").slice(-10) || "9876543210";

            const printResponse = await fetch(apiUrl("/print-order", "/api/print-order"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    file_name: fileNameVal,
                    copies: copiesVal,
                    pages: pageCountVal,
                    file_size: selectedFile?.size || 0,
                    paper_size: paperSizeVal,
                    page_range: pageRangeVal,
                    pages_per_sheet: colorModeVal === "micro_xerox" ? pagesPerSheetVal : 1,
                    page_order: colorModeVal === "micro_xerox" ? pageOrderVal : "horizontal",
                    color_mode: colorModeVal,
                    duplex: printSideVal,
                    orientation: orientationVal,
                    scaling: scalingVal,
                    custom_scale: customScaleVal,
                    margins: marginsVal,
                    customer_mobile: cleanContact,
                    amount: parseFloat(amountVal),
                    file_path: uploadedPath
                })
            });
            if (!printResponse.ok) {
                throw new Error(`Order creation failed with HTTP ${printResponse.status}`);
            }
            const printData = await printResponse.json();
            publishOrderUpdate(printData.order);

            // Trigger Razorpay Order API
            const orderRes = await fetchWithRetry(apiUrl("/api/create-order", "/api/create-order"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    amount: parseFloat(amountVal),
                    pages: pageCountVal,
                    copies: copiesVal,
                    color_mode: colorModeVal,
                    pages_per_sheet: colorModeVal === "micro_xerox" ? pagesPerSheetVal : 1,
                    order_id: printData.order.order_id
                })
            });
            const resText = await orderRes.text();
            let orderData;
            try {
                orderData = JSON.parse(resText);
            } catch (pErr) {
                throw new Error(`API server returned invalid response (HTTP ${orderRes.status}). Please ensure backend server is running.`);
            }

            if (!orderRes.ok || !orderData || orderData.status === "error") {
                const detail = (orderData && orderData.detail) ? orderData.detail : `HTTP ${orderRes.status}`;
                throw new Error(`Order creation failed: ${detail}`);
            }

            console.log("Razorpay Order Created:", orderData);

            if (typeof Razorpay !== "undefined") {
                const options = {
                    "key": orderData.key_id,
                    "amount": Math.round(Number(orderData.amount)),
                    "currency": orderData.currency || "INR",
                    "name": "PrintFlow",
                    "description": `Print Order Payment - ${fileNameVal}`,
                    "order_id": orderData.order_id,
                    "prefill": {
                        "contact": cleanContact,
                        "email": "customer@printflow.in"
                    },
                    "handler": async function (response) {
                        console.log("Razorpay Payment Success:", response);
                        try {
                            const verifyRes = await fetchWithRetry(apiUrl("/api/verify-payment", "/api/verify-payment"), {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                    ...response,
                                    print_order_id: printData.order.order_id,
                                    print_order: printData.order
                                })
                            });
                            const vText = await verifyRes.text();
                            let verifyData;
                            try {
                                verifyData = JSON.parse(vText);
                            } catch (vPErr) {
                                throw new Error("Payment verification server response was invalid.");
                            }

                            if (verifyRes.ok && verifyData && verifyData.status === "success") {
    localStorage.setItem("lastOrderId", printData.order.order_id);
    window.location.href = "success.html";
} else {
    const vDetail = verifyData?.detail || "Payment verification failed.";
    showPaymentFailedModal("Verification Failed", vDetail);

    payBtn.disabled = false;
    payBtn.textContent = "Pay with Razorpay";
}
                                
                        } catch (vErr) {
    console.error("Payment verification error:", vErr);

    showPaymentFailedModal(
        "Verification Error",
        vErr.message || "Payment verification failed."
    );

    payBtn.disabled = false;
    payBtn.textContent = "Pay with Razorpay";
                        }
                    },
                    "theme": {
                        "color": "#ea580c"
                    },
                    "modal": {
                        "escape": true,
                        "backdropclose": false,
                        "ondismiss": function() {
                            payBtn.disabled = false;
                            payBtn.textContent = "Pay with Razorpay";
                        }
                    }
                };

                const rzp = new Razorpay(options);
                rzp.on("payment.failed", function (response) {
                    console.warn("Razorpay Payment Failed:", response.error);
                    const errorDesc = response.error.description || "Your payment didn't go through due to a temporary issue. Any debited amount will be refunded in 4-5 business days.";
                    showPaymentFailedModal("Payment Failed", errorDesc);
                    payBtn.disabled = false;
                    payBtn.textContent = "Pay with Razorpay";
                });
                rzp.open();

                // Re-enable button after modal opens so button resets if modal is dismissed or closed
                setTimeout(() => {
                    if (payBtn) {
                        payBtn.disabled = false;
                        payBtn.textContent = "Pay with Razorpay";
                    }
                }, 1500);
            } else {
                showPaymentFailedModal("SDK Error", "Razorpay SDK failed to load. Please check your internet connection.");
                payBtn.disabled = false;
                payBtn.textContent = "Pay with Razorpay";
            }
        } catch (err) {
            console.error("Razorpay Payment error:", err);
            showPaymentFailedModal("Order Error", "Order creation failed: " + (err.message || "Please try again."));
            payBtn.disabled = false;
            payBtn.textContent = "Pay with Razorpay";
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
const printingOrdersCount = document.getElementById("printingOrdersCount");
const completedOrdersCount = document.getElementById("completedOrdersCount");
const failedOrdersCount = document.getElementById("failedOrdersCount");
const colorPagesCount = document.getElementById("colorPagesCount");
const monthRevenue = document.getElementById("monthRevenue");

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
        const res = await fetch(apiUrl("/api/orders", "/api/orders"));
        const data = await res.json();

        if (data && data.orders) {
            allAdminOrders = data.orders;
            renderAdminOrders(allAdminOrders);
        }
    } catch (err) {
        console.warn("Error fetching admin orders:", err);
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
    let printingCount = 0;
    let completedCount = 0;
    let failedCount = 0;
    let colorPages = 0;
    let monthSum = 0;
    const now = new Date();

    orders.forEach(order => {
        earningsSum += (order.amount || 0);
        pagesSum += ((order.pages || 1) * (order.copies || 1));
        if (order.status === "Pending" || order.status === "PRINT_QUEUED") pendingCount++;
        if (order.status === "PRINTING") printingCount++;
        if (order.status === "COMPLETED" || order.status === "Completed") completedCount++;
        if (order.status === "FAILED") failedCount++;
        if (order.color_mode === "color") colorPages += ((order.pages || 1) * (order.copies || 1));
        const orderDate = new Date(order.timestamp || 0);
        if (orderDate.getFullYear() === now.getFullYear() && orderDate.getMonth() === now.getMonth()) {
            monthSum += (order.amount || 0);
        }
    });

    if (totalEarnings) totalEarnings.textContent = `₹${earningsSum}`;
    if (totalOrdersCount) totalOrdersCount.textContent = String(orders.length);
    if (totalPagesPrinted) totalPagesPrinted.textContent = String(pagesSum);
    if (pendingOrdersCount) pendingOrdersCount.textContent = String(pendingCount);
    if (printingOrdersCount) printingOrdersCount.textContent = String(printingCount);
    if (completedOrdersCount) completedOrdersCount.textContent = String(completedCount);
    if (failedOrdersCount) failedOrdersCount.textContent = String(failedCount);
    if (colorPagesCount) colorPagesCount.textContent = String(colorPages);
    if (monthRevenue) monthRevenue.textContent = `₹${monthSum}`;

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
                <td><strong class="admin-file-name" title="${order.file_name}">${order.file_name}</strong><br><small style="color: #ea580c;">${order.pages || 1} Pages · ${order.paper_size || 'A4'} · ${order.orientation || 'portrait'}</small></td>
                <td>${order.copies || 1} Copies (${order.duplex === 'double' ? 'Double' : 'Single'} Side)<br><small>${order.color_mode === 'micro_xerox' ? `Micro Xerox · ${order.pages_per_sheet || 1}/sheet · ${order.page_order || 'horizontal'}` : (order.color_mode === 'color' ? 'Color' : 'B&W')}</small></td>
                <td><strong>₹${order.amount || 2}</strong></td>
                <td>
                    <span class="${badgeClass}">
                        ${order.status || 'Pending'}
                    </span>
                </td>
                <td>
                    <div class="action-btn-row">
                        ${order.file_path ? `<a href="${fileUrl}" target="_blank" class="btn-download">⬇️ View</a>` : ''}
                        ${order.file_path ? `<button type="button" class="btn-print" onclick="printOrderFile('${order.order_id}', '${fileUrl}')">🖨️ Print</button>` : ''}
                        ${(isPending || isFailed) ? `<button type="button" class="btn-complete" style="background:#e0f2fe; color:#0369a1; border-color:#bae6fd;" onclick="retryOrder('${order.order_id}')">🔄 Retry</button>` : ''}
                        ${(isPending || isPrinting) ? `<button type="button" class="btn-complete" style="background:#fff1f2; color:#be123c; border-color:#fecdd3;" onclick="cancelOrder('${order.order_id}')">✖ Cancel</button>` : ''}
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

window.printOrderFile = async function (orderId) {
    if (!orderId) return;
    try {
        const res = await fetch(apiUrl(`/api/orders/${orderId}/print`, `/api/orders/${orderId}/print`), {
            method: "POST"
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || data.message || `Print request failed with HTTP ${res.status}`);
        }
        alert(`🖨️ ${data.message || "Print job queued!"}`);
        fetchAdminOrders();
    } catch (err) {
        alert(`⚠️ ${err.message || "Failed to queue print job"}`);
    }
};

window.cancelOrder = async function (orderId) {
    if (!orderId || !window.confirm("Cancel this print job?")) return;
    try {
        const res = await fetch(apiUrl(`/api/orders/${orderId}/cancel`, `/api/orders/${orderId}/cancel`), { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Unable to cancel order");
        fetchAdminOrders();
    } catch (err) {
        alert(`⚠️ ${err.message || "Unable to cancel order"}`);
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

// Initial admin order & printers fetch if on admin.html
if (adminOrdersTableBody && adminPortalUnlocked) {
    fetchAdminOrders();
    fetchConnectedPrinters();
    setInterval(fetchAdminOrders, 2000); // Keep the admin queue current while the portal is open.
}

// =======================
// SUCCESS PAGE (success.html)
// =======================

const homeBtn = document.getElementById("homeBtn");
const privacyStatusText = document.getElementById("privacyStatusText");
const docCleanupBadge = document.getElementById("docCleanupBadge");
const successOrderId = document.getElementById("successOrderId");

if (privacyStatusText || docCleanupBadge) {
    const lastOrderId = localStorage.getItem("lastOrderId") || localStorage.getItem("razorpayOrderId") || "PF-ORDER";
    if (successOrderId) successOrderId.textContent = lastOrderId;

    async function checkDocCleanupStatus() {
        try {
            const res = await fetch(apiUrl(`/api/orders/${lastOrderId}/status`, `/api/orders/${lastOrderId}/status`));
            const data = await res.json();
            if (data && data.status === "success") {
                const orderStatus = data.order_status || "Pending";
                const docStatus = data.document_status || "UPLOADED";
                if (orderStatus === "COMPLETED" && (docStatus === "PRINTED" || docStatus === "DELETED")) {
                    if (privacyStatusText) privacyStatusText.textContent = "Your documents have been securely deleted after printing.";
                    if (docCleanupBadge) {
                        docCleanupBadge.textContent = "DELETED";
                        docCleanupBadge.style.color = "#15803d";
                    }
                } else if (orderStatus === "FAILED") {
                    if (privacyStatusText) privacyStatusText.textContent = data.print_error || "Printing failed. Please contact the print counter.";
                    if (docCleanupBadge) {
                        docCleanupBadge.textContent = "FAILED";
                        docCleanupBadge.style.color = "#b91c1c";
                    }
                } else if (orderStatus === "PRINTING") {
                    if (privacyStatusText) privacyStatusText.textContent = "Your printer is processing the document...";
                    if (docCleanupBadge) docCleanupBadge.textContent = "PRINTING";
                } else if (orderStatus === "PRINT_QUEUED") {
                    if (privacyStatusText) privacyStatusText.textContent = "Payment verified. Your print job is queued.";
                    if (docCleanupBadge) docCleanupBadge.textContent = "QUEUED";
                } else {
                    if (privacyStatusText) privacyStatusText.textContent = "Payment verified. Waiting for the printer agent...";
                    if (docCleanupBadge) {
                        docCleanupBadge.textContent = orderStatus.toUpperCase();
                        docCleanupBadge.style.color = "#ea580c";
                    }
                }
            }
        } catch (err) {
            if (privacyStatusText) privacyStatusText.textContent = "Payment verified. Checking printer status...";
            if (docCleanupBadge) docCleanupBadge.textContent = "CHECKING";
        }
    }

    checkDocCleanupStatus();
    const cleanupInterval = setInterval(checkDocCleanupStatus, 1500);
    setTimeout(() => clearInterval(cleanupInterval), 15000);
}

if (homeBtn) {
    homeBtn.addEventListener("click", function (e) {
        if (e && e.preventDefault) e.preventDefault();
        localStorage.removeItem("fileName");
        localStorage.removeItem("fileSize");
        localStorage.removeItem("fileType");
        localStorage.removeItem("fileLastModified");
        localStorage.removeItem("backendFilePath");
        localStorage.removeItem("copies");
        localStorage.removeItem("amount");
        localStorage.removeItem("pdfPageCount");
        localStorage.removeItem("printSide");
        localStorage.removeItem("orientation");
        sessionStorage.removeItem("pdfDataUrl");

        clearSavedPdfFile();

        window.location.href = "home.html";
    });
}
