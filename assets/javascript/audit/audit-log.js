/* globals gettext, interpolate */
import { AuditApi } from 'api-client';

import { apiJson, getApiConfiguration } from '../api';
import { readBook } from '../common/book';

/**
 * The audit log page (`templates/audit/audit_log.html`): a page of the book's
 * events from `GET audit/api/events/` (`AuditApi.auditEventsList`), filtered by
 * event type, with previous/next pages. Event labels are the filter's own
 * options. Every value is set as text: names and metadata come from users and
 * imports, so none of it may be read as HTML.
 */
const book = readBook();
const api = new AuditApi(getApiConfiguration(window.location.origin));

const tbody = document.getElementById('audit-log-tbody');
const prevBtn = document.getElementById('audit-prev');
const nextBtn = document.getElementById('audit-next');
const pageInfo = document.getElementById('audit-page-info');
const pagination = document.getElementById('audit-pagination');
const filterType = document.getElementById('audit-filter-type');
const filterClear = document.getElementById('audit-filter-clear');

const labels = Object.fromEntries([...filterType.options].filter((o) => o.value).map((o) => [o.value, o.text]));

let page = 1;
let request = 0;

function cell(text, className = '') {
  const td = document.createElement('td');
  if (className) td.className = className;
  td.textContent = text;
  return td;
}

function messageRow(text, className) {
  const tr = document.createElement('tr');
  const td = cell(text, `text-center py-8 ${className}`);
  td.colSpan = 4;
  tr.append(td);
  tbody.replaceChildren(tr);
}

function formatMetadata(meta) {
  if (!meta || !Object.keys(meta).length) return '—';
  return Object.entries(meta)
    .map(([key, value]) => `${key}: ${typeof value === 'object' && value !== null ? JSON.stringify(value) : value}`)
    .join(', ');
}

function renderRows(events) {
  if (!events.length) {
    messageRow(gettext('No events found.'), 'text-base-content/70');
    return;
  }
  tbody.replaceChildren(
    ...events.map((event) => {
      const tr = document.createElement('tr');
      const badgeCell = document.createElement('td');
      const badge = document.createElement('span');
      badge.className = 'badge badge-sm badge-ghost';
      badge.textContent = labels[event.event_type] || event.event_type;
      badgeCell.append(badge);
      tr.append(
        cell(new Date(event.timestamp).toLocaleString(), 'whitespace-nowrap text-sm'),
        cell(event.user_display, 'text-sm'),
        badgeCell,
        cell(formatMetadata(event.metadata), 'text-sm text-base-content/70'),
      );
      return tr;
    }),
  );
}

async function load() {
  const ticket = ++request;
  messageRow(gettext('Loading…'), 'text-base-content/70');
  try {
    const data = await apiJson(
      api.auditEventsListRaw({ ...book.params, page, eventType: filterType.value || undefined }),
    );
    if (ticket !== request) return;
    renderRows(data.results || []);
    prevBtn.disabled = !data.previous;
    nextBtn.disabled = !data.next;
    const count = data.count || 0;
    pageInfo.textContent = count ? interpolate(gettext('%s events'), [count]) : '';
    pagination.style.removeProperty('display');
  } catch {
    if (ticket === request) messageRow(gettext('Failed to load events.'), 'text-error');
  }
}

filterType.addEventListener('change', () => {
  filterClear.classList.toggle('hidden', !filterType.value);
  page = 1;
  load();
});

filterClear.addEventListener('click', () => {
  filterType.value = '';
  filterClear.classList.add('hidden');
  page = 1;
  load();
});

prevBtn.addEventListener('click', () => {
  if (page > 1) {
    page -= 1;
    load();
  }
});
nextBtn.addEventListener('click', () => {
  page += 1;
  load();
});

load();
