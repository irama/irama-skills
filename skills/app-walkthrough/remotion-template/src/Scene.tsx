import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Easing,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import boxesData from '../public/boxes.json';
import timing from '../public/timing.json';
import scene from '../public/scene.json';

/**
 * Config-driven walkthrough scene. Output is ALWAYS 16:9 (1920×1080): portrait
 * (phone) captures are centred and letterboxed with black side-bars, landscape
 * (desktop) captures fill the width with black top/bottom bars. Never stretched,
 * never white bars. Aspect is inferred from boxes.json viewport.
 *
 * All beats live in scene.json:
 * {
 *   fps, theme: {bg, accent, deviceBg, captionColor, captionSize?, captionBottom?},
 *   deviceScaleFactor, screenWidthPx?,             // optional explicit content width; else auto-fit
 *   shots:      [{src, atWord, edge?, offset?}],   // atWord: substring of a narration word ('' = 0)
 *   cursor:     [{atWord, edge?, offset?, target|idle}], // target = box name from boxes.json
 *   clicks:     [{atWord, edge?, offset?}],
 *   highlights: [{target, fromWord, toWord, fromOffset?, toOffset?}],
 * }
 * Word anchors resolve against timing.json (force-aligned verbatim script),
 * so re-pacing the narration re-times the whole scene automatically.
 */

const FPS = scene.fps ?? 30;
// HARD RULE: every walkthrough renders 16:9 (1920×1080), whatever the capture
// aspect. Portrait (phone) captures are centred and letterboxed with black
// side-bars; landscape (desktop) captures fill the width with black top/bottom
// bars. Never stretch, never white bars.
const CANVAS = { w: 1920, h: 1080 };
const THEME = {
  bg: '#000000', // pure-black letterbox field
  accent: '#D1B561',
  deviceBg: '#05080f',
  captionColor: '#F4F1E8',
  ...(scene.theme ?? {}),
};
const DSF = scene.deviceScaleFactor ?? 2;

const SHOT_W = boxesData.viewport.width * DSF;
const SHOT_H = boxesData.viewport.height * DSF;
const IS_PORTRAIT = boxesData.viewport.height > boxesData.viewport.width;

// Reserve a black band at the bottom for captions so they never overlap the
// app's own bottom bar / nav. Content is centred in the area ABOVE the band.
const CAPTION_BAND = 132;
const CONTENT_H = CANVAS.h - CAPTION_BAND;

// Fit the capture inside the content area, contain-style (whole shot visible,
// black bars fill the rest). Portrait (phone) → tall, black side-bars.
// Landscape (desktop) → wide, thin black top/bottom bars. An explicit
// scene.screenWidthPx still wins if a scene wants a specific width.
const PORTRAIT_FILL = 0.96; // of the content-area height
const LANDSCAPE_FILL = 0.94; // of the canvas width
const fitByHeight = (CONTENT_H * PORTRAIT_FILL) / SHOT_H;
const fitByWidth = (CANVAS.w * LANDSCAPE_FILL) / SHOT_W;
const DISP = scene.screenWidthPx
  ? scene.screenWidthPx / SHOT_W
  : IS_PORTRAIT
    ? fitByHeight
    : Math.min(fitByWidth, (CONTENT_H * 0.98) / SHOT_H); // desktop: don't exceed content height
const PHONE_W = SHOT_W * DISP;
const PHONE_H = SHOT_H * DISP;
const OX = (CANVAS.w - PHONE_W) / 2;
const OY = (CONTENT_H - PHONE_H) / 2;

type Box = { x: number; y: number; width: number; height: number };
type Pt = { x: number; y: number };

function toCanvas(b: Box) {
  const k = DSF * DISP;
  return { x: OX + b.x * k, y: OY + b.y * k, w: b.width * k, h: b.height * k };
}
function centerOf(name: string): Pt {
  const r = toCanvas((boxesData.boxes as Record<string, Box>)[name]);
  return { x: r.x + r.w / 2, y: r.y + r.h / 2 };
}

const WORDS = timing.words as { word: string; start: number; end: number }[];
const DUR = (timing as { duration: number }).duration;
function anchor(sub: string, edge: 'start' | 'end' = 'start'): number {
  if (!sub) return 0;
  const w = WORDS.find((x) => x.word.toLowerCase().includes(sub.toLowerCase()));
  if (!w) throw new Error(`anchor word not found in timing: "${sub}"`);
  return w[edge];
}
const S = (s: number) => Math.round(s * FPS);
// Cursor rest position: bottom-centre of the content area. Always computed from
// the current 16:9 geometry (scene.json.idle, if present, is ignored — it would
// be in stale pre-letterbox coordinates).
const IDLE: Pt = { x: CANVAS.w / 2, y: OY + PHONE_H - 120 };

