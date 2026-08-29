import { Composition } from 'remotion';
import { Scene } from './Scene';
import timing from '../public/timing.json';
import scene from '../public/scene.json';

const FPS = (scene as { fps?: number }).fps ?? 30;
const TAIL = 0.8; // hold at end
// HARD RULE: always 16:9. Portrait/desktop captures are letterboxed on black
// inside the Scene, never by changing these dimensions.
const durationInFrames = Math.ceil(((timing as { duration: number }).duration + TAIL) * FPS);

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Scene"
    component={Scene}
    durationInFrames={durationInFrames}
    fps={FPS}
    width={1920}
    height={1080}
  />
);
