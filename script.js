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

async function uploadPdfToBackend(file) {
    if (!file) return null;
    try {
        const formData = new FormData();
        formData.append("file", file, file.name);

        const res = await fetch(apiUrl("/upload-pdf", "/api/upload-pdf"), {
            method: "POST",
            body: formData
        });

        if (res.ok) {
            const data = await res.json();
            console.log("PDF uploaded to backend:", data);
            if (data && data.file_path) {
                localStorage.setItem("backendFilePath", data.file_path);
            }
            return { ok: true, data };
        }
    } catch (err) {
        console.warn("Backend upload note:", err);
    }
    return null;
}

const fileInput = document.getElementById("pdfFile");
const choosePdfBtn = document.getElementById("choosePdfBtn");
const fileName = document.getElementById("fileName");
const continueBtn = document.getElementById("continueBtn");
const pageCountDisplay = document.getElementById("pageCount");
const pdfErrorMsg = document.getElementById("pdfErrorMsg");
const pageCounterCard = document.getElementById("pageCounterCard");
const uploadConfirmation = document.getElementById("uploadConfirmation");

function countPdfPages(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = function () {
            const typedarray = new Uint8Array(this.result);
            if (typeof pdfjsLib === "undefined") {
                reject("PDF.js library is not loaded.");
                return;
            }
            pdfjsLib.getDocument(typedarray).promise.then(function (pdf) {
                resolve(pdf.numPages);
            }).catch(function (error) {
                reject(error);
            });
        };
        reader.onerror = function (error) {
            reject(error);
        };
        reader.readAsArrayBuffer(file);
    });
}

function renderPdfFirstPageThumbnail(file) {
    const previewContainer = document.getElementById("pdfPreviewContainer");
    const canvas = document.getElementById("pdfCanvas");
    if (!previewContainer || !canvas) return;

    if (file.type && file.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const img = new Image();
            img.onload = function() {
                canvas.width = 140;
                canvas.height = 180;
                const ctx = canvas.getContext("2d");
                ctx.drawImage(img, 0, 0, 140, 180);
                previewContainer.style.display = "block";
            };
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);
        return;
    }

    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
        previewContainer.style.display = "none";
        return;
    }

    const reader = new FileReader();
    reader.onload = function () {
        const typedarray = new Uint8Array(this.result);
        if (typeof pdfjsLib === "undefined") return;
        pdfjsLib.getDocument(typedarray).promise.then(function (pdf) {
            pdf.getPage(1).then(function (page) {
                const viewport = page.getViewport({ scale: 0.5 });
                const context = canvas.getContext("2d");
                canvas.height = viewport.height;
                canvas.width = viewport.width;
                page.render({
                    canvasContext: context,
                    viewport: viewport
                }).promise.then(function () {
                    previewContainer.style.display = "block";
                });
            });
        }).catch(err => {
            console.warn("Thumbnail render note:", err);
            previewContainer.style.display = "none";
        });
    };
    reader.readAsArrayBuffer(file);
}

async function handleFileSelection(e) {
    const files = e && e.target && e.target.files ? Array.from(e.target.files) : [];
    if (!files.length) return;

    if (pdfErrorMsg) pdfErrorMsg.style.display = "none";

    let totalPages = 0;
    const fileNames = files.map(f => f.name).join(", ");

    for (const f of files) {
        if (f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf")) {
            try {
                const pages = await countPdfPages(f);
                totalPages += pages;
            } catch (err) {
                totalPages += 1;
            }
        } else {
            totalPages += 1;
        }
    }

    if (fileName) {
        fileName.textContent = fileNames;
    }

    if (uploadConfirmation) {
        uploadConfirmation.textContent = `✓ Selected: ${fileNames}`;
        uploadConfirmation.classList.add("is-visible");
    }

    if (pageCountDisplay) {
        pageCountDisplay.textContent = totalPages;
        if (pageCounterCard) pageCounterCard.classList.add("is-visible");
    }

    localStorage.setItem("fileName", fileNames);
    localStorage.setItem("pdfPageCount", String(totalPages));

    if (files.length > 0) {
        renderPdfFirstPageThumbnail(files[0]);
        await savePdfFile(files[0]);
        uploadPdfToBackend(files[0]);
    }
}
window.handleFileSelection = handleFileSelection;

if (choosePdfBtn && fileInput) {
    choosePdfBtn.addEventListener("click", function () {
        fileInput.value = "";
        fileInput.click();
    });

    fileInput.addEventListener("change", handleFileSelection);
}

