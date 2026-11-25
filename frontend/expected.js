'use strict';

// Expected amounts, virtual allocations, actual payments, and budgets remain
// separate. All displayed balances and funding ratios come from the API.
window.ExpectedExpenses = (() => {
  let filterCurrency='', filters={account_id:'',status:'active',category:'',due_from:'',due_to:''};
  let currentAccounts=[];
  const label=status=>({planned:'Planned',partially_reserved:'Partially reserved',fully_reserved:'Fully reserved',paid:'Paid',cancelled:'Cancelled'}[status]||status);
  const field=(name,title,control,full=false)=>`<div class="field${full?' full':''}"><label for="plan-${name}">${title}</label>${control}</div>`;
  const input=(name,type,value='',extra='')=>`<input id="plan-${name}" name="${name}" type="${type}" value="${escapeHTML(value??'')}" ${extra}>`;
  const amount=(name,title,value,currency,minimum='0')=>field(name,title,input(name,'number',value,`min="${minimum}" step="${currency==='KHR'?'1':'.01'}" max="999999999999" required`));
  const options=(values,selected)=>values.map(([value,title])=>`<option value="${escapeHTML(value)}"${String(value)===String(selected)?' selected':''}>${escapeHTML(title)}</option>`).join('');
  function accountOptions(currency,selected,all=false) {
    return `${all?'<option value="">All accounts</option>':''}${options((state.accounts||[]).filter(a=>a.currency===currency).map(a=>[a.id,a.name]),selected)}`;
  }
  function defaultAccount(currency) {return (state.accounts||[]).find(a=>a.currency===currency&&a.default_key)?.id || (state.accounts||[]).find(a=>a.currency===currency)?.id;}
  function balanceHTML(finance) {
    if(!finance)return '';
    return `<section class="balance-overview" aria-label="Current balances"><article class="safe-to-spend"><span>Available balance · Safe to spend</span><strong>${money(finance.available_balance,finance.currency)}</strong><p>Actual balance minus allocated reserves</p></article><article><span>Actual balance</span><strong>${money(finance.actual_balance,finance.currency)}</strong><p>Opening balances + recorded income − expenses</p></article><article><span>Reserved funds</span><strong>${money(finance.reserved_balance,finance.currency)}</strong><p>Allocated to ${finance.upcoming_count} unpaid obligation${finance.upcoming_count===1?'':'s'}</p></article><div class="balance-breakdown"><span>${finance.currency} · Current balances as of ${escapeHTML(finance.as_of)} · All recorded dates</span>${Number(finance.actual_balance)>0&&Number(finance.available_balance)>=0?`<div class="progress" aria-label="Balance split between available and reserved"><span style="width:${Math.min(100,percent(finance.available_balance,finance.actual_balance))}%;background:#a8c795"></span></div><span>Available ${money(finance.available_balance,finance.currency)} · Reserved ${money(finance.reserved_balance,finance.currency)}</span>`:''}${Number(finance.available_balance)<0?'<p class="balance-warning">Available funds are below zero. Review your recorded balance and allocations before reserving more.</p>':''}</div></section>`;
  }
  function dueLabel(expense) {
    const days=expense.days_until_due;
    return expense.state!=='active'?dateLabel(expense.due_date)+', '+expense.due_date.slice(0,4):days<0?`${Math.abs(days)} day${days===-1?'':'s'} overdue`:days===0?'Due today':`Due in ${days} day${days===1?'':'s'}`;
  }
  function upcomingHTML(finance) {
    if(!finance)return '';
    return `<section class="panel upcoming-panel"><div class="panel-header"><div><h2 class="panel-title">Upcoming expected expenses</h2><p class="panel-subtitle">${finance.overdue_count?`${finance.overdue_count} overdue · `:''}An expectation is separate from the money reserved for it</p></div><button class="text-link" data-navigate="expected">Manage plans</button></div>${finance.upcoming.length?`<div class="upcoming-list">${finance.upcoming.map(e=>`<div><span class="merchant-icon">${icon(categoryIcon(e.category))}</span><div><strong>${escapeHTML(e.name)}</strong><p class="${e.overdue?'overdue-text':''}">${escapeHTML(dueLabel(e))} · ${escapeHTML(e.account_name)}</p></div><div class="upcoming-amount"><strong>${money(e.expected_amount,e.currency)}</strong><span>${money(e.reserved_amount,e.currency)} reserved</span></div></div>`).join('')}</div>`:`<div class="empty-state"><h3>A little room for future plans</h3><p>Plan an upcoming expense, then choose how much to set aside.</p><button class="button secondary" data-navigate="expected">Plan an expense</button></div>`}</section>`;
  }
  async function pageHTML() {
    if(filterCurrency!==state.currency){filterCurrency=state.currency;filters.account_id='';}
    const query=new URLSearchParams({currency:state.currency,...Object.fromEntries(Object.entries(filters).filter(([,v])=>v!==''))});
    const [data,series]=await Promise.all([api('/expected-expenses?'+query),api('/recurring-expenses?currency='+state.currency)]);
    const s=data.summary;
    return `${balanceHTML(s)}<div class="planning-summary"><div><span>Total expected</span><strong>${money(s.total_expected)}</strong><p>All unpaid obligations</p></div><div><span>Actually reserved</span><strong>${money(s.reserved_balance)}</strong><p>Money currently allocated</p></div><div><span>Still unfunded</span><strong>${money(s.remaining_unfunded)}</strong><p>Expected amounts less reserves</p></div></div><div class="section-actions"><span>Upcoming obligations, ordered by payment date</span><button class="button primary" data-plan-action="create">${icon('plus')}Plan an expense</button></div><section class="plan-filters panel"><label>Account<select id="plan-filter-account">${accountOptions(state.currency,filters.account_id,true)}</select></label><label>Status<select id="plan-filter-status">${options([['active','All unpaid'],['planned','Planned'],['partially_reserved','Partially reserved'],['fully_reserved','Fully reserved'],['overdue','Overdue'],['paid','Paid'],['cancelled','Cancelled'],['all','All statuses']],filters.status)}</select></label><label>Category<select id="plan-filter-category"><option value="">All categories</option>${categoryOptions(filters.category,false)}</select></label><label>Due from<input type="date" id="plan-filter-from" value="${escapeHTML(filters.due_from)}"></label><label>Due through<input type="date" id="plan-filter-to" value="${escapeHTML(filters.due_to)}"></label></section><div class="cards-grid expected-cards">${data.expenses.length?data.expenses.map(expenseCard).join(''):'<div class="empty-state panel"><h3>No expected expenses in this view</h3><p>Create a plan or adjust the filters to see your obligations here.</p></div>'}</div>${series.length?`<details class="panel recurring-definitions"><summary>Recurring definitions (${series.length})</summary><p>Each definition generates a separate, unfunded occurrence after the current one is paid or cancelled. Existing occurrences retain their own history.</p>${series.map(r=>`<div><span><strong>${escapeHTML(r.name)}</strong> · ${escapeHTML(r.frequency)} · ${money(r.expected_amount,r.currency)}<small>Definition #${r.id} · ${r.active?'Active':'Stopped'}</small></span>${r.active?`<button class="button secondary compact" data-plan-action="stop-series" data-id="${r.id}">Stop future repeats</button>`:''}</div>`).join('')}</details>`:''}<p class="subtle-note">These balances are independent of the monthly category budgets. Creating an expected expense does not spend or reserve money until an allocation is made. Reminders are shown in the app; no notifications are sent.</p>`;
  }
  function expenseCard(e) {
    const active=e.state==='active';
    return `<article class="detail-card expected-card" data-expense-id="${e.id}"><div class="detail-card-top"><span class="merchant-icon">${icon(categoryIcon(e.category))}</span><span class="plan-status ${e.status}">${label(e.status)}</span></div><h3>${escapeHTML(e.name)}</h3><p>${escapeHTML(e.category)} · ${escapeHTML(e.account_name)}</p>${e.description?`<p>${escapeHTML(e.description)}</p>`:''}<div class="big-number">${money(e.expected_amount,e.currency)} <span>${e.amount_type==='estimated'?'estimated':'expected'}</span></div><div class="progress"><span style="width:${e.funding_progress}%;background:${e.overdue?'#d5a184':'#a6bf91'}"></span></div><div class="card-bottom"><span>${money(e.reserved_amount,e.currency)} reserved</span><span>${active?`${money(e.unfunded_amount,e.currency)} unfunded`:`${e.state==='paid'?money(e.actual_amount,e.currency)+' paid':'Funds released'}`}</span></div><p class="plan-due ${e.overdue?'overdue-text':''}">${escapeHTML(dueLabel(e))} · ${escapeHTML(e.due_date)}</p>${e.recurrence!=='once'?`<span class="plan-recurrence">${escapeHTML(e.recurrence)} · Occurrence ${e.occurrence+1}${e.recurrence_active?'':' · Repeats stopped'}</span>`:''}${e.reminder_due?'<span class="plan-reminder">Payment reminder</span>':''}<div class="plan-actions">${active?`<button class="button secondary compact" data-plan-action="fund" data-id="${e.id}">Add / release funds</button><button class="button primary compact" data-plan-action="pay" data-id="${e.id}">Pay / link payment</button><button class="text-link" data-plan-action="edit" data-id="${e.id}">Edit</button><button class="text-link" data-plan-action="cancel" data-id="${e.id}">Cancel</button>`:e.transaction_id?`<button class="button secondary compact" data-plan-action="view-payment" data-id="${e.transaction_id}">View payment</button>`:''}<button class="text-link" data-plan-action="history" data-id="${e.id}">Allocation history</button></div></article>`;
  }
  function bindPage() {
    [['account','account_id'],['status','status'],['category','category'],['from','due_from'],['to','due_to']].forEach(([suffix,key])=>{
      $('#plan-filter-'+suffix)?.addEventListener('change',event=>{filters[key]=event.target.value;render();});
    });
  }
  async function accountsHTML() {
    state.accounts=await api('/accounts');currentAccounts=state.accounts;
    const rows=currentAccounts.filter(a=>a.currency===state.currency);
    return `<div class="section-actions"><span>Each account holds one currency. Opening balances are separate from income.</span><button class="button primary" data-plan-action="create-account">${icon('plus')}Add account</button></div><div class="cards-grid">${rows.map(a=>`<article class="detail-card"><div class="detail-card-top"><span class="merchant-icon">${icon('wallet')}</span><div class="card-menu"><button class="icon-button" data-plan-action="edit-account" data-id="${a.id}" aria-label="Edit ${escapeHTML(a.name)}">${icon('edit')}</button>${!a.default_key?`<button class="icon-button" data-plan-action="delete-account" data-id="${a.id}" aria-label="Delete ${escapeHTML(a.name)}">${icon('trash')}</button>`:''}</div></div><h3>${escapeHTML(a.name)}</h3><p>${a.default_key?'Default account · ':''}${a.currency}</p><div class="big-number">${money(a.available_balance,a.currency)} <span>available</span></div><div class="account-detail"><span>Actual balance</span><strong>${money(a.actual_balance,a.currency)}</strong></div><div class="account-detail"><span>Reserved</span><strong>${money(a.reserved_balance,a.currency)}</strong></div><div class="account-detail"><span>Opening balance</span><strong>${money(a.opening_balance,a.currency)}</strong></div></article>`).join('')}</div><div class="notice">Actual balance = opening balance + completed income − completed expenses. Only transactions dated today or earlier are included. Budget limits and savings goal progress do not alter account balances.</div><p class="subtle-note">Accounts containing financial history cannot be deleted. This is a local, single-user workspace; account names are organizational labels, not connections to your bank.</p>`;
  }
  function dialog(title,html,button,submit) {
    const box=$('#plan-dialog');$('#plan-dialog-title').textContent=title;
    $('#plan-dialog-fields').innerHTML=html;$('#plan-dialog-error').hidden=true;
    $('#plan-dialog-save').textContent=button||'Close';$('#plan-dialog-save').hidden=!submit;
    $('#plan-dialog-form').onsubmit=async event=>{
      event.preventDefault();$('#plan-dialog-error').hidden=true;$('#plan-dialog-save').disabled=true;
      try {await submit(Object.fromEntries(new FormData(event.currentTarget)));box.close();state.accounts=await api('/accounts');await render();}
      catch(error){$('#plan-dialog-error').textContent=error.message;$('#plan-dialog-error').hidden=false;}
      finally{$('#plan-dialog-save').disabled=false;}
    };
    box.showModal();
  }
  function planDialog(e=null) {
    const currency=e?.currency||state.currency,editing=!!e;
    const minimum=currency==='KHR'?'1':'.01';
    const html=`<div class="form-grid">${field('name','Expense name',input('name','text',e?.name,'maxlength="200" placeholder="Rent, tuition, internet…" required'),true)}${amount('expected_amount','Expected amount',e?.expected_amount,currency,minimum)}${field('currency','Currency',`<select id="plan-currency" name="currency">${currencyOptions(currency)}</select>`)}${field('account_id','Paying account',`<select id="plan-account_id" name="account_id" required>${accountOptions(currency,e?.account_id||defaultAccount(currency))}</select>`)}${field('category','Category',`<select id="plan-category" name="category">${categoryOptions(e?.category||'Bills & utilities',false)}</select>`)}${field('due_date','Expected payment date',input('due_date','date',e?.due_date||state.config.today,'required'))}${field('amount_type','Amount type',`<select id="plan-amount_type" name="amount_type">${options([['fixed','Fixed'],['estimated','Estimated']],e?.amount_type||'fixed')}</select>`)}${field('recurrence','Repeat',`<select id="plan-recurrence" name="recurrence"${editing?' disabled':''}>${options([['once','One-time'],['weekly','Weekly'],['monthly','Monthly'],['yearly','Yearly']],e?.recurrence||'once')}</select>`)}${field('reminder_days','In-app reminder',`<select id="plan-reminder_days" name="reminder_days">${options([['','No reminder'],['0','On the due date'],['1','1 day before'],['3','3 days before'],['7','7 days before']],e?.reminder_days??'')}</select>`)}${!editing?`${field('funding_method','Funding method',`<select id="plan-funding_method" name="funding_method"><option value="gradual">Gradual / reserve later</option><option value="full">Reserve full amount now</option></select>`)}${amount('reserved_amount','Reserve now (can be zero)','0',currency)}`:`<p class="field-hint field full">${money(e.reserved_amount,currency)} is currently reserved. Use Add / release funds to change it. Edits apply to this occurrence; the recurring definition retains its original settings.</p>`}${field('description','Description (optional)',`<textarea id="plan-description" name="description" maxlength="1000">${escapeHTML(e?.description||'')}</textarea>`,true)}</div>`;
    dialog(editing?'Edit expected expense':'Plan an expected expense',html,editing?'Save changes':'Create plan',async data=>{
      data.account_id=Number(data.account_id);data.reminder_days=data.reminder_days===''?null:Number(data.reminder_days);
      if(editing){data.recurrence=e.recurrence;data.funding_method=e.funding_method;}
      const saved=await api('/expected-expenses'+(editing?'/'+e.id:''),{method:editing?'PUT':'POST',body:JSON.stringify(data)});
      state.currency=saved.currency;filterCurrency=saved.currency;
      filters={account_id:String(saved.account_id),status:'active',category:'',due_from:'',due_to:''};
      toast(editing?'Expected expense updated.':'Expected expense created.');
    });
    $('#plan-currency').addEventListener('change',()=>{
      const selected=$('#plan-currency').value;$('#plan-account_id').innerHTML=accountOptions(selected,defaultAccount(selected));
      ['expected_amount','reserved_amount'].forEach(name=>{const el=$('#plan-'+name);if(el){el.step=selected==='KHR'?'1':'.01';el.min=name==='reserved_amount'?'0':selected==='KHR'?'1':'.01';}});
    });
    $('#plan-funding_method')?.addEventListener('change',()=>{$('#plan-reserved_amount').disabled=$('#plan-funding_method').value==='full';});
  }
  function fundDialog(e) {
    dialog('Add or release reserved funds',`<p class="confirm-text">${escapeHTML(e.name)} · ${money(e.reserved_amount,e.currency)} reserved of ${money(e.expected_amount,e.currency)} expected. Only this account’s unallocated funds can be reserved.</p><div class="form-grid">${field('action','Action',`<select id="plan-action" name="action"><option value="add">Add funds</option><option value="release">Release funds</option></select>`)}${amount('amount','Amount','',e.currency,e.currency==='KHR'?'1':'.01')}</div>`,'Update reserve',async data=>{
      await api(`/expected-expenses/${e.id}/fund`,{method:'POST',body:JSON.stringify(data)});toast('Reserved allocation updated.');
    });
  }
  async function payDialog(e) {
    const payments=await api(`/expected-expenses/${e.id}/payments`);
    dialog('Record or link a payment',`<p class="confirm-text">${escapeHTML(e.name)} · ${money(e.reserved_amount,e.currency)} reserved. Confirming will release this reserve and mark the obligation paid.</p><div class="form-grid">${field('mode','Payment method',`<select id="plan-mode" name="mode"><option value="new">Record a new expense</option><option value="link">Link an existing expense</option></select>`,true)}<div class="field full" id="existing-payment-fields" hidden><label for="plan-transaction_id">Existing payment · ${escapeHTML(e.account_name)}</label><select id="plan-transaction_id" name="transaction_id" disabled><option value="">Choose a payment</option>${options(payments.map(t=>[t.id,`${t.date} · ${t.merchant} · ${money(t.amount,t.currency)}`]),'')}</select><p class="field-hint">Linking uses the payment already in your ledger. It does not deduct money again.</p></div><div class="field full" id="new-payment-fields"><div class="form-grid">${field('merchant','Merchant / recipient',input('merchant','text',e.name,'maxlength="200" required'),true)}${amount('amount',`Actual payment (${e.currency})`,e.expected_amount,e.currency,e.currency==='KHR'?'1':'.01')}${field('date','Actual payment date',input('date','date',state.config.today,`max="${state.config.today}" required`))}${field('note','Note (optional)',input('note','text','','maxlength="1000"'),true)}<label class="plan-check field full"><input type="checkbox" name="allow_negative_available">Record even if available funds would become negative</label></div></div></div>`,'Confirm payment',async data=>{
      const payload=data.mode==='link'?{transaction_id:Number(data.transaction_id)}:{transaction:{merchant:data.merchant,description:data.merchant,date:data.date,amount:data.amount,currency:e.currency,account_id:e.account_id,category:e.category,kind:'expense',note:data.note,items:[{name:e.name,price:data.amount}]},allow_negative_available:!!data.allow_negative_available};
      if(data.mode==='link'&&!data.transaction_id)throw new Error('Choose the payment to link.');
      await api(`/expected-expenses/${e.id}/complete`,{method:'POST',body:JSON.stringify(payload)});toast('Payment confirmed. Reserved funds released.');
    });
    $('#plan-mode').addEventListener('change',()=>{
      const link=$('#plan-mode').value==='link';$('#existing-payment-fields').hidden=!link;$('#new-payment-fields').hidden=link;
      $('#plan-transaction_id').disabled=!link;$('#plan-transaction_id').required=link;
      $$('input',$('#new-payment-fields')).forEach(el=>el.disabled=link);
    });
  }
  function accountDialog(a=null) {
    const currency=a?.currency||state.currency;
    dialog(a?'Edit account':'Add a financial account',`<div class="form-grid">${field('name','Account name',input('name','text',a?.name,'maxlength="100" placeholder="Cash, bank account, mobile wallet…" required'),true)}${field('currency','Currency',`<select id="plan-currency" name="currency"${a?' disabled':''}>${currencyOptions(currency)}</select>`)}${field('opening_balance','Opening balance',input('opening_balance','number',a?.opening_balance||'0',`step="${currency==='KHR'?'1':'.01'}" min="-999999999999" max="999999999999" required`))}<p class="field-hint field full">Use the balance held before the transactions you entered. Do not include income already recorded. Accounts use a single currency.</p></div>`,'Save account',async data=>{
      data.currency=a?.currency||data.currency;
      const saved=await api('/accounts'+(a?'/'+a.id:''),{method:a?'PUT':'POST',body:JSON.stringify(data)});
      state.currency=saved.currency;toast('Account saved.');
    });
    $('#plan-currency').addEventListener('change',()=>$('#plan-opening_balance').step=$('#plan-currency').value==='KHR'?'1':'.01');
  }
  async function action(name,id) {
    if(name==='create'){planDialog();return;}
    if(name==='create-account'){accountDialog();return;}
    if(name==='view-payment'){showSavedTransaction(await api('/transactions/'+id),'Payment linked to an expected expense.');return;}
    if(name==='edit-account'){accountDialog(currentAccounts.find(a=>a.id===id));return;}
    if(name==='delete-account'){
      dialog('Delete unused account?',`<p class="confirm-text">Only an account without financial history can be deleted. This cannot be undone.</p>`,'Delete account',()=>api('/accounts/'+id,{method:'DELETE'}));return;
    }
    if(name==='stop-series'){
      dialog('Stop future repeats?',`<p class="confirm-text">Existing occurrences and their reserves stay intact. No further occurrences will be generated for this definition.</p>`,'Stop repeats',()=>api('/recurring-expenses/'+id+'/stop',{method:'POST'}));return;
    }
    const e=await api('/expected-expenses/'+id);
    if(name==='edit')planDialog(e);
    else if(name==='fund')fundDialog(e);
    else if(name==='pay')await payDialog(e);
    else if(name==='cancel')dialog('Cancel this expected expense?',`<p class="confirm-text">${escapeHTML(e.name)} will be cancelled and its ${money(e.reserved_amount,e.currency)} reserve released. Actual spending stays unchanged.</p>${e.recurring_id?'<label class="plan-check"><input type="checkbox" name="stop_recurrence">Also stop future repeats</label>':''}`,'Cancel expense',data=>api(`/expected-expenses/${e.id}/cancel`,{method:'POST',body:JSON.stringify({stop_recurrence:!!data.stop_recurrence})}));
    else if(name==='history'){
      const record=e;
      dialog('Reserve allocation history',`<p class="confirm-text">${escapeHTML(record.name)} · These are virtual allocations, not expense transactions.</p><div class="allocation-history">${record.allocations.length?record.allocations.map(entry=>`<div><span>${escapeHTML(entry.reason)}<small>${escapeHTML(entry.created_at.replace('T',' '))} UTC</small></span><strong>${money(entry.amount,entry.currency||record.currency)}</strong></div>`).join(''):'<p>No money has been reserved for this obligation.</p>'}</div>`,null,null);
    }
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-plan-action]');
    if(!button)return;
    action(button.dataset.planAction,Number(button.dataset.id)).catch(error=>toast(error.message));
  });
  document.addEventListener('click',event=>{if(event.target.closest('[data-close-plan]'))$('#plan-dialog').close();});
  return {balanceHTML,upcomingHTML,pageHTML,bindPage,accountsHTML,accountOptions,defaultAccount};
})();
