(() => {
  const byId = (id) => document.getElementById(id);
  const companyNames = {NVDA:'NVIDIA',AMD:'Advanced Micro Devices',AVGO:'Broadcom',MU:'Micron Technology',INTC:'Intel',MSFT:'Microsoft',AMZN:'Amazon',GOOGL:'Alphabet (Google)'};
  const metricNames = {Revenues:'Revenue',RevenueFromContractWithCustomerExcludingAssessedTax:'Revenue (excluding assessed tax)',RevenueFromContractWithCustomerIncludingAssessedTax:'Revenue (including assessed tax)',NetIncomeLoss:'Net income',PaymentsToAcquirePropertyPlantAndEquipment:'Capital expenditure'};
  const form = byId('research-form');
  const feedback = byId('feedback');
  let activeRun = null;
  let selectedNarrative = null;
  let revision = 0;
  let suppliedSource = null;
  let secSource = null;
  let dynamicCompanies = false;
  let currentData = null;
  let portfolioDirty = false;
  let filingRaw = null;
  let filingPreviewBody = null;
  let pendingConclusion = null;
  const selectedExcerpts = new Map();
  const mode = byId('source-kind');
  document.querySelector('label[for="scope-metric"]').textContent = 'Measure for this question';
  const optionalPanel = (node, id, title) => {
    const details = document.createElement('details'); details.id = id; details.className = 'panel optional-research';
    const summary = document.createElement('summary'); summary.textContent = title; node.before(details); details.append(summary,node); return details;
  };
  const optionalFacts = optionalPanel(byId('structured-facts'),'optional-facts','Browse all reported figures');
  const optionalPortfolio = optionalPanel(byId('portfolio-panel'),'optional-portfolio','Explore portfolio scenarios (optional)');
  const optionalInterpretations = optionalPanel(document.querySelector('#results>.compare'),'optional-interpretations','Explore interpretation lenses (optional)');
  const optionalEvidence = document.createElement('details'); optionalEvidence.id = 'optional-evidence'; optionalEvidence.className = 'panel optional-research';
  const evidenceSummary = document.createElement('summary'); evidenceSummary.textContent = 'Evidence and limitations';
  const evidencePanels = [...document.querySelectorAll('#results>.evidence-grid')]; evidencePanels[0].before(optionalEvidence); optionalEvidence.append(evidenceSummary,...evidencePanels);
  byId('answer-brief').after(document.querySelector('#results>.decision'));
  const labelMode = (supplied) => {
    document.querySelector('.mode-chip').textContent = supplied ? 'Your document' : 'Sample research';
    byId('setup-title').textContent = supplied ? 'Research your document' : 'Try the example';
    document.querySelector('.setup .eyebrow').textContent = supplied ? 'YOUR DOCUMENT · YOUR ANNOTATIONS' : 'SYNTHETIC EXAMPLE · NOT MARKET DATA';
    document.querySelector('footer span:last-child').textContent = supplied ? 'Source claims and annotations require your review.' : 'Synthetic example data is not real market evidence.';
    if (mode.value === 'PUBLIC_READ') {
      document.querySelector('.mode-chip').textContent = 'Company financials';
      byId('setup-title').textContent = 'Explore company financials';
      document.querySelector('.setup .eyebrow').textContent = 'SEC COMPANY FINANCIALS';
      document.querySelector('footer span:last-child').textContent = 'Saved company figures. Check reporting dates and original sources before drawing conclusions.';
    }
  };
  const clearRun = () => { revision++; activeRun = null; currentData = null; selectedNarrative = null; pendingConclusion = null; portfolioDirty = false; byId('results').hidden = true; byId('export').hidden = true; byId('export-md').hidden = true; byId('choose').disabled = true; byId('save-conclusion').disabled = true; history.replaceState(null, '', location.pathname + location.search); };
  document.addEventListener('research-new', event => {
    if (event.defaultPrevented) return;
    clearRun(); suppliedSource = null; filingRaw = null; filingPreviewBody = null;
    for (const id of ['question','source-text','support-quote','challenge-quote','decision-note','filing-cik','filing-accession','filing-published','portfolio-positions','basket-a','basket-b','rationale-a','rationale-b','invalidation-a','invalidation-b','source-file','filing-file','portfolio-file']) byId(id).value = '';
    byId('conclusion-verdict').value = ''; byId('quote-suggestions').replaceChildren(); byId('run-id').textContent = '';
    byId('filing-mode').checked = false; byId('source-text').readOnly = false; byId('source-file').disabled = false;
    const companies = byId('watchlist').value; setMode(); byId('watchlist').value = companies;
    document.dispatchEvent(new Event('research-reset')); message('Start a new question. Your source and company preferences are kept.'); byId('question').focus();
  });
  document.addEventListener('research-copy', event => {
    const data = event.detail; mode.value = data.mode; setMode();
    byId('question').value = data.question; byId('watchlist').value = data.watchlist.join(', '); byId('source').value = data.source_id;
    byId('cutoff').value = new Date(data.cutoff).toISOString().slice(0,23);
    byId('scope-metric').value = data.research_scope?.metric || ''; byId('scope-operation').value = data.research_scope?.operation || ''; byId('scope-period').value = data.research_scope?.period_request || 'annual';
    if (data.source_document) { suppliedSource = {source_id:data.source_id,available_at:data.source_document.available_at}; byId('source-text').value = data.source_document.text; byId('source-origin').value = data.source_document.origin; }
    document.dispatchEvent(new Event('research-reset')); byId('question').focus();
  });
  document.addEventListener('research-draft-restored', () => { clearRun(); suppliedSource = null; filingRaw = null; filingPreviewBody = null; byId('source-import').hidden = mode.value !== 'USER_SUPPLIED'; labelMode(mode.value === 'USER_SUPPLIED'); document.dispatchEvent(new Event('research-reset')); });
  const setMode = () => {
    const supplied = mode.value === 'USER_SUPPLIED';
    byId('source-import').hidden = !supplied;
    byId('source').value = supplied ? suppliedSource?.source_id || '' : 'fixture-ai-capex-001';
    byId('cutoff').value = supplied ? (suppliedSource ? new Date(new Date(suppliedSource.available_at).getTime() + 1).toISOString().slice(0, 23) : '') : '2026-09-15T00:00';
    byId('question-help').textContent = supplied ? 'Frame your question around the quotes you added. You choose which evidence supports or challenges it.' : 'Try the ready-made example. Its evidence is illustrative and stays the same when you edit the question.';
    if (mode.value === 'PUBLIC_READ') {
      byId('source').value = secSource?.source_id || 'retained-sec-2026-09-24';
      byId('cutoff').value = new Date(Math.max(Date.now(), Date.parse(secSource?.available_at) || 0) + 1).toISOString().slice(0, 23);
      byId('watchlist').value = ['NVDA','AMD'].filter(symbol=>!secSource || secSource.issuers.includes(symbol)).join(', ');
      if (byId('question').value === 'Does AI spending support NVIDIA growth?') byId('question').value = 'How do NVIDIA and AMD compare on reported revenue?';
      byId('question-help').textContent = 'Explore SEC company financial reports. Search companies by name or ticker; reporting dates and source details appear with your answer.';
    }
    labelMode(supplied);
  };
  mode.addEventListener('change', () => { clearRun(); setMode(); });
  form.addEventListener('input', clearRun);
  byId('source-form').addEventListener('input', () => { suppliedSource = null; clearRun(); if (mode.value === 'USER_SUPPLIED') byId('source').value = ''; });
  byId('source-text').addEventListener('input', () => { byId('quote-suggestions').textContent = 'Document changed. Find excerpts again and confirm your labels.'; byId('support-quote').value = ''; byId('challenge-quote').value = ''; });
  byId('suggest-quotes').addEventListener('click', async () => {
    const text = byId('source-text').value; const issuer = byId('evidence-issuer').value.trim(); const stamp = revision;
    try {
      const response = await api('/api/quote-suggestions',{method:'POST',body:JSON.stringify({text,issuer_id:issuer,metric:byId('scope-metric').value || 'revenue'})});
      const data = await response.json(); if (stamp !== revision || text !== byId('source-text').value) return;
      const list = byId('quote-suggestions'); list.replaceChildren();
      if (!data.suggestions.length) list.textContent = 'No relevant excerpts found. Review the document and select an exact quote yourself.';
      for (const item of data.suggestions) {
        const card = document.createElement('article'); const label = document.createElement('strong'); label.textContent = 'Relevant excerpt';
        const quote = document.createElement('blockquote'); quote.textContent = item.quote;
        const help = document.createElement('p'); help.textContent = 'Relevance does not establish company attribution or support. Confirm the company above and choose your label.';
        card.append(label,quote,help);
        for (const [stance,id] of [['supporting','support-quote'],['challenging','challenge-quote']]) {
          const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = `Use as ${stance} quote`;
          button.onclick = () => { if (text !== byId('source-text').value) { list.textContent = 'Document changed. Find excerpts again.'; return; } byId(id).value = item.quote; selectedExcerpts.set(id,{text,quote:item.quote,start:item.start}); byId(id).dispatchEvent(new Event('input',{bubbles:true})); message('Quote selected. Confirm its company and meaning in context.'); };
          card.append(button);
        } list.append(card);
      }
    } catch (error) { message('Could not find excerpts: '+error.message,'REJECTED'); }
  });
  byId('source-file').addEventListener('change', async () => {
    if (byId('filing-mode').checked) { message('Use the local filing file control for retained-byte import.', 'REJECTED'); return; }
    const file = byId('source-file').files[0];
    if (!file) return;
    try {
      if (file.size > 1_000_000) throw new Error('Choose a document smaller than 1 MB.');
      const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
      byId('source-text').value = text; byId('source-origin').value = file.name;
      byId('quote-suggestions').textContent = 'Document changed. Find excerpts again.'; byId('support-quote').value = ''; byId('challenge-quote').value = '';
      suppliedSource = null; clearRun(); byId('source').value = '';
      message('Document loaded. Label exact quotes and register the source.');
    } catch (error) { message(error.message, 'REJECTED'); }
  });
  const filingBody = () => ({raw_base64: filingRaw, format: byId('filing-format').value,
    issuer_id: byId('evidence-issuer').value.trim(), cik: byId('filing-cik').value.trim(),
    accession: byId('filing-accession').value.trim(), origin: byId('source-origin').value,
    permission: byId('source-permission').value, published_at: byId('filing-published').value.trim() || null});
  byId('filing-mode').addEventListener('change', () => {
    byId('source-text').readOnly = byId('filing-mode').checked;
    byId('source-text').maxLength = byId('filing-mode').checked ? 2 * 1024 * 1024 : 1_000_000;
    byId('source-file').disabled = byId('filing-mode').checked;
    filingPreviewBody = null;
    if (byId('filing-mode').checked) byId('source-text').value = '';
  });
  byId('filing-file').addEventListener('change', async () => {
    filingRaw = null; filingPreviewBody = null;
    const file = byId('filing-file').files[0]; if (!file) return;
    const stamp = revision;
    try {
      if (file.size > 4 * 1024 * 1024) throw new Error('Choose a filing no larger than 4 MiB.');
      const bytes = new Uint8Array(await file.arrayBuffer());
      const chunks = [];
      for (let i = 0; i < bytes.length; i += 8192) chunks.push(String.fromCharCode(...bytes.subarray(i, i + 8192)));
      if (stamp !== revision) return;
      filingRaw = btoa(chunks.join(''));
      message('Raw file loaded locally. Enter provenance and permission, then preview.', 'PARTIAL');
    } catch (error) { message(error.message, 'REJECTED'); }
  });
  byId('preview-filing').addEventListener('click', async () => {
    if (!byId('filing-mode').checked || !filingRaw) { message('Enable filing import and choose a local file.', 'INSUFFICIENT'); return; }
    const stamp = revision;
    const body = filingBody(); filingPreviewBody = null;
    byId('preview-filing').disabled = true;
    try {
      const response = await api('/api/filings/preview', {method:'POST', body:JSON.stringify(body)});
      const preview = await response.json(); if (stamp !== revision) return;
      filingPreviewBody = JSON.stringify(body); byId('source-text').value = preview.text;
      message('Text extracted. Review the context and label exact quotes. Origin and date remain caller asserted.', 'PARTIAL');
    } catch (error) { if (stamp === revision) message('Could not preview filing: ' + error.message, 'REJECTED'); }
    finally { byId('preview-filing').disabled = false; }
  });
  byId('source-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const evidence = [['support', 'support-quote'], ['challenge', 'challenge-quote']].filter(([, id]) => byId(id).value.trim()).map(([stance, id]) => {
      const selected = selectedExcerpts.get(id);
      const quote = byId(id).value;
      const offset = selected?.quote === quote && selected.text === byId('source-text').value ? {start:selected.start} : {};
      return {stance,quote,issuer_id:byId('evidence-issuer').value.trim(),...offset};
    });
    if (!evidence.length) { message('Supply at least one exact quote.', 'INSUFFICIENT'); return; }
    const stamp = revision;
    byId('register-source').disabled = true;
    try {
      const filing = byId('filing-mode').checked;
      const body = filing ? filingBody() : {text: byId('source-text').value, origin: byId('source-origin').value, permission: byId('source-permission').value};
      if (filing && JSON.stringify(body) !== filingPreviewBody) throw new Error('Preview this file and its current provenance before registering.');
      const response = await api(filing ? '/api/filings' : '/api/sources', { method: 'POST', body: JSON.stringify({...body, evidence}) });
      const source = await response.json();
      if (stamp !== revision) return;
      clearRun(); suppliedSource = source; mode.value = 'USER_SUPPLIED'; setMode();
      byId('watchlist').value = byId('evidence-issuer').value.trim();
      message('Source registered. Ask your question, then explore the evidence.', 'COMPLETE');
      document.dispatchEvent(new Event('research-source-registered'));
    } catch (error) { if (stamp === revision) message('Could not register source: ' + error.message, 'REJECTED'); }
    finally { byId('register-source').disabled = false; }
  });
  const message = (text, state = 'EMPTY') => {
    const allowed = ['EMPTY', 'LOADING', 'PARTIAL', 'STALE', 'REJECTED', 'INSUFFICIENT', 'COMPLETE', 'ERROR'];
    const explanations = {
      SOURCE_NOT_FOUND: 'Choose an available source or add your document first',
      SOURCE_AFTER_CUTOFF: 'The selected date is earlier than this source. Choose a later date',
      CITATION_SPAN_INVALID: 'Copy the quote exactly as it appears in your document',
      BASKET_ISSUER_CAP: 'Keep each company at 25% or less in an option',
      BASKET_BUDGET_EXCEEDED: 'Keep the total allocation at 60% or less',
      QUESTION_OR_WATCHLIST_INVALID: 'Enter a question and at least one company',
      NO_EVIDENCE_FOR_WATCHLIST: 'Choose a company covered by this document'
    };
    const codes = [...new Set(text.match(/\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g) || [])];
    feedback.textContent = codes.reduce((copy,code)=>copy.replaceAll(code,explanations[code] || 'Please review the source and your inputs'),text);
    if (codes.length) {
      const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Troubleshooting details';
      const diagnostic=document.createElement('small');diagnostic.textContent=codes.join(' · ');details.append(summary,diagnostic);feedback.append(details);
    }
    feedback.dataset.state = allowed.includes(state) ? state : 'ERROR';
    feedback.dataset.kind = state === 'ERROR' || state === 'REJECTED' || state === 'STALE' ? 'error' : state === 'COMPLETE' ? 'success' : 'info';
  };
  const api = async (url, options = {}) => {
    const response = await fetch(url, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(typeof body.detail === 'string' ? body.detail : body.detail ? 'Please check the input fields.' : `Request failed (HTTP ${response.status})`); }
    return response;
  };
  const renderRun = (data) => {
    for(const company of data.companies||[]){if(!companyNames[company.ticker])companyNames[company.ticker]=company.name;}
    window.CompanyDirectory?.register(data.companies);
    const supplied = data.mode === 'USER_SUPPLIED';
    const structured = data.mode === 'PUBLIC_READ';
    currentData = data; portfolioDirty = false;
    pendingConclusion = null;
    optionalFacts.hidden = !structured; optionalFacts.open = false; optionalPortfolio.open = false;
    optionalPortfolio.hidden = structured && data.watchlist.some(ticker=>!['NVDA','AMD','AVGO','MU','INTC','MSFT','AMZN','GOOGL'].includes(ticker));
    optionalInterpretations.open = !structured; optionalEvidence.open = !structured;
    if (data.research_scope) { byId('scope-metric').value = data.research_scope.metric || ''; byId('scope-operation').value = data.research_scope.operation; byId('scope-period').value = data.research_scope.period_request; }
    mode.value = data.mode; byId('source-import').hidden = !supplied;
    labelMode(supplied);
    byId('source-context').hidden = !supplied;
    byId('document-origin').textContent = data.source_document?.origin || '';
    byId('document-text').textContent = data.source_document?.text || '';
    const filing = data.source_document?.kind === 'LOCAL_FILING';
    byId('filing-provenance-panel').hidden = !filing;
    byId('filing-provenance').textContent = filing ? JSON.stringify(Object.fromEntries(Object.entries(data.source_document).filter(([key]) => !['raw_base64','text','segments','evidence'].includes(key))), null, 2) : '';
    byId('result-boundary').textContent = supplied ? 'Quotes match your document. Source accuracy and support/challenge labels are user asserted.' : 'Synthetic example only. These quotes do not establish real NVIDIA performance or a causal link between AI spending and growth.';
    byId('unknown').textContent = supplied ? data.unknowns.join(' ') : 'This synthetic source does not establish whether AI spending causes NVIDIA growth, how large any effect is, or whether growth will continue. Real source evidence is needed to answer the question.';
    byId('source-limits').hidden = !structured;
    byId('source-limits-copy').textContent = structured ? data.unknowns.join(' ') : '';
    if (filing) byId('result-boundary').textContent = 'Quotes match retained extracted text and raw hashes. Issuer/CIK and SEC URL consistency do not authenticate the document. Publication date is caller asserted. No historical PIT proof or publication permission. Labels require your review.';
    if (structured) {
      const savedAt=data.source_refs?.map(source=>source.available_at).sort().at(-1);
      const dateLabel=savedAt?new Date(savedAt).toLocaleDateString(undefined,{month:'long',day:'numeric',year:'numeric'}):'Date unavailable';
      byId('result-boundary').textContent = `Saved SEC figures · ${dateLabel}. Check the reporting period before comparing values. Original filings and independent review are not included.`;
      byId('unknown').textContent = 'The figures show reported financial results, but do not establish what caused the changes. Exact publication times and independent review are unavailable. Compare reporting periods carefully and review the original filings before drawing a conclusion.';
    }
    byId('structured-facts').hidden = !structured;
    byId('fact-list').replaceChildren(); byId('missing-facts').replaceChildren();
    for (const fact of data.facts || []) {
      const card = document.createElement('article'); card.className = 'citation';
      card.dataset.company = fact.issuer_id; card.dataset.metric = fact.metric;
      const title = document.createElement('h3'); title.textContent = `${companyNames[fact.issuer_id] || fact.issuer_id} · ${metricNames[fact.metric] || fact.metric.replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' ')}`;
      const value = document.createElement('p'); value.className = 'fact-value'; value.textContent = `${new Intl.NumberFormat('en-US', {notation:'compact',maximumFractionDigits:2}).format(Number(fact.value))} ${fact.unit}`;
      const dateLabel = value => new Intl.DateTimeFormat('en-US', {month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}).format(new Date(value));
      const period = document.createElement('small'); period.textContent = fact.start ? `${dateLabel(fact.start)} – ${dateLabel(fact.end)}` : `Period ending ${dateLabel(fact.end)}`;
      const details = document.createElement('details');
      const summary = document.createElement('summary'); summary.textContent = 'View source details';
      const readable = document.createElement('p'); readable.textContent = `Company: ${companyNames[fact.issuer_id] || fact.issuer_id}. SEC concept: ${metricNames[fact.metric] || fact.metric}. Filed ${fact.filed}. Accession ${fact.accession}. Exact value: ${fact.value} ${fact.unit}. Saved ${fact.available_at}.`;
      const link = document.createElement('a'); link.textContent = 'Open SEC structured source'; link.href = fact.origin; link.target = '_blank'; link.rel = 'noopener noreferrer';
      const verify = document.createElement('details'); const verifyLabel = document.createElement('summary'); verifyLabel.textContent = 'Verify details';
      const meta = document.createElement('pre'); meta.textContent = JSON.stringify(fact, null, 2);
      verify.append(verifyLabel,meta); details.append(summary,readable,link,verify); card.append(title, value, period, details); byId('fact-list').append(card);
    }
    for (const missing of data.missing_facts || []) { const card = document.createElement('article'); card.className = 'missing-observation'; card.dataset.company = missing.issuer_id; card.dataset.metric = missing.metric; const p = document.createElement('p'); p.textContent = `${companyNames[missing.issuer_id] || missing.issuer_id} · ${metricNames[missing.metric] || missing.metric}: not available in this source.`; const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = 'Availability details'; const reason = document.createElement('small'); reason.textContent = missing.reason; details.append(summary,reason); card.append(p,details); byId('missing-facts').append(card); }
    activeRun = data.run_id;
    history.replaceState(null, '', '#run=' + encodeURIComponent(activeRun));
    byId('result-question').textContent = data.question;
    byId('question').value = data.question;
    byId('source').value = data.source_id;
    byId('watchlist').value = data.watchlist.join(', ');
    byId('cutoff').value = new Date(data.cutoff).toISOString().slice(0, 23);
    byId('decision-note').value = data.user_conclusion?.note || data.decision?.note || '';
    byId('conclusion-verdict').value = data.user_conclusion?.verdict || '';
    byId('save-conclusion').disabled = !byId('conclusion-verdict').value;
    byId('legacy-choice').open = true;
    const evidenceChoices = byId('conclusion-evidence-list'); evidenceChoices.replaceChildren();
    const evidence = [...new Map([...(data.brief?.evidence_rows || []),...(data.facts || []), ...data.citations].map(item=>[item.fact_id || item.citation_id,item])).values()];
    for (const item of evidence) {
      const id = item.fact_id || item.citation_id; const label = document.createElement('label'); const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.value = id; checkbox.checked = (data.user_conclusion?.evidence_ids || []).includes(id);
      label.append(checkbox,document.createTextNode(item.quote ? item.quote : `${companyNames[item.issuer_id] || item.issuer_id} · ${metricNames[item.metric] || item.metric} · ${item.start} to ${item.end}`)); evidenceChoices.append(label);
    }
    renderBrief(data);
    for (const [target, narrativeId] of [['supports', 'growth-support'], ['challenges', 'margin-risk']]) {
      const container = byId(target); container.replaceChildren();
      // Only the declared example has a reviewed support/challenge mapping.
      const narrative = data.source_id === 'fixture-ai-capex-001' && data.narratives.find(item => item.narrative_id === narrativeId);
      const citation = narrative && data.citations.find(item => item.citation_id === narrative.citation_id);
      if (supplied) {
        const stance = target === 'supports' ? 'support' : 'challenge';
        const quotes = data.citations.filter(item => item.stance === stance);
        for (const item of quotes) { const quote = document.createElement('blockquote'); quote.textContent = '“' + item.quote + '”'; container.append(quote); }
        if (!quotes.length) container.textContent = 'No ' + stance + ' quote supplied. Absence is not confirmation.';
      } else if (citation) {
        const quote = document.createElement('blockquote'); quote.textContent = '“' + citation.quote + '”';
        const source = document.createElement('small'); source.textContent = 'Source: ' + data.source_id + ' · synthetic example';
        container.append(quote, source);
      } else {
        container.textContent = structured ? 'Structured figures provide financial context. Review the company financials and add a document for narrative evidence.' : 'No reviewed evidence mapping is available. Add a document to examine the question.';
      }
    }
    byId('run-id').textContent = data.run_id;
    byId('result-mode').textContent = data.mode;
    byId('result-source').textContent = `Source: ${data.source_id} · ${data.source_sha256.slice(0, 12)}…`;
    const citations = byId('citations'); citations.replaceChildren();
    if (!data.citations.length) { const empty = document.createElement('p'); empty.className = 'quote-empty'; empty.textContent = structured ? 'This source contains financial figures rather than document quotes. Open a figure’s source details to inspect the observation.' : 'No source quotes are available for this brief.'; citations.append(empty); }
    for (const item of data.citations) {
      const card = document.createElement('div'); card.className = 'citation';
      const quote = document.createElement('blockquote'); quote.textContent = `“${item.quote}”`;
      const meta = document.createElement('small'); meta.textContent = `SHA-256 ${item.source_sha256} · span ${item.start}–${item.end}`;
      const verification = document.createElement('details');
      const summary = document.createElement('summary'); summary.textContent = 'Verify this quote';
      verification.append(summary, meta);
      card.append(quote, verification); citations.append(card);
    }
    const counter = byId('counterevidence'); counter.replaceChildren();
    for (const status of data.counterevidence_status || []) { const p = document.createElement('p'); p.textContent = status === 'NOT_FOUND' ? 'No opposing evidence was found in this source. That does not confirm the claim.' : 'Related evidence is recorded in the source details.'; counter.append(p); }
    const list = byId('narratives'); list.replaceChildren();
    for (const [i, item] of data.narratives.entries()) {
      const card = document.createElement('article'); card.className = 'narrative';
      const title = document.createElement('h3'); title.textContent = item.title;
      const thesis = document.createElement('p'); thesis.textContent = item.thesis;
      const score = document.createElement('p'); score.className = 'score'; score.textContent = `Research priority ${Number(item.research_score).toFixed(2)} · ${item.classification}`;
      const basket = data.baskets.find(b => b.narrative_id === item.narrative_id); const allocation = basket ? Object.entries(basket.weights).map(([issuer, value]) => `${issuer} ${(Number(value)*100).toFixed(1)}%`).join(' · ') : '';
      const weight = document.createElement('p'); weight.className = 'weight'; weight.textContent = basket ? `Research-only basket · budget ${basket.budget_fraction * 100}% · ${allocation}` : '';
      const label = document.createElement('label'); const radio = document.createElement('input'); radio.type = 'radio'; radio.name = 'narrative-choice'; radio.value = item.narrative_id; radio.setAttribute('aria-label', `Choose ${item.title}`);
      const scoring = document.createElement('details');
      const scoringLabel = document.createElement('summary'); scoringLabel.textContent = 'Research scoring and example allocation';
      scoring.append(scoringLabel, score, weight);
      scoring.hidden = supplied || structured;
      radio.addEventListener('change', () => { selectedNarrative = radio.value; byId('choose').disabled = portfolioDirty; }); label.append(radio, document.createTextNode('Choose this interpretation')); card.append(title, thesis, label, scoring); list.append(card);
    }
    byId('results').hidden = false;
    const exportLink = byId('export'); exportLink.href = `/api/runs/${encodeURIComponent(activeRun)}/export`; exportLink.hidden = !(data.decision || data.user_conclusion);
    byId('export-md').href = `/api/runs/${encodeURIComponent(activeRun)}/export?format=md`; byId('export-md').hidden = !(data.decision || data.user_conclusion);
    byId('portfolio-panel').hidden = data.narratives.length !== 2;
    optionalPortfolio.hidden = byId('portfolio-panel').hidden || (structured && data.watchlist.some(ticker=>!['NVDA','AMD','AVGO','MU','INTC','MSFT','AMZN','GOOGL'].includes(ticker)));
    byId('portfolio-positions').value = (data.positions || []).map(p => `${p.issuer_id},${p.weight}`).join('\n');
    for (const [index, suffix] of ['a', 'b'].entries()) {
      const basket = data.baskets.find(b => b.narrative_id === data.narratives[index]?.narrative_id);
      byId('basket-' + suffix).value = Object.entries(basket?.weights || {}).filter(([issuer, value]) => issuer !== 'CASH' && Number(value)>0).map(([issuer,value]) => `${issuer},${value}`).join('\n');
      byId('rationale-' + suffix).value = basket?.rationale || '';
      byId('invalidation-' + suffix).value = basket?.invalidation_condition || '';
    }
    const comparison = byId('portfolio-comparison'); comparison.replaceChildren();
    if (data.portfolio_comparison) {
      for (const [name, scenario] of [['Current portfolio', data.portfolio_comparison.current], ...data.portfolio_comparison.scenarios.map(s => [s.narrative_id, s])]) {
        const article = document.createElement('article'); article.className = 'citation';
        const title = document.createElement('h3'); title.textContent = name === 'Current portfolio' ? name : data.narratives.find(item=>item.narrative_id === name)?.title || 'Portfolio option';
        const values = document.createElement('p'); values.textContent = Object.entries(scenario.issuer_weights).map(([issuer, value]) => `${issuer} ${(Number(value)*100).toFixed(2)}%`).join(' · ') + ` · Cash ${(Number(scenario.cash)*100).toFixed(2)}%`;
        const sectors = document.createElement('p'); sectors.textContent = 'Sector totals: ' + Object.entries(scenario.sector_weights).map(([sector,value]) => `${sector} ${(Number(value)*100).toFixed(2)}%`).join(' · ');
        const warnings = document.createElement('p'); warnings.textContent = scenario.warnings.length ? scenario.warnings.map(warning=>{const [kind,subject]=warning.split(':');return kind==='ISSUER_CAP' ? `${subject} is above the 25% company limit` : kind==='SECTOR_CAP' ? `${subject.replaceAll('_',' ')} is above the 60% sector limit` : 'Review the concentration of this portfolio';}).join(' · ') : 'Within the 25% company and 60% sector limits.';
        if (scenario.overlap_issuers?.length) warnings.textContent += ' · Companies in both options: ' + scenario.overlap_issuers.join(', ');
        article.append(title, values, sectors, warnings); comparison.append(article);
      }
    }
    byId('choose').disabled = !data.decision; selectedNarrative = data.decision?.narrative_id || null;
    if (selectedNarrative) { const radio = document.querySelector(`input[name="narrative-choice"][value="${CSS.escape(selectedNarrative)}"]`); if (radio) radio.checked = true; }
    document.dispatchEvent(new CustomEvent('research-rendered', {detail:data}));
  };
  const renderBrief = data => {
    const brief = data.brief; byId('answer-brief').hidden = !brief; if (!brief) return;
    const savedAt = data.source_refs?.map(source=>source.available_at).sort().at(-1) || data.source_document?.available_at;
    byId('answer-status').textContent = `${({answered:'Answered within scope',partial:'Partial answer',insufficient:'More evidence needed'})[brief.status]}${savedAt ? ' · Sources saved '+new Date(savedAt).toLocaleDateString() : ' · Synthetic example'}`;
    byId('answer-summary').textContent = brief.summary;
    let scopeLabel = byId('answer-scope'); if (!scopeLabel) { scopeLabel = document.createElement('p'); scopeLabel.id = 'answer-scope'; byId('answer-status').after(scopeLabel); }
    scopeLabel.textContent = `Selected scope: ${({revenue:'Revenue',net_income:'Net income',capex:'Capital spending'})[brief.scope.metric] || 'Choose one measure'} · ${({level:'Latest figures',change:'Year-over-year change',compare:'Compare companies'})[brief.scope.operation]} · ${({annual:'Annual reports',quarterly:'Quarterly reports',latest:'Latest supported reporting duration'})[brief.scope.period_request]}.`;
    byId('answer-method').textContent = brief.method;
    byId('answer-verification').textContent = JSON.stringify({analysis_cutoff:data.cutoff,scope:brief.scope,policy:brief.policy_version,comparisons:brief.comparisons,claims:brief.claims},null,2);
    const gaps = byId('answer-gaps'); gaps.replaceChildren(); for (const text of [...brief.gaps,...brief.next_steps]) { const li = document.createElement('li'); li.textContent = text; gaps.append(li); }
    const container = byId('answer-evidence'); container.replaceChildren();
    if (brief.evidence_rows.length) {
      const table = document.createElement('table'); const caption = document.createElement('caption'); caption.textContent = 'Figures used in this answer'; table.append(caption);
      const tr = document.createElement('tr'); for (const title of ['Company','Measure','Period','Value','Source']) { const th = document.createElement('th'); th.scope = 'col'; th.textContent = title; tr.append(th); } const head = document.createElement('thead'); head.append(tr); table.append(head); const body = document.createElement('tbody');
      for (const fact of brief.evidence_rows) {
        const row = document.createElement('tr'); for (const text of [companyNames[fact.issuer_id] || fact.issuer_id,metricNames[fact.metric] || fact.metric,`${fact.start} – ${fact.end}`,new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',notation:'compact',maximumFractionDigits:2}).format(Number(fact.value))]) { const td = document.createElement('td'); td.textContent = text; row.append(td); }
        const td = document.createElement('td'); const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = 'Inspect source'; const p = document.createElement('p'); p.textContent = `Exact value: ${fact.value} ${fact.unit}. Filed ${fact.filed}; accession ${fact.accession}; saved ${fact.available_at}. ${fact.origin}`; const verify = document.createElement('details'); const label = document.createElement('summary'); label.textContent = 'Verify details'; const pre = document.createElement('pre'); pre.textContent = JSON.stringify(fact,null,2); verify.append(label,pre); details.append(summary,p,verify); td.append(details); row.append(td); body.append(row);
      } table.append(body); container.append(table);
    }
    for (const item of brief.quote_evidence || []) { const quote = document.createElement('blockquote'); quote.textContent = item.quote; container.append(quote); }
  };
  const dirtyPortfolio = () => { revision++; portfolioDirty = true; selectedNarrative = null; document.querySelectorAll('input[name="narrative-choice"]').forEach(radio => { radio.checked = false; }); byId('choose').disabled = true; byId('export').hidden = true; byId('export-md').hidden = true; byId('portfolio-comparison').replaceChildren(); message('Portfolio inputs changed. Compare baskets to save a new research revision.', 'PARTIAL'); };
  for (const id of ['portfolio-positions', 'basket-a', 'basket-b', 'rationale-a', 'rationale-b', 'invalidation-a', 'invalidation-b']) byId(id).addEventListener('input', dirtyPortfolio);
  const parseRows = (text) => {
    const lines = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    if (lines[0]?.toLowerCase() === 'issuer_id,weight') lines.shift();
    return lines.map(line => { const cells = line.split(',').map(cell => cell.trim()); if (cells.length !== 2 || !/^[A-Z0-9._-]{1,32}$/.test(cells[0]) || !/^(?:0|1)(?:\.\d+)?$/.test(cells[1])) throw new Error('Use issuer_id,weight rows with nonnegative fractions (0.25 means 25%).'); return {issuer_id: cells[0], weight: cells[1]}; });
  };
  byId('portfolio-file').addEventListener('change', async () => {
    const file = byId('portfolio-file').files[0]; if (!file) return;
    const stamp = revision;
    try { if (file.size > 10000) throw new Error('Choose a positions CSV smaller than 10 KB.');
      const text = new TextDecoder('utf-8', {fatal:true}).decode(await file.arrayBuffer()); parseRows(text);
      if (stamp !== revision) return; byId('portfolio-positions').value = text; dirtyPortfolio(); document.dispatchEvent(new Event('research-rendered'));
    } catch (error) { message(error.message, 'REJECTED'); }
  });
  byId('compare-portfolio').addEventListener('click', async () => {
    if (!activeRun || !currentData) return;
    const stamp = revision; const run = activeRun;
    byId('compare-portfolio').disabled = true;
    try {
      const baskets = ['a','b'].map((suffix,index) => { const rows = parseRows(byId('basket-' + suffix).value); if (new Set(rows.map(row => row.issuer_id)).size !== rows.length) throw new Error('Each issuer may occur only once in a basket.'); return {narrative_id: currentData.narratives[index].narrative_id, weights: Object.fromEntries(rows.map(row => [row.issuer_id,row.weight])), rationale: byId('rationale-' + suffix).value, invalidation_condition: byId('invalidation-' + suffix).value}; });
      const response = await api(`/api/runs/${encodeURIComponent(run)}/portfolio`, {method:'POST', body:JSON.stringify({positions:parseRows(byId('portfolio-positions').value),baskets})});
      if (stamp !== revision) return; renderRun(await response.json()); message('Portfolio comparison saved as a new revision. Review the exposure, choose a lens and save your conclusion.', 'PARTIAL');
    } catch (error) { if (stamp === revision) message('Could not compare portfolio: ' + error.message, 'REJECTED'); }
    finally { byId('compare-portfolio').disabled = false; }
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault(); byId('results').hidden = true; message('Checking the source and evidence…', 'LOADING');
    if (!byId('watchlist').value.trim()) { message('Choose at least one company to begin.', 'INSUFFICIENT'); document.querySelector('.company-picker input')?.focus(); return; }
    const stamp = revision;
    let cutoff = new Date(`${byId('cutoff').value}Z`);
    if (Number.isNaN(cutoff.getTime())) { message('Enter a valid information cutoff to continue.', 'REJECTED'); byId('advanced').open = true; byId('cutoff').focus(); return; }
    try {
      startButton.disabled = true; startButton.setAttribute('aria-busy', 'true');
      startButton.firstChild.textContent = 'Exploring the evidence… ';
      if(mode.value==='PUBLIC_READ'&&dynamicCompanies&&byId('watchlist').value.split(',').map(x=>x.trim()).filter(Boolean).some(ticker=>!secSource?.issuers.includes(ticker))){
        message('Loading financial reports for your companies…','LOADING');
        const preparedResponse=await api('/api/companies/prepare',{method:'POST',body:JSON.stringify({tickers:byId('watchlist').value.split(',').map(x=>x.trim()).filter(Boolean)})});
        const prepared=await preparedResponse.json();if(stamp!==revision)return;
        byId('source').value=prepared.source_id;cutoff=new Date(Math.max(Date.now(),Date.parse(prepared.available_at))+1000);byId('cutoff').value=cutoff.toISOString().slice(0,23);
        window.CompanyDirectory?.register(prepared.companies);
      }
      const response = await api('/api/analyze', { method: 'POST', body: JSON.stringify({ source_id: byId('source').value.trim(), cutoff: cutoff.toISOString(), mode: mode.value, question: byId('question').value, watchlist: byId('watchlist').value.split(',').map((x) => x.trim()).filter(Boolean),metric:byId('scope-metric').value || null,operation:byId('scope-operation').value || null,period_request:byId('scope-period').value }) });
      const data = await response.json(); if (stamp !== revision) return;
      renderRun(data); message('Evidence ready. Review the gaps, then choose an interpretation.', data.status);
      document.dispatchEvent(new Event('research-analyzed'));
      document.getElementById('results-title').focus?.();
    } catch (error) {
      if (stamp !== revision) return;
      const state = error.message === 'SOURCE_AFTER_CUTOFF' ? 'STALE' : error.message === 'QUESTION_OR_WATCHLIST_INVALID' ? 'INSUFFICIENT' : error.message === 'SOURCE_NOT_FOUND' ? 'REJECTED' : 'ERROR';
      message(`Could not explore the evidence: ${error.message}. Review your selected source and try again.`, state); feedback.focus();
    } finally { startButton.disabled = false; startButton.removeAttribute('aria-busy'); startButton.firstChild.textContent = 'Explore the evidence '; }
  });
  byId('conclusion-verdict').addEventListener('change', () => { pendingConclusion = null; byId('save-conclusion').disabled = !activeRun || !byId('conclusion-verdict').value; });
  byId('save-conclusion').addEventListener('click', async () => {
    if (!activeRun) return;
    const payload = {version:2,verdict:byId('conclusion-verdict').value,note:byId('decision-note').value,evidence_ids:[...byId('conclusion-evidence-list').querySelectorAll('input:checked')].map(input=>input.value)};
    const signature = JSON.stringify(payload); if (!pendingConclusion || pendingConclusion.signature !== signature) pendingConclusion = {signature,id:crypto.randomUUID()};
    const stamp = revision; const run = activeRun; byId('save-conclusion').disabled = true;
    try { await api(`/api/runs/${encodeURIComponent(run)}/conclusion`,{method:'POST',body:JSON.stringify({...payload,decision_id:pendingConclusion.id})}); const response = await api(`/api/runs/${encodeURIComponent(run)}`); const data = await response.json(); if (stamp !== revision) return; renderRun(data); message('Conclusion saved. Revisions preserve your earlier reasoning.','COMPLETE'); byId('export').focus(); }
    catch(error) { if (stamp === revision) { message('Could not save conclusion: '+error.message+'. Choose evidence, or add a note for insufficient evidence.','ERROR'); feedback.focus(); } }
    finally { if (stamp === revision) byId('save-conclusion').disabled = !byId('conclusion-verdict').value; }
  });
  byId('choose').addEventListener('click', async () => {
    if (!activeRun || !selectedNarrative || portfolioDirty) return;
    const stamp = revision; const run = activeRun;
    try { await api(`/api/runs/${encodeURIComponent(run)}/decision`, { method: 'POST', body: JSON.stringify({ narrative_id: selectedNarrative, note: byId('decision-note').value }) });
      const response = await api(`/api/runs/${encodeURIComponent(run)}`); const data = await response.json(); if (stamp !== revision) return; renderRun(data);
      message('Choice saved. You can export the brief or reload this research.', data.status); byId('export').focus();
    } catch (error) { message(`Could not save your choice: ${error.message}. Reload the research and try again.`, 'ERROR'); }
  });
  byId('reload').addEventListener('click', async () => {
    if (!activeRun) return;
    const stamp = revision;
    try { const response = await api(`/api/runs/${encodeURIComponent(activeRun)}`); const data = await response.json(); if (stamp !== revision) return; renderRun(data); message('Research reloaded. The retained evidence status is unchanged.', data.status); }
    catch (error) { message(`Could not reload the research: ${error.message}`, 'ERROR'); }
  });
  form.addEventListener('invalid', () => { byId('advanced').open = true; }, true);
  const startButton = form.querySelector('button[type="submit"]');
  startButton.disabled = true;
  const initialRevision = revision;
  api('/api/capabilities').then(response => response.json()).then(data => {
    secSource = data.retained_sec;
    dynamicCompanies = !!data.company_directory;
    if(dynamicCompanies)window.CompanyDirectory?.enable();
    mode.querySelector('option[value="PUBLIC_READ"]').disabled = !secSource&&!dynamicCompanies;
    if (!location.hash.startsWith('#run=') && revision === initialRevision && (secSource||dynamicCompanies)) {
      mode.value = 'PUBLIC_READ'; setMode();
      message('Company reports are ready. Enter your question to begin.');
    }
  }).catch(() => { message('Company reports are unavailable. You can use the sample or add a document.'); })
    .finally(() => { startButton.disabled = false; document.dispatchEvent(new Event('desk-ready')); });
  const savedRun = location.hash.startsWith('#run=') ? location.hash.slice(5) : '';
  if (savedRun) {
    const savedRevision = revision;
    message('Loading saved research…', 'LOADING');
    api('/api/runs/' + savedRun).then(response => response.json()).then(data => {
      if (savedRevision !== revision || location.hash !== '#run='+savedRun) return;
      renderRun(data); message('Research reloaded with your saved choice.', data.status);
    }).catch(error => { if (savedRevision === revision && location.hash === '#run='+savedRun)
      message('Could not reopen this research: ' + error.message + '. Explore the example to start again.', 'ERROR'); });
  }
  labelMode(false);
})();
