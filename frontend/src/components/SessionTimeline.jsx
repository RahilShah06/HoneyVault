import { useMemo, useState } from 'react'

/**
 * Session risk reconstruction: the score climbing over time, with each scored
 * action marked on it.
 *
 * Encoding is deliberately two-channel, so nothing is carried by colour alone:
 *   shape  = what happened   (circle / diamond / triangle / square)
 *   colour = how serious     (routine ink / warning / critical)
 *
 * The colours are the reserved status steps, not series colours. Adjacent-pair
 * separation measures dE 24.4 under CVD simulation and 28.4 at normal vision,
 * clear of the >=15 floor. Warning sits below 3:1 on the light surface by
 * design; the relief for that is the always-visible legend labels plus the
 * action table underneath, which is this chart's table view.
 *
 * Active deception is drawn as an annotation rule rather than a marker - it is
 * a moment when the system changed behaviour, not another user action.
 */

const PAD = { top: 18, right: 64, bottom: 38, left: 40 }
const VIEW = { w: 800, h: 280 }
const PLOT = {
  w: VIEW.w - PAD.left - PAD.right,
  h: VIEW.h - PAD.top - PAD.bottom,
}

// Below this, the session is too short for elapsed time to mean anything and
// every point would pile up in one column. Spread by action order instead and
// say so on the axis, rather than drawing a time axis that implies precision
// the data does not have.
const MIN_SPAN_MS = 20000

const LEVELS = [
  { from: 0, to: 25, name: 'LOW' },
  { from: 25, to: 50, name: 'MEDIUM' },
  { from: 50, to: 75, name: 'HIGH' },
  { from: 75, to: 100, name: 'CRITICAL' },
]

const KINDS = {
  action: { label: 'Action', tone: 'routine', shape: 'circle' },
  honeyfile: { label: 'Honeyfile', tone: 'warning', shape: 'diamond' },
  restricted: { label: 'Out of role', tone: 'warning', shape: 'triangle' },
  honeytoken: { label: 'Honeytoken used', tone: 'critical', shape: 'square' },
}

// Order shown in the legend: least to most serious.
const LEGEND = ['action', 'honeyfile', 'restricted', 'honeytoken']

function kindOf(e) {
  if (e.action_type === 'HONEYTOKEN_USED') return 'honeytoken'
  if (e.action_type === 'RESTRICTED_ATTEMPT') return 'restricted'
  if (e.is_honeyfile) return 'honeyfile'
  return 'action'
}

function fmtClock(iso) {
  const d = new Date(iso)
  return isNaN(d) ? '' : d.toLocaleTimeString()
}

/** Marker path for one event. `r` is the half-size in px. */
function Marker({ shape, cx, cy, r, className }) {
  if (shape === 'diamond') {
    return (
      <polygon
        className={className}
        points={`${cx},${cy - r} ${cx + r},${cy} ${cx},${cy + r} ${cx - r},${cy}`}
      />
    )
  }
  if (shape === 'triangle') {
    return (
      <polygon
        className={className}
        points={`${cx},${cy - r} ${cx + r},${cy + r * 0.8} ${cx - r},${cy + r * 0.8}`}
      />
    )
  }
  if (shape === 'square') {
    return (
      <rect
        className={className}
        x={cx - r}
        y={cy - r}
        width={r * 2}
        height={r * 2}
        rx="1.5"
      />
    )
  }
  return <circle className={className} cx={cx} cy={cy} r={r} />
}

