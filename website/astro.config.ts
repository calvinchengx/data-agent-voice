import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';

// The site is generated from /docs by scripts/sync-docs.ts, which runs before
// dev and build. /docs stays the single source of truth; nothing here is
// written twice.
export default defineConfig({
  site: 'https://calvinchengx.github.io',
  base: '/data-agent-voice/docs/',
  integrations: [
    starlight({
      title: 'Data Agent Voice',
      description:
        'The Analyst Line: talk to your governed data. A voice front end over data-agent-service, ' +
        'where the conversation never waits for the agent and a refusal is never narrated.',
      components: {
        SiteTitle: './src/components/SiteTitle.astro',
      },
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/calvinchengx/data-agent-voice',
        },
      ],
      editLink: {
        baseUrl: 'https://github.com/calvinchengx/data-agent-voice/edit/main/docs/',
      },
      sidebar: [
        {
          label: 'Getting started',
          items: [{ slug: 'index' }, { slug: '01-quickstart' }, { slug: '02-architecture' }],
        },
        {
          label: 'Using it',
          items: [{ slug: '04-tiers' }, { slug: '03-latency' }],
        },
        {
          label: 'Proving it',
          items: [{ slug: '06-witnesses' }, { slug: '07-ci' }],
        },
        {
          // The plan is the long-form argument and the reading of the
          // framework is its evidence; parity and upstream-issues are living
          // ledgers rather than chapters, so they sit at the end where a
          // reader looks things up rather than reads through.
          label: 'Reference',
          items: [
            { slug: '00-plan' },
            { slug: '05-ten' },
            { slug: 'parity' },
            { slug: 'upstream-issues' },
          ],
        },
      ],
    }),
  ],
});
