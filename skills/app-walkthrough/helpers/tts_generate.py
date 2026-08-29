#!/usr/bin/env python3
"""Render narration to MP3 via OpenAI TTS (gpt-4o-mini-tts).

Usage: tts_generate.py <narration.txt> <out.mp3> [--voice NAME] [--gap 0.7]

Narration may contain <break time="0.9s" /> tags between lines (the historic
pause notation — kept). Pauses are rendered as REAL silence: each text chunk
is synthesised separately and joined with generated silence of the requested
duration (default --gap seconds between lines with no explicit tag). This
keeps the calm, deliberate pacing the Foreman's voice needs — OpenAI TTS has
no SSML breaks, so we build them in the container.

OPENAI_API_KEY read from env or a .env next to the narration file.
Default voice: ash. Accent/pace shaped via the instructions prompt below.
Requires ffmpeg on PATH (same requirement the pipeline already has).
"""
import os, re, sys, json, subprocess, tempfile, urllib.request

DEFAULT_VOICE = 'ash'
DEFAULT_MODEL = os.environ.get('OPENAI_TTS_MODEL', 'gpt-4o-mini-tts')
DEFAULT_GAP = 0.7  # seconds of silence between lines without an explicit tag
INSTRUCTIONS = (
    'Australian accent. Calm and plain — a foreman explaining a job to an '
    'offsider. Speak at a NORMAL conversational pace, the natural speed of '
    'everyday talk — do NOT slow down, drag words, or over-enunciate. The calm '
    'comes from the pauses BETWEEN phrases (rendered as real silence), not from '
    'slow delivery. No enthusiasm, no upspeak; let full stops land, then move on.'
)


def load_env(path):
    env = {}
    if os.path.exists(path):
        for line in open(path):
            m = re.match(r'^([A-Z0-9_]+)=(.*)$', line.strip())
            if m:
                env[m.group(1)] = m.group(2)
    return env


def synth(text, key, voice, out_path, attempts=3):
    payload = json.dumps({
        'model': DEFAULT_MODEL,
        'voice': voice,
        'input': text,
        'instructions': INSTRUCTIONS,
        'response_format': 'mp3',
    }).encode()
    for attempt in range(attempts):
        req = urllib.request.Request(
            'https://api.openai.com/v1/audio/speech',
            data=payload,
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(req) as resp:
                open(out_path, 'wb').write(resp.read())
            return
        except urllib.error.HTTPError as e:
            # 5xx are transient on this endpoint; 4xx are our fault — fail fast.
            if e.code < 500 or attempt == attempts - 1:
                raise
            import time
            time.sleep(2 * (attempt + 1))


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    args = sys.argv[1:]
    narration_path, out_path = args[0], args[1]
    voice = args[args.index('--voice') + 1] if '--voice' in args else DEFAULT_VOICE
    gap = float(args[args.index('--gap') + 1]) if '--gap' in args else DEFAULT_GAP

    key = os.environ.get('OPENAI_API_KEY') or load_env(
        os.path.join(os.path.dirname(os.path.abspath(narration_path)), '.env')
    ).get('OPENAI_API_KEY')
    if not key:
        sys.exit('OPENAI_API_KEY not found (env or .env beside narration file)')

    raw = open(narration_path).read().strip()
    # Split into (text, pause_after) chunks. Explicit break tags win; plain
    # newlines between lines get the default gap.
    parts = re.split(r'<break\s+time="([0-9.]+)s?"\s*/>', raw)
    chunks = []  # [(text, pause_after_seconds)]
    for i in range(0, len(parts), 2):
        text = parts[i].strip()
        pause = float(parts[i + 1]) if i + 1 < len(parts) else None
        if not text:
            # tag adjacent to another tag — add its pause to the previous chunk
            if pause is not None and chunks:
                chunks[-1] = (chunks[-1][0], chunks[-1][1] + pause)
            continue
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for j, line in enumerate(lines):
            last_of_part = j == len(lines) - 1
            chunks.append((line, (pause if pause is not None else gap) if last_of_part else gap))
    if chunks:
        chunks[-1] = (chunks[-1][0], 0.0)  # no trailing silence

    with tempfile.TemporaryDirectory() as td:
        wavs = []
        for n, (text, pause) in enumerate(chunks):
            mp3 = os.path.join(td, f'c{n}.mp3')
            wav = os.path.join(td, f'c{n}.wav')
            synth(text, key, voice, mp3)
            run(['ffmpeg', '-y', '-i', mp3, '-ar', '44100', '-ac', '1', wav])
            wavs.append(wav)
            if pause > 0:
                sil = os.path.join(td, f's{n}.wav')
                run(['ffmpeg', '-y', '-f', 'lavfi', '-i',
                     'anullsrc=r=44100:cl=mono', '-t', f'{pause}', sil])
                wavs.append(sil)
        lst = os.path.join(td, 'list.txt')
        open(lst, 'w').write('\n'.join(f"file '{w}'" for w in wavs))
        run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', lst,
             '-codec:a', 'libmp3lame', '-q:a', '2', out_path])

    print('wrote', out_path, os.path.getsize(out_path), 'bytes,',
          len(chunks), 'chunks, voice', voice)


if __name__ == '__main__':
    main()
