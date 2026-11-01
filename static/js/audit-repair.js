// Guided release repair: the plan page (templates/audit_repair_plan.html).
// Decisions save as they are made; the apply job is polled until it finishes.
(function () {
    const root = document.getElementById('repair');
    if (!root) { return; }
    const base = root.dataset.base;
    const aiUsed = new Set();

    if (root.dataset.status === 'building') {
        setTimeout(() => window.location.reload(), 4000);
        return;
    }

    async function post(url, body, method) {
        const res = await fetch(url, {
            method: method || 'POST',
            headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
            body: body === undefined ? undefined : JSON.stringify(body)
        });
        let data = {};
        try { data = await res.json(); } catch (e) { data = {error: 'The server sent no answer.'}; }
        return {ok: res.ok, data: data};
    }

    function content(optionEl) {
        const slot = optionEl.querySelector('.input-slot');
        if (!slot) { return null; }
        const kind = slot.dataset.kind;
        if (kind === 'fields') {
            const out = {};
            slot.querySelectorAll('.slot-field').forEach(el => { out[el.dataset.slot] = el.value; });
            return out;
        }
        if (kind === 'table') {
            const values = {};
            slot.querySelectorAll('tr[data-row]').forEach(tr => {
                const v = tr.querySelector('.table-value').value.trim();
                if (v) { values[tr.dataset.row] = v; }
            });
            return {values: values};
        }
        const el = slot.querySelector('.slot-value');
        return el ? el.value : null;
    }

    document.querySelectorAll('.remedy').forEach(card => {
        const rid = card.dataset.rid;
        const err = card.querySelector('.error');

        card.querySelectorAll('.act').forEach(btn => btn.addEventListener('click', async () => {
            const action = btn.dataset.action;
            const note = (card.querySelector('.note') || {}).value || '';
            const body = {action: action, note: note};
            if (action === 'accept') {
                const picked = card.querySelector('input[type=radio]:checked');
                if (!picked) { err.textContent = 'Choose an option first.'; return; }
                body.option = picked.value;
                const optEl = card.querySelector(`.option[data-option="${picked.value}"]`);
                body.content = content(optEl);
                body.ai_assisted = aiUsed.has(rid + ':' + picked.value);
            }
            if (action === 'declare' && !note.trim()) { err.textContent = 'Write the reason in the note first.'; return; }
            btn.disabled = true;
            err.textContent = '';
            const r = await post(`${base}/remedy/${encodeURIComponent(rid)}`, body);
            btn.disabled = false;
            if (!r.ok) { err.textContent = r.data.error || 'The decision was not saved.'; return; }
            window.location.hash = rid;
            window.location.reload();
        }));

        card.querySelectorAll('.ai-suggest').forEach(btn => btn.addEventListener('click', async () => {
            const optEl = btn.closest('.option');
            btn.disabled = true;
            btn.textContent = 'Asking...';
            const r = await post(`${base}/remedy/${encodeURIComponent(rid)}/ai`, {option: btn.dataset.option});
            btn.disabled = false;
            btn.textContent = 'Suggest with AI (your own key)';
            if (!r.ok) { err.textContent = r.data.error || 'The AI suggestion failed.'; return; }
            const slot = optEl.querySelector('.input-slot');
            if (r.data.values) {
                Object.entries(r.data.values).forEach(([row, v]) => {
                    const el = slot.querySelector(`tr[data-row="${row}"] .table-value`);
                    if (el) { el.value = v; }
                });
            } else if (r.data.value) {
                slot.querySelector('.slot-value').value = r.data.value;
            }
            aiUsed.add(rid + ':' + btn.dataset.option);
            optEl.querySelector('.ai-label').classList.remove('d-none');
        }));

        card.querySelectorAll('.rule-apply').forEach(btn => btn.addEventListener('click', () => {
            const slot = btn.closest('.input-slot');
            const file = slot.querySelector('.rule-file').value;
            const value = slot.querySelector('.rule-value').value;
            slot.querySelectorAll('.table-value').forEach(sel => {
                if (sel.dataset.file === file) { sel.value = value; }
            });
        }));

        const send = card.querySelector('.comment-send');
        if (send) {
            send.addEventListener('click', async () => {
                const text = card.querySelector('.comment-text').value;
                const prop = card.querySelector('.comment-propose');
                const r = await post(`${base}/remedy/${encodeURIComponent(rid)}/comment`,
                                     {text: text, propose_option: prop ? prop.value : ''});
                if (!r.ok) { err.textContent = r.data.error || 'The comment was not saved.'; return; }
                window.location.hash = rid;
                window.location.reload();
            });
        }
    });

    // -- apply -----------------------------------------------------------------------------
    const statusEl = document.getElementById('apply-status');

    function list(title, items) {
        if (!items || !items.length) { return ''; }
        const li = items.map(f => `<li><span class="badge bg-secondary">${esc(f.severity)}</span> ${esc(f.id)} ${esc(f.title)}</li>`).join('');
        return `<h3 class="h6 mt-2">${esc(title)} (${items.length})</h3><ul class="small">${li}</ul>`;
    }

    function esc(s) {
        return String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g,
            c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    }

    function render(state) {
        if (!statusEl) { return; }
        if (!state || state.status === 'none') { statusEl.innerHTML = '<p class="small">Not applied yet.</p>'; return; }
        if (state.status === 'running') {
            statusEl.innerHTML = `<div class="alert alert-info py-2">Applying: ${esc(state.stage || 'starting')}. This takes as long as an audit.</div>`;
            setTimeout(poll, 3000);
            return;
        }
        if (state.status === 'error' || state.status === 'stale') {
            statusEl.innerHTML = `<div class="alert alert-danger py-2">The apply stopped${state.code ? ' (' + esc(state.code) + ')' : ''}: ${esc(state.error || 'it did not finish')}. No output was published.</div>`;
            return;
        }
        const r = state.result || {};
        const out = r.outputs || {};
        const link = (k, label) => out[k] ? `<a class="btn btn-sm btn-outline-secondary" href="${base}/out/${k}">${label}</a>` : '';
        let html = '';
        if (r.verdict_after !== undefined) {
            const cls = r.fixed ? 'success' : 'warning';
            html += `<div class="alert alert-${cls} py-2"><strong>${r.fixed ? 'Fixed' : 'Not fixed yet'}</strong>: verdict ${esc(r.verdict_before)} before, ${esc(r.verdict_after)} after.</div>`;
            if (r.flagged && r.flagged.length) {
                html += `<div class="alert alert-danger py-2">${r.flagged.length} new finding(s) at or above the severity of those closed. Check them first.</div>`;
            }
            if (r.worse_untouched_stages && r.worse_untouched_stages.length) {
                html += `<div class="alert alert-danger py-2">Worse on stages you did not touch: ${r.worse_untouched_stages.map(s => esc(s.stage) + ' ' + esc(s.before) + ' to ' + esc(s.after)).join(', ')}.</div>`;
            }
            html += list('New', r.new) + list('Closed', r.closed) + list('Declared expected', r.declared) + list('Remaining', r.remaining);
        }
        if (r.bound) {
            html += `<p class="small">Removed ${r.bound.removed.axioms} axiom(s) (bound ${r.bound.bounds.axioms}) and ${r.bound.removed.data} data statement(s) (bound ${r.bound.bounds.data}).</p>`;
        }
        html += `<div class="d-flex flex-wrap gap-2">${link('zip', 'Repaired release (.zip)')}${link('patch', 'repair.patch')}${link('fixlog_md', 'FIXLOG.md')}${link('fixlog_json', 'FIXLOG.json')}${link('changelog', 'CHANGELOG draft')}${link('audit_before', 'Audit before')}${link('audit_after', 'Audit after')}<a class="btn btn-sm btn-outline-secondary" href="${base}/issues.zip">Issues with patches (.zip)</a></div>`;
        statusEl.innerHTML = html;
    }

    async function poll() {
        const res = await fetch(`${base}/apply`, {headers: {'Accept': 'application/json'}});
        if (res.ok) {
            const state = await res.json();
            render(state);
            if (state.status === 'done') {
                // statuses of the cards changed (applied / reverted)
                const marker = 'applied-' + (state.finished_at || '');
                if (sessionStorage.getItem('repair-reloaded') !== marker) {
                    sessionStorage.setItem('repair-reloaded', marker);
                    window.location.reload();
                }
            }
        }
    }

    if (statusEl) {
        try { render(JSON.parse(statusEl.dataset.state || '{}')); } catch (e) { render(null); }
    }
    const applyBtn = document.getElementById('apply-btn');
    if (applyBtn) {
        applyBtn.addEventListener('click', async () => {
            applyBtn.disabled = true;
            const r = await post(`${base}/apply`, {});
            applyBtn.disabled = false;
            if (!r.ok) { statusEl.innerHTML = `<div class="alert alert-danger py-2">${esc(r.data.error || 'Could not start.')}</div>`; return; }
            render({status: 'running'});
        });
    }

    // -- pull request (owner only) -----------------------------------------------------------
    const prOut = document.getElementById('pr-result');
    const tokenSave = document.getElementById('pr-token-save');
    if (tokenSave) {
        tokenSave.addEventListener('click', async () => {
            const el = document.getElementById('pr-token');
            const r = await post(`${base}/github-token`, {token: el.value});
            el.value = '';
            prOut.textContent = r.ok ? 'Token stored.' : (r.data.error || 'Could not store the token.');
        });
        document.getElementById('pr-token-delete').addEventListener('click', async () => {
            const r = await post(`${base}/github-token`, undefined, 'DELETE');
            prOut.textContent = r.ok && r.data.deleted ? 'Token forgotten.' : 'No token was stored.';
        });
        document.getElementById('pr-open').addEventListener('click', async () => {
            const body = {repo: document.getElementById('pr-repo').value.trim(),
                          base: document.getElementById('pr-base').value.trim(),
                          prefix: document.getElementById('pr-prefix').value.trim()};
            const dry = await post(`${base}/pull-request`, body);
            if (!dry.ok) { prOut.textContent = dry.data.error || 'Could not prepare the pull request.'; return; }
            const files = dry.data.files || [];
            if (!window.confirm(`Push ${files.length} changed file(s) to a new branch of ${body.repo} and open a pull request against ${body.base}?\n\n` + files.join('\n'))) { return; }
            const r = await post(`${base}/pull-request`, Object.assign(body, {confirm: true}));
            if (!r.ok) { prOut.textContent = r.data.error || 'The pull request failed.'; return; }
            prOut.innerHTML = `Opened <a href="${esc(r.data.url)}" target="_blank" rel="noopener">${esc(r.data.url)}</a>.`;
        });
    }

    // -- members -----------------------------------------------------------------------------
    const add = document.getElementById('member-add');
    if (add) {
        add.addEventListener('click', async () => {
            const r = await post(`${base}/members`, {account: document.getElementById('member-account').value,
                                                    role: document.getElementById('member-role').value});
            if (!r.ok) { document.getElementById('member-error').textContent = r.data.error || 'Could not add.'; return; }
            window.location.reload();
        });
    }
    document.querySelectorAll('.member-remove').forEach(btn => btn.addEventListener('click', async () => {
        const uid = btn.closest('li').dataset.user;
        const r = await post(`${base}/members/${encodeURIComponent(uid)}`, undefined, 'DELETE');
        if (r.ok) { window.location.reload(); }
    }));
})();
