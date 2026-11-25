'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const state = {view:'dashboard', currency:'USD', month:'', config:null, dashboard:null, transactions:[], review:null, charts:[], request:0, search:'', category:'', page:1, focusTransactionId:null, importMessage:''};
const palette = ['#9b88dd','#a8c9a4','#efc98e','#a9bde1','#d5b4cf','#8ebdb4','#dbac91','#bdc794','#b8b0dc','#b9c3c6'];
const categoryIcon = name => ({'Food & drinks':'food','Groceries':'bag','Transport':'car','Shopping':'bag','Bills & utilities':'bolt','Entertainment':'spark','Health':'plus','Education':'receipt','Travel':'car','Income':'wallet'}[name] || 'receipt');
const money = (value, currency = state.currency) => new Intl.NumberFormat('en-US', {style:'currency',currency,currencyDisplay:currency === 'KHR' ? 'narrowSymbol' : 'symbol',minimumFractionDigits:currency === 'KHR' ? 0 : 2,maximumFractionDigits:currency === 'KHR' ? 0 : 2}).format(Number(value || 0));
const percent = (a,b) => Number(b) ? Math.round(Number(a)/Number(b)*100) : 0;
const dateLabel = value => value ? new Date(value + 'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric'}) : 'No deadline';
const monthLabel = () => new Date(state.month + '-01T12:00:00').toLocaleDateString('en-US',{month:'long',year:'numeric'});
const categoryOptions = (value, income = true) => state.config.categories.filter(c => income || c !== 'Income').map(c => `<option${c === value ? ' selected' : ''}>${escapeHTML(c)}</option>`).join('');
const currencyOptions = value => ['USD','KHR'].map(c => `<option${c === value ? ' selected' : ''}>${c}</option>`).join('');

