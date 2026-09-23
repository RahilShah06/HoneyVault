/**
 * The edit decision list.
 *
 * One entry per feature being explained. A feature can span several recorded
 * segments (an employee's screen, then the dashboard reacting to it) - those
 * stay separate video files but share one overlay, because they are one idea.
 *
 * `trimStart` drops the page load at the head of each recording; `trimEnd`
 * drops any tail left after the last thing worth watching. Durations come from
 * recordings/durations.json, measured with ffprobe.
 */
export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

export const TITLE_SECONDS = 10;
export const TRANSITION_FRAMES = 11; // ~370ms crossfade

const sec = (s) => Math.round(s * FPS);

/** Measured source durations, in seconds. */
const SOURCE = {
  '01-normal-use': 12.4,
  '01b-normal-use-admin': 6.32,
  '02-decoy': 7.2,
  '03-insider-hunting': 22.96,
  '04-dashboard-reacts': 17.32,
  '05-active-response-intruder': 8.2,
  '05b-active-response-honest': 7.96,
  '06-honeytoken-used': 14.04,
  '06b-honeytoken-admin': 15.56,
  '07-second-opinion': 16.08,
  '08-nothing-hidden': 22.04,
  '09-restricted-attempt': 5.52,
  '09b-failed-logins': 15.12,
  '09c-carryover-admin': 6.84,
};

/**
 * Head trims. Every recording opens on a blank page while the SPA boots; the
 * clips that resume a session also spend a beat on a redirect. Nothing of
 * substance happens before these marks.
 */
const TRIM_START = {
  '01-normal-use': 0.8,
  '01b-normal-use-admin': 1.2,
  '02-decoy': 1.2,
  '03-insider-hunting': 0.8,
  '04-dashboard-reacts': 1.2,
  '05-active-response-intruder': 1.2,
  '05b-active-response-honest': 1.2,
  '06-honeytoken-used': 1.2,
  '06b-honeytoken-admin': 1.2,
  '07-second-opinion': 1.2,
  '08-nothing-hidden': 1.0,
  '09-restricted-attempt': 1.2,
  '09b-failed-logins': 0.8,
  '09c-carryover-admin': 1.2,
};

const segment = (name, trimEnd = 0.2) => {
  const trimStart = TRIM_START[name] ?? 0.8;
  const duration = SOURCE[name] - trimStart - trimEnd;
  if (!(duration > 0.5)) {
    throw new Error(`segment ${name} trimmed to nothing (${duration}s)`);
  }
  return {
    name,
    src: `${name}.webm`,
    startFrom: sec(trimStart),
    durationInFrames: sec(duration),
  };
};

/**
 * Overlay copy explains the mechanism, not what is visibly happening - the
 * footage already shows that part.
 */
export const CLIPS = [
  {
    id: 'normal-use',
    caption:
      'Every user sees every folder — restriction here is behavioral, not an access wall.',
    segments: [segment('01-normal-use'), segment('01b-normal-use-admin')],
  },
  {
    id: 'decoy',
    caption:
      'This bait was written by an LLM specifically for a Designer, then cached — no one sees it twice.',
    segments: [segment('02-decoy')],
  },
  {
    id: 'hunting',
    caption:
      'Legitimate curiosity looks different from a directed search. The engine watches the sequence, not single clicks.',
    segments: [segment('03-insider-hunting')],
  },
  {
    id: 'dashboard',
    caption:
      'Role weighting means a Designer reaching into HR is scored 1.5x — an HR employee doing the same is 0.5x.',
    segments: [segment('04-dashboard-reacts')],
  },
  {
    id: 'active-response',
    caption:
      'Once a session crosses CRITICAL, it silently starts reading fiction. Nothing else in the system changes.',
    segments: [
      segment('05-active-response-intruder'),
      segment('05b-active-response-honest'),
    ],
  },
  {
    id: 'honeytoken',
    caption:
      'A honeyfile shows someone looked. A honeytoken shows they took it and tried it — worth +40 on its own.',
    segments: [segment('06-honeytoken-used'), segment('06b-honeytoken-admin')],
  },
  {
    id: 'second-opinion',
    caption:
      "This model never sees the rule engine's own points. Agreement is corroboration, not an echo.",
    segments: [segment('07-second-opinion')],
  },
  {
    id: 'nothing-hidden',
    caption:
      'The scoring logic is not a black box — an admin can read the live rules and end any session on demand.',
    segments: [segment('08-nothing-hidden')],
  },
  {
    id: 'two-more-rules',
    caption:
      "Two more signals: reaching into a folder you don't need, and failed logins that roll into your next session's starting score.",
    segments: [
      segment('09-restricted-attempt'),
      segment('09b-failed-logins'),
      segment('09c-carryover-admin'),
    ],
  },
];

/** Every segment in play order, title card excluded. */
export const SEGMENTS = CLIPS.flatMap((clip) =>
  clip.segments.map((s) => ({ ...s, clipId: clip.id })),
);

/**
 * Absolute frame ranges for the overlays.
 *
 * A TransitionSeries overlaps neighbours by TRANSITION_FRAMES, so each item
 * after the first starts that much earlier than a naive running total would
 * suggest. The overlay layer sits outside the series, so it has to account for
 * the same overlap or it drifts further out of sync with every clip.
 */
export function layout() {
  const titleFrames = sec(TITLE_SECONDS);
  const items = [{ kind: 'title', durationInFrames: titleFrames }, ...SEGMENTS];

  let cursor = 0;
  const placed = items.map((item, i) => {
    const from = i === 0 ? 0 : cursor - TRANSITION_FRAMES;
    cursor = from + item.durationInFrames;
    return { ...item, from };
  });

  const overlays = CLIPS.map((clip) => {
    const own = placed.filter((p) => p.clipId === clip.id);
    const from = own[0].from;
    const last = own[own.length - 1];
    return {
      id: clip.id,
      caption: clip.caption,
      from,
      durationInFrames: last.from + last.durationInFrames - from,
    };
  });

  return {
    titleFrames,
    overlays,
    totalFrames: cursor,
  };
}
