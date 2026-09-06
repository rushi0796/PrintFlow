const mobileForm = document.getElementById("mobileForm");
const otpForm = document.getElementById("otpForm");
const mobileNumberInput = document.getElementById("mobileNumber") || document.getElementById("phone");
const sendOtpBtn = document.getElementById("sendOtpBtn");
const sendOtpSuccessMsg = document.getElementById("sendOtpSuccessMsg");
const otpSection = document.getElementById("otpSection");
const otpBoxContainer = document.getElementById("otpBoxContainer");
const otpBoxes = document.querySelectorAll(".otp-box");
const hiddenOtpInput = document.getElementById("otpInput") || document.getElementById("otp");
const verifyOtpBtn = document.getElementById("verifyOtpBtn");
const resendTimer = document.getElementById("resendTimer");
const resendBtn = document.getElementById("resendBtn");
const resendContainer = document.querySelector(".resend-container");
const resendSuccessMsg = document.getElementById("resendSuccessMsg");
const otpErrorMsg = document.getElementById("otpErrorMsg");

let countdownInterval = null;
let isSendingOtp = false;
let isOtpSent = false;
let isResendingOtp = false;
let isVerifyingOtp = false;

function isMsg91Ready() {
    return window.msg91Ready || (typeof window.sendOtp === "function");
}

function updateSendBtnState() {
    if (!sendOtpBtn) return;
    if (isOtpSent) {
        sendOtpBtn.disabled = true;
        sendOtpBtn.innerText = "OTP Sent";
        return;
    }
    if (isMsg91Ready()) {
        sendOtpBtn.disabled = false;
        if (sendOtpBtn.innerText === "Initializing OTP...") {
            sendOtpBtn.innerText = "Send OTP";
        }
    } else {
        sendOtpBtn.disabled = false;
    }
}

// Initial state check
updateSendBtnState();

// MSG91 Ready event listener
window.addEventListener("msg91-ready", updateSendBtnState);

// Poll briefly until ready
const readyTimer = setInterval(function () {
    if (isMsg91Ready()) {
        updateSendBtnState();
        clearInterval(readyTimer);
    }
}, 100);

function showOtpError(msg) {
    if (otpErrorMsg) {
        otpErrorMsg.textContent = msg || "Invalid OTP. Please try again.";
        otpErrorMsg.style.display = "block";
    }
}

function hideOtpError() {
    if (otpErrorMsg) {
        otpErrorMsg.style.display = "none";
    }
}

// Combine 4 individual boxes into hiddenOtpInput value
function syncOtpValue() {
    let combined = "";
    otpBoxes.forEach(box => {
        combined += box.value.trim();
    });
    if (hiddenOtpInput) {
        hiddenOtpInput.value = combined;
    }
    return combined;
}

// Dedicated Send OTP Handler
function handleSendOtp() {
    if (isSendingOtp || isOtpSent) return;
    hideOtpError();

    if (!mobileNumberInput) {
        alert("Please enter mobile number.");
        return;
    }

    const mobile = mobileNumberInput.value.trim();

    if (mobile.length !== 10 || !/^\d{10}$/.test(mobile)) {
        alert("Please enter a valid 10-digit mobile number.");
        return;
    }

    // If MSG91 SDK is initializing, wait briefly up to 3s
    if (!isMsg91Ready()) {
        console.log("MSG91 OTP service initializing, waiting for readiness...");
        let attempts = 0;
        const waitTimer = setInterval(function () {
            attempts++;
            if (isMsg91Ready()) {
                clearInterval(waitTimer);
                handleSendOtp();
            } else if (attempts > 30) {
                clearInterval(waitTimer);
                alert("MSG91 OTP service is taking longer than expected. Please try again.");
            }
        }, 100);
        return;
    }

    const identifier = "91" + mobile;

    console.log("MSG91 OTP request started for", identifier);
    isSendingOtp = true;
    if (sendOtpBtn) {
        sendOtpBtn.disabled = true;
        sendOtpBtn.innerText = "Sending...";
    }

    window.sendOtp(
        identifier,
        function (response) {
            console.log("MSG91 OTP request successful", response);
            isSendingOtp = false;
            isOtpSent = false;

            if (sendOtpBtn) {
                sendOtpBtn.disabled = false;
                sendOtpBtn.innerText = "Send OTP Again";
            }

            // Display inline success message below button
            if (sendOtpSuccessMsg) {
                sendOtpSuccessMsg.style.display = "block";
            }

            if (otpSection) otpSection.style.display = "block";
            if (otpBoxes && otpBoxes[0]) otpBoxes[0].focus();
            startResendCountdown();
        },
        function (error) {
            console.error("MSG91 OTP failed", error);
            isSendingOtp = false;
            isOtpSent = false;

            // On failure: restore button state so user can retry
            if (sendOtpBtn) {
                sendOtpBtn.disabled = false;
                sendOtpBtn.innerText = "Send OTP";
            }

            if (sendOtpSuccessMsg) {
                sendOtpSuccessMsg.style.display = "none";
            }

            let userMsg = "OTP request failed.";
            if (error && (error.code === "408" || error.message === "IPBlocked" || (Array.isArray(error) && error.includes("IPBlocked")))) {
                userMsg = "OTP service temporarily unavailable due to request limits (IP Blocked). Please try again later.";
            } else if (typeof error === "object") {
                userMsg = "OTP request failed: " + (error.message || JSON.stringify(error));
            } else if (error) {
                userMsg = "OTP request failed: " + error;
            }
            alert(userMsg);
        }
    );
}

