/* Optional explanation of a retained snapshot; rendering uses text only. */
(() => {
  const results = document.getElementById('results');
  const panel = document.createElement('section');
  panel.className = 'panel';
  panel.setAttribute('aria-label', 'Optional brief explanation');
  const heading = document.createElement('h2'); heading.textContent = 'Understand this brief';
  const privacy = document.createElement('p');
  privacy.textContent = 'Selected evidence is sent to the configured ChatGPT gateway when you ask for an explanation.';
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'secondary';
  button.textContent = 'Explain this brief'; button.disabled = true;
  const output = document.createElement('div');
  output.id = 'explanation-output'; output.setAttribute('role', 'status');
  output.setAttribute('aria-live', 'polite');
  panel.append(heading, privacy, button, output);
  document.getElementById('answer-brief').after(panel);
  let run = null, generation = 0;
  const reset = id => {
    generation++; run = id || null; output.replaceChildren();
    button.disabled = !run; button.removeAttribute('aria-busy');
  };
  document.addEventListener('research-rendered', event => {
    if (event.detail?.run_id) reset(event.detail.run_id);
  });
  document.addEventListener('research-new', event => {
    queueMicrotask(() => { if (!event.defaultPrevented) reset(null); });
  });
  document.addEventListener('research-explanation-invalidated', () => reset(null));
  // A hidden result during analysis/navigation invalidates any pending request.
  new MutationObserver(() => {
    if (results.hidden) reset(null);
    else if (results.classList.contains('view-inactive')) reset(run);
  }).observe(results, {attributes:true, attributeFilter:['hidden','class']});
  const paragraph = text => {
    const element = document.createElement('p'); element.textContent = text; output.append(element);
  };
  const metricNames = {Revenues:'Revenue', RevenueFromContractWithCustomerExcludingAssessedTax:'Revenue',
    RevenueFromContractWithCustomerIncludingAssessedTax:'Revenue', NetIncomeLoss:'Net income',
    PaymentsToAcquirePropertyPlantAndEquipment:'Capital expenditure'};
  const showEvidence = row => {
    if (typeof row.quote === 'string') {
      paragraph([row.issuer_id, row.stance === 'support' ? 'Supporting quote (annotation)' :
        row.stance === 'challenge' ? 'Challenging quote (annotation)' : 'Document quote'].filter(Boolean).join(' · '));
      paragraph(row.quote);
    } else if (row.value !== undefined) {
      const metric = metricNames[row.metric] || 'Reported observation';
      const amount = [String(row.value), row.unit].filter(Boolean).join(' ');
      const period = row.start && row.end ? row.start+' to '+row.end : row.end;
      paragraph([metric+': '+amount, row.issuer_id, period].filter(Boolean).join(' · '));
    } else if (Array.isArray(row.gaps)) {
      for (const gap of row.gaps) paragraph(gap);
    }
    const details = document.createElement('details');
    const summary = document.createElement('summary'); summary.textContent = 'Source details';
    const raw = document.createElement('pre'); raw.textContent = JSON.stringify(row, null, 2);
    details.append(summary, raw); output.append(details);
  };
  button.addEventListener('click', async () => {
    if (!run || results.hidden || results.classList.contains('view-inactive') || button.disabled) return;
    const selected = run, stamp = generation;
    button.disabled = true; button.setAttribute('aria-busy', 'true');
    output.textContent = 'Preparing an optional explanation…';
    try {
      const response = await fetch('/api/runs/'+encodeURIComponent(selected)+'/explanation', {method:'POST'});
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (stamp !== generation || selected !== run || results.hidden || results.classList.contains('view-inactive')) return;
      if (data.run_id !== selected || !Array.isArray(data.items)) throw new Error();
      output.replaceChildren();
      paragraph('AI chose which evidence to highlight. The explanation uses your saved brief.');
      if (data.provider) paragraph('AI-selected priorities · '+
        [data.provider.name, data.provider.model].filter(Boolean).join(' · '));
      if (data.mode) paragraph('Evidence mode: '+data.mode);
      for (const item of data.items) {
        paragraph(item.text);
        showEvidence(item.evidence);
      }
      if (data.follow_up) paragraph(data.follow_up.label+': '+data.follow_up.question);
    } catch {
      if (stamp === generation && selected === run && !results.hidden)
        output.textContent = 'Explanation unavailable. Your research brief is still available.';
    } finally {
      if (stamp === generation && selected === run) {
        button.disabled = false; button.removeAttribute('aria-busy');
      }
    }
  });
})();
