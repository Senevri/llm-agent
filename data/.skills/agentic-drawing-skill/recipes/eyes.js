/**
 * Eye Recipe for the Agentic Drawing Skill.
 * Handles various styles from "button eyes" to "detailed anime eyes".
 */
export const EyeRecipe = {
  /**
   * Generates a set of eye elements.
   * @param {number} cx - Center X
   * @param {number} cy - Center Y
   * @param {number} size - Base size of the eye
   * @param {Object} options - Configuration options
   * @param {string} options.style - 'button' | 'anime' | 'realistic'
   * @param {string} options.irisColor - Color of the iris
   * @param {string} options.pupilColor - Color of the pupil (default: black)
   * @param {string} options.scleraColor - Color of the white of the eye (default: white)
   * @param {boolean} options.hasEyelids - Whether to draw eyelids/creases
   * @param {boolean} options.hasLashes - Whether to draw eyelashes
   * @param {string} options.borderColor - Color of the eye outline (default: #000)
   * @returns {Array} Array of SVG elements.
   */
  generate: (cx, cy, size, options = {}) => {
    const { 
      style = 'anime', 
      irisColor = '#3d2b1f', 
      pupilColor = '#000', 
      scleraColor = '#fff', 
      hasEyelids = false, 
      hasLashes = false, 
      borderColor = '#000' 
    } = options;
    
    const elements = [];

    if (style === 'button') {
      // Simple, clean button eye
      elements.push(`<circle cx="${cx}" cy="${cy}" r="${size}" fill="${irisColor}" stroke="${borderColor}" stroke-width="1" />`);
    } 
    else if (style === 'anime') {
      // Detailed anime eye: Sclera -> Iris -> Pupil -> Highlights
      const irisR = size * 0.8;
      const pupilR = size * 0.3;
      
      // 1. Sclera (White of the eye)
      elements.push(`<ellipse cx="${cx}" cy="${cy}" rx="${size}" ry="${size * 0.6}" fill="${scleraColor}" stroke="${borderColor}" stroke-width="1" />`);
      
      // 2. Iris
      elements.push(`<circle cx="${cx}" cy="${cy}" r="${irisR}" fill="${irisColor}" />`);
      
      // 3. Pupil
      elements.push(`<circle cx="${cx}" cy="${cy}" r="${pupilR}" fill="${pupilColor}" />`);
      
      // 4. Highlights (Specular reflection)
      elements.push(`<circle cx="${cx - size*0.3}" cy="${cy - size*0.2}" r="${size * 0.2}" fill="white" />`);
      elements.push(`<circle cx="${cx + size*0.2}" cy="${cy + size*0.1}" r="${size * 0.1}" fill="white" />`);

      // 5. Eyelids / Eye-border
      if (hasEyelids) {
        elements.push(`<path d="M ${cx-size},${cy} Q ${cx},${cy - size*0.5} ${cx+size},${cy}" fill="none" stroke="${borderColor}" stroke-width="2" />`);
      }
      
      // 6. Eyelashes
      if (hasLashes) {
        const lashPoints = [
          [size * 0.8, size * 0.2],
          [size * 1.0, size * 0.4],
          [size * 0.8, size * 0.6]
        ];
        lashPoints.forEach(([dx, dy]) => {
          elements.push(`<line x1="${cx + dx}" y1="${cy}" x2="${cx + dx * 1.2}" y2="${cy + dy}" stroke="${borderColor}" stroke-width="1" />`);
        });
      }
    } 
    else {
      // Default / Realistic fallback
      elements.push(`<ellipse cx="${cx}" cy="${cy}" rx="${size}" ry="${size * 0.7}" fill="${scleraColor}" stroke="${borderColor}" />`);
      elements.push(`<circle cx="${cx}" cy="${cy}" r="${size * 0.5}" fill="${irisColor}" />`);
      elements.push(`<circle cx="${cx}" cy="${cy}" r="${size * 0.2}" fill="${pupilColor}" />`);
    }

    return elements;
  }
};
