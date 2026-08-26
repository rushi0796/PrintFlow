// ======================================================
// PRINTFLOW - PDF PERSISTENCE & APP LOGIC
// ======================================================

const DB_NAME = "PrintFlowDB";
const STORE_NAME = "pdfStore";

// ======================================================
// INDEXEDDB
// ======================================================

function openPdfDB() {
    return new Promise((resolve) => {
        if (!window.indexedDB) {
            console.error("IndexedDB is not supported.");
            resolve(null);
            return;
        }

        const request = indexedDB.open(DB_NAME, 1);

        request.onupgradeneeded = (event) => {
            const db = event.target.result;

            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME);
            }
        };

        request.onsuccess = (event) => {
            resolve(event.target.result);
        };

        request.onerror = () => {
            console.error("IndexedDB open failed:", request.error);
            resolve(null);
        };
    });
}


// ======================================================
// SAVE REAL PDF FILE
// ======================================================

async function savePdfFile(file) {
    if (!file) {
        return false;
    }

    try {
        // Save metadata
        localStorage.setItem("fileName", file.name);
        localStorage.setItem("fileSize", String(file.size));
        localStorage.setItem(
            "fileType",
            file.type || "application/pdf"
        );
        localStorage.setItem(
            "fileLastModified",
            String(file.lastModified)
        );

        const db = await openPdfDB();

        if (!db) {
            return false;
        }

        return await new Promise((resolve) => {
            const transaction = db.transaction(
                STORE_NAME,
                "readwrite"
            );

            const store = transaction.objectStore(
                STORE_NAME
            );

            const request = store.put(
                file,
                "currentPdf"
            );

            request.onerror = () => {
                console.error(
                    "PDF IndexedDB save failed:",
                    request.error
                );
            };

            transaction.oncomplete = () => {
                console.log(
                    "REAL PDF successfully saved:",
                    file.name
                );

                resolve(true);
            };

            transaction.onerror = () => {
                console.error(
                    "PDF IndexedDB transaction failed:",
                    transaction.error
                );

                resolve(false);
            };

            transaction.onabort = () => {
                console.error(
                    "PDF IndexedDB transaction aborted."
                );

                resolve(false);
            };
        });

    } catch (error) {
        console.error(
            "Error saving PDF:",
            error
        );

        return false;
    }
}


// ======================================================
// GET SAVED PDF
// ======================================================

async function getSavedPdfFile() {
    try {
        const db = await openPdfDB();

        if (!db) {
            return null;
        }

        return await new Promise((resolve) => {
            const transaction = db.transaction(
                STORE_NAME,
                "readonly"
            );

            const store = transaction.objectStore(
                STORE_NAME
            );

            const request = store.get(
                "currentPdf"
            );

            request.onsuccess = () => {
                const file = request.result || null;

                console.log(
                    "PDF retrieved from IndexedDB:",
                    file
                );

                resolve(file);
            };

            request.onerror = () => {
                console.error(
                    "PDF retrieval failed:",
                    request.error
                );

                resolve(null);
            };
        });

    } catch (error) {
        console.error(
            "Could not retrieve PDF:",
            error
        );

        return null;
    }
}


// ======================================================
// CLEAR SAVED PDF
// ======================================================

async function clearSavedPdfFile() {
    try {
        const db = await openPdfDB();

        if (!db) {
            return;
        }

        await new Promise((resolve) => {
            const transaction = db.transaction(
                STORE_NAME,
                "readwrite"
            );

            const store = transaction.objectStore(
                STORE_NAME
            );

            store.delete("currentPdf");

            transaction.oncomplete = () => {
                resolve();
            };

            transaction.onerror = () => {
                console.warn(
                    "Could not clear saved PDF:",
                    transaction.error
                );

                resolve();
            };
        });

    } catch (error) {
        console.warn(
            "Error clearing PDF:",
            error
        );
    }
}