async function api(path, options = {}) {
  const headers = {...options.headers};
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch('/api' + path, {...options, headers});
  if (!response.ok) {
    let message = 'Could not complete the request. Please try again.';
    try {
      const error = await response.json();
      message = Array.isArray(error.detail) ? error.detail.map(e => `${e.loc.slice(1).join(' · ')}: ${e.msg}`).join('; ') : error.detail || message;
    } catch { /* Keep the useful fallback message. */ }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

let toastTimer;
function toast(message) {
  clearTimeout(toastTimer);
  $('#toast').textContent = message;
  $('#toast').hidden = false;
  toastTimer = setTimeout(() => $('#toast').hidden = true, 4500);
}

const headings = {
  dashboard:['A LITTLE CLARITY, EVERY DAY','Your money, in perspective','Keep track of today. Make room for tomorrow.','Overview'],
  transactions:['EVERY LITTLE DETAIL','A place for every transaction','Your spending story, one transaction at a time.','Transactions'],
  expected:['A PLAN BEFORE THE PAYMENT','Make room for upcoming expenses','Expect an expense. Allocate funds when you’re ready. Record spending when you pay.','Expected expenses'],
  accounts:['YOUR MONEY, ACCOUNT BY ACCOUNT','A clear home for every balance','Track actual balances and reserves separately for each account and currency.','Accounts'],
  budgets:['SPEND WITH INTENTION','A little planning goes a long way','Give each category a limit. Keep your priorities in focus.','Budgets'],
  goals:['MAKE ROOM FOR TOMORROW','Good things are worth saving for','Turn your someday plans into a little progress today.','Savings goals'],
  receipts:['LESS TYPING, MORE LIVING','From paper to perspective','Scan a receipt in Khmer or English. Review it. Make it count.','Receipt scanner'],
  import:['BRING IT ALL TOGETHER','Your transactions, organized','Import your CSV, check the details, and take it from there.','Import CSV'],
  settings:['MAKE YOURSELF AT HOME','Your workspace, your way','A few details about your SmartSpend workspace.','Settings'],
};

async function render() {
  if (!state.config) return;
  const request = ++state.request;
  syncRoute();
  const [eyebrow,title,subtitle,label] = headings[state.view];
  $('#page-eyebrow').textContent = eyebrow;
  $('#page-title').innerHTML = escapeHTML(title) + '<span>.</span>';
  $('#page-subtitle').textContent = subtitle;
  $('#breadcrumb-view').textContent = label;
  $('#month-display').textContent = monthLabel();
  $('#month-picker').value = state.month;
  $$('[data-currency]').forEach(button => {
    const selected = button.dataset.currency === state.currency;
    button.classList.toggle('selected',selected);
    button.setAttribute('aria-pressed',String(selected));
  });
  document.title = `${label} · SmartSpend AI`;
  $$('.nav-link').forEach(link => { const active = link.dataset.view === state.view; link.classList.toggle('active',active); if (active) link.setAttribute('aria-current','page'); else link.removeAttribute('aria-current'); });
  const hasPeriod = ['dashboard','transactions','budgets'].includes(state.view);
  $('.period-control').hidden = !hasPeriod;
  $('#export-button').hidden = !hasPeriod;
  $('.currency-switch').hidden = ['receipts','import','settings'].includes(state.view);
  $('.toolbar').hidden = ['receipts','import','settings'].includes(state.view);
  $('#app-error').hidden = true;
  state.charts.forEach(chart => chart.destroy());
  state.charts = [];
  $('#view-content').innerHTML = '<div class="loading-state"><span class="loader"></span>Loading your workspace…</div>';
  try {
    let html;
    if (state.view === 'dashboard' || state.view === 'budgets') {
      const data = await api(`/dashboard?month=${state.month}&currency=${state.currency}`);
      if (request !== state.request) return;
      state.dashboard = data;
      html = state.view === 'dashboard' ? dashboardHTML(data) : budgetsHTML(data);
    } else if (state.view === 'transactions') {
      const data = await api(`/transactions?month=${state.month}&currency=${state.currency}`);
      if (request !== state.request) return;
      state.transactions = data;
      const focusedIndex = filteredTransactions().findIndex(t=>t.id===state.focusTransactionId);
      if (focusedIndex >= 0) state.page = Math.floor(focusedIndex / 15) + 1;
      html = transactionsHTML();
    } else if (state.view === 'goals') {
      const data = await api(`/goals?currency=${state.currency}`);
      if (request !== state.request) return;
      state.goals = data;
      html = goalsHTML(data);
    } else if (state.view === 'expected') {
      html = await ExpectedExpenses.pageHTML();
    } else if (state.view === 'accounts') {
      html = await ExpectedExpenses.accountsHTML();
    } else if (state.view === 'receipts' || state.view === 'import') html = uploadHTML();
    else html = settingsHTML();
    if (request !== state.request) return;
    $('#view-content').innerHTML = html;
    if (state.view === 'dashboard') drawCharts(state.dashboard);
    if (state.view === 'expected') ExpectedExpenses.bindPage();
    if (state.view === 'transactions') {
      bindTransactionFilters();
      const focused = $(`#transaction-${state.focusTransactionId}`);
      if (focused) { focused.scrollIntoView({block:'center'}); focused.focus({preventScroll:true}); }
    }
    if (state.view === 'receipts' || state.view === 'import') bindUpload();
  } catch (error) {
    if (request !== state.request) return;
    $('#app-error').textContent = error.message;
    $('#app-error').hidden = false;
    $('#view-content').innerHTML = `<div class="empty-state">${icon('wallet')}<h3>We couldn’t load your workspace</h3><p>Check the server connection, then try again.</p><button class="button primary" data-action="retry">Try again</button></div>`;
  }
}

function dashboardHTML(d) {
  const change = Number(d.previous_spending) ? Math.round((Number(d.spending)/Number(d.previous_spending)-1)*100) : null;
  const remaining = Number(d.budget) - Number(d.budget_spent);
  const stats = [
    ['Monthly income',d.income,'wallet','<span class="positive">This month</span><span>All income recorded</span>',false],
    ['Total expenses',d.spending,'transactions',change === null ? '<span>No previous month to compare</span>' : `<span class="${change <= 0 ? 'positive' : 'negative'}">${change > 0 ? '+' : ''}${change}%</span><span>vs full previous month</span>`,false],
    ['Monthly net income',d.net,'trend','<span>Monthly income minus actual expenses</span>',false],
    ['Budget remaining',remaining,'budget',`<span>${Number(d.budget) ? `${percent(d.budget_spent,d.budget)}% of category budgets used` : 'Set your first category budget'}</span>`,false],
  ];
  const top = [...d.categories].sort((a,b)=>Number(b.amount)-Number(a.amount));
  const topCategory = top[0];
  const goal = d.goals[0];
  return `${ExpectedExpenses.balanceHTML(d.finance)}<section class="stats-grid" aria-label="Monthly summary">${stats.map(([label,value,i,foot,featured])=>`<article class="stat-card${featured?' featured':''}"><div class="stat-top"><span class="stat-label">${label}</span><span class="stat-icon">${icon(i)}</span></div><div class="stat-value">${money(value)}</div><div class="stat-foot">${foot}</div></article>`).join('')}</section>
    <section class="charts-grid" aria-label="Spending charts"><article class="panel"><div class="panel-header"><div><h2 class="panel-title">Spending overview</h2><p class="panel-subtitle">A day-by-day look at where your money goes</p></div><span class="pill">Daily spending</span></div><div class="chart-meta"><div class="chart-total">${money(d.spending)}<span>spent this month</span></div><div class="chart-legend"><span class="legend-key"><i class="legend-dot"></i>This month</span><span class="legend-key"><i class="legend-dot gray"></i>Last month</span></div></div><div class="line-chart"><canvas id="spending-chart" role="img" aria-label="Daily spending in ${state.currency} for the selected month compared with the previous month"></canvas></div></article>
    <article class="panel"><div class="panel-header"><div><h2 class="panel-title">Where it all goes</h2><p class="panel-subtitle">Your spending, by category</p></div>${icon('bag')}</div><div class="donut-wrapper"><canvas id="category-chart" role="img" aria-label="Expense category breakdown; values listed below"></canvas><div class="donut-center"><span>TOTAL SPENT</span><strong>${money(d.spending)}</strong></div></div><div class="category-legend">${top.length ? top.map((c,i)=>`<div><i style="background:${palette[i % palette.length]}"></i><span class="category-name">${escapeHTML(c.name)}</span><strong title="${money(c.amount)}">${percent(c.amount,d.spending)}%</strong></div>`).join('') : '<div>No expenses yet</div>'}</div></article></section>
    ${ExpectedExpenses.upcomingHTML(d.finance)}<section class="middle-grid"><article class="panel"><div class="panel-header"><div><h2 class="panel-title">Recent transactions</h2><p class="panel-subtitle">The little things, all in one place</p></div><button class="text-link" data-navigate="transactions">View all</button></div><div class="table-wrap recent-table">${transactionTable(d.recent,false)}</div></article>
    <article class="panel"><div class="panel-header"><div><h2 class="panel-title">Monthly budgets</h2><p class="panel-subtitle">A plan that keeps you on track</p></div><button class="text-link" data-navigate="budgets">Manage</button></div><div class="budget-list">${d.budgets.length ? d.budgets.slice(0,4).map((b,i)=>budgetRow(b,i)).join('') : `<div class="empty-state"><h3>Make a little plan</h3><p>Set a category budget to see your progress here.</p><button class="text-link" data-action="add-budget">Create a budget</button></div>`}</div><div class="budget-footer">${icon('check')}${d.budgets.length ? (d.budgets.every(b=>Number(b.spent)<=Number(b.amount)) ? 'Looking good. Your category budgets are on track.' : 'A category needs a little attention. You’ve got this.') : 'Your next month can start with a plan.'}</div></article></section>
    <aside class="insight-strip"><span class="insight-icon">${icon('spark')}</span><div><h3>A little spending perspective</h3><p>${topCategory ? `${escapeHTML(topCategory.name)} makes up ${percent(topCategory.amount,d.spending)}% of this month’s spending. Small, intentional choices can make space for your next goal.` : 'Start by adding a transaction. Your spending patterns will come into focus as you go.'}</p></div><span class="insight-tag">MONTHLY INSIGHT</span></aside>
    <section class="bottom-grid"><article class="panel">${goal ? `<div class="goal-preview"><span class="goal-art">${icon('goal')}</span><div class="goal-preview-content"><h3>${escapeHTML(goal.name)}</h3><div class="progress"><span style="width:${Math.min(100,percent(goal.saved,goal.target))}%;background:#a5bf8b"></span></div><p>${money(goal.saved)} of ${money(goal.target)} saved</p></div><button class="text-link" data-navigate="goals">${percent(goal.saved,goal.target)}%</button></div>` : `<div class="quick-add-panel"><span class="goal-art">${icon('goal')}</span><div><h3 class="panel-title">A goal to look forward to</h3><p>Every little contribution brings it closer.</p></div><button class="text-link" data-navigate="goals">Set a goal</button></div>`}</article><article class="panel quick-add-panel"><span class="insight-icon">${icon('scan')}</span><div><h3 class="panel-title">A receipt? Let us read it.</h3><p>Khmer or English. Less typing, more living.</p></div><button class="button secondary compact" data-navigate="receipts">Scan receipt</button></article></section>`;
}

function budgetRow(b,i) {
  const used = percent(b.spent,b.amount);
  return `<div class="budget-row"><div class="budget-labels"><span class="budget-category">${icon(categoryIcon(b.category))}${escapeHTML(b.category)}</span><span class="budget-amount"><strong>${money(b.spent)}</strong> / ${money(b.amount)}</span></div><div class="progress" role="progressbar" aria-label="${escapeHTML(b.category)} budget used" aria-valuenow="${Math.min(100,used)}" aria-valuemin="0" aria-valuemax="100"><span style="width:${Math.min(100,used)}%;background:${used>100?'#d2957b':palette[i%palette.length]}"></span></div></div>`;
}

function drawCharts(d) {
  if (!window.Chart) {
    $('#spending-chart').parentElement.innerHTML = '<div class="chart-unavailable">Chart library unavailable. Monthly totals are shown above.</div>';
    return;
  }
  Chart.defaults.font.family = 'DM Sans, Noto Sans Khmer, sans-serif';
  Chart.defaults.color = '#a0aaa3';
  Chart.defaults.font.size = 9;
  const ctx = $('#spending-chart').getContext('2d');
  const gradient = ctx.createLinearGradient(0,0,0,230);
  gradient.addColorStop(0,'#a493e24d'); gradient.addColorStop(1,'#a493e202');
  state.charts.push(new Chart(ctx,{type:'line',data:{labels:d.daily.map(item=>item.day),datasets:[{label:`${monthLabel()} (${state.currency})`,data:d.daily.map(item=>Number(item.amount)),borderColor:'#9a86dc',backgroundColor:gradient,fill:true,tension:.36,borderWidth:2,pointRadius:0,pointHoverRadius:4},{label:`Previous month (${state.currency})`,data:d.previous_daily.map(item=>Number(item.amount)),borderColor:'#dbe2dd',borderWidth:1.5,borderDash:[4,4],pointRadius:0,tension:.36}]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{display:false},tooltip:{backgroundColor:'#23483b',padding:10,displayColors:false,callbacks:{label:context=>`${context.datasetIndex ? 'Last month' : 'This month'}: ${money(context.raw)}`}}},scales:{x:{grid:{display:false},border:{display:false},ticks:{maxTicksLimit:8,maxRotation:0,callback:function(value){return String(this.getLabelForValue(value)).padStart(2,'0');}}},y:{beginAtZero:true,border:{display:false,dash:[3,4]},grid:{color:'#f0f2f0',drawTicks:false},ticks:{padding:12,maxTicksLimit:5,callback:value=>money(value).replace('.00','')}}}}}));
  const sorted = [...d.categories].sort((a,b)=>Number(b.amount)-Number(a.amount));
  state.charts.push(new Chart($('#category-chart'),{type:'doughnut',data:{labels:sorted.length?sorted.map(c=>c.name):['No expenses'],datasets:[{data:sorted.length?sorted.map(c=>Number(c.amount)):[1],backgroundColor:sorted.length?palette:['#edf0eb'],borderWidth:4,borderColor:'#fff',borderRadius:5,hoverOffset:3}]},options:{responsive:true,maintainAspectRatio:false,cutout:'77%',layout:{padding:6},plugins:{legend:{display:false},tooltip:{enabled:!!sorted.length,backgroundColor:'#23483b',callbacks:{label:context=>`${context.label}: ${money(context.raw)}`}}}}}));
}

function transactionTable(records, actions = true) {
  if (!records.length) return `<div class="empty-state">${icon('transactions')}<h3>A fresh start</h3><p>No transactions match this view. Add a transaction or choose another month.</p><button class="button secondary" data-action="add-transaction">Add transaction</button></div>`;
  return `<table><thead><tr><th>TRANSACTION</th><th>DATE</th><th>CATEGORY</th><th class="amount-cell">AMOUNT</th>${actions?'<th aria-label="Actions"></th>':''}</tr></thead><tbody>${records.map(t=>`<tr id="transaction-${t.id}"${actions && t.id===state.focusTransactionId ? ' class="transaction-focused" tabindex="-1"' : ''}><td><div class="merchant"><span class="merchant-icon"${t.kind==='income'?' style="background:#eaf3e8;color:#6c9560"':''}>${icon(categoryIcon(t.category))}</span><div><span class="merchant-name" title="${escapeHTML(t.merchant||t.description)}">${escapeHTML(t.merchant||t.description)}</span><span class="merchant-note">${actions ? escapeHTML(t.source === 'demo'?'Sample transaction':t.source === 'manual'?'Manually added':t.source === 'csv'?'CSV import':'Receipt scan') : dateLabel(t.date)}</span>${savedItemsHTML(t)}</div></div></td><td style="color:#939e94">${dateLabel(t.date)}</td><td><span class="category-chip">${escapeHTML(t.category)}</span></td><td class="amount-cell${t.kind==='income'?' income-amount':''}">${t.kind==='income'?'+':'−'}${money(t.amount,t.currency)}</td>${actions?`<td><div class="transaction-actions"><button class="icon-button" data-action="edit-transaction" data-id="${t.id}" aria-label="Edit ${escapeHTML(t.merchant||t.description)}">${icon('edit')}</button><button class="icon-button" data-action="delete-transaction" data-id="${t.id}" aria-label="Delete ${escapeHTML(t.merchant||t.description)}">${icon('trash')}</button></div></td>`:''}</tr>`).join('')}</tbody></table>`;
}

function savedItemsHTML(t) {
  if(!t.items?.length)return '';
  return `<details class="saved-items"><summary>${t.items.length} purchased item${t.items.length===1?'':'s'}</summary><ul>${t.items.map(item=>`<li><span>${escapeHTML(item.name)}</span><strong>${money(item.price,t.currency)}</strong></li>`).join('')}</ul></details>`;
}

function filteredTransactions() {
  const needle = state.search.toLocaleLowerCase();
  return state.transactions.filter(t=>(!state.category || t.category===state.category) && (!state.transactionAccountId || String(t.account_id)===state.transactionAccountId) && (!needle || [t.merchant,t.description,t.note,...(t.items||[]).map(item=>item.name)].join(' ').toLocaleLowerCase().includes(needle)));
}

function transactionResultsHTML() {
  const filtered = filteredTransactions();
  const pages = Math.max(1,Math.ceil(filtered.length/15));
  state.page = Math.min(state.page,pages);
  return `<div class="table-wrap">${transactionTable(filtered.slice((state.page-1)*15,state.page*15))}</div>${filtered.length>15?`<div class="review-actions"><span>Page ${state.page} of ${pages} · ${filtered.length} transactions</span><div><button class="button secondary compact" data-action="previous-page"${state.page===1?' disabled':''}>Previous</button> <button class="button secondary compact" data-action="next-page"${state.page===pages?' disabled':''}>Next</button></div></div>`:''}`;
}

function transactionsHTML() {
  const focused = state.transactions.find(t=>t.id===state.focusTransactionId);
  const context = focused ? `${state.importMessage || 'Showing the selected transaction.'} ${monthLabel()} · ${state.currency}.${focused.source==='receipt' ? ' Check the receipt date and edit it if needed.' : ''}` : '';
  return `${context ? `<div class="notice" id="import-result" role="status">${escapeHTML(context)}</div>` : ''}<section class="panel" style="margin-bottom:24px"><div class="transactions-filters"><div class="search-box">${icon('search')}<input type="search" id="transaction-search" aria-label="Search transactions" placeholder="Find a transaction…" value="${escapeHTML(state.search)}"></div><select id="category-filter" aria-label="Filter by category"><option value="">All categories</option>${categoryOptions(state.category)}</select><select id="transaction-account-filter" aria-label="Filter by account">${ExpectedExpenses.accountOptions(state.currency,state.transactionAccountId,true)}</select><span class="filter-count" id="transaction-count">${filteredTransactions().length} transactions</span></div><div id="transaction-results">${transactionResultsHTML()}</div></section>`;
}

function bindTransactionFilters() {
  const update = () => { state.page=1; $('#transaction-results').innerHTML=transactionResultsHTML(); $('#transaction-count').textContent=`${filteredTransactions().length} transactions`; };
  $('#transaction-search').addEventListener('input',event=>{state.search=event.target.value;update();});
  $('#category-filter').addEventListener('change',event=>{state.category=event.target.value;update();});
  $('#transaction-account-filter').addEventListener('change',event=>{state.transactionAccountId=event.target.value;update();});
}

function budgetsHTML(d) {
  return `<div class="section-actions"><span>Category budgets for ${monthLabel()}</span><button class="button primary compact" data-action="add-budget">${icon('plus')}Create budget</button></div><div class="cards-grid">${d.budgets.map((b,i)=>`<article class="detail-card"><div class="detail-card-top"><span class="merchant-icon">${icon(categoryIcon(b.category))}</span><div class="card-menu"><button class="icon-button" data-action="edit-budget" data-id="${b.id}" aria-label="Edit ${escapeHTML(b.category)} budget">${icon('edit')}</button><button class="icon-button" data-action="delete-budget" data-id="${b.id}" aria-label="Delete ${escapeHTML(b.category)} budget">${icon('trash')}</button></div></div><h3>${escapeHTML(b.category)}</h3><div class="big-number">${money(b.spent)} <span>/ ${money(b.amount)}</span></div><div class="progress"><span style="width:${Math.min(100,percent(b.spent,b.amount))}%;background:${Number(b.spent)>Number(b.amount)?'#d2957b':palette[i%palette.length]}"></span></div><div class="card-bottom"><span>${percent(b.spent,b.amount)}% used</span><span>${Number(b.spent)>Number(b.amount)?`${money(Number(b.spent)-Number(b.amount))} over budget`:`${money(Number(b.amount)-Number(b.spent))} left`}</span></div></article>`).join('')}<button class="add-card" data-action="add-budget">${icon('plus')}A little plan for a category</button></div><p class="subtle-note">Budgets cover the selected month and currency. Expenses in categories without a budget are included in total spending, but do not reduce the category budget remaining.</p>`;
}

function goalsHTML(goals) {
  return `<div class="section-actions"><span>A little progress, one goal at a time</span><button class="button primary compact" data-action="add-goal">${icon('plus')}Create goal</button></div><div class="cards-grid">${goals.map((g,i)=>`<article class="detail-card"><div class="detail-card-top"><span class="goal-art" style="background:${i%2?'#f0ecf8':'#f3ecdf'};color:${i%2?'#9a82bb':'#b09a6d'}">${icon('goal')}</span><div class="card-menu"><button class="icon-button" data-action="edit-goal" data-id="${g.id}" aria-label="Edit ${escapeHTML(g.name)}">${icon('edit')}</button><button class="icon-button" data-action="delete-goal" data-id="${g.id}" aria-label="Delete ${escapeHTML(g.name)}">${icon('trash')}</button></div></div><h3>${escapeHTML(g.name)}</h3><div class="big-number">${money(g.saved)} <span>saved</span></div><p>of ${money(g.target)} goal</p><div class="progress"><span style="width:${Math.min(100,percent(g.saved,g.target))}%;background:${i%2?'#aa94d5':'#a9c397'}"></span></div><div class="card-bottom"><span>${percent(g.saved,g.target)}% of the way there</span><span>${g.deadline?`By ${dateLabel(g.deadline)}, ${g.deadline.slice(0,4)}`:'At your own pace'}</span></div><button class="button secondary compact" style="width:100%;margin-top:23px" data-action="edit-goal" data-id="${g.id}">${icon('plus')}Update saved amount</button></article>`).join('')}<button class="add-card" data-action="add-goal">${icon('plus')}Something to look forward to</button></div><p class="subtle-note">Savings goals are a planning tracker. Updating a saved amount does not move money or create a transaction.</p>`;
}

function uploadHTML() {
  const receipt = state.view === 'receipts';
  const relevant = state.review && state.review.source === (receipt?'receipt':'csv');
  return `${receipt && !state.config.receipt_scanner ? '<div class="notice warning">Receipt scanning is waiting for a Gemini API key. Add <strong>GEMINI_API_KEY</strong> to your server’s .env file and restart. You can use manual entry and CSV imports now.</div>' : ''}<div class="upload-layout"><section class="panel upload-panel"><h2>${receipt?'A paper trail, without the paperwork':'Let’s bring your transactions in'}</h2><p>${receipt?'Upload a clear photo of your receipt. SmartSpend reads Khmer and English, then lets you check every detail.':'Start with a CSV file from your records. Nothing gets saved until you’ve reviewed and confirmed the details.'}</p><div class="dropzone" id="dropzone"><span class="drop-icon">${icon(receipt?'scan':'upload')}</span><h3>${receipt?'Drop your receipt here':'Drop your CSV file here'}</h3><p>or choose a file from your device</p><button class="button primary" id="choose-file"${receipt&&!state.config.receipt_scanner?' disabled':''}>${icon(receipt?'scan':'upload')}${receipt?'Choose receipt':'Choose CSV file'}</button><input type="file" id="upload-file" accept="${receipt?'image/jpeg,image/png,image/webp':'.csv,text/csv'}" hidden><p class="upload-hint">${receipt?'JPG, PNG, or WebP · Up to 10 MB':'UTF-8 CSV · Up to 2 MB · 1,000 rows'}</p></div><div id="upload-status" class="notice" style="margin-top:18px" role="status" hidden></div>${!receipt?'<p class="upload-hint">Required columns: date, description, amount, currency.<br>Optional: kind (expense or income), category, note. Dates use YYYY-MM-DD.</p><button class="text-link" style="margin-top:14px" data-action="sample-csv">Download a sample CSV</button>':'<p class="upload-hint">Receipt images are sent to Google Gemini for extraction when you upload. Images are not stored by SmartSpend. Check the date, amount, and currency carefully before saving.</p>'}</section><aside class="panel upload-info"><h3>A little help along the way</h3>${[['upload',receipt?'A clear photo works best':'A simple file is all you need',receipt?'Keep the receipt flat, well lit, and fully in frame.':'Use positive amounts and USD or KHR in the currency column.'],['spark','A little intelligence, a lot less effort',receipt?'Gemini extracts your purchase details. The category classifier suggests a place for it.':'The category classifier suggests categories for rows that don’t have one.'],['check','You’re always in control','Review, edit, and choose the rows you want to keep. Only save when everything looks right.']].map(([i,t,p])=>`<div class="info-step"><span>${icon(i)}</span><div><h4>${t}</h4><p>${p}</p></div></div>`).join('')}<div class="notice">Two currencies. One clear picture.<br>USD and KHR are always tracked separately.</div></aside></div><div id="review-container">${relevant ? reviewHTML() : ''}</div>`;
}

function reviewHTML() {
  const r=state.review;
  if(r.source==='receipt')return receiptReviewHTML(r);
  return `<section class="panel review-panel"><div class="panel-header"><div><h2 class="panel-title">A quick check before we save</h2><p class="panel-subtitle">Edit any field. Uncheck rows you don’t want to import.</p></div><span class="pill">${r.rows.length} ${r.rows.length===1?'transaction':'transactions'}</span></div>${r.warnings?.length?`<div class="notice warning" style="margin:0 22px 18px">${r.warnings.map(escapeHTML).join('<br>')}</div>`:''}${r.items?.length?`<details class="receipt-details"><summary>Extracted receipt items</summary>${r.items.map(escapeHTML).join('<br>')}</details>`:''}<form id="review-form"><div class="table-wrap"><table class="review-table"><thead><tr><th>KEEP</th><th>DATE</th><th>MERCHANT</th><th>DESCRIPTION</th><th>AMOUNT</th><th>CURRENCY</th><th>ACCOUNT</th><th>TYPE</th><th>CATEGORY</th><th>NOTE / REVIEW</th></tr></thead><tbody>${r.rows.map((row,index)=>{const t=row.transaction;return `<tr data-row="${index}"${row.error?' class="error-row"':''}><td><input type="checkbox" name="keep" aria-label="Keep row ${row.row}"${!row.error&&!row.duplicate?' checked':''}></td><td><input type="date" name="date" aria-label="Date for row ${row.row}" value="${escapeHTML(t.date)}" required></td><td><input class="description-input" name="merchant" aria-label="Merchant for row ${row.row}" value="${escapeHTML(t.merchant||t.description)}" maxlength="200" required></td><td><input class="description-input" name="description" aria-label="Description for row ${row.row}" value="${escapeHTML(t.merchant||t.description)}" maxlength="200" required></td><td><input type="number" name="amount" aria-label="Amount for row ${row.row}" value="${escapeHTML(t.amount)}" step="${t.currency==='KHR'?'1':'.01'}" min="${t.currency==='KHR'?'1':'.01'}" max="999999999999" required></td><td><select name="currency" aria-label="Currency for row ${row.row}" required><option value="">Choose</option>${currencyOptions(t.currency)}</select></td><td><select name="account_id" aria-label="Account for row ${row.row}" required>${ExpectedExpenses.accountOptions(t.currency,t.account_id||ExpectedExpenses.defaultAccount(t.currency))}</select></td><td><select name="kind" aria-label="Type for row ${row.row}"><option value="expense"${t.kind==='expense'?' selected':''}>Expense</option><option value="income"${t.kind==='income'?' selected':''}>Income</option></select></td><td><select name="category" aria-label="Category for row ${row.row}">${categoryOptions(t.category)}</select></td><td><input name="note" aria-label="Note for row ${row.row}" value="${escapeHTML(t.note)}" maxlength="1000"><div class="row-warning">${row.duplicate?'Already imported. Leave unchecked to skip.':row.error?escapeHTML(row.error)+' Check Keep, then correct the fields.':''}</div></td></tr>`;}).join('')}</tbody></table></div><div class="review-actions"><span>Duplicates are skipped automatically when saving.</span><div><button class="button secondary" type="button" data-action="discard-review">Discard</button> <button class="button primary" type="submit" id="confirm-import">${icon('check')}Save selected transactions</button></div></div><div id="review-error" class="form-error" style="margin:0 20px 20px" role="alert" hidden></div></form></section>`;
}

function receiptReviewHTML(review) {
  const t=review.rows[0].transaction;
  const items=t.items?.length?t.items:[{name:'',price:''}];
  return `<section class="panel receipt-review"><div class="panel-header"><div><h2 class="panel-title">Review your receipt</h2><p class="panel-subtitle">Check the merchant, purchased items, prices, and receipt total before saving.</p></div><span class="pill">1 transaction</span></div>${review.warnings?.length?`<div class="notice warning">${review.warnings.map(escapeHTML).join('<br>')}</div>`:''}<form id="review-form" data-receipt="true"><div class="form-grid"><div class="field full"><label for="receipt-merchant">Merchant name</label><input id="receipt-merchant" name="merchant" value="${escapeHTML(t.merchant||t.description)}" maxlength="200" required></div><div class="field"><label for="receipt-date">Receipt date</label><input id="receipt-date" name="date" type="date" value="${escapeHTML(t.date)}" required></div><div class="field"><label for="receipt-currency">Currency</label><select id="receipt-currency" name="currency" required><option value="">Choose currency</option>${currencyOptions(t.currency)}</select></div><div class="field full"><label for="receipt-account">Paying account</label><select id="receipt-account" name="account_id" required>${ExpectedExpenses.accountOptions(t.currency||'USD',t.account_id||ExpectedExpenses.defaultAccount(t.currency||'USD'))}</select></div><div class="field full">${TransactionItems.html(items,t.currency||'USD')}</div><div class="field"><label for="receipt-amount">Receipt total</label><input id="receipt-amount" name="amount" type="number" value="${escapeHTML(t.amount)}" min="${t.currency==='KHR'?'1':'.01'}" step="${t.currency==='KHR'?'1':'.01'}" max="999999999999" required></div><div class="field"><label for="receipt-category">Category</label><select id="receipt-category" name="category">${categoryOptions(t.category,false)}</select></div><div class="field full"><label for="receipt-note">Note (optional)</label><textarea id="receipt-note" name="note" maxlength="1000">${escapeHTML(t.note)}</textarea></div></div><section id="receipt-expected-match" class="receipt-match"><h3>Is this payment for an expected expense?</h3><p>Choose an obligation to complete it and release its reserve, or save independently.</p><div id="receipt-match-suggestions" role="status"></div><label for="receipt-expected-id">Expected expense</label><select id="receipt-expected-id"><option value="">Record independently</option></select><label class="plan-check"><input type="checkbox" id="receipt-allow-negative">Confirm payment even if available funds become negative</label></section><div id="review-error" class="form-error" role="alert" hidden></div><div class="review-actions"><span>All items are saved with this purchase.</span><div><button class="button secondary" type="button" data-action="discard-review">Discard</button> <button class="button primary" id="confirm-import" type="submit">${icon('check')}Save transaction</button></div></div></form></section>`;
}

function bindReceiptReview(form) {
  TransactionItems.bind($('.item-editor',form),$('#receipt-amount'),$('#receipt-currency'));
  $('#receipt-currency').addEventListener('change',()=>{
    const riel=$('#receipt-currency').value==='KHR';
    $('#receipt-account').innerHTML=ExpectedExpenses.accountOptions($('#receipt-currency').value,ExpectedExpenses.defaultAccount($('#receipt-currency').value));
    $('#receipt-amount').step=riel?'1':'.01';$('#receipt-amount').min=riel?'1':'.01';
  });
  form.addEventListener('submit',event=>{
    event.preventDefault();
    const data=Object.fromEntries(new FormData(form));
    data.description=data.merchant;data.kind='expense';
    data.items=TransactionItems.read($('.item-editor',form));
    if(!data.items.length){$('#review-error').textContent='Add at least one purchased item and its price.';$('#review-error').hidden=false;return;}
    const expectedId=$('#receipt-expected-id').value;
    if(expectedId)completeReceiptExpected(data,Number(expectedId));
    else confirmReviewedTransactions([data],'receipt');
  });
  bindReceiptMatches(form);
}

function bindReceiptMatches(form) {
  let timer,request=0;
  const update=async()=>{
    const version=++request;
    const data=Object.fromEntries(new FormData(form));
    if(!data.currency||!data.account_id)return;
    try{
      const query=new URLSearchParams({currency:data.currency,account_id:data.account_id,status:'active'});
      const outstanding=await api('/expected-expenses?'+query);
      if(version!==request||!form.isConnected)return;
      const selector=$('#receipt-expected-id'),selected=selector.value;
      selector.innerHTML='<option value="">Record independently</option>'+outstanding.expenses.map(e=>`<option value="${e.id}">${escapeHTML(e.name)} · ${money(e.expected_amount,e.currency)} expected · ${money(e.reserved_amount,e.currency)} reserved</option>`).join('');
      if(outstanding.expenses.some(e=>String(e.id)===selected))selector.value=selected;
      if(!data.date||!data.merchant||!data.amount)return;
      const result=await api('/expected-expenses/matches',{method:'POST',body:JSON.stringify({...data,description:data.merchant,kind:'expense'})});
      if(version!==request||!form.isConnected)return;
      $('#receipt-match-suggestions').textContent=result.suggestions.length
        ? 'Possible matches: '+result.suggestions.map(e=>`${e.name} (${e.match_reasons.join(', ')})`).join('; ')+'. Choose one below to confirm.'
        : 'No suggested match. You can choose any outstanding expense below or record independently.';
    }catch{if(form.isConnected&&$('#receipt-match-suggestions'))$('#receipt-match-suggestions').textContent='Complete the merchant, date, amount, currency, and account to check for matches.';}
  };
  form.addEventListener('input',event=>{if(event.target.closest('#receipt-expected-match'))return;clearTimeout(timer);timer=setTimeout(update,350);});
  form.addEventListener('change',event=>{if(event.target.closest('#receipt-expected-match'))return;clearTimeout(timer);timer=setTimeout(update,100);});
  update();
}

async function completeReceiptExpected(data,id) {
  const errorBox=$('#review-error');errorBox.hidden=true;$('#confirm-import').disabled=true;
  const allowNegative=$('#receipt-allow-negative').checked;
  try{
    const result=await api(`/expected-expenses/${id}/complete`,{method:'POST',body:JSON.stringify({transaction:data,source:'receipt',allow_negative_available:allowNegative})});
    state.review=null;const message=result.already_paid?'Payment was already linked. No new expense added.':'Receipt saved and expected expense completed. Reserved funds released.';
    toast(message);showSavedTransaction(result.transaction,message);
  }catch(error){errorBox.textContent=error.message;errorBox.hidden=false;}
  finally{if($('#confirm-import'))$('#confirm-import').disabled=false;}
}

function showSavedTransaction(saved,message) {
  state.month=saved.date.slice(0,7);state.currency=saved.currency;
  state.focusTransactionId=saved.id;state.importMessage=message;
  state.search='';state.category='';state.transactionAccountId='';state.page=1;
  navigate('transactions');
}

async function confirmReviewedTransactions(rows,source) {
  const errorBox=$('#review-error');errorBox.hidden=true;
  $('#confirm-import').disabled=true;
  try {
    const result=await api('/import/confirm',{method:'POST',body:JSON.stringify({transactions:rows,source})});
    state.review=null;
    const message=result.inserted
      ? `${result.inserted} transaction${result.inserted===1?'':'s'} saved${result.skipped?` · ${result.skipped} duplicate${result.skipped===1?'':'s'} skipped`:''}.`
      : result.updated ? 'Purchase already saved. Item details added to the existing transaction.' : 'Already saved. No new transactions were added.';
    toast(message);
    if(source==='receipt' && result.transactions?.length)showSavedTransaction(result.transactions[0],message);
    else await render();
  }catch(error){errorBox.textContent=error.message;errorBox.hidden=false;}
  finally{if($('#confirm-import'))$('#confirm-import').disabled=false;}
}

function bindUpload() {
  $('#choose-file').addEventListener('click',()=>$('#upload-file').click());
  $('#upload-file').addEventListener('change',event=>{if(event.target.files[0])uploadFile(event.target.files[0]);});
  const zone=$('#dropzone');
  zone.addEventListener('dragover',event=>{event.preventDefault();zone.classList.add('dragover');});
  zone.addEventListener('dragleave',()=>zone.classList.remove('dragover'));
  zone.addEventListener('drop',event=>{event.preventDefault();zone.classList.remove('dragover');if(event.dataTransfer.files[0])uploadFile(event.dataTransfer.files[0]);});
  bindReview();
}

async function uploadFile(file) {
  const receipt=state.view==='receipts';
  const view=state.view;
  const status=$('#upload-status');
  if(receipt&&!state.config.receipt_scanner){toast('Connect a Gemini API key to scan receipts.');return;}
  if(file.size>(receipt?10_000_000:2_000_000)){status.textContent=`Choose a file smaller than ${receipt?'10':'2'} MB.`;status.className='notice error';status.hidden=false;return;}
  const data=new FormData();data.append('file',file);
  status.textContent=receipt?'Reading your receipt. This may take a moment…':'Preparing your transactions for review…';status.className='notice';status.hidden=false;
  $('#choose-file').disabled=true;
  try {
    const result=await api(`/import/${receipt?'receipt':'csv'}/preview`,{method:'POST',body:data});
    state.review=result;
    if(state.view!==view)return;
    $('#review-container').innerHTML=reviewHTML();
    bindReview();
    status.textContent=`${file.name} is ready. Review the details below before saving.`;
    $('#review-container').scrollIntoView({behavior:'smooth',block:'start'});
  } catch(error) {if(state.view===view){status.textContent=error.message;status.className='notice error';}}
  finally {if(state.view===view&&$('#choose-file'))$('#choose-file').disabled=false;}
}

function bindReview() {
  const form=$('#review-form');
  if(!form)return;
  if(form.dataset.receipt==='true'){bindReceiptReview(form);return;}
  const updateRow=row=>{
    const keep=$('[name=keep]',row).checked;
    $$('input:not([name=keep]),select',row).forEach(field=>field.disabled=!keep);
    const currency=$('[name=currency]',row).value;
    const account=$('[name=account_id]',row);
    if(!(state.accounts||[]).some(a=>String(a.id)===account.value && a.currency===currency))account.innerHTML=ExpectedExpenses.accountOptions(currency,ExpectedExpenses.defaultAccount(currency));
    $('[name=amount]',row).step=currency==='KHR'?'1':'.01';
    $('[name=amount]',row).min=currency==='KHR'?'1':'.01';
    if($('[name=kind]',row).value==='income')$('[name=category]',row).value='Income';
    else if($('[name=category]',row).value==='Income')$('[name=category]',row).value='Other';
  };
  $$('tbody tr',form).forEach(updateRow);
  form.addEventListener('change',event=>{const row=event.target.closest('tr');if(row)updateRow(row);});
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    const rows=$$('tbody tr',form).filter(row=>$('[name=keep]',row).checked).map(row=>Object.fromEntries(['date','merchant','description','amount','currency','account_id','kind','category','note'].map(key=>[key,$(`[name=${key}]`,row).value]).concat([['items',state.review.rows[Number(row.dataset.row)].transaction.items || []]])));
    const errorBox=$('#review-error');errorBox.hidden=true;
    if(!rows.length){errorBox.textContent='Choose at least one transaction to save.';errorBox.hidden=false;return;}
    await confirmReviewedTransactions(rows,state.review.source);
  });
}

