# Agentic Drawing Skill: Future Roadmap & Iteration Strategies

## 1. Proposed Recipe Categories
To transition from "geometric shapes" to "artistic generation," the skill should implement specific templates (recipes) for these domains:

### A. Procedural Environments (World Building)
*   **Dungeon Layouts**: Top-down grid-based maps with walls, doors, and corridors.
*   **Natural Landscapes**: Layered horizons, mountains, and atmospheric depth.
*   **Starfields**: Stochastic distributions of points with glow/nebula effects.

### B. Schematic & Information Design (Logic)
*   **Flowcharts/State Machines**: Nodes and directed arrows with structured layouts.
*   **Technical Blueprints**: Isometric views of mechanical parts or architectural plans.
*   **Data Visualizations**: Custom charts (radar, sunburst, etc.) that go beyond standard bar/line graphs.

### C. Character & Asset Art (Narrative)
*   **Portrait Sprites**: Front/Profile/3/4 views with consistent character features.
*   **Equipment/Loot Icons**: High-detail, single-object renders with specific lighting (e.g., "magical glow").
*   **Action Poses**: Skeletal-based posing for characters in motion.

## 2. Automated Visual Iteration (The "Vision Loop")
To enable autonomous improvement, the system can implement a **Visual Critic-Actor** loop:

1.  **Render**: The Agent renders the current SVG to a PNG (`rasterize` tool).
2.  **Observe**: A VLM (Vision-Language Model) receives the PNG and the original prompt.
3.  **Critique**: The VLM provides a structured critique:
    *   *Geometric Errors*: "The triangle is not centered."
    *   *Style Errors*: "The lighting is too harsh for a forest scene."
    *   *Completeness*: "The requested weapon is missing."
4.  **Act**: The Agent parses the critique and applies a surgical `edit` to the SVG code.
