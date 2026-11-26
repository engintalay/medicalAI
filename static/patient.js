/**
 * Medical AI Hasta Paneli
 * Hasta JWT'si ile çalışan tek sayfa uygulama (SPA).
 */
(function () {
    'use strict';

    const TOKEN_KEY = 'patient_token';
    const USER_KEY = 'patient_user';

    const contentArea = document.getElementById('contentArea');
    const pageTitle = document.getElementById('pageTitle');
    const userName = document.getElementById('userName');
    const userEmail = document.getElementById('userEmail');
    const userAvatar = document.getElementById('userAvatar');
    const toastEl = document.getElementById('toast');
    const refreshBtn = document.getElementById('refreshBtn');
    const logoutBtn = document.getElementById('logoutBtn');

    const state = {
        token: localStorage.getItem(TOKEN_KEY) || '',
        user: readUser(),
        page: 'dashboard',
        authMode: 'login',
        chat: { conversations: [], activeId: null, messages: [], upload: null },
        metrics: { items: [], query: '', category: '', selected: new Set(), editingId: null },
        uploads: { items: [], selected: new Set(), previews: {} },
        toastTimer: null
    };

    /* ------------------------------------------------------------------ */
    /* Yardımcılar                                                        */
    /* ------------------------------------------------------------------ */

    function readUser() {
        try {
            return JSON.parse(localStorage.getItem(USER_KEY) || 'null');
        } catch (error) {
            return null;
        }
    }

    function esc(value) {
        return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, function (ch) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
        });
    }

    function formatDateTime(value) {
        if (!value) return '—';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '—';
        return date.toLocaleDateString('tr-TR') + ' ' +
            date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
    }

    function localDateTimeInputValue(value) {
        const date = value ? new Date(value) : new Date();
        if (Number.isNaN(date.getTime())) return '';
        const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
        return local.toISOString().slice(0, 16);
    }

    function formatNumber(value, digits) {
        if (value === null || value === undefined || value === '') return '—';
        const number = Number(value);
        if (Number.isNaN(number)) return esc(value);
        return number.toLocaleString('tr-TR', {
            minimumFractionDigits: digits === undefined ? 0 : digits,
            maximumFractionDigits: digits === undefined ? 2 : digits
        });
    }

    function formatBytes(value) {
        const bytes = Number(value);
        if (!Number.isFinite(bytes) || bytes < 0) return '—';
        if (bytes < 1024) return formatNumber(bytes) + ' B';
        const units = ['KB', 'MB', 'GB', 'TB'];
        let size = bytes / 1024;
        let unit = 0;
        while (size >= 1024 && unit < units.length - 1) {
            size /= 1024;
            unit += 1;
        }
        return formatNumber(size, size < 10 ? 2 : 1) + ' ' + units[unit];
    }

    function loadingHTML(message) {
        return '<div class="loading"><div class="spinner"></div><p>' +
            esc(message || 'Yükleniyor...') + '</p></div>';
    }

    function errorHTML(message) {
        return '<div class="error-box"><div class="emoji">⚠️</div>' +
            '<p>' + esc(message || 'Beklenmeyen bir hata oluştu.') + '</p>' +
            '<button type="button" class="btn btn-primary" id="retryBtn">Tekrar Dene</button></div>';
    }

    function showToast(message, type) {
        if (!toastEl) return;
        toastEl.textContent = message;
        toastEl.className = 'toast show' + (type ? ' ' + type : '');
        clearTimeout(state.toastTimer);
        state.toastTimer = setTimeout(function () {
            toastEl.className = 'toast';
        }, 3500);
    }

    function extractError(data, status) {
        if (!data) return 'İstek başarısız (HTTP ' + status + ')';
        const detail = data.error || data.message || data.detail;
        if (Array.isArray(detail)) {
            return detail.map(function (item) {
                if (typeof item === 'string') return item;
                return item.msg || JSON.stringify(item);
            }).join(', ');
        }
        return detail || 'İstek başarısız (HTTP ' + status + ')';
    }

    class AuthError extends Error {}

    async function api(path, options) {
        options = options || {};
        const headers = new Headers(options.headers || {});
        if (state.token) headers.set('Authorization', 'Bearer ' + state.token);

        let body = options.body;
        if (body && typeof body === 'object' && !(body instanceof FormData) &&
            !(body instanceof URLSearchParams)) {
            headers.set('Content-Type', 'application/json');
            body = JSON.stringify(body);
        }

        const response = await fetch(path, {
            method: options.method || 'GET',
            headers: headers,
            body: body
        });

        const text = await response.text();
        let data = null;
        if (text) {
            try {
                data = JSON.parse(text);
            } catch (error) {
                data = { raw: text };
            }
        }

        if (response.status === 401) {
            clearAuth();
            renderAuth('Oturum süresi doldu, tekrar giriş yapın.');
            throw new AuthError('Oturum süresi doldu');
        }

        if (!response.ok) {
            throw new Error(extractError(data, response.status));
        }

        if (data && data.success === false) {
            throw new Error(extractError(data, response.status));
        }

        return data;
    }

    function clearAuth() {
        state.token = '';
        state.user = null;
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
    }

    function updateUserChip() {
        const user = state.user || {};
        const name = user.full_name || 'Hasta';
        if (userName) userName.textContent = name;
        if (userEmail) userEmail.textContent = user.email || '';
        if (userAvatar) userAvatar.textContent = (name.charAt(0) || 'H').toUpperCase();
    }

    function metricLabel(name) {
        const labels = {
            sistolik: 'Sistolik', diyastolik: 'Diyastolik', 'nabız': 'Nabız',
            weight: 'Kilo', glucose: 'Kan şekeri', temperature: 'Sıcaklık', spo2: 'SpO2'
        };
        return labels[name] || name;
    }

    function statCard(icon, iconClass, value, label) {
        return '<div class="stat-card">' +
            '<div class="stat-icon ' + iconClass + '">' + icon + '</div>' +
            '<div><div class="stat-value">' + esc(value) + '</div>' +
            '<div class="stat-label">' + esc(label) + '</div></div></div>';
    }

    /* ------------------------------------------------------------------ */
    /* Giriş / kayıt                                                      */
    /* ------------------------------------------------------------------ */

    function renderAuth(notice) {
        state.page = 'auth';
        if (pageTitle) pageTitle.textContent = 'Giriş';
        document.title = 'Medical AI · Hasta Girişi';
        document.querySelectorAll('.nav-item[data-path]').forEach(function (item) {
            item.classList.remove('active');
        });
        const register = state.authMode === 'register';
        const extra = register
            ? '<div class="form-grid">' +
              '<div class="field"><label class="label" for="authFullName">Ad Soyad</label>' +
              '<input class="input" id="authFullName" name="full_name" required></div>' +
              '<div class="field"><label class="label" for="authCity">Şehir</label>' +
              '<input class="input" id="authCity" name="city"></div>' +
              '<div class="field"><label class="label" for="authHeight">Boy (cm)</label>' +
              '<input class="input" id="authHeight" name="height_cm" type="number" step="0.1" min="50" max="250"></div>' +
              '<div class="field"><label class="label" for="authWeight">Kilo (kg)</label>' +
              '<input class="input" id="authWeight" name="weight_kg" type="number" step="0.1" min="10" max="400"></div>' +
              '<div class="field"><label class="label" for="authBirth">Doğum yılı</label>' +
              '<input class="input" id="authBirth" name="birth_year" type="number" min="1900" max="2100"></div>' +
              '</div>'
            : '';

        contentArea.innerHTML =
            '<div class="auth-page"><div class="card auth-card">' +
            '<div class="login-brand"><div class="brand-logo">🩺</div>' +
            '<div><div class="login-title">Medical AI</div><div class="login-sub">Hasta Paneli</div></div></div>' +
            '<div class="auth-tabs">' +
            '<button type="button" class="btn ' + (register ? 'btn-secondary' : 'btn-primary') +
            '" data-auth-mode="login">Giriş Yap</button>' +
            '<button type="button" class="btn ' + (register ? 'btn-primary' : 'btn-secondary') +
            '" data-auth-mode="register">Kayıt Ol</button></div>' +
            (notice ? '<div class="alert alert-error show">' + esc(notice) + '</div>' : '') +
            '<form class="login-form" id="authForm" data-form="auth">' +
            '<div class="field"><label class="label" for="authEmail">E-posta</label>' +
            '<input class="input" id="authEmail" name="email" type="email" autocomplete="email" required></div>' +
            '<div class="field"><label class="label" for="authPassword">Şifre</label>' +
            '<input class="input" id="authPassword" name="password" type="password" ' +
            'autocomplete="' + (register ? 'new-password' : 'current-password') + '" required></div>' +
            extra +
            '<button type="submit" class="btn btn-primary" id="authSubmitBtn">' +
            (register ? 'Kayıt Ol' : 'Giriş Yap') + '</button>' +
            '</form>' +
            '<div class="auth-note">Bu panel sağlık verilerinizi görüntülemek içindir; ' +
            'verdiğiniz yanıtlar tanı yerine geçmez, doktorunuza danışın.</div>' +
            '</div></div>';
    }

    function switchAuthMode(mode) {
        if (state.authMode === mode) return;
        state.authMode = mode;
        renderAuth();
    }

    async function submitAuth(form) {
        const register = state.authMode === 'register';
        const payload = {
            email: form.elements.email.value.trim(),
            password: form.elements.password.value
        };
        if (register) {
            payload.full_name = form.elements.full_name.value.trim();
            const city = form.elements.city.value.trim();
            if (city) payload.city = city;
            ['height_cm', 'weight_kg', 'birth_year'].forEach(function (key) {
                const raw = form.elements[key].value;
                if (raw !== '') payload[key] = Number(raw);
            });
        }
        const button = document.getElementById('authSubmitBtn');
        if (button) button.disabled = true;
        try {
            const response = await fetch(register ? '/api/auth/register' : '/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const text = await response.text();
            const data = text ? JSON.parse(text) : null;
            if (!response.ok || !data || !data.token) {
                throw new Error(extractError(data, response.status));
            }
            state.token = data.token;
            state.user = data.user || data.data || null;
            localStorage.setItem(TOKEN_KEY, state.token);
            localStorage.setItem(USER_KEY, JSON.stringify(state.user || {}));
            updateUserChip();
            showToast(register ? 'Hesabınız oluşturuldu. Hoş geldiniz!' : 'Hoş geldiniz!', 'success');
            await navigate('/patient');
        } catch (error) {
            showToast(error.message, 'error');
            if (button) button.disabled = false;
        }
    }

    /* ------------------------------------------------------------------ */
    /* Yönlendirme / kabuk                                                */
    /* ------------------------------------------------------------------ */

    const PAGES = {
        '/patient': { key: 'dashboard', title: 'Dashboard', render: renderDashboard },
        '/patient/chat': { key: 'chat', title: 'Sağlık Sohbeti', render: renderChat },
        '/patient/metrics': { key: 'metrics', title: 'Metriklerim', render: renderMetrics },
        '/patient/uploads': { key: 'uploads', title: 'Dosyalarım', render: renderUploads },
        '/patient/reminders': { key: 'reminders', title: 'Hatırlatmalar', render: renderReminders },
        '/patient/profile': { key: 'profile', title: 'Profilim', render: renderProfile },
        '/patient/rag': { key: 'rag', title: 'Bilgi Tabanım', render: renderPatientRag }
    };

    function setActiveNav(path) {
        document.querySelectorAll('.nav-item[data-path]').forEach(function (item) {
            item.classList.toggle('active', item.getAttribute('data-path') === path);
        });
    }

    async function navigate(path, options) {
        options = options || {};
        if (!state.token) {
            renderAuth();
            return;
        }
        const resolved = PAGES[path] || PAGES['/patient'];
        const effectivePath = PAGES[path] ? path : '/patient';

        if (options.push !== false && window.location.pathname !== effectivePath) {
            window.history.pushState({}, '', effectivePath);
        }

        state.page = resolved.key;
        setActiveNav(effectivePath);
        if (pageTitle) pageTitle.textContent = resolved.title;
        document.title = 'Medical AI · ' + resolved.title;
        contentArea.innerHTML = loadingHTML();

        try {
            await resolved.render();
        } catch (error) {
            if (error instanceof AuthError) return;
            contentArea.innerHTML = errorHTML(error.message);
        }
    }

    function setupShell() {
        updateUserChip();

        document.addEventListener('click', function (event) {
            const navLink = event.target.closest('[data-path]');
            if (navLink) {
                event.preventDefault();
                navigate(navLink.getAttribute('data-path'));
                return;
            }

            const authModeBtn = event.target.closest('[data-auth-mode]');
            if (authModeBtn) {
                switchAuthMode(authModeBtn.getAttribute('data-auth-mode'));
                return;
            }

            const retry = event.target.closest('#retryBtn');
            if (retry) {
                navigate(window.location.pathname, { push: false });
                return;
            }

            const convBtn = event.target.closest('[data-conv]');
            if (convBtn) {
                openConversation(Number(convBtn.getAttribute('data-conv')));
                return;
            }

            const convArchive = event.target.closest('[data-conv-archive]');
            if (convArchive) {
                archiveConversation(
                    Number(convArchive.getAttribute('data-conv-archive')),
                    convArchive.getAttribute('data-archived') !== 'true'
                );
                return;
            }

            const convDelete = event.target.closest('[data-conv-delete]');
            if (convDelete) {
                deleteConversation(Number(convDelete.getAttribute('data-conv-delete')));
                return;
            }

            const newChatBtn = event.target.closest('#newChatBtn');
            if (newChatBtn) {
                newConversation();
                return;
            }

            const chatAttachBtn = event.target.closest('#chatAttachBtn');
            if (chatAttachBtn) {
                const input = document.getElementById('chatFile');
                if (input) input.click();
                return;
            }

            const chatRemoveAttachment = event.target.closest('#chatRemoveAttachment');
            if (chatRemoveAttachment) {
                clearChatAttachment();
                return;
            }

            const exportBtn = event.target.closest('[data-export]');
            if (exportBtn) {
                exportData(exportBtn.getAttribute('data-export'));
                return;
            }

            const reminderDelete = event.target.closest('[data-reminder-delete]');
            if (reminderDelete) {
                deleteReminder(Number(reminderDelete.getAttribute('data-reminder-delete')));
                return;
            }

            const metricEdit = event.target.closest('[data-metric-edit]');
            if (metricEdit) {
                editMetric(Number(metricEdit.getAttribute('data-metric-edit')));
                return;
            }

            if (event.target.closest('#metricCancelEditBtn')) {
                resetMetricForm();
                return;
            }

            const metricDelete = event.target.closest('[data-metric-delete]');
            if (metricDelete) {
                deleteMetric(Number(metricDelete.getAttribute('data-metric-delete')));
                return;
            }

            const metricCheck = event.target.closest('[data-metric-select]');
            if (metricCheck) {
                const id = Number(metricCheck.getAttribute('data-metric-select'));
                if (metricCheck.checked) state.metrics.selected.add(id);
                else state.metrics.selected.delete(id);
                renderMetricsTable();
                return;
            }

            if (event.target.closest('#metricsSelectAll')) {
                const checked = document.getElementById('metricsSelectAll').checked;
                filteredMetrics().forEach(function (item) {
                    if (checked) state.metrics.selected.add(item.id);
                    else state.metrics.selected.delete(item.id);
                });
                renderMetricsTable();
                return;
            }

            if (event.target.closest('#deleteSelectedMetricsBtn')) {
                deleteSelectedMetrics();
                return;
            }

            const uploadPreview = event.target.closest('[data-upload-preview]');
            if (uploadPreview) {
                previewUpload(Number(uploadPreview.getAttribute('data-upload-preview')));
                return;
            }

            const uploadText = event.target.closest('[data-upload-text]');
            if (uploadText) {
                showUploadText(Number(uploadText.getAttribute('data-upload-text')));
                return;
            }

            const uploadCheck = event.target.closest('[data-upload-select]');
            if (uploadCheck) {
                const id = Number(uploadCheck.getAttribute('data-upload-select'));
                if (uploadCheck.checked) state.uploads.selected.add(id);
                else state.uploads.selected.delete(id);
                renderUploadsTable();
                return;
            }

            if (event.target.closest('#uploadsSelectAll')) {
                const checked = document.getElementById('uploadsSelectAll').checked;
                state.uploads.items.forEach(function (item) {
                    if (checked) state.uploads.selected.add(item.id);
                    else state.uploads.selected.delete(item.id);
                });
                renderUploadsTable();
                return;
            }

            if (event.target.closest('#deleteSelectedUploadsBtn')) {
                deleteSelectedUploads();
                return;
            }

            const uploadDelete = event.target.closest('[data-upload-delete]');
            if (uploadDelete) {
                deleteUpload(Number(uploadDelete.getAttribute('data-upload-delete')));
                return;
            }

            const uploadExtract = event.target.closest('[data-upload-extract]');
            if (uploadExtract) {
                extractUpload(Number(uploadExtract.getAttribute('data-upload-extract')));
                return;
            }

            const drugImportBtn = event.target.closest('[data-drug-import]');
            if (drugImportBtn) {
                importPatientDrugUrl(
                    drugImportBtn.getAttribute('data-drug-url'),
                    drugImportBtn.getAttribute('data-drug-title')
                );
            }
        });

        document.addEventListener('submit', function (event) {
            const form = event.target;
            if (!form || !form.getAttribute) return;
            const name = form.getAttribute('data-form');
            if (name === 'auth') {
                event.preventDefault();
                submitAuth(form);
            } else if (name === 'metric') {
                event.preventDefault();
                addMetric(form);
            } else if (name === 'upload') {
                event.preventDefault();
                uploadFile(form);
            } else if (name === 'reminder') {
                event.preventDefault();
                addReminder(form);
            } else if (name === 'prefs') {
                event.preventDefault();
                savePreferences(form);
            } else if (name === 'profile') {
                event.preventDefault();
                saveProfile(form);
            } else if (name === 'rag') {
                event.preventDefault();
                ingestPatientRag(form);
            } else if (name === 'rag-file') {
                event.preventDefault();
                savePatientRagFile(form);
            } else if (name === 'rag-url') {
                event.preventDefault();
                savePatientRagUrl(form);
            } else if (name === 'drug-search') {
                event.preventDefault();
                searchDrugsPatient(form);
            } else if (name === 'chat') {
                event.preventDefault();
                sendChat(form);
            }
        });

        document.addEventListener('change', function (event) {
            if (event.target && event.target.id === 'chatFile') {
                uploadChatFile(event.target.files && event.target.files[0]);
            }
        });

        document.addEventListener('keydown', function (event) {
            if (event.target && event.target.id === 'chatInput' && event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                const form = document.getElementById('chatForm');
                if (form && form.requestSubmit) form.requestSubmit();
            }
        });

        if (refreshBtn) {
            refreshBtn.addEventListener('click', function () {
                navigate(window.location.pathname, { push: false });
            });
        }

        if (logoutBtn) {
            logoutBtn.addEventListener('click', async function () {
                logoutBtn.disabled = true;
                try {
                    if (state.token) await api('/api/auth/logout', { method: 'POST' });
                } catch (error) {
                    // Token zaten geçersiz olabilir; istemciyi yine temizle.
                } finally {
                    clearAuth();
                    renderAuth();
                    window.history.pushState({}, '', '/patient');
                }
            });
        }

        window.addEventListener('popstate', function () {
            if (!state.token) {
                renderAuth();
                return;
            }
            navigate(window.location.pathname, { push: false });
        });
    }

    /* ------------------------------------------------------------------ */
    /* Dashboard                                                          */
    /* ------------------------------------------------------------------ */

    function trendSVG(trend) {
        if (!trend || trend.length < 2) {
            return '<div class="hint">Grafik için en az iki kilo kaydı ekleyin.</div>';
        }
        const values = trend.map(function (item) { return Number(item.value); })
            .filter(function (value) { return Number.isFinite(value); });
        if (values.length < 2) return '<div class="hint">Geçerli kilo kaydı bulunamadı.</div>';
        const min = Math.min.apply(null, values);
        const max = Math.max.apply(null, values);
        const span = max - min || 1;
        const points = values.map(function (value, index) {
            const x = 8 + (index * 584) / Math.max(1, values.length - 1);
            const y = 100 - ((value - min) / span) * 84;
            return x.toFixed(1) + ',' + y.toFixed(1);
        }).join(' ');
        return '<div class="trend-box"><svg class="trend-svg" viewBox="0 0 600 110" ' +
            'preserveAspectRatio="none" aria-label="Kilo değişimi">' +
            '<polyline fill="none" stroke="#2563eb" stroke-width="3" points="' + points + '"></polyline>' +
            '</svg><div class="trend-labels"><span>' + esc(formatNumber(min, 1)) + ' kg</span>' +
            '<span>' + esc(formatNumber(max, 1)) + ' kg</span></div></div>';
    }

    async function renderDashboard() {
        const response = await api('/api/user/dashboard');
        const data = response.data || {};
        const profile = data.profile || {};
        const trend = data.weight_trend || [];
        const metrics = data.metrics || [];
        const reminders = data.reminders || [];
        const uploads = data.uploads || [];

        const metricRows = metrics.slice(0, 8).map(function (item) {
            return '<tr><td>' + esc(item.name) + '</td><td>' + esc(formatNumber(item.value, 1)) + '</td>' +
                '<td>' + esc(item.unit || '—') + '</td><td>' + formatDateTime(item.date) + '</td></tr>';
        }).join('') || '<tr><td colspan="4" class="empty">Henüz metrik kaydı yok.</td></tr>';

        const reminderRows = reminders.slice(0, 5).map(function (item) {
            return '<div class="kv-row"><span class="k">' + esc(item.title) + '</span>' +
                '<span class="v">' + formatDateTime(item.due_date) + '</span></div>';
        }).join('') || '<div class="hint">Yaklaşan hatırlatma yok.</div>';

        contentArea.innerHTML =
            '<div class="page-head"><h2 class="page-title">Merhaba, ' +
            esc(profile.full_name || (state.user && state.user.full_name) || 'Hasta') + '</h2>' +
            '<p class="page-sub">Sağlık verilerinizin özeti ve hızlı işlemler.</p></div>' +
            '<div class="stats-grid">' +
            statCard('❤️', 'red', formatNumber(metrics.length), 'Sağlık metriği') +
            statCard('📎', '', formatNumber(uploads.length || data.upload_count || 0), 'Yüklenen dosya') +
            statCard('⏰', 'amber', formatNumber(reminders.length), 'Aktif hatırlatma') +
            statCard('🧩', 'green', formatNumber(trend.length), 'Kilo ölçümü') +
            '</div>' +
            '<div class="cards-grid">' +
            '<div class="card"><div class="card-head"><div class="card-title">Profil özeti</div>' +
            '<a class="btn btn-secondary btn-sm" href="/patient/profile" data-path="/patient/profile">Düzenle</a></div>' +
            '<div class="kv-list">' +
            '<div class="kv-row"><span class="k">Ad Soyad</span><span class="v">' + esc(profile.full_name || '—') + '</span></div>' +
            '<div class="kv-row"><span class="k">E-posta</span><span class="v">' +
            esc((state.user && state.user.email) || '—') + '</span></div>' +
            '<div class="kv-row"><span class="k">Boy</span><span class="v">' +
            esc(profile.height_cm ? formatNumber(profile.height_cm, 1) + ' cm' : '—') + '</span></div>' +
            '<div class="kv-row"><span class="k">Kilo</span><span class="v">' +
            esc(profile.weight_kg ? formatNumber(profile.weight_kg, 1) + ' kg' : '—') + '</span></div>' +
            '<div class="kv-row"><span class="k">Şehir</span><span class="v">' + esc(profile.city || '—') + '</span></div>' +
            '</div></div>' +
            '<div class="card"><div class="card-head"><div class="card-title">Kilo değişimi</div></div>' +
            trendSVG(trend) +
            '<div class="card-note">Son 30 kilo ölçümü grafiğe yansır.</div></div>' +
            '</div>' +
            '<div class="section-head"><div class="section-title">Son metrikler</div>' +
            '<a class="btn btn-secondary btn-sm" href="/patient/metrics" data-path="/patient/metrics">Tümünü gör</a></div>' +
            '<div class="table-wrap"><table class="table"><thead><tr>' +
            '<th>Metrik</th><th>Değer</th><th>Birim</th><th>Tarih</th>' +
            '</tr></thead><tbody>' + metricRows + '</tbody></table></div>' +
            '<div class="section-head"><div class="section-title">Yaklaşan hatırlatmalar</div>' +
            '<a class="btn btn-secondary btn-sm" href="/patient/reminders" data-path="/patient/reminders">Yönet</a></div>' +
            '<div class="card">' + reminderRows + '</div>' +
            '<div class="section-head"><div class="section-title">Hızlı işlemler</div></div>' +
            '<div class="quick-actions">' +
            '<button type="button" class="btn btn-primary" data-export="csv">⬇️ CSV indir</button>' +
            '<button type="button" class="btn btn-secondary" data-export="pdf">⬇️ PDF indir</button>' +
            '<a class="btn btn-secondary" href="/patient/chat" data-path="/patient/chat">💬 Sohbet et</a>' +
            '<a class="btn btn-secondary" href="/patient/uploads" data-path="/patient/uploads">📎 Dosya yükle</a>' +
            '</div>';
    }

    async function exportData(format) {
        try {
            const response = await fetch('/api/user/export?format=' + encodeURIComponent(format), {
                headers: { Authorization: 'Bearer ' + state.token }
            });
            if (response.status === 401) {
                clearAuth();
                renderAuth();
                return;
            }
            if (!response.ok) {
                const data = await response.json().catch(function () { return null; });
                throw new Error(extractError(data, response.status));
            }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = 'medicalai-rapor.' + format;
            document.body.appendChild(link);
            link.click();
            link.remove();
            setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
            showToast(format.toUpperCase() + ' raporu indirildi.', 'success');
        } catch (error) {
            showToast(error.message, 'error');
        }
    }

    /* ------------------------------------------------------------------ */
    /* Sohbet                                                             */
    /* ------------------------------------------------------------------ */

    function renderMessages() {
        const box = document.getElementById('chatMessages');
        if (!box) return;
        if (!state.chat.messages.length) {
            box.innerHTML = '<div class="chat-empty"><div class="emoji">💬</div>' +
                '<div>Sağlık sorularınızı sorun. Yanıtlar bilgi tabanındaki kaynaklara dayanır.</div>' +
                '<div class="hint" style="margin-top:8px">Bu sohbet tanı yerine geçmez.</div></div>';
            return;
        }
        box.innerHTML = state.chat.messages.map(function (msg) {
            const sources = (msg.sources || []).map(function (source) {
                return '<span class="source-chip">' + esc(source.source || 'kaynak') +
                    ' · ' + esc(formatNumber(source.score, 2)) + '</span>';
            }).join('');
            const attachment = msg.attachment
                ? '<div class="msg-attachment"><span>📎 ' + esc(msg.attachment.filename || 'dosya') + '</span>' +
                  '<span class="badge badge-success">Okundu</span>' +
                  (msg.attachment.extracted_text
                    ? '<details><summary>Çıkarılan metni göster</summary><div class="markdown-body">' +
                      (window.MedicalMarkdown ? MedicalMarkdown.render(msg.attachment.extracted_text) : esc(msg.attachment.extracted_text)) +
                      '</div></details>'
                    : '') + '</div>'
                : '';
            const metrics = (msg.recorded_metrics || []).length
                ? '<div class="saved-metrics"><strong>✅ Ölçümler kaydedildi</strong>' +
                  (msg.recorded_metrics || []).map(function (item) {
                      return '<span>' + esc(metricLabel(item.name)) + ': ' +
                          esc(formatNumber(item.value, 2)) + ' ' + esc(item.unit || '') + '</span>';
                  }).join('') + '</div>'
                : '';
            return '<div class="msg ' + esc(msg.role) + '">' + esc(msg.content) +
                attachment + metrics +
                (sources ? '<div class="msg-sources">' + sources + '</div>' : '') + '</div>';
        }).join('');
        box.scrollTop = box.scrollHeight;
    }

    function renderConversationList() {
        const list = document.getElementById('conversationList');
        if (!list) return;
        const items = state.chat.conversations;
        list.innerHTML = items.length ? items.map(function (item) {
            const archived = !!item.is_archived;
            return '<div class="conv-wrap' + (state.chat.activeId === item.id ? ' active' : '') + '">' +
                '<button type="button" class="conv-item" data-conv="' + item.id + '">' +
                '<div class="conv-title">' + esc(item.title || 'Sohbet ' + item.id) + '</div>' +
                '<div class="conv-date">' + formatDateTime(item.created_at) +
                (archived ? ' · Arşivlendi' : '') + '</div></button>' +
                '<div class="conv-actions">' +
                '<button type="button" class="btn btn-secondary btn-sm" data-conv-archive="' + item.id +
                '" data-archived="' + (archived ? 'true' : 'false') + '">' +
                (archived ? 'Geri yükle' : 'Arşivle') + '</button>' +
                '<button type="button" class="btn btn-danger btn-sm" data-conv-delete="' + item.id + '">Sil</button>' +
                '</div></div>';
        }).join('') : '<div class="empty" style="padding:20px 12px">Sohbet bulunamadı.</div>';
    }

    async function renderChat() {
        state.chat.activeId = null;
        state.chat.messages = [];
        state.chat.upload = null;

        contentArea.innerHTML =
            '<div class="page-head"><h2 class="page-title">Sağlık Sohbeti</h2>' +
            '<p class="page-sub">Sohbetlerde arama yapın; arşivleyin veya silin. Dosyayı sohbet alanına sürükleyebilirsin.</p></div>' +
            '<div class="chat-layout">' +
            '<div class="chat-sidebar"><div class="chat-sidebar-head">' +
            '<input type="search" class="input" id="conversationSearch" placeholder="Sohbetlerde ara...">' +
            '<select class="select" id="conversationFilter">' +
            '<option value="active">Aktif sohbetler</option>' +
            '<option value="archived">Arşivlenmişler</option>' +
            '<option value="all">Tüm sohbetler</option></select>' +
            '<button type="button" class="btn btn-primary btn-sm" id="newChatBtn">＋ Yeni sohbet</button>' +
            '<span class="hint" id="conversationCount"></span></div>' +
            '<div class="conv-list" id="conversationList">' + loadingHTML('Sohbetler yükleniyor...') + '</div></div>' +
            '<div class="chat-main">' +
            '<div class="chat-head"><span class="card-title">Sohbet</span>' +
            '<span class="hint">Yanıtlar tanı değildir</span></div>' +
            '<div class="chat-messages" id="chatMessages"></div>' +
            '<div id="chatAttachment" class="chat-attachment hidden"></div>' +
            '<form class="chat-composer" data-form="chat" id="chatForm">' +
            '<input type="file" id="chatFile" class="hidden" accept="image/jpeg,image/png,image/webp,application/pdf,text/plain">' +
            '<button type="button" class="btn btn-secondary" id="chatAttachBtn" title="Dosya ekle ve otomatik analiz et">📎</button>' +
            '<textarea id="chatInput" name="message" placeholder="Mesaj yazın veya ölçüm resmi ekleyin... (Enter: gönder)"></textarea>' +
            '<button type="submit" class="btn btn-primary" id="chatSendBtn">Gönder</button>' +
            '</form></div></div>';

        const search = document.getElementById('conversationSearch');
        const filter = document.getElementById('conversationFilter');
        if (search) {
            search.addEventListener('input', function () { loadConversations(); });
        }
        if (filter) {
            filter.addEventListener('change', function () { loadConversations(); });
        }
        renderMessages();
        setupChatDropzone();
        await loadConversations();
    }

    async function loadConversations() {
        const search = document.getElementById('conversationSearch');
        const filter = document.getElementById('conversationFilter');
        const mode = filter ? filter.value : 'active';
        const params = new URLSearchParams();
        params.set('q', search ? search.value.trim() : '');
        params.set('include_archived', mode === 'active' ? 'false' : 'true');
        if (mode === 'active') params.set('archived', 'false');
        if (mode === 'archived') params.set('archived', 'true');
        try {
            const response = await api('/api/conversations?' + params.toString());
            state.chat.conversations = response.data || [];
            renderConversationList();
            const count = document.getElementById('conversationCount');
            if (count) count.textContent = formatNumber(state.chat.conversations.length) + ' sohbet';
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        }
    }

    function setupChatDropzone() {
        const zone = document.querySelector('.chat-main');
        if (!zone) return;
        let depth = 0;
        zone.addEventListener('dragenter', function (event) {
            event.preventDefault();
            depth += 1;
            zone.classList.add('dragover');
        });
        zone.addEventListener('dragover', function (event) {
            event.preventDefault();
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
        });
        zone.addEventListener('dragleave', function (event) {
            event.preventDefault();
            depth = Math.max(0, depth - 1);
            if (depth === 0) zone.classList.remove('dragover');
        });
        zone.addEventListener('drop', function (event) {
            event.preventDefault();
            depth = 0;
            zone.classList.remove('dragover');
            const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
            if (file) uploadChatFile(file);
        });
    }

    async function openConversation(id) {
        state.chat.activeId = id;
        try {
            const response = await api('/api/conversations/' + encodeURIComponent(id));
            state.chat.messages = (response.data && response.data.messages) || [];
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
            return;
        }
        renderConversationList();
        renderMessages();
    }

    async function archiveConversation(id, archived) {
        try {
            await api('/api/conversations/' + encodeURIComponent(id) + '/archive', {
                method: 'PATCH', body: { archived: archived }
            });
            if (archived && state.chat.activeId === id) newConversation();
            showToast(archived ? 'Sohbet arşivlendi.' : 'Sohbet arşivden çıkarıldı.', 'success');
            await loadConversations();
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        }
    }

    async function deleteConversation(id) {
        if (!await MedicalDialog.confirm('Bu sohbet ve tüm mesajları kalıcı olarak silinsin mi?', {
            title: 'Sohbeti sil', confirmText: 'Sil', cancelText: 'Vazgeç'
        })) return;
        try {
            await api('/api/conversations/' + encodeURIComponent(id), { method: 'DELETE' });
            if (state.chat.activeId === id) newConversation();
            showToast('Sohbet silindi.', 'success');
            await loadConversations();
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        }
    }

    function newConversation() {
        state.chat.activeId = null;
        state.chat.messages = [];
        renderConversationList();
        renderMessages();
        const input = document.getElementById('chatInput');
        if (input) input.focus();
    }

    function renderChatAttachment() {
        const box = document.getElementById('chatAttachment');
        if (!box) return;
        const item = state.chat.upload;
        if (!item) {
            box.className = 'chat-attachment hidden';
            box.innerHTML = '';
            return;
        }
        box.className = 'chat-attachment';
        box.innerHTML = '<span>📎 <strong>' + esc(item.filename) + '</strong></span>' +
            '<span class="hint">' + (item.uploading ? 'Yükleniyor...' : 'Analiz için hazır') + '</span>' +
            '<button type="button" class="btn btn-secondary btn-sm" id="chatRemoveAttachment">Kaldır</button>';
    }

    function clearChatAttachment() {
        state.chat.upload = null;
        const input = document.getElementById('chatFile');
        if (input) input.value = '';
        renderChatAttachment();
    }

    async function uploadChatFile(file) {
        if (!file) return;
        state.chat.upload = { id: null, filename: file.name, uploading: true };
        renderChatAttachment();
        try {
            const data = new FormData();
            data.append('file', file);
            const response = await fetch('/api/uploads', {
                method: 'POST',
                headers: { Authorization: 'Bearer ' + state.token },
                body: data
            });
            if (response.status === 401) {
                clearAuth();
                renderAuth();
                return;
            }
            const text = await response.text();
            const payload = text ? JSON.parse(text) : null;
            if (!response.ok || !payload || !payload.data || !payload.data.id) {
                throw new Error(extractError(payload, response.status));
            }
            state.chat.upload = {
                id: payload.data.id,
                filename: payload.data.filename || file.name,
                uploading: false
            };
            showToast('Dosya yüklendi, analiz başlıyor...', 'success');
            // Kullanıcı dosyayı seçtiğinde ek "Gönder" aşamasına ihtiyaç duymasın.
            const form = document.getElementById('chatForm');
            if (form && state.page === 'chat' && form.requestSubmit) {
                form.requestSubmit();
            }
        } catch (error) {
            state.chat.upload = null;
            showToast(error.message, 'error');
        } finally {
            const input = document.getElementById('chatFile');
            if (input) input.value = '';
            renderChatAttachment();
        }
    }

    async function sendChat(form) {
        const message = form.elements.message.value.trim();
        const attachment = state.chat.upload;
        if (!message && !attachment) return;
        if (attachment && attachment.uploading) {
            showToast('Dosya yükleniyor, birkaç saniye bekleyin.', 'info');
            return;
        }
        const button = document.getElementById('chatSendBtn');
        const isNew = state.chat.activeId === null;
        state.chat.messages.push({
            role: 'user',
            content: message || (attachment ? 'Bu dosyayı incele.' : ''),
            attachment: attachment ? { filename: attachment.filename, extracting: true } : null
        });
        renderMessages();
        form.elements.message.value = '';
        if (button) button.disabled = true;
        try {
            const payload = { message: message };
            if (state.chat.activeId !== null) payload.conversation_id = state.chat.activeId;
            if (attachment && attachment.id !== null) payload.upload_id = attachment.id;
            const response = await api('/api/chat', {
                method: 'POST',
                body: payload
            });
            const data = response.data || {};
            state.chat.activeId = data.conversation_id || state.chat.activeId;
            // Kullanıcı mesajını sunucudan gelen gerçek ek bilgilerle güncelle.
            state.chat.messages[state.chat.messages.length - 1].attachment = data.attachment || null;
            state.chat.messages.push({
                role: 'assistant',
                content: data.answer || '',
                sources: data.sources || [],
                recorded_metrics: data.recorded_metrics || []
            });
            if (isNew && state.chat.activeId !== null) {
                await loadConversations();
            }
            clearChatAttachment();
            renderMessages();
        } catch (error) {
            if (error instanceof AuthError) return;
            state.chat.messages.pop();
            showToast(error.message, 'error');
            renderMessages();
        } finally {
            if (button) button.disabled = false;
        }
    }

    /* ------------------------------------------------------------------ */
    /* Sağlık metrikleri                                                  */
    /* ------------------------------------------------------------------ */

    function metricCategory(name) {
        const value = String(name || '').toLocaleLowerCase('tr');
        if (value.includes('sistolik') || value.includes('diyastolik') ||
            value.includes('tansiyon') || value.includes('blood_pressure')) return 'blood_pressure';
        if (value.includes('nabız') || value.includes('pulse') || value.includes('heart_rate')) return 'pulse';
        if (value.includes('weight') || value.includes('kilo')) return 'weight';
        if (value.includes('glucose') || value.includes('glukoz') || value.includes('kan şekeri')) return 'glucose';
        if (value.includes('temperature') || value.includes('sıcaklık')) return 'temperature';
        if (value.includes('spo2') || value.includes('oxygen')) return 'spo2';
        return 'other';
    }

    function metricCategoryLabel(key) {
        const labels = {
            blood_pressure: 'Tansiyon', pulse: 'Nabız', weight: 'Kilo',
            glucose: 'Kan Şekeri', temperature: 'Sıcaklık', spo2: 'Oksijen', other: 'Diğer'
        };
        return labels[key] || key;
    }

    function filteredMetrics() {
        const query = state.metrics.query.trim().toLocaleLowerCase('tr');
        return state.metrics.items.filter(function (item) {
            if (state.metrics.category && metricCategory(item.name) !== state.metrics.category) return false;
            if (!query) return true;
            const haystack = [item.name, item.unit, item.value,
                metricCategoryLabel(metricCategory(item.name))]
                .join(' ').toLocaleLowerCase('tr');
            return haystack.includes(query);
        });
    }

    async function renderMetrics() {
        const response = await api('/api/user/dashboard');
        state.metrics.items = (response.data && response.data.metrics) || [];
        state.metrics.query = '';
        state.metrics.category = '';
        state.metrics.selected = new Set();
        state.metrics.editingId = null;

        contentArea.innerHTML =
            '<div class="page-head"><h2 class="page-title">Sağlık Metriklerim</h2>' +
            '<p class="page-sub">Ölçüm tarihini gir; sistem giriş zamanından bağımsız olarak ölçüm tarihine göre sıralanır.</p></div>' +
            '<form class="card" data-form="metric" id="metricForm">' +
            '<div class="form-grid">' +
            '<div class="field"><label class="label" for="metricName">Metrik adı</label>' +
            '<input class="input" id="metricName" name="name" required placeholder="Örn. weight, tansiyon"></div>' +
            '<div class="field"><label class="label" for="metricValue">Değer</label>' +
            '<input class="input" id="metricValue" name="value" type="number" step="any" required></div>' +
            '<div class="field"><label class="label" for="metricUnit">Birim</label>' +
            '<input class="input" id="metricUnit" name="unit" placeholder="Örn. kg, mmHg"></div>' +
            '<div class="field"><label class="label" for="metricRecordedAt">Ölçüm tarihi ve saati</label>' +
            '<input class="input" id="metricRecordedAt" name="recorded_at" type="datetime-local" required ' +
            'value="' + localDateTimeInputValue() + '"></div>' +
            '</div><div class="form-actions"><button type="submit" class="btn btn-primary" id="metricSubmitBtn">Kaydet</button>' +
            '<button type="button" class="btn btn-secondary hidden" id="metricCancelEditBtn">Vazgeç</button></div>' +
            '</form>' +
            '<div class="section-head"><div class="section-title">Geçmiş</div>' +
            '<span class="hint" id="metricsCount"></span></div>' +
            '<div class="toolbar">' +
            '<div class="toolbar-group">' +
            '<input type="search" class="input" id="metricSearch" placeholder="Metrik, değer veya birim ara..." style="min-width:240px">' +
            '<select class="select" id="metricCategoryFilter" style="width:auto">' +
            '<option value="">Tüm kategoriler</option>' +
            '<option value="blood_pressure">Tansiyon</option><option value="pulse">Nabız</option>' +
            '<option value="weight">Kilo</option><option value="glucose">Kan Şekeri</option>' +
            '<option value="temperature">Sıcaklık</option><option value="spo2">Oksijen</option>' +
            '<option value="other">Diğer</option></select></div>' +
            '<div class="toolbar-group">' +
            '<label class="inline-check"><input type="checkbox" id="metricsSelectAll"> Tümünü seç</label>' +
            '<button type="button" class="btn btn-danger btn-sm" id="deleteSelectedMetricsBtn" disabled>Seçilenleri sil (0)</button>' +
            '</div></div>' +
            '<div id="metricsTable"></div>';

        const search = document.getElementById('metricSearch');
        const category = document.getElementById('metricCategoryFilter');
        if (search) {
            search.addEventListener('input', function () {
                state.metrics.query = search.value;
                renderMetricsTable();
            });
        }
        if (category) {
            category.addEventListener('change', function () {
                state.metrics.category = category.value;
                renderMetricsTable();
            });
        }
        renderMetricsTable();
    }

    function renderMetricsTable() {
        const container = document.getElementById('metricsTable');
        if (!container) return;
        const items = filteredMetrics();
        const rows = items.length ? items.map(function (item) {
            const checked = state.metrics.selected.has(item.id);
            return '<tr>' +
                '<td><input type="checkbox" data-metric-select="' + item.id + '"' +
                (checked ? ' checked' : '') + ' aria-label="Metriği seç"></td>' +
                '<td>' + esc(item.name) + '</td>' +
                '<td>' + esc(formatNumber(item.value, 2)) + '</td>' +
                '<td>' + esc(item.unit || '—') + '</td>' +
                '<td><strong>' + formatDateTime(item.date) + '</strong></td>' +
                '<td class="muted-cell">' + formatDateTime(item.created_at) + '</td>' +
                '<td class="actions-cell">' +
                '<button type="button" class="btn btn-secondary btn-sm" data-metric-edit="' + item.id + '">Düzenle</button>' +
                '<button type="button" class="btn btn-danger btn-sm" data-metric-delete="' + item.id + '">Sil</button>' +
                '</td></tr>';
        }).join('') : '<tr><td colspan="7" class="empty">Filtreye uygun metrik kaydı yok.</td></tr>';

        container.innerHTML = '<div class="table-wrap"><table class="table"><thead><tr>' +
            '<th></th><th>Metrik</th><th>Değer</th><th>Birim</th>' +
            '<th>Ölçüm Tarihi</th><th>Sisteme Girildi</th><th></th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table></div>';

        const count = document.getElementById('metricsCount');
        if (count) count.textContent = formatNumber(items.length) + ' / ' +
            formatNumber(state.metrics.items.length) + ' kayıt';
        const selectAll = document.getElementById('metricsSelectAll');
        if (selectAll) {
            const selectedCount = items.filter(function (item) {
                return state.metrics.selected.has(item.id);
            }).length;
            selectAll.checked = items.length > 0 && selectedCount === items.length;
            selectAll.indeterminate = selectedCount > 0 && selectedCount < items.length;
        }
        const deleteButton = document.getElementById('deleteSelectedMetricsBtn');
        if (deleteButton) {
            deleteButton.disabled = state.metrics.selected.size === 0;
            deleteButton.textContent = 'Seçilenleri sil (' + state.metrics.selected.size + ')';
        }
    }

    function editMetric(metricId) {
        const item = state.metrics.items.find(function (row) { return row.id === metricId; });
        const form = document.getElementById('metricForm');
        if (!item || !form) return;
        state.metrics.editingId = item.id;
        form.elements.name.value = item.name || '';
        form.elements.value.value = item.value;
        form.elements.unit.value = item.unit || '';
        form.elements.recorded_at.value = localDateTimeInputValue(item.date);
        const submit = document.getElementById('metricSubmitBtn');
        const cancel = document.getElementById('metricCancelEditBtn');
        if (submit) submit.textContent = 'Güncelle';
        if (cancel) cancel.classList.remove('hidden');
        form.scrollIntoView({ behavior: 'smooth', block: 'center' });
        form.elements.name.focus();
    }

    function resetMetricForm() {
        const form = document.getElementById('metricForm');
        if (!form) return;
        state.metrics.editingId = null;
        form.reset();
        const submit = document.getElementById('metricSubmitBtn');
        const cancel = document.getElementById('metricCancelEditBtn');
        if (submit) submit.textContent = 'Kaydet';
        if (cancel) cancel.classList.add('hidden');
    }

    async function addMetric(form) {
        const recordedAt = form.elements.recorded_at.value;
        const payload = {
            name: form.elements.name.value.trim(),
            value: Number(form.elements.value.value),
            unit: form.elements.unit.value.trim() || null,
            recorded_at: recordedAt ? new Date(recordedAt).toISOString() : null
        };
        const editingId = state.metrics.editingId;
        const button = form.querySelector('button[type="submit"]');
        if (button) button.disabled = true;
        try {
            if (editingId !== null) {
                await api('/api/user/metrics/' + encodeURIComponent(editingId), {
                    method: 'PUT', body: payload
                });
                showToast('Metrik güncellendi.', 'success');
            } else {
                await api('/api/user/metrics', { method: 'POST', body: payload });
                showToast('Metrik kaydedildi.', 'success');
            }
            await navigate('/patient/metrics', { push: false });
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
            if (button) button.disabled = false;
        }
    }

    async function deleteMetric(metricId) {
        if (!await MedicalDialog.confirm('Bu metrik kaydı silinsin mi?', {
            title: 'Metriği sil', confirmText: 'Sil', cancelText: 'Vazgeç'
        })) return;
        try {
            await api('/api/user/metrics/' + encodeURIComponent(metricId), { method: 'DELETE' });
            showToast('Metrik silindi.', 'success');
            await navigate('/patient/metrics', { push: false });
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        }
    }

    async function deleteSelectedMetrics() {
        const ids = Array.from(state.metrics.selected);
        if (!ids.length) return;
        if (!await MedicalDialog.confirm(ids.length + ' metrik kaydı silinsin mi?', {
            title: 'Seçilen metrikleri sil', confirmText: 'Tümünü sil', cancelText: 'Vazgeç'
        })) return;
        const button = document.getElementById('deleteSelectedMetricsBtn');
        if (button) button.disabled = true;
        let deleted = 0;
        for (const id of ids) {
            try {
                await api('/api/user/metrics/' + encodeURIComponent(id), { method: 'DELETE' });
                deleted += 1;
            } catch (error) {
                if (error instanceof AuthError) return;
                showToast(error.message, 'error');
            }
        }
        showToast(deleted + ' metrik silindi.', deleted === ids.length ? 'success' : 'error');
        await navigate('/patient/metrics', { push: false });
    }

    /* ------------------------------------------------------------------ */
    /* Dosyalar                                                           */
    /* ------------------------------------------------------------------ */

    function revokeUploadPreviews() {
        Object.keys(state.uploads.previews).forEach(function (key) {
            URL.revokeObjectURL(state.uploads.previews[key]);
            delete state.uploads.previews[key];
        });
    }

    async function fetchUploadBlob(id) {
        const response = await fetch('/api/uploads/' + encodeURIComponent(id) + '/file', {
            headers: { Authorization: 'Bearer ' + state.token }
        });
        if (response.status === 401) {
            clearAuth();
            renderAuth();
            throw new AuthError('Oturum süresi doldu');
        }
        if (!response.ok) throw new Error('Dosya açılamadı (HTTP ' + response.status + ')');
        return response.blob();
    }

    async function loadUploadThumbnails() {
        const images = state.uploads.items.filter(function (item) {
            return String(item.mime_type || '').startsWith('image/');
        }).slice(0, 30);
        for (const item of images) {
            if (state.uploads.previews[item.id]) {
                const img = document.querySelector('[data-upload-thumb="' + item.id + '"]');
                if (img) img.src = state.uploads.previews[item.id];
                continue;
            }
            try {
                const blob = await fetchUploadBlob(item.id);
                const url = URL.createObjectURL(blob);
                state.uploads.previews[item.id] = url;
                const img = document.querySelector('[data-upload-thumb="' + item.id + '"]');
                if (img) img.src = url;
            } catch (error) {
                if (error instanceof AuthError) return;
            }
        }
    }

    async function renderUploads() {
        revokeUploadPreviews();
        const response = await api('/api/uploads');
        state.uploads.items = response.data || [];
        state.uploads.selected = new Set();

        contentArea.innerHTML =
            '<div class="page-head"><h2 class="page-title">Dosyalarım</h2>' +
            '<p class="page-sub">Görsel/PDF önizleyin, metin çıkarın ve birden fazla dosyayı birlikte silin.</p></div>' +
            '<form class="card" data-form="upload" id="uploadForm">' +
            '<label class="dropzone" for="uploadFile">' +
            '<span class="emoji">📎</span><strong>Dosya seç veya sürükle-bırak</strong>' +
            '<span class="hint">PDF, JPEG, PNG, WebP, TXT · maksimum boyut config\'den okunur</span>' +
            '<input type="file" id="uploadFile" name="file" class="hidden" required></label>' +
            '<div class="form-actions"><button type="submit" class="btn btn-primary">Yükle</button></div>' +
            '</form><div id="extractResult"></div>' +
            '<div class="section-head"><div class="section-title">Yüklenen dosyalar</div>' +
            '<span class="hint" id="uploadsCount"></span></div>' +
            '<div class="toolbar"><div class="toolbar-group">' +
            '<label class="inline-check"><input type="checkbox" id="uploadsSelectAll"> Tümünü seç</label>' +
            '<button type="button" class="btn btn-danger btn-sm" id="deleteSelectedUploadsBtn" disabled>Seçilenleri sil (0)</button>' +
            '</div></div><div id="uploadsTable"></div>';

        renderUploadsTable();
        const zone = document.querySelector('.dropzone');
        const input = document.getElementById('uploadFile');
        if (zone && input) {
            ['dragenter', 'dragover'].forEach(function (type) {
                zone.addEventListener(type, function (event) {
                    event.preventDefault();
                    zone.classList.add('dragover');
                });
            });
            ['dragleave', 'drop'].forEach(function (type) {
                zone.addEventListener(type, function (event) {
                    event.preventDefault();
                    zone.classList.remove('dragover');
                });
            });
            zone.addEventListener('drop', function (event) {
                if (event.dataTransfer && event.dataTransfer.files.length) {
                    input.files = event.dataTransfer.files;
                }
            });
        }
    }

    function renderUploadsTable() {
        const container = document.getElementById('uploadsTable');
        if (!container) return;
        const items = state.uploads.items;
        const rows = items.length ? items.map(function (item) {
            const image = String(item.mime_type || '').startsWith('image/');
            const icon = image
                ? '<img class="upload-thumb" data-upload-thumb="' + item.id + '" alt="Önizleme">'
                : '<span class="upload-file-icon">' + (item.mime_type === 'application/pdf' ? '📄' : '📝') + '</span>';
            const textReady = !!(item.extracted_text || '').trim();
            return '<tr>' +
                '<td><input type="checkbox" data-upload-select="' + item.id + '"' +
                (state.uploads.selected.has(item.id) ? ' checked' : '') + ' aria-label="Dosyayı seç"></td>' +
                '<td><div class="upload-name">' + icon + '<div><strong>' + esc(item.filename) + '</strong>' +
                '<div class="hint">' + esc(item.mime_type || '—') + '</div></div></div></td>' +
                '<td>' + formatBytes(item.size) + '</td>' +
                '<td>' + formatDateTime(item.created_at) + '</td>' +
                '<td>' + (textReady
                    ? '<span class="badge badge-success">Metin hazır</span><div class="hint">' +
                      formatDateTime(item.extracted_at) + '</div>'
                    : '<span class="badge badge-warning">Çıkarılmadı</span>') + '</td>' +
                '<td class="actions-cell">' +
                '<button type="button" class="btn btn-secondary btn-sm" data-upload-preview="' + item.id + '">Önizle</button>' +
                '<button type="button" class="btn btn-secondary btn-sm" data-upload-' +
                (textReady ? 'text' : 'extract') + '="' + item.id + '">' +
                (textReady ? 'Metni gör' : 'Metin çıkar') + '</button>' +
                '<button type="button" class="btn btn-danger btn-sm" data-upload-delete="' + item.id + '">Sil</button>' +
                '</td></tr>';
        }).join('') : '<tr><td colspan="6" class="empty">Henüz dosya yüklemediniz.</td></tr>';

        container.innerHTML = '<div class="table-wrap"><table class="table"><thead><tr>' +
            '<th></th><th>Dosya</th><th>Boyut</th><th>Yüklenme</th><th>Metin</th><th></th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table></div>';
        const count = document.getElementById('uploadsCount');
        if (count) count.textContent = formatNumber(items.length) + ' dosya';
        const selectAll = document.getElementById('uploadsSelectAll');
        if (selectAll) {
            selectAll.checked = items.length > 0 && state.uploads.selected.size === items.length;
            selectAll.indeterminate = state.uploads.selected.size > 0 && state.uploads.selected.size < items.length;
        }
        const button = document.getElementById('deleteSelectedUploadsBtn');
        if (button) {
            button.disabled = state.uploads.selected.size === 0;
            button.textContent = 'Seçilenleri sil (' + state.uploads.selected.size + ')';
        }
        loadUploadThumbnails();
    }

    function closePreview(overlay, objectUrl) {
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        document.removeEventListener('keydown', onPreviewKeydown, true);
        overlay.remove();
    }

    function onPreviewKeydown(event) {
        if (event.key === 'Escape') {
            const overlay = document.querySelector('.preview-overlay');
            if (overlay) closePreview(overlay, overlay.getAttribute('data-object-url'));
        }
    }

    async function previewUpload(id) {
        const item = state.uploads.items.find(function (row) { return row.id === id; });
        if (!item) return;
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay preview-overlay';
        overlay.innerHTML = '<div class="preview-card"><div class="preview-head">' +
            '<strong></strong><button type="button" class="btn btn-secondary btn-sm" data-preview-close>Kapat</button></div>' +
            '<div class="preview-body">' + loadingHTML('Dosya açılıyor...') + '</div></div>';
        overlay.querySelector('.preview-head strong').textContent = item.filename;
        overlay.querySelector('[data-preview-close]').addEventListener('click', function () {
            closePreview(overlay, overlay.getAttribute('data-object-url'));
        });
        overlay.addEventListener('click', function (event) {
            if (event.target === overlay) closePreview(overlay, overlay.getAttribute('data-object-url'));
        });
        document.addEventListener('keydown', onPreviewKeydown, true);
        document.body.appendChild(overlay);
        try {
            const blob = await fetchUploadBlob(id);
            const url = URL.createObjectURL(blob);
            overlay.setAttribute('data-object-url', url);
            const body = overlay.querySelector('.preview-body');
            if (String(item.mime_type || '').startsWith('image/')) {
                body.innerHTML = '<img class="preview-image" alt="Dosya önizleme">';
                body.querySelector('img').src = url;
            } else if (item.mime_type === 'application/pdf') {
                body.innerHTML = '<iframe class="preview-pdf" title="PDF önizleme"></iframe>';
                body.querySelector('iframe').src = url;
            } else {
                const text = await blob.text();
                body.innerHTML = '<pre class="preview-text"></pre>';
                body.querySelector('pre').textContent = text;
            }
        } catch (error) {
            if (error instanceof AuthError) return;
            const body = overlay.querySelector('.preview-body');
            if (body) body.innerHTML = '<div class="alert alert-error show">' + esc(error.message) + '</div>';
        }
    }

    function showUploadText(id) {
        const item = state.uploads.items.find(function (row) { return row.id === id; });
        if (!item) return;
        if (!(item.extracted_text || '').trim()) {
            extractUpload(id, true);
            return;
        }
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay preview-overlay';
        overlay.innerHTML = '<div class="preview-card"><div class="preview-head">' +
            '<strong>Çıkarılan metin · ' + esc(item.filename) + '</strong>' +
            '<button type="button" class="btn btn-secondary btn-sm" data-preview-close>Kapat</button></div>' +
            '<div class="preview-body"><div class="markdown-body"></div></div></div>';
        overlay.querySelector('.markdown-body').innerHTML = window.MedicalMarkdown
            ? MedicalMarkdown.render(item.extracted_text) : '<pre>' + esc(item.extracted_text) + '</pre>';
        overlay.querySelector('[data-preview-close]').addEventListener('click', function () { closePreview(overlay); });
        overlay.addEventListener('click', function (event) {
            if (event.target === overlay) closePreview(overlay);
        });
        document.addEventListener('keydown', onPreviewKeydown, true);
        document.body.appendChild(overlay);
    }

    async function uploadFile(form) {
        const button = form.querySelector('button[type="submit"]');
        if (button) button.disabled = true;
        try {
            await api('/api/uploads', { method: 'POST', body: new FormData(form) });
            showToast('Dosya yüklendi.', 'success');
            await navigate('/patient/uploads', { push: false });
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
            if (button) button.disabled = false;
        }
    }

    async function deleteUpload(id) {
        if (!await MedicalDialog.confirm('Bu dosya silinsin mi?', {
            title: 'Dosyayı sil', confirmText: 'Sil', cancelText: 'Vazgeç'
        })) return;
        try {
            await api('/api/uploads/' + encodeURIComponent(id), { method: 'DELETE' });
            showToast('Dosya silindi.', 'success');
            await navigate('/patient/uploads', { push: false });
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        }
    }

    async function deleteSelectedUploads() {
        const ids = Array.from(state.uploads.selected);
        if (!ids.length) return;
        if (!await MedicalDialog.confirm(ids.length + ' dosya kalıcı olarak silinsin mi?', {
            title: 'Seçilen dosyaları sil', confirmText: 'Tümünü sil', cancelText: 'Vazgeç'
        })) return;
        const button = document.getElementById('deleteSelectedUploadsBtn');
        if (button) button.disabled = true;
        let deleted = 0;
        for (const id of ids) {
            try {
                await api('/api/uploads/' + encodeURIComponent(id), { method: 'DELETE' });
                deleted += 1;
            } catch (error) {
                if (error instanceof AuthError) return;
                showToast(error.message, 'error');
            }
        }
        showToast(deleted + ' dosya silindi.', deleted === ids.length ? 'success' : 'error');
        await navigate('/patient/uploads', { push: false });
    }

    async function extractUpload(id, openResult) {
        const box = document.getElementById('extractResult');
        if (box) box.innerHTML = '<div class="alert alert-info show">Metin çıkarılıyor...</div>';
        try {
            const response = await api('/api/uploads/' + encodeURIComponent(id) + '/extract', {
                method: 'POST', body: {}
            });
            const data = response.data || {};
            const text = data.text || data.extracted_text || JSON.stringify(data);
            const item = state.uploads.items.find(function (row) { return row.id === id; });
            if (item) {
                item.extracted_text = text;
                item.extracted_at = new Date().toISOString();
                item.extraction_source = data.source || '';
            }
            renderUploadsTable();
            if (box) box.innerHTML = '<div class="extract-box markdown-body">' +
                (window.MedicalMarkdown ? MedicalMarkdown.render(text) : esc(text)) + '</div>';
            showToast('Metin çıkarıldı ve kaydedildi.', 'success');
            if (openResult) showUploadText(id);
        } catch (error) {
            if (error instanceof AuthError) return;
            if (box) box.innerHTML = '<div class="alert alert-error show">' + esc(error.message) + '</div>';
            showToast(error.message, 'error');
        }
    }

    /* ------------------------------------------------------------------ */
    /* Hatırlatmalar ve tercihler                                         */
    /* ------------------------------------------------------------------ */

    async function renderReminders() {
        const [listResponse, prefsResponse] = await Promise.all([
            api('/api/reminders'),
            api('/api/user/notification-preferences')
        ]);
        const items = listResponse.data || [];
        const prefs = prefsResponse.data || {};
        const rows = items.length ? items.map(function (item) {
            return '<tr><td>' + esc(item.type) + '</td>' +
                '<td>' + esc(item.title) + '</td>' +
                '<td>' + formatDateTime(item.due_date) + '</td>' +
                '<td class="actions-cell"><button type="button" class="btn btn-danger btn-sm" ' +
                'data-reminder-delete="' + item.id + '">Sil</button></td></tr>';
        }).join('') : '<tr><td colspan="4" class="empty">Aktif hatırlatma yok.</td></tr>';

        contentArea.innerHTML =
            '<div class="page-head"><h2 class="page-title">Hatırlatmalar</h2>' +
            '<p class="page-sub">İlaç, kontrol ve tahlil zamanlarınızı takip edin.</p></div>' +
            '<form class="card" data-form="reminder" id="reminderForm">' +
            '<div class="form-grid">' +
            '<div class="field"><label class="label" for="reminderType">Tip</label>' +
            '<select class="select" id="reminderType" name="type">' +
            '<option value="medication">İlaç</option><option value="checkup">Kontrol</option>' +
            '<option value="lab">Tahlil</option><option value="other">Diğer</option></select></div>' +
            '<div class="field"><label class="label" for="reminderTitle">Başlık</label>' +
            '<input class="input" id="reminderTitle" name="title" required placeholder="Örn. Kan basıncı ölçümü"></div>' +
            '<div class="field"><label class="label" for="reminderDue">Tarih ve saat</label>' +
            '<input class="input" id="reminderDue" name="due_date" type="datetime-local" required></div>' +
            '</div><div class="form-actions"><button type="submit" class="btn btn-primary">Hatırlatma ekle</button></div>' +
            '</form>' +
            '<div class="section-head"><div class="section-title">Aktif hatırlatmalar</div></div>' +
            '<div class="table-wrap"><table class="table"><thead><tr>' +
            '<th>Tip</th><th>Başlık</th><th>Zaman</th><th></th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
            '<div class="section-head"><div class="section-title">Bildirim tercihleri</div></div>' +
            '<form class="card" data-form="prefs" id="prefsForm">' +
            '<label class="check-row"><input type="checkbox" name="email_enabled"' +
            (prefs.email_enabled ? ' checked' : '') + '>' +
            '<span><span class="check-title">E-posta bildirimleri</span>' +
            '<span class="check-hint">Hatırlatmalar e-posta ile gönderilir.</span></span></label>' +
            '<label class="check-row"><input type="checkbox" name="push_enabled"' +
            (prefs.push_enabled ? ' checked' : '') + '>' +
            '<span><span class="check-title">Push bildirimleri</span>' +
            '<span class="check-hint">Tarayıcı bildirimleri için hazırlık.</span></span></label>' +
            '<div class="field" style="margin-top:16px"><label class="label" for="quietHours">Sessiz saatler</label>' +
            '<input class="input" id="quietHours" name="quiet_hours" placeholder="Örn. 22:00-07:00" ' +
            'value="' + esc(prefs.quiet_hours || '') + '"></div>' +
            '<div class="form-actions"><button type="submit" class="btn btn-primary">Tercihleri kaydet</button></div>' +
            '</form>';
    }

    async function addReminder(form) {
        const raw = form.elements.due_date.value;
        if (!raw) return;
        const due = new Date(raw);
        if (Number.isNaN(due.getTime())) {
            showToast('Geçerli bir tarih seçin.', 'error');
            return;
        }
        const payload = {
            type: form.elements.type.value,
            title: form.elements.title.value.trim(),
            due_date: due.toISOString()
        };
        const button = form.querySelector('button[type="submit"]');
        if (button) button.disabled = true;
        try {
            await api('/api/reminders', { method: 'POST', body: payload });
            showToast('Hatırlatma eklendi.', 'success');
            await navigate('/patient/reminders', { push: false });
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
            if (button) button.disabled = false;
        }
    }

    async function deleteReminder(id) {
        if (!await MedicalDialog.confirm('Bu hatırlatma silinsin mi?', {
            title: 'Hatırlatmayı sil', confirmText: 'Sil', cancelText: 'Vazgeç'
        })) return;
        try {
            await api('/api/reminders/' + encodeURIComponent(id), { method: 'DELETE' });
            showToast('Hatırlatma silindi.', 'success');
            await navigate('/patient/reminders', { push: false });
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        }
    }

    async function savePreferences(form) {
        const payload = {
            email_enabled: form.elements.email_enabled.checked,
            push_enabled: form.elements.push_enabled.checked,
            quiet_hours: form.elements.quiet_hours.value.trim() || null
        };
        try {
            await api('/api/user/notification-preferences', { method: 'PUT', body: payload });
            showToast('Tercihler kaydedildi.', 'success');
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        }
    }

    /* ------------------------------------------------------------------ */
    /* Profil                                                             */
    /* ------------------------------------------------------------------ */

    async function renderProfile() {
        const response = await api('/api/user/me');
        const profile = response.data || {};
        contentArea.innerHTML =
            '<div class="page-head"><h2 class="page-title">Profilim</h2>' +
            '<p class="page-sub">Kişisel bilgilerinizi güncelleyin.</p></div>' +
            '<form class="card" data-form="profile" id="profileForm" style="max-width:720px">' +
            '<div class="form-grid">' +
            '<div class="field"><label class="label" for="profileName">Ad Soyad</label>' +
            '<input class="input" id="profileName" name="full_name" value="' + esc(profile.full_name || '') + '" required></div>' +
            '<div class="field"><label class="label" for="profileCity">Şehir</label>' +
            '<input class="input" id="profileCity" name="city" value="' + esc(profile.city || '') + '"></div>' +
            '<div class="field"><label class="label" for="profileHeight">Boy (cm)</label>' +
            '<input class="input" id="profileHeight" name="height_cm" type="number" step="0.1" ' +
            'value="' + esc(profile.height_cm || '') + '"></div>' +
            '<div class="field"><label class="label" for="profileWeight">Kilo (kg)</label>' +
            '<input class="input" id="profileWeight" name="weight_kg" type="number" step="0.1" ' +
            'value="' + esc(profile.weight_kg || '') + '"></div>' +
            '<div class="field"><label class="label" for="profileBirth">Doğum yılı</label>' +
            '<input class="input" id="profileBirth" name="birth_year" type="number" ' +
            'value="' + esc(profile.birth_year || '') + '"></div>' +
            '<div class="field"><label class="label" for="profileEmail">E-posta</label>' +
            '<input class="input" id="profileEmail" value="' + esc(profile.email || (state.user && state.user.email) || '') + '" disabled></div>' +
            '</div><div class="form-actions"><button type="submit" class="btn btn-primary">Değişiklikleri kaydet</button></div>' +
            '</form>';
    }

    async function saveProfile(form) {
        const payload = {
            full_name: form.elements.full_name.value.trim(),
            city: form.elements.city.value.trim(),
            height_cm: form.elements.height_cm.value === '' ? null : Number(form.elements.height_cm.value),
            weight_kg: form.elements.weight_kg.value === '' ? null : Number(form.elements.weight_kg.value),
            birth_year: form.elements.birth_year.value === '' ? null : Number(form.elements.birth_year.value)
        };
        try {
            const response = await api('/api/user/me', { method: 'PUT', body: payload });
            state.user = response.data || state.user;
            localStorage.setItem(USER_KEY, JSON.stringify(state.user || {}));
            updateUserChip();
            showToast('Profil güncellendi.', 'success');
            await navigate('/patient/profile', { push: false });
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        }
    }

    /* ------------------------------------------------------------------ */
    /* Hasta bilgi tabanı (RAG)                                           */
    /* ------------------------------------------------------------------ */

    async function renderPatientRag() {
        contentArea.innerHTML =
            '<div class="page-head"><h2 class="page-title">Bilgi Tabanım</h2>' +
            '<p class="page-sub">Sohbetin yalnızca sizin gördüğünüz kaynaklarına metin ekleyin. ' +
            'Aynı kaynak adı yeniden yüklenirse eski parçalar değiştirilir.</p></div>' +
            '<form class="card" data-form="rag" id="patientRagForm" style="max-width:820px">' +
            '<div class="form-grid">' +
            '<div class="field"><label class="label" for="patientRagSource">Kaynak adı</label>' +
            '<input class="input" id="patientRagSource" name="source" required placeholder="Örn. notlarim"></div>' +
            '<div class="field"><label class="label" for="patientRagChunk">Parça boyutu</label>' +
            '<input class="input" id="patientRagChunk" name="chunk_size" type="number" value="800" min="100" max="4000"></div>' +
            '<div class="field"><label class="label" for="patientRagOverlap">Örtüşme</label>' +
            '<input class="input" id="patientRagOverlap" name="overlap" type="number" value="100" min="0" max="1000"></div>' +
            '</div><div class="field" style="margin-top:16px"><label class="label" for="patientRagText">Metin</label>' +
            '<textarea class="input" id="patientRagText" name="text" required placeholder="Eklenacak metin"></textarea></div>' +
            '<div class="form-actions"><button type="submit" class="btn btn-primary">Bilgi tabanına ekle</button></div>' +
            '</form><div id="ragResult"></div>' +
            '<div class="cards-grid" style="margin-top:16px">' +
            '<form class="card" data-form="rag-file" id="patientRagFileForm">' +
            '<div class="card-title" style="margin-bottom:14px">PDF / TXT yükle</div>' +
            '<div class="field"><label class="label" for="patientRagFileSource">Kaynak adı</label>' +
            '<input class="input" id="patientRagFileSource" name="source" required placeholder="Örn. prospektus:majezik"></div>' +
            '<div class="field" style="margin-top:12px"><label class="label" for="patientRagFile">Dosya</label>' +
            '<input class="input" id="patientRagFile" name="file" type="file" accept="application/pdf,text/plain" required></div>' +
            '<div class="form-actions"><button type="submit" class="btn btn-primary">Yükle ve ekle</button></div></form>' +
            '<form class="card" data-form="rag-url" id="patientRagUrlForm">' +
            '<div class="card-title" style="margin-bottom:14px">İlaç URL\'si içe aktar</div>' +
            '<div class="field"><label class="label" for="patientRagUrlSource">Kaynak adı</label>' +
            '<input class="input" id="patientRagUrlSource" name="source" required placeholder="Örn. prospektus:majezik"></div>' +
            '<div class="field" style="margin-top:12px"><label class="label" for="patientRagUrl">Prospektüs URL</label>' +
            '<input class="input" id="patientRagUrl" name="url" type="url" required placeholder="https://prospektus.co/ilaclar/..."></div>' +
            '<div class="form-actions"><button type="submit" class="btn btn-primary">Çek ve ekle</button></div></form>' +
            '<form class="card" data-form="drug-search" id="patientDrugSearchForm">' +
            '<div class="card-title" style="margin-bottom:14px">İlaç ara ve seç</div>' +
            '<div class="field"><label class="label" for="patientDrugQuery">İlaç adı</label>' +
            '<input class="input" id="patientDrugQuery" name="q" required placeholder="Örn. Majezik"></div>' +
            '<div class="form-actions"><button type="submit" class="btn btn-secondary">Ara</button></div>' +
            '<div id="patientDrugResults" class="status-list" style="margin-top:14px"></div></form>' +
            '</div>';
    }

    async function ingestPatientRag(form) {
        const payload = {
            source: form.elements.source.value.trim(),
            text: form.elements.text.value.trim(),
            chunk_size: Number(form.elements.chunk_size.value) || 800,
            overlap: Number(form.elements.overlap.value) || 0
        };
        const button = form.querySelector('button[type="submit"]');
        if (button) button.disabled = true;
        try {
            const response = await api('/api/rag/ingest', { method: 'POST', body: payload });
            const data = response.data || {};
            const box = document.getElementById('ragResult');
            if (box) {
                box.innerHTML = '<div class="alert alert-success show">' +
                    esc(formatNumber(data.chunks) + ' parça eklendi · model: ' + (data.model || '—')) + '</div>';
            }
            form.reset();
            showToast('Bilgi tabanı güncellendi.', 'success');
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function savePatientRagFile(form) {
        const button = form.querySelector('button[type="submit"]');
        if (button) button.disabled = true;
        try {
            const response = await api('/api/rag/upload', { method: 'POST', body: new FormData(form) });
            const info = response.data || {};
            showToast(formatNumber(info.chunks) + ' parça eklendi · ' + esc(info.filename || 'dosya'), 'success');
            form.reset();
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function savePatientRagUrl(form) {
        const payload = { source: form.elements.source.value.trim(), url: form.elements.url.value.trim() };
        const button = form.querySelector('button[type="submit"]');
        if (button) button.disabled = true;
        try {
            const response = await api('/api/rag/import-url', { method: 'POST', body: payload });
            const info = response.data || {};
            showToast(formatNumber(info.chunks) + ' parça eklendi · ' + esc(info.title || 'URL'), 'success');
            form.reset();
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function searchDrugsPatient(form) {
        const query = form.elements.q.value.trim();
        const box = document.getElementById('patientDrugResults');
        if (!box) return;
        box.innerHTML = loadingHTML('İlaçlar aranıyor...');
        try {
            const response = await api('/api/rag/drug-search?q=' + encodeURIComponent(query));
            const items = response.data || [];
            box.innerHTML = items.length ? items.map(function (item) {
                return '<div class="status-row" style="align-items:flex-start">' +
                    '<div><div class="status-label">' + esc(item.title) + '</div>' +
                    '<div class="status-hint">' + esc(item.url) + '</div></div>' +
                    '<button type="button" class="btn btn-primary btn-sm" data-drug-import="' +
                    esc(item.url) + '" data-drug-title="' + esc(item.title) + '">Ekle</button></div>';
            }).join('') : '<div class="empty" style="padding:16px">Sonuç bulunamadı.</div>';
        } catch (error) {
            if (error instanceof AuthError) return;
            box.innerHTML = '<div class="alert alert-error show">' + esc(error.message) + '</div>';
        }
    }

    async function importPatientDrugUrl(url, title) {
        const slug = String(url || '').split('/').filter(Boolean).pop() || 'ilac';
        try {
            const response = await api('/api/rag/import-url', {
                method: 'POST', body: { source: 'prospektus:' + slug, url: url }
            });
            const info = response.data || {};
            showToast((title || 'İlaç') + ' eklendi · ' + formatNumber(info.chunks) + ' parça', 'success');
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        }
    }

    /* ------------------------------------------------------------------ */
    /* Başlat                                                             */
    /* ------------------------------------------------------------------ */

    function init() {
        setupShell();
        if (!state.token) {
            renderAuth();
            return;
        }
        navigate(window.location.pathname, { push: false });
    }

    init();
})();
