(function () {
    const KEY  = 'jts_admin_v1';
    const PASS = 'JaysTires2025'; // ← Change this to your preferred password

    window.JTS_ADMIN = {
        isAdmin:    () => localStorage.getItem(KEY) === '1',
        logout:     () => { localStorage.removeItem(KEY); location.reload(); },
        showPrompt: (onSuccess) => renderGate(true, onSuccess)
    };

    // Full-page gate — only activates when <body data-admin-gate> is present
    document.addEventListener('DOMContentLoaded', function () {
        if (!document.body.hasAttribute('data-admin-gate')) return;
        if (window.location.hash === '#employee') return;
        if (localStorage.getItem(KEY) === '1') return;
        renderGate(false, null);
    });

    function renderGate(canClose, onSuccess) {
        if (document.getElementById('jts-admin-gate')) return;

        const overlay = document.createElement('div');
        overlay.id = 'jts-admin-gate';
        overlay.style.cssText = [
            'position:fixed;inset:0;z-index:99999;',
            'background:#111827;',
            'display:flex;align-items:center;justify-content:center;',
            'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;'
        ].join('');

        overlay.innerHTML = `
            <div style="background:white;border-radius:16px;padding:40px 36px;width:340px;
                        text-align:center;box-shadow:0 25px 60px rgba(0,0,0,0.45);">
                <div style="width:58px;height:58px;background:black;border-radius:50%;
                            display:flex;align-items:center;justify-content:center;margin:0 auto 18px;">
                    <span style="color:white;font-weight:800;font-size:14px;letter-spacing:-0.5px;">JTS</span>
                </div>
                <h2 style="margin:0 0 6px;font-size:22px;font-weight:700;color:#111827;">
                    Jay's Tire Shop
                </h2>
                <p style="margin:0 0 26px;font-size:14px;color:#6b7280;">Enter password to continue</p>
                <input id="jts-pw-input" type="password" placeholder="Password"
                    style="border:2px solid #e5e7eb;border-radius:10px;padding:13px 16px;
                           width:100%;font-size:16px;box-sizing:border-box;margin-bottom:10px;
                           outline:none;transition:border-color 0.15s;"
                    onfocus="this.style.borderColor='#2563eb'"
                    onblur="this.style.borderColor='#e5e7eb'"
                    onkeydown="if(event.key==='Enter')document.getElementById('jts-unlock-btn').click()" />
                <p id="jts-pw-err" style="color:#dc2626;font-size:13px;margin:0 0 12px;min-height:18px;"></p>
                <button id="jts-unlock-btn"
                    style="background:#111827;color:white;border:none;border-radius:10px;
                           padding:14px;width:100%;font-size:16px;font-weight:600;cursor:pointer;
                           margin-bottom:${canClose ? '10px' : '0'};">
                    Unlock
                </button>
                ${canClose
                    ? '<button id="jts-cancel-btn" style="background:none;border:none;color:#9ca3af;font-size:14px;cursor:pointer;padding:6px;width:100%;">Cancel</button>'
                    : ''}
            </div>`;

        document.body.appendChild(overlay);
        document.getElementById('jts-pw-input').focus();

        document.getElementById('jts-unlock-btn').addEventListener('click', function () {
            const val = document.getElementById('jts-pw-input').value;
            if (val === PASS) {
                localStorage.setItem(KEY, '1');
                overlay.remove();
                if (onSuccess) onSuccess();
            } else {
                document.getElementById('jts-pw-err').textContent = 'Incorrect password. Try again.';
                document.getElementById('jts-pw-input').value = '';
                document.getElementById('jts-pw-input').focus();
            }
        });

        if (canClose) {
            document.getElementById('jts-cancel-btn').addEventListener('click', function () {
                overlay.remove();
            });
        }
    }
})();
