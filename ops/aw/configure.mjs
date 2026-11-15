import { readFile } from 'node:fs/promises';

const base = new URL(process.env.AW_BASE_URL ?? 'https://aw-demo.ru');
if (base.protocol !== 'https:' && !['localhost', '127.0.0.1'].includes(base.hostname)) {
  throw new Error('AW_BASE_URL must use HTTPS outside localhost');
}
if (base.username || base.password) throw new Error('Do not include credentials in AW_BASE_URL');
const token = process.env.AW_TOKEN?.trim().replace(/^Bearer\s+/i, '');
if (!token) throw new Error('AW_TOKEN is required');

function id(name, fallback) {
  const value = Number(process.env[name] ?? fallback);
  if (!Number.isSafeInteger(value) || value < 1) throw new Error(`Invalid ${name}`);
  return value;
}

const modelId = id('AW_MODEL_ID', 32036);
const objectId = id('AW_MODEL_OBJECT_ID', 114233);
const sourceId = id('AW_SOURCE_ID', 33540);
const widgets = {
  reasons: id('AW_REASONS_WIDGET_ID', 93512),
  autonomous: id('AW_AUTONOMOUS_WIDGET_ID', 93513),
  firstAnswer: id('AW_FIRST_ANSWER_WIDGET_ID', 93514),
  topics: id('AW_TOPICS_WIDGET_ID', 93515),
};

async function api(path, body, method = body === undefined ? 'GET' : 'POST') {
  const response = await fetch(new URL(`/api/${path}`, base), {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(60_000),
  });
  if (!response.ok) throw new Error(`${method} ${path}: HTTP ${response.status}`);
  const result = await response.json();
  if (!result.success) throw new Error(`${method} ${path}: ${result.error?.message ?? 'AW error'}`);
  return result.data;
}

const source = await api(`model-object/view?id=${objectId}`);
if (source.model_id !== modelId || source.type !== 'sql') throw new Error('Unexpected AW model object');
const keys = [
  'name', 'columns', 'rows', 'invisible_fields_filter', 'settings', 'type', 'common_filter',
  'model_id', 'map_region', 'html_code', 'indicator', 'field_aliases',
];
const current = new Map();
for (const widgetId of Object.values(widgets)) {
  const widget = await api(`widget/view?id=${widgetId}`);
  if (widget.model_id !== modelId) throw new Error(`Widget ${widgetId} belongs to another model`);
  current.set(widgetId, widget);
}

const sql = (await readFile(new URL('./requests.sql', import.meta.url), 'utf8')).trim().replace(/;$/, '');
const summary = await api('model-object/sql-data', {
  data_source_id: sourceId,
  query: `SELECT count(*) AS total, count(*) FILTER (WHERE kb_search_count IS NOT NULL) AS covered, count(*) FILTER (WHERE category_id IS NOT NULL) AS categorized FROM (${sql}) AS requests`,
});
console.log('Source coverage:', summary);
await api(`model-object/update?id=${objectId}`, {
  state: source.state,
  type: source.type,
  alias: source.alias,
  sql_text: sql,
  model_id: modelId,
  parent_id: source.parent_id,
  model_data_source_id: source.model_data_source_id,
}, 'PUT');

function payload(widgetId) {
  const widget = current.get(widgetId);
  const result = Object.fromEntries(keys.map((key) => [key, structuredClone(widget[key])]));
  result.html_code = structuredClone(widget.html_code?.dev ?? { html: '', css: '', js: '' });
  return result;
}

function field(name, aggregate) {
  return { field: name, type: 'field', aggregate: { type: aggregate } };
}

function group(name) {
  return { field: name, type: 'field', group_type: 'row' };
}

function kpi(widgetId, name, title, subtitle, columns, aliases, color, background) {
  const p = payload(widgetId);
  p.name = name;
  p.type = 'kpi';
  p.columns = columns;
  p.rows = [group('request_count')];
  p.common_filter = '';
  p.invisible_fields_filter = [];
  p.indicator = [];
  p.html_code = { html: '', css: '', js: '' };
  p.field_aliases = aliases;
  p.settings.header.enable = true;
  p.settings.kpi.header.title.text = title;
  p.settings.kpi.header.subtitle = {
    ...p.settings.kpi.header.subtitle, enable: true, text: subtitle,
  };
  p.settings.kpi.background.type = 'solid';
  p.settings.kpi.background.color = background;
  p.settings.kpi.border.color = color;
  const template = p.settings.kpi.aggregate[0];
  p.settings.kpi.aggregate = columns.map((column, index) => ({
    ...template,
    aggregates: [column.field],
    title_enable: columns.length > 1,
    value_font_color: index === 0 ? color : '#64748B',
    value_font_size: index === 0 ? 40 : 20,
    value_empty: 'Нет данных',
  }));
  return p;
}

