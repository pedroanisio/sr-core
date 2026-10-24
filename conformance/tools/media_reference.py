"""Reference implementation of the participating-medium model of the draft SREP "Define the participating-medium
model and its phase functions" (srep/srep-0000-media.md, the F3 building block of SREP 12).

Standard-library Python, written from the SREP text. Every function is pure. The names are the SREP's:

- coefficients, combine, emission: the extinction, scattering and absorption coefficients and the emission of a
  medium at a point (SREP sections 1 and 2);
- transmittance, step_weight: Beer-Lambert transmittance and the exact weight of one march step (section 2);
- surface_absorption: the absorption of a transmissive surface's interior as a medium (section 3);
- phase_hg, phase_rayleigh, phase_draine, phase_fog, fog_parameters, mean_cosine_draine: the phase functions
  (section 4);
- cdf_draine, sample_hg, sample_draine, sample_fog: exact sampling of the phase functions (section 5).

``python media_reference.py`` prints the SREP's numeric-test table.
"""
from __future__ import annotations

import math
from typing import NamedTuple, Sequence

RGB = tuple[float, float, float]

# The reference engine clamps a transmissive surface's attenuation colour at this floor before taking its logarithm
# (crates/sr-gpu/src/pathtrace.rs:84, three.wgsl:583).
ATTENUATION_FLOOR = 1e-4
# Below this |g| the Henyey-Greenstein inversion is the isotropic one (SREP 79 rule 6).
HG_ISOTROPIC = 1e-3
# Below this |g| the Draine cumulative uses its g = 0 form; both forms agree to 1e-9 there.
DRAINE_ISOTROPIC = 1e-6
# Bisection steps of the Draine inversion: 2 / 2**64 is far below the 1e-12 the SREP asks.
BISECTION_STEPS = 64


class Coefficients(NamedTuple):
    """Per scene unit: scalar extinction, RGB scattering and RGB absorption."""

    sigma_t: float
    sigma_s: RGB
    sigma_a: RGB


class FogParameters(NamedTuple):
    """The four parameters of the HG + Draine fog phase function at one droplet diameter."""

    g_hg: float
    g_d: float
    alpha: float
    w_d: float


