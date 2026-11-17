import { getSite } from '@/config';
import { addDays, weekdayOf } from './agenda';
import { catalogCents, serviceNames } from './painel';
import type { IsoDate } from '@/types/agenda';
import type { AppointmentRow, FinancialCategoryRow, FinancialEntryRow, PaymentMethod } from '@/types/painel';

/**
 * Financeiro de DEMONSTRAÇÃO da Joana. As receitas de serviço saem dos atendimentos da agenda de
 * exemplo (como o `appointment_id` da API), para Agenda, Visão geral, Financeiro e Relatórios
 * contarem a mesma história. Sai quando os lançamentos vierem de `GET /financial-entries`.
 */

export const DEMO_CATEGORIES: FinancialCategoryRow[] = [
  { id: 'servicos', name: 'Serviços', type: 'INCOME', group: 'services' },
  { id: 'produtos', name: 'Produtos', type: 'INCOME', group: 'products' },
  { id: 'outras-receitas', name: 'Outras receitas', type: 'INCOME', group: 'other' },
  { id: 'insumos', name: 'Insumos', type: 'EXPENSE', group: 'variable' },
  { id: 'transporte', name: 'Transporte', type: 'EXPENSE', group: 'variable' },
  { id: 'divulgacao', name: 'Divulgação', type: 'EXPENSE', group: 'variable' },
  { id: 'equipamentos', name: 'Equipamentos', type: 'EXPENSE', group: 'variable' },
  { id: 'cursos', name: 'Cursos', type: 'EXPENSE', group: 'variable' },
  { id: 'pro-labore', name: 'Pró-labore', type: 'EXPENSE', group: 'fixed' },
  { id: 'estrutura', name: 'Estrutura', type: 'EXPENSE', group: 'fixed' },
  { id: 'software', name: 'Software', type: 'EXPENSE', group: 'fixed' },
  { id: 'impostos', name: 'Impostos', type: 'EXPENSE', group: 'tax' },
];

/** Caixa no primeiro dia dos dados, em centavos. A API ainda não tem conta de caixa nem saldo inicial. */
export const DEMO_OPENING_BALANCE = 250_000;

/** Custo de material por serviço, para a margem estimada. Também ainda não existe no back. */
export const DEMO_SERVICE_COSTS: Record<string, number> = {
  alongamento: 3_200,
  manutencao: 1_800,
  esmaltacao: 600,
  pedicure: 900,
};

/** Alíquota do Simples Nacional sobre o faturamento do mês anterior. */
export const DEMO_TAX_RATE = 0.06;

const MONTHLY: Array<{ day: number; description: string; category: string; cents: number; method: PaymentMethod }> = [
  { day: 3, description: 'Géis e esmaltes', category: 'insumos', cents: 68_000, method: 'card' },
  { day: 5, description: 'Sistema Organizaê', category: 'software', cents: 4_900, method: 'debit' },
  { day: 8, description: 'Contador', category: 'estrutura', cents: 18_000, method: 'boleto' },
  { day: 10, description: 'Celular e internet', category: 'estrutura', cents: 12_000, method: 'debit' },
  { day: 15, description: 'Seguro do carro', category: 'estrutura', cents: 16_000, method: 'boleto' },
  { day: 18, description: 'Lixas e descartáveis', category: 'insumos', cents: 24_000, method: 'pix' },
  // A retirada da dona sai no fim do mês, depois que o mês se pagou.
  { day: 28, description: 'Pró-labore da Joana', category: 'pro-labore', cents: 350_000, method: 'pix' },
];

const PRODUCTS = [
  { name: 'Óleo de cutícula', cents: 2_900 },
  { name: 'Base fortalecedora', cents: 3_500 },
  { name: 'Kit manutenção', cents: 5_900 },
  { name: 'Creme para mãos', cents: 4_200 },
];

/** Hash estável: o mesmo dia e o mesmo atendimento sempre caem na mesma forma de pagamento. */
function pick(seed: string, buckets: number): number {
  let hash = 0;
  for (const char of seed) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash % buckets;
}

const monthStart = (date: IsoDate) => `${date.slice(0, 8)}01`;

/** Primeiro dia do mês `offset` meses antes (negativo) ou depois do de `date`. */
export function shiftMonth(date: IsoDate, offset: number): IsoDate {
  const [year, month] = date.split('-').map(Number) as [number, number];
  const at = new Date(Date.UTC(year, month - 1 + offset, 1));
  return at.toISOString().slice(0, 10);
}

/** Primeiro dia dos dados: seis meses antes do mês de hoje. */
export const demoFinanceStart = (today: IsoDate) => shiftMonth(today, -6);