const autonomous = kpi(
  widgets.autonomous, 'БАРС — обслуживание без оператора (%)', 'Без оператора, %',
  'Подтверждённые решения · от всех обращений', [field('bot_resolved_percent', 'AVG')],
  { bot_resolved_percent: 'Подтверждено без оператора, %' }, '#15803D', '#F0FDF4',
);
autonomous.settings.info = {
  enable: true,
  text: 'Подтверждено (confirmed), без handoff / все обращения, включая открытые. Благодарности и отсутствие оценки не считаются confirmed.',
};

const firstAnswer = kpi(
  widgets.firstAnswer, 'БАРС — решения с одного запроса в БЗ (%)', 'С одного запроса в БЗ, %',
  'Подтверждённое решение после одного поиска',
  [field('first_kb_search_resolved_percent', 'AVG'), field('kb_search_coverage_percent', 'AVG')],
  {
    first_kb_search_resolved_percent: 'Решено с одного поиска, %',
    kb_search_coverage_percent: 'Полнота учёта поисков, %',
  }, '#2563EB', '#EFF6FF',
);
firstAnswer.settings.info = {
  enable: true,
  text: 'Подтверждено (confirmed), ровно один вызов /internal/rag/search, без handoff. Каждый поиск split и повторная попытка считаются отдельно; попадание в кэш тоже считается запросом. Число сообщений и уточнений не влияет. Старые обращения с неизвестным счётчиком исключены, открытые с известным — включены.',
};

const reasons = payload(widgets.reasons);
reasons.name = 'БАРС — причины эскалаций';
reasons.type = 'bar';
reasons.rows = [group('close_reason_label')];
reasons.columns = [field('request_count', 'SUM')];
reasons.columns[0].aggregate.colors = [{
  type: 'diagram', value: 'full', ignore_filter: false,
  groups: [{ conditions: [{ field: 'request_count', color: ['#F59E0B'] }] }],
}];
reasons.common_filter = "[close_reason] != 'confirmed' AND [close_reason] != 'spam' AND [close_reason] != 'reset'";
reasons.invisible_fields_filter = [];
reasons.field_aliases = { request_count: 'Обращения', close_reason_label: 'Причина' };
reasons.settings.info = {
  enable: true,
  text: 'Все причины закрытия кроме confirmed, spam и reset, включая таймауты. Spam хранится в БД, но исключён из этого виджета. Открытые обращения без причины исключены. Не равно числу доставленных оператору тикетов.',
};
reasons.indicator = reasons.indicator.map((item) => ({ ...item, model_name: 'request_count' }));
reasons.settings.labels = reasons.settings.labels.map((item) => ({ ...item, indicators: ['request_count'] }));

const topics = payload(widgets.topics);
topics.name = 'БАРС — темы, требующие оператора';
topics.type = 'table';
topics.rows = [group('topic')];
topics.columns = [field('request_count', 'SUM'), field('escalation_count', 'SUM'), field('escalation_percent', 'AVG')];
topics.common_filter = '';
topics.invisible_fields_filter = [];
topics.indicator = [];
topics.field_aliases = {
  topic: 'Тема', request_count: 'Все обращения', escalation_count: 'К оператору', escalation_percent: 'Доля передач, %',
};
topics.settings.info = {
  enable: true,
  text: 'Тема из category_id, заполняемого классификатором при финализации. Старые и ещё не классифицированные обращения остаются в «Тема не указана». Передачи считаются по handoff, а не по всем причинам кроме confirmed.',
};
topics.settings.table.total_row_enable = false;
topics.settings.table.row_grid_lines_alternation = true;
topics.settings.table.data_aggregate_font_color = '#B45309';

for (const [widgetId, p] of [
  [widgets.autonomous, autonomous], [widgets.firstAnswer, firstAnswer],
  [widgets.reasons, reasons], [widgets.topics, topics],
]) {
  await api(`widget/update?id=${widgetId}`, p, 'PUT');
  console.log(`Updated widget ${widgetId}`);
}
await api(`model/migrate-data?id=${modelId}`);
console.log('Model reload requested. Verify completion in AW before checking widget values.');
