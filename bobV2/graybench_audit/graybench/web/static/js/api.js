/* GrayBench API client */

const API = {
    base: '/api',

    async get(path) {
        const resp = await fetch(this.base + path);
        if (!resp.ok) throw new Error(`API error: ${resp.status}`);
        return resp.json();
    },

    async post(path, data) {
        const resp = await fetch(this.base + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ error: resp.statusText }));
            throw new Error(err.error || resp.statusText);
        }
        return resp.json();
    },

    async put(path, data) {
        const resp = await fetch(this.base + path, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error(`API error: ${resp.status}`);
        return resp.json();
    },

    async del(path) {
        const resp = await fetch(this.base + path, { method: 'DELETE' });
        if (!resp.ok) throw new Error(`API error: ${resp.status}`);
        return resp.json();
    },

    // Convenience methods
    getRuns: (params) => API.get('/runs' + (params ? '?' + new URLSearchParams(params) : '')),
    getRun: (id) => API.get(`/runs/${id}`),
    createRun: (data) => API.post('/runs', data),
    deleteRun: (id) => API.del(`/runs/${id}`),

    getModels: (provider) => API.get('/models' + (provider ? `?provider=${provider}` : '')),
    addModel: (data) => API.post('/models', data),
    updateModel: (provider, modelId, data) => API.put(`/models/${provider}/${modelId}`, data),
    deleteModel: (provider, modelId) => API.del(`/models/${provider}/${modelId}`),

    getKeys: () => API.get('/keys'),
    setKey: (data) => API.post('/keys', data),
    deleteKey: (provider) => API.del(`/keys/${provider}`),
    testKey: (provider) => API.post(`/keys/${provider}/test`, {}),

    getBenchmarks: () => API.get('/benchmarks'),
};
