import type {Session} from '@passport/api-types';

import {ApiClient, ApiError} from '../src/api/client';
import {memoryStore} from '../src/api/tokenStore';
import type {Deployment} from '../src/config/deployments';

const deployment: Deployment = {id: 'test', name: 'Test', kind: 'shared', apiBaseUrl: 'https://api.test'};

function session(tenantId: string): Session {
  return {
    user: {id: 'u1', email: 'a@b.c', first_name: '', last_name: ''},
    tenant: {id: tenantId, name: 'T', slug: 't', kind: 'client', hosting_model: 'shared'},
    membership: {id: 'm1', role: 'client_user'},
    capabilities: ['parts.view'],
  };
}

type Call = {url: string; init?: {method?: string; headers?: Record<string, string>; body?: string}};

/** Fetch stub that answers queued responses in order and records each call. */
function fakeFetch(responses: {status: number; body?: unknown}[]) {
  const calls: Call[] = [];
  const impl = jest.fn(async (url: string, init?: Call['init']) => {
    calls.push({url, init});
    const r = responses.shift();
    if (!r) {
      throw new Error(`unexpected request ${url}`);
    }
    return {ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body};
  });
  return {impl, calls};
}

describe('ApiClient', () => {
  it('logs in, stores the refresh token and sends the bearer token', async () => {
    const store = memoryStore();
    const {impl, calls} = fakeFetch([
      {status: 200, body: {access: 'A1', refresh: 'R1', session: session('t1')}},
      {status: 200, body: {count: 0, next: null, previous: null, results: []}},
    ]);
    const client = new ApiClient(deployment, store, impl);
    const s = await client.login('a@b.c', 'pw', 'acme');
    expect(s.tenant.id).toBe('t1');
    expect(JSON.parse(calls[0].init!.body!)).toEqual({email: 'a@b.c', password: 'pw', tenant: 'acme'});
    expect(await store.loadRefresh('test')).toBe('R1');

    await client.request('/parts/', {query: {search: 'pump 1', page: undefined}});
    expect(calls[1].url).toBe('https://api.test/api/v1/parts/?search=pump%201');
    expect(calls[1].init!.headers!.Authorization).toBe('Bearer A1');
  });

  it('maps the error envelope to ApiError', async () => {
    const {impl} = fakeFetch([
      {
        status: 400,
        body: {error: {code: 'tenant_selection_required', message: 'Select an organisation.', details: {tenants: [{slug: 'a'}]}, request_id: 'rq1'}},
      },
    ]);
    const client = new ApiClient(deployment, memoryStore(), impl);
    const err = await client.login('a@b.c', 'pw').catch(e => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({status: 400, code: 'tenant_selection_required', requestId: 'rq1', details: {tenants: [{slug: 'a'}]}});
  });

  it('falls back to a generic code when the body is not JSON', async () => {
    const impl = jest.fn(async () => ({ok: false, status: 502, json: async () => Promise.reject(new SyntaxError('html'))}));
    const client = new ApiClient(deployment, memoryStore(), impl);
    await expect(client.request('/parts/')).rejects.toMatchObject({code: 'http_502', message: 'Request failed.'});
  });

  it('refreshes once on 401, rotates the refresh token and retries', async () => {
    const store = memoryStore();
    await store.saveRefresh('test', 'R1');
    const {impl, calls} = fakeFetch([
      {status: 401, body: {error: {code: 'token_not_valid', message: 'expired', details: {}, request_id: ''}}},
      {status: 200, body: {access: 'A2', refresh: 'R2'}},
      {status: 200, body: {ok: true}},
    ]);
    const client = new ApiClient(deployment, store, impl);
    await expect(client.request('/parts/')).resolves.toEqual({ok: true});
    expect(calls.map(c => c.url)).toEqual([
      'https://api.test/api/v1/parts/',
      'https://api.test/api/v1/auth/refresh/',
      'https://api.test/api/v1/parts/',
    ]);
    expect(calls[2].init!.headers!.Authorization).toBe('Bearer A2');
    expect(await store.loadRefresh('test')).toBe('R2');
  });

  it('shares one refresh between concurrent 401s', async () => {
    const store = memoryStore();
    await store.saveRefresh('test', 'R1');
    const {impl, calls} = fakeFetch([
      {status: 401},
      {status: 401},
      {status: 200, body: {access: 'A2', refresh: 'R2'}},
      {status: 200, body: 1},
      {status: 200, body: 2},
    ]);
    const client = new ApiClient(deployment, store, impl);
    await Promise.all([client.request('/a/'), client.request('/b/')]);
    expect(calls.filter(c => c.url.endsWith('/auth/refresh/'))).toHaveLength(1);
  });

  it('ends the session when refresh is rejected', async () => {
    const store = memoryStore();
    await store.saveRefresh('test', 'R1');
    const ended = jest.fn();
    const {impl} = fakeFetch([
      {status: 401},
      {status: 401, body: {error: {code: 'membership_invalid', message: 'Membership is no longer active.', details: {}, request_id: ''}}},
    ]);
    const client = new ApiClient(deployment, store, impl);
    client.onSessionEnded = ended;
    await expect(client.request('/parts/')).rejects.toMatchObject({status: 401});
    expect(await store.loadRefresh('test')).toBeNull();
    expect(ended).toHaveBeenCalled();
  });

  it('resume returns null without a stored refresh token', async () => {
    const {impl} = fakeFetch([]);
    const client = new ApiClient(deployment, memoryStore(), impl);
    await expect(client.resume()).resolves.toBeNull();
    expect(impl).not.toHaveBeenCalled();
  });

  it('resume restores the session from the stored refresh token', async () => {
    const store = memoryStore();
    await store.saveRefresh('test', 'R1');
    const {impl} = fakeFetch([
      {status: 200, body: {access: 'A2', refresh: 'R2'}},
      {status: 200, body: session('t1')},
    ]);
    const client = new ApiClient(deployment, store, impl);
    await expect(client.resume()).resolves.toMatchObject({tenant: {id: 't1'}});
  });

  it('rejects a session for a different tenant than the bound one and clears tokens', async () => {
    const store = memoryStore();
    const {impl} = fakeFetch([{status: 200, body: {access: 'A1', refresh: 'R1', session: session('t1')}}]);
    const client = new ApiClient(deployment, store, impl);
    await client.login('a@b.c', 'pw');
    expect(() => client.bind(session('t2'))).toThrow(expect.objectContaining({code: 'tenant_binding_mismatch'}));
    await Promise.resolve();
    expect(await store.loadRefresh('test')).toBeNull();
  });

  it('logout blacklists the refresh token and clears local state', async () => {
    const store = memoryStore();
    const {impl, calls} = fakeFetch([
      {status: 200, body: {access: 'A1', refresh: 'R1', session: session('t1')}},
      {status: 205},
    ]);
    const client = new ApiClient(deployment, store, impl);
    await client.login('a@b.c', 'pw');
    await client.logout();
    expect(calls[1].url).toBe('https://api.test/api/v1/auth/logout/');
    expect(JSON.parse(calls[1].init!.body!)).toEqual({refresh: 'R1'});
    expect(await store.loadRefresh('test')).toBeNull();
  });
});
