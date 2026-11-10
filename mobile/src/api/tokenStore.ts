/**
 * Refresh-token storage (MOB-002, MOB-004, MOB-007, MOB-022).
 * Production implementation uses the platform keystore (iOS Keychain / Android Keystore via react-native-keychain).
 * Access tokens are kept in memory only.
 */
import * as Keychain from 'react-native-keychain';

export interface TokenStore {
  saveRefresh(deploymentId: string, token: string): Promise<void>;
  loadRefresh(deploymentId: string): Promise<string | null>;
  clear(deploymentId: string): Promise<void>;
}

const service = (deploymentId: string) => `passport.refresh.${deploymentId}`;

export const keychainStore: TokenStore = {
  async saveRefresh(deploymentId, token) {
    await Keychain.setGenericPassword('refresh', token, {
      service: service(deploymentId),
      accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    });
  },
  async loadRefresh(deploymentId) {
    const creds = await Keychain.getGenericPassword({service: service(deploymentId)});
    return creds ? creds.password : null;
  },
  async clear(deploymentId) {
    await Keychain.resetGenericPassword({service: service(deploymentId)});
  },
};

/** In-memory store for tests. */
export function memoryStore(): TokenStore & {data: Map<string, string>} {
  const data = new Map<string, string>();
  return {
    data,
    async saveRefresh(id, t) {
      data.set(id, t);
    },
    async loadRefresh(id) {
      return data.get(id) ?? null;
    },
    async clear(id) {
      data.delete(id);
    },
  };
}
