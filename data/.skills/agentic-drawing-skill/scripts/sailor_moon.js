import { Toolkit } from './toolkit.js';

const scene = new Toolkit.Scene(300, 400, 10, "0 0 300 400");

// Background
scene.add(`<rect width="300" height="400" fill="#f0f0f0" />`);

// Hair (Complex Curves - Manual SVG Path)
scene.add(`<path d="M 150,50 C 130,30 110,40 100,60 C 90,80 100,100 110,120 C 120,140 130,150 150,160 C 170,150 180,140 190,120 C 200,100 210,80 200,60 C 190,40 170,30 150,50 Z" fill="#ff69b4" />`);

// Head (Symmetrical)
scene.add(`<circle cx="150" cy="150" r="40" fill="#ffd700" />`);

// Eyes
scene.add(`<circle cx="140" cy="140" r="5" fill="#000000" />`);
scene.add(`<circle cx="160" cy="140" r="5" fill="#000000" />`);

// Nose
scene.add(`<path d="M 150,150 L 150,155" stroke="#000000" stroke-width="2" />`);

// Mouth
scene.add(`<path d="M 145,160 Q 150,165 155,160" fill="none" stroke="#000000" stroke-width="2" />`);

// Armor (Star Pattern - Manual)
scene.add(`<path d="M 150,100 L 160,120 L 150,140 L 140,120 Z" fill="#ff0000" />`);
scene.add(`<path d="M 150,100 L 170,110 L 150,120 L 130,110 Z" fill="#ff0000" />`);

// Arms (Using getLimb)
scene.add(`<polygon points="120,200 90,250 100,260 130,230" fill="#ff69b4" />`);
scene.add(`<polygon points="180,200 210,250 200,260 170,230" fill="#ff69b4" />`);

// Torso (Symmetrical)
scene.add(`<path d="M 150,200 C 130,220 120,250 150,270 C 180,250 170,220 150,200 Z" fill="#ff69b4" />`);

// Star Symbols on Armor
scene.add(`<path d="M 150,100 L 155,110 L 160,100 L 155,90 Z" fill="#ffffff" />`);
scene.add(`<path d="M 150,100 L 145,110 L 140,100 L 145,90 Z" fill="#ffffff" />`);

// Highlights
scene.add(`<circle cx="145" cy="135" r="3" fill="#ffffff" />`);
scene.add(`<circle cx="155" cy="135" r="3" fill="#ffffff" />`);

console.log(scene.render());