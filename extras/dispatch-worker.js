// Optional independent trigger. This Worker never receives Meta/Discord secrets.
export default {
  async scheduled(_event, env) {
    if (!env.GH_ACTIONS_TOKEN) throw new Error('GH_ACTIONS_TOKEN is not configured');
    const result = await fetch('https://api.github.com/repos/Ameyohou/-hanaabi-discord-monitor/actions/workflows/monitor.yml/dispatches', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.GH_ACTIONS_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'HanaabiSchedule/1.0',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ref: 'main', inputs: {respect_interval: true}}),
    });
    if (!result.ok) throw new Error(`GitHub dispatch failed: HTTP ${result.status}`);
    console.log('GitHub workflow dispatch accepted');
  },
  fetch() { return new Response('Not found', {status: 404}); },
};
