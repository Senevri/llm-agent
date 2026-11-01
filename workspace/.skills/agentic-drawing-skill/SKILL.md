---
name: agentic-drawing-skill
description: "A skill that can draw diagrams, flowcharts, and other types of diagrams using agentic techniques."
---

 # Purpose
Converts natural language descriptions into visual representations.

 # Capabilities
1. **Diagramming (Mermaid)**: For flowcharts, sequence diagrams, and structural logic.
2. **Geometric/Illustrative Drawing (SVG)**: For precise shapes, characters, and layouts.

 # Operational Protocol

## 1. Analysis
- **Target Determination**: What elements should be included in the drawing
- **Entity Extraction**: Identify all objects, colors, and their properties.
- **Relationship/Spatial Mapping**: Determine how objects are positioned relative to each other.
- **Complexity Assessment**: Choose between Mermaid (structural) or SVG (geometric).

## 2. Implementation
- **Mermaid**: Use ` ```mermaid ` blocks.
- **SVG**: Use ` ```svg ` blocks. Use the Drawing Toolkit for complex shapes.

## 3. Resources & Guides
Detailed documentation and templates are stored in the `resources/` directory:
- **Toolkit Guide**: `resources/toolkit_guide.md` (Primitives, Scene, Grids).
- **Visual Iteration**: `resources/visual_iteration.md` (Using the Rasterizer loop).
- **Face Recipes**: `recipes/faces.js` (Configurable head shapes and proportions).

## 4. Verification
- **SVG**: Check required shapes, colors, and layering.
- **Mermaid**: Ensure structural logic is sound.

## 5. Organization
- All implementation scripts are located in `/scripts`.
- All guides and templates are located in `/resources`.

# Purpose
Converts natural language descriptions into visual representations.

# Capabilities
1. **Diagramming (Mermaid)**: For flowcharts, sequence diagrams, state diagrams, class diagrams, ER diagrams, Gantt charts, and pie charts.
2. **Geometric/Illustrative Drawing (SVG)**: For precise geometric shapes, complex spatial arrangements, and detailed illustrations.

# Operational Protocol

## 1. Analysis
- **Entity Extraction**: Identify all objects, colors, and their properties.
- **Relationship/Spatial Mapping**: Determine how objects are positioned relative to each other (e.g., "inside", "next to", "under").
- **Complexity Assessment**:
  - If the request is structural/relational $\rightarrow$ use **Mermaid**.
  - If the request is geometric/positional $\rightarrow$ use **SVG**.

## 2. Implementation

### Mermaid
- Always use a ` ```mermaid ` block.
- Ensure syntax is valid for the specific diagram type.

### SVG
- Always use a ` ```svg ` block.
- Use `viewBox` for responsiveness.
- **Layering**: Draw background elements first, foreground elements last.
- **Color**: Use standard CSS color names or hex codes as specified.

## 3. Drawing Toolkit (via `eval`)
For complex geometric tasks, the agent SHOULD use the `toolkit.js` via `eval`.

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
- **`Toolkit.palettes.rainbow`, `Toolkit.palettes.material`, `Toolkit.palettes.pastel`**: Pre-made color arrays.

### Example: Tactical Map Generation
```javascript
import { Toolkit } from '/home/sandboxuser/.omp/agent/managed-skills/agentic-drawing-skill/toolkit.js';
const scene = new Toolkit.Scene(200, 200, 20);
const pos = Toolkit.Grid.gridToPixel(1, 1, 20);
scene.add(`<circle cx="${pos.cx}" cy="${pos.cy}" r="8" fill="blue" />`);
console.log(scene.render());
```
- **Precision**: For "inside" or "centered" requests, calculate coordinates precisely.

## 3. Drawing Toolkit (via `eval`)
For complex geometric tasks, the agent SHOULD use the `toolkit.js` via `eval`.

### Available Functions
- **`Toolkit.getPoints(cx, cy, r, sides)`**: Returns SVG `points` string for a regular polygon.
- **`Toolkit.getStarPoints(cx, cy, r_out, r_in)`**: Returns SVG `points` string for a star.
- **`Toolkit.palettes.rainbow`, `Toolkit.palettes.material`, `Toolkit.palettes.pastel`**: Pre-made color arrays.

### Example Usage in `eval`
```javascript
import { Toolkit } from '/home/sandboxuser/.omp/agent/managed-skills/agentic-drawing-skill/toolkit.js';
const pts = Toolkit.getPoints(50, 50, 40, 6);
console.log(`<polygon points="${pts}" />`);
```

## 4. Verification
- For SVG: Check that all required shapes and colors are present and correctly layered.
- For Mermaid: Ensure the diagram is structurally logical.

## 5. Visual Iteration (The "Vision Loop")
To avoid "blind coding," the agent SHOULD use the `Rasterizer` to verify output visually.

### Rasterizer API (`rasterizer.js`)
- **`Rasterizer.render(svgContent, width, height)`**: Renders an SVG string to a PNG image using the system browser.

### Iteration Workflow
1. **Draft**: Generate an SVG using `Toolkit` and `Scene`.
2. **Render**: Use `Rasterizer.render()` to create a screenshot.
3. **Observe**: Analyze the resulting image for errors (e.g., "Head is too large", "Colors clash").
4. **Correct**: Edit the SVG coordinates or colors and repeat.

### Example
```javascript
import { Toolkit } from '/home/sandboxuser/.omp/agent/managed-skills/agentic-drawing-skill/toolkit.js';
import { Rasterizer } from '/home/sandboxuser/.omp///rasterizer.js';

const scene = new Toolkit.Scene(200, 200, 10);
scene.add(`<circle cx="100" cy="100" r="50" fill="red" />`);

const image = await Rasterizer.render(scene.render());
// Agent now observes 'image' and iterates.
```

 Drawing Skill Resources

Short planning guides for common visual requests. These are **decision aids**, not mandatory templates: use only the guidance relevant to the user's request.

## Guides
- `characters.md` — full-body characters, poses, silhouette, asymmetry
- `portraits.md` — heads, faces, expressions, hair
- `maps.md` — geographic, fantasy, and tactical maps
- `diagrams.md` — conceptual diagrams, layouts, relationships
- `flowcharts.md` — processes and decision flows
- `icons.md` — icons, symbols, badges, and small assets
- `objects.md` — props, vehicles, and designed objects
- `landscapes.md` — scenes, environments, and backgrounds
- `charts.md` — data charts and infographic-style visuals

## General rule
First identify the intended use, output format, required content, and constraints. Plan the composition before drawing. Prefer simple, legible shapes over decorative complexity. Validate what can be checked mechanically; request or use visual inspection only when available. Stop when the user's requirements are met, not when no further embellishment is imaginable.