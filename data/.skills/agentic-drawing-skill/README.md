# Toolkit update

Proposed drop-in replacement for `toolkit.js`, aimed at giving small drawing agents reusable, composable primitives rather than subject-specific hardcoding.

## Added
- SVG primitives: `circle`, `ellipse`, `rect`, `line`, `polygon`, `polyline`, `path`, `text`, `group`
- Transforms: `translate`, `rotate`, `scale`
- `getTaperedLimb`, `defs`, `Grid.cellRect`
- `Scene.addAll`, `Scene.clear`
- Geometry: `midpoint`, `distance`, `clamp`, `lerp`, `mapRange`, `jitter`, `seededJitter`

## Fixed
- `getRadialGradient` now returns its generated SVG.
- `getSymmetricPath` now creates a consistently ordered closed mirrored path.
- `getBezierPath(points, tension, closed)` is open by default, so it can draw hair strands, limbs, contours, and other open curves.
- Zero-length limbs avoid division by zero.
- Equal-z scene elements preserve insertion order.

## API notes
- Helpers return SVG strings; add them to a `Scene` or combine them with `group`.
- Style options use camelCase (`strokeWidth`, `linecap`, `linejoin`, `dasharray`, `className`, `fontSize`).
- `getSymmetricPath(cx, cy, leftHalf)` expects `[distanceFromAxis, yOffset]` pairs. Check existing callers before replacing: the old implementation's path ordering was malformed.
- `getBezierPath` uses Catmull–Rom-like cubic control points; set `closed=true` for closed contours.
- This is a source update, not a verified visual regression-tested release. Run existing recipe tests and inspect representative SVG renders before integration.