export function demoFinancialEntries(today: IsoDate, appointments: AppointmentRow[]): FinancialEntryRow[] {
  const agenda = getSite('exemplo')?.agenda;
  const entries: FinancialEntryRow[] = [];
  const settle = (due: IsoDate) => (due < today ? { status: 'PAID' as const, paid_on: due } : { status: 'PENDING' as const, paid_on: null });
  let invoice = 1200;

  for (const row of appointments) {
    if (row.status === 'cancelled') continue;
    const cents = catalogCents([row], agenda);
    if (!cents) continue;
    const done = row.status === 'done';
    // Pix e dinheiro entram no dia; cartão de crédito cai em 30 dias. É a diferença entre caixa e resultado.
    const method: PaymentMethod | null = done ? (['pix', 'pix', 'card', 'pix', 'cash', 'card'] as const)[pick(`${row.date}${row.start_time}`, 6)]! : null;
    const due = method === 'card' ? addDays(row.date, 30) : row.date;
    entries.push({
      id: `servico-${row.date}-${row.start_time}`,
      category_id: 'servicos',
      type: 'INCOME',
      description: `${serviceNames(row, agenda)} · ${row.client_name}`,
      amount_cents: cents,
      due_date: due,
      ...(done ? settle(due) : { status: 'PENDING' as const, paid_on: null }),
      appointment_id: row.id,
      competence: row.date,
      payment_method: method,
      invoice: done && pick(row.client_name + row.date, 10) < 7 ? `NFS-e ${invoice++}` : null,
      scheduled: false,
    });
  }

  const servicesByMonth = new Map<string, number>();
  for (const entry of entries) {
    if (entry.competence > today) continue;
    const key = entry.competence.slice(0, 7);
    servicesByMonth.set(key, (servicesByMonth.get(key) ?? 0) + entry.amount_cents);
  }

  for (let offset = -6; offset <= 0; offset++) {
    const first = shiftMonth(today, offset);
    const days = Number(addDays(shiftMonth(today, offset + 1), -1).slice(8, 10));
    const at = (day: number) => `${first.slice(0, 8)}${String(Math.min(day, days)).padStart(2, '0')}`;
    const expense = (id: string, day: number, description: string, category: string, cents: number, method: PaymentMethod) => {
      const due = at(day);
      // O contador deste mês ficou esquecido: é a conta vencida que o alerta dos Insights mostra.
      const forgotten = offset === 0 && id === 'estrutura8';
      entries.push({
        id: `${id}-${first.slice(0, 7)}`,
        category_id: category,
        type: 'EXPENSE',
        description,
        amount_cents: cents,
        due_date: due,
        ...(forgotten ? { status: 'PENDING' as const, paid_on: null } : settle(due)),
        appointment_id: null,
        competence: due,
        payment_method: method,
        invoice: null,
        scheduled: method === 'debit' && due >= today,
      });
    };

    for (const fixed of MONTHLY) expense(fixed.category + fixed.day, fixed.day, fixed.description, fixed.category, fixed.cents, fixed.method);

    // O DAS de um mês vence no dia 20 do seguinte, mas pela competência é imposto do mês da receita.
    const revenue = servicesByMonth.get(first.slice(0, 7));
    if (revenue) {
      const due = `${shiftMonth(today, offset + 1).slice(0, 8)}20`;
      entries.push({
        id: `das-${first.slice(0, 7)}`,
        category_id: 'impostos',
        type: 'EXPENSE',
        description: 'Simples Nacional (DAS)',
        amount_cents: Math.round(revenue * DEMO_TAX_RATE),
        due_date: due,
        ...settle(due),
        appointment_id: null,
        competence: first,
        payment_method: 'boleto',
        invoice: null,
        scheduled: false,
      });
    }
    if (offset % 2 === 0) expense('anuncio', 12, 'Anúncio no Instagram', 'divulgacao', 15_000, 'card');
    if (offset === -3) expense('cabine', 22, 'Cabine LED', 'equipamentos', 89_000, 'card');
    if (offset === -2) expense('curso', 9, 'Curso de nail art', 'cursos', 60_000, 'pix');

    for (let day = 1; day <= days; day++) {
      const date = at(day);
      if (date > addDays(today, 21)) break;
      if (weekdayOf(date) === 'mon') expense(`combustivel-${day}`, day, 'Combustível', 'transporte', 9_500, 'card');
    }

    for (const [index, day] of [6, 13, 21, 27].entries()) {
      const date = at(day);
      if (date >= today) continue;
      const product = PRODUCTS[(index + offset + 6) % PRODUCTS.length]!;
      entries.push({
        id: `produto-${date}`,
        category_id: 'produtos',
        type: 'INCOME',
        description: `Venda de ${product.name.toLowerCase()}`,
        amount_cents: product.cents * 3,
        due_date: date,
        status: 'PAID',
        paid_on: date,
        appointment_id: null,
        competence: date,
        payment_method: 'pix',
        invoice: null,
        scheduled: false,
      });
    }

    if (offset === -4 || offset === -1) {
      const date = at(26);
      entries.push({
        id: `workshop-${first.slice(0, 7)}`,
        category_id: 'outras-receitas',
        type: 'INCOME',
        description: 'Workshop de esmaltação',
        amount_cents: offset === -4 ? 45_000 : 52_000,
        due_date: date,
        ...settle(date),
        appointment_id: null,
        competence: date,
        payment_method: 'pix',
        invoice: `NFS-e ${invoice++}`,
        scheduled: false,
      });
    }
  }

  return entries.filter((e) => e.competence >= monthStart(demoFinanceStart(today)));
}

/**
 * O que a leitura de comprovante devolve na DEMONSTRAÇÃO, qualquer que seja a imagem. Com a API, vem
 * da IA do projeto: a imagem vai, os campos sugeridos voltam para a pessoa conferir.
 */
export function demoReceiptReading(type: 'INCOME' | 'EXPENSE', today: IsoDate) {
  return type === 'EXPENSE'
    ? { descricao: 'Géis e esmaltes · Distribuidora Bela Unha', valor: 'R$ 186,40', categoria: 'insumos', situacao: 'paid:card', competencia: today, pagamento: today }
    : { descricao: 'Workshop de esmaltação', valor: 'R$ 450,00', categoria: 'outras-receitas', situacao: 'paid:pix', competencia: today, pagamento: today };
}
