import { formatDuration } from './agenda';
import type { Agenda, Service, ServiceCategory } from '@/types/agenda';

/** `Service.hidden` e `Service.soon` vistos pela dona do negócio. Com a API, `is_active`. */
export type ServiceState = 'active' | 'soon' | 'draft';

export const SERVICE_STATE: Record<ServiceState, { label: string; detail: string }> = {
  active: { label: 'Ativo', detail: 'Disponível para agendamento' },
  soon: { label: 'Em breve', detail: 'Aparece na página, sem agendar' },
  draft: { label: 'Rascunho', detail: 'Fora da página pública' },
};

export const serviceState = (service: Service): ServiceState =>
  service.hidden ? 'draft' : service.soon ? 'soon' : 'active';

export function catalogServices(agenda: Agenda | undefined): Array<{ service: Service; category: ServiceCategory }> {
  return (agenda?.categories ?? []).flatMap((category) => category.services.map((service) => ({ service, category })));
}

/** De 15 em 15 minutos até 2h, depois de 30 em 30 até 4h. */
export const DURATION_OPTIONS = [15, 30, 45, 60, 75, 90, 105, 120, 150, 180, 210, 240].map((minutes) => ({
  value: String(minutes),
  label: formatDuration(minutes),
}));
