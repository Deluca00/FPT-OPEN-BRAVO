// Payment tab logic
const pay$ = (sel) => document.querySelector(sel);
let payScheduleCache = [];
let paymentLoadedOnce = false;

async function payFetchJSON(url, options = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

async function loadPayStats() {
  try {
    const data = await payFetchJSON('/api/dashboard/financial');
    const s = data.stats || {};
    pay$('#payStatBalance').textContent = (s.total_balance || 0).toLocaleString();
    pay$('#payStatRecv').textContent = (s.total_receivables || 0).toLocaleString();
    pay$('#payStatPay').textContent = (s.total_payables || 0).toLocaleString();
    const overdue = (s.overdue_receivables || 0) + (s.overdue_payables || 0);
    pay$('#payStatOver').textContent = overdue.toLocaleString();
  } catch (err) {
    console.error('loadPayStats', err);
    if (window.showAlert) showAlert(err.message || 'Không tải được thống kê', 'danger');
  }
}

async function loadPayAccounts() {
  try {
    const data = await payFetchJSON('/api/financial-accounts');
    const sel = pay$('#payAccount');
    sel.innerHTML = '';
    (data.accounts || []).forEach((a) => {
      const opt = document.createElement('option');
      opt.value = a.fin_financial_account_id;
      opt.textContent = `${a.name} (${a.currency || ''})`;
      sel.appendChild(opt);
    });
  } catch (err) {
    if (window.showAlert) showAlert(err.message || 'Không tải được tài khoản', 'danger');
  }
}

async function loadPayMethods() {
  try {
    const data = await payFetchJSON('/api/payment-methods');
    const sel = pay$('#payMethod');
    sel.innerHTML = '';
    (data.methods || []).forEach((m) => {
      const opt = document.createElement('option');
      opt.value = m.fin_paymentmethod_id;
      opt.textContent = m.name;
      sel.appendChild(opt);
    });
  } catch (err) {
    if (window.showAlert) showAlert(err.message || 'Không tải được phương thức', 'danger');
  }
}

async function loadPaySchedules() {
  try {
    const data = await payFetchJSON('/api/payment-schedules?pending=true');
    payScheduleCache = data.schedules || [];
    const tbody = pay$('#payScheduleBody');
    tbody.innerHTML = '';
    payScheduleCache.forEach((s) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><input type="checkbox" data-sch="${s.fin_payment_schedule_id}"></td>
        <td>${s.schedule_type || ''}</td>
        <td>${s.bpartner_name || ''}</td>
        <td>${s.invoice_no || s.order_no || ''}</td>
        <td>${s.duedate || ''}</td>
        <td>${Number(s.outstandingamt || 0).toLocaleString()}</td>
        <td><input type="number" step="0.01" class="form-control form-control-sm" style="width:110px" value="${s.outstandingamt || 0}" data-sch-amt="${s.fin_payment_schedule_id}"></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    if (window.showAlert) showAlert(err.message || 'Không tải được lịch thanh toán', 'danger');
  }
}

async function loadPayPayments() {
  try {
    const data = await payFetchJSON('/api/payments?limit=50');
    const tbody = pay$('#payListBody');
    tbody.innerHTML = '';
    (data.payments || []).forEach((p) => {
      const badge = p.isreceipt === 'Y' ? 'badge bg-success' : 'badge bg-danger';
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${p.documentno || ''}</td>
        <td>${p.bpartner_name || ''}</td>
        <td><span class="${badge}">${p.payment_type || ''}</span></td>
        <td>${p.paymentdate || ''}</td>
        <td>${Number(p.amount || 0).toLocaleString()} ${p.currency || ''}</td>
        <td>${p.status || ''}</td>
        <td>${p.payment_method || ''}</td>
        <td class="d-flex gap-1">
          <button class="btn btn-sm btn-outline-success" data-pay-process="${p.fin_payment_id}">Process</button>
          <button class="btn btn-sm btn-outline-danger" data-pay-void="${p.fin_payment_id}">Void</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    if (window.showAlert) showAlert(err.message || 'Không tải được payments', 'danger');
  }
}

async function loadPayInvoices() {
  try {
    const data = await payFetchJSON('/api/invoices?pending_payment=true&limit=50');
    const tbody = pay$('#payInvoiceBody');
    tbody.innerHTML = '';
    (data.invoices || []).forEach((i) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${i.documentno || ''}</td>
        <td>${i.bpartner_name || ''}</td>
        <td>${i.invoice_type || ''}</td>
        <td>${i.dateinvoiced || ''}</td>
        <td>${Number(i.grandtotal || 0).toLocaleString()} ${i.currency || ''}</td>
        <td>${Number(i.outstanding_amount || 0).toLocaleString()}</td>
        <td>${i.docstatus || ''}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    if (window.showAlert) showAlert(err.message || 'Không tải được invoices', 'danger');
  }
}

async function submitPayment(evt) {
  evt.preventDefault();
  const btn = evt.submitter || pay$('#paymentForm button[type="submit"]');
  if (btn) btn.disabled = true;
  try {
    const payload = {
      fin_financial_account_id: pay$('#payAccount').value,
      c_bpartner_id: pay$('#payBpartner').value.trim(),
      fin_paymentmethod_id: pay$('#payMethod').value,
      amount: Number(pay$('#payAmount').value || 0),
      isreceipt: pay$('#payType').value === 'in',
      paymentdate: pay$('#payDate').value,
      description: pay$('#payDesc').value,
      referenceno: pay$('#payRef').value,
      schedules: []
    };
    payScheduleCache.forEach((s) => {
      const ck = document.querySelector(`[data-sch='${s.fin_payment_schedule_id}']`);
      const amtInput = document.querySelector(`[data-sch-amt='${s.fin_payment_schedule_id}']`);
      if (ck && ck.checked) {
        const amt = Number(amtInput?.value || 0);
        if (amt > 0) payload.schedules.push({ fin_payment_schedule_id: s.fin_payment_schedule_id, amount: amt });
      }
    });
    if (!payload.amount || payload.amount <= 0) throw new Error('Số tiền phải > 0');
    const res = await payFetchJSON('/api/payment', { method: 'POST', body: JSON.stringify(payload) });
    if (window.showAlert) showAlert(`Tạo payment thành công: ${res.payment.documentno}`, 'success');
    await refreshPaymentData();
  } catch (err) {
    if (window.showAlert) showAlert(err.message || 'Tạo payment thất bại', 'danger');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function onPaymentAction(evt) {
  const pidProcess = evt.target.dataset.payProcess;
  const pidVoid = evt.target.dataset.payVoid;
  if (!pidProcess && !pidVoid) return;
  evt.preventDefault();
  const btn = evt.target;
  btn.disabled = true;
  try {
    if (pidProcess) {
      await payFetchJSON(`/api/payment/${pidProcess}/process`, { method: 'POST' });
      if (window.showAlert) showAlert('Đã process payment', 'success');
    } else if (pidVoid) {
      await payFetchJSON(`/api/payment/${pidVoid}/void`, { method: 'POST' });
      if (window.showAlert) showAlert('Đã void payment', 'info');
    }
    await refreshPaymentData();
  } catch (err) {
    if (window.showAlert) showAlert(err.message || 'Thao tác thất bại', 'danger');
  } finally {
    btn.disabled = false;
  }
}

async function refreshPaymentData() {
  await Promise.all([
    loadPayStats(),
    loadPayAccounts(),
    loadPayMethods(),
    loadPaySchedules(),
    loadPayPayments(),
    loadPayInvoices()
  ]);
}

function setupPaymentHandlers() {
  const form = pay$('#paymentForm');
  if (form) form.addEventListener('submit', submitPayment);
  const list = pay$('#payListBody');
  if (list) list.addEventListener('click', onPaymentAction);
}

function initPaymentTabOnce() {
  if (paymentLoadedOnce) return;
  paymentLoadedOnce = true;
  setupPaymentHandlers();
  refreshPaymentData();
}

// Expose to inline script - keep reference to original function to avoid infinite recursion
const _originalRefreshPaymentData = refreshPaymentData;
window.refreshPaymentData = function () {
  initPaymentTabOnce();
  return _originalRefreshPaymentData();
};
