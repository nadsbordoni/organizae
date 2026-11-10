import { baseTheme } from '@/themes/base';
import type { SiteConfig } from '@/types/site';

/**
 * TEMPLATE e DEMONSTRAÇÃO: copie para `src/config/sites/nome-do-cliente.ts`, troque os
 * dados e as imagens em /public e registre em `src/config/index.ts`.
 */
export const exemplo: SiteConfig = {
  slug: 'exemplo',
  theme: baseTheme,

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
      title: 'Agendar um horário',
      emphasis: 'primary',
    },
    {
      type: 'link',
      title: 'Nossos produtos',
      subtitle: 'Cuidados para continuar em casa',
      icon: 'bag',
      href: '/exemplo/produtos',
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

  // Sem foto, cada produto mostra a etiqueta com a inicial.
  collections: [
    {
      slug: 'produtos',
      eyebrow: 'Cuide-se em casa',
      title: 'Favoritos da Joana',
      intro: 'Uma seleção para suas unhas durarem mais entre uma visita e outra.',
      items: [
        {
          name: 'Óleo de cutícula',
          badge: 'Mais vendido',
          description: 'Hidrata e fortalece',
          price: 'R$ 29',
          href: 'https://wa.me/5511988887777',
          ctaLabel: 'Pedir',
        },
        {
          name: 'Base fortalecedora',
          badge: 'Novidade',
          description: 'Unhas mais resistentes',
          price: 'R$ 35',
          href: 'https://wa.me/5511988887777',
          ctaLabel: 'Pedir',
        },
        {
          name: 'Kit manutenção',
          description: 'Lixa, palito e óleo',
          price: 'R$ 59',
          href: 'https://wa.me/5511988887777',
          ctaLabel: 'Pedir',
        },
        {
          name: 'Creme para mãos',
          badge: 'Novidade',
          description: 'Maciez sem pesar',
          price: 'R$ 42',
          href: 'https://wa.me/5511988887777',
          ctaLabel: 'Pedir',
        },
      ],
    },
  ],

  /**
   * DEMONSTRAÇÃO da pausa: com almoço das 12:00 às 13:00, o alongamento de 2h some
   * da lista a partir das 10:30, porque não caberia antes do meio-dia.
   */
  agenda: {
    timezone: 'America/Sao_Paulo',

    hours: {
      mon: { opens: '09:00', closes: '18:00', breaks: [{ from: '12:00', to: '13:00', label: 'Almoço' }] },
      tue: { opens: '09:00', closes: '18:00', breaks: [{ from: '12:00', to: '13:00', label: 'Almoço' }] },
      wed: { opens: '09:00', closes: '18:00', breaks: [{ from: '12:00', to: '13:00', label: 'Almoço' }] },
      thu: { opens: '09:00', closes: '18:00', breaks: [{ from: '12:00', to: '13:00', label: 'Almoço' }] },
      fri: { opens: '09:00', closes: '18:00', breaks: [{ from: '12:00', to: '13:00', label: 'Almoço' }] },
      sat: { opens: '09:00', closes: '13:00' },
    },

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
