import { describe, expect, it } from 'vitest';
import type { NextRequest } from 'next/server';
import { GET } from './route';

const MAC_CHROME =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
const MAC_SAFARI =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15';
const ANDROID_CHROME =
  'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36';

const purposes = async (headers: Record<string, string>) => {
  // A plain Headers object: building a Request in a browser-like test environment
  // drops Sec-* headers, and the route only reads the headers.
  const res = GET({ headers: new Headers(headers) } as unknown as NextRequest);
  const body = (await res.json()) as { icons: { purpose: string }[] };
  return body.icons.map((i) => i.purpose);
};

describe('GET /manifest.webmanifest', () => {
  it('lists no maskable icon for desktop browsers, so Safari and Chromium show one size', async () => {
    expect(
      await purposes({ 'user-agent': MAC_CHROME, 'sec-ch-ua-platform': '"macOS"' })
    ).not.toContain('maskable');
    expect(await purposes({ 'user-agent': MAC_SAFARI })).not.toContain('maskable');
  });

  it('adds the maskable icons for Android, by client hint or by user agent', async () => {
    expect(await purposes({ 'sec-ch-ua-platform': '"Android"' })).toContain('maskable');
    expect(await purposes({ 'user-agent': ANDROID_CHROME })).toContain('maskable');
  });

  it('trusts the platform hint over the user agent', async () => {
    expect(
      await purposes({ 'user-agent': ANDROID_CHROME, 'sec-ch-ua-platform': '"Windows"' })
    ).not.toContain('maskable');
  });

  it('is a manifest that caches per platform', () => {
    const res = GET({ headers: new Headers() } as unknown as NextRequest);
    expect(res.headers.get('content-type')).toBe('application/manifest+json');
    expect(res.headers.get('vary')).toBe('Sec-CH-UA-Platform, User-Agent');
  });
});
