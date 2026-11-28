/**
 * SVG Rasterizer for the Agentic Drawing Skill.
 * Leverages the global 'browser' object to render SVG to an image.
 */
export const Rasterizer = {
  /**
   * Renders an SVG string to an image and returns the screenshot.
   * @param {string} svgContent - The SVG code to render.
   * @param {number} width - Width of the output image.
   * @param {number} height - Height of the output image.
   * @returns {Promise<string>} Path to the saved image or image data.
   */
  async render(svgContent, width = 300, height = 300) {
    // 1. Create a minimal HTML wrapper for the SVG
    const html = `
      <!DOCTYPE html>
      <html>
      <head>
        <style>
          body { margin: 0; padding: 0; overflow: hidden; background: white; }
          svg { width: ${width}px; height: ${height}px; }
        </style>
      </head>
      <body>
        ${svgContent}
      </body>
      </html>
    `;

    // 2. Use the browser to render the HTML
    // We use a data URL to avoid writing to a temporary file
    const dataUrl = `data:text/html;base64,${btoa(unescape(encodeURIComponent(html)))}`;
    const page = await browser.open(dataUrl);
    
    // 3. Capture the image
    const screenshot = await page.screenshot({
      clip: { x: 0, y: 0, width, height }
    });

    // 4. Close the page to prevent leaks
    await page.close();

    return screenshot;
  }
};
