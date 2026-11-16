import { addDays, parsePrice } from './agenda';
import { serviceIds } from './painel';
import type { Agenda, IsoDate } from '@/types/agenda';
import type { AppointmentRow, FinancialCategoryRow, FinancialEntryRow } from '@/types/painel';

/**
 * Contas do Financeiro, no mesmo espírito dos relatórios da API (`/financial/summary`,
 * `/financial/reports/*`): resultado pela competência, caixa pelo dia do pagamento, cancelados fora.
 */

export interface Range {
  from: IsoDate;
  to: IsoDate;
}

export interface Period extends Range {
  /** Mês corrente: o mesmo trecho do mês anterior (1 a 16 de novembro contra 1 a 16 de outubro). Mês fechado: o anterior inteiro. */
  previous: Range;
  /** 'AAAA-MM'. */
  key: string;
}

const at = (date: IsoDate) => new Date(`${date}T12:00:00Z`);
const lastDay = (key: string) => {
  const [year, month] = key.split('-').map(Number) as [number, number];
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
};
const monthKey = (date: IsoDate, offset = 0) => {
  const [year, month] = date.split('-').map(Number) as [number, number];
  return new Date(Date.UTC(year, month - 1 + offset, 1)).toISOString().slice(0, 7);
};

/** Mês escolhido (`?mes=AAAA-MM`) ou o atual; o atual vai até hoje, e a comparação até o mesmo dia. */
export function periodFor(requested: string | null, today: IsoDate, options: string[]): Period {
  const key = requested && options.includes(requested) ? requested : monthKey(today);
  const current = key === monthKey(today);
  const day = current ? Number(today.slice(8, 10)) : lastDay(key);
  const previousKey = monthKey(`${key}-01`, -1);
  return {
    key,
    from: `${key}-01`,
    to: current ? today : `${key}-${String(day).padStart(2, '0')}`,
    previous: {
      from: `${previousKey}-01`,
      to: `${previousKey}-${String(current ? Math.min(day, lastDay(previousKey)) : lastDay(previousKey)).padStart(2, '0')}`,
    },
  };
}

/** O mês inteiro do período, para listas e contas a vencer: o período do mês corrente para em hoje. */
export const wholeMonth = (period: Period): Range => ({ from: period.from, to: `${period.key}-${String(lastDay(period.key)).padStart(2, '0')}` });

/** Os últimos `count` meses, do atual para trás: '2026-11'. */
export const monthOptions = (today: IsoDate, count: number) =>
  Array.from({ length: count }, (_, i) => monthKey(today, -i));

const long = (date: IsoDate, parts: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat('pt-BR', { ...parts, timeZone: 'UTC' }).format(at(date));

/** 'Novembro de 2026'. */
export function monthTitle(key: string): string {
  const text = long(`${key}-01`, { month: 'long', year: 'numeric' });
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}`;
}

/** 'Out', para as comparações curtas dos cartões. */
export function monthShort(date: IsoDate): string {
  const text = long(date, { month: 'short' }).replace('.', '');
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}`;
}

/** '01 a 16 de novembro de 2026'. */
export function rangeLabel({ from, to }: Range): string {
  return `${from.slice(8, 10)} a ${to.slice(8, 10)} de ${long(to, { month: 'long', year: 'numeric' })}`;
}

/** 'R$ 21.430': nos painéis os centavos só ocupam espaço. */
export const money = (cents: number) =>
  `${cents < 0 ? '−' : ''}R$ ${Math.round(Math.abs(cents) / 100).toLocaleString('pt-BR')}`;

/** '49,5%'; negativo com o sinal de menos tipográfico, como o dinheiro. */
export const percent = (value: number, digits = 1) =>
  `${value < 0 ? '−' : ''}${Math.abs(value).toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;

/** Variação com sinal: '+12,4%' ou '−3,1%'. `undefined` quando não há base para comparar. */
export function change(current: number, previous: number): string | undefined {
  if (!previous) return undefined;
  const value = ((current - previous) / Math.abs(previous)) * 100;
  return `${value >= 0 ? '+' : '−'}${percent(Math.abs(value))}`;
}

/** Diferença entre duas porcentagens, em pontos: '+2,4 p.p.'. */
export function pointsChange(current: number | undefined, previous: number | undefined): string | undefined {
  if (current === undefined || previous === undefined) return undefined;
  const value = current - previous;
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} p.p.`;
}

/** Diferença em reais com sinal: '+R$ 2.365'. */
export const moneyChange = (current: number, previous: number) =>
  `${current >= previous ? '+' : '−'}${money(Math.abs(current - previous))}`;

