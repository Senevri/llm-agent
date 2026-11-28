# Drawing Toolkit Guide

## Toolkit Overview
The `toolkit.js` provides the core geometric and composition engine.

### Helper: Grid (Mapping)
- **`Toolkit.Grid.gridToPixel(gx, gy, cellSize)`**: Converts grid coordinates to pixel center.
- **`Toolkit.Grid.pixelToGrid(px, py, cellSize)`**: Converts pixel coordinates to grid cell.

### Helper: Scene (Composition)
- **`new Toolkit.Scene(width, height, cellSize, viewBox)`**: Initializes a drawing scene.
- **`scene.add(svgTag, [zIndex])`**: Adds an SVG element to the scene (higher zIndex = foreground).
- **`scene.render()`**: Returns the complete SVG string.

### Primitives & Palettes
- **`Toolkit.getPoints(cx, cy, r, sides)`**: Returns SVG `points` string for a regular polygon.
- **`Toolkit.getStarPoints(cx, cy, r_out, r_in)`**: Returns SVG `points` string for a star.
- **`Toolkit.getSymmetricPath(cx, cy, leftHalf)`**: Mirrored paths for organic shapes.
- **`Toolkit.getLimb(x1, y1, x2, y2, width, color)`**: Thickened lines for limbs.
- **`Toolkit.getBezierPath(points, tension)`**: Smooth curves.
- **`Toolkit.getLinearGradient(id, stops)`**: Multi-stop linear gradients.
- **`Toolkit.getRadialGradient(id, cx, cy, r, stops)`**: Multi-stop radial gradients.
- **`Toolkit.palettes`**: predefined sets (rainbow, material, pastel, monochrome, dungeon, skintones).