type CursorKey = { t: number; p: Pt };
const cursorKeys: CursorKey[] = (scene.cursor as {
  atWord: string; edge?: 'start' | 'end'; offset?: number; target?: string; idle?: boolean;
}[]).map((c) => ({
  t: anchor(c.atWord, c.edge ?? 'start') + (c.offset ?? 0),
  p: c.idle ? IDLE : centerOf(c.target as string),
}));

const CLICKS: number[] = (scene.clicks as { atWord: string; edge?: 'start' | 'end'; offset?: number }[]).map(
  (c) => anchor(c.atWord, c.edge ?? 'start') + (c.offset ?? 0)
);

const HILITES = (scene.highlights as {
  target: string; fromWord: string; toWord: string; fromOffset?: number; toOffset?: number;
}[]).map((h) => ({
  name: h.target,
  from: anchor(h.fromWord, 'start') + (h.fromOffset ?? 0),
  to: anchor(h.toWord, 'end') + (h.toOffset ?? 0),
}));

const SHOTS = (scene.shots as { src: string; atWord: string; edge?: 'start' | 'end'; offset?: number }[]).map(
  (s) => ({ src: s.src, from: s.atWord ? anchor(s.atWord, s.edge ?? 'start') + (s.offset ?? 0) : 0 })
);

// Cursor pacing: a quick flick between stops, then a long dwell. Continuous
// gliding across the whole gap reads unnaturally slow; instead the cursor
// HOLDS on its current target and travels only in the last TRAVEL_S seconds
// before the next anchor, so the viewer gets time to take each stop in.
const TRAVEL_S = 0.55;

function interpKeys(frame: number, keys: CursorKey[]) {
  const sorted = [...keys].sort((a, b) => a.t - b.t);
  const times: number[] = [];
  const xs: number[] = [];
  const ys: number[] = [];
  sorted.forEach((k, i) => {
    if (i > 0) {
      const prev = sorted[i - 1];
      const holdT = Math.max(prev.t + 0.05, k.t - TRAVEL_S);
      const holdF = S(holdT);
      if (holdF > (times[times.length - 1] ?? -1)) {
        times.push(holdF);
        xs.push(prev.p.x);
        ys.push(prev.p.y);
      }
    }
    let f = S(k.t);
    if (f <= (times[times.length - 1] ?? -1)) f = (times[times.length - 1] ?? 0) + 1;
    times.push(f);
    xs.push(k.p.x);
    ys.push(k.p.y);
  });
  const opts = {
    extrapolateLeft: 'clamp' as const,
    extrapolateRight: 'clamp' as const,
    easing: Easing.inOut(Easing.cubic),
  };
  return {
    x: interpolate(frame, times, xs, opts),
    y: interpolate(frame, times, ys, opts),
  };
}

const Cursor: React.FC = () => {
  const frame = useCurrentFrame();
  const { x, y } = interpKeys(frame, cursorKeys);
  let scale = 1;
  for (const c of CLICKS) {
    const d = frame - S(c);
    if (d >= 0 && d <= 8) scale = Math.min(scale, interpolate(d, [0, 4, 8], [1, 0.72, 1]));
  }
  return (
    <div
      style={{
        position: 'absolute', left: x, top: y,
        transform: `translate(-6px,-4px) scale(${scale})`,
        transformOrigin: 'top left',
        filter: 'drop-shadow(0 4px 6px rgba(0,0,0,0.45))', zIndex: 40,
      }}
    >
      <svg width="54" height="54" viewBox="0 0 24 24" fill="none">
        <path
          d="M4 2 L4 18 L8.5 13.8 L11.2 20 L13.8 18.9 L11.1 12.8 L17 12.6 Z"
          fill={THEME.captionColor} stroke={THEME.bg} strokeWidth="1.1" strokeLinejoin="round"
        />
      </svg>
    </div>
  );
};

const ClickRing: React.FC = () => {
  const frame = useCurrentFrame();
  const { x, y } = interpKeys(frame, cursorKeys);
  return (
    <>
      {CLICKS.map((c, i) => {
        const d = frame - S(c);
        if (d < 0 || d > 14) return null;
        const r = interpolate(d, [0, 14], [6, 46]);
        const o = interpolate(d, [0, 14], [0.55, 0]);
        return (
          <div key={i} style={{
            position: 'absolute', left: x - r, top: y - r, width: r * 2, height: r * 2,
            borderRadius: '50%', border: `3px solid ${THEME.accent}`, opacity: o, zIndex: 39,
          }} />
        );
      })}
    </>
  );
};