function settingsHTML() {
  const c=state.config;
  return `<div class="settings-grid"><section class="panel settings-card"><h2>Your workspace</h2><div class="setting-row"><span>Application</span><strong>SmartSpend AI · v0.1.0</strong></div><div class="setting-row"><span>Workspace type</span><strong>Single-user · local</strong></div><div class="setting-row"><span>Database</span><strong>${c.database==='mysql'?'MySQL':'SQLite · local development'}</strong></div><div class="setting-row"><span>Sample data</span><strong>${c.demo?'Demo seeding enabled':'Disabled'}</strong></div><div class="setting-row"><span>Currencies</span><strong>USD & KHR · Separate ledgers</strong></div><p>This version is a personal local workspace. Authentication and account isolation are required before hosting it for multiple users.</p></section><section class="panel settings-card"><h2>A little intelligence behind the scenes</h2><div class="setting-row"><span>Receipt scanner</span><strong>${c.receipt_scanner?'Gemini key configured':'Waiting for a Gemini key'}</strong></div><div class="setting-row"><span>Receipt languages</span><strong>Khmer & English</strong></div><div class="setting-row"><span>Category suggestions</span><strong>Multinomial Naive Bayes</strong></div><p>Add <code>GEMINI_API_KEY</code> to your server’s <code>.env</code> file, then restart to enable receipt scanning. Uploaded receipt images are sent to Google for processing and are not stored by this app.</p><p>The category model starts with a small example set and learns from saved expense categories. Suggestions need your review. Dashboard spending insights are calculated from your totals.</p></section><section class="panel settings-card"><h2>Your data, a little more portable</h2><p>Use Export on Overview or Transactions to download the selected month and currency as a CSV file. Imported and scanned transactions are only saved after you confirm them.</p><button class="button secondary" style="margin-top:20px" data-navigate="transactions">${icon('transactions')}Explore transactions</button></section><section class="panel settings-card"><h2>Ready for MySQL</h2><p>Set <code>DATABASE_URL</code> to your MySQL connection in <code>.env</code> and restart. SmartSpend creates the application tables in your existing database. For a fresh workspace, use a new database and set <code>DEMO_DATA=false</code>.</p><p>Changing the database connection does not transfer existing records. Setup instructions and sample CSV files are included with the project.</p></section></div>`;
}

