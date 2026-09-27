#version 440
// googlebeam.frag — per-pixel Google-style light rail for the Kinetix bars.
//
// Everything is computed analytically per device pixel, so there are no
// gradient layers to band and no textures to blur:
//   * colour flows along the rail through Google blue → red → yellow → green,
//     interpolated in OKLab (perceptual) space so the transitions stay vivid
//     instead of passing through grey/mud the way sRGB mixing does;
//   * the colour boundaries are domain-warped by slow noise, so they drift and
//     breathe organically rather than scrolling rigidly;
//   * brightness "plumes" rise and fall along the rail (fbm), taller bloom
//     where the light is strongest;
//   * a crisp, whitened hot core sits on the edge, travelling highlights
//     glide through it;
//   * intensity is composed in display space, soft-shouldered (no hard
//     clip) and dithered, so the falloff is exactly as specified and smooth.
//
// Compile: /usr/lib/qt6/bin/qsb --glsl "100es,120,150" --hlsl 50 --msl 12 \
//            -o googlebeam.frag.qsb googlebeam.frag

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;      // flow clock, seconds (speed-integrated on the CPU)
    float gain;      // overall brightness
    float pulse;     // transient burst 0..1
    float blocked;   // 0 = Google palette, 1 = alert palette (animated)
    float edgeTop;   // 1 = rail on the top edge, 0 = on the bottom edge
    float resW;      // item size in logical px
    float resH;
    float fadeLen;   // px faded out at each end of the rail (0 = none)
};

// ── palettes, OKLab ────────────────────────────────────────────────────
const vec3 BLUE   = vec3(0.6304, -0.0314, -0.1773);
const vec3 RED    = vec3(0.6257,  0.1799,  0.1000);
const vec3 YELLOW = vec3(0.8304,  0.0177,  0.1690);
const vec3 GREEN  = vec3(0.6475, -0.1367,  0.0838);
const vec3 CRIM   = vec3(0.6089,  0.1973,  0.0882);
const vec3 ORANGE = vec3(0.7201,  0.1254,  0.1213);
const vec3 AMBER  = vec3(0.8055,  0.0620,  0.1302);
const vec3 DEEP   = vec3(0.5364,  0.1839,  0.0817);

vec3 oklabToLinear(vec3 c) {
    float l_ = c.x + 0.3963377774 * c.y + 0.2158037573 * c.z;
    float m_ = c.x - 0.1055613458 * c.y - 0.0638541728 * c.z;
    float s_ = c.x - 0.0894841775 * c.y - 1.2914855480 * c.z;
    float l = l_ * l_ * l_, m = m_ * m_ * m_, s = s_ * s_ * s_;
    return vec3( 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
                -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
                -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s);
}

vec3 linearToSrgb(vec3 c) {
    c = max(c, vec3(0.0));
    return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c));
}

// cyclic 4-stop palette with smoothstep easing between stops (C1-continuous,
// so no visible "kinks" where one hue hands over to the next)
vec3 cyc4(vec3 a, vec3 b, vec3 c, vec3 d, float h) {
    h = fract(h) * 4.0;
    float i = floor(h);
    float k = smoothstep(0.0, 1.0, h - i);
    k = k * k * (3.0 - 2.0 * k) * 0.35 + k * 0.65;    // hold each hue a touch longer
    if (i < 1.0) return mix(a, b, k);
    if (i < 2.0) return mix(b, c, k);
    if (i < 3.0) return mix(c, d, k);
    return mix(d, a, k);
}

vec3 palette(float h) {
    vec3 g = cyc4(BLUE, RED, YELLOW, GREEN, h);
    vec3 r = cyc4(CRIM, ORANGE, DEEP, AMBER, h);
    return oklabToLinear(mix(g, r, blocked));
}

