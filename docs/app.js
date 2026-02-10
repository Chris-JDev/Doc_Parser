(() => {
  const els = {
    backendUrl: document.getElementById('backendUrl'),
    uploadForm: document.getElementById('uploadForm'),
    files: document.getElementById('files'),
    translate: document.getElementById('translate'),
    uploadBtn: document.getElementById('uploadBtn'),
    uploadOut: document.getElementById('uploadOut'),
    jobs: document.getElementById('jobs'),
    log: document.getElementById('log'),
    clearBtn: document.getElementById('clearBtn'),
  };

  const storeKey = 'doc_parser_backend_url';

  function log(line) {
    const ts = new Date().toLocaleTimeString();
    els.log.textContent = `[${ts}] ${line}\n` + els.log.textContent;
  }

  function getBackend() {
    const v = (els.backendUrl.value || '').trim().replace(/\/$/, '');
    return v;
  }

  function setBackend(v) {
    els.backendUrl.value = v || '';
    if (v) localStorage.setItem(storeKey, v);
  }

  function api(path) {
    const b = getBackend();
    if (!b) throw new Error('Set the Render Backend URL first.');
    return `${b}${path}`;
  }

  function makeJobCard(jobId) {
    const div = document.createElement('div');
    div.style.padding = '12px';
    div.style.border = '1px solid #232a2c';
    div.style.borderRadius = '12px';
    div.style.margin = '10px 0';
    div.innerHTML = `
      <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap">
        <div>
          <div style="font-weight:700">Job: ${jobId}</div>
          <div class="muted" id="status-${jobId}">queued</div>
        </div>
        <div style="display:flex;gap:10px;align-items:center">
          <a href="#" id="open-${jobId}">Open job page</a>
          <a href="#" id="doc-${jobId}" style="display:none">Open document</a>
        </div>
      </div>
      <div class="muted" id="progress-${jobId}" style="margin-top:8px"></div>
    `;
    els.jobs.prepend(div);

    const open = div.querySelector(`#open-${jobId}`);
    open.addEventListener('click', (e) => {
      e.preventDefault();
      window.open(api(`/jobs/${jobId}`), '_blank');
    });

    const docLink = div.querySelector(`#doc-${jobId}`);
    return { div, docLink };
  }

  function listenJob(jobId, card) {
    const url = api(`/api/jobs/${jobId}/events`);
    log(`Connecting SSE: ${url}`);
    const es = new EventSource(url);

    const statusEl = document.getElementById(`status-${jobId}`);
    const progressEl = document.getElementById(`progress-${jobId}`);

    es.addEventListener('initial', (ev) => {
      try {
        const d = JSON.parse(ev.data);
        statusEl.textContent = d.status || 'queued';
        progressEl.textContent = d.page_count ? `Pages: ${d.page_count}` : '';
      } catch {}
    });

    es.addEventListener('progress', (ev) => {
      try {
        const d = JSON.parse(ev.data);
        statusEl.textContent = d.status || 'processing';
        if (typeof d.current_page === 'number' && typeof d.page_count === 'number') {
          progressEl.textContent = `Page ${d.current_page + 1} / ${d.page_count}`;
        } else if (d.message) {
          progressEl.textContent = d.message;
        }
      } catch {
        progressEl.textContent = ev.data;
      }
    });

    es.addEventListener('done', (ev) => {
      statusEl.textContent = 'done';
      try {
        const d = JSON.parse(ev.data);
        if (d.document_id) {
          card.docLink.style.display = 'inline';
          card.docLink.href = '#';
          card.docLink.onclick = (e) => {
            e.preventDefault();
            window.open(api(`/docs/${d.document_id}`), '_blank');
          };
        }
      } catch {}
      es.close();
    });

    es.addEventListener('error', (ev) => {
      statusEl.textContent = 'failed';
      progressEl.textContent = 'Error. Open job page for details.';
      es.close();
    });
  }

  els.clearBtn.addEventListener('click', () => {
    els.jobs.innerHTML = '';
    els.uploadOut.textContent = '';
    els.log.textContent = '';
  });

  els.backendUrl.addEventListener('change', () => {
    const b = getBackend();
    setBackend(b);
    log(`Backend set: ${b}`);
  });

  els.uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const backend = getBackend();
      if (!backend) throw new Error('Set the Render Backend URL first.');

      const files = els.files.files;
      if (!files || files.length === 0) throw new Error('Choose at least one PDF.');

      els.uploadBtn.disabled = true;
      els.uploadOut.textContent = 'Uploading...';

      const fd = new FormData();
      for (const f of files) fd.append('files', f);
      if (els.translate.checked) fd.append('translate_to_english', 'true');

      const res = await fetch(api('/api/upload'), { method: 'POST', body: fd });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(`Upload failed (${res.status}): ${t}`);
      }

      const data = await res.json();
      const ids = data.job_ids || [];
      els.uploadOut.textContent = `Started ${ids.length} job(s).`;

      for (const id of ids) {
        const card = makeJobCard(id);
        listenJob(id, card);
      }

      log(`Upload OK: ${JSON.stringify(data)}`);
    } catch (err) {
      els.uploadOut.textContent = err.message || String(err);
      log(`ERROR: ${err.message || String(err)}`);
    } finally {
      els.uploadBtn.disabled = false;
      els.files.value = '';
    }
  });

  // init
  const saved = localStorage.getItem(storeKey);
  if (saved) {
    setBackend(saved);
    log(`Loaded saved backend: ${saved}`);
  } else {
    log('Set your Render Backend URL to begin.');
  }
})();
