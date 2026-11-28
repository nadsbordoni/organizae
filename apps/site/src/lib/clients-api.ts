import type { Agenda, IsoDate } from '@/types/agenda';
import type { AppointmentRow, ClientRow } from '@/types/painel';
import { addDays, nowInBusinessTime } from './agenda';
import { ApiError, api, apiEnabled } from './api';
import { appointmentsBetween, businessAgenda, toRow } from './appointments';
import type { AppointmentResponse } from './appointments';
import { forTenant } from './dados-exemplo';

/** Clientes do negócio logado (`/clients`), no mesmo formato dos dados de exemplo. */

interface ClientResponse {
  id: string;
  name: string;
  phone: string;
  email: string | null;
  notes: string | null;
  birth_date: string | null;
  referral: Referral | null;
  whatsapp_opt_in: boolean;
  created_at: string;
}

type Referral = 'INSTAGRAM' | 'REFERRAL' | 'GOOGLE' | 'WHATSAPP' | 'OTHER';

/** O formulário mostra o rótulo; a API guarda o código. "Não informado" é `null`. */
const REFERRAL_LABELS: Record<Referral, string> = {
  INSTAGRAM: 'Instagram',
  REFERRAL: 'Indicação',
  GOOGLE: 'Google',
  WHATSAPP: 'WhatsApp',
  OTHER: 'Outro',
};

const referralCode = (label: string) =>
  (Object.keys(REFERRAL_LABELS) as Referral[]).find((code) => REFERRAL_LABELS[code] === label) ?? null;

const toClientRow = (client: ClientResponse): ClientRow => ({
  ...client,
  referral: client.referral && REFERRAL_LABELS[client.referral],
});

function clientsApi(token: string, timezone: string) {
  return {
    async clients(): Promise<ClientRow[]> {
      // PROTÓTIPO: só a primeira página (até 100); paginar quando algum negócio passar disso.
      return (await api<ClientResponse[]>('/clients?limit=100', { token })).map(toClientRow);
    },

    /** `undefined` se não existe ou é de outro negócio: a API responde 404 nos dois casos. */
    async client(id: string): Promise<ClientRow | undefined> {
      try {
        return toClientRow(await api<ClientResponse>(`/clients/${encodeURIComponent(id)}`, { token }));
      } catch (error) {
        if (error instanceof ApiError && (error.status === 404 || error.status === 422)) return undefined;
        throw error;
      }
    },

    /** Do mais recente ao mais antigo. */
    async clientAppointments(id: string): Promise<AppointmentRow[]> {
      const history = await api<AppointmentResponse[]>(`/clients/${encodeURIComponent(id)}/appointments`, { token });
      return history.map((item) => toRow(item, timezone)).filter((row): row is AppointmentRow => row !== undefined);
    },
  };
}

/** Quanto da agenda a lista de clientes olha para contar visitas e valor gasto. */
const HISTORY_DAYS = 365;
/** `GET /appointments` aceita até 31 dias; `appointmentsBetween` soma um dia de cada lado. */
const CHUNK_DAYS = 29;

/**
 * Histórico de todos os clientes de uma vez, agrupado pelo telefone, que é como a API liga
 * atendimento a cliente. Uma chamada por cliente estourava o tempo com algumas dezenas deles.
 */
async function allHistories(token: string, timezone: string, clients: ClientRow[]): Promise<Map<string, AppointmentRow[]>> {
  const today = nowInBusinessTime(timezone).date;
  const ranges: Array<[IsoDate, IsoDate]> = [];
  for (let from = addDays(today, -HISTORY_DAYS); from <= today; from = addDays(from, CHUNK_DAYS)) {
    ranges.push([from, addDays(from, CHUNK_DAYS - 1)]);
  }
  const rows = (await Promise.all(ranges.map(([from, to]) => appointmentsBetween(token, from, to, timezone)))).flat();

  const byPhone = new Map<string, AppointmentRow[]>();
  for (const row of rows) {
    if (!row.client_phone) continue;
    byPhone.set(row.client_phone, [...(byPhone.get(row.client_phone) ?? []), row]);
  }
  return new Map(clients.map((client) => [client.id, (byPhone.get(client.phone) ?? []).reverse()]));
}

/** Com a API, clientes e catálogo do banco; sem ela, os do exemplo. */
export async function clientData(token: string | undefined, tenantSlug: string, siteAgenda: Agenda | undefined) {
  if (!apiEnabled() || !token) {
    const dados = forTenant(tenantSlug);
    const histories = async (clients: ClientRow[]) =>
      new Map(await Promise.all(clients.map(async (c) => [c.id, await dados.clientAppointments(c.id)] as const)));
    return { live: false, agenda: siteAgenda, dados, histories };
  }
  const { agenda } = await businessAgenda(token, siteAgenda);
  const histories = (clients: ClientRow[]) => allHistories(token, agenda.timezone, clients);
  return { live: true, agenda, dados: clientsApi(token, agenda.timezone), histories };
}

export interface ClientInput {
  name: string;
  phone: string;
  email: string;
  notes: string;
  /** 'AAAA-MM-DD' ou vazio. */
  birthDate: string;
  /** Rótulo do formulário, ex.: 'Instagram'. */
  referral: string;
  whatsappOptIn: boolean;
}

export function readClientForm(form: FormData): ClientInput {
  const text = (name: string) => String(form.get(name) ?? '').trim();
  return {
    name: text('nome'),
    phone: text('telefone'),
    email: text('email').toLowerCase(),
    notes: text('observacoes'),
    birthDate: text('nascimento'),
    referral: text('origem'),
    whatsappOptIn: form.get('whatsapp') !== null,
  };
}

/** Cria (`POST`) ou atualiza (`PATCH`) e devolve o id. Campo opcional vazio vai como `null`, para apagar. */
export async function saveClient(token: string, input: ClientInput, id?: string): Promise<string> {
  const body = {
    name: input.name,
    phone: input.phone,
    email: input.email || null,
    notes: input.notes || null,
    birth_date: input.birthDate || null,
    referral: referralCode(input.referral),
    whatsapp_opt_in: input.whatsappOptIn,
  };
  const saved = await api<ClientResponse>(id ? `/clients/${encodeURIComponent(id)}` : '/clients', {
    method: id ? 'PATCH' : 'POST',
    token,
    body,
  });
  return saved.id;
}

export function clientError(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) return 'Já existe um cliente com este telefone.';
  if (error instanceof ApiError && error.status === 422) {
    if (error.fields.includes('phone')) return 'Telefone inválido. Use DDD e número, ex.: (81) 99999-9999.';
    if (error.fields.includes('email')) return 'E-mail inválido. Confira o endereço.';
    if (error.fields.includes('birth_date')) return 'Data de nascimento inválida. Use uma data entre 1900 e hoje.';
    return 'Confira os dados do cliente e tente de novo.';
  }
  return 'Não foi possível salvar o cliente agora. Tente de novo em instantes.';
}

/** Valores digitados de volta no formulário, depois de um erro. */
export function draftClient(input: ClientInput, base?: ClientRow): ClientRow {
  return {
    id: base?.id ?? '',
    created_at: base?.created_at ?? '',
    birth_date: input.birthDate || null,
    referral: input.referral || null,
    whatsapp_opt_in: input.whatsappOptIn,
    name: input.name,
    phone: input.phone,
    email: input.email || null,
    notes: input.notes || null,
  };
}