let dialogContext=null, suggestionTimer=null, suggestionRequest=0;
function openEditor(type,record=null) {
  dialogContext={type,record};
  const editing=!!record;
  const currency=record?.currency||state.currency;
  const field=(name,label,input,full=false)=>`<div class="field${full?' full':''}"><label for="field-${name}">${label}</label>${input}</div>`;
  const input=(name,type,value,extra='')=>`<input id="field-${name}" name="${name}" type="${type}" value="${escapeHTML(value??'')}" ${extra}>`;
  const moneyField=(name,label,value)=>field(name,label,input(name,'number',value,`min="${currency==='KHR'?'1':'.01'}" step="${currency==='KHR'?'1':'.01'}" max="999999999999" required`));
  let fields;
  if(type==='transaction') {
    $('#dialog-title').textContent=editing?'Edit transaction':'A little detail to remember';
    $('#save-dialog').textContent=editing?'Save changes':'Save transaction';
    fields=field('merchant','Merchant name',input('merchant','text',record?.merchant||record?.description,'placeholder="Shop, café, restaurant, or income source" maxlength="200" required'),true)
      +field('kind','Type',`<select id="field-kind" name="kind"><option value="expense"${record?.kind!=='income'?' selected':''}>Expense</option><option value="income"${record?.kind==='income'?' selected':''}>Income</option></select>`)
      +field('date','Date',input('date','date',record?.date||state.config.today,'required'))
      +moneyField('amount','Amount',record?.amount)
      +field('currency','Currency',`<select id="field-currency" name="currency">${currencyOptions(currency)}</select>`)
      +field('account_id','Account',`<select id="field-account_id" name="account_id" required>${ExpectedExpenses.accountOptions(currency,record?.account_id||ExpectedExpenses.defaultAccount(currency))}</select>`,true)
      +`<div class="field full">${TransactionItems.html(record?.items||[{name:'',price:''}],currency,!editing)}</div>`
      +field('category','Category',`<select id="field-category" name="category">${categoryOptions(record?.category||'Other')}</select><span class="suggestion" id="category-suggestion"></span>`,true)
      +field('note','A note, if you like',`<textarea id="field-note" name="note" maxlength="1000" placeholder="Any extra details…">${escapeHTML(record?.note||'')}</textarea>`,true);
  } else if(type==='budget') {
    $('#dialog-title').textContent=editing?'A little adjustment':'Give a category a little plan';
    $('#save-dialog').textContent=editing?'Update budget':'Create budget';
    fields=field('category','Category',`<select id="field-category" name="category"${editing?' disabled':''}>${categoryOptions(record?.category||'Food & drinks',false)}</select>`,true)
      +moneyField('amount','Monthly limit',record?.amount)
      +field('currency','Currency',`<select id="field-currency" name="currency"${editing?' disabled':''}>${currencyOptions(currency)}</select>`)
      +`<p class="field-hint field full">For ${monthLabel()}. Saving a limit for an existing category updates that month’s budget.</p>`;
  } else {
    $('#dialog-title').textContent=editing?'A little closer to your goal':'Something to look forward to';
    $('#save-dialog').textContent=editing?'Update goal':'Create goal';
    fields=field('name','What are you saving for?',input('name','text',record?.name,'placeholder="A rainy day, a little getaway…" maxlength="100" required'),true)
      +moneyField('target','Target amount',record?.target)
      +field('currency','Currency',`<select id="field-currency" name="currency"${editing?' disabled':''}>${currencyOptions(currency)}</select>`)
      +field('saved','Already saved',input('saved','number',record?.saved||'0',`min="0" max="999999999999" step="${currency==='KHR'?'1':'.01'}" required`))
      +field('deadline','Target date (optional)',input('deadline','date',record?.deadline))
      +'<p class="field-hint field full">This tracks your progress. Updating the amount does not create a transaction or move money.</p>';
  }
  $('#dialog-fields').innerHTML=`<div class="form-grid">${fields}</div>`;
  $('#editor-dialog').classList.toggle('transaction-dialog',type==='transaction');
  $('#form-error').hidden=true;
  $('#save-dialog').disabled=false;
  $('#editor-dialog').showModal();
  if(type==='transaction'){
    bindSuggestion();
    TransactionItems.bind($('.item-editor',$('#dialog-fields')),$('#field-amount'),$('#field-currency'));
    $('#field-kind').addEventListener('change',()=>{
      const income=$('#field-kind').value==='income';
      const editor=$('.item-editor',$('#dialog-fields'));
      editor.hidden=income;
      $$('input,button',editor).forEach(element=>element.disabled=income);
      if(!income)editor.querySelector('.add-item').disabled=editor.querySelectorAll('[data-item-row]').length>=100;
    });
    if($('#field-kind').value==='income')$('#field-kind').dispatchEvent(new Event('change'));
  }
  $('#field-currency')?.addEventListener('change',()=>{
    const riel=$('#field-currency').value==='KHR';
    if(type==='transaction')$('#field-account_id').innerHTML=ExpectedExpenses.accountOptions($('#field-currency').value,ExpectedExpenses.defaultAccount($('#field-currency').value));
    ['amount','target','saved'].forEach(name=>{const f=$(`#field-${name}`);if(f){f.step=riel?'1':'.01';if(name!=='saved')f.min=riel?'1':'.01';}});
  });
}