// ======================================================
// REAL PDF BACKEND UPLOAD
// ======================================================

const API_BASE_URL =
    window.location.protocol === "file:"
        ? "http://127.0.0.1:8000"
        : "";
const API_PATH_PREFIX =
    window.location.protocol === "file:"
        ? ""
        : "/api";

async function uploadPdfToBackend(file) {
    if (!file) {
        console.error(
            "No PDF File object provided."
        );

        return null;
    }

    try {
        const formData = new FormData();

        formData.append(
            "file",
            file,
            file.name
        );

        console.log(
            "Uploading REAL PDF:",
            file.name,
            file.size,
            "bytes"
        );

        const response = await fetch(
            `${API_BASE_URL}${API_PATH_PREFIX}/upload-pdf`,
            {
                method: "POST",
                body: formData
            }
        );

        if (!response.ok) {
            console.error(
                "PDF backend upload failed:",
                response.status,
                response.statusText
            );

            return null;
        }

        const data = await response.json();

        console.log(
            "PDF backend upload response:",
            data
        );

        if (
            data &&
            data.file_path
        ) {
            localStorage.setItem(
                "backendFilePath",
                data.file_path
            );
        }

        return data;

    } catch (error) {
        console.error(
            "PDF upload request failed:",
            error
        );

        return null;
    }
}


// ======================================================
// PDF UPLOAD PAGE - home.html
// ======================================================

const choosePdfBtn =
    document.getElementById("choosePdfBtn");

const pdfFile =
    document.getElementById("pdfFile");

const fileName =
    document.getElementById("fileName");

const pageCount =
    document.getElementById("pageCount");

const continueBtn =
    document.getElementById("continueBtn");

const pdfErrorMsg =
    document.getElementById("pdfErrorMsg");


// ======================================================
// PDF ERROR MESSAGE
// ======================================================

function showPdfError(message) {
    if (!pdfErrorMsg) {
        return;
    }

    pdfErrorMsg.textContent =
        message ||
        "📄 Please select a PDF file first";

    pdfErrorMsg.style.display =
        "block";
}


function hidePdfError() {
    if (!pdfErrorMsg) {
        return;
    }

    pdfErrorMsg.style.display =
        "none";
}


// ======================================================
// RESTORE FILENAME
// ======================================================

if (fileName) {
    const savedName =
        localStorage.getItem("fileName");

    if (
        savedName &&
        savedName !== "No PDF Selected" &&
        savedName !== "No file selected"
    ) {
        fileName.textContent =
            savedName;
    }
}


// ======================================================
// FILE SELECTION
// ======================================================

window.handleFileSelection =
    async function (event) {

        const input =
            document.getElementById(
                "pdfFile"
            );

        const selectedFile =
            (
                event &&
                event.target &&
                event.target.files &&
                event.target.files[0]
            ) ||
            (
                input &&
                input.files &&
                input.files[0]
            );

        const nameDisplay =
            document.getElementById(
                "fileName"
            );

        // User cancelled picker
        if (!selectedFile) {
            return;
        }

        console.log(
            "REAL PDF selected:",
            selectedFile
        );

        console.log(
            "PDF name:",
            selectedFile.name
        );

        console.log(
            "PDF type:",
            selectedFile.type
        );

        console.log(
            "PDF size:",
            selectedFile.size
        );


        // ==================================================
        // PDF VALIDATION
        // ==================================================

        const isPdf =
            selectedFile.type ===
                "application/pdf" ||
            selectedFile.name
                .toLowerCase()
                .endsWith(".pdf");

        if (!isPdf) {

            if (input) {
                input.value = "";
            }

            window.selectedPdfFile =
                null;

            if (nameDisplay) {
                nameDisplay.textContent =
                    "No PDF Selected";
            }

            showPdfError(
                "📄 Please select a valid PDF file (.pdf)"
            );

            return;
        }


        // ==================================================
        // STORE REAL FILE IN MEMORY
        // ==================================================

        window.selectedPdfFile =
            selectedFile;


        // ==================================================
        // SHOW REAL FILE NAME
        // ==================================================

        if (nameDisplay) {
            nameDisplay.textContent =
                selectedFile.name;
        }

        hidePdfError();


        // ==================================================
        // SAVE REAL FILE TO INDEXEDDB
        // ==================================================

        const saved =
            await savePdfFile(
                selectedFile
            );

        if (!saved) {
            console.error(
                "PDF could not be saved."
            );

            showPdfError(
                "📄 Could not save PDF. Please try again."
            );

            return;
        }

        console.log(
            "PDF selection and persistence completed."
        );
    };


