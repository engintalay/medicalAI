/* Medical AI · Admin login */
(function () {
    'use strict';

    const TOKEN_KEY = 'admin_token';
    const USER_KEY = 'admin_user';

    const form = document.getElementById('loginForm');
    const alertBox = document.getElementById('loginAlert');
    const button = document.getElementById('loginBtn');
    const emailInput = document.getElementById('email');
    const passwordInput = document.getElementById('password');

    // Zaten geçerli bir token varsa panele dön.
    if (localStorage.getItem(TOKEN_KEY)) {
        window.location.replace('/admin');
        return;
    }

    function showError(message) {
        alertBox.textContent = message;
        alertBox.classList.add('show');
    }

    function clearError() {
        alertBox.textContent = '';
        alertBox.classList.remove('show');
    }

    function extractError(data, status) {
        if (!data) return 'Giriş yapılamadı (HTTP ' + status + ')';
        const detail = data.error || data.message || data.detail;
        if (Array.isArray(detail)) {
            return detail.map(function (item) {
                return item.msg || JSON.stringify(item);
            }).join(', ');
        }
        return detail || 'Giriş yapılamadı (HTTP ' + status + ')';
    }

    form.addEventListener('submit', async function (event) {
        event.preventDefault();
        clearError();

        const email = emailInput.value.trim();
        const password = passwordInput.value;

        if (!email || !password) {
            showError('E-posta ve şifre zorunludur.');
            return;
        }

        button.disabled = true;
        button.textContent = 'Giriş yapılıyor...';

        try {
            const response = await fetch('/admin/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: email, password: password })
            });

            let data = null;
            try {
                data = await response.json();
            } catch (parseError) {
                data = null;
            }

            if (!response.ok || !data || !data.success || !data.token) {
                showError(extractError(data, response.status));
                passwordInput.value = '';
                passwordInput.focus();
                return;
            }

            localStorage.setItem(TOKEN_KEY, data.token);
            localStorage.setItem(USER_KEY, JSON.stringify(data.user || {}));
            window.location.replace('/admin');
        } catch (error) {
            showError('Sunucuya bağlanılamadı: ' + error.message);
        } finally {
            button.disabled = false;
            button.textContent = 'Giriş Yap';
        }
    });
})();
