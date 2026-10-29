/**
 * Face Recipes for the Agentic Drawing Skill.
 */
export const FaceRecipes = {
  /**
   * Generates a standard face layout.
   * @param {number} cx - Center X
   * @param {number} cy - Center Y
   * @param {number} rw - Radius Width
   * @param {number} rh - Radius Height
   * @param {string} skinColor - Hex color
   * @param {Object} options - { shape: 'oval'|'heart'|'square'|'diamond', eyeColor, mouth: 'smile'|'neutral' }
   */
  generate: (cx, cy, rw, rh, skinColor, options = {}) => {
    const { shape = 'oval', eyeColor = '#000', mouth = 'smile' } = options;
    const elements = [];

    // 1. Face Base Shape
    if (shape === 'oval') {
      elements.push(`<ellipse cx="${cx}" cy="${cy}" rx="${rw}" ry="${rh}" fill="${skinColor}" />`);
    } else if (shape === 'heart') {
      const p = `M ${cx},${cy + rh * 0.2} 
                 C ${cx - rw},${cy - rh * 0.5} ${cx - rw * 1.5},${cy + rh * 0.2} ${cx},${cy + rh * 0.8} 
                 C ${cx + rw * 1.5},${cy + rh * 0.2} ${cx + rw},${cy - rh * 0.5} ${cx},${cy + rh * 0.2} Z`;
      elements.push(`<path d="${p}" fill="${skinColor}" />`);
    } else if (shape === 'square') {
      elements.push(`<rect x="${cx - rw}" y="${cy - rh}" width="${rw * 2}" height="${rh * 2}" rx="${rw * 0.2}" fill="${skinColor}" />`);
    } else if (shape === 'diamond') {
      elements.push(`<polygon points="${cx},${cy - rh} ${cx + rw},${cy} ${cx},${cy + rh} ${cx - rw},${cy}" fill="${skinColor}" />`);
    } else {
      elements.push(`<circle cx="${cx}" cy="${cy}" r="${rw}" fill="${skinColor}" />`);
    }

    // 2. Feature Positioning (Proportional to the shape)
    const eyeOffset = rw * 0.4;
    const eyeR = rw * 0.15;
    const eyeY = cy - rh * 0.2;
    elements.push(`<circle cx="${cx - eyeOffset}" cy="${eyeY}" r="${eyeR}" fill="${eyeColor}" />`);
    elements.push(`<circle cx="${cx + eyeOffset}" cy="${eyeY}" r="${eyeR}" fill="${eyeColor}" />`);

    // 3. Nose
    elements.push(`<path d="M ${cx},${cy} L ${cx},${cy + rh * 0.2}" stroke="${skinColor}" stroke-width="2" opacity="0.6" />`);

    // 4. Mouth
    if (mouth === 'smile') {
      elements.push(`<path d="M ${cx - rw * 0.3},${cy + rh * 0.3} Q ${cx},${cy + rh * 0.5} ${cx + rw * 0.3},${cy + rh * 0.3}" fill="none" stroke="#000" stroke-width="2" />`);
    } else {
      elements.push(`<line x1="${cx - rw * 0.2}" y1="${cy + rh * 0.4}" x2="${cx + rw * 0.2}" y2="${cy + rh * 0.4}" stroke="#000" stroke-width="2" />`);
    }

    return elements;
  }
};