export default function SessionTimeline({ timeline }) {
  const [hover, setHover] = useState(null)

  const model = useMemo(() => {
    const rows = (timeline || []).filter((e) => e.timestamp)
    if (rows.length === 0) return null

    const times = rows.map((e) => new Date(e.timestamp).getTime())
    const t0 = Math.min(...times)
    const realSpan = Math.max(...times) - t0
    const byOrder = realSpan < MIN_SPAN_MS
    const span = realSpan || 1

    let running = 0
    const points = rows.map((e, i) => {
      running = Math.min(100, running + (e.points_awarded || 0))
      return {
        event: e,
        index: i,
        score: running,
        scored: (e.points_awarded || 0) > 0,
        deception: e.action_type === 'ACTIVE_DECEPTION_TRIGGERED',
        kind: kindOf(e),
        x: byOrder
          ? PAD.left + (rows.length === 1 ? PLOT.w / 2 : (PLOT.w * i) / (rows.length - 1))
          : PAD.left + (PLOT.w * (times[i] - t0)) / span,
        y: PAD.top + PLOT.h * (1 - running / 100),
      }
    })

    return { points, byOrder, final: running }
  }, [timeline])

  if (!model) {
    return <p className="muted">No actions to plot yet.</p>
  }

  const { points, byOrder, final } = model
  const last = points[points.length - 1]
  const trigger = points.find((p) => p.deception)

  // Step path: the score holds flat until the next scored action lands.
  const path = points
    .map((p, i) => {
      const prev = points[i - 1]
      return i === 0
        ? `M ${p.x} ${p.y}`
        : `L ${p.x} ${prev.y} L ${p.x} ${p.y}`
    })
    .join(' ')

  const yFor = (score) => PAD.top + PLOT.h * (1 - score / 100)

  return (
    <div className="viz-root">
      <div className="viz-legend">
        {LEGEND.map((k) => (
          <span className="viz-legend-item" key={k}>
            <svg width="14" height="14" aria-hidden="true">
              <Marker
                shape={KINDS[k].shape}
                cx={7}
                cy={7}
                r={5}
                className={`mk-${KINDS[k].tone}`}
              />
            </svg>
            {KINDS[k].label}
          </span>
        ))}
        <span className="viz-legend-item">
          <svg width="14" height="14" aria-hidden="true">
            <line className="mk-annotation" x1="7" y1="1" x2="7" y2="13" />
          </svg>
          Active deception
        </span>
      </div>

      <div className="viz-plot">
        <svg
          viewBox={`0 0 ${VIEW.w} ${VIEW.h}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label={`Risk score over the session, ending at ${final} out of 100. The table below lists every action.`}
        >
          {/* Hairline grid, one shade off the surface. */}
          {[0, 25, 50, 75, 100].map((v) => (
            <line
              key={v}
              className={v === 75 ? 'viz-grid viz-grid-critical' : 'viz-grid'}
              x1={PAD.left}
              y1={yFor(v)}
              x2={PAD.left + PLOT.w}
              y2={yFor(v)}
            />
          ))}

          {[0, 25, 50, 75, 100].map((v) => (
            <text key={v} className="viz-tick" x={PAD.left - 8} y={yFor(v) + 4} textAnchor="end">
              {v}
            </text>
          ))}

          {LEVELS.map((l) => (
            <text
              key={l.name}
              className="viz-band-label"
              x={PAD.left + PLOT.w + 8}
              y={yFor((l.from + l.to) / 2) + 3}
            >
              {l.name}
            </text>
          ))}

          {/* The moment active deception engaged. */}
          {trigger && (
            <g>
              <line
                className="mk-annotation"
                x1={trigger.x}
                y1={PAD.top - 6}
                x2={trigger.x}
                y2={PAD.top + PLOT.h}
              />
              <text className="viz-annotation-label" x={trigger.x + 4} y={PAD.top - 8}>
                decoys engaged
              </text>
            </g>
          )}

          <path className="viz-line" d={path} />

          {/* Only scored actions get a marker; unscored ones would be noise. */}
          {points.filter((p) => p.scored && !p.deception).map((p) => (
            <g key={p.index}>
              <Marker
                shape={KINDS[p.kind].shape}
                cx={p.x}
                cy={p.y}
                r={p.index === hover ? 7 : 5.5}
                className={`mk-${KINDS[p.kind].tone} viz-marker`}
              />
              {/* Hit area well above the mark size, per the 24px minimum. */}
              <circle
                className="viz-hit"
                cx={p.x}
                cy={p.y}
                r={13}
                onMouseEnter={() => setHover(p.index)}
                onMouseLeave={() => setHover(null)}
              />
            </g>
          ))}

          {/* One direct label: the endpoint. Never a number on every point. */}
          <text className="viz-endpoint" x={last.x + 10} y={last.y + 4}>
            {final}
          </text>

          <line
            className="viz-axis"
            x1={PAD.left}
            y1={PAD.top + PLOT.h}
            x2={PAD.left + PLOT.w}
            y2={PAD.top + PLOT.h}
          />
          <text className="viz-tick" x={PAD.left} y={VIEW.h - 14}>
            {fmtClock(points[0].event.timestamp)}
          </text>
          <text
            className="viz-band-label"
            x={PAD.left + PLOT.w / 2}
            y={VIEW.h - 14}
            textAnchor="middle"
          >
            {byOrder ? 'action order (session under 20s)' : 'elapsed time'}
          </text>
          <text
            className="viz-tick"
            x={PAD.left + PLOT.w}
            y={VIEW.h - 14}
            textAnchor="end"
          >
            {fmtClock(last.event.timestamp)}
          </text>
        </svg>

        {hover !== null && points[hover] && (
          <div
            className="viz-tooltip"
            style={{
              left: `${(points[hover].x / VIEW.w) * 100}%`,
              top: `${(points[hover].y / VIEW.h) * 100}%`,
            }}
          >
            <strong>{points[hover].event.action_type}</strong>
            <br />
            {fmtClock(points[hover].event.timestamp)} · score{' '}
            {points[hover].score}
            <br />
            <span className="muted">
              +{points[hover].event.points_awarded}
              {points[hover].event.filename
                ? ` · ${points[hover].event.filename}`
                : ''}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
