"""Seamless (tileable) noise for the Studio's own textures - adapted from Procedural-PBR by Whappens (MIT,
https://github.com/Whappens/Procedural-PBR, commit 30c7111, common/noise.py and common/mathutils.py; the licence in
tools/third_party/procedural_pbr_LICENSE.txt). Kept as it is there but for the package imports."""
import numpy as np

def normalize01(a):
    """Rescales an array so its values span exactly [0, 1]."""
    return (a - a.min()) / (a.max() - a.min() + 1e-9)


def to_u8(arr01):
    """Converts a 0-1 float array to a clipped uint8 array (0-255)."""
    return np.clip(arr01 * 255.0, 0, 255).astype(np.uint8)


def posterize(arr, levels):
    """Quantizes a 0-1 array into a fixed number of flat bands - used for
    hand-painted/stylized shading and for pixel-art color quantization."""
    levels = max(2, levels)
    return np.round(arr * (levels - 1)) / (levels - 1)


def adjust_saturation(r, g, b, factor):
    """Pushes RGB channels away from (factor>1) or toward (factor<1) their
    per-pixel mean - a cheap saturation boost without a full HSV round-trip."""
    mean = (r + g + b) / 3.0
    return (mean + (r - mean) * factor,
            mean + (g - mean) * factor,
            mean + (b - mean) * factor)


def lerp(a, b, t):
    return a + (b - a) * t


def smootherstep_compress(x, edge0, edge1):
    """Ken Perlin's improved smoothstep (quintic, C2-continuous). Unlike a
    hard np.clip, both the first AND second derivative go to zero at the 0/1
    boundaries, so a shape eases into its peak instead of cutting off into a
    flat plateau with a visible ridge line."""
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * t * (t * (t * 6 - 15) + 10)


def sharpen_crests(height, power):
    """Pinches a smooth noise field into sharp peaks / flat troughs, like
    real wave crests or blob tops instead of soft sine-wave bumps."""
    shaped = 1.0 - np.abs(height - 0.5) * 2.0
    shaped = np.clip(shaped, 0.0, 1.0)
    return np.power(shaped, power)

