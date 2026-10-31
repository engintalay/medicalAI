/**
 * Admin Panel JavaScript
 * Fetch API ile backend'den JSON verilerini alıp DOM'a yükler.
 */

// --- Global State ---
const state = {
    token: localStorage.getItem('admin_token') || '',
    user: JSON.parse(localStorage.getItem('admin_user') || 'null'),
    currentPage: 'dashboard',
    isLoading: false
};

// --- DOM Elements ---
const contentArea = document.getElementById('contentArea');
const pageTitle = document.getElementById('pageTitle');
const userName = document.getElementById('userName');
const userEmail = document.getElementById('userEmail');
const toast = document.getElementById('toast');

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    if (state.token) {
        loadDashboard();
    } else {
        showLoading();
    }
    updateHeader();
    setupEventListeners();
});

// --- Core Functions ---

async function loadDashboard() {
    state.isLoading = true;
    contentArea.innerHTML = `<div class="loading"><div class="spinner"></div><p>İçerik yükleniyor...</p></div>`;
    
    try {
        const response = await fetch('/admin/api/monitoring', {
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        
        if (response.ok) {
            const data = await response.json();
            renderDashboard(data.data);
        } else {
            renderError('Giriş süresi dolmuş. Lütfen tekrar giriş yapın.');
        }
    } catch (error) {
        renderError('Bağlantı hatası: ' + error.message);
    } finally {
        state.isLoading = false;
    }
}

async function loadConfig() {
    try {
        const response = await fetch('/admin/api/config', {
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        
        if (response.ok) {
            const data = await response.json();
            renderConfig(data.data);
        } else {
            renderError('Config yüklenirken hata oluştu.');
        }
    } catch (error) {
        renderError('Bağlantı hatası: ' + error.message);
    }
}

async function loadUsers() {
    try {
        const response = await fetch('/admin/api/users', {
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        
        if (response.ok) {
            const data = await response.json();
            renderUsers(data.data, data.pagination);
        } else {
            renderError('Kullanıcılar yüklenirken hata oluştu.');
        }
    } catch (error) {
        renderError('Bağlantı hatası: ' + error.message);
    }
}

async function loadMonitoring() {
    try {
        const response = await fetch('/admin/api/monitoring', {
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        
        if (response.ok) {
            const data = await response.json();
            renderMonitoring(data.data);
        } else {
            renderError('İzleme verileri yüklenirken hata oluştu.');
        }
    } catch (error) {
        renderError('Bağlantı hatası: ' + error.message);
    }
}

// --- Render Functions ---

function renderDashboard(data) {
    pageTitle.textContent = 'Dashboard';
    contentArea.innerHTML = `
        <div class="max-w-4xl">
            <div class="mb-4">
                <h2 class="text-2xl font-bold mb-2">Hoşgeldiniz, ${data.full_name || 'Admin'}!</h2>
                <p class="text-gray-600">Sistem genel durumunu görüntüleyebilirsiniz.</p>
            </div>
            
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
                <div class="card">
                    <div class="text-3xl font-bold text-blue-600">${data.active_sessions || 0}</div>
                    <div class="text-gray-600">Aktif Oturum</div>
                </div>
                <div class="card">
                    <div class="text-3xl font-bold text-green-600">${data.request_count_24h || 0}</div>
                    <div class="text-gray-600">24 Saatlik İstek</div>
                </div>
                <div class="card">
                    <div class="text-3xl font-bold text-yellow-600">${data.error_rate || 0}%</div>
                    <div class="text-gray-600">Hata Oranı</div>
                </div>
                <div class="card">
                    <div class="text-3xl font-bold text-purple-600">${data.redis_cache_hit_rate || 0}%</div>
                    <div class="text-gray-600">Cache Hit Rate</div>
                </div>
            </div>
            
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div class="card">
                    <h3 class="text-lg font-semibold mb-3">Son Aktiviteler</h3>
                    <div class="text-gray-600 text-sm">
                        <p>• Sistem başlatıldı (Nov 01, 2026)</p>
                        <p>• İlk admin giriş yapıldı</p>
                        <p>• Config yüklenirken başarı</p>
                    </div>
                </div>
                <div class="card">
                    <h3 class="text-lg font-semibold mb-3">Sistem Durumu</h3>
                    <div class="text-gray-600 text-sm">
                        <p>• PostgreSQL: <span class="text-green-600">Bağlı</span></p>
                        <p>• Redis: <span class="text-green-600">Bağlı</span></p>
                        <p>• LLM: <span class="text-yellow-600">Env'de</span></p>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderConfig(configs) {
    pageTitle.textContent = 'Sistem Config';
    contentArea.innerHTML = `
        <div class="max-w-4xl">
            <div class="mb-4">
                <h2 class="text-2xl font-bold mb-2">Sistem Konfigürasyonları</h2>
                <p class="text-gray-600">PostgreSQL, Redis ve LLM bağlantı ayarlarını görüntüleyebilirsiniz.</p>
            </div>
            
            <div class="table-responsive">
                <table class="table">
                    <thead>
                        <tr>
                            <th>Key</th>
                            <th>Value</th>
                            <th>Tanım</th>
                            <th>Güncellenme</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${configs.map(config => `
                            <tr>
                                <td>${config.key}</td>
                                <td><code class="text-blue-600">${config.value || '---'}</code></td>
                                <td>${config.description || ''}</td>
                                <td>${config.updated_at ? formatDateTime(config.updated_at) : '-'}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

function renderUsers(users, pagination) {
    pageTitle.textContent = 'Kullanıcılar';
    contentArea.innerHTML = `
        <div class="max-w-4xl">
            <div class="mb-4 flex justify-between items-center">
                <div>
                    <h2 class="text-2xl font-bold">Kullanıcı Listesi</h2>
                    <p class="text-gray-600">Toplam ${pagination.total} kullanıcı</p>
                </div>
                <div class="flex gap-2">
                    <select id="userRoleFilter" class="form-input" style="width: auto;" onchange="loadUsers()">
                        <option value="">Tüm Rolleri</option>
                        <option value="admin">Admin</option>
                        <option value="patient">Patient</option>
                    </select>
                    <select id="userActiveFilter" class="form-input" style="width: auto;" onchange="loadUsers()">
                        <option value="">Tüm Durumlar</option>
                        <option value="true">Aktif</option>
                        <option value="false">Pasif</option>
                    </select>
                </div>
            </div>
            
            <div class="table-responsive">
                <table class="table">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Email</th>
                            <th>Ad Soyad</th>
                            <th>Rol</th>
                            <th>Durum</th>
                            <th>Son Giriş</th>
                            <th>İşlemler</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${users.map(user => `
                            <tr>
                                <td>${user.user_id}</td>
                                <td>${user.email}</td>
                                <td>${user.full_name}</td>
                                <td><span class="badge badge-${user.role === 'admin' ? 'info' : 'success'}">${user.role}</span></td>
                                <td><span class="badge badge-${user.is_active ? 'success' : 'warning'}">${user.is_active ? 'Aktif' : 'Pasif'}</span></td>
                                <td>${user.last_login ? formatDateTime(user.last_login) : '-'}</td>
                                <td>
                                    <button class="btn btn-secondary" onclick="showToast('Profile açma özelliği eklenecek')">👁️ Profile</button>
                                    <button class="btn btn-secondary" onclick="showToast('Reset özelliği eklenecek')">🔄 Reset</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            
            ${pagination.total_pages > 1 ? `
                <div class="mt-4 flex justify-center gap-2">
                    ${Array.from({length: pagination.total_pages}, (_, i) => i + 1).map(page => `
                        <button class="btn btn-secondary" onclick="loadUsers(${page}, ${pagination.per_page})">${page}</button>
                    `).join('')}
                </div>
            ` : ''}
        </div>
    `;
}

function renderMonitoring(data) {
    pageTitle.textContent = 'Sistem İzleme';
    contentArea.innerHTML = `
        <div class="max-w-4xl">
            <div class="mb-4">
                <h2 class="text-2xl font-bold mb-2">Sistem Durumu</h2>
                <p class="text-gray-600">Gerçek zamanlı sistem metriklerini görüntüleyebilirsiniz.</p>
            </div>
            
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="card">
                    <h3 class="text-lg font-semibold mb-3">Network & Bağlantılar</h3>
                    <div class="text-gray-600 text-sm space-y-2">
                        <div class="flex justify-between">
                            <span>PostgreSQL Bağlantısı:</span>
                            <span class="badge badge-success">Aktif</span>
                        </div>
                        <div class="flex justify-between">
                            <span>Redis Bağlantısı:</span>
                            <span class="badge badge-success">Aktif</span>
                        </div>
                        <div class="flex justify-between">
                            <span>DB Connections:</span>
                            <span>${data.db_connections.active}/${data.db_connections.max}</span>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <h3 class="text-lg font-semibold mb-3">LLM Kullanımı</h3>
                    <div class="text-gray-600 text-sm space-y-2">
                        <div class="flex justify-between">
                            <span>Toplam Input Token:</span>
                            <span>${data.llm_token_usage.total_input.toLocaleString()}</span>
                        </div>
                        <div class="flex justify-between">
                            <span>Toplam Output Token:</span>
                            <span>${data.llm_token_usage.total_output.toLocaleString()}</span>
                        </div>
                        <div class="flex justify-between">
                            <span>Hata Oranı:</span>
                            <span>${data.error_rate}%</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

// --- Utilities ---

function updateHeader() {
    if (state.user) {
        userName.textContent = state.user.full_name || 'Sistem Yöneticisi';
        userEmail.textContent = state.user.email || 'admin@medicalai.com';
    }
}

function setupEventListeners() {
    // Token değiştiğinde
    window.addEventListener('storage', (e) => {
        if (e.key === 'admin_token') {
            if (e.newValue) {
                state.token = e.newValue;
                loadDashboard();
            } else {
                state.token = '';
                loadDashboard();
            }
        }
    });
}

function formatDateTime(isoString) {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return date.toLocaleDateString('tr-TR') + ' ' + date.toLocaleTimeString('tr-TR', {hour: '2-digit', minute: '2-digit'});
}

function showToast(message, type = 'info') {
    toast.textContent = message;
    toast.className = 'toast show ' + (type === 'success' ? 'success' : type === 'error' ? 'error' : '');
    setTimeout(() => {
        toast.className = 'toast';
    }, 3000);
}

function showLoading() {
    contentArea.innerHTML = `<div class="loading"><div class="spinner"></div><p>İçerik yükleniyor...</p></div>`;
}

function renderError(message) {
    contentArea.innerHTML = `
        <div class="max-w-4xl text-center py-8">
            <div class="text-red-600 text-2xl font-bold mb-4">⚠️ Hata</div>
            <p class="text-gray-600 mb-4">${message}</p>
            <button class="btn btn-primary" onclick="loadDashboard()">Tekrar Dene</button>
        </div>
    `;
}

async function handleLogin(email, password) {
    try {
        const response = await fetch('/admin/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ email, password })
        });
        
        const data = await response.json();
        
        if (data.success) {
            state.token = data.token;
            localStorage.setItem('admin_token', data.token);
            localStorage.setItem('admin_user', JSON.stringify(data.user));
            updateHeader();
            loadDashboard();
            showToast('Giriş başarılı!', 'success');
        } else {
            showToast(data.message || 'Giriş hatası', 'error');
        }
    } catch (error) {
        showToast('Bağlantı hatası', 'error');
    }
}

function handleLogout() {
    if (state.token) {
        fetch('/admin/api/auth/logout', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
    }
    
    state.token = '';
    state.user = null;
    localStorage.removeItem('admin_token');
    localStorage.removeItem('admin_user');
    updateHeader();
    loadDashboard();
    showToast('Çıkış yapıldı.', 'success');
}

// --- Event Handlers for Login Modal ---
function setupLoginModal() {
    const loginBtn = document.getElementById('loginBtn');
    if (loginBtn) {
        loginBtn.addEventListener('click', (e) => {
            e.preventDefault();
            const email = document.getElementById('loginEmail').value;
            const password = document.getElementById('loginPassword').value;
            handleLogin(email, password);
        });
    }
}

// Export to global scope for inline handlers
window.loadUsers = loadUsers;
window.loadConfig = loadConfig;
window.loadMonitoring = loadMonitoring;
window.formatDateTime = formatDateTime;
window.showToast = showToast;
window.handleLogin = handleLogin;