// ======================================================
// CHOOSE PDF BUTTON
// ======================================================

if (
    choosePdfBtn &&
    pdfFile
) {

    choosePdfBtn.addEventListener(
        "click",
        function (event) {

            event.preventDefault();

            try {

                // Allow selecting the same PDF again
                pdfFile.value = "";

                pdfFile.click();

            } catch (error) {

                console.error(
                    "Could not open PDF picker:",
                    error
                );
            }
        }
    );


    // File picker change event
    pdfFile.addEventListener(
        "change",
        function (event) {
            window.handleFileSelection(
                event
            );
        }
    );
}


// ======================================================
// CONTINUE BUTTON
// ======================================================

if (continueBtn) {

    continueBtn.addEventListener(
        "click",
        async function (event) {

            event.preventDefault();


            // ==================================================
            // GET REAL PDF
            // ==================================================

            const input =
                document.getElementById(
                    "pdfFile"
                );

            let selectedFile =
                window.selectedPdfFile ||
                (
                    input &&
                    input.files &&
                    input.files[0]
                );


            // If not available in memory,
            // try IndexedDB
            if (!selectedFile) {

                selectedFile =
                    await getSavedPdfFile();
            }


            console.log(
                "PDF available before Continue:",
                selectedFile
            );


            // ==================================================
            // NO PDF
            // ==================================================

            if (!selectedFile) {

                showPdfError(
                    "📄 Please select a PDF file first"
                );

                return;
            }


            // ==================================================
            // HIDE ERROR
            // ==================================================

            hidePdfError();


            // ==================================================
            // DISABLE BUTTON WHILE PROCESSING
            // ==================================================

            const originalText =
                continueBtn.textContent;

            continueBtn.disabled =
                true;

            continueBtn.textContent =
                "Uploading PDF...";


            try {

                // ==================================================
                // STEP 1
                // MAKE SURE REAL FILE IS SAVED
                // ==================================================

                const saved =
                    await savePdfFile(
                        selectedFile
                    );

                if (!saved) {

                    throw new Error(
                        "Could not save PDF to IndexedDB."
                    );
                }


                // ==================================================
                // STEP 2
                // REAL BACKEND UPLOAD
                // ==================================================

                const uploadResult =
                    await uploadPdfToBackend(
                        selectedFile
                    );


                // ==================================================
                // STEP 3
                // DO NOT REDIRECT IF UPLOAD FAILED
                // ==================================================

                if (!uploadResult) {

                    throw new Error(
                        "PDF backend upload failed."
                    );
                }


                console.log(
                    "REAL PDF upload completed successfully."
                );


                // ==================================================
                // STEP 4
                // ONLY NOW GO TO PRINT DETAILS
                // ==================================================

                window.location.href =
                    "print-details.html";

            } catch (error) {

                console.error(
                    "PDF flow failed:",
                    error
                );

                showPdfError(
                    "📄 PDF upload failed. Please try again."
                );

            } finally {

                continueBtn.disabled =
                    false;

                continueBtn.textContent =
                    originalText;
            }
        }
    );
}


// ======================================================
// PRINT DETAILS PAGE
// ======================================================

