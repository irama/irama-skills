#!/usr/bin/env python3
"""Word timings for a KNOWN narration script, via Whisper + force-alignment.

Whisper transcribes freely and sometimes mis-hears ("Tap"->"Tapped") or drops
quiet words. We know the exact script, so:
  1. call OpenAI whisper-1 (verbose_json, word granularity) for raw timings
  2. sequence-align script words <-> whisper words (difflib on normalized text)
  3. matched script words inherit whisper timings; unmatched script words get
     timings interpolated between their matched neighbours

Output timing.json: { duration, words: [{word, start, end}] } where `word` is
ALWAYS the verbatim script word. Captions/SRT built from this read exactly as
written; cursor anchors stay reliable.

Usage: align_captions.py <audio.mp3> <narration.txt> <out_timing.json>
OPENAI_API_KEY from env or .env beside the narration file.
"""
import os, re, sys, json, uuid, difflib, mimetypes, urllib.request


def load_env(path):
    env = {}
    if os.path.exists(path):
        for line in open(path):
            m = re.match(r'^([A-Z0-9_]+)=(.*)$', line.strip())
            if m:
                env[m.group(1)] = m.group(2)
    return env


def whisper(audio_path, key):
    boundary = uuid.uuid4().hex
    body = bytearray()

    def field(name, value):
        body.extend(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )

    field('model', 'whisper-1')
    field('response_format', 'verbose_json')
    field('timestamp_granularities[]', 'word')
    fn = os.path.basename(audio_path)
    mime = mimetypes.guess_type(fn)[0] or 'audio/mpeg'
    body.extend(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fn}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
    )
    body.extend(open(audio_path, 'rb').read())
    body.extend(f'\r\n--{boundary}--\r\n'.encode())
    req = urllib.request.Request(
        'https://api.openai.com/v1/audio/transcriptions',
        data=bytes(body),
        headers={'Authorization': f'Bearer {key}', 'Content-Type': f'multipart/form-data; boundary={boundary}'},
        method='POST',
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def norm(w):
    return re.sub(r'[^a-z0-9]', '', w.lower())


NUM_WORDS = {  # whisper often emits digits for spoken numbers
    '15': 'fifteen', '1': 'one', '2': 'two', '3': 'three', '4': 'four', '5': 'five',
    '10': 'ten', '20': 'twenty', '30': 'thirty', '50': 'fifty', '100': 'onehundred',
}


def norm2(w):
    n = norm(w)
    return NUM_WORDS.get(n, n)


def script_words(text):
    # strip <break/> pause tags and markup, keep verbatim words
    text = re.sub(r'<[^>]+>', ' ', text)
    return [w for w in re.split(r'\s+', text) if norm(w)]


def align(script, hyp):
    """Return per-script-word (start,end) using difflib matched blocks +
    linear interpolation across gaps."""
    a = [norm2(w) for w in script]
    b = [norm2(h['word']) for h in hyp]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    times = [None] * len(script)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            times[blk.a + k] = (hyp[blk.b + k]['start'], hyp[blk.b + k]['end'])
    # fill gaps by interpolation between matched neighbours
    n = len(times)
    i = 0
    while i < n:
        if times[i] is None:
            j = i
            while j < n and times[j] is None:
                j += 1
            left_end = times[i - 1][1] if i > 0 else 0.0
            right_start = times[j][0] if j < n else (hyp[-1]['end'] if hyp else left_end + (j - i) * 0.3)
            span = max(right_start - left_end, 0.12 * (j - i))
            step = span / (j - i)
            if step > 0.6:
                # big silence gap (a <break/>): right-align words against the
                # next matched word so captions don't appear mid-pause
                step = 0.35
                left_end = max(left_end, right_start - step * (j - i))
            for k in range(i, j):
                s = left_end + (k - i) * step
                times[k] = (s, s + step * 0.9)
            i = j
        else:
            i += 1
    return [{'word': w, 'start': round(t[0], 3), 'end': round(t[1], 3)} for w, t in zip(script, times)]


def main():
    audio_path, narration_path, out_path = sys.argv[1:4]
    key = os.environ.get('OPENAI_API_KEY') or load_env(
        os.path.join(os.path.dirname(os.path.abspath(narration_path)), '.env')
    ).get('OPENAI_API_KEY')
    if not key:
        sys.exit('OPENAI_API_KEY not found (env or .env beside narration file)')

    raw = whisper(audio_path, key)
    script = script_words(open(narration_path).read())
    words = align(script, raw.get('words', []))
    out = {'duration': raw.get('duration'), 'words': words, 'whisper_text': raw.get('text', '')}
    json.dump(out, open(out_path, 'w'), indent=2)
    matched = sum(1 for w, r in zip(words, raw.get('words', [])) )
    print('duration', out['duration'])
    print('script words', len(words), '| whisper words', len(raw.get('words', [])))
    for w in words:
        print(f"{w['start']:6.2f}-{w['end']:6.2f}  {w['word']}")


if __name__ == '__main__':
    main()
