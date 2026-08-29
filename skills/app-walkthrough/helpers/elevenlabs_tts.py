#!/usr/bin/env python3
"""Render narration to MP3 via ElevenLabs — the MANDATED narrator voice.

Usage: elevenlabs_tts.py <narration.txt> <out.mp3> [--speed 0.95] [--gap 0.7]
       [--voice-id <id>]

Voice: ElevenLabs "Charlie" (AU male), voice_id IKne3meq5aSn9XLyUdCD, at speed
0.95 by default — the house narrator for every walkthrough (SKILL.md
"Voice defaults"). This is the mandated voice; only override for a genuinely
different audience.

Same <break time="0.9s" /> pause handling as the OpenAI helper: each text chunk
is synthesised separately and joined with REAL generated silence, so the calm
comes from the pauses, not slow delivery (Hard Rule 2). Delivery pace is set by
ElevenLabs voice_settings.speed (0.7 slow — 1.2 fast); 0.95 = natural talk.

ELEVENLABS_API_KEY read from env or a .env next to the narration file.
OPENAI_API_KEY is still needed SEPARATELY for align_captions.py (Whisper).
Requires ffmpeg on PATH.
"""
import os, re, sys, json, subprocess, tempfile, urllib.request, urllib.error

CHARLIE_VOICE_ID = 'IKne3meq5aSn9XLyUdCD'  # ElevenLabs "Charlie" (AU male)
DEFAULT_SPEED = 0.95
DEFAULT_GAP = 0.7  # seconds of silence between lines without an explicit tag
MODEL_ID = os.environ.get('ELEVENLABS_MODEL', 'eleven_turbo_v2_5')


def load_env(path):
    env = {}
    if os.path.exists(path):
        for line in open(path):
            m = re.match(r'^([A-Z0-9_]+)=(.*)$', line.strip())
            if m:
                env[m.group(1)] = m.group(2)
    return env


def synth(text, key, voice_id, speed, out_path, attempts=3):
    payload = json.dumps({
        'text': text,
        'model_id': MODEL_ID,
        # speed lives in voice_settings; keep the voice steady + clear.
        'voice_settings': {'stability': 0.5, 'similarity_boost': 0.75, 'speed': speed},
    }).encode()
    for attempt in range(attempts):
        req = urllib.request.Request(
            f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128',
            data=payload,
            headers={'xi-api-key': key, 'Content-Type': 'application/json', 'Accept': 'audio/mpeg'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(req) as resp:
                open(out_path, 'wb').write(resp.read())
            return
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == attempts - 1:
                sys.stderr.write(e.read().decode('utf-8', 'ignore')[:500] + '\n')
                raise
            import time
            time.sleep(2 * (attempt + 1))


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    args = sys.argv[1:]
    narration_path, out_path = args[0], args[1]
    speed = float(args[args.index('--speed') + 1]) if '--speed' in args else DEFAULT_SPEED
    gap = float(args[args.index('--gap') + 1]) if '--gap' in args else DEFAULT_GAP
    voice_id = args[args.index('--voice-id') + 1] if '--voice-id' in args else CHARLIE_VOICE_ID

    skill_env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    key = (os.environ.get('ELEVENLABS_API_KEY')
           or load_env(os.path.join(os.path.dirname(os.path.abspath(narration_path)), '.env')).get('ELEVENLABS_API_KEY')
           or load_env(skill_env).get('ELEVENLABS_API_KEY'))
    if not key:
        sys.exit('ELEVENLABS_API_KEY not found (env, .env beside narration, or skill .env)')

    raw = open(narration_path).read().strip()
    parts = re.split(r'<break\s+time="([0-9.]+)s?"\s*/>', raw)
    chunks = []  # [(text, pause_after_seconds)]
    for i in range(0, len(parts), 2):
        text = parts[i].strip()
        pause = float(parts[i + 1]) if i + 1 < len(parts) else None
        if not text:
            if pause is not None and chunks:
                chunks[-1] = (chunks[-1][0], chunks[-1][1] + pause)
            continue
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for j, line in enumerate(lines):
            last_of_part = j == len(lines) - 1
            chunks.append((line, (pause if pause is not None else gap) if last_of_part else gap))
    if chunks:
        chunks[-1] = (chunks[-1][0], 0.0)

    with tempfile.TemporaryDirectory() as td:
        wavs = []
        for n, (text, pause) in enumerate(chunks):
            mp3 = os.path.join(td, f'c{n}.mp3')
            wav = os.path.join(td, f'c{n}.wav')
            synth(text, key, voice_id, speed, mp3)
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
             '-ar', '44100', '-ac', '1', '-b:a', '192k', out_path])
    print(f'wrote {out_path}, {len(chunks)} chunks, ElevenLabs Charlie @ speed {speed}')


if __name__ == '__main__':
    main()