const inRange = (date: string | null, range: Range): date is string => !!date && date >= range.from && date <= range.to;
const sum = (entries: FinancialEntryRow[]) => entries.reduce((total, e) => total + e.amount_cents, 0);
const active = (entries: FinancialEntryRow[]) => entries.filter((e) => e.status !== 'CANCELLED');

export type Groups = Map<string, FinancialCategoryRow['group']>;
export const groupsOf = (categories: FinancialCategoryRow[]): Groups => new Map(categories.map((c) => [c.id, c.group]));

export interface Result {
  income: number;
  expenses: number;
  taxes: number;
  /** Despesas sem os impostos. */
  costs: number;
  fixed: number;
  result: number;
  /** De 0 a 100; `undefined` sem receita. */
  margin: number | undefined;
}

/** Resultado pela competência: o atendimento de hoje pago no cartão em 30 dias é receita de hoje. */
export function resultOf(entries: FinancialEntryRow[], range: Range, groups: Groups): Result {
  const inPeriod = active(entries).filter((e) => inRange(e.competence, range));
  const income = sum(inPeriod.filter((e) => e.type === 'INCOME'));
  const outgoing = inPeriod.filter((e) => e.type === 'EXPENSE');
  const expenses = sum(outgoing);
  const taxes = sum(outgoing.filter((e) => groups.get(e.category_id) === 'tax'));
  const fixed = sum(outgoing.filter((e) => groups.get(e.category_id) === 'fixed'));
  const result = income - expenses;
  return { income, expenses, taxes, costs: expenses - taxes, fixed, result, margin: income ? (result / income) * 100 : undefined };
}

export interface Cash {
  opening: number;
  received: number;
  paid: number;
  closing: number;
  /** Receitas do período ainda não recebidas, e despesas ainda não pagas. */
  receivable: number;
  payable: number;
  receivableCount: number;
}

/** Caixa pelo dia do pagamento: é o dinheiro que entrou e saiu, não o lucro. */
export function cashOf(entries: FinancialEntryRow[], range: Range, openingBalance: number): Cash {
  const paid = entries.filter((e) => e.status === 'PAID');
  const before = paid.filter((e) => e.paid_on! < range.from);
  const opening = openingBalance + sum(before.filter((e) => e.type === 'INCOME')) - sum(before.filter((e) => e.type === 'EXPENSE'));
  const now = paid.filter((e) => inRange(e.paid_on, range));
  const received = sum(now.filter((e) => e.type === 'INCOME'));
  const out = sum(now.filter((e) => e.type === 'EXPENSE'));
  const pending = entries.filter((e) => e.status === 'PENDING' && inRange(e.competence, range));
  const receivable = pending.filter((e) => e.type === 'INCOME');
  return {
    opening,
    received,
    paid: out,
    closing: opening + received - out,
    receivable: sum(receivable),
    payable: sum(pending.filter((e) => e.type === 'EXPENSE')),
    receivableCount: receivable.length,
  };
}

/** Pedaços de `size` dias a partir do primeiro dia do período: '01–07', '08–14'… */
export function slices(range: Range, size: number): Range[] {
  const out: Range[] = [];
  for (let from = range.from; from <= range.to; from = addDays(from, size)) {
    const to = addDays(from, size - 1);
    out.push({ from, to: to > range.to ? range.to : to });
  }
  return out;
}

/** Entradas e saídas de cada pedaço: pelo pagamento (`cash`) ou pela competência. */
export function flowBy(entries: FinancialEntryRow[], ranges: Range[], basis: 'cash' | 'result') {
  const valid = basis === 'cash' ? entries.filter((e) => e.status === 'PAID') : active(entries);
  const dateOf = (e: FinancialEntryRow) => (basis === 'cash' ? e.paid_on : e.competence);
  return ranges.map((range) => {
    const inside = valid.filter((e) => inRange(dateOf(e), range));
    return {
      range,
      income: sum(inside.filter((e) => e.type === 'INCOME')),
      expenses: sum(inside.filter((e) => e.type === 'EXPENSE')),
    };
  });
}

/** Total de cada grupo de categoria no período, pela competência. */
export function totalsByGroup(entries: FinancialEntryRow[], range: Range, groups: Groups) {
  const totals = new Map<FinancialCategoryRow['group'], number>();
  for (const e of active(entries)) {
    if (!inRange(e.competence, range)) continue;
    const group = groups.get(e.category_id);
    if (group) totals.set(group, (totals.get(group) ?? 0) + e.amount_cents);
  }
  return totals;
}

