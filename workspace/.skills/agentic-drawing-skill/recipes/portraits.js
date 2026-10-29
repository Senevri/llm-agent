/**
 * Character Portrait Recipe
 * Provides a structured approach to generating a portrait.
 * Focuses on composition, lighting, and proportional layering.
 */
export const PortraitRecipe = {
  /**
   * Generates a portrait composition.
   * @param {Object} config - Configuration for the portrait.
   * @param {number} config.centerX - Center X
   * @param {number} config.centerY - Center Y
   * @param {string} config.skinTone - Key from Toolkit.palettes.skintones
   * @param {string} config.eyeColor - Color for eyes
   * @param {Object} config.headParams - { rw, rh, shape }
   * @returns {Array} Array of SVG strings for the portrait.
   */
  generate: (config) => {
    const { Toolkit } = require('./../toolkit.js'); // Assuming commonJS or bundled environment
    const elements = [];
    const { centerX, centerY, skinTone, headParams } = config;
    const skinColor = Toolkit.palettes.skintones[skinTone] || '#FFDBAC';

    // 1. Background/Aura
    elements.push(`<circle cx="${centerX}" cy="${centerY}" r="100" fill="url(#portraitGlow)" opacity="0.3" />`);

    // 2. Base Face (using the face recipe)
    const face = Toolkit.generateFace(centerX, centerY, headParams.rw, headParams.rh, skinColor, {
      shape: headParams.shape || 'oval',
      eyeColor: config.eyeColor || '#000',
      mouth: config.mouth || 'smile'
    });
    elements.push(...face);

    // 3. Neck/Shoulders (Standardized Portrait base)
    const neckW = headParams.rw * 0.4;
    elements.push(`<rect x="${centerX - neckW}" y="${centerY + headParams.rh * 0.8}" width="${neckW * 2}" height="40" fill="${skinColor}" />`);
    
    // Shoulders
    elements.push(`<path d="M ${centerX - 60},${centerY + 150} Q ${centerX},${centerY + 120} ${centerX + 60},${centerY + 150} L ${centerX + 80},${centerY + 200} L ${centerX - 80},${centerY + 200} Z" fill="${config.outfitColor || '#ccc'}" />`);

    return elements;
  },

  /**
   * Suggested lighting configurations for portraits.
   */
  lighting: {
    dramatic: { cx: "20%", cy: "20%", r: "80%", stops: [{offset: 0, color: "#fff"}, {offset: 100, color: "#000"}] },
    soft: { cx: "50%", cy: "50%", r: "100%", stops: [{offset: 0, color: "#fff"}, {offset: 100, color: "#ddd"}] },
    mystic: { cx: "50%", cy: "50%", r: "100%", stops: [{offset: 0, color: "#e0f7fa"}, {offset: 100, color: "#4b0082"}] }
  }
};