function bindSuggestion() {
  const input=$('#field-merchant'),kind=$('#field-kind'),category=$('#field-category');
  let categoryTouched=!!dialogContext.record;
  category.addEventListener('change',()=>categoryTouched=true);
  kind.addEventListener('change',()=>{category.value=kind.value==='income'?'Income':'Other';category.disabled=kind.value==='income';});
  category.disabled=kind.value==='income';
  $('.item-editor',$('#dialog-fields')).addEventListener('input',()=>input.dispatchEvent(new Event('input')));
  input.addEventListener('input',()=>{
    clearTimeout(suggestionTimer);
    const request=++suggestionRequest;
    suggestionTimer=setTimeout(async()=>{
      if(input.value.trim().length<2||kind.value==='income')return;
      try {
        const description=[input.value,...TransactionItems.read($('.item-editor',$('#dialog-fields'))).map(item=>item.name)].join(' ').slice(0,200);
        const result=await api('/categories/suggest',{method:'POST',body:JSON.stringify({description})});
        if(request!==suggestionRequest||!$('#category-suggestion'))return;
        $('#category-suggestion').textContent=result.category==='Other'?'Choose the category that feels right.':`Suggested: ${result.category} · You can change this.`;
        if(!categoryTouched)category.value=result.category;
      }catch{/* A suggestion failure should not prevent manual entry. */}
    },400);
  });
}

