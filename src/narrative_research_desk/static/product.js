/* Friendly allocation inputs; the existing serialized fields remain the API boundary. */
(() => {
  const companies = ['NVDA','AMD','AVGO','MU','INTC','MSFT','AMZN','GOOGL'];
  const companyNames = {NVDA:'NVIDIA',AMD:'Advanced Micro Devices',AVGO:'Broadcom',MU:'Micron Technology',INTC:'Intel',MSFT:'Microsoft',AMZN:'Amazon',GOOGL:'Alphabet (Google)'};
  const editors = [];
  for (const [id, title] of [['portfolio-positions','Your current holdings'],['basket-a','Portfolio option A'],['basket-b','Portfolio option B']]) {
    const field = document.getElementById(id);
    const label = document.querySelector(`label[for="${id}"]`);
    const editor = document.createElement('div'); editor.className = 'allocation-editor';
    const heading = document.createElement('h3'); heading.textContent = title;
    const help = document.createElement('small'); help.textContent = 'Choose a company and enter its share of your portfolio in percent.';
    const rows = document.createElement('div'); rows.className = 'allocation-rows';
    const add = document.createElement('button'); add.type = 'button'; add.className = 'secondary allocation-add'; add.textContent = '+ Add company';
    const advanced = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = 'Paste or edit allocation data';
    field.before(editor); editor.append(heading,help,rows,add,advanced); advanced.append(summary,label,field);
    const sync = () => {
      field.value = [...rows.children].map(row => `${row.querySelector('select').value},${Number(row.querySelector('input').value)/100}`).join('\n');
      field.dispatchEvent(new Event('input', {bubbles:true}));
    };
    const append = (symbol = companies[0], weight = '') => {
      const row = document.createElement('div'); row.className = 'allocation-row';
      const select = document.createElement('select'); select.setAttribute('aria-label', `${title}: company`);
      const options = companies.includes(symbol) ? companies : [...companies,symbol];
      options.forEach(value => {const option = document.createElement('option'); option.value=value; option.textContent=companyNames[value] ? `${companyNames[value]} (${value})` : value; select.append(option);}); select.value=symbol;
      const wrapper = document.createElement('div'); wrapper.className = 'percent-field';
      const input = document.createElement('input'); input.type='number';input.min='0';input.max='100';input.step='0.1';input.value=weight;input.placeholder='0';input.setAttribute('aria-label', `${title}: allocation percent`);
      const percent = document.createElement('span');percent.textContent='%';percent.setAttribute('aria-hidden','true');wrapper.append(input,percent);
      const remove = document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',`Remove company from ${title}`);remove.addEventListener('click',()=>{row.remove();sync();add.focus();});
      select.addEventListener('change',sync);input.addEventListener('input',sync);row.append(select,wrapper,remove);rows.append(row);
    };
    const refresh = () => {
      rows.replaceChildren();
      for (const line of field.value.trim().split(/\r?\n/).filter(Boolean)) {
        const [symbol,weight] = line.split(',').map(s=>s.trim());
        if (symbol === 'issuer_id') continue;
        if (symbol && Number.isFinite(Number(weight))) append(symbol, String(Math.round(Number(weight)*1000000)/10000));
      }
    };
    add.addEventListener('click',()=>{append();rows.lastElementChild.querySelector('input').focus();});
    field.addEventListener('change',refresh);editors.push(refresh);refresh();
  }
  document.addEventListener('research-rendered',()=>{
    editors.forEach(refresh=>refresh());
    const step = document.getElementById('export').hidden ? 1 : 2;
    document.querySelectorAll('.journey>span').forEach((item,index)=>{
      if(index===step)item.setAttribute('aria-current','step');else item.removeAttribute('aria-current');
    });
  });
  document.getElementById('source-kind').addEventListener('change',()=>{
    document.querySelectorAll('.journey>span').forEach((item,index)=>{
      if(index===0)item.setAttribute('aria-current','step');else item.removeAttribute('aria-current');
    });
  });
})();
