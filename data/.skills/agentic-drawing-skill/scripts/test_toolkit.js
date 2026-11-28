import { Toolkit } from './toolkit.js';

/**
 * Generates a tiled SVG grid of hexagons using the toolkit.
 * @param {number} cols - Number of columns
 * @param {number} rows - Number of rows
 * @param {number} spacing - Spacing between hexagon centers
 * @param {string} paletteName - Name of the palette from Toolkit.palettes
 * @returns {string} SVG string containing the tiled hexagons
 */
export function generateHexTiling(cols, rows, spacing, paletteName) {
  const palette = Toolkit.palettes[paletteName] || Toolkit.palettes.rainbow;
  let svgContent = '';
  
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const color = palette[(row + col) % palette.length];
      
      // Hexagon math: dx = sqrt(3) * r, dy = 1.5 * r
      // For simplicity, we'll use a fixed r and calculate offsets
      const r = spacing / Math.sqrt(3);
      const dx = Math.sqrt(3) * r;
      const dy = 1.5 * r;
      
      let cx = col * dx + (row % 2 === 0 ? dx / 2 : 0);
      let cy = row * dy;

      // Adjusting center to be within a visible area
      cx += 50; 
      cy += 50;

      svgContent += `<polygon points="${Toolkit.getPoints(cx, cy, r, 6)}" fill="${color}" />\n`;
    }
  }

  return `<svg viewBox="0 0 ${cols * dx + 50} ${rows * dy + 50}" xmlns="http://www.w3.org/2000/svg">${svgContent}</svg>`;
}

console.log("Toolkit generated a test tiling...");