const backBtn =
    document.getElementById(
        "backBtn"
    );

const paymentBtn =
    document.getElementById(
        "paymentBtn"
    );

const copiesBox =
    document.getElementById(
        "copies"
    );

const totalPriceBox =
    document.getElementById(
        "totalPrice"
    );

const printDetailsFileName =
    document.getElementById(
        "fileName"
    );


// ======================================================
// RESTORE FILE ON PRINT DETAILS
// ======================================================

if (printDetailsFileName) {

    const savedName =
        localStorage.getItem(
            "fileName"
        );

    if (savedName) {

        printDetailsFileName.textContent =
            savedName;
    }


    getSavedPdfFile()
        .then(
            (selectedFile) => {

                console.log(
                    "REAL PDF available on Print Details:",
                    selectedFile
                );

                if (selectedFile) {

                    window.selectedPdfFile =
                        selectedFile;
                }
            }
        );
}


// ======================================================
// BACK BUTTON
// ======================================================

if (backBtn) {

    backBtn.addEventListener(
        "click",
        function (event) {

            event.preventDefault();

            window.location.href =
                "home.html";
        }
    );
}


// ======================================================
// PRINT DETAILS TOTAL
// ======================================================

if (
    copiesBox &&
    totalPriceBox
) {

    function updateTotalPrice() {

        const copies =
            Number(
                copiesBox.value
            ) || 1;

        const pricePerCopy =
            2;

        totalPriceBox.textContent =
            "Total: ₹" +
            (
                copies *
                pricePerCopy
            );
    }


    copiesBox.addEventListener(
        "input",
        updateTotalPrice
    );

    updateTotalPrice();
}


// ======================================================
// CONTINUE TO PAYMENT
// ======================================================

if (paymentBtn) {

    paymentBtn.addEventListener(
        "click",
        function (event) {

            event.preventDefault();

            const copies =
                copiesBox
                    ? copiesBox.value
                    : 1;

            const amount =
                Number(copies) * 2;


            localStorage.setItem(
                "copies",
                copies
            );

            localStorage.setItem(
                "amount",
                amount
            );


            const selectedSide =
                document.querySelector(
                    'input[name="printSide"]:checked'
                );

            if (selectedSide) {

                localStorage.setItem(
                    "printSide",
                    selectedSide.value
                );
            }


            const selectedOrientation =
                document.querySelector(
                    'input[name="orientation"]:checked'
                );

            if (selectedOrientation) {

                localStorage.setItem(
                    "orientation",
                    selectedOrientation.value
                );
            }


            window.location.href =
                "payment.html";
        }
    );
}


// ======================================================
// PAYMENT PAGE
// ======================================================

const paymentFile =
    document.getElementById(
        "paymentFile"
    );

const paymentCopies =
    document.getElementById(
        "paymentCopies"
    );

const paymentAmount =
    document.getElementById(
        "paymentAmount"
    );

const paymentSide =
    document.getElementById(
        "paymentSide"
    );

const paymentOrientation =
    document.getElementById(
        "paymentOrientation"
    );

const payBtn =
    document.getElementById(
        "payBtn"
    );

const paymentBackBtn =
    document.getElementById(
        "paymentBackBtn"
    );


// ======================================================
// RESTORE PAYMENT DETAILS
// ======================================================

