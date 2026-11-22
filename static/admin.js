/**
 * Medical AI Admin Panel
 * Tek sayfa uygulama (SPA): auth gate + sayfa yönlendirme + tüm ekranlar.
 */
(function () {
    'use strict';

    const TOKEN_KEY = 'admin_token';
    const USER_KEY = 'admin_user';
    const API_BASE = '/admin/api';

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
        configMap: new Map(),
        healthUserId: null,
        healthUsers: [],
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

    function formatPercent(value) {
        if (value === null || value === undefined || value === '') return '0%';
        const number = Number(value);
        if (Number.isNaN(number)) return '0%';
        const percent = number <= 1 ? number * 100 : number;
        return percent.toLocaleString('tr-TR', { maximumFractionDigits: 1 }) + '%';
    }

    function clampPercent(value) {
        const number = Number(value);
        if (Number.isNaN(number)) return 0;
        return Math.max(0, Math.min(100, number));
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
        headers.set('Authorization', 'Bearer ' + state.token);

        let body = options.body;
        if (body && typeof body === 'object' && !(body instanceof FormData) &&
            !(body instanceof URLSearchParams)) {
            headers.set('Content-Type', 'application/json');
            body = JSON.stringify(body);
        }

        const response = await fetch(API_BASE + path, {
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
            window.location.replace('/admin/login');
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
        const name = user.full_name || 'Sistem Yöneticisi';
        const email = user.email || 'admin@medicalai.com';
        if (userName) userName.textContent = name;
        if (userEmail) userEmail.textContent = email;
        if (userAvatar) {
            userAvatar.textContent = (name.charAt(0) || 'A').toUpperCase();
        }
    }

    /* ------------------------------------------------------------------ */
    /* Yönlendirme / kabuk                                                */
    /* ------------------------------------------------------------------ */

    const PAGES = {
        '/admin': { key: 'dashboard', title: 'Dashboard', render: renderDashboard },
        '/admin/monitoring': { key: 'monitoring', title: 'Sistem İzleme', render: renderMonitoring },
        '/admin/config': { key: 'config', title: 'Sistem Config', render: renderConfig },
        '/admin/llm': { key: 'llm', title: 'LLM Ayarları', render: renderLlmSettings },
        '/admin/users': { key: 'users', title: 'Kullanıcılar', render: renderUsersPage },
        '/admin/storage': { key: 'storage', title: 'Disk Kullanımı', render: renderStorage },
        '/admin/health': { key: 'health', title: 'Sağlık Metrikleri', render: renderHealth },
        '/admin/db-config': { key: 'db-config', title: 'Veritabanı Ayarları', render: renderDbConfig }
    };

    function setActiveNav(path) {
        document.querySelectorAll('.nav-item[data-path]').forEach(function (item) {
            item.classList.toggle('active', item.getAttribute('data-path') === path);
        });
    }

    async function navigate(path, options) {
        options = options || {};
        const resolved = PAGES[path] || PAGES['/admin'];
        const effectivePath = PAGES[path] ? path : '/admin';

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

            const retry = event.target.closest('#retryBtn');
            if (retry) {
                navigate(window.location.pathname, { push: false });
                return;
            }

            const usersPageBtn = event.target.closest('[data-users-page]');
            if (usersPageBtn) {
                loadUsers(Number(usersPageBtn.getAttribute('data-users-page')) || 1);
                return;
            }

            const editConfigBtn = event.target.closest('[data-config-edit]');
            if (editConfigBtn) {
                beginConfigEdit(editConfigBtn.getAttribute('data-config-edit'));
                return;
            }

            const saveConfigBtn = event.target.closest('[data-config-save]');
            if (saveConfigBtn) {
                saveConfig(saveConfigBtn.getAttribute('data-config-save'));
                return;
            }

            const cancelConfigBtn = event.target.closest('[data-config-cancel]');
            if (cancelConfigBtn) {
                navigate('/admin/config', { push: false });
                return;
            }

            const healthDeleteBtn = event.target.closest('[data-health-delete]');
            if (healthDeleteBtn) {
                deleteHealthMetric(Number(healthDeleteBtn.getAttribute('data-health-delete')));
                return;
            }

            const testConnectionBtn = event.target.closest('[data-test-connection]');
            if (testConnectionBtn) {
                testConnection(testConnectionBtn.getAttribute('data-test-connection'));
            }
        });

        contentArea.addEventListener('keydown', function (event) {
            const input = event.target.closest('[data-config-input]');
            if (!input) return;
            if (event.key === 'Enter') {
                event.preventDefault();
                saveConfig(input.getAttribute('data-config-input'));
            } else if (event.key === 'Escape') {
                navigate('/admin/config', { push: false });
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
                    if (state.token) {
                        await api('/auth/logout', { method: 'POST' });
                    }
                } catch (error) {
                    // Token zaten geçersiz olabilir; yine de istemciyi temizle.
                } finally {
                    clearAuth();
                    window.location.replace('/admin/login');
                }
            });
        }

        window.addEventListener('popstate', function () {
            navigate(window.location.pathname, { push: false });
        });

        window.addEventListener('storage', function (event) {
            if (event.key === TOKEN_KEY && !event.newValue) {
                clearAuth();
                window.location.replace('/admin/login');
            }
        });
    }

    /* ------------------------------------------------------------------ */
    /* Dashboard                                                          */
    /* ------------------------------------------------------------------ */

    function statCard(icon, iconClass, value, label) {
        return '<div class="stat-card">' +
            '<div class="stat-icon ' + iconClass + '">' + icon + '</div>' +
            '<div><div class="stat-value">' + value + '</div>' +
            '<div class="stat-label">' + label + '</div></div></div>';
    }

    function statusBadge(connected) {
        return connected
            ? '<span class="badge badge-success"><span class="dot"></span>Bağlı</span>'
            : '<span class="badge badge-error"><span class="dot"></span>Bağlı değil</span>';
    }

    async function renderDashboard() {
        const response = await api('/monitoring');
        const data = response.data || {};
        const database = data.database || data.db || {};
        const redisInfo = data.redis || {};
        const llm = data.llm || {};
        const user = state.user || {};

        contentArea.innerHTML =
            '<div class="page-head">' +
            '<h2 class="page-title">Hoş geldiniz, ' + esc(user.full_name || 'Yönetici') + '</h2>' +
            '<p class="page-sub">Sistemin genel durumunu ve hızlı erişimleri buradan görüntüleyin.</p>' +
            '</div>' +
            '<div class="stats-grid">' +
            statCard('👥', '', formatNumber(data.active_sessions || 0), 'Son 24 saat aktif kullanıcı') +
            statCard('⚡', 'green', formatNumber(data.request_count_24h || 0), 'Son 24 saat istek') +
            statCard('⚠️', 'amber', formatPercent(data.error_rate), 'Hata oranı') +
            statCard('🗄️', 'red', formatPercent(data.redis_cache_hit_rate), 'Redis cache hit') +
            '</div>' +
            '<div class="cards-grid">' +
            '<div class="card">' +
            '<div class="card-head"><div class="card-title">Sistem Durumu</div>' +
            '<a class="btn btn-secondary btn-sm" href="/admin/monitoring" data-path="/admin/monitoring">Detay</a></div>' +
            '<div class="status-list">' +
            statusRow('PostgreSQL', statusBadge(!!database.connected),
                database.connected ? (esc(database.host || '') + ':' + esc(database.port || '')) : '') +
            statusRow('Redis', statusBadge(!!redisInfo.connected),
                redisInfo.connected ? (esc(redisInfo.host || '') + ':' + esc(redisInfo.port || '')) : '') +
            statusRow('LLM', llm.configured
                ? '<span class="badge badge-info"><span class="dot"></span>Yapılandırıldı</span>'
                : '<span class="badge badge-warning"><span class="dot"></span>Tanımlı değil</span>',
                esc(llm.model || '')) +
            '</div></div>' +
            '<div class="card">' +
            '<div class="card-head"><div class="card-title">Hızlı Erişim</div></div>' +
            '<div class="quick-actions">' +
            '<a class="btn btn-secondary" href="/admin/config" data-path="/admin/config">⚙️ Config</a>' +
            '<a class="btn btn-secondary" href="/admin/llm" data-path="/admin/llm">🧠 LLM Ayarları</a>' +
            '<a class="btn btn-secondary" href="/admin/users" data-path="/admin/users">👥 Kullanıcılar</a>' +
            '<a class="btn btn-secondary" href="/admin/storage" data-path="/admin/storage">💾 Disk Kullanımı</a>' +
            '<a class="btn btn-secondary" href="/admin/db-config" data-path="/admin/db-config">🗄️ Veritabanı</a>' +
            '</div>' +
            '<div class="card-note">Config ve veritabanı ayarlarını buradan yönetebilirsiniz.</div>' +
            '</div>' +
            '<div class="card">' +
            '<div class="card-head"><div class="card-title">Oturum</div></div>' +
            '<div class="kv-list">' +
            kvRow('Kullanıcı', esc(user.full_name || '—')) +
            kvRow('E-posta', esc(user.email || '—')) +
            kvRow('Rol', '<span class="badge badge-info">' + esc(user.role || 'admin') + '</span>') +
            kvRow('Son giriş', formatDateTime(user.last_login)) +
            '</div></div>' +
            '</div>';
    }

    function statusRow(label, badge, hint) {
        return '<div class="status-row"><span class="status-label">' + label + '</span>' +
            '<span class="status-value">' + badge + '</span></div>' +
            (hint ? '<div class="status-hint">' + hint + '</div>' : '');
    }

    function kvRow(key, value) {
        return '<div class="kv-row"><span class="k">' + esc(key) + '</span>' +
            '<span class="v">' + value + '</span></div>';
    }

    /* ------------------------------------------------------------------ */
    /* Sistem Config                                                      */
    /* ------------------------------------------------------------------ */

    function configValueDisplay(config) {
        const value = config.value === null || config.value === undefined || config.value === ''
            ? '—'
            : config.value;
        return '<span class="mono truncate-cell">' + esc(value) + '</span>';
    }

    async function renderConfig() {
        const response = await api('/config?limit=200');
        const configs = response.data || [];
        state.configMap = new Map(configs.map(function (item) { return [item.key, item]; }));

        const rows = configs.map(function (config) {
            return '<tr data-config-row="' + esc(config.key) + '" ' +
                'data-secret="' + (config.is_secret ? 'true' : 'false') + '" ' +
                'data-search="' + esc((config.key + ' ' + (config.description || '')).toLowerCase()) + '">' +
                '<td class="mono">' + esc(config.key) + '</td>' +
                '<td data-config-value="' + esc(config.key) + '">' + configValueDisplay(config) + '</td>' +
                '<td class="muted-cell">' + esc(config.description || '—') + '</td>' +
                '<td>' + formatDateTime(config.updated_at) + '</td>' +
                '<td class="actions-cell">' +
                '<button type="button" class="btn btn-secondary btn-sm" data-config-edit="' +
                esc(config.key) + '">Düzenle</button></td>' +
                '</tr>';
        }).join('');

        contentArea.innerHTML =
            '<div class="page-head">' +
            '<h2 class="page-title">Sistem Konfigürasyonu</h2>' +
            '<p class="page-sub">PostgreSQL, Redis, LLM ve RAG ayarlarını görüntüleyip güncelleyin. Gizli değerler maskelenir.</p>' +
            '</div>' +
            '<div class="toolbar">' +
            '<div class="toolbar-group">' +
            '<input type="search" class="input config-search" id="configSearch" placeholder="Ayar ara (key veya açıklama)...">' +
            '</div>' +
            '<div class="toolbar-group"><span class="hint">' + configs.length + ' ayar</span></div>' +
            '</div>' +
            '<div class="table-wrap"><table class="table">' +
            '<thead><tr><th>Key</th><th>Değer</th><th>Açıklama</th><th>Güncellenme</th><th></th></tr></thead>' +
            '<tbody id="configTableBody">' + rows +
            '<tr id="configNoResults" class="hidden"><td colspan="5" class="empty">Eşleşen ayar bulunamadı.</td></tr>' +
            '</tbody></table></div>';

        const search = document.getElementById('configSearch');
        if (search) {
            search.addEventListener('input', function () {
                const needle = search.value.trim().toLowerCase();
                let visible = 0;
                document.querySelectorAll('[data-config-row]').forEach(function (row) {
                    const match = !needle || (row.getAttribute('data-search') || '').indexOf(needle) !== -1;
                    row.classList.toggle('hidden', !match);
                    if (match) visible += 1;
                });
                const noResults = document.getElementById('configNoResults');
                if (noResults) noResults.classList.toggle('hidden', visible !== 0);
            });
        }
    }

    function beginConfigEdit(key) {
        const row = document.querySelector('[data-config-row="' + CSS.escape(key) + '"]');
        if (!row) return;
        const valueCell = row.querySelector('[data-config-value]');
        const actionsCell = row.querySelector('.actions-cell');
        const config = state.configMap.get(key) || {};
        const isSecret = row.getAttribute('data-secret') === 'true';

        valueCell.innerHTML = '<input type="' + (isSecret ? 'password' : 'text') + '" class="input inline-input" ' +
            'data-config-input="' + esc(key) + '" data-secret="' + (isSecret ? 'true' : 'false') + '" ' +
            'value="' + (isSecret ? '' : esc(config.value || '')) + '" ' +
            'placeholder="' + (isSecret ? 'Yeni gizli değer girin' : '') + '">' +
            (isSecret ? '<div class="hint">Mevcut değer güvenlik için gösterilmez.</div>' : '');

        actionsCell.innerHTML =
            '<button type="button" class="btn btn-primary btn-sm" data-config-save="' + esc(key) + '">Kaydet</button> ' +
            '<button type="button" class="btn btn-secondary btn-sm" data-config-cancel="1">İptal</button>';

        const input = valueCell.querySelector('input');
        if (input) input.focus();
    }

    async function saveConfig(key) {
        const input = document.querySelector('[data-config-input="' + CSS.escape(key) + '"]');
        if (!input) return;
        const value = input.value;
        const isSecret = input.getAttribute('data-secret') === 'true';

        if (isSecret && value.trim() === '') {
            showToast('Gizli ayar için yeni bir değer girmelisiniz.', 'error');
            input.focus();
            return;
        }

        input.disabled = true;
        try {
            await api('/config/' + encodeURIComponent(key), { method: 'PUT', body: { value: value } });
            showToast(key + ' güncellendi.', 'success');
            await navigate('/admin/config', { push: false });
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
            input.disabled = false;
        }
    }

    /* ------------------------------------------------------------------ */
    /* Kullanıcılar                                                       */
    /* ------------------------------------------------------------------ */

    async function renderUsersPage() {
        contentArea.innerHTML =
            '<div class="page-head">' +
            '<h2 class="page-title">Kullanıcılar</h2>' +
            '<p class="page-sub">Sistemdeki kullanıcıları rol ve durumlarına göre filtreleyin.</p>' +
            '</div>' +
            '<div class="toolbar">' +
            '<div class="toolbar-group">' +
            '<input type="search" class="input" id="userSearch" placeholder="E-posta ile ara..." style="min-width:220px">' +
            '<select class="select" id="userRoleFilter" style="width:auto">' +
            '<option value="">Tüm roller</option>' +
            '<option value="admin">Admin</option>' +
            '<option value="patient">Patient</option>' +
            '</select>' +
            '<select class="select" id="userActiveFilter" style="width:auto">' +
            '<option value="">Tüm durumlar</option>' +
            '<option value="true">Aktif</option>' +
            '<option value="false">Pasif</option>' +
            '</select>' +
            '<button type="button" class="btn btn-secondary btn-sm" id="userResetBtn">Sıfırla</button>' +
            '</div>' +
            '</div>' +
            '<div id="usersTable"></div>';

        const search = document.getElementById('userSearch');
        const role = document.getElementById('userRoleFilter');
        const active = document.getElementById('userActiveFilter');
        const reset = document.getElementById('userResetBtn');

        let timer = null;
        if (search) {
            search.addEventListener('input', function () {
                clearTimeout(timer);
                timer = setTimeout(function () { loadUsers(1); }, 300);
            });
            search.addEventListener('keydown', function (event) {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    loadUsers(1);
                }
            });
        }
        if (role) role.addEventListener('change', function () { loadUsers(1); });
        if (active) active.addEventListener('change', function () { loadUsers(1); });
        if (reset) {
            reset.addEventListener('click', function () {
                if (search) search.value = '';
                if (role) role.value = '';
                if (active) active.value = '';
                loadUsers(1);
            });
        }

        await loadUsers(1);
    }

    async function loadUsers(page) {
        const container = document.getElementById('usersTable');
        if (!container) return;
        container.innerHTML = loadingHTML('Kullanıcılar yükleniyor...');

        const params = new URLSearchParams({ page: String(page || 1), per_page: '20' });
        const search = document.getElementById('userSearch');
        const role = document.getElementById('userRoleFilter');
        const active = document.getElementById('userActiveFilter');
        if (search && search.value.trim()) params.set('email', search.value.trim());
        if (role && role.value) params.set('role', role.value);
        if (active && active.value) params.set('is_active', active.value);

        try {
            const response = await api('/users?' + params.toString());
            renderUsersTable(response.data || [], response.pagination || {});
        } catch (error) {
            if (error instanceof AuthError) return;
            container.innerHTML = '<div class="table-wrap"><div class="empty">' + esc(error.message) + '</div></div>';
        }
    }

    function renderUsersTable(users, pagination) {
        const container = document.getElementById('usersTable');
        if (!container) return;

        const rows = users.map(function (user) {
            const roleClass = user.role === 'admin' ? 'badge-info' : 'badge-success';
            return '<tr>' +
                '<td class="mono">' + esc(user.user_id) + '</td>' +
                '<td>' + esc(user.email) + '</td>' +
                '<td>' + esc(user.full_name || '—') + '</td>' +
                '<td><span class="badge ' + roleClass + '">' + esc(user.role) + '</span></td>' +
                '<td>' + (user.is_active
                    ? '<span class="badge badge-success"><span class="dot"></span>Aktif</span>'
                    : '<span class="badge badge-warning"><span class="dot"></span>Pasif</span>') + '</td>' +
                '<td>' + formatDateTime(user.created_at) + '</td>' +
                '<td>' + formatDateTime(user.last_login) + '</td>' +
                '</tr>';
        }).join('');

        const total = pagination.total || 0;
        const totalPages = pagination.total_pages || 1;
        const current = pagination.page || 1;

        let paginationHTML = '';
        if (totalPages > 1) {
            const buttons = [];
            for (let index = 1; index <= totalPages; index += 1) {
                buttons.push('<button type="button" class="btn btn-sm ' +
                    (index === current ? 'btn-primary' : 'btn-secondary') +
                    '" data-users-page="' + index + '">' + index + '</button>');
            }
            paginationHTML = '<div class="pagination">' + buttons.join('') + '</div>';
        }

        container.innerHTML =
            '<div class="table-wrap"><table class="table">' +
            '<thead><tr><th>ID</th><th>E-posta</th><th>Ad Soyad</th><th>Rol</th>' +
            '<th>Durum</th><th>Kayıt</th><th>Son Giriş</th></tr></thead>' +
            '<tbody>' + (rows || '<tr><td colspan="7" class="empty">Kullanıcı bulunamadı.</td></tr>') +
            '</tbody></table></div>' +
            '<div class="table-foot">Toplam ' + formatNumber(total) + ' kullanıcı · Sayfa ' +
            esc(current) + ' / ' + esc(totalPages) + '</div>' +
            paginationHTML;
    }

    /* ------------------------------------------------------------------ */
    /* Disk Kullanımı (kullanıcı bazlı)                                  */
    /* ------------------------------------------------------------------ */

    const STORAGE_TYPE_LABELS = {
        pdf: 'PDF', image: 'Görseller', text: 'Metin', other: 'Diğer'
    };

    async function renderStorage() {
        contentArea.innerHTML =
            '<div class="page-head"><h2 class="page-title">Disk Kullanımı</h2>' +
            '<p class="page-sub">Yüklenen dosyaların kullanıcı bazında disk kullanımı.</p></div>' +
            '<div class="table-wrap"><div class="empty">İstatistikler yükleniyor...</div></div>';

        try {
            const response = await api('/uploads/stats');
            const data = response.data || {};
            const summary = data.summary || {};
            const byType = data.by_type || [];
            const byUser = data.by_user || [];
            const recent = data.recent || [];
            const totalBytes = Number(summary.total_bytes) || 0;

            const typeRows = byType.length
                ? byType.map(function (item) {
                    const pct = totalBytes ? (Number(item.bytes) / totalBytes) * 100 : 0;
                    const label = STORAGE_TYPE_LABELS[item.type] || item.type;
                    return resourceRow(label + ' · ' + formatNumber(item.count) + ' dosya',
                        pct, formatBytes(item.bytes));
                }).join('')
                : '<div class="empty">Henüz dosya yok.</div>';

            const userRows = byUser.length
                ? byUser.map(function (user) {
                    const types = user.types || {};
                    const share = totalBytes
                        ? (Number(user.total_bytes) / totalBytes) * 100 : 0;
                    const breakdown = [
                        ['PDF', types.pdf], ['Görsel', types.image],
                        ['Metin', types.text], ['Diğer', types.other]
                    ].filter(function (pair) { return Number(pair[1]) > 0; })
                     .map(function (pair) { return pair[0] + ': ' + pair[1]; }).join(' · ') || '—';
                    return '<tr>' +
                        '<td>' + esc(user.full_name || '—') + '<div class="hint">' + esc(user.email) + '</div></td>' +
                        '<td class="mono">' + esc(user.user_id) + '</td>' +
                        '<td>' + formatNumber(user.file_count) + '</td>' +
                        '<td>' + formatBytes(user.total_bytes) + '</td>' +
                        '<td>' + formatNumber(share, 1) + '%</td>' +
                        '<td>' + esc(breakdown) + '</td>' +
                        '<td>' + formatDateTime(user.last_upload) + '</td>' +
                        '</tr>';
                }).join('')
                : '<tr><td colspan="7" class="empty">Henüz dosya yükleyen kullanıcı yok.</td></tr>';

            const recentRows = recent.length
                ? recent.map(function (item) {
                    return '<tr>' +
                        '<td>' + esc(item.full_name || '—') + '<div class="hint">' + esc(item.email) + '</div></td>' +
                        '<td>' + esc(item.filename) + '</td>' +
                        '<td>' + formatBytes(item.size) + '</td>' +
                        '<td>' + formatDateTime(item.uploaded_at) + '</td>' +
                        '</tr>';
                }).join('')
                : '<tr><td colspan="4" class="empty">Son yükleme yok.</td></tr>';

            contentArea.innerHTML =
                '<div class="page-head">' +
                '<h2 class="page-title">Disk Kullanımı</h2>' +
                '<p class="page-sub">Yüklenen dosyaların kullanıcı bazında disk kullanımı. ' +
                'Dosya içerikleri gösterilmez.</p>' +
                '</div>' +
                '<div class="stats-grid">' +
                statCard('📁', '', formatNumber(summary.total_files || 0), 'Toplam dosya') +
                statCard('💾', 'green', formatBytes(summary.total_bytes || 0), 'Toplam disk kullanımı') +
                statCard('👥', 'amber', formatNumber(summary.users_with_uploads || 0), 'Dosya yükleyen kullanıcı') +
                statCard('📊', 'red', formatBytes(summary.avg_bytes || 0), 'Ortalama dosya boyutu') +
                '</div>' +
                '<div class="cards-grid">' +
                '<div class="card"><div class="card-head"><div class="card-title">Tür Dağılımı</div></div>' +
                typeRows + '</div>' +
                '<div class="card"><div class="card-head"><div class="card-title">Son Yüklemeler</div></div>' +
                '<div class="table-wrap"><table class="table">' +
                '<thead><tr><th>Kullanıcı</th><th>Dosya</th><th>Boyut</th><th>Tarih</th></tr></thead>' +
                '<tbody>' + recentRows + '</tbody></table></div></div>' +
                '</div>' +
                '<div class="section-head"><h3 class="section-title">Kullanıcı Bazlı Kullanım</h3></div>' +
                '<div class="table-wrap"><table class="table">' +
                '<thead><tr><th>Kullanıcı</th><th>ID</th><th>Dosya</th><th>Toplam Boyut</th>' +
                '<th>Pay</th><th>Türler</th><th>Son Yükleme</th></tr></thead>' +
                '<tbody>' + userRows + '</tbody></table></div>' +
                '<div class="table-foot">Toplam ' + formatNumber(summary.total_files || 0) +
                ' dosya · ' + formatBytes(summary.total_bytes || 0) + '</div>';
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
            contentArea.innerHTML =
                '<div class="page-head"><h2 class="page-title">Disk Kullanımı</h2></div>' +
                '<div class="table-wrap"><div class="empty">İstatistikler yüklenemedi: ' +
                esc(error.message) + '</div></div>';
        }
    }

    /* ------------------------------------------------------------------ */
    /* Sağlık Metrikleri                                                  */
    /* ------------------------------------------------------------------ */

    async function renderHealth() {
        const usersResponse = await api('/users?page=1&per_page=100');
        const users = usersResponse.data || [];

        if (!users.length) {
            contentArea.innerHTML =
                '<div class="page-head"><h2 class="page-title">Sağlık Metrikleri</h2></div>' +
                '<div class="table-wrap"><div class="empty">Sağlık metriği eklemek için önce bir kullanıcı oluşturmalısınız.</div></div>';
            return;
        }

        const existing = users.find(function (user) { return user.user_id === state.healthUserId; });
        state.healthUserId = existing ? existing.user_id : users[0].user_id;
        state.healthUsers = users;

        const options = users.map(function (user) {
            return '<option value="' + esc(user.user_id) + '" ' +
                (user.user_id === state.healthUserId ? 'selected' : '') + '>' +
                esc(user.full_name || user.email) + ' · ' + esc(user.email) + '</option>';
        }).join('');

        contentArea.innerHTML =
            '<div class="page-head">' +
            '<h2 class="page-title">Sağlık Metrikleri</h2>' +
            '<p class="page-sub">Kullanıcı bazlı sağlık ölçümlerini görüntüleyin, ekleyin ve silin.</p>' +
            '</div>' +
            '<div class="toolbar">' +
            '<div class="toolbar-group">' +
            '<label class="label" for="healthUserSelect">Kullanıcı</label>' +
            '<select class="select" id="healthUserSelect" style="min-width:280px">' + options + '</select>' +
            '</div>' +
            '<div class="toolbar-group"><span class="hint">İstatistikler son 30 günü kapsar.</span></div>' +
            '</div>' +
            '<div class="stats-grid" id="healthStats"></div>' +
            '<div class="cards-grid">' +
            '<div class="card">' +
            '<div class="card-head"><div class="card-title">Yeni Ölçüm Ekle</div></div>' +
            '<form id="healthForm" class="form-grid">' +
            '<div class="field"><label class="label" for="metricName">Metrik</label>' +
            '<input class="input" id="metricName" list="metricNames" placeholder="weight" required>' +
            '<datalist id="metricNames"><option value="weight"><option value="heart_rate">' +
            '<option value="blood_pressure"><option value="glucose"><option value="temperature">' +
            '<option value="oxygen_saturation"></datalist></div>' +
            '<div class="field"><label class="label" for="metricValue">Değer</label>' +
            '<input class="input" id="metricValue" type="number" step="0.01" placeholder="72.5" required></div>' +
            '<div class="field"><label class="label" for="metricUnit">Birim</label>' +
            '<input class="input" id="metricUnit" placeholder="kg, bpm, %" ></div>' +
            '<div class="field field-action"><button type="submit" class="btn btn-primary" id="healthSubmitBtn">Ekle</button></div>' +
            '</form>' +
            '</div>' +
            '<div class="card">' +
            '<div class="card-head"><div class="card-title">Seçili Kullanıcı</div></div>' +
            '<div class="kv-list" id="healthUserInfo"></div>' +
            '</div>' +
            '</div>' +
            '<div class="section-head"><h3 class="section-title">Ölçümler</h3></div>' +
            '<div id="healthTable"></div>';

        const select = document.getElementById('healthUserSelect');
        if (select) {
            select.addEventListener('change', function () {
                state.healthUserId = Number(select.value);
                loadHealth();
            });
        }

        const form = document.getElementById('healthForm');
        if (form) form.addEventListener('submit', handleHealthSubmit);

        await loadHealth();
    }

    async function loadHealth() {
        const userId = state.healthUserId;
        if (!userId) return;

        const table = document.getElementById('healthTable');
        if (table) table.innerHTML = loadingHTML('Sağlık metrikleri yükleniyor...');

        const user = (state.healthUsers || []).find(function (item) {
            return item.user_id === Number(userId);
        });
        const userInfo = document.getElementById('healthUserInfo');
        if (userInfo) {
            userInfo.innerHTML =
                kvRow('Kullanıcı', esc(user ? (user.full_name || '—') : '—')) +
                kvRow('E-posta', esc(user ? user.email : '—')) +
                kvRow('Rol', '<span class="badge badge-info">' + esc(user ? user.role : '—') + '</span>') +
                kvRow('Kullanıcı ID', esc(userId));
        }

        try {
            const results = await Promise.all([
                api('/health/metrics?user_id=' + encodeURIComponent(userId) + '&limit=100'),
                api('/health/stats?user_id=' + encodeURIComponent(userId) + '&days=30')
            ]);
            renderHealthStats(results[1].data || {});
            renderHealthTable(results[0].data || []);
        } catch (error) {
            if (error instanceof AuthError) return;
            if (table) {
                table.innerHTML = '<div class="table-wrap"><div class="empty">' + esc(error.message) + '</div></div>';
            }
        }
    }

    function renderHealthStats(stats) {
        const container = document.getElementById('healthStats');
        if (!container) return;
        container.innerHTML =
            statCard('🧾', '', formatNumber(stats.count || 0), 'Ölçüm sayısı (30 gün)') +
            statCard('📊', 'green', formatNumber(stats.avg_value), 'Ortalama') +
            statCard('⬇️', 'amber', formatNumber(stats.min_value), 'Minimum') +
            statCard('⬆️', 'red', formatNumber(stats.max_value), 'Maksimum');
    }

    function renderHealthTable(metrics) {
        const container = document.getElementById('healthTable');
        if (!container) return;

        const rows = metrics.map(function (metric) {
            return '<tr>' +
                '<td>' + formatDateTime(metric.recorded_at) + '</td>' +
                '<td><span class="badge badge-info">' + esc(metric.metric_name) + '</span></td>' +
                '<td class="mono">' + formatNumber(metric.value) + '</td>' +
                '<td>' + esc(metric.unit || '—') + '</td>' +
                '<td class="actions-cell"><button type="button" class="btn btn-danger btn-sm" ' +
                'data-health-delete="' + esc(metric.metric_id) + '">Sil</button></td>' +
                '</tr>';
        }).join('');

        container.innerHTML =
            '<div class="table-wrap"><table class="table">' +
            '<thead><tr><th>Kayıt Zamanı</th><th>Metrik</th><th>Değer</th><th>Birim</th><th></th></tr></thead>' +
            '<tbody>' + (rows || '<tr><td colspan="5" class="empty">Bu kullanıcı için ölçüm bulunamadı.</td></tr>') +
            '</tbody></table></div>';
    }

    async function handleHealthSubmit(event) {
        event.preventDefault();
        const nameInput = document.getElementById('metricName');
        const valueInput = document.getElementById('metricValue');
        const unitInput = document.getElementById('metricUnit');
        const submit = document.getElementById('healthSubmitBtn');

        const metricName = nameInput.value.trim();
        const value = Number(valueInput.value);
        const unit = unitInput.value.trim();

        if (!metricName) {
            showToast('Metrik adı zorunludur.', 'error');
            nameInput.focus();
            return;
        }
        if (!Number.isFinite(value)) {
            showToast('Geçerli bir sayısal değer girin.', 'error');
            valueInput.focus();
            return;
        }

        submit.disabled = true;
        try {
            await api('/health/metrics?user_id=' + encodeURIComponent(state.healthUserId), {
                method: 'POST',
                body: {
                    metric_name: metricName,
                    value: value,
                    unit: unit || null
                }
            });
            showToast('Ölçüm eklendi.', 'success');
            valueInput.value = '';
            await loadHealth();
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        } finally {
            submit.disabled = false;
        }
    }

    async function deleteHealthMetric(metricId) {
        if (!metricId) return;
        if (!window.confirm('Bu ölçümü silmek istediğinize emin misiniz?')) return;
        try {
            await api('/health/metrics/' + encodeURIComponent(metricId) +
                '?user_id=' + encodeURIComponent(state.healthUserId), { method: 'DELETE' });
            showToast('Ölçüm silindi.', 'success');
            await loadHealth();
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
        }
    }

    /* ------------------------------------------------------------------ */
    /* Sistem İzleme                                                      */
    /* ------------------------------------------------------------------ */

    function resourceRow(label, percent, detail) {
        const safe = clampPercent(percent);
        return '<div class="resource-row">' +
            '<div class="resource-head"><span>' + esc(label) + '</span><span>' +
            formatPercent(safe) + '</span></div>' +
            '<div class="progress"><div class="progress-bar" style="width:' + safe + '%"></div></div>' +
            (detail ? '<div class="hint">' + esc(detail) + '</div>' : '') +
            '</div>';
    }

    async function renderMonitoring() {
        const response = await api('/monitoring');
        const data = response.data || {};
        const database = data.database || data.db || {};
        const redisInfo = data.redis || {};
        const llm = data.llm || {};
        const system = data.system || {};
        const connections = data.db_connections || {};

        contentArea.innerHTML =
            '<div class="page-head">' +
            '<h2 class="page-title">Sistem İzleme</h2>' +
            '<p class="page-sub">Servis bağlantıları, kaynak kullanımı ve çalışma zamanı bilgileri.</p>' +
            '</div>' +
            '<div class="stats-grid">' +
            statCard('🖥️', '', formatPercent(system.cpu_percent), 'CPU kullanımı') +
            statCard('🧠', 'green', formatPercent(system.memory_percent), 'Bellek kullanımı') +
            statCard('💾', 'amber', formatPercent(system.disk_percent), 'Disk kullanımı') +
            statCard('⏱️', 'red', formatNumber(system.uptime_hours, 1) + ' sa', 'Sunucu çalışma süresi') +
            '</div>' +
            '<div class="cards-grid">' +
            '<div class="card">' +
            '<div class="card-head"><div class="card-title">Bağlantılar</div>' +
            statusBadge(!!database.connected && !!redisInfo.connected) + '</div>' +
            '<div class="status-list">' +
            statusRow('PostgreSQL', statusBadge(!!database.connected),
                database.connected
                    ? esc(database.name || '') + ' · ' + esc(database.host || '') + ':' + esc(database.port || '') +
                      (database.latency_ms !== undefined ? ' · ' + formatNumber(database.latency_ms, 1) + ' ms' : '')
                    : esc(database.error || '')) +
            statusRow('Redis', statusBadge(!!redisInfo.connected),
                redisInfo.connected
                    ? esc(redisInfo.host || '') + ':' + esc(redisInfo.port || '') +
                      (redisInfo.latency_ms !== undefined ? ' · ' + formatNumber(redisInfo.latency_ms, 1) + ' ms' : '')
                    : esc(redisInfo.error || '')) +
            statusRow('LLM', llm.configured
                ? '<span class="badge badge-info"><span class="dot"></span>Yapılandırıldı</span>'
                : '<span class="badge badge-warning"><span class="dot"></span>Tanımlı değil</span>',
                esc(llm.model || '')) +
            '</div></div>' +
            '<div class="card">' +
            '<div class="card-head"><div class="card-title">Veritabanı Havuzu</div></div>' +
            '<div class="kv-list">' +
            kvRow('Aktif bağlantı', formatNumber(connections.active || 0)) +
            kvRow('Maksimum bağlantı', formatNumber(connections.max || 0)) +
            kvRow('Kullanım', formatPercent(connections.max
                ? (Number(connections.active || 0) / Number(connections.max)) : 0)) +
            '</div></div>' +
            '<div class="card">' +
            '<div class="card-head"><div class="card-title">Kaynak Kullanımı</div></div>' +
            resourceRow('CPU', system.cpu_percent, 'Süreç: ' + formatNumber(system.process_cpu_percent, 1) + '%') +
            resourceRow('Bellek', system.memory_percent,
                formatNumber(system.memory_used_mb, 0) + ' MB / ' + formatNumber(system.memory_total_mb, 0) + ' MB') +
            resourceRow('Disk', system.disk_percent,
                formatNumber(system.disk_used_gb, 1) + ' GB / ' + formatNumber(system.disk_total_gb, 1) + ' GB') +
            '</div>' +
            '<div class="card">' +
            '<div class="card-head"><div class="card-title">Uygulama</div></div>' +
            '<div class="kv-list">' +
            kvRow('Aktif kullanıcı (24s)', formatNumber(data.active_sessions || 0)) +
            kvRow('İstek (24s)', formatNumber(data.request_count_24h || 0)) +
            kvRow('Hata oranı', formatPercent(data.error_rate)) +
            kvRow('Cache hit oranı', formatPercent(data.redis_cache_hit_rate)) +
            kvRow('Süreç belleği', formatNumber(system.process_memory_mb, 1) + ' MB') +
            '</div></div>' +
            '</div>';
    }

    /* ------------------------------------------------------------------ */
    /* Veritabanı / Redis Ayarları                                        */
    /* ------------------------------------------------------------------ */

    function configInput(configs, key, label, type, hint, placeholder) {
        const config = configs.get(key) || {};
        const isSecret = !!config.is_secret || type === 'password';
        const hasSavedSecret = isSecret && !!String(config.value || '').trim();
        const value = isSecret ? '' : (config.value === undefined || config.value === null ? '' : config.value);
        const savedNote = hasSavedSecret
            ? '<span class="hint">✅ Kayıtlı değer var (güvenlik için gösterilmez). Boş bırakırsanız korunur.</span>'
            : '';
        return '<div class="field">' +
            '<label class="label" for="cfg-' + esc(key) + '">' + esc(label) + '</label>' +
            '<input class="input" id="cfg-' + esc(key) + '" type="' + esc(type) + '" ' +
            'data-config-key="' + esc(key) + '" data-secret="' + (isSecret ? 'true' : 'false') + '" ' +
            'value="' + esc(value) + '" ' +
            'placeholder="' + esc(hasSavedSecret ? 'Değiştirmek için yeni değer girin' : (placeholder || '')) + '">' +
            savedNote + (hint ? '<span class="hint">' + esc(hint) + '</span>' : '') +
            '</div>';
    }

    async function renderDbConfig() {
        const response = await api('/config?limit=200');
        const configs = new Map((response.data || []).map(function (item) { return [item.key, item]; }));

        contentArea.innerHTML =
            '<div class="page-head">' +
            '<h2 class="page-title">Veritabanı Ayarları</h2>' +
            '<p class="page-sub">PostgreSQL ve Redis bağlantı bilgilerini yönetin. Değişiklikler kaydedildikten sonra uygulanır.</p>' +
            '</div>' +
            '<div id="dbTestResult" class="alert"></div>' +
            '<div class="cards-grid">' +
            '<div class="card">' +
            '<div class="card-head"><div class="card-title">PostgreSQL</div>' +
            '<span class="badge badge-info">Bağlantı</span></div>' +
            '<div class="form-grid">' +
            configInput(configs, 'db_host', 'DB Host', 'text', 'PostgreSQL sunucu adresi', '') +
            configInput(configs, 'db_port', 'DB Port', 'number', 'Varsayılan: 5432', '') +
            configInput(configs, 'db_name', 'DB Adı', 'text', 'Veritabanı adı', '') +
            configInput(configs, 'db_user', 'DB Kullanıcısı', 'text', 'PostgreSQL kullanıcısı', '') +
            configInput(configs, 'db_password', 'DB Şifresi', 'password',
                'Gizli değer gösterilmez. Değiştirmek için yeni şifre girin.', '') +
            '</div>' +
            '<div class="form-actions">' +
            '<button type="button" class="btn btn-primary" id="saveDbConfigBtn">Değişiklikleri Kaydet</button>' +
            '<button type="button" class="btn btn-secondary" data-test-connection="db">Bağlantıyı Test Et</button>' +
            '</div>' +
            '</div>' +
            '<div class="card">' +
            '<div class="card-head"><div class="card-title">Redis</div>' +
            '<span class="badge badge-info">Cache</span></div>' +
            '<div class="form-grid">' +
            configInput(configs, 'redis_host', 'Redis Host', 'text', 'Redis sunucu adresi', '') +
            configInput(configs, 'redis_port', 'Redis Port', 'number', 'Varsayılan: 6379', '') +
            configInput(configs, 'redis_password', 'Redis Şifresi', 'password',
                'Gizli değer gösterilmez. Değiştirmek için yeni şifre girin.', '') +
            '</div>' +
            '<div class="form-actions">' +
            '<button type="button" class="btn btn-primary" id="saveDbConfigBtn2">Değişiklikleri Kaydet</button>' +
            '<button type="button" class="btn btn-secondary" data-test-connection="redis">Bağlantıyı Test Et</button>' +
            '</div>' +
            '</div>' +
            '<div class="card">' +
            '<div class="card-head"><div class="card-title">Ortam Bilgisi</div></div>' +
            '<div class="kv-list">' +
            kvRow('DB', esc((configs.get('db_user') || {}).value || '') + '@' +
                esc((configs.get('db_host') || {}).value || '') + ':' +
                esc((configs.get('db_port') || {}).value || '')) +
            kvRow('Veritabanı', esc((configs.get('db_name') || {}).value || '—')) +
            kvRow('Redis', esc((configs.get('redis_host') || {}).value || '') + ':' +
                esc((configs.get('redis_port') || {}).value || '')) +
            kvRow('Config kaynağı', '<span class="badge badge-info">system_config</span>') +
            '</div>' +
            '<div class="card-note">Bağlantı değişikliklerinin bazıları uygulamanın yeniden başlatılmasını gerektirebilir.</div>' +
            '</div>' +
            '</div>';

        const saveButtons = [
            document.getElementById('saveDbConfigBtn'),
            document.getElementById('saveDbConfigBtn2')
        ];
        saveButtons.forEach(function (button) {
            if (button) button.addEventListener('click', saveDbConfig);
        });
    }

    /* ------------------------------------------------------------------ */
    /* LLM Ayarları                                                       */
    /* ------------------------------------------------------------------ */

    const LLM_PROVIDERS = [
        { value: 'openai', label: 'OpenAI' },
        { value: 'ollama', label: 'Ollama / Yerel' },
        { value: 'custom', label: 'OpenAI uyumlu (özel)' }
    ];

    const LLM_DEFAULT_BASE_URLS = {
        openai: 'https://api.openai.com/v1',
        ollama: 'http://localhost:11434'
    };

    function collectConfigUpdates(includeEmptyNonSecret) {
        const inputs = Array.from(contentArea.querySelectorAll('[data-config-key]'));
        const updates = [];

        inputs.forEach(function (input) {
            // Devre dışı bırakılmış alanlar mevcut değeri korur (ör. ana LLM
            // vision desteklediğinde ikinci LLM alanları).
            if (input.disabled) return;

            const key = input.getAttribute('data-config-key');
            const isSecret = input.getAttribute('data-secret') === 'true';
            const isBool = input.getAttribute('data-type') === 'bool';
            let value;

            if (isBool) {
                value = input.checked ? 'true' : 'false';
            } else {
                value = input.value.trim();
            }

            // Gizli alanlar boş bırakıldıysa mevcut değer korunur.
            if (isSecret && value === '') return;
            // Gizli olmayan boş alanlar varsayılan olarak atlanır.
            if (!isBool && !includeEmptyNonSecret && value === '') return;

            updates.push([key, value]);
        });

        return updates;
    }

    function isConfigTrue(configs, key) {
        const config = configs.get(key) || {};
        return String(config.value || 'false').toLowerCase() === 'true';
    }

    function providerOptions(selected) {
        const current = selected || 'openai';
        const known = LLM_PROVIDERS.some(function (provider) {
            return provider.value === current;
        });
        let html = LLM_PROVIDERS.map(function (provider) {
            return '<option value="' + esc(provider.value) + '" ' +
                (provider.value === current ? 'selected' : '') + '>' +
                esc(provider.label) + '</option>';
        }).join('');
        if (!known) {
            html += '<option value="' + esc(current) + '" selected>' + esc(current) + ' (özel)</option>';
        }
        return html;
    }

    function providerSelect(configs, key, id, label, hint) {
        const config = configs.get(key) || {};
        return '<div class="field">' +
            '<label class="label" for="' + esc(id) + '">' + esc(label) + '</label>' +
            '<select class="select" id="' + esc(id) + '" data-config-key="' + esc(key) + '">' +
            providerOptions(config.value) + '</select>' +
            (hint ? '<span class="hint">' + esc(hint) + '</span>' : '') +
            '</div>';
    }

    function checkboxInput(configs, key, id, title, hint) {
        return '<label class="check-row" for="' + esc(id) + '">' +
            '<input type="checkbox" id="' + esc(id) + '" data-config-key="' + esc(key) + '" ' +
            'data-type="bool" ' + (isConfigTrue(configs, key) ? 'checked' : '') + '>' +
            '<span><span class="check-title">' + esc(title) + '</span>' +
            '<span class="check-hint">' + esc(hint) + '</span></span>' +
            '</label>';
    }

    function setModelStatus(scope, message, type) {
        const status = document.getElementById('models-status-' + scope);
        if (!status) return;
        status.className = 'hint model-status status-' + (type || 'info');
        status.textContent = message;
    }

    function modelOptions(current, models) {
        const list = Array.isArray(models) ? models : [];
        const hasCurrent = !!current && list.indexOf(current) !== -1;
        let html = '';

        if (!current) {
            html += '<option value=""' + (list.length ? '' : ' selected') + '>-- Model seçin --</option>';
        } else if (!hasCurrent) {
            html += '<option value="' + esc(current) + '" selected>(mevcut: ' + esc(current) + ')</option>';
        }

        list.forEach(function (model, index) {
            const selected = current ? model === current : index === 0;
            html += '<option value="' + esc(model) + '"' + (selected ? ' selected' : '') + '>' + esc(model) + '</option>';
        });

        if (!current && !list.length) {
            html = '<option value="" selected>-- Model yüklenmedi --</option>';
        }
        return html;
    }

    function modelSelect(configs, key, id, label, hint, scope) {
        const config = configs.get(key) || {};
        const current = config.value || '';
        return '<div class="field">' +
            '<label class="label" for="' + esc(id) + '">' + esc(label) + '</label>' +
            '<select class="select" id="' + esc(id) + '" data-config-key="' + esc(key) + '" ' +
            'data-model-scope="' + esc(scope) + '">' + modelOptions(current, []) + '</select>' +
            (hint ? '<span class="hint">' + esc(hint) + '</span>' : '') +
            '</div>';
    }

    function baseUrlField(configs, key, id, scope, provider, hint) {
        const config = configs.get(key) || {};
        const value = config.value === undefined || config.value === null ? '' : config.value;
        return '<div class="field">' +
            '<label class="label" for="' + esc(id) + '">API Base URL</label>' +
            '<div class="inline-field">' +
            '<input class="input" id="' + esc(id) + '" type="text" data-config-key="' + esc(key) + '" ' +
            'data-llm-base-url="' + esc(scope) + '" value="' + esc(value) + '" ' +
            'placeholder="' + esc(LLM_DEFAULT_BASE_URLS[provider] || 'https://api.openai.com/v1') + '">' +
            '<button type="button" class="btn btn-secondary btn-sm" id="load-' + esc(scope) + '-models">' +
            '🔄 Modelleri Yükle</button>' +
            '</div>' +
            '<span class="hint model-status" id="models-status-' + esc(scope) + '">' + esc(hint) + '</span>' +
            '</div>';
    }

    function markModelsStale(scope) {
        const id = scope === 'primary' ? 'cfg-llm_model' : 'cfg-vision_llm_model';
        const select = document.getElementById(id);
        const current = select ? select.value : '';
        if (select) {
            select.innerHTML = modelOptions(current, []);
            select.dataset.stale = 'true';
        }
        setModelStatus(scope, 'Sağlayıcı veya base URL değişti. Modelleri yeniden yükleyin.', 'info');
    }

    async function loadModels(scope) {
        const isPrimary = scope === 'primary';
        const providerId = isPrimary ? 'llm-provider' : 'vision-llm-provider';
        const baseId = isPrimary ? 'cfg-llm_base_url' : 'cfg-vision_llm_base_url';
        const modelId = isPrimary ? 'cfg-llm_model' : 'cfg-vision_llm_model';
        const keyId = isPrimary ? 'cfg-llm_api_key' : 'cfg-vision_llm_api_key';
        const providerEl = document.getElementById(providerId);
        const baseEl = document.getElementById(baseId);
        const keyEl = document.getElementById(keyId);
        const select = document.getElementById(modelId);
        const button = document.getElementById('load-' + scope + '-models');
        const provider = providerEl ? providerEl.value : 'openai';
        const baseUrl = baseEl ? baseEl.value.trim() : '';
        // Yeni yazılmış anahtar boşsa kayıtlı anahtar kullanılır (backend tarafı).
        const apiKey = keyEl ? keyEl.value.trim() : '';

        if (provider === 'custom' && !baseUrl) {
            setModelStatus(scope, 'OpenAI uyumlu sağlayıcı için API Base URL girin.', 'error');
            showToast('OpenAI uyumlu sağlayıcı için API Base URL girin.', 'error');
            return;
        }

        if (button) button.disabled = true;
        setModelStatus(scope, 'Modeller yükleniyor...', 'info');

        try {
            const response = await api('/llm/models', {
                method: 'POST',
                body: {
                    scope: scope,
                    provider: provider,
                    base_url: baseUrl,
                    api_key: apiKey
                }
            });
            const models = (response.data && response.data.models) || [];
            const current = select ? select.value : '';
            if (select) {
                select.innerHTML = modelOptions(current, models);
                select.dataset.stale = 'false';
            }
            const usedBase = (response.data && response.data.base_url) ||
                baseUrl || LLM_DEFAULT_BASE_URLS[provider] || '';
            setModelStatus(scope, models.length + ' model yüklendi' + (usedBase ? ' · ' + usedBase : ''), 'success');
        } catch (error) {
            if (error instanceof AuthError) return;
            setModelStatus(scope, 'Model listesi alınamadı: ' + error.message, 'error');
            showToast(error.message, 'error');
        } finally {
            if (button) button.disabled = false;
        }
    }

    function updateLlmUi() {
        const primaryVisionEl = document.getElementById('llm-vision-supported');
        const visionEnabledEl = document.getElementById('vision-llm-enabled');
        const fields = document.getElementById('visionLlmFields');
        const note = document.getElementById('visionNote');
        const badge = document.getElementById('visionStatusBadge');
        if (!primaryVisionEl || !visionEnabledEl) return;

        const primaryVision = primaryVisionEl.checked;
        if (primaryVision) visionEnabledEl.checked = false;
        visionEnabledEl.disabled = primaryVision;

        const active = !primaryVision && visionEnabledEl.checked;

        if (fields) {
            fields.querySelectorAll('input, select, button').forEach(function (element) {
                element.disabled = !active;
            });
            fields.classList.toggle('is-disabled', !active);
        }

        if (note) {
            note.className = 'alert alert-info show';
            if (primaryVision) {
                note.textContent = 'Ana LLM görsel (vision) destekliyor. Görseller ana LLM ile okunacak; ikinci LLM gerekmez.';
            } else if (active) {
                note.textContent = 'Ana LLM vision desteklemiyor. Görsel okuma için aşağıdaki ikinci LLM kullanılacak.';
            } else {
                note.textContent = 'Ana LLM vision desteklemiyor ve ikinci LLM kapalı. Görsel okuma devre dışı.';
            }
        }

        if (badge) {
            badge.className = 'badge ' + (primaryVision ? 'badge-success' : active ? 'badge-info' : 'badge-warning');
            badge.textContent = primaryVision ? 'Ana LLM yeterli' : active ? 'İkinci LLM aktif' : 'Pasif';
        }
    }

    async function renderLlmSettings() {
        const response = await api('/config?limit=200');
        const configs = new Map((response.data || []).map(function (item) { return [item.key, item]; }));
        const primaryProvider = (configs.get('llm_provider') || {}).value || 'openai';
        const visionProvider = (configs.get('vision_llm_provider') || {}).value || 'openai';

        contentArea.innerHTML =
            '<div class="page-head">' +
            '<h2 class="page-title">LLM Ayarları</h2>' +
            '<p class="page-sub">Sağlık verilerini işleyen ana LLM ile görsel okuma için kullanılacak vision LLM\'i yapılandırın.</p>' +
            '</div>' +
            '<div class="cards-grid">' +
            '<div class="card">' +
            '<div class="card-head"><div class="card-title">Ana LLM · Sağlık</div>' +
            '<span class="badge badge-info">Birincil</span></div>' +
            '<div class="form-grid">' +
            providerSelect(configs, 'llm_provider', 'llm-provider', 'Sağlayıcı',
                'Sağlık metinlerini ve sohbeti işleyen ana model.') +
            modelSelect(configs, 'llm_model', 'cfg-llm_model', 'Model',
                'Model adı listeden seçilir. Boş bırakılan base URL için varsayılan adres kullanılır.', 'primary') +
            configInput(configs, 'llm_api_key', 'API Anahtarı', 'password',
                'Gizli değer gösterilmez. Yeni anahtarı yazdıktan sonra kaydetmeden modelleri yükleyebilirsiniz.', 'sk-...') +
            baseUrlField(configs, 'llm_base_url', 'cfg-llm_base_url', 'primary', primaryProvider,
                'Boş bırakılırsa ' + (LLM_DEFAULT_BASE_URLS[primaryProvider] || 'sağlayıcı varsayılanı') + ' kullanılır.') +
            '</div>' +
            '<div class="check-stack">' +
            checkboxInput(configs, 'llm_vision_supported', 'llm-vision-supported',
                'Ana LLM görsel (vision) destekliyor',
                'Destekliyorsa görsel okuma için ikinci LLM kullanılmaz.') +
            '</div>' +
            '</div>' +
            '<div class="card" id="visionLlmCard">' +
            '<div class="card-head"><div class="card-title">Vision LLM · Görsel Okuma</div>' +
            '<span class="badge badge-warning" id="visionStatusBadge">Pasif</span></div>' +
            '<div class="alert alert-info" id="visionNote"></div>' +
            checkboxInput(configs, 'vision_llm_enabled', 'vision-llm-enabled',
                'İkinci vision LLM kullan',
                'Ana LLM vision desteklemiyorsa görseller bu model ile okunur.') +
            '<div class="form-grid" id="visionLlmFields">' +
            providerSelect(configs, 'vision_llm_provider', 'vision-llm-provider', 'Sağlayıcı',
                'Görsel okuma yapacak modelin sağlayıcısı.') +
            modelSelect(configs, 'vision_llm_model', 'cfg-vision_llm_model', 'Model',
                'Görsel destekleyen bir model seçin. Model adı listeden seçilir.', 'vision') +
            configInput(configs, 'vision_llm_api_key', 'API Anahtarı', 'password',
                'Gizli değer gösterilmez. Yeni anahtarı yazdıktan sonra kaydetmeden modelleri yükleyebilirsiniz.', 'sk-...') +
            baseUrlField(configs, 'vision_llm_base_url', 'cfg-vision_llm_base_url', 'vision', visionProvider,
                'Boş bırakılırsa ' + (LLM_DEFAULT_BASE_URLS[visionProvider] || 'sağlayıcı varsayılanı') + ' kullanılır.') +
            '</div>' +
            '</div>' +
            '</div>' +
            '<div class="form-actions">' +
            '<button type="button" class="btn btn-primary" id="saveLlmBtn">Değişiklikleri Kaydet</button>' +
            '</div>' +
            '<div class="card-note">Kaydettikten sonra yeni LLM ayarları uygulama tarafından kullanılır. ' +
            'Ana LLM vision destekliyorsa vision LLM otomatik olarak devre dışı bırakılır.</div>';

        const primaryVision = document.getElementById('llm-vision-supported');
        const visionEnabled = document.getElementById('vision-llm-enabled');
        if (primaryVision) primaryVision.addEventListener('change', updateLlmUi);
        if (visionEnabled) visionEnabled.addEventListener('change', updateLlmUi);

        const providerPrimary = document.getElementById('llm-provider');
        const providerVision = document.getElementById('vision-llm-provider');
        const basePrimary = document.getElementById('cfg-llm_base_url');
        const baseVision = document.getElementById('cfg-vision_llm_base_url');
        if (providerPrimary) providerPrimary.addEventListener('change', function () { markModelsStale('primary'); });
        if (providerVision) providerVision.addEventListener('change', function () { markModelsStale('vision'); });
        if (basePrimary) basePrimary.addEventListener('input', function () { markModelsStale('primary'); });
        if (baseVision) baseVision.addEventListener('input', function () { markModelsStale('vision'); });

        ['primary', 'vision'].forEach(function (scope) {
            const loadButton = document.getElementById('load-' + scope + '-models');
            if (loadButton) loadButton.addEventListener('click', function () { loadModels(scope); });
        });

        const saveButton = document.getElementById('saveLlmBtn');
        if (saveButton) saveButton.addEventListener('click', saveLlmSettings);

        updateLlmUi();
    }

    async function saveLlmSettings() {
        const modelInput = document.getElementById('cfg-llm_model');
        if (!modelInput || !modelInput.value.trim()) {
            showToast('Ana LLM için model adı zorunludur.', 'error');
            if (modelInput) modelInput.focus();
            return;
        }

        const primaryVisionEl = document.getElementById('llm-vision-supported');
        const visionEnabledEl = document.getElementById('vision-llm-enabled');
        const primaryVision = !!(primaryVisionEl && primaryVisionEl.checked);

        if (!primaryVision && visionEnabledEl && visionEnabledEl.checked) {
            const visionModelInput = document.getElementById('cfg-vision_llm_model');
            if (!visionModelInput || !visionModelInput.value.trim()) {
                showToast('Vision LLM aktifken model adı zorunludur.', 'error');
                if (visionModelInput) visionModelInput.focus();
                return;
            }
        }

        const updates = collectConfigUpdates(true).filter(function (pair) {
            return pair[0] !== 'vision_llm_enabled';
        });
        // İkinci LLM anahtarı her zaman açıkça yazılır; ana LLM vision
        // destekliyorsa zorla kapatılır.
        updates.push([
            'vision_llm_enabled',
            primaryVision ? 'false' : (visionEnabledEl && visionEnabledEl.checked ? 'true' : 'false')
        ]);

        const button = document.getElementById('saveLlmBtn');
        if (button) button.disabled = true;

        try {
            for (const pair of updates) {
                await api('/config/' + encodeURIComponent(pair[0]), {
                    method: 'PUT',
                    body: { value: pair[1] }
                });
            }
            showToast('LLM ayarları güncellendi.', 'success');
            await navigate('/admin/llm', { push: false });
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
            if (button) button.disabled = false;
        }
    }

    /* ------------------------------------------------------------------ */
    /* Veritabanı / Redis Ayarları                                        */
    /* ------------------------------------------------------------------ */

    async function saveDbConfig() {
        const updates = collectConfigUpdates(false);

        if (!updates.length) {
            showToast('Kaydedilecek bir değişiklik yok.', 'info');
            return;
        }

        const buttons = [
            document.getElementById('saveDbConfigBtn'),
            document.getElementById('saveDbConfigBtn2')
        ];
        buttons.forEach(function (button) { if (button) button.disabled = true; });

        try {
            for (const pair of updates) {
                await api('/config/' + encodeURIComponent(pair[0]), {
                    method: 'PUT',
                    body: { value: pair[1] }
                });
            }
            showToast(updates.length + ' ayar güncellendi.', 'success');
            await navigate('/admin/db-config', { push: false });
        } catch (error) {
            if (error instanceof AuthError) return;
            showToast(error.message, 'error');
            buttons.forEach(function (button) { if (button) button.disabled = false; });
        }
    }

    async function testConnection(kind) {
        const box = document.getElementById('dbTestResult');
        if (box) {
            box.className = 'alert alert-info show';
            box.textContent = (kind === 'db' ? 'PostgreSQL' : 'Redis') + ' bağlantısı test ediliyor...';
        }

        try {
            const response = await api('/utils/test-' + kind, { method: 'POST' });
            const data = response.data || {};
            let message = (kind === 'db' ? 'PostgreSQL' : 'Redis') + ' bağlantısı başarılı.';
            if (kind === 'db' && data.version) {
                message += ' Sürüm: ' + data.version + ' · ' + formatNumber(data.latency_ms, 1) + ' ms';
            } else if (kind === 'redis' && data.ping) {
                message += ' Yanıt: ' + data.ping + ' · ' + formatNumber(data.latency_ms, 1) + ' ms';
            }
            if (box) {
                box.className = 'alert alert-success show';
                box.textContent = message;
            }
            showToast('Bağlantı başarılı.', 'success');
        } catch (error) {
            if (error instanceof AuthError) return;
            if (box) {
                box.className = 'alert alert-error show';
                box.textContent = 'Bağlantı başarısız: ' + error.message;
            }
            showToast('Bağlantı başarısız.', 'error');
        }
    }

    /* ------------------------------------------------------------------ */
    /* Başlat                                                             */
    /* ------------------------------------------------------------------ */

    function init() {
        if (!state.token) {
            window.location.replace('/admin/login');
            return;
        }
        setupShell();
        navigate(window.location.pathname, { push: false });
    }

    init();
})();
