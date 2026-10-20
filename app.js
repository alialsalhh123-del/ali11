const API_URL = 'api.php';

let currentPendingPhone = '';
let targetPhoneToDelete = '';

function notify(text, type = 'info') {
    const box = document.getElementById('toast-zone');
    if (!box) return;

    const toast = document.createElement('div');
    toast.className = `toast-msg toast-${type}`;
    
    let icon = 'fa-info-circle';
    if (type === 'success') icon = 'fa-check-circle';
    if (type === 'error') icon = 'fa-circle-exclamation';
    if (type === 'warning') icon = 'fa-triangle-exclamation';

    toast.innerHTML = `<i class="fas ${icon}"></i> <span>${text}</span>`;
    box.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(-10px)';
        toast.style.transition = '0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 4500);
}

function setBtnLoading(btn, isLoading, label = 'جارٍ المعالجة...') {
    if (!btn) return;
    if (isLoading) {
        btn.disabled = true;
        btn.dataset.original = btn.innerHTML;
        btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> <span>${label}</span>`;
    } else {
        btn.disabled = false;
        if (btn.dataset.original) btn.innerHTML = btn.dataset.original;
    }
}

function switchToCodeStep(phone) {
    currentPendingPhone = phone;
    const phoneStep = document.getElementById('phoneStep');
    const codeStep = document.getElementById('codeStep');
    const inventoryCard = document.getElementById('inventoryCard');
    const phoneDisplay = document.getElementById('currentPhoneDisplay');
    const codeInput = document.getElementById('codeInput');

    if (phoneDisplay) phoneDisplay.textContent = phone;

    phoneStep.classList.add('step-hidden');
    if (inventoryCard) inventoryCard.classList.add('step-hidden');
    codeStep.classList.remove('step-hidden');

    if (codeInput) {
        codeInput.value = '';
        setTimeout(() => codeInput.focus(), 250);
    }
}

function switchToPhoneStep() {
    const phoneStep = document.getElementById('phoneStep');
    const codeStep = document.getElementById('codeStep');
    const inventoryCard = document.getElementById('inventoryCard');
    const codeInput = document.getElementById('codeInput');

    if (codeInput) codeInput.value = '';
    currentPendingPhone = '';

    codeStep.classList.add('step-hidden');
    phoneStep.classList.remove('step-hidden');
    if (inventoryCard) inventoryCard.classList.remove('step-hidden');

    const phoneInput = document.getElementById('phoneInput');
    if (phoneInput) phoneInput.focus();
}

// 1. طلب الكود
async function requestCode(forceSms = 0, event) {
    const phoneInput = document.getElementById('phoneInput');
    const phone = phoneInput.value.trim();

    if (!phone) {
        notify("يرجى كتابة رقم الهاتف مع الرمز الدولي", "error");
        return;
    }

    const btn = event.currentTarget;
    setBtnLoading(btn, true, forceSms ? "إجبار SMS..." : "طلب الكود...");
    
    if (forceSms) {
        notify("جاري طلب الكود برسالة نصية قصيرة (SMS)...", "info");
    } else {
        notify("جاري طلب كود التحقق...", "info");
    }

    try {
        const res = await fetch(`${API_URL}?action=request_code&phone=${encodeURIComponent(phone)}&force_sms=${forceSms}`);
        const data = await res.json();

        let parsed = data;
        if (typeof data.output === 'string') {
            try { parsed = JSON.parse(data.output); } catch(e) {}
        }

        const status = parsed.status || "error";
        const channel = parsed.channel || "unknown";
        const message = parsed.message || data.output || "تم إرسال الطلب";

        if (status === "success") {
            if (channel === "sms") {
                notify(message, "success");
            } else if (channel === "app") {
                notify(message, "warning");
            } else {
                notify(message, "success");
            }
            switchToCodeStep(phone);
        } else {
            notify(message, "error");
        }
        loadNumbers();
    } catch (e) {
        notify("تعذر الاتصال بالخادم: " + e.message, "error");
    } finally {
        setBtnLoading(btn, false);
    }
}

// 2. التحقق من الكود وحفظ الجلسة بالتسمية التلقائية
async function verifyCode(event) {
    const codeInput = document.getElementById('codeInput');
    const code = codeInput.value.trim();
    const phone = currentPendingPhone;

    if (!phone) {
        notify("لا يوجد رقم هاتف محدد للتحقق!", "error");
        switchToPhoneStep();
        return;
    }

    if (!code) {
        notify("يرجى إدخال رمز التحقق", "error");
        codeInput.focus();
        return;
    }

    const btn = event.currentTarget;
    setBtnLoading(btn, true, "جارٍ التثبيت...");
    notify("جاري التحقق من الرمز وتثبيت الجلسة...", "info");

    try {
        const res = await fetch(`${API_URL}?action=verify_code&phone=${encodeURIComponent(phone)}&code=${encodeURIComponent(code)}`);
        const data = await res.json();

        if (data.status === 'success' || (data.output && data.output.includes("بنجاح"))) {
            notify(data.output || "تم تأكيد الجلسة بنجاح!", "success");
            document.getElementById('phoneInput').value = '';
            switchToPhoneStep();
        } else {
            notify(data.output || "فشل التحقق من الكود", "error");
        }
        loadNumbers();
    } catch (e) {
        notify("خطأ أثناء الاتصال: " + e.message, "error");
    } finally {
        setBtnLoading(btn, false);
    }
}

// 3. عرض الجلسات في المخزون
async function loadNumbers() {
    try {
        const res = await fetch(`${API_URL}?action=list_numbers`);
        const data = await res.json();

        const countBadge = document.getElementById('activeStockCount');
        const listContainer = document.getElementById('numbersList');

        if (listContainer) listContainer.innerHTML = '';

        if (Array.isArray(data) && data.length > 0) {
            if (countBadge) countBadge.textContent = data.length;

            data.forEach((item, idx) => {
                if (listContainer) {
                    const row = document.createElement('div');
                    row.className = 'record-card';
                    row.style.display = 'flex';
                    row.style.justifyContent = 'space-between';
                    row.style.alignItems = 'center';
                    row.style.padding = '14px 18px';

                    const sName = item.session_name || `السفاح الشمالي ${idx + 1}`;
                    const phoneId = item.phone.replace(/\D/g, '');
                    const currentHealth = item.health_status || 'clean';

                    let badgeClass = 'clean';
                    let badgeIcon = 'fa-shield-halved';
                    let badgeText = 'سليمة';

                    if (currentHealth === 'spam') {
                        badgeClass = 'spam';
                        badgeIcon = 'fa-triangle-exclamation';
                        badgeText = 'سبام';
                    } else if (currentHealth === 'dead') {
                        badgeClass = 'dead';
                        badgeIcon = 'fa-ban';
                        badgeText = 'معطلة';
                    }

                    row.innerHTML = `
                        <div class="record-phone" style="cursor: pointer; display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; text-align: right; gap: 8px;" title="انقر لسحب الكود">
                            <div style="display: flex; align-items: center; justify-content: flex-start; gap: 8px;">
                                <span style="font-size: 11.5px; color: #c084fc; font-weight: 800; background: rgba(139, 92, 246, 0.18); border: 1px solid rgba(139, 92, 246, 0.4); padding: 2px 8px; border-radius: 6px;">
                                    <i class="fas fa-crown"></i> ${sName}
                                </span>

                                <span id="health-${phoneId}" class="health-badge ${badgeClass}">
                                    <i class="fas ${badgeIcon}"></i> <span>${badgeText}</span>
                                </span>

                                <button class="btn-mini-check" onclick="checkSingleHealth('${item.phone}', event)" title="فحص ومزامنة الحالة">
                                    <i class="fas fa-arrows-rotate"></i>
                                </button>
                            </div>

                            <div style="display: flex; align-items: center; justify-content: flex-start; gap: 8px; width: 100%;">
                                <i class="fas fa-sim-card" style="color: #38bdf8; font-size: 14px;"></i>
                                <span dir="ltr" style="font-weight: 900; font-size: 16px; letter-spacing: 0.5px; color: #ffffff;">
                                    ${item.phone}
                                </span>
                            </div>
                        </div>

                        <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
                            <span class="badge-status ready" style="cursor: pointer; white-space: nowrap;">
                                <i class="fas fa-bolt"></i> جاهز للسحب
                            </span>
                            <button class="btn-delete-session" onclick="triggerDeleteModal('${item.phone}', event)" title="إنهاء الجلسة وتسجيل الخروج" style="white-space: nowrap;">
                                <i class="fas fa-trash-can"></i> إنهاء وحذف
                            </button>
                        </div>
                    `;

                    row.querySelector('.record-phone').addEventListener('click', () => {
                        window.location.href = `sessions.html?phone=${encodeURIComponent(item.phone)}`;
                    });
                    row.querySelector('.badge-status').addEventListener('click', () => {
                        window.location.href = `sessions.html?phone=${encodeURIComponent(item.phone)}`;
                    });

                    listContainer.appendChild(row);
                }
            });
        } else if (listContainer) {
            listContainer.innerHTML = `<div style="text-align: center; color: var(--text-sub); padding: 12px; font-size: 13px;">لا توجد جلسات جاهزة بالمخزون حالياً</div>`;
            if (countBadge) countBadge.textContent = '0';
        }
    } catch (e) {
        console.error("فشل جلب الأرقام:", e);
    }
}

// 4. فحص الجلسة مع بقاء النتيجة محفوظة في قاعدة البيانات
async function checkSingleHealth(phone, event) {
    if (event) event.stopPropagation();
    const phoneId = phone.replace(/\D/g, '');
    const badge = document.getElementById(`health-${phoneId}`);
    if (badge) {
        badge.className = "health-badge";
        badge.innerHTML = `<i class="fas fa-spinner fa-spin"></i> <span>فحص...</span>`;
    }

    try {
        const res = await fetch(`${API_URL}?action=check_health&phone=${encodeURIComponent(phone)}`);
        const data = await res.json();
        
        if (badge) {
            if (data.status === 'clean') {
                badge.className = "health-badge clean";
                badge.innerHTML = `<i class="fas fa-shield-halved"></i> <span>سليمة</span>`;
            } else if (data.status === 'spam') {
                badge.className = "health-badge spam";
                badge.innerHTML = `<i class="fas fa-triangle-exclamation"></i> <span>سبام</span>`;
            } else {
                badge.className = "health-badge dead";
                badge.innerHTML = `<i class="fas fa-ban"></i> <span>معطلة</span>`;
            }
        }

        notify(`[${phone}] ${data.label}: ${data.message}`, data.status === 'clean' ? 'success' : 'warning');
    } catch (e) {
        if (badge) badge.innerHTML = `<span>خطأ</span>`;
    }
}

// نافذة حذف الجلسة
function triggerDeleteModal(phone, event) {
    if (event) event.stopPropagation();
    targetPhoneToDelete = phone;
    const modal = document.getElementById('confirmModal');
    const input = document.getElementById('confirmInputText');
    if (input) {
        input.value = '';
        setTimeout(() => input.focus(), 200);
    }
    if (modal) modal.classList.add('active');
}

function closeDeleteModal() {
    targetPhoneToDelete = '';
    const modal = document.getElementById('confirmModal');
    if (modal) modal.classList.remove('active');
}

async function executeDeleteSession() {
    const input = document.getElementById('confirmInputText');
    if (!input || input.value.trim() !== 'تأكيد') {
        notify("يرجى كتابة كلمة (تأكيد) للمتابعة", "error");
        return;
    }

    const phone = targetPhoneToDelete;
    closeDeleteModal();
    notify("جاري إنهاء الجلسة وتسجيل الخروج...", "info");

    try {
        const res = await fetch(`${API_URL}?action=logout&phone=${encodeURIComponent(phone)}`);
        const data = await res.json();
        notify(data.message || "تم حذف الجلسة بنجاح", "success");
        loadNumbers();
    } catch (e) {
        notify("خطأ أثناء الحذف: " + e.message, "error");
    }
}

// 5. دوال النافذة التفاعلية للنسخ الاحتياطي (Backup System مع مؤشر التحميل الدوار)
function openBackupModal() {
    const modal = document.getElementById('backupModal');
    if (modal) modal.classList.add('active');
}

function closeBackupModal() {
    const modal = document.getElementById('backupModal');
    if (modal) modal.classList.remove('active');
}

// أ. تنزيل النسخة مباشرة إلى اللابتوب مع دوران الأيقونة
async function executeDownloadBackup(btn) {
    setBtnLoading(btn, true, "جاري الضغط والتنزيل...");
    notify("جاري تجهيز وضغط النسخة الاحتياطية وتنزيلها للابتوب...", "info");

    try {
        window.location.href = `${API_URL}?action=backup_download`;
        setTimeout(() => {
            setBtnLoading(btn, false);
            closeBackupModal();
            notify("بدأ تنزيل ملف النسخة الاحتياطية بنجاح!", "success");
        }, 1500);
    } catch (e) {
        setBtnLoading(btn, false);
        window.location.href = `${API_URL}?action=backup_download`;
        setTimeout(() => closeBackupModal(), 1500);
    }
}

// ب. إرسال النسخة عبر بوت تيليجرام مع دوران الأيقونة
async function executeTelegramBackup(btn) {
    setBtnLoading(btn, true, "جاري الإرسال لتيليجرام...");
    notify("جاري تجميع الملفات وقاعدة البيانات وإرسالها لبوت تيليجرام...", "info");

    try {
        const res = await fetch(`${API_URL}?action=backup_telegram`);
        const data = await res.json();

        if (data.status === 'success') {
            notify(data.message, "success");
            closeBackupModal();
        } else {
            notify(data.message || "فشل إرسال النسخة الاحتياطية", "error");
        }
    } catch (e) {
        notify("خطأ اتصال أثناء النسخ الاحتياطي: " + e.message, "error");
    } finally {
        setBtnLoading(btn, false);
    }
}

function initThemeToggle() {
    const themeBtn = document.getElementById('themeBtn');
    const themeIco = document.getElementById('themeIco');
    const headerAvatar = document.getElementById('headerAvatar');
    const html = document.documentElement;

    const savedTheme = localStorage.getItem('tg_theme') || 'dark';
    html.setAttribute('data-theme', savedTheme);
    updateThemeAssets(savedTheme);

    themeBtn.addEventListener('click', () => {
        const current = html.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';

        const rect = themeBtn.getBoundingClientRect();
        const x = rect.left + rect.width / 2;
        const y = rect.top + rect.height / 2;

        const circle = document.createElement('div');
        circle.className = 'theme-circle';
        circle.style.backgroundColor = next === 'light' ? '#f8fafc' : '#070d19';
        circle.style.clipPath = `circle(0px at ${x}px ${y}px)`;
        document.body.appendChild(circle);

        requestAnimationFrame(() => {
            circle.style.clipPath = `circle(150% at ${x}px ${y}px)`;
        });

        setTimeout(() => {
            html.setAttribute('data-theme', next);
            localStorage.setItem('tg_theme', next);
            updateThemeAssets(next);
            circle.remove();
        }, 500);
    });

    function updateThemeAssets(theme) {
        themeIco.className = theme === 'light' ? 'fas fa-moon' : 'fas fa-sun';
        if (headerAvatar) {
            headerAvatar.src = theme === 'light' ? 'bg3.jpg' : 'bg2.jpg';
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initThemeToggle();

    document.getElementById('btnRequestSms')?.addEventListener('click', (e) => requestCode(0, e));
    document.getElementById('btnForceSms')?.addEventListener('click', (e) => requestCode(1, e));
    document.getElementById('btnVerify')?.addEventListener('click', (e) => verifyCode(e));
    
    document.getElementById('btnCancelCode')?.addEventListener('click', () => {
        switchToPhoneStep();
        notify("تم إلغاء العملية والعودة", "info");
    });

    document.getElementById('btnCancelModal')?.addEventListener('click', closeDeleteModal);
    document.getElementById('btnConfirmDeleteAction')?.addEventListener('click', executeDeleteSession);
    
    // أحداث نظام النسخ الاحتياطي (ربط الأزرار لتفعيل علامة التحميل الدوارة)
    document.getElementById('btnOpenBackupModal')?.addEventListener('click', openBackupModal);
    document.getElementById('btnCloseBackupModal')?.addEventListener('click', closeBackupModal);
    document.getElementById('btnBackupDownload')?.addEventListener('click', function() {
        executeDownloadBackup(this);
    });
    document.getElementById('btnBackupTelegram')?.addEventListener('click', function() {
        executeTelegramBackup(this);
    });

    document.getElementById('btnRefresh')?.addEventListener('click', () => {
        loadNumbers();
        notify("تم تحديث المخزون", "info");
    });

    document.getElementById('btnResetFields')?.addEventListener('click', () => {
        document.getElementById('phoneInput').value = '';
        currentPendingPhone = '';
        notify("تم تفريغ الحقول", "info");
    });

    document.querySelectorAll('.flag-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('.flag-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            const phoneInput = document.getElementById('phoneInput');
            phoneInput.value = chip.getAttribute('data-code');
            phoneInput.focus();
        });
    });

    loadNumbers();
});