// Dedicated Verify OTP Handler
function handleVerifyOtp() {
    if (isVerifyingOtp) return;
    hideOtpError();
    const otp = syncOtpValue();

    if (otp.length !== 4 || !/^\d{4}$/.test(otp)) {
        showOtpError("Enter 4-digit OTP");
        if (otpBoxContainer) {
            otpBoxContainer.classList.add("shake");
            setTimeout(() => otpBoxContainer.classList.remove("shake"), 400);
        }
        return;
    }

    if (typeof window.verifyOtp === "function") {
        console.log("MSG91 OTP verification started");
        isVerifyingOtp = true;
        if (verifyOtpBtn) {
            verifyOtpBtn.disabled = true;
            verifyOtpBtn.innerText = "Verifying...";
        }

        window.verifyOtp(
            otp,
            function (response) {
                console.log("MSG91 OTP verification successful", response);
                hideOtpError();

                if (resendContainer) resendContainer.style.display = "none";
                if (resendSuccessMsg) resendSuccessMsg.style.display = "none";
                if (verifyOtpBtn) verifyOtpBtn.style.display = "none";
                const otpSentText = document.querySelector(".otp-sent-text");
                if (otpSentText) otpSentText.style.display = "none";

                // Step 1: Morph OTP boxes into vibrant green circular dots (0 to 350ms)
                otpBoxes.forEach((box) => {
                    box.classList.remove("error");
                    box.classList.add("circle-morph");
                    box.readOnly = true;
                });

                // Step 2: Orbit rotation & convergence toward center (350ms to 750ms)
                setTimeout(() => {
                    otpBoxes.forEach((box, i) => {
                        box.classList.add(`circle-orbit-${i + 1}`);
                    });
                }, 350);

                // Step 3: Merge into glowing green success badge with SVG checkmark & text (at 750ms)
                setTimeout(() => {
                    if (otpBoxContainer) {
                        otpBoxContainer.style.display = "none";
                    }

                    let badgeContainer = document.getElementById("successBadgeContainer");
                    if (!badgeContainer) {
                        badgeContainer = document.createElement("div");
                        badgeContainer.id = "successBadgeContainer";
                        if (otpSection) otpSection.appendChild(badgeContainer);
                    }
                    badgeContainer.innerHTML = `
                        <div class="merged-success-badge">
                            <svg class="checkmark-svg" viewBox="0 0 24 24">
                                <polyline points="20 6 9 17 4 12"></polyline>
                            </svg>
                        </div>
                        <div class="success-text-anim">
                            ✓ OTP Verified
                        </div>
                    `;
                }, 750);

                // Step 4: Wait until animation completes (1800ms total visible duration), then navigate to home.html
                setTimeout(() => {
                    const mobileVal = (mobileNumberInput ? mobileNumberInput.value.trim() : "") || localStorage.getItem("mobileNumber") || "";
                    if (mobileVal) {
                        localStorage.setItem("mobileNumber", mobileVal);
                    }
                    if (window.clearUserDocumentSession) {
                        window.clearUserDocumentSession();
                    } else {
                        ["fileName", "uploadedFileName", "backendFilePath", "pdfPageCount", "copies", "amount", "pdfDataUrl"].forEach(k => localStorage.removeItem(k));
                    }
                    window.location.href = "home.html";
                }, 1800);
            },
            function (error) {
                console.error("MSG91 OTP verification failed", error);
                isVerifyingOtp = false;
                if (verifyOtpBtn) {
                    verifyOtpBtn.disabled = false;
                    verifyOtpBtn.innerText = "Verify OTP";
                }

                if (otpBoxContainer) {
                    otpBoxContainer.classList.add("shake");
                    setTimeout(() => otpBoxContainer.classList.remove("shake"), 400);
                }

                otpBoxes.forEach(box => {
                    box.classList.add("error");
                });

                showOtpError("Invalid OTP. Please try again.");
            }
        );
    } else {
        console.error("MSG91 OTP verification failed: window.verifyOtp is not defined");
        showOtpError("OTP verification service is not ready.");
    }
}

