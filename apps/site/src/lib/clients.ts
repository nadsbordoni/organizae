import { dayNumber, formatPrice } from './agenda';
import { catalogCents, formatPhone, numericDate } from './painel';
import type { PanelTone } from './painel';
import type { IconName } from '@/types/blocks';
import type { Agenda, IsoDate } from '@/types/agenda';
import type { AppointmentRow, ClientRow } from '@/types/painel';

/** Sem atendimento há mais que isso, a pessoa conta como ausente. */
export const AWAY_AFTER_DAYS = 60;
/** Cadastro mais novo que isso conta como recente, mesmo sem atendimento. */
const NEW_FOR_DAYS = 30;

export type ClientStatus = 'regular' | 'new' | 'away';

/** Sem gênero de propósito: o "Ativa"/"Nova" do protótipo erra com os clientes de uma barbearia. */
export const CLIENT_STATUS: Record<ClientStatus, { label: string; tone: PanelTone; icon: IconName }> = {
  regular: { label: 'Em dia', tone: 'positive', icon: 'check-circle' },
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

const fold = (text: string) => text.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().trim();

/** Nome sem acento nem caixa; telefone a partir de 3 dígitos. Com a API, vira o `?search=` de `GET /clients`. */
export function matchesSearch(client: ClientRow, query: string): boolean {
  const term = fold(query);
  if (!term) return true;
  const digits = query.replace(/\D/g, '');
  return fold(client.name).includes(term) || (digits.length >= 3 && client.phone.includes(digits));
}

/** Planilha para o Excel em português: `;` separa as colunas e o BOM faz os acentos abrirem certos. */
export function clientsCsv(rows: ClientSummary[]): string {
  // Célula que começa com = + - @ vira fórmula no Excel; o apóstrofo a mantém como texto.
  const cell = (value: string) => `"${value.replace(/^[=+\-@\t\r]/, "'$&").replace(/"/g, '""')}"`;
  const lines = [
    ['Nome', 'Telefone', 'E-mail', 'Situação', 'Atendimentos', 'Valor total', 'Último atendimento'],
    ...rows.map((r) => [
      r.client.name,
      formatPhone(r.client.phone),
      r.client.email ?? '',
      CLIENT_STATUS[r.status].label,
      String(r.visits),
      r.spentCents === undefined ? '' : formatPrice(r.spentCents),
      r.lastVisit ? numericDate(r.lastVisit) : '',
    ]),
  ];
  return `\uFEFF${lines.map((line) => line.map(cell).join(';')).join('\r\n')}`;
}