/**
 * Faturamento que cobre os custos fixos do mês inteiro (`month`), dada a margem que sobra depois dos
 * custos variáveis e impostos no período. `reachedOn`: o dia em que a receita acumulada passou dele.
 */
export function breakEven(entries: FinancialEntryRow[], range: Range, month: Range, groups: Groups) {
  const { income, expenses } = resultOf(entries, range, groups);
  const fixedInPeriod = resultOf(entries, range, groups).fixed;
  const { fixed } = resultOf(entries, month, groups);
  const contribution = income ? 1 - (expenses - fixedInPeriod) / income : 0;
  if (contribution <= 0) return undefined;
  const target = Math.round(fixed / contribution);
  let total = 0;
  let reachedOn: IsoDate | undefined;
  const incomes = active(entries)
    .filter((e) => e.type === 'INCOME' && inRange(e.competence, range))
    .sort((a, b) => a.competence.localeCompare(b.competence));
  for (const e of incomes) {
    total += e.amount_cents;
    if (total >= target) {
      reachedOn = e.competence;
      break;
    }
  }
  return { target, reachedOn };
}


export interface ServiceShare {
  id: string;
  name: string;
  count: number;
  cents: number;
  /** De 0 a 100: o que sobra do preço depois do material e do imposto. */
  margin: number;
}

/** Valor agendado de cada serviço no período e a margem estimada com o custo de material de cada um. */
export function serviceShares(
  rows: AppointmentRow[],
  agenda: Agenda | undefined,
  costs: Record<string, number>,
  taxRate: number,
): ServiceShare[] {
  const catalog = new Map((agenda?.categories ?? []).flatMap((c) => c.services.map((s) => [s.id, s] as const)));
  const shares = new Map<string, ServiceShare>();
  for (const row of rows) {
    if (row.status === 'cancelled') continue;
    for (const id of serviceIds(row) ?? []) {
      const service = catalog.get(id);
      const price = parsePrice(service?.price);
      if (!service || price === undefined) continue;
      const share = shares.get(id) ?? {
        id,
        name: service.name,
        count: 0,
        cents: 0,
        margin: ((price - (costs[id] ?? 0) - price * taxRate) / price) * 100,
      };
      share.count += 1;
      share.cents += price;
      shares.set(id, share);
    }
  }
  return [...shares.values()].sort((a, b) => b.cents - a.cents);
}

/** 'outubro'. */
export const monthName = (date: IsoDate) => long(date, { month: 'long' });

/** Situação como a dona do negócio fala: "Pago", "A vencer", "Agendado", "Vencido"… */
export function entryStatus(entry: FinancialEntryRow, today: IsoDate): string {
  const income = entry.type === 'INCOME';
  if (entry.status === 'CANCELLED') return 'Cancelado';
  if (entry.status === 'PAID') return income ? 'Recebido' : 'Pago';
  if (entry.scheduled) return 'Agendado';
  if (entry.due_date < today) return 'Vencido';
  return income ? 'A receber' : 'A vencer';
}

const METHOD: Record<NonNullable<FinancialEntryRow['payment_method']>, string> = {
  pix: 'Pix',
  card: 'Cartão',
  cash: 'Dinheiro',
  boleto: 'Boleto',
  debit: 'Débito automático',
};
export const methodLabel = (entry: FinancialEntryRow) => (entry.payment_method ? METHOD[entry.payment_method] : '');

/** O nome da cliente, quando a descrição segue o formato "Serviço · Cliente". */
export const counterpart = (entry: FinancialEntryRow) => entry.description.split(' · ').at(-1) ?? entry.description;

/** Linhas da planilha de lançamentos do período, com cabeçalho. */
export function entriesSheet(entries: FinancialEntryRow[], categories: FinancialCategoryRow[], today: IsoDate): string[][] {
  const names = new Map(categories.map((c) => [c.id, c.name]));
  return [
    ['Competência', 'Descrição', 'Categoria', 'Tipo', 'Valor', 'Vencimento', 'Situação', 'Pagamento', 'Nota fiscal'],
    ...entries.map((e) => [
      e.competence.split('-').reverse().join('/'),
      e.description,
      names.get(e.category_id) ?? '',
      e.type === 'INCOME' ? 'Receita' : 'Despesa',
      (e.amount_cents / 100).toLocaleString('pt-BR', { minimumFractionDigits: 2 }),
      e.due_date.split('-').reverse().join('/'),
      entryStatus(e, today),
      methodLabel(e),
      e.invoice ?? '',
    ]),
  ];
}

export const inPeriod = (entries: FinancialEntryRow[], range: Range) => entries.filter((e) => inRange(e.competence, range));
