#!/usr/bin/env python3
"""Emit <name>.srt and <name>.md alongside <name>.mp4.

SRT is built from Whisper word timings (grouped into cue lines on pauses).
The .md manifest carries ffprobe technical metadata as YAML frontmatter plus a
human/AI-readable description of what the video teaches and shows.

Scene-specific narrative content is passed in via a sidecar JSON (meta.json) so
this generator stays reusable across videos (basis for the future ~/.claude skill).
"""
import os, re, sys, json, subprocess

BASE = os.path.dirname(os.path.abspath(__file__))


def ff_probe(mp4):
    out = subprocess.check_output([
        'ffprobe', '-v', 'error', '-print_format', 'json',
        '-show_format', '-show_streams', mp4,
    ])
    return json.loads(out)


def srt_ts(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(words, gap=0.7, max_words=6):
    """Group words into cues; break on silence gap or max length."""
    cues, cur = [], []
    for w in words:
        if cur:
            prev = cur[-1]
            if (w['start'] - prev['end'] > gap) or len(cur) >= max_words:
                cues.append(cur)
                cur = []
        cur.append(w)
    if cur:
        cues.append(cur)
    lines = []
    for i, c in enumerate(cues, 1):
        text = ' '.join(x['word'] for x in c)
        lines.append(f"{i}\n{srt_ts(c[0]['start'])} --> {srt_ts(c[-1]['end'])}\n{text}\n")
    return '\n'.join(lines)


def yaml_frontmatter(d):
    lines = ['---']
    def emit(k, v, indent=0):
        pad = '  ' * indent
        if isinstance(v, dict):
            lines.append(f"{pad}{k}:")
            for kk, vv in v.items():
                emit(kk, vv, indent + 1)
        elif isinstance(v, list):
            lines.append(f"{pad}{k}:")
            for item in v:
                lines.append(f"{pad}  - {item}")
        else:
            lines.append(f"{pad}{k}: {v}")
    for k, v in d.items():
        emit(k, v)
    lines.append('---')
    return '\n'.join(lines)


def main():
    mp4 = sys.argv[1]
    timing_path = sys.argv[2]
    meta_path = sys.argv[3]
    stem = os.path.splitext(mp4)[0]

    timing = json.load(open(timing_path))
    words = timing['words']
    meta = json.load(open(meta_path))

    # SRT
    srt = build_srt(words)
    open(stem + '.srt', 'w').write(srt)

    # ffprobe metadata
    pr = ff_probe(mp4)
    v = next(s for s in pr['streams'] if s['codec_type'] == 'video')
    a = next((s for s in pr['streams'] if s['codec_type'] == 'audio'), None)
    fmt = pr['format']
    dur = float(fmt.get('duration', timing.get('duration', 0)))
    fps_num, fps_den = (v.get('r_frame_rate', '30/1').split('/') + ['1'])[:2]
    fps = round(int(fps_num) / int(fps_den), 2)

    fm = {
        'title': meta['title'],
        'app': meta['app'],
        'feature': meta['feature'],
        'kind': 'app-walkthrough',
        'register': meta.get('register', 'product'),
        'narrator_voice': meta.get('voice', 'OpenAI ash (AU-instructed)'),
        'duration_seconds': round(dur, 2),
        'duration_hms': srt_ts(dur).split(',')[0],
        'video': {
            'width': v['width'],
            'height': v['height'],
            'fps': fps,
            'codec': v['codec_name'],
            'pix_fmt': v.get('pix_fmt', ''),
        },
        'audio': ({'codec': a['codec_name'], 'sample_rate': a.get('sample_rate', ''),
                   'channels': a.get('channels', '')} if a else 'none'),
        'file_bytes': int(fmt.get('size', 0)),
        'sidecars': [os.path.basename(stem) + '.srt', os.path.basename(stem) + '.md'],
        'routes_shown': meta.get('routes_shown', []),
        'reference_urls': meta.get('reference_urls', []),
        'pipeline': 'playwright-capture + elevenlabs-tts + whisper-word-timing + remotion',
        'generated': meta.get('generated', 'local'),
    }

    body = []
    body.append(f"# {meta['title']}\n")
    body.append(meta['summary'] + '\n')
    body.append('## What this teaches\n')
    for t in meta['teaches']:
        body.append(f"- {t}")
    body.append('\n## Context\n')
    body.append(meta['context'] + '\n')
    body.append('## Step-by-step (matches what is on screen)\n')
    for i, step in enumerate(meta['steps'], 1):
        body.append(f"{i}. **{step['at']}** — {step['text']}")
    body.append('\n## Narration (verbatim)\n')
    body.append('> ' + meta['narration'].replace('\n', ' ') + '\n')
    if meta.get('reference_urls'):
        body.append('## Reference (theory behind the feature)\n')
        for r in meta['reference_urls']:
            body.append(f"- {r}")
    body.append('')

    md = yaml_frontmatter(fm) + '\n\n' + '\n'.join(body)
    open(stem + '.md', 'w').write(md)
    print('wrote', stem + '.srt')
    print('wrote', stem + '.md')


if __name__ == '__main__':
    main()
