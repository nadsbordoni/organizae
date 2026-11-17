import { addDays, freeWindows, scheduleFor, toClock, toMinutes, weekdayOf } from './agenda';
import { change, money } from './finance';
import type { Range } from './finance';
import type { ClientSummary } from './clients';
import type { Agenda, IsoDate } from '@/types/agenda';
import type { AppointmentRow, FinancialEntryRow } from '@/types/painel';

/**
 * Leituras dos Insights. Os alertas seguem as regras de `GET /financial/insights` da API (branch
 * `feat/assistant-insights`): queda de receita abaixo de 80%, despesas acima de 120%, resultado
 * negativo e despesas vencidas, recebidos e pagos pelo dia do pagamento.
 */

export interface Alert {
  severity: 'WARNING' | 'CRITICAL';
  title: string;
  description: string;
}

const paidIn = (entries: FinancialEntryRow[], range: Range, type: FinancialEntryRow['type']) =>
  entries
    .filter((e) => e.type === type && e.status === 'PAID' && e.paid_on! >= range.from && e.paid_on! <= range.to)
    .reduce((sum, e) => sum + e.amount_cents, 0);

export function financialAlerts(entries: FinancialEntryRow[], current: Range, previous: Range, today: IsoDate): Alert[] {
  const income = paidIn(entries, current, 'INCOME');
  const incomeBefore = paidIn(entries, previous, 'INCOME');
  const out = paidIn(entries, current, 'EXPENSE');
  const outBefore = paidIn(entries, previous, 'EXPENSE');
  const overdue = entries.filter((e) => e.type === 'EXPENSE' && e.status === 'PENDING' && e.due_date < today);
  const alerts: Alert[] = [];

  if (out > income && income > 0) {
    alerts.push({
      severity: 'CRITICAL',
      title: 'Atenção: saiu mais dinheiro do que entrou',
      description: `Recebido ${money(income)}, pago ${money(out)} no período. O resultado realizado ficou em ${money(income - out)}.`,
    });
  }
  if (income > 0 && incomeBefore > 0 && income < incomeBefore * 0.8) {
    alerts.push({
      severity: 'WARNING',
      title: `Atenção: queda de ${change(income, incomeBefore)?.slice(1)} na receita recebida`,
      description: `${money(income)} recebidos contra ${money(incomeBefore)} no mesmo trecho do mês anterior.`,
    });
  }
  if (outBefore > 0 && out > outBefore * 1.2) {
    alerts.push({
      severity: 'WARNING',
      title: `Atenção: despesas ${change(out, outBefore)} acima do mês anterior`,
      description: `${money(out)} pagos contra ${money(outBefore)} no mesmo trecho do mês anterior.`,
    });
  }
  if (overdue.length) {
    const total = overdue.reduce((sum, e) => sum + e.amount_cents, 0);
    const oldest = [...overdue].sort((a, b) => a.due_date.localeCompare(b.due_date))[0]!;
    alerts.push({
      severity: 'WARNING',
      title: `Atenção: ${overdue.length === 1 ? '1 despesa vencida' : `${overdue.length} despesas vencidas`}`,
      description: `${overdue.map((e) => e.description).join(', ')}: ${money(total)} em aberto desde ${oldest.due_date.split('-').reverse().slice(0, 2).join('/')}.`,
    });
  }
  return alerts;
}

export interface QuietDay {
  date: IsoDate;
  /** De 0 a 100. */
  occupancy: number;
  /** Janelas livres do dia, em minutos. */
  windows: Array<{ from: string; to: string; minutes: number }>;
}

/** O dia com menos ocupação entre os próximos `days` dias de atendimento. */
export function quietestDay(agenda: Agenda, rows: AppointmentRow[], today: IsoDate, days = 7): QuietDay | undefined {
  let best: QuietDay | undefined;
  for (let offset = 1; offset <= days; offset++) {
    const date = addDays(today, offset);
    const { hours } = scheduleFor(agenda, date);
    if (!hours || weekdayOf(date) === 'sun') continue;
    const busy = rows
      .filter((r) => r.date === date && r.status !== 'cancelled')
      .map((r) => ({ from: r.start_time, to: toClock(toMinutes(r.start_time) + r.duration_min) }));
    const open = freeWindows(hours).reduce((sum, [a, b]) => sum + (b - a), 0);
    const free = freeWindows(hours, busy).filter(([a, b]) => b - a >= 30);
    const freeMinutes = free.reduce((sum, [a, b]) => sum + (b - a), 0);
    const occupancy = open ? Math.round(((open - freeMinutes) / open) * 100) : 100;
    if (!best || occupancy < best.occupancy) {
      best = { date, occupancy, windows: free.map(([a, b]) => ({ from: toClock(a), to: toClock(b), minutes: b - a })) };
    }
  }
  return best;
}

/** Quem mais gastou, para o convite de retorno; a ausente de maior valor ganha a abordagem de recuperação. */
export function highValue(summaries: ClientSummary[], count = 3) {
  return [...summaries].sort((a, b) => (b.spentCents ?? 0) - (a.spentCents ?? 0)).slice(0, count);
}

/** Ausentes há mais de 60 dias e, entre eles, quem autorizou mensagens. */
export function recoveryAudience(summaries: ClientSummary[]) {
  const away = summaries
    .filter((s) => s.status === 'away')
    .sort((a, b) => (a.daysAway ?? Infinity) - (b.daysAway ?? Infinity));
  return { away, eligible: away.filter((s) => s.client.whatsapp_opt_in) };
}


/** Mensagem inicial da campanha de recuperação. `{primeiro_nome}` vira o nome de cada cliente na prévia. */
export const recoveryMessage = (business: string, link: string) =>
  `Olá, {primeiro_nome}! Faz um tempinho que não nos vemos. Que tal reservar um momento para cuidar de você? Veja os serviços e horários: ${link}. Se preferir não receber novidades, responda SAIR. Com carinho, ${business}.`;

/** Quem entra na campanha: as clientes marcadas na tela de ausentes (`?clientes=`), ou todas as elegíveis. */
export function pickRecipients(eligible: ClientSummary[], ids: string | null) {
  const wanted = new Set((ids ?? '').split(',').filter(Boolean));
  return wanted.size ? eligible.filter((s) => wanted.has(s.client.id)) : eligible;
}
