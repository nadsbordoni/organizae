/** Dados do painel. Hoje vêm de `lib/dados-exemplo.ts`; a API vai devolver este formato. */
import type { AppointmentStatus } from '@/lib/dashboard-status';

/** O negócio vem da sessão, NUNCA de parâmetro de URL. */
export interface AuthenticatedUser {
  userId: number;
  tenantSlug: string;
  email: string;
  name?: string;
  sessionId: string;
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
