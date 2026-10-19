/**
 * Formato dos dados que o painel recebe. Hoje vem de `lib/dados-exemplo.ts`;
 * quando a API existir, ela devolve este formato (ou o front converte).
 */
import type { AppointmentStatus } from '@/lib/dashboard-status';

/** Quem está logada. O negócio vem da sessão, nunca de parâmetro de URL. */
export interface AuthenticatedUser {
  userId: number;
  tenantSlug: string;
  email: string;
  name?: string;
  sessionId: string;
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
