import {NavigationContainer} from '@react-navigation/native';
import {createNativeStackNavigator} from '@react-navigation/native-stack';
import React from 'react';
import {ActivityIndicator, Pressable, Text, View} from 'react-native';

import {useAuth} from '../auth/AuthContext';
import InventoryScreen from '../screens/InventoryScreen';
import PassportScreen from '../screens/PassportScreen';
import SignInScreen from '../screens/SignInScreen';
import {colors} from '../ui/theme';
import type {RootStack} from './types';

const Stack = createNativeStackNavigator<RootStack>();

function SignOutButton() {
  const {logout} = useAuth();
  return (
    <Pressable onPress={() => void logout()} accessibilityRole="button" hitSlop={8}>
      <Text style={{color: '#fff', fontWeight: '600'}}>Sign out</Text>
    </Pressable>
  );
}

export default function RootNavigator() {
  const {session, ready} = useAuth();
  if (!ready) {
    return (
      <View style={{flex: 1, justifyContent: 'center'}}>
        <ActivityIndicator />
      </View>
    );
  }
  return (
    <NavigationContainer>
      <Stack.Navigator
        screenOptions={{headerStyle: {backgroundColor: colors.brand}, headerTintColor: '#fff', headerTitleStyle: {fontWeight: '600'}}}>
        {session ? (
          <>
            <Stack.Screen
              name="Inventory"
              component={InventoryScreen}
              options={{title: session.tenant.name, headerRight: SignOutButton}}
            />
            <Stack.Screen name="Passport" component={PassportScreen} options={({route}) => ({title: route.params.title})} />
          </>
        ) : (
          <Stack.Screen name="SignIn" component={SignInScreen} options={{headerShown: false}} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
