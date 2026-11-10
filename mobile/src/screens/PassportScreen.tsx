import type {EngineeringFile, Paginated, Passport} from '@passport/api-types';
import type {NativeStackScreenProps} from '@react-navigation/native-stack';
import React, {useEffect, useState} from 'react';
import {ActivityIndicator, ScrollView, Text, View} from 'react-native';

import {ApiError} from '../api/client';
import {useAuth} from '../auth/AuthContext';
import type {RootStack} from '../navigation/types';
import {s} from '../ui/theme';

type Props = NativeStackScreenProps<RootStack, 'Passport'>;

// Passport sections (PSEC-001) in display order
const SECTIONS: [string, string][] = [
  ['3d_model', 'Interactive 3D model'],
  ['drawing', 'Engineering drawings'],
  ['specification', 'Manufacturing specifications'],
  ['inspection', 'Inspection and quality documents'],
  ['certificate', 'Certifications'],
  ['other', 'Other documents'],
];

const human = (v?: string | null) => (v ? v.replace(/_/g, ' ') : '—');

/** Passport detail foundation (MOB-012, MOB-023). 3D viewing on mobile is the next item (WebView viewer, MOB-014). */
export default function PassportScreen({route}: Props) {
  const {client} = useAuth();
  const [passport, setPassport] = useState<Passport | null>(null);
  const [files, setFiles] = useState<EngineeringFile[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      client.request<Passport>(`/passports/${route.params.id}/`),
      client.request<Paginated<EngineeringFile>>('/files/', {query: {passport: route.params.id, page_size: 100}}),
    ])
      .then(([p, f]) => {
        if (!cancelled) {
          setPassport(p);
          setFiles(f.results);
        }
      })
      .catch(e => !cancelled && setError(e instanceof ApiError ? e.message : 'Cannot load the passport.'));
    return () => {
      cancelled = true;
    };
  }, [client, route.params.id]);

  if (error) {
    return (
      <View style={[s.screen, s.pad]}>
        <View style={s.error} accessibilityRole="alert">
          <Text style={s.errorText}>{error}</Text>
        </View>
      </View>
    );
  }
  if (!passport) {
    return <ActivityIndicator style={{marginTop: 32}} />;
  }
  const rl1 = passport.current_revision?.content?.rl1 ?? {};
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.pad}>
      <Text style={s.h1}>{passport.passport_number}</Text>
      <Text style={[s.muted, {marginBottom: 12}]}>{passport.title}</Text>
      <View style={s.notice}>
        <Text style={s.noticeText}>Approval, publication and manufacturing release are not available yet (pending OQ-35, OQ-36).</Text>
      </View>
      <View style={s.card}>
        <Text style={s.h2}>Product information</Text>
        <Text style={s.text}>Spare part {passport.part_summary.part_number} · {passport.part_summary.name}</Text>
        <Text style={s.muted}>Publication: {human(passport.publication_state)}</Text>
        <Text style={s.muted}>Evidence level: {passport.evidence_level === 'none' ? 'not assessed' : passport.evidence_level}</Text>
        <Text style={s.muted}>Manufacturing: {human(passport.manufacturing_eligibility)}</Text>
        <Text style={s.muted}>Size: {rl1.part_size || '—'} · Material: {rl1.original_material_grade || '—'}</Text>
        <Text style={s.muted}>Revision {passport.current_revision?.revision_number} ({passport.current_revision?.status})</Text>
      </View>
      {SECTIONS.map(([key, title]) => {
        const list = files.filter(f => f.category === key);
        if (!list.length) {
          return null;
        }
        return (
          <View key={key} style={s.card}>
            <Text style={s.h2}>{title}</Text>
            {list.map(f => (
              <View key={f.id} style={{marginBottom: 8}}>
                <Text style={s.text}>{f.title}</Text>
                <Text style={s.muted}>
                  {(f.kind ?? '').toUpperCase()} · v{f.latest_version?.version_number} · {f.latest_version?.detected_format}
                </Text>
                {f.latest_version?.conversion && (
                  <Text style={s.muted}>
                    {f.latest_version.conversion.status === 'not_available' ? 'Preview not available yet' : `3D derivative: ${f.latest_version.conversion.status}`}
                  </Text>
                )}
              </View>
            ))}
          </View>
        );
      })}
    </ScrollView>
  );
}