function closeDialog() {
  clearTimeout(suggestionTimer);suggestionRequest++;
  $('#editor-dialog').close();dialogContext=null;
}

async function saveEditor(event) {
  event.preventDefault();
  const {type,record}=dialogContext;
  const data=Object.fromEntries(new FormData(event.currentTarget));
  if(type==='transaction'){
    data.description=data.merchant;
    data.items=data.kind==='expense'?TransactionItems.read($('.item-editor',$('#dialog-fields'))):[];
    if(data.kind==='expense' && !record && !data.items.length){
      $('#form-error').textContent='Add at least one purchased item and its price.';
      $('#form-error').hidden=false;return;
    }
  }
  // Disabled selectors retain the immutable value of an existing record.
  if(type==='transaction'&&data.kind==='income')data.category='Income';
  if(type==='budget'){data.month=state.month;if(record){data.category=record.category;data.currency=record.currency;}}
  if(type==='goal'){if(record)data.currency=record.currency;data.deadline=data.deadline||null;}
  const path=type==='transaction'?'/transactions':type==='budget'?'/budgets':'/goals';
  $('#save-dialog').disabled=true;$('#form-error').hidden=true;
  try {
    const saved=await api(path+(record&&type!=='budget'?`/${record.id}`:''),{method:record&&type!=='budget'?'PUT':'POST',body:JSON.stringify(data)});
    const message=`${type==='transaction'?'Transaction':type==='budget'?'Budget':'Savings goal'} ${record?'updated':'saved'}.`;
    closeDialog();toast(message);
    if(type==='transaction')showSavedTransaction(saved,message);else await render();
  }catch(error){$('#form-error').textContent=error.message;$('#form-error').hidden=false;}
  finally{$('#save-dialog').disabled=false;}
}

