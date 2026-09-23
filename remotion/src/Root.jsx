import { Composition } from 'remotion';
import Demo from './Demo.jsx';
import { FPS, HEIGHT, WIDTH, layout } from './clips.js';

export const RemotionRoot = () => {
  const { totalFrames } = layout();
  return (
    <Composition
      id="Demo"
      component={Demo}
      durationInFrames={totalFrames}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
    />
  );
};
