# Conceptual and Structural Diagrams

Use for system diagrams, relationship maps, architecture diagrams, timelines, cycles, and explanatory visuals.

## Choose the right representation
- Use Mermaid for graphs and relationships that are naturally nodes and edges.
- Use SVG when exact placement, custom shapes, spatial grouping, or visual styling matters.
- Use a table when the information is mainly comparative and does not benefit from spatial layout.

## Plan first
1. State the central question the diagram should answer.
2. Identify entities, relationships, directionality, grouping, and hierarchy.
3. Keep one visual meaning per encoding: for example, colour for category and line style for status.
4. Arrange the diagram to follow reading order, usually left-to-right or top-to-bottom.
5. Include a title and legend only when they add necessary context.

## Layout rules
- Minimize line crossings and ambiguous arrow direction.
- Use consistent shape meanings and connector styles.
- Group related items and leave whitespace between groups.
- Keep labels short; explain details in nearby text rather than shrinking labels.
- Do not add nodes or relationships that were not supplied or reasonably implied.
- For complex systems, make a high-level overview first; split detail into separate diagrams instead of cramming everything into one canvas.

## Verification
Check every required node and relationship, arrow direction, grouping, reading order, label legibility, and whether the diagram answers the original question without extra explanation.