def _finite(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def _unit_interval(value: float, name: str) -> float:
    value = _finite(value, name)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must lie in [0, 1], got {value!r}")
    return value


def _rgb(value: Sequence[float], name: str, unit: bool = False) -> RGB:
    if len(value) != 3:
        raise ValueError(f"{name} must have three channels")
    out = tuple(_unit_interval(v, name) if unit else _finite(v, name) for v in value)
    if not unit and any(v < 0.0 for v in out):
        raise ValueError(f"{name} must be nonnegative")
    return out  # type: ignore[return-value]


def _cosine(mu: float) -> float:
    mu = _finite(mu, "cos theta")
    if not -1.0 <= mu <= 1.0:
        raise ValueError(f"cos theta must lie in [-1, 1], got {mu!r}")
    return mu


def _asymmetry(g: float) -> float:
    g = _finite(g, "g")
    if not -1.0 < g < 1.0:
        raise ValueError(f"g must lie in (-1, 1), got {g!r}")
    return g


def _alpha(alpha: float) -> float:
    alpha = _finite(alpha, "alpha")
    if alpha < 0.0:
        raise ValueError(f"alpha must be nonnegative, got {alpha!r}")
    return alpha


def _draw(xi: float, name: str = "xi") -> float:
    xi = _finite(xi, name)
    if not 0.0 <= xi < 1.0:
        raise ValueError(f"{name} must lie in [0, 1), got {xi!r}")
    return xi


# --- section 1 and 2: coefficients, emission, transmittance -----------------------------------------------------

def coefficients(density: float, density_scale: float, opacity: float, extinction: float,
                 albedo: Sequence[float]) -> Coefficients:
    """The coefficients at a point: rho = density * densityScale * opacity; sigma_t = rho * extinction;
    sigma_s = sigma_t * albedo and sigma_a = sigma_t * (1 - albedo) per channel."""
    density = _finite(density, "density")
    if density < 0.0:
        raise ValueError("density must be nonnegative")
    density_scale = _finite(density_scale, "densityScale")
    if density_scale < 0.0:
        raise ValueError("densityScale must be nonnegative")
    opacity = _unit_interval(opacity, "opacity")
    extinction = _finite(extinction, "extinction")
    if extinction < 0.0:
        raise ValueError("extinction must be nonnegative")
    a = _rgb(albedo, "albedo", unit=True)
    rho = density * density_scale * opacity
    sigma_t = rho * extinction
    sigma_s = (sigma_t * a[0], sigma_t * a[1], sigma_t * a[2])
    sigma_a = (sigma_t * (1.0 - a[0]), sigma_t * (1.0 - a[1]), sigma_t * (1.0 - a[2]))
    return Coefficients(sigma_t, sigma_s, sigma_a)


def combine(parts: Sequence[Coefficients]) -> Coefficients:
    """Overlapping media add their coefficients. Addition is commutative, so the order of the media is immaterial."""
    sigma_t = 0.0
    sigma_s = [0.0, 0.0, 0.0]
    sigma_a = [0.0, 0.0, 0.0]
    for part in parts:
        sigma_t += part.sigma_t
        for c in range(3):
            sigma_s[c] += part.sigma_s[c]
            sigma_a[c] += part.sigma_a[c]
    return Coefficients(sigma_t, (sigma_s[0], sigma_s[1], sigma_s[2]), (sigma_a[0], sigma_a[1], sigma_a[2]))


def emission(density: float, emission_scale: float, emission_color: Sequence[float],
             thermal: Sequence[float] = (0.0, 0.0, 0.0)) -> RGB:
    """Emitted radiance per scene unit: density * emissionScale * (emissionColor + thermal RGB). The thermal term
    is the blackbody colour of SREP 40 at the point's scaled temperature, or black without blackbody."""
    density = _finite(density, "density")
    if density < 0.0:
        raise ValueError("density must be nonnegative")
    scale = _finite(emission_scale, "emissionScale")
    if scale < 0.0:
        raise ValueError("emissionScale must be nonnegative")
    color = _rgb(emission_color, "emissionColor")
    therm = _rgb(thermal, "thermal")
    return tuple(density * scale * (color[c] + therm[c]) for c in range(3))  # type: ignore[return-value]


def transmittance(sigma: float | Sequence[float], length: float):
    """Beer-Lambert: exp(-sigma * length), per channel when sigma is RGB."""
    length = _finite(length, "length")
    if length < 0.0:
        raise ValueError("length must be nonnegative")
    if isinstance(sigma, (int, float)):
        s = _finite(sigma, "sigma")
        if s < 0.0:
            raise ValueError("sigma must be nonnegative")
        return math.exp(-s * length)
    s3 = _rgb(sigma, "sigma")
    return tuple(math.exp(-v * length) for v in s3)


def step_weight(sigma_t: float, ds: float) -> float:
    """The integral of the transmittance over one march step of length ds with constant extinction:
    (1 - exp(-sigma_t ds)) / sigma_t, and ds when sigma_t is 0 (SREP 79 rule 4)."""
    sigma_t = _finite(sigma_t, "sigma_t")
    ds = _finite(ds, "ds")
    if sigma_t < 0.0 or ds < 0.0:
        raise ValueError("sigma_t and ds must be nonnegative")
    if sigma_t == 0.0:
        return ds
    return -math.expm1(-sigma_t * ds) / sigma_t


# --- section 3: the interior of a transmissive surface as a medium --------------------------------------------

def surface_absorption(attenuation_color: Sequence[float], attenuation_distance: float) -> RGB:
    """The absorption coefficient per channel inside a transmissive surface: -ln(c) / d with c clamped to
    [ATTENUATION_FLOOR, 1]; zero without a finite positive distance, and zero for a white colour."""
    color = _rgb(attenuation_color, "attenuationColor")
    if not isinstance(attenuation_distance, (int, float)) or isinstance(attenuation_distance, bool):
        raise ValueError("attenuationDistance must be a number")
    d = float(attenuation_distance)
    if not (math.isfinite(d) and d > 0.0):
        return (0.0, 0.0, 0.0)
    out = []
    for c in color:
        c = min(max(c, ATTENUATION_FLOOR), 1.0)
        out.append(max(0.0, -math.log(c) / d))
    return (out[0], out[1], out[2])


# --- section 4: phase functions ---------------------------------------------------------------------------------

def phase_hg(mu: float, g: float) -> float:
    """Henyey-Greenstein: (1 - g^2) / (4 pi (1 + g^2 - 2 g mu)^(3/2)). mu is the cosine between the incoming and
    the outgoing propagation directions, so g > 0 peaks at mu = 1 (forward)."""
    mu, g = _cosine(mu), _asymmetry(g)
    denominator = 1.0 + g * g - 2.0 * g * mu
    return (1.0 - g * g) / (4.0 * math.pi * denominator ** 1.5)


def phase_rayleigh(mu: float) -> float:
    """Rayleigh: 3 (1 + mu^2) / (16 pi)."""
    mu = _cosine(mu)
    return 3.0 * (1.0 + mu * mu) / (16.0 * math.pi)


def phase_draine(mu: float, g: float, alpha: float) -> float:
    """Draine (2003, equation 5): (1 - g^2) / (4 pi (1 + alpha (1 + 2 g^2) / 3)) * (1 + alpha mu^2) /
    (1 + g^2 - 2 g mu)^(3/2). alpha = 0 is Henyey-Greenstein; g = 0, alpha = 1 is Rayleigh; alpha = 1 is
    Cornette-Shanks."""
    mu, g, alpha = _cosine(mu), _asymmetry(g), _alpha(alpha)
    denominator = 1.0 + g * g - 2.0 * g * mu
    norm = (1.0 - g * g) / (4.0 * math.pi * (1.0 + alpha * (1.0 + 2.0 * g * g) / 3.0))
    return norm * (1.0 + alpha * mu * mu) / denominator ** 1.5


def mean_cosine_draine(g: float, alpha: float) -> float:
    """The first moment of the Draine phase function (Draine 2003, equation A2)."""
    g, alpha = _asymmetry(g), _alpha(alpha)
    return g * (1.0 + alpha * (3.0 + 2.0 * g * g) / 5.0) / (1.0 + alpha * (1.0 + 2.0 * g * g) / 3.0)


def fog_parameters(diameter: float) -> FogParameters:
    """The HG + Draine fit of the Mie phase function of water droplets (Jendersie and d'Eon 2023, equations 4
    to 7) for a droplet diameter in micrometres, 5 <= d <= 50."""
    d = _finite(diameter, "dropletDiameter")
    if not 5.0 <= d <= 50.0:
        raise ValueError(f"dropletDiameter must lie in [5, 50] micrometres, got {d!r}")
    return FogParameters(
        g_hg=math.exp(-0.0990567 / (d - 1.67154)),
        g_d=math.exp(-2.20679 / (d + 3.91029) - 0.428934),
        alpha=math.exp(3.62489 - 8.29288 / (d + 5.52825)),
        w_d=math.exp(-0.599085 / (d - 0.641583) - 0.665888),
    )


def phase_fog(mu: float, diameter: float) -> float:
    """(1 - w_D) HG(g_HG) + w_D Draine(g_D, alpha) with the parameters of fog_parameters(diameter)."""
    p = fog_parameters(diameter)
    return (1.0 - p.w_d) * phase_hg(mu, p.g_hg) + p.w_d * phase_draine(mu, p.g_d, p.alpha)


# --- section 5: sampling --------------------------------------------------------------------------------------------

def cdf_draine(mu: float, g: float, alpha: float) -> float:
    """The cumulative of the Draine phase function in cos theta, from -1 to mu: the integral over the sphere of
    the directions with a cosine at most mu. In closed form (the antiderivative in t = 1 + g^2 - 2 g mu)."""
    mu, g, alpha = _cosine(mu), _asymmetry(g), _alpha(alpha)
    k = (1.0 - g * g) / (2.0 * (1.0 + alpha * (1.0 + 2.0 * g * g) / 3.0))
    if abs(g) < DRAINE_ISOTROPIC:
        return k * ((mu + 1.0) + alpha * (mu ** 3 + 1.0) / 3.0)
    a = 1.0 + g * g

    def antiderivative(t: float) -> float:
        root = math.sqrt(t)
        return -2.0 / root + alpha / (4.0 * g * g) * (-2.0 * a * a / root - 4.0 * a * root + (2.0 / 3.0) * t * root)

    t_low = a + 2.0 * g          # mu = -1
    t_mu = a - 2.0 * g * mu
    return k * (antiderivative(t_mu) - antiderivative(t_low)) / (-2.0 * g)


def sample_hg(xi: float, g: float) -> float:
    """cos theta of a Henyey-Greenstein direction from a unit draw, by the inversion of SREP 79 rule 6."""
    xi, g = _draw(xi), _asymmetry(g)
    if abs(g) < HG_ISOTROPIC:
        return 1.0 - 2.0 * xi
    s = (1.0 - g * g) / (1.0 - g + 2.0 * g * xi)
    return max(-1.0, min(1.0, (1.0 + g * g - s * s) / (2.0 * g)))


def sample_draine(xi: float, g: float, alpha: float) -> float:
    """cos theta of a Draine direction from a unit draw: the mu with cdf_draine(mu) = xi, found by BISECTION_STEPS
    halvings of [-1, 1]. A closed-form inversion exists (Jendersie and d'Eon 2023, supplemental section 2.2) and
    gives the same mu within the SREP's tolerance."""
    xi, g, alpha = _draw(xi), _asymmetry(g), _alpha(alpha)
    low, high = -1.0, 1.0
    for _ in range(BISECTION_STEPS):
        mid = 0.5 * (low + high)
        if cdf_draine(mid, g, alpha) < xi:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def sample_fog(xi_lobe: float, xi: float, diameter: float) -> float:
    """cos theta of a fog direction: the Draine lobe when xi_lobe < w_D, else the HG lobe, each sampled with the
    second draw (Jendersie and d'Eon 2023, supplemental section 2)."""
    xi_lobe = _draw(xi_lobe, "xi_lobe")
    p = fog_parameters(diameter)
    if xi_lobe < p.w_d:
        return sample_draine(xi, p.g_d, p.alpha)
    return sample_hg(xi, p.g_hg)


# --- the SREP's numeric-test table ----------------------------------------------------------------------------------

_SMOKE = "coefficients(density=0.5, density_scale=2.0, opacity=0.5, extinction=4.0, albedo=(1.0, 0.5, 0.0))"
_THIN = "coefficients(density=1.0, density_scale=1.0, opacity=1.0, extinction=2.0, albedo=(1.0, 0.0, 0.5))"
_THICK = "coefficients(density=0.5, density_scale=1.0, opacity=1.0, extinction=4.0, albedo=(0.0, 1.0, 0.5))"

TABLE: list[tuple[str, str]] = [
    ("extinction", f"{_SMOKE}.sigma_t"),
    ("scattering", f"{_SMOKE}.sigma_s"),
    ("absorption", f"{_SMOKE}.sigma_a"),
    ("overlap", f"combine([{_THIN}, {_THICK}]).sigma_s"),
    ("emission", "emission(density=2.0, emission_scale=3.0, emission_color=(1.0, 0.5, 0.0), thermal=(0.0, 0.5, 1.0))"),
    ("transmittance scalar", "transmittance(2.0, 0.5)"),
    ("transmittance rgb", "transmittance((1.0, 2.0, 3.0), 1.0)"),
    ("step weight", "step_weight(2.0, 0.5)"),
    ("step weight empty", "step_weight(0.0, 0.25)"),
    ("surface absorption", "surface_absorption((0.5, 0.25, 1.0), 2.0)"),
    ("surface absorption floor", "surface_absorption((0.0, 1e-5, 1.0), 1.0)"),
    ("surface absorption none", "surface_absorption((0.5, 0.25, 1.0), 0.0)"),
    ("hg forward", "phase_hg(1.0, 0.5)"),
    ("hg backward", "phase_hg(-0.3, -0.7)"),
    ("hg isotropic", "phase_hg(0.2, 0.0)"),
    ("rayleigh side", "phase_rayleigh(0.0)"),
    ("rayleigh forward", "phase_rayleigh(1.0)"),
    ("draine", "phase_draine(0.25, 0.5, 2.0)"),
    ("draine cornette-shanks", "phase_draine(0.0, 0.76, 1.0)"),
    ("draine rayleigh", "phase_draine(0.5, 0.0, 1.0)"),
    ("draine mean cosine", "mean_cosine_draine(0.7, 1.5)"),
    ("draine cdf", "cdf_draine(0.0, 0.7, 1.5)"),
    ("draine cdf isotropic", "cdf_draine(0.5, 0.0, 1.0)"),
    ("sample hg", "sample_hg(0.5, 0.5)"),
    ("sample hg isotropic", "sample_hg(0.25, 0.0)"),
    ("sample draine", "sample_draine(0.5, 0.7, 1.5)"),
    ("sample draine backward", "sample_draine(0.01, -0.6, 3.0)"),
    ("fog 5", "tuple(fog_parameters(5.0))"),
    ("fog 10", "tuple(fog_parameters(10.0))"),
    ("fog 50", "tuple(fog_parameters(50.0))"),
    ("fog forward", "phase_fog(1.0, 10.0)"),
    ("fog side", "phase_fog(0.0, 10.0)"),
    ("fog backward", "phase_fog(-1.0, 20.0)"),
    ("sample fog draine lobe", "sample_fog(0.1, 0.5, 10.0)"),
    ("sample fog hg lobe", "sample_fog(0.9, 0.5, 10.0)"),
]


def main() -> None:
    """Print the SREP's numeric-test table: one Markdown row per entry of TABLE."""
    scope = {name: value for name, value in globals().items() if not name.startswith("_")}
    scope["math"] = math
    scope["tuple"] = tuple
    print("| Test | Expression | Expected |")
    print("|---|---|---|")
    for name, expr in TABLE:
        value = eval(expr, {"__builtins__": {}}, scope)  # noqa: S307 - the expressions are this module's own
        print(f"| {name} | `{expr}` | `{value!r}` |")


if __name__ == "__main__":
    main()
