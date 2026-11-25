'use strict';

// Shared item editor for manual entry, saved transactions, and receipt review.
window.TransactionItems = (() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const svg = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
  function row(item, currency) {
    return `<div class="item-row" data-item-row><input class="item-name" aria-label="Item name" placeholder="Item name, e.g. Iced latte × 2" value="${escape(item.name)}" maxlength="200" required><input class="item-price" aria-label="Item price" type="number" placeholder="0${currency==='KHR'?'':'.00'}" value="${escape(item.price)}" min="0" max="999999999999" step="${currency==='KHR'?'1':'.01'}" required><button class="icon-button remove-item" type="button" aria-label="Remove item">${svg('trash')}</button></div>`;
  }
  function html(items, currency, autoTotal = false) {
    return `<section class="item-editor" data-auto-total="${autoTotal}"><div class="item-editor-heading"><div><h3>Purchased items</h3><p>Enter the full price for each line, including quantities.</p></div><button class="button secondary compact add-item" type="button">${svg('plus')}Add item</button></div><div class="item-columns" aria-hidden="true"><span>Item name</span><span>Line price</span><span></span></div><div class="item-rows">${items.map(item=>row(item,currency)).join('')}</div><p class="item-empty"${items.length?' hidden':''}>No item details recorded. Add an item to keep the purchase details here.</p><div class="item-subtotal"><span>Items subtotal <output aria-live="polite">—</output></span><button class="text-link use-items-total" type="button">Use as transaction total</button></div><p class="item-total-note" role="status"></p></section>`;
  }
  function read(editor) {
    return [...editor.querySelectorAll('[data-item-row]')].map(item=>({
      name:item.querySelector('.item-name').value.trim(),
      price:item.querySelector('.item-price').value,
    }));
  }
  function minorUnits(raw, currency) {
    if (!(currency==='KHR'?/^\d+$/:/^\d+(?:\.\d{1,2})?$/).test(raw)) return null;
    const [whole,fraction=''] = raw.split('.');
    return BigInt(whole)*(currency==='KHR'?1n:100n) + (currency==='KHR'?0n:BigInt(fraction.padEnd(2,'0')));
  }
  function decimalString(value, currency) {
    return currency==='KHR'?String(value):`${value/100n}.${String(value%100n).padStart(2,'0')}`;
  }
  function bind(editor, totalInput, currencyInput) {
    const output=editor.querySelector('output');
    const note=editor.querySelector('.item-total-note');
    const update = () => {
      const currency=currencyInput.value || 'USD';
      const rows=[...editor.querySelectorAll('[data-item-row]')];
      let subtotal=0n, valid=true;
      rows.forEach(item=>{
        const price=item.querySelector('.item-price');
        price.step=currency==='KHR'?'1':'.01';
        const value=minorUnits(price.value,currency);
        price.setCustomValidity(value===null && price.value ? (currency==='KHR'?'Enter a whole riel price.':'Enter a price with at most two decimal places.') : '');
        if(value===null)valid=false;else subtotal+=value;
      });
      editor.querySelector('.item-empty').hidden=rows.length>0;
      editor.querySelector('.item-columns').hidden=rows.length===0;
      editor.querySelector('.add-item').disabled=rows.length>=100;
      editor.querySelector('.use-items-total').disabled=!valid || !rows.length;
      const value=decimalString(subtotal,currency);
      output.textContent=valid?new Intl.NumberFormat('en-US',{style:'currency',currency,minimumFractionDigits:currency==='KHR'?0:2,maximumFractionDigits:currency==='KHR'?0:2}).format(value):'Complete each price';
      if(valid && rows.length && editor.dataset.autoTotal==='true')totalInput.value=value;
      const total=minorUnits(totalInput.value,currency);
      note.textContent=valid && rows.length && total!==null && total!==subtotal
        ? 'The transaction total differs from the items subtotal. Check any tax, tips, or discounts before saving.'
        : 'You can adjust the transaction total for tax, tips, or discounts.';
    };
    editor.addEventListener('input',update);
    editor.addEventListener('click',event=>{
      if(event.target.closest('.add-item')) {
        editor.querySelector('.item-rows').insertAdjacentHTML('beforeend',row({name:'',price:''},currencyInput.value));
        const rows=editor.querySelectorAll('.item-name');rows[rows.length-1].focus();
      } else if(event.target.closest('.remove-item'))event.target.closest('[data-item-row]').remove();
      else if(event.target.closest('.use-items-total'))editor.dataset.autoTotal='true';
      else return;
      update();
    });
    totalInput.addEventListener('input',()=>{editor.dataset.autoTotal='false';update();});
    currencyInput.addEventListener('change',update);
    update();
    return {update};
  }
  return {html,bind,read};
})();
