import React, {useState} from 'react';
import {ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View} from 'react-native';

import {ApiError} from '../api/client';
import {useAuth} from '../auth/AuthContext';
import {colors, s} from '../ui/theme';

interface TenantChoice {
  slug: string;
  name: string;
}

export default function SignInScreen() {
  const {client, login} = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [tenants, setTenants] = useState<TenantChoice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(tenant?: string) {
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password, tenant);
    } catch (e) {
      if (e instanceof ApiError && e.code === 'tenant_selection_required') {
        setTenants((e.details.tenants as TenantChoice[]) ?? []);
      } else {
        setError(e instanceof ApiError ? e.message : 'Cannot reach the deployment. Check your connection.');
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView style={s.screen} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={[s.pad, {flexGrow: 1, justifyContent: 'center'}]} keyboardShouldPersistTaps="handled">
        <View style={s.card}>
          <Text style={s.h1}>Digital Passport</Text>
          <Text style={[s.muted, {marginBottom: 16}]}>
            {client.deployment.name} · {client.deployment.kind === 'dedicated' ? 'dedicated deployment' : 'shared platform'}
          </Text>
          {error && (
            <View style={s.error} accessibilityRole="alert">
              <Text style={s.errorText}>{error}</Text>
            </View>
          )}
          {!tenants ? (
            <>
              <Text style={s.label}>Email</Text>
              <TextInput style={s.input} value={email} onChangeText={setEmail} autoCapitalize="none" autoComplete="email" keyboardType="email-address" textContentType="username" accessibilityLabel="Email" />
              <Text style={s.label}>Password</Text>
              <TextInput style={s.input} value={password} onChangeText={setPassword} secureTextEntry textContentType="password" accessibilityLabel="Password" />
              <Pressable style={s.button} onPress={() => submit()} disabled={busy || !email || !password} accessibilityRole="button">
                {busy ? <ActivityIndicator color="#fff" /> : <Text style={s.buttonText}>Sign in</Text>}
              </Pressable>
            </>
          ) : (
            <>
              <Text style={[s.h2, {marginTop: 4}]}>Select an organisation</Text>
              {tenants.map(t => (
                <Pressable key={t.slug} style={s.buttonGhost} onPress={() => submit(t.slug)} disabled={busy} accessibilityRole="button">
                  <Text style={{color: colors.ink}}>{t.name}</Text>
                </Pressable>
              ))}
              <Pressable onPress={() => setTenants(null)} accessibilityRole="button">
                <Text style={[s.muted, {textAlign: 'center', marginTop: 8}]}>Back</Text>
              </Pressable>
            </>
          )}
        </View>
        <Text style={[s.muted, {textAlign: 'center'}]}>Access is limited to authorised users. Activity is audited.</Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