def generate_perlin_noise_2d(shape, res, seed=None):
    """Generates seamless (tileable) 2D Perlin noise.

    res: int (isotropic frequency) or an (res_x, res_y) tuple for anisotropic
    noise - e.g. a low res_y stretches features vertically, which is used for
    streaking/weathering/blade-grain effects.

    seed: if given, reseeds the global numpy RNG before drawing gradients so
    this call is independently reproducible; if omitted, this call continues
    whatever RNG stream the caller already seeded (handy for stacking octaves
    off a single outer seed without juggling per-octave offsets).
    """
    if seed is not None:
        np.random.seed(seed)

    def f(t):
        return 6*t**5 - 15*t**4 + 10*t**3

    res_x, res_y = res if isinstance(res, tuple) else (res, res)

    # float32/int32 instead of numpy's float64/int64 defaults: at 4K each of
    # the ~15 full-resolution temporaries below is ~128MB in float64 vs ~64MB
    # in float32, and this function (plus fbm_perlin, which calls it several
    # times per octave) is the hottest allocation path in every generator -
    # halving it is what keeps 4K runs from paging/OOMing on memory-limited
    # machines.
    x = np.linspace(0, res_x, shape, endpoint=False, dtype=np.float32)
    y = np.linspace(0, res_y, shape, endpoint=False, dtype=np.float32)
    x_grid, y_grid = np.meshgrid(x, y, indexing="ij")

    r0_x, r0_y = x_grid % 1.0, y_grid % 1.0
    r1_x, r1_y = r0_x - 1.0, r0_y - 1.0

    gradients = np.random.randn(res_x, res_y, 2).astype(np.float32)
    norm = np.linalg.norm(gradients, axis=-1, keepdims=True)
    gradients = np.where(norm > 0, gradients / norm, gradients).astype(np.float32)

    i_x, i_y = (x_grid // 1).astype(np.int32), (y_grid // 1).astype(np.int32)

    i_x0 = i_x % res_x
    i_x1 = (i_x + 1) % res_x
    i_y0 = i_y % res_y
    i_y1 = (i_y + 1) % res_y

    n00 = gradients[i_x0, i_y0][..., 0] * r0_x + gradients[i_x0, i_y0][..., 1] * r0_y
    n10 = gradients[i_x1, i_y0][..., 0] * r1_x + gradients[i_x1, i_y0][..., 1] * r0_y
    n01 = gradients[i_x0, i_y1][..., 0] * r0_x + gradients[i_x0, i_y1][..., 1] * r1_y
    n11 = gradients[i_x1, i_y1][..., 0] * r1_x + gradients[i_x1, i_y1][..., 1] * r1_y

    t_x, t_y = f(r0_x), f(r0_y)
    return (n00 * (1.0 - t_x) + n10 * t_x) * (1.0 - t_y) + (n01 * (1.0 - t_x) + n11 * t_x) * t_y


def fbm_perlin(shape, base_res, octaves=3, persistence=0.5, lacunarity=2.0, seed=None):
    """Fractal Brownian Motion: stacked Perlin octaves
    (1.0*res + 0.5*2res + 0.25*4res + ...). If seed is given, each octave
    draws from an independent, reproducible seed (seed + octave index);
    otherwise every octave continues the caller's already-seeded RNG stream."""
    total = np.zeros((shape, shape), dtype=np.float32)
    amplitude = 1.0
    frequency = 1.0
    max_amp = 0.0
    for o in range(octaves):
        res = max(2, int(round(base_res * frequency)))
        octave_seed = None if seed is None else seed + o
        total += generate_perlin_noise_2d(shape, res, seed=octave_seed) * amplitude
        max_amp += amplitude
        amplitude *= persistence
        frequency *= lacunarity
    return total / max_amp


def generate_voronoi_f1_f2(shape, cells, seed, warp_strength=0.0, warp_res=4):
    """Seamless (tileable) Voronoi cell distances. Returns (F1, F2): distance
    to the nearest feature point and to the second-nearest one. F2-F1 is the
    true distance-to-edge field (small near cell borders, large at centers).

    warp_strength domain-warps the sample coordinates with Perlin noise so
    the cell grid isn't perfectly static/regular.
    """
    np.random.seed(seed)
    points = np.random.rand(cells, cells, 2)

    px = (np.arange(shape) / shape) * cells
    py = (np.arange(shape) / shape) * cells
    PX, PY = np.meshgrid(px, py, indexing="ij")

    if warp_strength > 0:
        warp_x = generate_perlin_noise_2d(shape, warp_res, seed=seed + 500)
        warp_y = generate_perlin_noise_2d(shape, warp_res, seed=seed + 501)
        PX = PX + warp_x * warp_strength * cells
        PY = PY + warp_y * warp_strength * cells

    cell_x = np.floor(PX).astype(int)
    cell_y = np.floor(PY).astype(int)

    f1 = np.full((shape, shape), np.inf, dtype=np.float32)
    f2 = np.full((shape, shape), np.inf, dtype=np.float32)

    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            ncx = cell_x + dx
            ncy = cell_y + dy
            idx_x = ncx % cells
            idx_y = ncy % cells
            point_x = ncx + points[idx_x, idx_y, 0]
            point_y = ncy + points[idx_x, idx_y, 1]
            dist = np.sqrt((PX - point_x) ** 2 + (PY - point_y) ** 2)

            closer = dist < f1
            f2 = np.where(closer, f1, np.minimum(f2, dist))
            f1 = np.where(closer, dist, f1)

    return f1, f2


def generate_worley_f1(shape, cells, seed, warp_strength=0.0):
    """Normalized F1-only Worley/Voronoi field (0 on a feature point, ~1 at
    the farthest cell-interior point) - a thin convenience wrapper around
    generate_voronoi_f1_f2 for callers that just want 'bubble' style noise."""
    f1, _ = generate_voronoi_f1_f2(shape, cells, seed, warp_strength)
    f1 = f1 / (np.sqrt(2.0) * 0.5)
    return np.clip(f1, 0.0, 1.0)


def voronoi_edge_lines(shape, cells, seed, warp_strength, sharpen_power):
    """Distance-to-edge Voronoi collapsed into thin bright lines: invert the
    F2-F1 edge field (edges -> bright, cell interiors -> dark) then raise to a
    power so only the sharpest edge pixels stay lit."""
    f1, f2 = generate_voronoi_f1_f2(shape, cells, seed, warp_strength)
    edge_dist = normalize01(f2 - f1)
    lines = np.clip(1.0 - edge_dist, 0.0, 1.0)
    return np.power(lines, sharpen_power)


def layered_caustic_network(shape, cells_a, cells_b, warp_strength, sharpen_power, seed):
    """Two edge-line Voronoi layers at different scales, each independently
    domain-warped, blended with a Maximum ('lighten') combine so the webs
    overlap into a connected network instead of a single regular grid."""
    layer_a = voronoi_edge_lines(shape, cells_a, seed, warp_strength, sharpen_power)
    layer_b = voronoi_edge_lines(shape, cells_b, seed + 1000, warp_strength, sharpen_power)
    return np.maximum(layer_a, layer_b)


def tileable_gaussian_blur(img, sigma):
    """Seamless (toroidal) Gaussian blur via the frequency domain. Multiplying
    by a Gaussian in frequency space is mathematically identical to spatial
    convolution with a Gaussian kernel, and because numpy's FFT is inherently
    periodic, the blur wraps around every edge automatically - no manual
    padding/wrap bookkeeping, and no seams."""
    if sigma <= 0:
        return img
    size = img.shape[0]
    freqs = np.fft.fftfreq(size)
    fx, fy = np.meshgrid(freqs, freqs, indexing="ij")
    gaussian_kernel_freq = np.exp(-2.0 * (np.pi ** 2) * (sigma ** 2) * (fx ** 2 + fy ** 2))
    blurred = np.fft.ifft2(np.fft.fft2(img) * gaussian_kernel_freq)
    return np.real(blurred)


def central_diff_gradients(height):
    """Cheap tileable gradient via wraparound central differences."""
    hx = np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)
    hy = np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)
    return hx, hy


def sobel_gradients(height):
    """Tileable Sobel operator (manual convolution via np.roll so wraparound
    stays seamless) - smoother/more accurate than a plain central difference."""
    kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float64)
    ky = kx.T

    def convolve(img, kernel):
        result = np.zeros_like(img)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                w = kernel[i + 1, j + 1]
                if w != 0:
                    result += w * np.roll(np.roll(img, -i, axis=0), -j, axis=1)
        return result

    gx = convolve(height, kx)
    gy = convolve(height, ky)
    return gx, gy
