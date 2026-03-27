(function () {
    var OWNER_PASS = 'JaysTires2025';
    var EMP_PASS   = 'Jays';
    var EMPLOYEES  = ['Jay', 'Noe', 'Felipe', 'Chuy', 'Pedro'];
    var OWNER_ONLY = ['reports.html', 'transactions.html'];
    var SESS_KEY   = 'jts_sess';

    // Clear the old localStorage-based auth so it can't bypass the new gate
    localStorage.removeItem('jts_admin_v1');

    // ── Session API (available globally) ─────────────────────────────────────
    window.JTS_SESSION = {
        get: function () {
            try { return JSON.parse(sessionStorage.getItem(SESS_KEY)); } catch (e) { return null; }
        },
        set: function (d) { sessionStorage.setItem(SESS_KEY, JSON.stringify(d)); },
        clear: function () { sessionStorage.removeItem(SESS_KEY); location.href = 'index.html'; },
        isOwner: function () { var s = window.JTS_SESSION.get(); return !!(s && s.role === 'owner'); },
        isEmployee: function () { var s = window.JTS_SESSION.get(); return !!(s && s.role === 'employee'); }
    };

    // Backward compat for any code that uses JTS_ADMIN
    window.JTS_ADMIN = {
        isAdmin:    function () { return window.JTS_SESSION.isOwner(); },
        logout:     function () { window.JTS_SESSION.clear(); },
        showPrompt: function () {}
    };

    // ── Routing ──────────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        var page    = location.pathname.split('/').pop() || 'index.html';
        var session = window.JTS_SESSION.get();

        if (session) {
            if (session.role === 'employee') {
                // Block owner-only pages
                if (OWNER_ONLY.indexOf(page) !== -1) {
                    location.href = 'pos.html?store=' + session.store; return;
                }
                // Employees skip the dashboard — go straight to POS
                if (page === 'index.html') {
                    location.href = 'pos.html?store=' + session.store; return;
                }
                // Ensure POS is loaded for their store
                if (page === 'pos.html') {
                    var sp = new URLSearchParams(location.search).get('store');
                    if (!sp) { location.href = 'pos.html?store=' + session.store; return; }
                }
            }
            injectSignOut(session);
        return; // valid session — let the page load
        }

        // No session — redirect every non-index page back to login
        if (page !== 'index.html') {
            location.href = 'index.html'; return;
        }

        // index.html with no session — show login gate
        showGate();
    });

    // ── Sign-out pill (injected on every authenticated page) ─────────────────
    function injectSignOut(session) {
        var page = location.pathname.split('/').pop() || 'index.html';
        if (page === 'index.html') return; // index.html has its own header sign-out
        if (document.getElementById('jts-signout')) return;
        var label = session.role === 'owner' ? 'Owner' : (session.name + ' · Store #' + session.store);
        var pill = document.createElement('div');
        pill.id = 'jts-signout';
        pill.style.cssText = [
            'position:fixed;bottom:20px;right:20px;z-index:9999;',
            'display:flex;align-items:center;gap:10px;',
            'background:white;border:1px solid #e5e7eb;border-radius:999px;',
            'padding:8px 14px 8px 12px;',
            'box-shadow:0 2px 12px rgba(0,0,0,0.12);',
            'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;',
            'font-size:13px;color:#374151;'
        ].join('');
        pill.innerHTML =
            '<span style="font-weight:600;">' + label + '</span>' +
            '<button onclick="window.JTS_SESSION.clear()" style="' +
            'background:#f3f4f6;border:none;border-radius:999px;' +
            'padding:4px 10px;font-size:12px;font-weight:600;color:#374151;cursor:pointer;">Sign out</button>';
        document.body.appendChild(pill);
    }

    // ── Login Gate ───────────────────────────────────────────────────────────
    function showGate() {
        if (document.getElementById('jts-gate')) return;

        var overlay = document.createElement('div');
        overlay.id  = 'jts-gate';
        overlay.style.cssText = [
            'position:fixed;inset:0;z-index:99999;',
            'background:#0f172a;',
            'display:flex;align-items:center;justify-content:center;',
            'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;'
        ].join('');
        overlay.innerHTML = buildHTML();
        document.body.appendChild(overlay);
        bindEvents(overlay);
    }

    function logo() {
        return '<div style="width:52px;height:52px;background:#2563eb;border-radius:14px;' +
            'display:flex;align-items:center;justify-content:center;margin:0 auto 16px;">' +
            '<span style="color:white;font-weight:800;font-size:13px;letter-spacing:-0.5px;">JTS</span></div>' +
            '<h2 style="margin:0 0 4px;font-size:22px;font-weight:700;color:#111827;">Jay\'s Tire Shop</h2>';
    }
    function btn(bg, color, extra) {
        return 'background:' + bg + ';color:' + color + ';border:none;border-radius:10px;' +
            'padding:13px;width:100%;font-size:15px;font-weight:600;cursor:pointer;display:block;' + (extra || '');
    }
    function inp() {
        return 'border:2px solid #e5e7eb;border-radius:10px;padding:12px 14px;' +
            'width:100%;font-size:16px;box-sizing:border-box;outline:none;';
    }

    function buildHTML() {
        var stores = [
            ['1', '2932 N 16th St'],
            ['2', '2347 E Osborn Rd'],
            ['3', '430 N 16th St']
        ].map(function (s) {
            return '<button class="jts-store" data-store="' + s[0] + '" style="' +
                'background:#f9fafb;border:2px solid #e5e7eb;border-radius:12px;' +
                'padding:14px 16px;width:100%;cursor:pointer;text-align:left;margin-bottom:8px;">' +
                '<span style="font-size:16px;font-weight:700;color:#111827;display:block;">Store #' + s[0] + '</span>' +
                '<span style="font-size:12px;color:#6b7280;">' + s[1] + ', Phoenix AZ</span></button>';
        }).join('');

        var names = EMPLOYEES.map(function (n) {
            return '<button class="jts-name" data-name="' + n + '" style="' +
                'background:#f3f4f6;border:2px solid #e5e7eb;border-radius:10px;' +
                'padding:12px;font-size:15px;font-weight:600;color:#111827;cursor:pointer;">' + n + '</button>';
        }).join('');

        var backBtn = '<button class="jts-back" style="' + btn('transparent','#9ca3af','font-size:14px;margin-top:8px;') + '">← Back</button>';
        var errStyle = 'color:#dc2626;font-size:13px;margin:0 0 10px;min-height:16px;';

        return '<div style="background:white;border-radius:20px;padding:36px 32px;width:340px;text-align:center;box-shadow:0 30px 80px rgba(0,0,0,0.5);">' +

            // Step 1 — choose role
            '<div id="jts-s1">' + logo() +
            '<p style="margin:0 0 24px;font-size:14px;color:#6b7280;">How are you signing in?</p>' +
            '<button id="jts-to-owner" style="' + btn('#111827','white','margin-bottom:10px;') + '">Owner / Manager</button>' +
            '<button id="jts-to-emp" style="' + btn('#f3f4f6','#111827') + '">Employee</button>' +
            '</div>' +

            // Step 2a — owner password
            '<div id="jts-s2o" style="display:none">' + logo() +
            '<p style="margin:0 0 20px;font-size:14px;color:#6b7280;">Enter owner password</p>' +
            '<input id="jts-opw" type="password" placeholder="Password" style="' + inp() + 'margin-bottom:6px;" />' +
            '<p id="jts-oerr" style="' + errStyle + '"></p>' +
            '<button id="jts-ounlock" style="' + btn('#111827','white','margin-bottom:8px;') + '">Unlock</button>' +
            backBtn + '</div>' +

            // Step 2b — employee password
            '<div id="jts-s2e" style="display:none">' + logo() +
            '<p style="margin:0 0 20px;font-size:14px;color:#6b7280;">Enter employee password</p>' +
            '<input id="jts-epw" type="password" placeholder="Password" style="' + inp() + 'margin-bottom:6px;" />' +
            '<p id="jts-eerr" style="' + errStyle + '"></p>' +
            '<button id="jts-enext" style="' + btn('#111827','white','margin-bottom:8px;') + '">Continue</button>' +
            backBtn + '</div>' +

            // Step 3 — store selection
            '<div id="jts-s3" style="display:none">' + logo() +
            '<p style="margin:0 0 16px;font-size:14px;color:#6b7280;">Which store are you at today?</p>' +
            stores + backBtn + '</div>' +

            // Step 4 — name selection
            '<div id="jts-s4" style="display:none">' + logo() +
            '<p id="jts-s4sub" style="margin:0 0 16px;font-size:14px;color:#6b7280;">Tap your name</p>' +
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:4px;">' + names + '</div>' +
            backBtn + '</div>' +

        '</div>';
    }

    function bindEvents(overlay) {
        var selectedStore = null;
        var steps = ['jts-s1','jts-s2o','jts-s2e','jts-s3','jts-s4'];

        function show(id) {
            steps.forEach(function (s) {
                document.getElementById(s).style.display = (s === id) ? '' : 'none';
            });
            // Focus password input if present on new step
            var pw = document.querySelector('#' + id + ' input[type="password"]');
            if (pw) { pw.value = ''; setTimeout(function () { pw.focus(); }, 50); }
        }

        // Step 1
        document.getElementById('jts-to-owner').onclick = function () { show('jts-s2o'); };
        document.getElementById('jts-to-emp').onclick   = function () { show('jts-s2e'); };

        // Owner password
        function tryOwner() {
            if (document.getElementById('jts-opw').value === OWNER_PASS) {
                window.JTS_SESSION.set({ role: 'owner' });
                document.getElementById('jts-gate').remove();
            } else {
                document.getElementById('jts-oerr').textContent = 'Incorrect password.';
                document.getElementById('jts-opw').value = '';
                document.getElementById('jts-opw').focus();
            }
        }
        document.getElementById('jts-ounlock').onclick = tryOwner;
        document.getElementById('jts-opw').onkeydown  = function (e) { if (e.key === 'Enter') tryOwner(); };

        // Employee password
        function tryEmp() {
            if (document.getElementById('jts-epw').value === EMP_PASS) {
                show('jts-s3');
            } else {
                document.getElementById('jts-eerr').textContent = 'Incorrect password.';
                document.getElementById('jts-epw').value = '';
                document.getElementById('jts-epw').focus();
            }
        }
        document.getElementById('jts-enext').onclick = tryEmp;
        document.getElementById('jts-epw').onkeydown  = function (e) { if (e.key === 'Enter') tryEmp(); };

        // Store buttons
        overlay.querySelectorAll('.jts-store').forEach(function (b) {
            b.onmouseenter = function () { this.style.borderColor = '#2563eb'; };
            b.onmouseleave = function () { this.style.borderColor = '#e5e7eb'; };
            b.onclick = function () {
                selectedStore = this.getAttribute('data-store');
                document.getElementById('jts-s4sub').textContent = 'Tap your name — Store #' + selectedStore;
                show('jts-s4');
            };
        });

        // Name buttons
        overlay.querySelectorAll('.jts-name').forEach(function (b) {
            b.onmouseenter = function () { this.style.background = '#e5e7eb'; };
            b.onmouseleave = function () { this.style.background = '#f3f4f6'; };
            b.onclick = function () {
                window.JTS_SESSION.set({ role: 'employee', store: selectedStore, name: this.getAttribute('data-name') });
                location.href = 'pos.html?store=' + selectedStore;
            };
        });

        // Back buttons — each goes to the previous step
        overlay.querySelectorAll('.jts-back').forEach(function (b) {
            b.onclick = function () {
                var visible = steps.find(function (s) { return document.getElementById(s).style.display !== 'none'; });
                var prev = { 'jts-s2o': 'jts-s1', 'jts-s2e': 'jts-s1', 'jts-s3': 'jts-s2e', 'jts-s4': 'jts-s3' };
                if (prev[visible]) show(prev[visible]);
            };
        });
    }
})();
