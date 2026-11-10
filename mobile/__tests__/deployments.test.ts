import {DeploymentError, staticRegistry, validateApiBaseUrl} from '../src/config/deployments';

describe('validateApiBaseUrl', () => {
  it('accepts HTTPS and normalises to the origin', () => {
    expect(validateApiBaseUrl('https://passport.example.com/some/path', false)).toBe('https://passport.example.com');
  });

  it('rejects plain HTTP outside development', () => {
    expect(() => validateApiBaseUrl('http://passport.example.com', false)).toThrow(DeploymentError);
    expect(() => validateApiBaseUrl('http://10.0.2.2:8000', false)).toThrow('Deployments must use HTTPS.');
  });

  it('allows HTTP only for local development hosts', () => {
    expect(validateApiBaseUrl('http://10.0.2.2:8000', true)).toBe('http://10.0.2.2:8000');
    expect(validateApiBaseUrl('http://localhost:8000', true)).toBe('http://localhost:8000');
    expect(() => validateApiBaseUrl('http://192.168.1.20:8000', true)).toThrow('Deployments must use HTTPS.');
  });

  it('rejects malformed URLs and embedded credentials', () => {
    expect(() => validateApiBaseUrl('not a url', true)).toThrow('not a valid URL');
    expect(() => validateApiBaseUrl('https://user:pw@passport.example.com', false)).toThrow('Credentials');
  });
});

describe('staticRegistry', () => {
  it('validates entries and looks deployments up by id', () => {
    const reg = staticRegistry([{id: 'shared', name: 'Shared', kind: 'shared', apiBaseUrl: 'https://a.example.com/'}], false);
    expect(reg.get('shared').apiBaseUrl).toBe('https://a.example.com');
    expect(() => reg.get('other')).toThrow('Unknown deployment');
  });

  it('refuses an insecure deployment at construction', () => {
    expect(() => staticRegistry([{id: 'x', name: 'X', kind: 'dedicated', apiBaseUrl: 'http://x.example.com'}], false)).toThrow(
      DeploymentError,
    );
  });
});
