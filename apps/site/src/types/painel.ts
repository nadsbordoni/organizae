/** Dados do painel. Hoje vêm de `lib/dados-exemplo.ts`; a API vai devolver este formato. */
import type { AppointmentStatus } from '@/lib/dashboard-status';

/** Quem entrou no painel. O negócio vem da sessão, NUNCA de parâmetro de URL. */
export interface AuthenticatedUser {
  /** O `id` de `GET /users/me`. */
  userId: string;
  /** Qual `config/sites/` monta o painel. Até a fatia do negócio, é sempre o exemplo. */
  tenantSlug: string;
  email: string;
  name?: string;
  /** `null` enquanto a conta não tem negócio cadastrado. */
  businessId?: string | null;
  /** `api` quando a sessão veio do login; `exemplo` na demonstração. */
  sessionId: 'api' | 'exemplo';
}

/** Evento da agenda para a tela de notificações. */
export interface AgendaNotification {
  id: string;
  kind: 'created' | 'cancelled';
  /** 'HH:MM' de hoje, quando o evento aconteceu. */
  at: string;
  read: boolean;
  row: AppointmentRow;
}

/** Cliente da carteira do negócio, no formato de `GET /clients`. */
export interface ClientRow {
  id: string;
  name: string;
  /** Só dígitos, com DDD. Único por negócio; é por ele que a API acha o histórico. */
  phone: string;
  email: string | null;
  notes: string | null;
  created_at: string;
  /** Os três abaixo ainda NÃO existem no back. */
  birth_date: string | null;
  referral: string | null;
  /** Autorizou mensagens de retorno pelo WhatsApp. Sem isso, a pessoa fica fora das campanhas. */
  whatsapp_opt_in: boolean;
}

/** Profissional do negócio, no formato de `GET /professionals`. */
export interface ProfessionalRow {
  id: string;
  name: string;
  phone: string | null;
  /** Especialidade, mostrada na lista da equipe. */
  description: string | null;
  /** Desligado, não recebe agendamentos. */
  is_active: boolean;
  /** Ids do catálogo; a API devolve os serviços inteiros. */
  service_ids: string[];
  /** Os dois abaixo ainda NÃO existem no back: e-mail de acesso ao painel e quem administra. */
  email: string | null;
  role: 'owner' | 'professional';
}

/**
 * Férias ou folga de alguém da equipe. Com a API, é um bloqueio de dia inteiro
 * (`POST /appointments/blocks` com `professional_id`), com o motivo em `notes`.
 */
export interface TimeOffRow {
  id: string;
  professional_id: string;
  /** 'AAAA-MM-DD'; os dois dias contam. */
  starts_on: string;
  ends_on: string;
  reason: string;
}

export type FinancialType = 'INCOME' | 'EXPENSE';

/**
 * Categoria financeira, no formato de `GET /financial-categories`. `group` ainda NÃO existe no back:
 * separa a origem da receita (serviços, produtos, outras) e as despesas em custo fixo, variável e imposto.
 */
export interface FinancialCategoryRow {
  id: string;
  name: string;
  type: FinancialType;
  group: 'services' | 'products' | 'other' | 'fixed' | 'variable' | 'tax';
}

export type PaymentMethod = 'pix' | 'card' | 'cash' | 'boleto' | 'debit';

/** Lançamento, no formato de `GET /financial-entries`. */
export interface FinancialEntryRow {
  id: string;
  category_id: string;
  type: FinancialType;
  description: string;
  /** Em centavos; a API manda `Decimal` em texto. */
  amount_cents: number;
  /** Vencimento: quando entra ou sai do caixa, se ainda não foi pago. */
  due_date: string;
  /** Dia do pagamento, na hora de parede do negócio; a API guarda o instante em `paid_at`. */
  paid_on: string | null;
  status: 'PENDING' | 'PAID' | 'CANCELLED';
  appointment_id: number | null;
  /** Os campos abaixo ainda NÃO existem no back (a API só tem `competence` em recorrências). */
  /** Mês do resultado: o atendimento de hoje pago no cartão em 30 dias é receita de hoje. */
  competence: string;
  payment_method: PaymentMethod | null;
  /** Número da nota fiscal emitida ou recebida. */
  invoice: string | null;
  /** Pagamento já programado (débito automático). */
  scheduled: boolean;
}

export interface AppointmentRow {
  id: number;
  tenant_slug: string;
  /** 'AAAA-MM-DD' na hora de parede do negócio. */
  date: string;
  /** 'HH:MM'. */
  start_time: string;
  duration_min: number;
  /** JSON com ids de serviço: '["manutencao","esmaltacao"]'. */
  service_ids: string;
  client_name: string;
  client_phone: string | null;
  notes: string | null;
  status: AppointmentStatus;
  origin: 'site' | 'panel';
  created_at: string;
  updated_at: string;
}
