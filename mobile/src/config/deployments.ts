/**
 * Deployment binding (HYB-007, MOB-006, MOB-035, MOB-046).
 *
 * The app talks to exactly one deployment per session: the shared Azure platform or a client's dedicated
 * deployment. How users reach dedicated deployments (OQ-49) and whether one configurable app or per-client
 * builds are used (OQ-64) are still open, so this module only defines the interface and validation.
 * Nothing here selects a production endpoint.
 */
export type DeploymentKind = 'shared' | 'dedicated';

export interface Deployment {
  id: string;
  name: string;
  kind: DeploymentKind;
  apiBaseUrl: string; // e.g. https://<deployment-host>  (the app appends /api/v1)
}

export class DeploymentError extends Error {
  constructor(public code: 'invalid_url' | 'insecure_url' | 'unknown_deployment', message: string) {
    super(message);
  }
}

// Plain HTTP is accepted only for local development targets (Android emulator host alias and loopback).
const DEV_HOSTS = new Set(['10.0.2.2', '127.0.0.1', 'localhost']);

export function validateApiBaseUrl(url: string, allowDevHttp: boolean): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new DeploymentError('invalid_url', 'The deployment address is not a valid URL.');
  }
  if (parsed.protocol !== 'https:') {
    const devOk = allowDevHttp && parsed.protocol === 'http:' && DEV_HOSTS.has(parsed.hostname);
    if (!devOk) {
      throw new DeploymentError('insecure_url', 'Deployments must use HTTPS.');
    }
  }
  if (parsed.username || parsed.password) {
    throw new DeploymentError('invalid_url', 'Credentials must not be part of the deployment address.');
  }
  return `${parsed.protocol}//${parsed.host}`;
}

/** Development default: the API on the developer machine as seen from the Android emulator. */
export const DEV_DEPLOYMENT: Deployment = {
  id: 'dev-local',
  name: 'Local development',
  kind: 'shared',
  apiBaseUrl: 'http://10.0.2.2:8000',
};

export interface DeploymentRegistry {
  /** Deployments available to this build (configuration only; see OQ-64). */
  list(): Deployment[];
  get(id: string): Deployment;
}

export function staticRegistry(deployments: Deployment[], allowDevHttp: boolean): DeploymentRegistry {
  const checked = deployments.map(d => ({...d, apiBaseUrl: validateApiBaseUrl(d.apiBaseUrl, allowDevHttp)}));
  return {
    list: () => checked,
    get(id) {
      const d = checked.find(x => x.id === id);
      if (!d) {
        throw new DeploymentError('unknown_deployment', `Unknown deployment: ${id}`);
      }
      return d;
    },
  };
}
