import type { NextRequest } from 'next/server';

// The manifest lists maskable icons for Android only. Safari and Chromium on desktop
// both read a listed maskable icon and only Chromium crops it, so a desktop install
// gets the standard icons alone and shows the same size in both (app-icons skill,
// "Maskable icons"). Android launchers need the maskable icon to fill their shapes.

const BASE = __BASE__;

const STANDARD = [
  { src: '/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
  { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
];

const MASKABLE = [
  { src: '/icon-maskable-192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
  { src: '/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
];

// The platform client hint is sent by Chromium-based browsers by default; others
// are judged by the user agent.
function isAndroid(headers: Headers): boolean {
  const platform = headers.get('sec-ch-ua-platform');
  if (platform) return platform.replace(/"/g, '').toLowerCase() === 'android';
  return /\bandroid\b/i.test(headers.get('user-agent') ?? '');
}

export function GET(request: NextRequest): Response {
  const icons = isAndroid(request.headers) ? [...STANDARD, ...MASKABLE] : STANDARD;
  return new Response(JSON.stringify({ ...BASE, icons }), {
    headers: {
      'Content-Type': 'application/manifest+json',
      'Cache-Control': 'public, max-age=0, must-revalidate',
      Vary: 'Sec-CH-UA-Platform, User-Agent',
    },
  });
}
