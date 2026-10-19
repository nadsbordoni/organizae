import { indigoTheme } from '@/themes/indigo';
import type { SiteConfig } from '@/types/site';

/**
 * TEMPLATE para um novo empreendedor.
 *
 * Como criar uma página nova, sem escrever componente nenhum:
 *   1. Copie este arquivo para `src/config/sites/nome-do-cliente.ts`
 *   2. Troque `slug`, `profile`, `blocks` e as imagens em /public
 *   3. Escolha um tema pronto ou crie um em `src/themes/`
 *   4. Registre em `src/config/index.ts`
 * Pronto — a rota `/nome-do-cliente` passa a existir.
 *
 * Esta demo fica fora dos buscadores por causa de `seo.noindex`.
 */
export const exemplo: SiteConfig = {
  slug: 'exemplo',
  theme: indigoTheme,

  profile: {
    name: 'Joana',
    nameSuffix: 'Manicure',
    headline: 'Atendimento em domicílio',
    services: ['Unhas em gel', 'Manutenção', 'Esmaltação'],
  },

  seo: {
    title: 'Joana Manicure • Exemplo de página',
    description: 'Página de demonstração da plataforma de link na bio.',
    noindex: true,
  },

  blocks: [
    {
      type: 'booking',
      title: 'Agendar horário',
      subtitle: 'Escolha serviço, dia e hora',
      emphasis: 'primary',
    },
    {
      type: 'whatsapp',
      title: 'Falar comigo',
      phone: '5511988887777',
      message: 'Oi, Joana! Queria tirar uma dúvida.',
    },
    {
      type: 'hours',
      subtitle: 'Somente com hora marcada',
      // Sem `schedule`: derivado da `agenda` abaixo, inclusive o almoço.
    },
    {
      type: 'section',
      title: 'Redes',
    },
    {
      type: 'socials',
      items: [{ network: 'instagram', handle: 'joanamanicure' }],
    },
  ],

  /**
   * Agenda de demonstração — é aqui que se vê o recurso de PAUSA funcionando.
   *
   * Com almoço das 12:00 às 13:00, o fluxo não oferece nada nesse intervalo, e
   * também não oferece começo que invada a pausa: o alongamento de 2h some da
   * lista a partir das 10:30, porque não caberia antes do meio-dia.
   */
  agenda: {
    timezone: 'America/Sao_Paulo',

    hours: {
      mon: { opens: '09:00', closes: '18:00', breaks: [{ from: '12:00', to: '13:00', label: 'Almoço' }] },
      tue: { opens: '09:00', closes: '18:00', breaks: [{ from: '12:00', to: '13:00', label: 'Almoço' }] },
      wed: { opens: '09:00', closes: '18:00', breaks: [{ from: '12:00', to: '13:00', label: 'Almoço' }] },
      thu: { opens: '09:00', closes: '18:00', breaks: [{ from: '12:00', to: '13:00', label: 'Almoço' }] },
      fri: { opens: '09:00', closes: '18:00', breaks: [{ from: '12:00', to: '13:00', label: 'Almoço' }] },
      // Sábado sem pausa e mais curto — mostra que cada dia é independente.
      sat: { opens: '09:00', closes: '13:00' },
    },

    // Feriado: o dia some do calendário sem mexer no expediente da semana.
    exceptions: [{ date: '2026-12-25', hours: null, reason: 'Natal' }],

    minNoticeHours: 6,
    request: { via: 'whatsapp', phone: '5511988887777' },

    policies: [
      'Agende com pelo menos 6 horas de antecedência',
      'Atendimento em domicílio dentro da zona oeste',
    ],

    categories: [
      {
        id: 'unhas',
        name: 'Unhas',
        description: 'Alongamento, manutenção, esmaltação',
        services: [
          { id: 'alongamento', name: 'Alongamento em gel', durationMinutes: 120, price: 'R$ 160,00' },
          { id: 'manutencao', name: 'Manutenção', durationMinutes: 90, price: 'R$ 90,00' },
          { id: 'esmaltacao', name: 'Esmaltação', durationMinutes: 45, price: 'R$ 50,00' },
        ],
      },
      {
        id: 'pes',
        name: 'Pés',
        description: 'Pedicure e spa',
        services: [
          { id: 'pedicure', name: 'Pedicure', durationMinutes: 60, price: 'R$ 60,00' },
          { id: 'spa-dos-pes', name: 'Spa dos pés', durationMinutes: 75, soon: true },
        ],
      },
    ],
  },
};