const Highlights: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <>
      {HILITES.map((h, i) => {
        const from = S(h.from);
        const to = S(h.to);
        if (frame < from - 6 || frame > to + 6) return null;
        const r = toCanvas((boxesData.boxes as Record<string, Box>)[h.name]);
        const appear = spring({ frame: frame - from, fps, config: { damping: 200 }, durationInFrames: 8 });
        const out = interpolate(frame, [to, to + 6], [1, 0], {
          extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
        });
        const pad = 8;
        return (
          <div key={i} style={{
            position: 'absolute', left: r.x - pad, top: r.y - pad,
            width: r.w + pad * 2, height: r.h + pad * 2,
            border: `3px solid ${THEME.accent}`, borderRadius: 14,
            boxShadow: `0 0 0 4px ${THEME.accent}2e, 0 0 22px ${THEME.accent}59`,
            opacity: Math.min(appear, out),
            transform: `scale(${interpolate(appear, [0, 1], [1.06, 1])})`, zIndex: 30,
          }} />
        );
      })}
    </>
  );
};

// Caption blocks — HARD RULE: never move a word once it is on screen. A whole
// sentence (or comma-broken chunk of a long one) appears at once, the current
// word highlights in place, then the block swaps for the next sentence. No
// rolling window, no sideways ticker.
type CapWord = { word: string; start: number; end: number };
const CAP_MAX_WORDS = 10; // fits two 44px lines in the caption band

function buildCaptionBlocks(words: CapWord[]) {
  const groups: CapWord[][] = [];
  let cur: CapWord[] = [];
  for (const w of words) {
    cur.push(w);
    const terminal = /[.!?]$/.test(w.word);
    const commaBreak = cur.length >= 6 && /,$/.test(w.word);
    if (terminal || commaBreak || cur.length >= CAP_MAX_WORDS) {
      groups.push(cur);
      cur = [];
    }
  }
  if (cur.length) groups.push(cur);
  // A block holds until the next block's first word (no flash gaps).
  return groups.map((ws, i, arr) => ({
    words: ws,
    from: ws[0].start - 0.15,
    to: i < arr.length - 1 ? arr[i + 1][0].start - 0.15 : ws[ws.length - 1].end + 0.5,
  }));
}
const CAP_BLOCKS = buildCaptionBlocks(WORDS as CapWord[]);

const Caption: React.FC = () => {
  const frame = useCurrentFrame();
  const t = frame / FPS;
  const block = CAP_BLOCKS.find((b) => t >= b.from && t < b.to);
  if (!block) return null;
  // Whole-block fade only — individual words never move or reflow.
  const opacity = interpolate(t - block.from, [0, 0.18], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  // Exactly ONE word highlighted at a time: the latest word that has started.
  // (A trailing window would keep the previous word lit into the next one.)
  let activeIdx = -1;
  block.words.forEach((w, i) => {
    if (t >= w.start - 0.05) activeIdx = i;
  });
  return (
    <div style={{
      position: 'absolute', bottom: 0, height: CAPTION_BAND, left: 80, right: 80,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      textAlign: 'center', flexWrap: 'wrap',
      fontFamily: 'Inter, system-ui, sans-serif',
      fontSize: (THEME as { captionSize?: number }).captionSize ?? 44, lineHeight: 1.2,
      fontWeight: 500, color: THEME.captionColor,
      textShadow: '0 2px 10px rgba(0,0,0,0.6)', zIndex: 50, opacity,
    }}>
      {block.words.map((w, i) => (
        <span key={i} style={{
          color: i === activeIdx ? THEME.accent : THEME.captionColor,
          marginRight: 10,
        }}>
          {w.word}
        </span>
      ))}
    </div>
  );
};

export const Scene: React.FC = () => {
  const frame = useCurrentFrame();
  // Portrait phones get a device bezel; landscape (desktop) shots get a thin
  // rounded frame. Both sit on the pure-black letterbox field.
  const bezel = IS_PORTRAIT ? 14 : 8;
  const radius = IS_PORTRAIT ? 34 : 12;
  return (
    <AbsoluteFill style={{ backgroundColor: THEME.bg }}>
      <div style={{
        position: 'absolute', left: OX - bezel, top: OY - bezel,
        width: PHONE_W + bezel * 2, height: PHONE_H + bezel * 2,
        borderRadius: radius + bezel,
        background: THEME.deviceBg, boxShadow: '0 24px 70px rgba(0,0,0,0.6)',
      }} />
      <div style={{
        position: 'absolute', left: OX, top: OY, width: PHONE_W, height: PHONE_H,
        borderRadius: radius, overflow: 'hidden',
      }}>
        {SHOTS.map((s, i) => {
          const from = S(s.from);
          const fade = interpolate(frame, [from, from + 6], [0, 1], {
            extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
          });
          return (
            <Img key={i} src={staticFile(s.src)} style={{
              position: 'absolute', inset: 0, width: '100%', height: '100%',
              objectFit: 'cover', opacity: i === 0 ? 1 : fade,
            }} />
          );
        })}
      </div>
      <Highlights />
      <ClickRing />
      <Cursor />
      <Caption />
      <Audio src={staticFile('narration.mp3')} />
    </AbsoluteFill>
  );
};

export const sceneDuration = DUR;
