/**
 * Situação de um agendamento. Arquivo próprio para `types/painel.ts` e o domínio
 * não se importarem em ciclo. `cancelled` não apaga a linha: o histórico de
 * desmarcação é útil, e o registro sai do cálculo de ocupação de todo jeito.
 */
export type AppointmentStatus = 'pending' | 'confirmed' | 'done' | 'cancelled';

/** Situações que ocupam lugar na agenda. */
export const BLOCKING_STATUSES: readonly AppointmentStatus[] = ['pending', 'confirmed', 'done'];

/**
 * ⚠️ `pending` ocupa lugar de propósito: senão duas clientes pedem o mesmo
 * horário. Pedido abandonado segura a agenda até alguém cancelar: NÃO existe
 * expiração de pendência.
 */
export function occupiesSlot(status: AppointmentStatus): boolean {
  return BLOCKING_STATUSES.includes(status);
}