function confirmDelete(type,record) {
  dialogContext={type:'delete',record,deleteType:type};
  const label=type==='transaction'?record.description:type==='budget'?record.category:record.name;
  $('#dialog-title').textContent=`Delete this ${type==='goal'?'goal':type}?`;
  $('#dialog-fields').innerHTML=`<p class="confirm-text">“${escapeHTML(label)}” will be removed from your workspace. This cannot be undone.</p>`;
  $('#save-dialog').textContent='Delete';$('#form-error').hidden=true;
  $('#editor-dialog').showModal();
}

async function deleteRecord(event) {
  event.preventDefault();
  const {record,deleteType}=dialogContext;
  $('#save-dialog').disabled=true;
  try {
    await api(`/${deleteType==='transaction'?'transactions':deleteType==='budget'?'budgets':'goals'}/${record.id}`,{method:'DELETE'});
    closeDialog();toast('Removed from your workspace.');await render();
  }catch(error){$('#form-error').textContent=error.message;$('#form-error').hidden=false;}
  finally{$('#save-dialog').disabled=false;}
}

function routeHash(view) {
  const params=new URLSearchParams();
  if(['dashboard','transactions','budgets','goals','expected','accounts'].includes(view)) {
    params.set('month',state.month); params.set('currency',state.currency);
    if(view==='transactions' && state.focusTransactionId)params.set('transaction',state.focusTransactionId);
  }
  return '#'+view+(params.size?'?'+params.toString():'');
}
function syncRoute() { history.replaceState(null,'',routeHash(state.view)); }
function readRoute() {
  const [view,query='']=location.hash.slice(1).split('?');
  const params=new URLSearchParams(query);
  state.view=Object.hasOwn(headings,view)?view:'dashboard';
  const month=params.get('month');
  if(/^(?!0000)\d{4}-(0[1-9]|1[0-2])$/.test(month||''))state.month=month;
  const currency=params.get('currency');
  if(['USD','KHR'].includes(currency))state.currency=currency;
  const id=Number(params.get('transaction'));
  state.focusTransactionId=state.view==='transactions' && Number.isSafeInteger(id) && id>0 ? id : null;
  if(state.view!=='transactions')state.importMessage='';
}
function navigate(view) { const hash=routeHash(view); if(location.hash===hash)render();else location.hash=hash; }
function downloadSample() {
  const csv=`date,description,amount,currency,kind,category,note\r\n${state.config.today},Brown Coffee,4.50,USD,expense,,Morning coffee\r\n${state.config.today},ផ្សារថ្មី,25000,KHR,expense,Groceries,Vegetables and fruit\r\n`;
  const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='smartspend-sample.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

document.addEventListener('click',event=>{
  const target=event.target.closest('[data-action],[data-navigate]');
  if(!target)return;
  if(target.dataset.navigate){navigate(target.dataset.navigate);return;}
  const action=target.dataset.action,id=Number(target.dataset.id);
  if(action==='retry')render();
  else if(action==='reload')location.reload();
  else if(action==='add-transaction')openEditor('transaction');
  else if(action==='add-budget')openEditor('budget');
  else if(action==='add-goal')openEditor('goal');
  else if(action==='sample-csv')downloadSample();
  else if(action==='discard-review'){state.review=null;$('#review-container').innerHTML='';toast('Preview discarded. No transactions were saved.');}
  else if(action==='next-page'||action==='previous-page'){state.page+=action==='next-page'?1:-1;$('#transaction-results').innerHTML=transactionResultsHTML();}
  else if(action.startsWith('edit-')||action.startsWith('delete-')){
    const type=action.split('-')[1];
    const records=type==='transaction'?state.transactions:type==='budget'?state.dashboard.budgets:state.goals;
    const record=records.find(r=>r.id===id);
    if(!record)return;
    if(action.startsWith('edit-'))openEditor(type,record);else confirmDelete(type,record);
  }
});

$('#editor-form').addEventListener('submit',event=>{if(dialogContext?.type==='delete')deleteRecord(event);else saveEditor(event);});
$('#close-dialog').addEventListener('click',closeDialog);
$('#cancel-dialog').addEventListener('click',closeDialog);
$('#editor-dialog').addEventListener('cancel',()=>{clearTimeout(suggestionTimer);suggestionRequest++;dialogContext=null;});
$('#add-transaction').addEventListener('click',()=>{if(state.config)openEditor('transaction');});
$('#month-picker').addEventListener('change',event=>{if(event.target.value){state.month=event.target.value;state.page=1;state.focusTransactionId=null;state.importMessage='';render();}});
$$('[data-currency]').forEach(button=>button.addEventListener('click',()=>{state.currency=button.dataset.currency;state.transactionAccountId='';state.page=1;state.focusTransactionId=null;state.importMessage='';render();}));
$('#export-button').addEventListener('click',()=>{window.location.href=`/api/export?month=${state.month}&currency=${state.currency}`;});
$('#menu-button').addEventListener('click',()=>{$('#sidebar').classList.add('open');$('#sidebar-backdrop').hidden=false;$('#menu-button').setAttribute('aria-expanded','true');});
function closeSidebar(){$('#sidebar').classList.remove('open');$('#sidebar-backdrop').hidden=true;$('#menu-button').setAttribute('aria-expanded','false');}
$('#sidebar-backdrop').addEventListener('click',closeSidebar);
window.addEventListener('hashchange',()=>{readRoute();closeSidebar();render();});

async function init() {
  try {
    state.config=await api('/config');
    state.accounts=await api('/accounts');
    state.month=state.config.today.slice(0,7);
    readRoute();
    $('#month-picker').value=state.month;
    $('#demo-badge').hidden=!state.config.demo;
    await render();
  }catch(error){$('#app-error').textContent='The workspace could not connect to the server. '+error.message;$('#app-error').hidden=false;$('#view-content').innerHTML='<div class="empty-state"><h3>The server needs a little attention</h3><p>Start SmartSpend with the command in the README, then refresh this page.</p><button class="button secondary" data-action="reload">Refresh page</button></div>';}
}
init();