// Dedicated Resend OTP Handler
function handleResendOtp() {
    if (isResendingOtp) return;
    const mobile = mobileNumberInput ? mobileNumberInput.value.trim() : "";
    if (mobile.length !== 10) {
        alert("Please enter a valid 10-digit mobile number.");
        return;
    }

    hideOtpError();
    if (resendSuccessMsg) resendSuccessMsg.style.display = "none";

    isResendingOtp = true;
    if (resendBtn) resendBtn.disabled = true;

    function onResendSuccess(response) {
        console.log("MSG91 OTP resend successful", response);
        isResendingOtp = false;
        if (resendSuccessMsg) {
            resendSuccessMsg.textContent = "✓ OTP resent successfully";
            resendSuccessMsg.style.display = "block";
        }
        startResendCountdown();
    }

    function onResendFailure(error) {
        console.error("MSG91 OTP resend failed", error);
        isResendingOtp = false;
        if (resendBtn) resendBtn.disabled = false;
        const msg = typeof error === "object" ? (error.message || JSON.stringify(error)) : error;
        showOtpError("Resend failed: " + msg);
    }

    if (typeof window.retryOtp === "function") {
        window.retryOtp(null, onResendSuccess, onResendFailure);
    } else if (typeof window.sendOtp === "function") {
        window.sendOtp("91" + mobile, onResendSuccess, onResendFailure);
    } else {
        isResendingOtp = false;
        if (resendBtn) resendBtn.disabled = false;
        showOtpError("MSG91 OTP resend service is not ready.");
    }
}

// Event Listeners for Buttons & Forms
if (sendOtpBtn) {
    sendOtpBtn.addEventListener("click", function (e) {
        e.preventDefault();
        handleSendOtp();
    });
}

if (mobileForm) {
    mobileForm.addEventListener("submit", function (e) {
        e.preventDefault();
        handleSendOtp();
    });
}

if (verifyOtpBtn) {
    verifyOtpBtn.addEventListener("click", function (e) {
        e.preventDefault();
        handleVerifyOtp();
    });
}

if (otpForm) {
    otpForm.addEventListener("submit", function (e) {
        e.preventDefault();
        handleVerifyOtp();
    });
}

// Setup 4 OTP Boxes Navigation & Auto-focus
if (otpBoxes && otpBoxes.length > 0) {
    otpBoxes.forEach((box, index) => {
        box.addEventListener("input", function (e) {
            const value = this.value.replace(/[^0-9]/g, "");
            this.value = value;

            hideOtpError();
            box.classList.remove("error", "circle-morph");

            if (value && index < otpBoxes.length - 1) {
                otpBoxes[index + 1].focus();
            }

            syncOtpValue();
        });

        box.addEventListener("keydown", function (e) {
            if (e.key === "Enter" || e.keyCode === 13) {
                e.preventDefault();
                handleVerifyOtp();
            } else if (e.key === "Backspace") {
                hideOtpError();
                if (!this.value && index > 0) {
                    otpBoxes[index - 1].focus();
                    otpBoxes[index - 1].value = "";
                    syncOtpValue();
                }
            } else if (e.key === "ArrowLeft" && index > 0) {
                otpBoxes[index - 1].focus();
            } else if (e.key === "ArrowRight" && index < otpBoxes.length - 1) {
                otpBoxes[index + 1].focus();
            }
        });

        box.addEventListener("paste", function (e) {
            e.preventDefault();
            hideOtpError();
            const pastedData = (e.clipboardData || window.clipboardData).getData("text").replace(/[^0-9]/g, "");
            if (pastedData) {
                const digits = pastedData.substring(0, 4).split("");
                digits.forEach((digit, i) => {
                    if (otpBoxes[i]) {
                        otpBoxes[i].value = digit;
                        otpBoxes[i].classList.remove("error", "circle-morph");
                    }
                });
                const lastIndex = Math.min(digits.length - 1, otpBoxes.length - 1);
                if (otpBoxes[lastIndex]) {
                    otpBoxes[lastIndex].focus();
                }
                syncOtpValue();
            }
        });
    });
}

if (mobileNumberInput) {
    mobileNumberInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.keyCode === 13) {
            e.preventDefault();
            handleSendOtp();
        }
    });
}

// Resend Countdown Timer (30s)
function startResendCountdown() {
    if (!resendTimer || !resendBtn) return;
    let timeLeft = 30;
    resendBtn.style.display = "none";
    resendBtn.disabled = true;
    resendTimer.style.display = "inline";
    resendTimer.textContent = `Resend OTP in ${timeLeft}s`;

    if (countdownInterval) clearInterval(countdownInterval);

    countdownInterval = setInterval(() => {
        timeLeft -= 1;
        if (timeLeft <= 0) {
            clearInterval(countdownInterval);
            resendTimer.style.display = "none";
            resendBtn.style.display = "inline-block";
            resendBtn.disabled = false;
        } else {
            resendTimer.textContent = `Resend OTP in ${timeLeft}s`;
        }
    }, 1000);
}

// Resend OTP Action Listener
if (resendBtn) {
    resendBtn.addEventListener("click", function (e) {
        e.preventDefault();
        handleResendOtp();
    });
}
