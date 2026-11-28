/**
 * Body Recipe for the Agentic Drawing Skill.
 * Provides a base for anatomical structure with options for "connected" or "floating" parts.
 */
export const BodyRecipe = {
  generate: (cx, cy, config = {}) => {
    const style = config.style || 'connected';
    const s = config.scale || 1;
    const skin = config.skinColor || '#FFDBAC';
    const el = [];

    // Torso
    el.push(`<path d="M ${cx - 20 * s},${cy} Q ${cx},${cy - 5 * s} ${cx + 20 * s},${cy} L ${cx + 15 * s},${cy + 50 * s} Q ${cx},${cy + 55 * s} ${cx - 15 * s},${cy + 50 * s} Z" fill="${skin}" stroke="#333" stroke-width="1" />`);

    if (style === 'connected') {
      // Arms
      el.push(`<path d="M ${cx - 20 * s},${cy + 10 * s} L ${cx - 40 * s},${cy + 30 * s}" stroke="${skin}" stroke-width="12 * s" stroke-linecap="round" />`);
      el.push(`<path d="M ${cx + 20 * s},${cy + 10 * s} L ${cx + 40 * s},${cy + 30 * s}" stroke="${skin}" stroke-width="12 * s" stroke-linecap="round" />`);
      // Legs
      el.push(`<path d="M ${cx - 15 * s},${cy + 50 * s} L ${cx - 15 * s},${cy + 120 * s}" stroke="${skin}" stroke-width="15 * s" stroke-linecap="round" />`);
      el.push(`<path d="M ${cx + 15 * s},${cy + 50 * s} L ${cx + 15 * s},${cy + 120 * s}" stroke="${skin}" stroke-width="15 * s" stroke-linecap="round" />`);
    } else {
      // Floating Hands
      el.push(`<circle cx="${cx - 45 * s}" cy="${cy + 30 * s}" r="${8 * s}" fill="${skin}" stroke="#333" />`);
      el.push(`<circle cx="${cx + 45 * s}" cy="${cy + 30 * s}" r="${8 * s}" fill="${skin}" stroke="#333" />`);
      // Floating Feet
      el.push(`<ellipse cx="${cx - 15 * s}" cy="${cy + 130 * s}" rx="${12 * s}" ry="${6 * s}" fill="${skin}" stroke="#333" />`);
      el.push(`<ellipse cx="${cx + 15 * s}" cy="${cy + 130 * s}" rx="12 * s" ry="6 * s" fill="${skin}" stroke="#333" />`);
    }
    return el;
  }
};
