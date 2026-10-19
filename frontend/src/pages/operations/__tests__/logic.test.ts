import { describe, expect, it } from 'vitest';
import {
  choiceToSpec,
  cpuCores,
  defaultSpec,
  errorsForStep,
  mapServerErrors,
  memBytes,
  mergeSpec,
  repoBasename,
  sanitizeName,
  splitImage,
  suggestDestination,
  toPayload,
  validateSpec,
  type DeploySpec,
} from '../logic';

function valid(): DeploySpec {
  return { ...defaultSpec(), name: 'web', namespace: 'prod', image: 'nginx', tag: '1.27', port: 80 };
}

describe('quantities', () => {
  it('parses cpu', () => {
    expect(cpuCores('250m')).toBe(0.25);
    expect(cpuCores('2')).toBe(2);
    expect(cpuCores('0.5')).toBe(0.5);
    expect(cpuCores('1.2345')).toBeNull();
    expect(cpuCores('abc')).toBeNull();
  });
  it('parses memory', () => {
    expect(memBytes('1Gi')).toBe(2 ** 30);
    expect(memBytes('256Mi')).toBe(256 * 2 ** 20);
    expect(memBytes('1G')).toBe(1e9);
    expect(memBytes('1.5Gi')).toBeNull();
    expect(memBytes('12KB')).toBeNull();
  });
});

describe('names and images', () => {
  it('sanitizes names to DNS-1123', () => {
    expect(sanitizeName('My_App.Server')).toBe('my-app-server');
    expect(sanitizeName('--Ciao Città--')).toBe('ciao-citta');
    expect(sanitizeName('___')).toBe('app');
    expect(sanitizeName('a'.repeat(80))).toHaveLength(50);
    expect(sanitizeName('x'.repeat(49) + '-yz')).toBe('x'.repeat(49));
  });
  it('splits image references', () => {
    expect(splitImage('nginx:1.27')).toEqual({ image: 'nginx', tag: '1.27' });
    expect(splitImage('registry:5000/team/app')).toEqual({ image: 'registry:5000/team/app', tag: '' });
    expect(splitImage('registry:5000/team/app:2.0')).toEqual({ image: 'registry:5000/team/app', tag: '2.0' });
    expect(splitImage('app@sha256:abc')).toEqual({ image: 'app', tag: 'sha256:abc' });
    expect(repoBasename('quay.io/prometheus/node-exporter:v1.8.2')).toBe('node-exporter');
  });
});

describe('validateSpec', () => {
  it('accepts a valid spec', () => {
    expect(validateSpec(valid())).toEqual({});
  });
  it('rejects bad names, image with tag and bad quantities', () => {
    const e = validateSpec({ ...valid(), name: 'Web_App', image: 'nginx:1.2', cpu_request: '1.2345', memory_limit: '1.5Gi' });
    expect(e.name).toBe('dnsLabel');
    expect(e.image).toBe('tagInImage');
    expect(e.cpu_request).toBe('cpuFormat');
    expect(e.memory_limit).toBe('memFormat');
  });
  it('checks request <= limit', () => {
    expect(validateSpec({ ...valid(), cpu_request: '2', cpu_limit: '500m' }).cpu_limit).toBe('requestOverLimit');
    expect(validateSpec({ ...valid(), memory_request: '1Gi', memory_limit: '512Mi' }).memory_limit).toBe('requestOverLimit');
  });
  it('checks networking rules', () => {
    const s = valid();
    s.port = null;
    expect(validateSpec(s)['networking.service_type']).toBe('serviceNeedsPort');
    const n = valid();
    n.networking.node_port = 31000;
    expect(validateSpec(n)['networking.node_port']).toBe('nodePortType');
    n.networking.service_type = 'NodePort';
    n.networking.node_port = 80;
    expect(validateSpec(n)['networking.node_port']).toBe('nodePortRange');
    const i = valid();
    i.networking.ingress.enabled = true;
    expect(validateSpec(i)['networking.ingress.host']).toBe('required');
    i.networking.service_type = 'none';
    expect(validateSpec(i)['networking.ingress.enabled']).toBe('ingressNeedsService');
  });
  it('checks probes, storage and env', () => {
    const s = valid();
    s.port = null;
    s.networking.service_type = 'none';
    s.readiness.type = 'http';
    s.storage.enabled = true;
    s.storage.mount_path = '/';
    s.env = [{ name: '1BAD', value: '' }, { name: 'A', value: '' }, { name: 'A', value: '' }];
    const e = validateSpec(s);
    expect(e['readiness.port']).toBe('probeNeedsPort');
    expect(e['storage.mount_path']).toBe('mountPath');
    expect(e['env.0']).toBe('envName');
    expect(e.env).toBe('envDuplicate');
  });
  it('groups errors by wizard step', () => {
    const e = validateSpec({ ...valid(), name: '', cpu_request: 'x' });
    expect(Object.keys(errorsForStep(e, 'name'))).toEqual(['name']);
    expect(Object.keys(errorsForStep(e, 'cpu'))).toEqual(['cpu_request']);
    expect(errorsForStep(e, 'storage')).toEqual({});
  });
});

describe('onboarding → deploy', () => {
  const cfg = { exposedPorts: [{ port: 8080, protocol: 'TCP' }], volumes: ['/var/lib/app'], user: '1001', runsAsRoot: false, env: [] };
  it('suggests destination from image config', () => {
    const c = suggestDestination('registry.example.com/shop/Order_Api:2.1', cfg);
    expect(c.name).toBe('order-api');
    expect(c.port).toBe(8080);
    expect(c.storage).toBe(true);
    expect(c.mountPath).toBe('/var/lib/app');
    expect(c.probe).toBe('tcp');
    expect(c.replicas).toBe(2);
  });
  it('maps the choice to a valid deploy spec', () => {
    const spec = choiceToSpec(suggestDestination('registry.example.com/shop/api:2.1', cfg), cfg);
    expect(spec.image).toBe('registry.example.com/shop/api');
    expect(spec.tag).toBe('2.1');
    expect(spec.storage.enabled).toBe(true);
    expect(spec.readiness.type).toBe('tcp');
    expect(spec.networking.service_type).toBe('ClusterIP');
    expect(validateSpec(spec)).toEqual({});
  });
  it('handles images without ports or tags', () => {
    const c = suggestDestination('busybox', null);
    const spec = choiceToSpec(c, null);
    expect(spec.tag).toBe('latest');
    expect(spec.port).toBeNull();
    expect(spec.networking.service_type).toBe('none');
    expect(spec.readiness.type).toBe('none');
    expect(validateSpec(spec)).toEqual({});
  });
  it('merges partial prefill and builds payload', () => {
    const s = mergeSpec(defaultSpec(), { name: 'x', networking: { service_type: 'NodePort' } as DeploySpec['networking'] });
    expect(s.name).toBe('x');
    expect(s.networking.service_type).toBe('NodePort');
    expect(s.networking.ingress.path).toBe('/');
    const p = toPayload({ ...valid(), cpu_limit: '  ', image_pull_secret: '' });
    expect(p.cpu_limit).toBeNull();
    expect(p.image_pull_secret).toBeNull();
  });
  it('maps server validation errors', () => {
    expect(mapServerErrors([{ field: 'body.networking.node_port', message: 'bad' }, { message: 'x' }])).toEqual({ 'networking.node_port': 'bad' });
  });
});