if (
    paymentFile &&
    paymentCopies &&
    paymentAmount
) {

    const fileNameVal =
        localStorage.getItem(
            "fileName"
        ) ||
        "No file selected";

    const copiesVal =
        localStorage.getItem(
            "copies"
        ) ||
        "1";

    const amountVal =
        localStorage.getItem(
            "amount"
        ) ||
        "0";

    const printSideVal =
        localStorage.getItem(
            "printSide"
        ) ||
        "single";

    const orientationVal =
        localStorage.getItem(
            "orientation"
        ) ||
        "portrait";


    paymentFile.textContent =
        "File: " +
        fileNameVal;

    paymentCopies.textContent =
        "Copies: " +
        copiesVal;

    paymentAmount.textContent =
        "Total Amount: ₹" +
        amountVal;


    if (paymentSide) {

        paymentSide.textContent =
            "Print Side: " +
            (
                printSideVal === "double"
                    ? "Double Side"
                    : "Single Side"
            );
    }


    if (paymentOrientation) {

        paymentOrientation.textContent =
            "Orientation: " +
            (
                orientationVal === "landscape"
                    ? "Landscape"
                    : "Portrait"
            );
    }


    getSavedPdfFile()
        .then(
            (selectedFile) => {

                console.log(
                    "REAL PDF available on Payment:",
                    selectedFile
                );

                if (selectedFile) {

                    window.selectedPdfFile =
                        selectedFile;
                }
            }
        );
}


// ======================================================
// PAYMENT BACK
// ======================================================

if (paymentBackBtn) {

    paymentBackBtn.addEventListener(
        "click",
        function (event) {

            event.preventDefault();

            window.location.href =
                "print-details.html";
        }
    );
}


// ======================================================
// PAYMENT
// ======================================================

if (payBtn) {

    payBtn.addEventListener(
        "click",
        async function (event) {

            event.preventDefault();


            // Get REAL PDF
            const selectedFile =
                window.selectedPdfFile ||
                await getSavedPdfFile();


            console.log(
                "REAL PDF before final payment upload:",
                selectedFile
            );


            // Upload REAL PDF if available
            if (selectedFile) {

                await uploadPdfToBackend(
                    selectedFile
                );
            }


            // ==================================================
            // PRINT ORDER DATA
            // ==================================================

            const fileNameVal =
                localStorage.getItem(
                    "fileName"
                ) ||
                "document.pdf";

            const copiesVal =
                parseInt(
                    localStorage.getItem(
                        "copies"
                    ) ||
                    "1",
                    10
                );

            const printSideVal =
                localStorage.getItem(
                    "printSide"
                ) ||
                "double";

            const orientationVal =
                localStorage.getItem(
                    "orientation"
                ) ||
                "portrait";


            // ==================================================
            // SEND PRINT ORDER
            // ==================================================

            fetch(
                `${API_BASE_URL}${API_PATH_PREFIX}/print-order`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        file_name:
                            fileNameVal,

                        copies:
                            copiesVal,

                        color_mode:
                            "black_white",

                        duplex:
                            printSideVal,

                        orientation:
                            orientationVal
                    })
                }
            )
                .then(
                    (response) =>
                        response.json()
                )
                .then(
                    (data) => {

                        console.log(
                            "Print order placed successfully:",
                            data
                        );
                    }
                )
                .catch(
                    (error) => {

                        console.warn(
                            "Backend print order note:",
                            error
                        );
                    }
                );


            window.location.href =
                "success.html";
        }
    );
}


// ======================================================
// SUCCESS PAGE
// ======================================================

const homeBtn =
    document.getElementById(
        "homeBtn"
    );


if (homeBtn) {

    homeBtn.addEventListener(
        "click",
        async function (event) {

            event.preventDefault();


            // Clear order metadata
            localStorage.removeItem(
                "fileName"
            );

            localStorage.removeItem(
                "fileSize"
            );

            localStorage.removeItem(
                "fileType"
            );

            localStorage.removeItem(
                "fileLastModified"
            );

            localStorage.removeItem(
                "backendFilePath"
            );

            localStorage.removeItem(
                "copies"
            );

            localStorage.removeItem(
                "amount"
            );

            localStorage.removeItem(
                "printSide"
            );

            localStorage.removeItem(
                "orientation"
            );


            sessionStorage.removeItem(
                "pdfDataUrl"
            );


            // Clear REAL PDF
            await clearSavedPdfFile();


            // Return home
            window.location.href =
                "home.html";
        }
    );
}