#version 440
// rgbflow.frag — animated red / green / blue light field filling a glass
// surface: the dock's rail, the top bar and the taskbar. Colours flow along the rail and blend in OKLab (so the
// hand-overs stay vivid instead of turning muddy); brightness plumes drift
// through it; the rounded outline glows a little brighter. The rail's
// rounded-rectangle shape is computed here (SDF), so the corners are
// anti-aliased and nothing needs a mask.
//
// Compile: /usr/lib/qt6/bin/qsb --glsl "100es,120,150" --hlsl 50 --msl 12 \
//            -o rgbflow.frag.qsb rgbflow.frag

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;     // flow clock, seconds
    float gain;     // overall brightness
    float resW;     // item size, logical px
    float resH;
    float radius;   // corner radius, logical px
    float horizontal; // 1 = colour flows along x (bars), 0 = along y (dock)
    float period;   // px per red→green→blue cycle along the flow
    float pulse;    // transient brightness burst 0..1
};

// Google red / green / blue, OKLab
const vec3 RED   = vec3(0.6257,  0.1799,  0.1000);
const vec3 GREEN = vec3(0.6475, -0.1367,  0.0838);
const vec3 BLUE  = vec3(0.6304, -0.0314, -0.1773);

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

// cyclic red → green → blue → red, eased between stops
vec3 palette(float h) {
    h = fract(h) * 3.0;
    float i = floor(h);
    float k = smoothstep(0.0, 1.0, h - i);
    vec3 c = i < 1.0 ? mix(RED, GREEN, k) : (i < 2.0 ? mix(GREEN, BLUE, k) : mix(BLUE, RED, k));
    return oklabToLinear(c);
}

float hash(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
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

// signed distance to a rounded box centred at the origin
float sdRoundBox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

void main() {
    vec2 res = vec2(resW, resH);
    vec2 p = qt_TexCoord0 * res;

    // rounded-rail shape, anti-aliased over ~1px
    float d = sdRoundBox(p - res * 0.5, res * 0.5 - 0.5, radius);
    float inside = 1.0 - smoothstep(-0.75, 0.75, d);
    if (inside <= 0.0) { fragColor = vec4(0.0); return; }

    // flow coordinates: `along` runs the length of the surface
    float along  = mix(p.y, p.x, horizontal);
    float across = mix(p.x, p.y, horizontal);
    float len    = mix(resH, resW, horizontal);

    // colour flows along the surface, boundaries warped so they drift organically
    // noise scales follow the colour period, so a long bar gets a few broad
    // drifts (like the dock) instead of many small blotches
    float scale = period / 560.0;
    float warp = fbm(vec2(across / 60.0, along / (160.0 * scale) - time * 0.05)) - 0.5;
    float h = along / period - time * 0.055 + 0.55 * warp + across / 420.0;
    vec3 col = linearToSrgb(palette(h));

    // brightness plumes drifting through the glass
    float plume = smoothstep(0.25, 0.85, fbm(vec2(across / 45.0 + 3.0, along / (110.0 * scale) + time * 0.11)));
    // a slow bright band travelling the length of the surface
    float band = exp(-pow((fract(time * 0.045) * (len + 240.0) - 120.0 - along) / 90.0, 2.0));
    // the outline catches more light
    float rim = exp(d / 2.2) * 0.9 + exp(d / 9.0) * 0.35;

    float glow = 0.20 + 0.34 * plume + 0.22 * band;
    vec3 rgb = col * (glow + rim) * gain * (1.0 + 0.6 * pulse);
    rgb += vec3(1.0) * pow(max(0.0, exp(d / 1.4)), 2.0) * 0.18 * gain;   // hairline highlight

    // soft shoulder + dither (no banding in the long gradients)
    rgb = (vec3(1.0) - exp(-rgb * 1.4)) / (1.0 - exp(-1.4));
    float n = hash(gl_FragCoord.xy + fract(time * 7.0) * 61.0) + hash(gl_FragCoord.yx * 1.37) - 1.0;
    rgb = clamp(rgb + n / 255.0, 0.0, 1.0) * inside;

    // premultiplied, partly additive over the dark glass
    float a = max(rgb.r, max(rgb.g, rgb.b)) * 0.6;
    fragColor = vec4(rgb, a) * qt_Opacity;
}
