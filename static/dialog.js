/* Ortak onay dialog'u — native window.confirm yerine kullanılır. */
(function () {
    'use strict';

    function confirm(message, options) {
        options = options || {};
        const title = options.title || 'Onay gerekli';
        const confirmText = options.confirmText || 'Onayla';
        const cancelText = options.cancelText || 'Vazgeç';
        const danger = options.danger !== false;

        return new Promise(function (resolve) {
            const previousFocus = document.activeElement;
            const overlay = document.createElement('div');
            overlay.className = 'modal-overlay';
            overlay.innerHTML =
                '<div class="modal-card" role="dialog" aria-modal="true" ' +
                'aria-labelledby="medicalDialogTitle" aria-describedby="medicalDialogMessage">' +
                '<div class="modal-icon ' + (danger ? 'danger' : '') + '">' +
                (danger ? '⚠️' : '❓') + '</div>' +
                '<h2 class="modal-title" id="medicalDialogTitle"></h2>' +
                '<p class="modal-message" id="medicalDialogMessage"></p>' +
                '<div class="modal-actions">' +
                '<button type="button" class="btn btn-secondary" data-modal-cancel></button>' +
                '<button type="button" class="btn ' + (danger ? 'btn-danger' : 'btn-primary') +
                '" data-modal-confirm></button></div></div>';

            overlay.querySelector('#medicalDialogTitle').textContent = title;
            overlay.querySelector('#medicalDialogMessage').textContent = String(message || '');
            const cancelButton = overlay.querySelector('[data-modal-cancel]');
            const confirmButton = overlay.querySelector('[data-modal-confirm]');
            cancelButton.textContent = cancelText;
            confirmButton.textContent = confirmText;

            function cleanup(result) {
                document.removeEventListener('keydown', onKeydown, true);
                overlay.remove();
                if (previousFocus && typeof previousFocus.focus === 'function') {
                    previousFocus.focus();
                }
                resolve(result);
            }

            function onKeydown(event) {
                if (event.key === 'Escape') {
                    event.preventDefault();
                    cleanup(false);
                } else if (event.key === 'Enter') {
                    event.preventDefault();
                    cleanup(true);
                } else if (event.key === 'Tab') {
                    const first = danger ? cancelButton : confirmButton;
                    const last = danger ? confirmButton : cancelButton;
                    if (event.shiftKey && document.activeElement === first) {
                        event.preventDefault();
                        last.focus();
                    } else if (!event.shiftKey && document.activeElement === last) {
                        event.preventDefault();
                        first.focus();
                    }
                }
            }

            cancelButton.addEventListener('click', function () { cleanup(false); });
            confirmButton.addEventListener('click', function () { cleanup(true); });
            overlay.addEventListener('click', function (event) {
                if (event.target === overlay) cleanup(false);
            });
            document.addEventListener('keydown', onKeydown, true);
            document.body.appendChild(overlay);
            (danger ? cancelButton : confirmButton).focus();
        });
    }

    window.MedicalDialog = { confirm: confirm };
})();
