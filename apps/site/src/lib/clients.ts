import { dayNumber, formatPrice } from './agenda';
import { catalogCents, foldText, formatPhone, numericDate } from './painel';
import type { PanelTone } from './painel';
import type { IconName } from '@/types/blocks';
import type { Agenda, IsoDate } from '@/types/agenda';
import type { AppointmentRow, ClientRow } from '@/types/painel';

/** Sem atendimento há mais que isso, a pessoa conta como ausente. */
export const AWAY_AFTER_DAYS = 60;
/** Cadastro mais novo que isso conta como recente, mesmo sem atendimento. */
const NEW_FOR_DAYS = 30;

export type ClientStatus = 'regular' | 'new' | 'away';

/**
 * Sem gênero de propósito: o "Ativa"/"Nova" do protótipo erra com os clientes de uma barbearia.
 * Quem veio nos últimos 60 dias não ganha rótulo, só a data da visita: "Em dia" lembrava pagamento.
 */
export const CLIENT_STATUS: Record<ClientStatus, { label: string; tone: PanelTone; icon: IconName }> = {
  regular: { label: 'Última visita', tone: 'positive', icon: 'check-circle' },
  new: { label: 'Recente', tone: 'info', icon: 'sparkles' },
  away: { label: 'Ausente', tone: 'attention', icon: 'clock' },
};

export interface ClientSummary {
  client: ClientRow;
  status: ClientStatus;
  /** Atendimentos concluídos. */
  visits: number;
  /** `undefined` se algum serviço não tem preço legível. */
  spentCents: number | undefined;
  firstVisit?: IsoDate;
  lastVisit?: IsoDate;
  /** Dias desde o último atendimento. */
  daysAway?: number;
}

export const daysBetween = (from: IsoDate, to: IsoDate) => dayNumber(to) - dayNumber(from);

export function summarize(
  client: ClientRow,
  history: AppointmentRow[],
  today: IsoDate,
  agenda: Agenda | undefined,
): ClientSummary {
  const done = history.filter((row) => row.status === 'done');
  const dates = done.map((row) => row.date).sort();
  const lastVisit = dates.at(-1);
  const daysAway = lastVisit ? daysBetween(lastVisit, today) : undefined;

  let status: ClientStatus = 'regular';
  if (daysBetween(client.created_at.slice(0, 10), today) <= NEW_FOR_DAYS) status = 'new';
  else if (daysAway === undefined || daysAway > AWAY_AFTER_DAYS) status = 'away';

  return {
    client,
    status,
    visits: done.length,
    spentCents: catalogCents(done, agenda),
    firstVisit: dates[0],
    lastVisit,
    daysAway,
  };
}

const days = (n: number) => (n === 0 ? 'hoje' : `há ${n} ${n === 1 ? 'dia' : 'dias'}`);

/** A situação com o motivo: "Ausente há 82 dias", "Última visita há 14 dias", "Recente · cadastro há 3 dias". */
export function statusDetail(summary: ClientSummary, today: IsoDate): string {
  const { label } = CLIENT_STATUS[summary.status];
  if (summary.status === 'new') return `${label} · cadastro ${days(daysBetween(summary.client.created_at.slice(0, 10), today))}`;
  if (summary.daysAway === undefined) return `${label} · sem atendimentos`;
  return summary.status === 'away' ? `${label} há ${summary.daysAway} dias` : `${label} ${days(summary.daysAway)}`;
}

/** Nome sem acento nem caixa; telefone a partir de 3 dígitos. Com a API, vira o `?search=` de `GET /clients`. */
export function matchesSearch(client: ClientRow, query: string): boolean {
  const term = foldText(query);
  if (!term) return true;
  const digits = query.replace(/\D/g, '');
  return foldText(client.name).includes(term) || (digits.length >= 3 && client.phone.includes(digits));
}

/** Linhas da planilha de clientes, com cabeçalho. */
export function clientsSheet(rows: ClientSummary[], today: IsoDate): string[][] {
  return [
    ['Nome', 'Telefone', 'E-mail', 'Situação', 'Atendimentos', 'Valor total', 'Último atendimento'],
    ...rows.map((r) => [
      r.client.name,
      formatPhone(r.client.phone),
      r.client.email ?? '',
      statusDetail(r, today),
      String(r.visits),
      r.spentCents === undefined ? '' : formatPrice(r.spentCents),
      r.lastVisit ? numericDate(r.lastVisit) : '',
    ]),
  ];
}
