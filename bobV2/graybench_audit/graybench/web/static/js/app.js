/* GrayBench SPA – Main Application */

const App = {
    currentPage: 'dashboard',

    init() {
        this.bindNav();
        this.navigate('dashboard');
    },

    bindNav() {
        document.querySelectorAll('.nav-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.navigate(btn.dataset.page);
            });
        });
    },

    navigate(page) {
        this.currentPage = page;
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.page === page));
        const main = document.getElementById('main');
        main.innerHTML = '<div class="spinner" style="margin:60px auto;display:block;"></div>';

        switch (page) {
            case 'dashboard': Dashboard.render(main); break;
            case 'launcher': Launcher.render(main); break;
            case 'results': Results.render(main); break;
            case 'settings': Settings.render(main); break;
            default: main.innerHTML = '<div class="empty-state"><h3>Page not found</h3></div>';
        }
    },

    toast(message, type = 'success') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    },
};

/* ─── Dashboard ────────────────────────────────────────────────────────── */

const Dashboard = {
    async render(el) {
        try {
            const [runs, models, keys] = await Promise.all([
                API.getRuns({ limit: 10 }),
                API.getModels(),
                API.getKeys(),
            ]);

            const completed = runs.filter(r => r.status === 'completed');
            const totalPassed = completed.reduce((s, r) => s + (r.passed_tasks || 0), 0);
            const totalTasks = completed.reduce((s, r) => s + (r.total_tasks || 0), 0);
            const totalCost = completed.reduce((s, r) => s + (r.total_cost_usd || 0), 0);

            el.innerHTML = `
                <div class="stats-row fade-in">
                    <div class="stat-card">
                        <div class="stat-label">Total Runs</div>
                        <div class="stat-value blue">${runs.length}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Pass Rate</div>
                        <div class="stat-value green">${totalTasks ? ((totalPassed/totalTasks)*100).toFixed(1) : 0}%</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Models</div>
                        <div class="stat-value">${models.length}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">API Keys</div>
                        <div class="stat-value">${keys.length}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Total Cost</div>
                        <div class="stat-value yellow">$${totalCost.toFixed(4)}</div>
                    </div>
                </div>

                <div class="card fade-in">
                    <div class="card-header">
                        <span class="card-title">Recent Runs</span>
                        <button class="btn btn-primary btn-sm" onclick="App.navigate('launcher')">New Run</button>
                    </div>
                    <div class="table-wrap">
                        ${this.renderRunsTable(runs)}
                    </div>
                </div>
            `;
        } catch (err) {
            el.innerHTML = `<div class="empty-state"><h3>Failed to load</h3><p>${err.message}</p></div>`;
        }
    },

    renderRunsTable(runs) {
        if (!runs.length) return '<div class="empty-state"><h3>No runs yet</h3><p>Launch a benchmark to get started.</p></div>';
        const statusBadge = (s) => ({
            completed: '<span class="badge badge-green">done</span>',
            running: '<span class="badge badge-yellow">running</span>',
            failed: '<span class="badge badge-red">failed</span>',
            canceled: '<span class="badge badge-dim">canceled</span>',
            pending: '<span class="badge badge-dim">pending</span>',
        }[s] || s);

        return `<table>
            <thead><tr>
                <th>Run ID</th><th>Benchmark</th><th>Model</th><th>Route</th>
                <th>Status</th><th>Score</th><th>Pass/Total</th><th>Cost</th><th>Date</th>
            </tr></thead>
            <tbody>
                ${runs.map(r => `
                    <tr class="clickable" onclick="Results.showRun('${r.run_id}')">
                        <td style="font-family:var(--font-mono);font-size:12px">${r.run_id}</td>
                        <td>${r.benchmark}</td>
                        <td><strong>${r.model_provider}/${r.model_id}</strong></td>
                        <td>${r.route}</td>
                        <td>${statusBadge(r.status)}</td>
                        <td>${r.score != null ? (r.score*100).toFixed(1)+'%' : '—'}</td>
                        <td>${r.passed_tasks || 0}/${r.total_tasks || 0}</td>
                        <td>$${(r.total_cost_usd || 0).toFixed(4)}</td>
                        <td style="font-size:12px;color:var(--text-dim)">${(r.created_at || '').slice(0,16)}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>`;
    },
};

/* ─── Launcher ─────────────────────────────────────────────────────────── */

const Launcher = {
    async render(el) {
        try {
            const [benchmarks, models] = await Promise.all([
                API.getBenchmarks(),
                API.getModels(),
            ]);

            // Group models by provider
            const providers = {};
            models.forEach(m => {
                if (!providers[m.provider]) providers[m.provider] = [];
                providers[m.provider].push(m);
            });

            el.innerHTML = `
                <div class="card fade-in">
                    <div class="card-header">
                        <span class="card-title">Launch Benchmark</span>
                    </div>
                    <form id="launch-form">
                        <div class="grid-2">
                            <div class="form-group">
                                <label>Benchmark</label>
                                <select class="form-select" name="benchmark" required>
                                    ${benchmarks.map(b => `<option value="${b.name}">${b.display_name}</option>`).join('')}
                                </select>
                            </div>
                            <div class="form-group">
                                <label>Model</label>
                                <select class="form-select" name="model" required>
                                    ${Object.entries(providers).map(([prov, mods]) =>
                                        `<optgroup label="${prov.toUpperCase()}">${mods.map(m =>
                                            `<option value="${prov}/${m.model_id}">${m.display_name} ($${m.input_price_per_m ?? '?'}/$${m.output_price_per_m ?? '?'}/M)</option>`
                                        ).join('')}</optgroup>`
                                    ).join('')}
                                </select>
                            </div>
                        </div>
                        <div class="grid-3">
                            <div class="form-group">
                                <label>Route</label>
                                <select class="form-select" name="route">
                                    <option value="direct">Direct</option>
                                    <option value="openrouter">OpenRouter</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label>Task Limit</label>
                                <input type="number" class="form-input" name="tasks" placeholder="All" min="1">
                            </div>
                            <div class="form-group">
                                <label>Parallel</label>
                                <input type="number" class="form-input" name="parallel" value="1" min="1" max="16">
                            </div>
                        </div>
                        <button type="submit" class="btn btn-primary">Launch Benchmark</button>
                    </form>
                </div>
            `;

            document.getElementById('launch-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                const form = new FormData(e.target);
                try {
                    const result = await API.createRun({
                        benchmark: form.get('benchmark'),
                        model: form.get('model'),
                        route: form.get('route'),
                        tasks: form.get('tasks') ? parseInt(form.get('tasks')) : null,
                        parallel: parseInt(form.get('parallel') || 1),
                    });
                    App.toast(`Run started: ${result.run_id}`);
                    App.navigate('results');
                } catch (err) {
                    App.toast(err.message, 'error');
                }
            });
        } catch (err) {
            el.innerHTML = `<div class="empty-state"><h3>Failed to load</h3><p>${err.message}</p></div>`;
        }
    },
};

/* ─── Results ──────────────────────────────────────────────────────────── */

const Results = {
    async render(el) {
        try {
            const runs = await API.getRuns({ limit: 50 });
            el.innerHTML = `
                <div class="card fade-in">
                    <div class="card-header">
                        <span class="card-title">Benchmark Results</span>
                        <button class="btn btn-sm" onclick="App.navigate('launcher')">New Run</button>
                    </div>
                    <div class="table-wrap">
                        ${Dashboard.renderRunsTable(runs)}
                    </div>
                </div>
                <div id="run-detail"></div>
            `;
        } catch (err) {
            el.innerHTML = `<div class="empty-state"><h3>Failed to load</h3><p>${err.message}</p></div>`;
        }
    },

    async showRun(runId) {
        const detail = document.getElementById('run-detail') || document.getElementById('main');
        try {
            const run = await API.getRun(runId);
            const score = ((run.score || 0) * 100).toFixed(1);

            detail.innerHTML = `
                <div class="card fade-in" style="margin-top:16px">
                    <div class="card-header">
                        <span class="card-title">Run: ${run.run_id}</span>
                        <button class="btn btn-danger btn-sm" onclick="Results.deleteRun('${runId}')">Delete</button>
                    </div>
                    <div class="grid-3" style="margin-bottom:16px">
                        <div><strong>Benchmark:</strong> ${run.benchmark}</div>
                        <div><strong>Model:</strong> ${run.model}</div>
                        <div><strong>Route:</strong> ${run.route}</div>
                        <div><strong>Status:</strong> ${run.status}</div>
                        <div><strong>Score:</strong> <span style="color:var(--green);font-weight:700">${score}%</span></div>
                        <div><strong>Passed:</strong> ${run.passed}/${run.total}</div>
                        <div><strong>Cost:</strong> $${(run.cost_usd || 0).toFixed(4)}</div>
                        <div><strong>Duration:</strong> ${(run.duration_s || 0).toFixed(1)}s</div>
                    </div>
                    ${run.tasks && run.tasks.length ? this.renderTasksTable(run.tasks) : ''}
                </div>
            `;
        } catch (err) {
            detail.innerHTML = `<div class="card"><p style="color:var(--red)">Error: ${err.message}</p></div>`;
        }
    },

    renderTasksTable(tasks) {
        return `<table>
            <thead><tr>
                <th>Task</th><th>Status</th><th>Score</th><th>Duration</th><th>Tokens</th><th>Cost</th><th>Error</th>
            </tr></thead>
            <tbody>
                ${tasks.map(t => `
                    <tr>
                        <td style="font-family:var(--font-mono);font-size:12px">${t.task_id || t.task_name || '?'}</td>
                        <td>${t.passed ? '<span class="badge badge-green">PASS</span>' : '<span class="badge badge-red">FAIL</span>'}</td>
                        <td>${t.score != null ? (t.score*100).toFixed(0)+'%' : '—'}</td>
                        <td>${(t.duration_s || 0).toFixed(1)}s</td>
                        <td>${t.tokens_used || 0}</td>
                        <td>$${(t.cost_usd || 0).toFixed(4)}</td>
                        <td style="color:var(--red);font-size:12px;max-width:200px;overflow:hidden;text-overflow:ellipsis">${t.error || ''}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>`;
    },

    async deleteRun(runId) {
        if (!confirm(`Delete run ${runId}?`)) return;
        try {
            await API.deleteRun(runId);
            App.toast('Run deleted');
            App.navigate('results');
        } catch (err) {
            App.toast(err.message, 'error');
        }
    },
};

/* ─── Settings ─────────────────────────────────────────────────────────── */

const Settings = {
    currentTab: 'keys',

    async render(el) {
        el.innerHTML = `
            <div class="card fade-in">
                <div class="tabs">
                    <button class="tab active" data-tab="keys">API Keys</button>
                    <button class="tab" data-tab="models">Models</button>
                </div>
                <div id="settings-content"></div>
            </div>
        `;

        el.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                el.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                this.currentTab = tab.dataset.tab;
                this.renderTab(document.getElementById('settings-content'));
            });
        });

        this.renderTab(document.getElementById('settings-content'));
    },

    async renderTab(el) {
        if (this.currentTab === 'keys') await this.renderKeys(el);
        else await this.renderModels(el);
    },

    async renderKeys(el) {
        try {
            const keys = await API.getKeys();
            el.innerHTML = `
                <div style="margin-bottom:16px">
                    <h3 style="margin-bottom:12px">API Keys</h3>
                    <form id="add-key-form" style="display:flex;gap:8px;margin-bottom:16px">
                        <select class="form-select" name="provider" style="width:150px" required>
                            <option value="">Provider...</option>
                            <option value="openai">OpenAI</option>
                            <option value="anthropic">Anthropic</option>
                            <option value="google">Google</option>
                            <option value="deepseek">DeepSeek</option>
                            <option value="moonshot">Moonshot</option>
                            <option value="openrouter">OpenRouter</option>
                        </select>
                        <input type="password" class="form-input" name="key" placeholder="API Key" required style="flex:1">
                        <button type="submit" class="btn btn-primary btn-sm">Save</button>
                    </form>
                </div>
                <table>
                    <thead><tr><th>Provider</th><th>Name</th><th>Source</th><th>Active</th><th>Actions</th></tr></thead>
                    <tbody>
                        ${keys.length ? keys.map(k => `
                            <tr>
                                <td><strong>${k.provider}</strong></td>
                                <td>${k.key_name || ''}</td>
                                <td>${k.source}</td>
                                <td>${k.is_active ? '<span class="badge badge-green">yes</span>' : '<span class="badge badge-dim">no</span>'}</td>
                                <td>
                                    <button class="btn btn-sm" onclick="Settings.testKey('${k.provider}')">Test</button>
                                    ${k.source === 'database' ? `<button class="btn btn-danger btn-sm" onclick="Settings.deleteKey('${k.provider}')">Delete</button>` : ''}
                                </td>
                            </tr>
                        `).join('') : '<tr><td colspan="5" style="text-align:center;color:var(--text-dim)">No keys configured</td></tr>'}
                    </tbody>
                </table>
            `;

            document.getElementById('add-key-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                const form = new FormData(e.target);
                try {
                    await API.setKey({ provider: form.get('provider'), key: form.get('key') });
                    App.toast('Key saved');
                    this.renderTab(el);
                } catch (err) {
                    App.toast(err.message, 'error');
                }
            });
        } catch (err) {
            el.innerHTML = `<p style="color:var(--red)">Error: ${err.message}</p>`;
        }
    },

    async testKey(provider) {
        App.toast(`Testing ${provider}...`);
        try {
            const result = await API.testKey(provider);
            App.toast(`${provider}: OK`);
        } catch (err) {
            App.toast(`${provider}: ${err.message}`, 'error');
        }
    },

    async deleteKey(provider) {
        if (!confirm(`Delete API key for ${provider}?`)) return;
        try {
            await API.deleteKey(provider);
            App.toast('Key deleted');
            this.renderTab(document.getElementById('settings-content'));
        } catch (err) {
            App.toast(err.message, 'error');
        }
    },

    async renderModels(el) {
        try {
            const models = await API.getModels();
            el.innerHTML = `
                <div style="margin-bottom:16px">
                    <h3 style="margin-bottom:12px">Models Registry</h3>
                    <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px">${models.length} models configured</p>
                </div>
                <div class="table-wrap">
                    <table>
                        <thead><tr>
                            <th>Provider</th><th>Model ID</th><th>Display Name</th>
                            <th>Status</th><th>Input $/M</th><th>Cached $/M</th><th>Output $/M</th>
                            <th>Actions</th>
                        </tr></thead>
                        <tbody>
                            ${models.map(m => `
                                <tr>
                                    <td style="color:var(--cyan)">${m.provider}</td>
                                    <td style="font-family:var(--font-mono);font-size:12px"><strong>${m.model_id}</strong></td>
                                    <td>${m.display_name}</td>
                                    <td>${m.status === 'active' ? '<span class="badge badge-green">active</span>' : `<span class="badge badge-dim">${m.status}</span>`}</td>
                                    <td>$${m.input_price_per_m != null ? m.input_price_per_m.toFixed(2) : '—'}</td>
                                    <td>${m.cached_price_per_m != null ? '$'+m.cached_price_per_m.toFixed(3) : 'N/A'}</td>
                                    <td>$${m.output_price_per_m != null ? m.output_price_per_m.toFixed(2) : '—'}</td>
                                    <td>
                                        <button class="btn btn-danger btn-sm" onclick="Settings.deleteModel('${m.provider}','${m.model_id}')">Delete</button>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `;
        } catch (err) {
            el.innerHTML = `<p style="color:var(--red)">Error: ${err.message}</p>`;
        }
    },

    async deleteModel(provider, modelId) {
        if (!confirm(`Delete ${provider}/${modelId}?`)) return;
        try {
            await API.deleteModel(provider, modelId);
            App.toast('Model deleted');
            this.renderTab(document.getElementById('settings-content'));
        } catch (err) {
            App.toast(err.message, 'error');
        }
    },
};

/* ─── Init ─────────────────────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => App.init());
