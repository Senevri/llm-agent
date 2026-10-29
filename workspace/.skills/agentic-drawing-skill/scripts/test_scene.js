import { Toolkit } from './toolkit.js';

const cellSize = 20;
const scene = new Toolkit.Scene(200, 200, cellSize, "0 0 200 200");

// 1. Draw Floor
scene.add(`<rect width="200" height="200" fill="#f0f0f0" />`, 0);

// 2. Draw Grid lines
for(let i=0; i<=10; i++) {
    scene.add(`<line x1="${i*cellSize}" y1="0" x2="${i*cellSize}" y2="200" stroke="#ddd" />`, 1);
    scene.add(`<line x1="0" y1="${i*cellSize}" x2="200" y2="${i*cellSize}" stroke="#ddd" />`, 1);
}

// 3. Draw a Player (Blue Circle) at Grid (2, 8)
const pPos = Toolkit.Grid.gridToPixel(2, 8, cellSize);
scene.add(`<circle cx="${pPos.cx}" cy="${pPos.cy}" r="8" fill="blue" stroke="white" />`, 5);

// 4. Draw an Orc (Red Triangle) at Grid (7, 2)
const oPos = Toolkit.Grid.gridToPixel(7, 2, cellSize);
const oPoints = Toolkit.getPoints(oPos.cx, oPos.cy, 10, 3);
scene.add(`<polygon points="${oPoints}" fill="red" stroke="white" />`, 5);

// 5. Draw a Goblin (Green Star) at Grid (8, 7)
const gPos = Toolkit.Grid.gridToPixel(8, 7, cellSize);
const gPoints = Toolkit.getStarPoints(gPos.cx, gPos.cy, 12, 6);
scene.add(`<polygon points="${gPoints}" fill="green" stroke="white" />`, 5);

const svg = scene.render();

// Verification
const hasPlayer = svg.includes('fill="blue"');
const hasOrc = svg.includes('fill="red"');
const hasGoblin = svg.includes('fill="green"');
const hasGrid = svg.includes('stroke="#ddd"');

console.log("Verification Results:");
console.log("- Floor/Grid present:", hasGrid);
console.log("- Player (Blue) present:", hasPlayer);
console.log("- Orc (Red) present:", hasOrc);
console.log("- Goblin (Green) present:", hasGoblin);

if (hasGrid && hasPlayer && hasOrc && hasGoblin) {
    console.log("RESULT: SUCCESS");
} else {
    console.log("RESULT: FAILURE");
}
