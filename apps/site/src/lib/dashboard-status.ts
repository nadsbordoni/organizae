/**
 * Arquivo próprio para `types/painel.ts` e o domínio não se importarem em ciclo.
 * `cancelled` NÃO apaga a linha: o histórico fica, e o registro sai do cálculo de ocupação.
 */
export type AppointmentStatus = 'pending' | 'confirmed' | 'done' | 'cancelled';

export const BLOCKING_STATUSES: readonly AppointmentStatus[] = ['pending', 'confirmed', 'done'];

/**
 * `pending` ocupa lugar de propósito, senão duas clientes pedem o mesmo horário.
 * NÃO existe expiração de pendência: pedido abandonado segura a agenda até alguém cancelar.
 */
export function occupiesSlot(status: AppointmentStatus): boolean {
  return BLOCKING_STATUSES.includes(status);
}
