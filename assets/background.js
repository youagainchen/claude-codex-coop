// AI Coop 面板动态背景（WebGL）。
// SPDX-License-Identifier: CC-BY-NC-SA-3.0 (aurora shader) — see NOTICE.md
// “极光”着色器改编自 nimitz (@stormoid) 的 Shadertoy 作品 “Auroras”（https://www.shadertoy.com/view/XtGGRt），
// 依 Shadertoy 默认许可 CC BY-NC-SA 3.0 使用：署名、非商业、相同方式共享。其余着色器为本项目原创（MIT）。
(() => {
  const VERT = 'attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}';
  const HEAD = `precision highp float;uniform vec2 R;uniform float T;uniform vec2 M;uniform float I;
float h21(vec2 n){return fract(sin(dot(n,vec2(12.9898,4.1414)))*43758.5453);}
vec3 h33(vec3 p){p=fract(p*vec3(443.8975,397.2973,491.1871));p+=dot(p.zxy,p.yxz+19.27);return fract(vec3(p.x*p.y,p.z*p.x,p.y*p.z));}
vec3 stars(vec3 p,float d,float sc){vec3 c=vec3(0.);float res=R.y*sc;
 for(float i=0.;i<4.;i++){vec3 q=fract(p*(.15*res))-.5;vec3 id=floor(p*(.15*res));vec2 rn=h33(id).xy;
  float s=1.-smoothstep(0.,.6,length(q));s*=step(rn.x,(.0005+i*i*.001)*d);
  s*=.65+.35*sin(T*1.7+rn.y*40.);
  c+=s*(mix(vec3(1.,.49,.1),vec3(.75,.9,1.),rn.y)*.1+.9);p*=1.3;}
 return c*c*.8;}
vec3 ray(){vec2 u=gl_FragCoord.xy/R;vec2 p=vec2(u.x-.5,u.y*.55+.015);p.x*=R.x/R.y;p+=(M-.5)*vec2(.10,.04);return normalize(vec3(p,1.3));}
`;
  const SHADERS = {
    aurora: HEAD + `
mat2 mm2(float a){float c=cos(a),s=sin(a);return mat2(c,s,-s,c);}
float tri(float x){return clamp(abs(fract(x)-.5),.01,.49);}
vec2 tri2(vec2 p){return vec2(tri(p.x)+tri(p.y),tri(p.y+tri(p.x)));}
float triNoise(vec2 p,float spd){float z=1.8,z2=2.5,rz=0.;p*=mm2(p.x*.06);vec2 bp=p;
 mat2 m2=mat2(.95534,.29552,-.29552,.95534);
 for(float i=0.;i<5.;i++){vec2 dg=tri2(bp*1.85)*.75;dg*=mm2(T*spd);p-=dg/z2;bp*=1.3;z2*=.45;z*=.42;
  p*=1.21+(rz-1.)*.02;rz+=tri(p.x+tri(p.y))*z;p*=-m2;}
 return clamp(1./pow(rz*29.,1.3),0.,.55);}
vec4 aurora(vec3 ro,vec3 rd){vec4 col=vec4(0.),avg=vec4(0.);
 for(float i=0.;i<42.;i++){float of=.006*h21(gl_FragCoord.xy)*smoothstep(0.,15.,i);
  float pt=((.8+pow(i,1.4)*.002)-ro.y)/(rd.y*2.+.4)-of;vec3 b=ro+pt*rd;float rz=triNoise(b.zx+vec2(T*.05,0.),.16);
  vec4 c2=vec4((sin(1.-vec3(2.15,-.5,1.2)+i*.043)*.5+.5)*rz,rz);avg=mix(avg,c2,.5);
  col+=avg*exp2(-i*.065-2.5)*smoothstep(0.,5.,i);}
 col*=clamp(rd.y*15.+.4,0.,1.);return col*1.8;}
void main(){vec3 rd=ray();vec3 ro=vec3(0.,0.,-6.7);
 float sd=pow(dot(normalize(vec3(-.5,-.6,.9)),rd)*.5+.5,5.);
 vec3 col=mix(vec3(.05,.1,.2),vec3(.1,.05,.2),sd)*.63;
 vec2 su=gl_FragCoord.xy/R;float rev=1.-smoothstep(I*1.25-.15,I*1.25+.1,su.y);
 vec4 a=smoothstep(0.,1.5,aurora(ro,rd))*rev;col*=smoothstep(0.,.5,I);col+=stars(rd,1.,.4)*smoothstep(.4,1.,I);col=col*(1.-a.a)+a.rgb;
 gl_FragColor=vec4(col,1.);}`,
    galaxy: HEAD + `
float n2(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
 return mix(mix(h21(i),h21(i+vec2(1,0)),f.x),mix(h21(i+vec2(0,1)),h21(i+vec2(1,1)),f.x),f.y);}
float fbm(vec2 p){float v=0.,a=.5;for(int i=0;i<6;i++){v+=a*n2(p);p=p*2.03+vec2(1.7,9.2);a*=.5;}return v;}
void main(){vec2 u=gl_FragCoord.xy/R;vec2 p=(u-.5)*vec2(R.x/R.y,1.)+(M-.5)*.06;
 float ang=-1.12+.02*sin(T*.1);vec2 q=mat2(cos(ang),-sin(ang),sin(ang),cos(ang))*p;
 float warp=fbm(q*2.+T*.03);
 float band=exp(-pow(q.y*2.4+.35*(warp-.5)+.1*sin(q.x*3.),2.));
 float neb=fbm(q*3.2+vec2(T*.04,warp));float dust=fbm(q*8.-vec2(0.,T*.025));
 vec3 col=mix(vec3(.010,.012,.035),vec3(.03,.02,.07),u.y);
 col+=band*mix(vec3(.30,.14,.62),vec3(.08,.50,.72),smoothstep(.3,.75,neb))*(.7+1.6*neb);
 col+=pow(band,3.)*vec3(1.,.86,.70)*.55*smoothstep(.4,.85,neb);
 col*=1.-.6*band*smoothstep(.52,.72,dust);
 col+=stars(normalize(vec3(p,1.3)),3.+10.*band,1.4);
 col+=stars(normalize(vec3(p.yx,1.3)),1.5,.7)*.8;
 gl_FragColor=vec4(col*smoothstep(0.,1.,I),1.);}`,
    horizon: HEAD + `
void main(){vec2 u=gl_FragCoord.xy/R;float asp=R.x/R.y;vec2 p=vec2((u.x-.5)*asp,u.y);
 float breathe=.5+.5*sin(T*.35);
 float cy=-.55-.5*(1.-smoothstep(0.,1.,I));float r=length(vec2(p.x,p.y-cy))-(.78+.02*breathe);
 float hx=(M.x-.5)*asp;float rim=exp(-abs(r)*38.)*(.7+.6*exp(-pow((p.x-hx)*2.2,2.)));float halo=exp(-max(r,0.)*5.5);float inner=smoothstep(.02,-.2,r);
 vec3 warm=vec3(1.,.55,.22),hot=vec3(1.,.85,.6),cool=vec3(.35,.25,.9);
 vec3 col=mix(vec3(.02,.02,.05),vec3(.07,.04,.12),u.y);
 col+=halo*mix(warm,cool,smoothstep(.0,.6,r))*.55;
 col+=rim*hot*1.4;
 col=mix(col,vec3(.01,.01,.02),inner*.92);
 col+=stars(normalize(vec3(p,1.3)),1.2,.4)*smoothstep(.15,.6,r);
 col+=(h21(gl_FragCoord.xy+T)-.5)*.015;
 gl_FragColor=vec4(col,1.);}`
  };

  const canvas = document.createElement('canvas');
  canvas.id = 'bg';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  const gl = canvas.getContext('webgl', {antialias: false, alpha: false, powerPreference: 'low-power'});
  const programs = {};
  let current = null, raf = 0, last = 0, start = performance.now(), intro = 0;
  const mouse = {x: .5, y: .5, tx: .5, ty: .5};
  const INTRO_MS = 1800;   // 切换背景时的开场动画时长
  const SCALE = 0.5;   // 半分辨率渲染再由 CSS 拉伸：画面本就柔和，省一半以上 GPU
  const FRAME = 1000 / 30;

  function compile(type, src) {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }
  function program(name) {
    if (programs[name]) return programs[name];
    const p = gl.createProgram();
    gl.attachShader(p, compile(gl.VERTEX_SHADER, VERT));
    gl.attachShader(p, compile(gl.FRAGMENT_SHADER, SHADERS[name]));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    return programs[name] = {p, R: gl.getUniformLocation(p, 'R'), T: gl.getUniformLocation(p, 'T'), M: gl.getUniformLocation(p, 'M'), I: gl.getUniformLocation(p, 'I'), a: gl.getAttribLocation(p, 'a')};
  }
  if (gl) {
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  }
  function resize() {
    const w = Math.max(1, Math.round(innerWidth * SCALE)), h = Math.max(1, Math.round(innerHeight * SCALE));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  }
  function frame(now) {
    raf = requestAnimationFrame(frame);
    if (now - last < FRAME) return;
    last = now;
    draw(now);
  }
  function draw(now) {
    if (!gl || !current) return;
    resize();
    const pr = program(current);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.useProgram(pr.p);
    gl.enableVertexAttribArray(pr.a);
    gl.vertexAttribPointer(pr.a, 2, gl.FLOAT, false, 0, 0);
    gl.uniform2f(pr.R, canvas.width, canvas.height);
    mouse.x += (mouse.tx - mouse.x) * .08; mouse.y += (mouse.ty - mouse.y) * .08;
    gl.uniform1f(pr.T, (now - start) / 1000);
    gl.uniform2f(pr.M, mouse.x, mouse.y);
    gl.uniform1f(pr.I, reduced.matches ? 1 : Math.min(1, (now - intro) / INTRO_MS));
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  function stop() { cancelAnimationFrame(raf); raf = 0; }
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');

  window.AICoopBackground = {
    names: {system: '跟随 App', aurora: '极光', galaxy: '星河', horizon: '地平线'},
    set(name) {
      document.documentElement.dataset.bg = name;
      stop();
      current = gl && SHADERS[name] ? name : null;
      canvas.hidden = !current;
      if (!current) return;
      try { program(current); } catch (e) { console.error(e); current = null; canvas.hidden = true; document.documentElement.dataset.bg = 'plain'; return; }
      intro = performance.now();
      if (reduced.matches) draw(performance.now()); else raf = requestAnimationFrame(frame);
    }
  };
  addEventListener('pointermove', e => { mouse.tx = e.clientX / innerWidth; mouse.ty = 1 - e.clientY / innerHeight; });
  document.addEventListener('pointerleave', () => { mouse.tx = .5; mouse.ty = .5; });
  addEventListener('resize', () => { if (current) draw(performance.now()); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop(); else if (current && !raf && !reduced.matches) raf = requestAnimationFrame(frame);
  });
})();