if (continueBtn) {
    continueBtn.addEventListener("click", function (e) {
        if (e && e.preventDefault) e.preventDefault();
        const savedName = localStorage.getItem("fileName");
        if (!savedName || savedName === "No File Selected") {
            if (pdfErrorMsg) pdfErrorMsg.style.display = "block";
            return;
        }
        window.location.href = "print-details.html";
    });
}

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
    const pagesPerSheet = pagesPerSheetEl ? parseInt(pagesPerSheetEl.value, 10) : 2;

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
        paperSheetPreview.className = `paper-sheet size-${paperSize} ${orientation}`;
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
        if (previewLabelBadge) previewLabelBadge.textContent = "Standard Print";
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
            const pagesPerSheetVal = parseInt(localStorage.getItem("pagesPerSheet") || "1", 10);
            const pageOrderVal = localStorage.getItem("pageOrder") || "horizontal";
            const rawMobile = localStorage.getItem("mobileNumber") || "9876543210";
            const cleanContact = rawMobile.replace(/\D/g, "").slice(-10) || "9876543210";

            const printResponse = await fetch(apiUrl("/print-order", "/api/print-order"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    file_name: fileNameVal,
                    copies: copiesVal,
                    pages: pageCountVal,
                    color_mode: colorModeVal,
                    duplex: printSideVal,
                    paper_size: paperSizeVal,
                    orientation: orientationVal,
                    scale_mode: scaleModeVal,
                    margins: marginsVal,
                    print_mode: printModeVal,
                    pages_per_sheet: pagesPerSheetVal,
                    page_order: pageOrderVal,
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

            if (printData && printData.order && printData.order.order_id) {
                localStorage.setItem("lastOrderId", printData.order.order_id);
            }

            const orderRes = await fetchWithRetry(apiUrl("/api/create-order", "/api/create-order"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    amount: parseFloat(amountVal),
                    pages: pageCountVal,
                    copies: copiesVal,
                    color_mode: colorModeVal,
                    duplex: printSideVal,
                    print_mode: printModeVal,
                    pages_per_sheet: pagesPerSheetVal,
                    order_id: `PF_ORDER_${Date.now()}`
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
                        try {
                            const verifyRes = await fetchWithRetry(apiUrl("/api/verify-payment", "/api/verify-payment"), {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify(response)
                            });
                            const vText = await verifyRes.text();
                            let verifyData;
                            try {
                                verifyData = JSON.parse(vText);
                            } catch (vPErr) {
                                throw new Error("Payment verification server response was invalid.");
                            }

                            if ((verifyRes.ok && verifyData && verifyData.status === "success") || (response && response.razorpay_payment_id)) {
                                window.location.href = "success.html";
                            } else {
                                const vDetail = (verifyData && verifyData.detail) ? verifyData.detail : "Payment signature verification failed.";
                                showPaymentFailedModal("Verification Failed", vDetail);
                                payBtn.disabled = false;
                                payBtn.textContent = "Pay with Razorpay";
                            }
                        } catch (vErr) {
                            if (response && response.razorpay_payment_id) {
                                window.location.href = "success.html";
                            } else {
                                showPaymentFailedModal("Verification Error", vErr.message || "Payment verification error occurred.");
                                payBtn.disabled = false;
                                payBtn.textContent = "Pay with Razorpay";
                            }
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
                    const errorDesc = response.error.description || "Your payment didn't go through due to a temporary issue. Any debited amount will be refunded in 4-5 business days.";
                    showPaymentFailedModal("Payment Failed", errorDesc);
                    payBtn.disabled = false;
                    payBtn.textContent = "Pay with Razorpay";
                });
                rzp.open();

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

function initSuccessReceiptPage() {
    const rcptPaper = document.getElementById("receiptPaper");
    const rcptOrderId = document.getElementById("rcptOrderId");
    const rcptFileName = document.getElementById("rcptFileName");
    const rcptPages = document.getElementById("rcptPages");
    const rcptCopies = document.getElementById("rcptCopies");
    const rcptPrintMode = document.getElementById("rcptPrintMode");
    const rcptColorMode = document.getElementById("rcptColorMode");
    const rcptSides = document.getElementById("rcptSides");
    const rcptPaperSize = document.getElementById("rcptPaperSize");
    const rcptOrientation = document.getElementById("rcptOrientation");
    const rcptAmount = document.getElementById("rcptAmount");
    const rcptStatusBadge = document.getElementById("rcptStatusBadge");
    const statusHeadline = document.getElementById("statusHeadline");
    const statusSubtext = document.getElementById("statusSubtext");
    const ledDot = document.getElementById("ledDot");
    const agentStateText = document.getElementById("agentStateText");
    const privacyToast = document.getElementById("privacyToast");
    const retryBtn = document.getElementById("retryBtn");

    if (!rcptOrderId && !rcptPaper) return;

    const orderId = localStorage.getItem("lastOrderId") || localStorage.getItem("razorpayOrderId") || `PF-${Math.floor(100000 + Math.random() * 900000)}`;
    const fileName = localStorage.getItem("fileName") || "document.pdf";
    const pages = localStorage.getItem("pdfPageCount") || "1";
    const copies = localStorage.getItem("copies") || "1";
    const printMode = localStorage.getItem("printMode") === "micro_xerox" ? "Micro Xerox" : "Standard";
    const colorMode = localStorage.getItem("colorMode") === "color" ? "Color Print 🎨" : "Black & White";
    const sides = localStorage.getItem("printSide") === "double" ? "Double Side" : "Single Side";
    const paperSize = (localStorage.getItem("paperSize") || "a4").toUpperCase();
    const orientation = (localStorage.getItem("orientation") || "portrait").toUpperCase();
    const amount = localStorage.getItem("amount") || "2.00";

    if (rcptOrderId) rcptOrderId.textContent = orderId;
    if (rcptFileName) rcptFileName.textContent = fileName;
    if (rcptPages) rcptPages.textContent = pages;
    if (rcptCopies) rcptCopies.textContent = copies;
    if (rcptPrintMode) rcptPrintMode.textContent = printMode;
    if (rcptColorMode) rcptColorMode.textContent = colorMode;
    if (rcptSides) rcptSides.textContent = sides;
    if (rcptPaperSize) rcptPaperSize.textContent = paperSize;
    if (rcptOrientation) rcptOrientation.textContent = orientation;
    if (rcptAmount) rcptAmount.textContent = `₹${amount}`;

    if (rcptPaper) {
        setTimeout(() => rcptPaper.classList.add("emerging"), 150);
    }

    async function pollStatus() {
        try {
            const res = await fetch(apiUrl(`/api/orders/${orderId}/status`, `/api/orders/${orderId}/status`));
            const data = await res.json();
            if (data && data.status === "success") {
                const orderState = data.order_status || "PRINT_QUEUED";

                if (rcptStatusBadge) {
                    rcptStatusBadge.textContent = orderState;
                    rcptStatusBadge.className = `receipt-status-badge status-${orderState.toLowerCase()}`;
                }

                if (orderState === "PRINT_QUEUED") {
                    if (statusHeadline) statusHeadline.textContent = "Preparing your print...";
                    if (statusSubtext) statusSubtext.textContent = "Your payment has been received. Queueing document for physical printer.";
                    if (ledDot) ledDot.className = "led-dot";
                    if (agentStateText) agentStateText.textContent = "QUEUED";
                } else if (orderState === "PRINTING") {
                    if (statusHeadline) statusHeadline.textContent = "Printing your document...";
                    if (statusSubtext) statusSubtext.textContent = "The physical printer is actively printing your file.";
                    if (ledDot) ledDot.className = "led-dot";
                    if (agentStateText) agentStateText.textContent = "PRINTING";
                    if (rcptPaper) rcptPaper.classList.add("emerging");
                } else if (orderState === "COMPLETED") {
                    if (statusHeadline) statusHeadline.textContent = "Print Successful! 🎉";
                    if (statusSubtext) statusSubtext.textContent = "Your document has been printed successfully.";
                    if (ledDot) ledDot.className = "led-dot online";
                    if (agentStateText) agentStateText.textContent = "COMPLETED";
                    if (rcptPaper) {
                        rcptPaper.classList.remove("emerging");
                        rcptPaper.classList.add("settled");
                    }
                    if (privacyToast) privacyToast.style.display = "flex";
                    if (successPollingInterval) clearInterval(successPollingInterval);
                } else if (orderState === "FAILED") {
                    if (statusHeadline) statusHeadline.textContent = "Printing Failed";
                    if (statusSubtext) statusSubtext.textContent = "We couldn't complete your print job on the physical printer.";
                    if (ledDot) ledDot.className = "led-dot failed";
                    if (agentStateText) agentStateText.textContent = "FAILED";
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
        const res = await fetch(apiUrl(`/api/orders/${orderId}/retry`, `/api/orders/${orderId}/retry`), { method: "POST" });
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
