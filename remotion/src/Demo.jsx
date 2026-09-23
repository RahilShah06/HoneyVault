import React from 'react';
import {
  AbsoluteFill,
  OffthreadVideo,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import { TransitionSeries, linearTiming } from '@remotion/transitions';
import { fade } from '@remotion/transitions/fade';
import { CLIPS, SEGMENTS, TRANSITION_FRAMES, layout } from './clips.js';

const ACCENT = '#38BDF8';
const INK = '#F1F5F9';
const BAR = 'rgba(10, 15, 25, 0.85)';
const FADE_FRAMES = 8; // ~270ms

const FONT =
  'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';

/** Title card. No footage - just what this is, before anything moves. */
function TitleCard() {
  const frame = useCurrentFrame();
  const rise = interpolate(frame, [0, 24], [18, 0], {
    extrapolateRight: 'clamp',
  });
  const fadeIn = interpolate(frame, [0, 20], [0, 1], {
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: '#080C14',
        justifyContent: 'center',
        alignItems: 'center',
        fontFamily: FONT,
      }}
    >
      <div
        style={{
          transform: `translateY(${rise}px)`,
          opacity: fadeIn,
          textAlign: 'center',
          maxWidth: 1340,
          padding: '0 80px',
        }}
      >
        <div
          style={{
            width: 72,
            height: 4,
            backgroundColor: ACCENT,
            margin: '0 auto 38px auto',
            borderRadius: 2,
          }}
        />
        <h1
          style={{
            color: INK,
            fontSize: 92,
            fontWeight: 700,
            letterSpacing: -2,
            margin: 0,
            lineHeight: 1.05,
          }}
        >
          Cloud HoneyVault
        </h1>
        <p
          style={{
            color: '#94A3B8',
            fontSize: 34,
            lineHeight: 1.45,
            margin: '30px 0 0 0',
            fontWeight: 400,
          }}
        >
          A shared drive that watches how people use it, scores the behaviour,
          and answers back.
        </p>
        <div
          style={{
            display: 'flex',
            gap: 26,
            justifyContent: 'center',
            marginTop: 54,
          }}
        >
          {[
            ['Adaptive decoys', 'Bait written per role, then cached'],
            ['Active response', 'Cross CRITICAL and you are served fiction'],
          ].map(([title, sub]) => (
            <div
              key={title}
              style={{
                borderLeft: `4px solid ${ACCENT}`,
                padding: '10px 0 10px 22px',
                textAlign: 'left',
                minWidth: 420,
              }}
            >
              <div style={{ color: INK, fontSize: 30, fontWeight: 600 }}>
                {title}
              </div>
              <div style={{ color: '#7C8CA5', fontSize: 23, marginTop: 8 }}>
                {sub}
              </div>
            </div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
}

/**
 * Bottom-third explainer. Styled as post-production chrome, deliberately
 * unlike the recorded app's own light theme so it never reads as part of it.
 */
function Caption({ text, durationInFrames }) {
  const frame = useCurrentFrame();
  const opacity = interpolate(
    frame,
    [
      0,
      FADE_FRAMES,
      Math.max(FADE_FRAMES, durationInFrames - FADE_FRAMES),
      durationInFrames,
    ],
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
  );

  return (
    <AbsoluteFill style={{ fontFamily: FONT }}>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 96,
          opacity,
          display: 'flex',
          justifyContent: 'center',
          padding: '0 96px',
        }}
      >
        <div
          style={{
            backgroundColor: BAR,
            borderLeft: `6px solid ${ACCENT}`,
            padding: '26px 38px',
            maxWidth: 1500,
            backdropFilter: 'blur(2px)',
          }}
        >
          <p
            style={{
              color: INK,
              fontSize: 33,
              lineHeight: 1.4,
              margin: 0,
              fontWeight: 500,
            }}
          >
            {text}
          </p>
        </div>
      </div>
    </AbsoluteFill>
  );
}

export default function Demo() {
  const { overlays } = layout();
  const transition = () => (
    <TransitionSeries.Transition
      presentation={fade()}
      timing={linearTiming({ durationInFrames: TRANSITION_FRAMES })}
    />
  );

  return (
    <AbsoluteFill style={{ backgroundColor: '#080C14' }}>
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={layout().titleFrames}>
          <TitleCard />
        </TransitionSeries.Sequence>
        {SEGMENTS.flatMap((seg) => [
          <React.Fragment key={`t-${seg.name}`}>{transition()}</React.Fragment>,
          <TransitionSeries.Sequence
            key={seg.name}
            durationInFrames={seg.durationInFrames}
          >
            <AbsoluteFill style={{ backgroundColor: '#080C14' }}>
              <OffthreadVideo
                src={staticFile(seg.src)}
                startFrom={seg.startFrom}
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              />
            </AbsoluteFill>
          </TransitionSeries.Sequence>,
        ])}
      </TransitionSeries>

      {overlays.map((o) => (
        <Sequence key={o.id} from={o.from} durationInFrames={o.durationInFrames}>
          <Caption text={o.caption} durationInFrames={o.durationInFrames} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
}

export { CLIPS };
