import type {Paginated, Part} from '@passport/api-types';
import type {NativeStackScreenProps} from '@react-navigation/native-stack';
import React, {useCallback, useEffect, useState} from 'react';
import {ActivityIndicator, FlatList, Pressable, RefreshControl, Text, TextInput, View} from 'react-native';

import {ApiError} from '../api/client';
import {useAuth} from '../auth/AuthContext';
import type {RootStack} from '../navigation/types';
import {s} from '../ui/theme';

type Props = NativeStackScreenProps<RootStack, 'Inventory'>;

/** Digital inventory foundation (MOB-009, MOB-010): search by passport-relevant fields. Filters by evidence level and
 * manufacturing eligibility are added once publication rules (OQ-35) and eligibility rules (OQ-36) are decided. */
export default function InventoryScreen({navigation}: Props) {
  const {client} = useAuth();
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<Part[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (search: string) => {
      setLoading(true);
      setError(null);
      try {
        const page = await client.request<Paginated<Part>>('/parts/', {query: {search, page_size: 50}});
        setItems(page.results);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'Cannot load the inventory.');
      } finally {
        setLoading(false);
      }
    },
    [client],
  );

  useEffect(() => {
    void load('');
  }, [load]);

  return (
    <View style={s.screen}>
      <View style={[s.pad, {paddingBottom: 0}]}>
        <TextInput
          style={s.input}
          placeholder="Search part number, name or description"
          value={query}
          onChangeText={setQuery}
          onSubmitEditing={() => load(query)}
          returnKeyType="search"
          accessibilityLabel="Search spare parts"
        />
        {error && (
          <View style={s.error} accessibilityRole="alert">
            <Text style={s.errorText}>{error}</Text>
          </View>
        )}
      </View>
      <FlatList
        contentContainerStyle={s.pad}
        data={items}
        keyExtractor={p => p.id}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => load(query)} />}
        ListEmptyComponent={loading ? <ActivityIndicator /> : <Text style={s.muted}>No spare parts found.</Text>}
        renderItem={({item}) => (
          <Pressable
            style={s.card}
            accessibilityRole="button"
            onPress={() => item.passport_id && navigation.navigate('Passport', {id: item.passport_id, title: item.part_number})}>
            <Text style={s.h2}>{item.part_number}</Text>
            <Text style={s.text}>{item.name}</Text>
            {!!item.dimensions && <Text style={s.muted}>{item.dimensions}</Text>}
            <View style={s.badge}>
              <Text style={s.badgeText}>{item.passport_id ? 'Digital passport' : 'No passport yet'}</Text>
            </View>
          </Pressable>
        )}
      />
    </View>
  );
}
