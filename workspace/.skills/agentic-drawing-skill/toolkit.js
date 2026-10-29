/**
 * Drawing toolkit for small LLM agents.
 * Coordinates are SVG user-space units. Helpers return SVG strings unless noted.
 */
const esc = (v) => String(v).replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const n = (v, fallback = 0) => Number.isFinite(Number(v)) ? Number(v) : fallback;
const attr = (k, v) => v == null ? "" : ` ${k}="${esc(v)}"`;
const pts = (p = []) => p.map(([x,y]) => `${n(x)},${n(y)}`).join(" ");
const stops = (s = []) => s.filter(x => x && x.offset !== undefined && x.color !== undefined);

export const Toolkit = {
  Grid: {
    gridToPixel: (gx, gy, cellSize) => ({ cx: (gx + 0.5) * cellSize, cy: (gy + 0.5) * cellSize }),
    pixelToGrid: (px, py, cellSize) => {
      if (!Number.isFinite(cellSize) || cellSize <= 0) throw new RangeError("cellSize must be positive");
      return { gx: Math.floor(px / cellSize), gy: Math.floor(py / cellSize) };
    },
    cellRect: (gx, gy, cellSize, options = {}) => Toolkit.rect(gx * cellSize, gy * cellSize, cellSize, cellSize, options)
  },

  Scene: class {
    constructor(width, height, cellSize = 1, viewBox = `0 0 ${width} ${height}`) {
      this.width = width; this.height = height; this.cellSize = cellSize; this.viewBox = viewBox;
      this.elements = []; this._sequence = 0;
    }
    add(svgTag, zIndex = 0) {
      this.elements.push({ tag: String(svgTag), zIndex: n(zIndex), order: this._sequence++ });
      this.elements.sort((a,b) => a.zIndex - b.zIndex || a.order - b.order);
      return this;
    }
    addAll(elements, zIndex = 0) { for (const e of elements) this.add(e, zIndex); return this; }
    clear() { this.elements.length = 0; return this; }
    render() {
      return `<svg viewBox="${esc(this.viewBox)}" width="${esc(this.width)}" height="${esc(this.height)}" xmlns="http://www.w3.org/2000/svg">${this.elements.map(e => e.tag).join("\n")}</svg>`;
    }
  },

  _styleAttrs: (o = {}) => {
    const pairs = [["fill",o.fill],["stroke",o.stroke],["stroke-width",o.strokeWidth],["opacity",o.opacity],
      ["stroke-linecap",o.linecap],["stroke-linejoin",o.linejoin],["stroke-dasharray",o.dasharray],
      ["transform",o.transform],["class",o.className],["id",o.id]];
    return pairs.filter(([,v]) => v != null).map(([k,v]) => `${k}="${esc(v)}"`).join(" ").replace(/^/, s => s ? " " : "");
  },

  circle: (cx,cy,r,o={}) => `<circle cx="${n(cx)}" cy="${n(cy)}" r="${Math.max(0,n(r))}"${Toolkit._styleAttrs(o)} />`,
  ellipse: (cx,cy,rx,ry,o={}) => `<ellipse cx="${n(cx)}" cy="${n(cy)}" rx="${Math.max(0,n(rx))}" ry="${Math.max(0,n(ry))}"${Toolkit._styleAttrs(o)} />`,
  rect: (x,y,width,height,o={}) => `<rect x="${n(x)}" y="${n(y)}" width="${Math.max(0,n(width))}" height="${Math.max(0,n(height))}"${attr("rx",o.rx)}${attr("ry",o.ry)}${Toolkit._styleAttrs(o)} />`,
  line: (x1,y1,x2,y2,o={}) => `<line x1="${n(x1)}" y1="${n(y1)}" x2="${n(x2)}" y2="${n(y2)}"${Toolkit._styleAttrs({fill:"none",...o})} />`,
  polygon: (points,o={}) => `<polygon points="${pts(points)}"${Toolkit._styleAttrs(o)} />`,
  polyline: (points,o={}) => `<polyline points="${pts(points)}"${Toolkit._styleAttrs({fill:"none",...o})} />`,
  path: (d,o={}) => `<path d="${esc(d)}"${Toolkit._styleAttrs(o)} />`,
  text: (x,y,content,o={}) => {
    const extra = [["font-size",o.fontSize],["font-family",o.fontFamily],["font-weight",o.fontWeight],
      ["text-anchor",o.textAnchor],["dominant-baseline",o.dominantBaseline]]
      .filter(([,v])=>v!=null).map(([k,v])=>`${k}="${esc(v)}"`).join(" ");
    return `<text x="${n(x)}" y="${n(y)}"${Toolkit._styleAttrs(o)}${extra ? " "+extra : ""}>${esc(content)}</text>`;
  },
  group: (elements,o={}) => `<g${Toolkit._styleAttrs(o)}>${Array.isArray(elements)?elements.join("\n"):String(elements??"")}</g>`,
  translate: (x,y) => `translate(${n(x)} ${n(y)})`,
  rotate: (degrees,cx=0,cy=0) => `rotate(${n(degrees)} ${n(cx)} ${n(cy)})`,
  scale: (sx,sy=sx) => `scale(${n(sx,1)} ${n(sy,1)})`,

  getBezierPath: (points,tension=0.5,closed=false) => {
    if (!Array.isArray(points)||points.length===0) return "";
    const p=points.map(v=>[n(v[0]),n(v[1])]), count=p.length;
    if (count===1) return `M ${p[0][0]},${p[0][1]}`;
    const t=Math.max(0,Math.min(1,n(tension,0.5)));
    let d=`M ${p[0][0]},${p[0][1]}`;
    for(let i=0;i<(closed?count:count-1);i++){
      const a=p[(i-1+count)%count], b=p[i%count], c=p[(i+1)%count], q=p[(i+2)%count];
      const c1=[b[0]+(c[0]-a[0])*t/3,b[1]+(c[1]-a[1])*t/3];
      const c2=[c[0]-(q[0]-b[0])*t/3,c[1]-(q[1]-b[1])*t/3];
      d+=` C ${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${c[0]},${c[1]}`;
    }
    return d+(closed?" Z":"");
  },

  // leftHalf points are [distance from vertical axis, y offset].
  getSymmetricPath: (cx,cy,leftHalf) => {
    if(!Array.isArray(leftHalf)||leftHalf.length<2) return "";
    const left=leftHalf.map(([dx,y])=>[cx-n(dx),cy+n(y)]);
    const right=leftHalf.map(([dx,y])=>[cx+n(dx),cy+n(y)]).reverse();
    const all=[...left,...right];
    return `M ${all[0][0]},${all[0][1]} ${all.slice(1).map(p=>`L ${p[0]},${p[1]}`).join(" ")} Z`;
  },

  getLimb: (x1,y1,x2,y2,width=10,color="green") => {
    const dx=x2-x1,dy=y2-y1,len=Math.hypot(dx,dy);
    if(len<1e-9) return Toolkit.circle(x1,y1,Math.max(0,width/2),{fill:color});
    const nx=-dy/len*width/2,ny=dx/len*width/2;
    return Toolkit.polygon([[x1+nx,y1+ny],[x2+nx,y2+ny],[x2-nx,y2-ny],[x1-nx,y1-ny]],{fill:color,stroke:"none"});
  },
  getTaperedLimb: (x1,y1,x2,y2,widthStart=10,widthEnd=6,color="green",options={}) => {
    const dx=x2-x1,dy=y2-y1,len=Math.hypot(dx,dy);
    if(len<1e-9) return Toolkit.circle(x1,y1,Math.max(widthStart,widthEnd)/2,{fill:color,...options});
    const nx=-dy/len,ny=dx/len;
    return Toolkit.polygon([[x1+nx*widthStart/2,y1+ny*widthStart/2],[x2+nx*widthEnd/2,y2+ny*widthEnd/2],
      [x2-nx*widthEnd/2,y2-ny*widthEnd/2],[x1-nx*widthStart/2,y1-ny*widthStart/2]],{fill:color,...options});
  },

  getLinearGradient: (id,ss,options={}) => {
    const body=stops(ss).map(s=>`<stop offset="${esc(String(s.offset).includes("%")?s.offset:`${s.offset}%`)}" stop-color="${esc(s.color)}"${attr("stop-opacity",s.opacity)} />`).join("");
    return `<linearGradient id="${esc(id)}" x1="${esc(options.x1??"0%")}" y1="${esc(options.y1??"0%")}" x2="${esc(options.x2??"100%")}" y2="${esc(options.y2??"0%")}">${body}</linearGradient>`;
  },
  getRadialGradient: (id,cx,cy,r,ss) => {
    const body=stops(ss).map(s=>`<stop offset="${esc(String(s.offset).includes("%")?s.offset:`${s.offset}%`)}" stop-color="${esc(s.color)}"${attr("stop-opacity",s.opacity)} />`).join("");
    return `<radialGradient id="${esc(id)}" cx="${esc(cx)}%" cy="${esc(cy)}%" r="${esc(r)}%">${body}</radialGradient>`;
  },
  defs: definitions => `<defs>${(Array.isArray(definitions)?definitions:[definitions]).join("\n")}</defs>`,

  midpoint: (x1,y1,x2,y2) => ({x:(x1+x2)/2,y:(y1+y2)/2}),
  distance: (x1,y1,x2,y2) => Math.hypot(x2-x1,y2-y1),
  clamp: (v,min,max) => Math.max(min,Math.min(max,v)),
  lerp: (a,b,t) => a+(b-a)*t,
  mapRange: (v,inMin,inMax,outMin,outMax) => {
    if(inMax===inMin) throw new RangeError("Input range must not be zero");
    return outMin+((v-inMin)/(inMax-inMin))*(outMax-outMin);
  },
  jitter: (v,amount,random=Math.random) => v+(random()*2-1)*amount,
  seededJitter: (v,amount,seed=1) => {
    let x=(Math.trunc(seed)||1)>>>0; x^=x<<13; x^=x>>>17; x^=x<<5;
    return v+(((x>>>0)/4294967295)*2-1)*amount;
  },

  generateFace: (cx,cy,rw,rh,skinColor,options={}) => {
    const {shape="oval",eyeColor="#000",mouth="smile",outline="none",outlineWidth=1,nose=true,
      eyeScale=1,eyeOffsetX=0.4,eyeOffsetY=-0.2,mouthColor="#000",mouthWidth=2}=options;
    const e=[],base={fill:skinColor,stroke:outline,strokeWidth:outlineWidth};
    if(shape==="oval") e.push(Toolkit.ellipse(cx,cy,rw,rh,base));
    else if(shape==="heart") e.push(Toolkit.path(`M ${cx},${cy+rh*.2} C ${cx-rw},${cy-rh*.5} ${cx-rw*1.5},${cy+rh*.2} ${cx},${cy+rh*.8} C ${cx+rw*1.5},${cy+rh*.2} ${cx+rw},${cy-rh*.5} ${cx},${cy+rh*.2} Z`,base));
    else if(shape==="square") e.push(Toolkit.rect(cx-rw,cy-rh,rw*2,rh*2,{...base,rx:rw*.2}));
    else if(shape==="diamond") e.push(Toolkit.polygon([[cx,cy-rh],[cx+rw,cy],[cx,cy+rh],[cx-rw,cy]],base));
    else e.push(Toolkit.ellipse(cx,cy,rw,rh,base));
    const er=rw*.15*eyeScale,ey=cy+rh*eyeOffsetY,ex=rw*eyeOffsetX;
    e.push(Toolkit.circle(cx-ex,ey,er,{fill:eyeColor}),Toolkit.circle(cx+ex,ey,er,{fill:eyeColor}));
    if(nose)e.push(Toolkit.line(cx,cy,cx,cy+rh*.2,{stroke:"#8a6654",strokeWidth:Math.max(.5,rw*.025),opacity:.7}));
    if(mouth==="smile")e.push(Toolkit.path(`M ${cx-rw*.3},${cy+rh*.3} Q ${cx},${cy+rh*.5} ${cx+rw*.3},${cy+rh*.3}`,{fill:"none",stroke:mouthColor,strokeWidth:mouthWidth,linecap:"round"}));
    else if(mouth==="frown")e.push(Toolkit.path(`M ${cx-rw*.3},${cy+rh*.45} Q ${cx},${cy+rh*.25} ${cx+rw*.3},${cy+rh*.45}`,{fill:"none",stroke:mouthColor,strokeWidth:mouthWidth,linecap:"round"}));
    else e.push(Toolkit.line(cx-rw*.2,cy+rh*.4,cx+rw*.2,cy+rh*.4,{stroke:mouthColor,strokeWidth:mouthWidth,linecap:"round"}));
    return e;
  },

  palettes: {
    rainbow:["#FF0000","#FF7F00","#FFFF00","#00FF00","#0000FF","#4B0082","#8B00FF"],
    material:["#F44336","#E91E63","#9C27B0","#673AB7","#3F51B5","#2196F3","#03A9F4"],
    pastel:["#FFB7B2","#FFDAC1","#E2F0CB","#B5EAD7","#C7CEEA","#FF9AA2","#D4A5A4"],
    monochrome:["#FFFFFF","#F0F0F0","#D0D0D0","#A0A0A0","#808080","#404040","#000000"],
    dungeon:["#0a0a0a","#1a1a1a","#2d3319","#4b5320","#8b9c42","#c2d16b"],
    skintones:{fair:"#FFDBAC",light:"#F1C27D",medium:"#E0AC69",tan:"#8D5524",deep:"#C68642",dark:"#3C2E28"}
  }
};
