# Visual Iteration & Feedback Loop

To avoid "blind coding," the agent SHOULD use the `Rasterizer` to verify output visually.

## Rasterizer API (`rasterizer.js`)
- **`Rasterizer.render(svgContent, width, height)`**: Renders an SVG string to a PNG image using the system browser.

## Iteration Workflow
1. **Draft**: Generate an SVG using `Toolkit` and `Scene`.
2. **Render**: Use `Rasterizer.render()` to create a screenshot.
3. **Observe**: Analyze the resulting image for errors (e.g., "Head is too large", "Colors clash").
4. **Correct**: Edit the SVG coordinates or colors and repeat.

## Example
```javascript
import { Toolkit } from './toolkit.js';
import { Rasterizer } from './rasterizer.js';

const scene = new Toolkit.Scene(200, 200, 10);
scene.add(`<circle cx="100" cy="100" r="50" fill="red" />`);

const image = await Rasterizer.render(scene.render());
// Agent now observes 'image' and iterates.
```