// ── noise ──────────────────────────────────────────────────────────────
float hash(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);   // quintic: no grid creases
    return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x),
               mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
}
float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 4; i++) {
        v += a * noise(p);
        p = p * 2.03 + vec2(17.1, 9.3);
        a *= 0.5;
    }
    return v;
}

// a highlight gliding along the rail: gaussian in x around a moving point
float glint(float x, float speed, float offset, float width, float span) {
    float pos = fract(time * speed + offset) * (span + 2.0 * width) - width;
    float t = (x - pos) / width;
    return exp(-t * t);
}

void main() {
    vec2 p = qt_TexCoord0 * vec2(resW, resH);
    float x = p.x;
    float d = mix(resH - p.y, p.y, edgeTop);          // px from the rail edge

    // ── colour field ──
    float warp = fbm(vec2(x / 540.0, time * 0.055)) - 0.5;
    float h = x / 1150.0 - time * 0.045 + 0.42 * warp + d * 0.0035;
    vec3 col = palette(h);
    vec3 colCore = palette(h + 0.015);

    // ── brightness plumes along the rail ──
    float plume = smoothstep(0.22, 0.80, fbm(vec2(x / 360.0 - time * 0.12, time * 0.035 + 3.1)));
    float span = resW;
    float g = glint(x, 0.050, 0.00, 150.0, span) * 1.00
            + glint(x, 0.031, 0.41, 230.0, span) * 0.70
            + glint(x, 0.074, 0.73, 110.0, span) * 0.85;

    // ── vertical profile (perceptual intensity, px from the edge) ──
    // Intensities are composed in display space, not linear light: sRGB
    // encoding lifts faint linear tails (0.02 → ~0.15), which would smear a
    // wash over the whole bar. Here the falloff you specify is what you see.
    // Light stays concentrated on the rail: a crisp core, a tight glow, and a
    // restrained bloom that swells only where a plume or glint passes.
    float coreT = (d - 0.9) / 0.80;
    float core  = exp(-coreT * coreT);                               // crisp ~2px line
    float inner = exp(-d / 3.0);                                     // tight glow hugging it
    float bloomR = 9.0 + 12.0 * plume + 10.0 * g + 6.0 * pulse;
    float bloom = exp(-pow(d / bloomR, 1.45));                        // soft rising light
    float haze  = exp(-d / 22.0);                                    // faint atmosphere

    float glow = 0.78 * inner
               + (0.30 + 0.58 * plume + 0.60 * g) * bloom
               + (0.06 + 0.06 * plume) * haze;
    float boost = gain * (1.0 + 0.7 * pulse);

    vec3 cS = linearToSrgb(col);
    vec3 hot = mix(linearToSrgb(colCore), vec3(1.0), 0.45 + 0.40 * g);
    vec3 rgb = (cS * glow + hot * core * (1.0 + 0.9 * g)) * boost;

    // soft shoulder: the hot core rolls off to white instead of clipping flat
    rgb = (vec3(1.0) - exp(-rgb * 1.4)) / (1.0 - exp(-1.4));

    // triangular dither kills 8-bit banding in the long falloff
    float n = hash(gl_FragCoord.xy + fract(time * 7.0) * 61.0) + hash(gl_FragCoord.yx * 1.37) - 1.0;
    rgb = clamp(rgb + n / 255.0, 0.0, 1.0);

    // premultiplied, partly additive: light brightens the glass beneath it
    // rather than painting an opaque film over it
    // optional soft ends, for rails shorter than their surface (the dock)
    if (fadeLen > 0.0) {
        float f = smoothstep(0.0, fadeLen, x) * smoothstep(0.0, fadeLen, resW - x);
        // and fade the glow out before the strip's inner edge, so a narrow
        // strip never ends in a hard line (the bars keep their full falloff)
        f *= 1.0 - smoothstep(resH * 0.35, resH, d);
        rgb *= f;
    }

    float a = max(rgb.r, max(rgb.g, rgb.b)) * 0.45;
    fragColor = vec4(rgb, a) * qt_Opacity;
}
