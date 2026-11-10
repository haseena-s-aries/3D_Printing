/**
 * Digital Passport mobile app (iOS and Android) — Phase 1 foundation.
 * Deployment selection is configuration only until OQ-49 and OQ-64 are decided.
 */
import React, {useMemo} from 'react';
import {StatusBar} from 'react-native';
import {SafeAreaProvider} from 'react-native-safe-area-context';

import {ApiClient} from './src/api/client';
import {keychainStore} from './src/api/tokenStore';
import {AuthProvider} from './src/auth/AuthContext';
import {DEV_DEPLOYMENT, staticRegistry} from './src/config/deployments';
import RootNavigator from './src/navigation/RootNavigator';

const registry = staticRegistry([DEV_DEPLOYMENT], __DEV__);

export default function App() {
  const client = useMemo(() => new ApiClient(registry.get(DEV_DEPLOYMENT.id), keychainStore), []);
  return (
    <SafeAreaProvider>
      <StatusBar barStyle="light-content" />
      <AuthProvider client={client}>
        <RootNavigator />
      </AuthProvider>
    </SafeAreaProvider>
  );
}
