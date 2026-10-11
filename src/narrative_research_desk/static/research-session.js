/* Browser metadata and editable drafts are separate from immutable server runs. */
(() => {
  const byId = id => document.getElementById(id);
  const draftKey = 'narrative-draft-v2';
  const libraryKey = 'narrative-library-v2';
  const oldLibraryKey = 'narrative-recent-work-v1';
  const names = {NVDA:'NVIDIA',AMD:'Advanced Micro Devices',AVGO:'Broadcom',MU:'Micron Technology',INTC:'Intel',MSFT:'Microsoft',AMZN:'Amazon',GOOGL:'Alphabet (Google)'};
  const notice = document.createElement('p'); notice.id = 'session-notice'; notice.className = 'feedback'; notice.setAttribute('role','status'); notice.hidden = true;
  byId('feedback').before(notice);
  const say = text => { notice.hidden = false; notice.textContent = text; };
  let memoryRows = null;
  const readJSON = (key, fallback) => {
    try { const raw = localStorage.getItem(key); return raw === null ? fallback : JSON.parse(raw); }
    catch(error) { say(error instanceof SyntaxError ? 'Saved browser data could not be read. The damaged record has been kept; your server research is safe.' : 'Storage is unavailable. This session can continue, but drafts and library changes cannot persist.'); return fallback; }
  };
  const writeJSON = (key,value) => {
    try { localStorage.setItem(key,JSON.stringify(value)); return true; }
    catch { say('Storage is unavailable or full. This session can continue, but drafts and library changes cannot persist.'); return false; }
  };
  const enrich = row => ({...row, entryId:row.entryId || row.id, companyNames:(row.companies || []).map((symbol,index)=>names[symbol] || row.companyNames?.[index] || symbol)});
  const readLibrary = () => {
    if (memoryRows) return memoryRows;
    const saved = readJSON(libraryKey,null);
    let rows;
    if (saved === null) rows = readJSON(oldLibraryKey,[]);
    else if (saved.version === 2 && Array.isArray(saved.items)) rows = saved.items;
    else { say('Saved library data could not be read. It has been kept for recovery.'); rows = []; }
    if (!Array.isArray(rows)) { say('Saved library data could not be read. It has been kept for recovery.'); rows = []; }
    memoryRows = rows.filter(row=>row && typeof row.id==='string' && /^[a-zA-Z0-9_-]+$/.test(row.id)).map(enrich);
    return memoryRows;
  };
  const saveLibrary = rows => { memoryRows = rows.map(enrich); writeJSON(libraryKey,{version:2,items:memoryRows}); };
  let removed = null;
  const undo = document.createElement('button'); undo.id = 'library-undo'; undo.type = 'button'; undo.className = 'secondary'; undo.textContent = 'Undo removal'; undo.hidden = true; notice.after(undo);
  const changed = () => document.dispatchEvent(new Event('research-library-changed'));
  undo.onclick = () => { if (!removed) return; const rows = [...readLibrary()]; rows.splice(removed.index,0,removed.row); saveLibrary(rows); removed = null; undo.hidden = true; say('Library entry restored.'); changed(); };
  window.ResearchSession = {
    readLibrary,
    remember(data) {
      for(const company of data.companies||[])names[company.ticker]=company.name;
      const rows = [...readLibrary()]; const found = rows.findIndex(row=>row.id===data.run_id && !row.duplicate);
      const old = found >= 0 ? rows[found] : null;
      const row = enrich({...(old || {}),id:data.run_id,entryId:old?.entryId || data.run_id,title:old?.renamed ? old.title : data.question,
        companies:data.watchlist,complete:!!(data.decision || data.user_conclusion),status:data.brief?.status || data.status,time:old?.time || Date.now()});
      if (found >= 0) rows[found] = row;
      else if (rows.length >= 50) { say('Your library keeps up to 50 entries. This new brief is saved on the server; remove a browser entry to add it here. No entry was discarded.'); return; }
      else rows.unshift(row);
      saveLibrary(rows);
    },
    rename(entryId,title) { if (!title?.trim()) return; saveLibrary(readLibrary().map(row=>row.entryId===entryId ? {...row,title:title.trim().slice(0,200),renamed:true} : row)); changed(); },
    async duplicate(entryId) {
      const row = readLibrary().find(row=>row.entryId===entryId); if (!row) return;
      try {
        const response = await fetch('/api/runs/'+encodeURIComponent(row.id)); if (!response.ok) throw new Error();
        const run = await response.json(); const reset = new Event('research-new',{cancelable:true});
        if (!document.dispatchEvent(reset)) return;
        document.dispatchEvent(new CustomEvent('research-copy',{detail:run}));
        say('Editable copy created. It has no saved conclusion; analyzing it creates a new research snapshot.');
      } catch { say('Could not open this research to duplicate it. The original snapshot is retained.'); }
    },
    remove(entryId) { const rows = [...readLibrary()]; const index = rows.findIndex(row=>row.entryId===entryId); if (index < 0) return;
      if (!confirm('Remove this entry from your browser library? Your server research is retained. You can undo the removal.')) return;
      removed = {row:rows[index],index}; rows.splice(index,1); saveLibrary(rows); undo.hidden = false; say('Removed from this browser library. The server research is retained.'); changed(); },
    notice:say
  };
  const fields = ['question','watchlist','source-kind','scope-metric','scope-operation','scope-period','cutoff','evidence-issuer'];
  const documentFields = ['source-text','source-origin','source-permission','support-quote','challenge-quote'];
  const filingFields = ['filing-format','filing-cik','filing-accession','filing-published'];
  let timer = null; let ready = false; let baseRun = null; let uploaded = false; let dirty = false; let documentDirty = false; let copiedFrom = null;
  const snapshot = () => {
    const remember = byId('remember-document').checked;
    const filingMode = byId('filing-mode').checked;
    const ids = filingMode ? [...fields,...filingFields] : remember ? [...fields,...documentFields] : fields;
    return {version:2,baseRun,copied_from:copiedFrom,updatedAt:Date.now(),rememberDocument:remember,fileNeedsReselect:uploaded || byId('filing-mode').checked,
      filingMode,
      fields:Object.fromEntries(ids.map(id=>[id,byId(id).value]))};
  };
  const saveDraft = () => { timer = null; if (ready) writeJSON(draftKey,snapshot()); };
  const queue = () => { if (!ready) return; dirty = true; clearTimeout(timer); timer = setTimeout(saveDraft,500); };
  for (const id of ['research-form','source-form']) {
    byId(id).addEventListener('input',queue); byId(id).addEventListener('change',queue);
  }
  for (const id of ['source-kind','source-file','filing-file']) byId(id).addEventListener('change', () => { if (id !== 'source-kind') { uploaded = true; documentDirty = true; } queue(); });
  byId('source-text').addEventListener('input',()=>{documentDirty = true;});
  document.addEventListener('research-source-registered',()=>{documentDirty = false;});
  byId('remember-document').addEventListener('change', () => { if (!byId('remember-document').checked) { clearTimeout(timer); saveDraft(); } });
  const banner = document.createElement('section'); banner.id = 'draft-restore'; banner.className = 'panel'; banner.hidden = true; banner.setAttribute('aria-label','Saved draft');
  const description = document.createElement('p'); const restore = document.createElement('button'); restore.type = 'button'; restore.className = 'secondary'; restore.textContent = 'Restore draft';
  const discard = document.createElement('button'); discard.type = 'button'; discard.className = 'secondary'; discard.textContent = 'Discard draft'; banner.append(description,restore,discard); notice.before(banner);
  let pendingDraft = null;
  const removeDraft = () => { clearTimeout(timer); timer = null; pendingDraft = null; dirty = false; banner.hidden = true; try { localStorage.removeItem(draftKey); } catch { say('Storage is unavailable. This draft could not be removed from browser storage.'); } };
  restore.onclick = () => {
    if (!pendingDraft) return;
    const saved = pendingDraft;
    byId('remember-document').checked = !!saved.rememberDocument;
    for (const id of [...fields,...documentFields]) if (typeof saved.fields[id] === 'string') byId(id).value = saved.fields[id];
    byId('source-kind').dispatchEvent(new Event('change',{bubbles:true}));
    byId('filing-mode').checked = saved.filingMode === true;
    byId('filing-mode').dispatchEvent(new Event('change',{bubbles:true}));
    byId('source-file').value = ''; byId('filing-file').value = '';
    for (const id of filingFields) byId(id).value = typeof saved.fields[id] === 'string' ? saved.fields[id] : id === 'filing-format' ? 'html' : '';
    byId('filing-controls').open = saved.filingMode === true;
    // Mode initialization adjusts defaults; restore the actual saved inputs afterward.
    for (const id of [...fields,...documentFields]) if (typeof saved.fields[id] === 'string') byId(id).value = saved.fields[id];
    document.dispatchEvent(new Event('research-draft-restored')); banner.hidden = true; baseRun = saved.baseRun; uploaded = saved.fileNeedsReselect;
    copiedFrom = saved.copied_from || null; documentDirty = saved.fileNeedsReselect || !!saved.fields['source-text'];
    say(saved.fileNeedsReselect ? 'Draft restored. Choose your uploaded file again and register its source before analyzing.' : 'Draft restored. Review the question and register your document if needed.'); byId('question').focus(); queue();
  };
  discard.onclick = () => { removeDraft(); say('Draft discarded. Your saved research is retained.'); byId('question').focus(); };
  document.addEventListener('desk-ready', () => {
    ready = true; const draft = readJSON(draftKey,null);
    if (draft && (draft.version !== 2 || !draft.fields || typeof draft.fields !== 'object' || Array.isArray(draft.fields))) { say('Saved draft data could not be read. It has been kept for recovery.'); return; }
    if (draft) { pendingDraft = draft; banner.hidden = false; description.textContent = location.hash.startsWith('#run=') ? 'A separate editable draft is available. Restore it to leave this saved snapshot and continue editing.' : 'You have an unfinished draft. Restore it to continue.'; }
  });
  document.addEventListener('research-rendered', event => { if (event.detail) baseRun = event.detail.run_id; });
  document.addEventListener('research-analyzed',removeDraft);
  document.addEventListener('research-new', event => {
    if ((dirty || pendingDraft || documentDirty) && !confirm('Start new research and discard the unfinished draft? Cancel to keep your draft.')) { event.preventDefault(); return; }
    removeDraft(); baseRun = null; copiedFrom = null; uploaded = false; documentDirty = false;
  });
  document.addEventListener('research-copy',event=>{copiedFrom = event.detail.run_id;baseRun = null;queueMicrotask(()=>{dirty=true;saveDraft();});});
  window.addEventListener('beforeunload',event=>{if(documentDirty){event.preventDefault();event.returnValue='';}});
  window.addEventListener('pagehide', () => { if (timer) { clearTimeout(timer); saveDraft(); } });
})();
