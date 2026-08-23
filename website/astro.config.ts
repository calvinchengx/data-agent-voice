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
          label: 'Start here',
          items: [{ slug: 'index' }, { slug: '00-plan' }],
        },
        {
          label: 'What was read',
          items: [{ slug: '05-ten' }],
        },
        {
          // Living ledgers rather than chapters: a reader looks things up here.
          label: 'Reference',
          items: [{ slug: 'parity' }, { slug: 'upstream-issues' }],
        },
      ],
    }),
  ],
});
