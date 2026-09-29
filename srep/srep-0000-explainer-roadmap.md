```
SREP:            0
Title:           Roadmap for science-explainer video
Author:          rs-scene-render maintainers
Status:          Draft
Type:            Informational
Created:         2026-09-29
Schema-Version:  n/a
Requires:        the 1.2 drafts for basemaps, 3D maps and 3D rigid bodies
```

# SREP 0 — Roadmap for science-explainer video

## Abstract

The format's goal is to produce almost any shot of a science-explainer video (Veritasium, PBS Space Time,
Kurzgesagt, 3Blue1Brown, minutephysics, Steve Mould, Real Engineering, Primer) from a document, with every
frame exact under seeking and every physical claim tested. This SREP measures the format against a catalogue
of 36 reference shots from those channels and against its usual peers (Lottie, Rive, SVG 2, Remotion, Motion
Canvas, HyperFrames, the JSON video APIs, MLT, OTIO, FCPXML, OpenUSD, glTF, OCIO, plus Manim, OpenSpace,
ParaView and ray-optics for the new families). It takes the specialist tools that lead each area as the
quality bar, fixes the design rules the work shares, and orders the Standards SREPs that close the gaps into
nine milestones by share of screen time and size of gap. It proposes no schema change itself.

## Motivation

Explainer videos are built from a small number of shot families. A survey of the channels above gives a rough
share of screen time for each (a judgement, not a measurement), and how well the format covers it today:

| Shot family | Share | Today |
|---|---|---|
| Live action and compositing | ≈22% | covered: keys, imported tracking, stabilisation |
| Flat motion graphics and typography | ≈16% | covered |
| Space and astronomy | ≈12% | gap |
| Math animation | ≈10% | partial: shapes, TeX, morphing |
| Scientific visualisation (fields, waves) | ≈10% | gap |
| 3D mechanics and physics | ≈9% | partial: 3D rigid bodies (1.2 draft) |
| Data, charts and maps | ≈8% | covered |
| Characters and creatures | ≈6% | partial: 2D rigs, skinned glTF |
| Optics | ≈3% | gap |
| Fluids, smoke and fire | ≈2% | gap in 3D |
| Landscapes, sky and weather | ≈2% | gap |

Of the 36 catalogue shots, an estimated 15 render natively today, 6 need custom work (shaders, hand-built
geometry) and 15 hit a gap. None of the peers declares the missing families: the motion-graphics formats and
JSON video APIs have none of them, the code frameworks reach them only through embedded three.js, Python or
scripts that the author must make deterministic by hand, and the interchange formats describe results
(volumes, rigid bodies, instances) without simulating anything. The specialist tools that do simulate or
render these subjects (Houdini, OpenSpace, ParaView, ray-optics) are not driven by a declarative document, do
not render to finished video under a single timeline, and are rarely validated. That is the opening.

## Specification

This section is the plan. It is informative: each item becomes normative only through its own Standards or
Semantics SREP.

### Against the formats and tools we compare with

The peers are those of the format's earlier comparison. N: declared natively. E: reachable only by embedding
external code (three.js, a shader, a physics library) or a pre-baked cache. P: partial. –: nothing. Status as of
September 2026.

| Peer | Terrain and its processes | Sky, fog, volumes, clouds | Water and weather | Cloth, smoke, liquids, fracture | Vegetation, scattering, growth | Map layers | Determinism |
|---|---|---|---|---|---|---|---|
| Lottie 1.0 | – | – | – | – | P (repeater) | – | keyframes only |
| Rive | – | E (Luau scripts) | E (Luau scripts) | P (constraints), E | P | – | author seeds scripts |
| SVG 2 with Filter Effects | P (feTurbulence, lighting) | P (2D noise) | – | – | P (`use`) | P (hillshade look) | seeded noise |
| Remotion | E (React Three Fiber) | E (three.js Sky, a Preetham model) | E (three.js Water) | E (Rapier, cannon) | E (instanced meshes) | E (deck.gl) | by convention: frame-driven, seeded `random` |
| Motion Canvas | – | – | – | – | P (loops) | – | seeded random |
| HyperFrames | E (three.js adapter) | E | E | E | E | E | seek contract, no unseeded randomness |
| Shotstack, Creatomate, JSON2Video | – | – | – | – | – | – | template render |
| Editly | E (GL layers) | E (GLSL) | E | E | E (canvas) | – | partial |
| MLT (frei0r) | – | P (plasma, noise) | – | – | – | – | yes |
| OTIO, FCPXML | – | P (FCPXML references FCP generators) | – | – | – | – | editorial only |
| OpenUSD | – (meshes) | P (DomeLight images), N (UsdVol OpenVDB assets as caches) | – | N rigid bodies (UsdPhysics schema, no solver); P deformables (proposal) | N (PointInstancer) | P (vendor schemas) | description only |
| glTF 2.0 | – | P (homogeneous absorption, image-based light) | – | P (rigid bodies at review draft) | N (EXT_mesh_gpu_instancing) | P (as 3D Tiles content) | description only |
| OpenColorIO | – | – | – | – | – | – | colour only |

Three things follow. No peer simulates any of these processes in the document: where they appear at all, the
author writes the simulation in embedded code, or imports a result baked elsewhere. Embedded simulations are
deterministic only if the author re-runs them from the start at a fixed step on every seek, which none of the
frameworks does for them. And the interchange formats (UsdVol, UsdPhysics, PointInstancer, glTF instancing and
3D Tiles) are the right way to exchange results, so the plan reads and writes them.

The criteria on which the format must beat every peer:

1. **Declared, not programmed.** Each capability is elements and attributes in the document, validated by the
   schema; no script is needed.
2. **Simulated on the timeline.** Processes run along the composition's time and seek exactly, by the rules
   below.
3. **Checked against physics.** Each capability passes reference solutions (analytic cases, published data,
   GDAL for relief), where the peers offer none.
4. **Interchange.** Volumes, instances, rigid bodies and 3D tiles are read from and written to OpenUSD and glTF
   forms, so results move to and from the peers' ecosystems.

### The new families against their own leaders

For the families the first comparison barely touches, the relevant peers are different tools:

| Tool | Math animation | Fields | Space | Optics and waves | Video pipeline |
|---|---|---|---|---|---|
| Manim (3b1b, CE) | N: axes, plots, grid transforms, TeX matching by keys | P: vector fields, streamlines | – | – | yes; updaters replay from the start |
| Motion Canvas | P: TeX by hand-split parts, code diffs | – | – | – | yes |
| ParaView, VisIt | – | N: streamlines, LIC, isosurfaces, volumes | – | – | weak animation and typography |
| OpenSpace | – | – | N: SPICE, catalogues, globes (MIT) | – | live planetarium shows |
| SpaceEngine | – | – | N: procedural universe | – | free licence forbids monetised video |
| ray-optics, Falstad, PhET | – | P | – | N: ray diagrams, ripple tanks | no video export |

### The measure: a benchmark catalogue

Progress is measured on a catalogue of 36 reference shots of 5 to 10 seconds from the channels above, kept in
the reference implementation's evidence harness. Each shot records its source video, the techniques it needs,
its status (native, custom, gap) and the milestone expected to make it native. A shot counts as native when
its probe scene renders under `--strict`, meets its pixel checks, and gives the same frame when seeked as when
played. The format leads when at least 90% of the catalogue is native.

### The quality bar: specialist tools

The peers set no bar for quality here, so each capability is measured against the specialist tools that lead
it. "Lead" means we aim past them on a named criterion; "parity" means matching their table stakes is enough.

| Capability | Leading tools (what they offer) | scene-render today | Target and criterion |
|---|---|---|---|
| Terrain generation | Gaea 2, World Machine, World Creator, Houdini heightfields (fBm, ridged, warped noise; terraces; masks for slope, altitude, curvature, flow) | procedural heightmap inside `<erosion>`, 2D only | **Parity** in primitives and masks; terrain as a 3D object and a 2D picture from one element |
| Erosion (hydraulic, thermal, geological) | Houdini Erode, Gaea Erosion2/Thermal2, World Machine with Uplift, Instant Terra | droplet erosion (Beyer 2015), baked | **Lead:** erosion that plays over the timeline and seeks exactly; stream-power relief solved in closed form (Tzathas et al. 2024), so any geological time is reached without stepping |
| Rivers, lakes, floods | World Machine water, UE5 spline water (static) | none | **Lead:** a well-balanced shallow-water solver (Kurganov and Petrova 2007) passing the analytic dam-break, lake-at-rest and parabolic-bowl tests; no competitor animates floods on terrain |
| Snow, avalanches, glaciers | Gaea Snow/Glacier, World Machine snowfall and drift (static) | snow particles in 2D | **Lead:** layered snow with drift, melt and avalanches (Cordonnier et al. 2018) that evolves over time |
| Lava | World Creator (per-biome, real time) | none | **Lead:** a Bingham flow with cooling that solidifies into the terrain (MAGFLOW-style), checked against the critical thickness on an incline |
| Wildfire | none of the terrain tools; FARSITE and BehavePlus in forestry | none | **Lead:** a Rothermel spread model checked against BehavePlus fuel models |
| Sky and atmosphere | UE5 Sky Atmosphere (Hillaire 2020), Unity HDRP, Terragen, Blender sky texture | HDR environment images only | **Parity plus:** one physical atmosphere shared by raster and path tracer; sun and moon placed by date, time and location (NREL SPA); checked against libRadtran data and the Hosek–Wilkie and Prague models |
| Fog and volumes | UE5 Heterogeneous Volumes and height fog, Houdini/Karma VDB, Blender Principled Volume | none | **Parity plus:** homogeneous, height and grid (OpenVDB/NanoVDB) media with blackbody emission; raster output converges to the path tracer |
| Clouds | Terragen (path-traced), UE5 and HDRP volumetric clouds (Schneider 2015 style) | none | **Parity:** layered procedural clouds driven by a weather map, path-traced for final frames |
| Ocean and water surfaces | Houdini and Blender ocean spectra, HDRP water, UE5 water | none | **Parity plus:** directional wave spectra (Horvath 2015) as pure functions of time, so every frame renders alone; spectrum statistics tested |
| Weather | no unified system anywhere | 2D rain and snow particles | **Lead:** one `weather` state driving clouds, fog, precipitation, wet and snowy surfaces, lightning and wind together |
| Cloth and soft bodies in 3D | Houdini Vellum (XPBD), Unreal Chaos, Blender cloth | 2D spring lattices only | **Parity plus:** Vertex Block Descent with a fixed iteration count; bit-exact seeking, which PhysX states it does not provide for cloth |
| Smoke and fire in 3D | Houdini Pyro, EmberGen, Blender Mantaflow | 2D grid smoke | **Parity plus:** deterministic sparse-grid solver feeding the volume renderer |
| Liquids | Houdini FLIP, Blender Mantaflow, Unreal Niagara Fluids | none | **Parity plus:** APIC/FLIP with deterministic transfers; the Martin and Moyce dam-break curve as acceptance test |
| Fracture and ragdolls | Houdini RBD, Unreal Chaos Destruction | 3D rigid bodies and joints (draft) | **Parity:** seeded Voronoi fracture with breakable glue; articulated ragdolls blended from animation |
| Vegetation | SpeedTree, Unreal PCG and foliage, Houdini scatter, Blender Geometry Nodes | none | **Parity plus:** seeded scattering over terrain masks, L-system and space-colonisation trees, analytic wind; ecosystems that grow along the timeline |
| Growth and pattern systems | Houdini (by hand), shader toys | slime mould, flocks | **Lead:** reaction–diffusion, Lenia and cellular automata, DLA and differential growth as first-class nodes, each tested against its known behaviour |
| Map relief layers | MapLibre GL 5.x (hillshade with 5 methods, color-relief), GDAL, QGIS | none of these layer types | **Lead:** results equal to `gdaldem` within 1 level, in any projection, including terrain on globes and bathymetry |
| Map data layers | deck.gl (heatmap, trips), Kepler.gl, GEOlayers 3 | points, lines, choropleths, animated styles | **Parity plus:** heatmap, fill-extrusion, icons and time-series layers, rendered deterministically |
| Wind and current fields | earth.nullschool, Windy | none | **Lead:** particle advection from GRIB2 data resolved into a pinned cache, reproducible frame by frame |
| Photogrammetric 3D cities | Google Earth Studio, Cesium | extruded footprints | **Parity** for open and self-hosted OGC 3D Tiles 1.1 only (see Licensing) |
| Math animation | Manim, Motion Canvas | shapes, TeX, morphing | **Lead:** formula morphs from TeX semantics, not hand-split strings; morphing free of artefacts; any frame computed alone, where Manim replays updaters |
| Fields | ParaView, VisIt, matplotlib, Mathematica | particles in force fields | **Lead:** correct algorithms (Jobard–Lefer, LIC, Wegert phase portraits) with film-quality typography and camera, tested against analytic fields |
| Space | OpenSpace, SpaceEngine, Celestia | none | **Lead:** mission-grade ephemerides pinned by digest, catalogue stars, physical atmospheres, and relativistic rendering in one deterministic document |
| Black holes and relativity | the DNGR renderer (James et al. 2015), SpaceEngine | none | **Parity plus:** Kerr geodesics with ray bundles, Doppler and redshift, checked against the photon sphere, shadow and ISCO |
| Optics and waves | ray-optics, LuxCore dispersion, Falstad | a path tracer, no diagrams | **Lead:** verified ray and wave optics (Snell, Fresnel, Airy, fringe spacing) that renders to film quality |
| Footage | After Effects, Nuke | chroma, luma and difference keys; imported point, planar, camera and face tracks | **Parity:** tracks, camera solves, masks and depth computed by resolve providers into pinned caches |
| Looks | After Effects (Kurzgesagt), Blender (Primer) | vector rendering, PBR | **Lead:** one scene rendered flat, hand-drawn, toon-shaded or photoreal |

What no leading tool offers, and every SREP below must keep: a render is a pure function of the document,
its pinned inputs and the frame time, and seeking to any frame gives exactly what playing up to it gives.

### Shared design rules

These rules extend the four rules of SREP 0 (neutral defaults, determinism, one space, engine-neutral
specification) to the work below. Each planned SREP states how it meets them.

1. **Time.** A simulation advances in fixed steps from its own start, owns its state, and reaches a later
   frame only by stepping. Engines may keep checkpoints; the specification fixes only the result. Where a
   process has a closed form in time (ocean spectra, analytic stream-power relief, wind), the frame is that
   closed form and no state is kept.
2. **Randomness.** Every random value is a function of `project/@seed`, the element's `seed`, and integer
   indices (cell, particle, step), through one counter-based generator that a Semantics SREP defines exactly.
   No generator carries hidden state across elements.
3. **Order independence.** Results must not depend on evaluation order. Specifications describe updates as
   functions of the previous step's state (gather form), and where contributions are summed they state an
   order or an exact (integer) accumulation.
4. **Units.** Lengths are scene pixels and physical quantities convert through `physics/@pixelsPerMeter`, as
   for existing physics. Terrain heights, water depths and snow depths are pixels in the element's space.
   Temperatures are kelvin; times are seconds.
5. **Agreement between engines.** Within one engine, output is bit-identical for the same inputs. Between
   engines, and between an engine's GPU and CPU paths, results are compared by the compatibility kit's
   geometric measurements and each SREP's stated tolerances, because floating-point simulations do not
   match bit for bit across implementations.
6. **Validation.** Each SREP names reference solutions with closed forms or published data (listed below)
   and turns them into conformance cases or engine tests.
7. **Pinned external data.** Data from services (elevation, imagery, weather grids, 3D tiles) is fetched by
   a resolve step into a cache whose digest is in the document, as for `<generated>` and `<tiles>`. A source
   whose terms forbid caching is not usable in a document.

### Shared building blocks

Four definitions are reused across the plan and get their own SREPs first:

- **Terrain grid.** One element holding a regular grid of layers over a rectangle: bedrock, loose material,
  water depth and flow, suspended sediment, lava depth and temperature, snow (by type), ice, fuel and burn
  state, hardness and wetness. The ground surface is the sum of the solid layers. Processes read and write
  layers; display turns them into a 3D surface (like `object3D primitive="map"` today) or a 2D picture (like
  `<erosion>` today).
- **Medium.** One description of participating media (absorption, scattering, emission, phase function) used
  by the atmosphere, fog, clouds, volumes, water and smoke, so the raster renderer and the path tracer agree.
- **Wind.** One wind field (a base vector, gusts and curl noise, animatable) read by particles, vegetation,
  clouds, water, snow drift and fire spread.
- **Resolve manifests.** Each external source declares its licence, required attribution, whether caching is
  allowed and any duration limits; renders fail when required attribution is suppressed.

### The planned SREPs

Each line is one Standards (or Semantics) SREP, in dependency order within its track. Algorithms are the
current recommendation; each SREP argues its own choice. Tracks can proceed in parallel once the shared
building blocks exist. The milestones under **Order of work** group them.

**Math and fields**

| # | SREP | Recommended method | Reference tests |
|---|---|---|---|
| MF1 | Coordinate systems and plots | axes, number and complex planes, polar and 3D axes; explicit, parametric, polar and implicit curves (marching squares); TeX tick labels | plotted points on the analytic curve within 0.5 px |
| MF2 | Space transforms | matrix, complex-function and nonlinear warps applied to any shape after adaptive subdivision | a linear map moves grid nodes exactly; conformal maps keep right angles |
| MF3 | Semantic TeX and robust morphing | tagged formula parts carried to glyphs; morph by part with remaps and glyph-outline fallback; arc-length resampling, start alignment, sub-path matching | tagged parts land on their targets; no self-intersections mid-morph |
| MF4 | Reactive values | attributes bound to value trackers and expressions, evaluated per frame without replay | any frame alone equals the played frame |
| MF5 | Fields and flow | one field element (analytic, grid, simulated; vector, scalar, complex); arrow glyphs; evenly spaced streamlines (Jobard and Lefer 1997); line integral convolution (Cabral and Leedom 1993); phase portraits (Wegert 2012); charge and current field lines | dipole lines r = C sin²θ; winding number of zeros and poles; streamline separation |
| MF6 | Scalar 3D | isosurfaces (marching cubes), transfer-function volumes through the media model | sphere area error falls as O(h²) |

**Space**

| # | SREP | Recommended method | Reference tests |
|---|---|---|---|
| SP1 | Time and frames | UTC and TDB, ICRF and body-fixed frames; JPL DE440 kernels pinned by digest; VSOP87 fallback | JPL Horizons positions within 1 km |
| SP2 | Star fields | Hipparcos and Yale BSC; magnitude to flux; B–V to temperature (Ballesteros 2012) to colour through CIE 1931; proper motion; constellations | Δm = 5 gives flux ratio 100; Sun colour at about 5,800 K |
| SP3 | Planets and the Sun | textures, clouds, night lights, rings, limb darkening; atmosphere from ground to orbit (A1) | terminator and limb positions against geometry |
| SP4 | Orbits and N-body | Kepler propagation; leapfrog, Wisdom–Holman and IAS15 (Rein and Spiegel 2015) integrators; trajectory ribbons | two-body closure 1e-12; bounded energy error; time reversibility |
| SP5 | Scale | double-precision floating origin, logarithmic depth, powers-of-ten camera, scale bars | no depth fighting across 10²⁰ in scale |
| SP6 | Relativity diagrams | Minkowski diagrams with boosts, light cones, Penrose diagrams, embedding and curvature grids, gravitational-wave strain | boost preserves the interval; Flamm's paraboloid z = 2√(r_s(r − r_s)) |
| SP7 | Relativistic rendering | Schwarzschild and Kerr geodesics with ray bundles (James et al. 2015); accretion disks with g⁴ beaming; relativistic camera (aberration, Doppler, searchlight) | photon sphere 1.5 r_s; shadow √27 M; ISCO 6M; weak-field deflection 4GM/(c²b) |
| SP8 | Deep sky | procedural galaxies (density-wave arms, Sérsic bulge, dust lanes), N-body mergers, nebulae with emission-line palettes, through A2 | galaxy profiles follow their exponential and Sérsic laws |

**Footage**

| # | SREP | Recommended method | Reference tests |
|---|---|---|---|
| LA1 | Computed tracking | point and planar tracks and camera solves made by resolve providers into pinned track caches | synthetic plates with known motion: error below 0.5 px |
| LA2 | Masks and depth | segmentation masks for rotoscoping and monocular depth as resolved assets | mask IoU against synthetic mattes |
| LA3 | Integration | 3D objects anchored in plates, shadow catchers, lens-distortion matching | a solved camera re-projects scene points onto their plate positions |

**Optics and waves**

| # | SREP | Recommended method | Reference tests |
|---|---|---|---|
| OW1 | Ray-optics diagrams | sequential and non-sequential 2D tracing through thin and thick lenses, mirrors, prisms, GRIN media; Snell and Fresnel; image construction | Snell; total internal reflection; lensmaker equation |
| OW2 | Spectral rendering | Sellmeier and Cauchy materials, hero-wavelength sampling in the path tracer | BK7 n = 1.5168 at 587.6 nm; prism deviation |
| OW3 | Polarisation and wave optics | Jones calculus; Huygens–Fresnel summation; Fraunhofer patterns by FFT; phase shown as hue | Malus's law; Airy first zero 1.22 λ/D; fringe spacing λL/d |
| OW4 | Wave simulations | 2D ripple tank (finite differences with absorbing boundaries), strings, Chladni plates from a plate eigen-solver (Ritz; Gander and Wanner 2012) | standing-wave nodes at nλ/2; CFL-stable steps |

**Characters, agents and looks**

| # | SREP | Recommended method | Reference tests |
|---|---|---|---|
| CL1 | Style layer | the same scene rendered flat, hand-drawn, toon-shaded with outlines, or photoreal | toon bands fall at their declared thresholds |
| CL2 | Stylised characters | blob characters with squash-and-stretch rigs and eyes, in 2D and 3D | volume preserved under squash and stretch |
| CL3 | Agent behaviours | declared rules (seek, eat, reproduce, pair off) on seeded agents, with charts bound to live counts | seeded populations reproduce exactly |

**Foundations**

| # | SREP | Content | Depends on |
|---|---|---|---|
| F1 | Deterministic random numbers | the counter-based generator and its keying, exactly | — |
| F2 | Terrain grid | the element, layers, units, generation (fBm, ridged, warp, terraces, from DEM or image), masks, 3D and 2D display, material splatting by slope, altitude, curvature and flow | F1 |
| F3 | Media | the medium description and phase functions (Henyey–Greenstein, Rayleigh, Draine mix) | — |
| F4 | Wind | the shared wind field | F1 |
| F5 | Resolve manifests and licence gating | licence and attribution metadata for every resolved source | — |

**Terrain processes**

| # | SREP | Recommended method | Reference tests |
|---|---|---|---|
| T1 | Erosion | hydraulic grid erosion (Mei et al. 2007; Šťava et al. 2008); thermal slope collapse by talus angle (Musgrave et al. 1989); stream-power relief in closed form (Tzathas et al. 2024) | mass conservation; maximum slope ≤ talus after convergence; stream-power steady-state scaling |
| T2 | Surface water | shallow-water equations, central-upwind and well-balanced (Kurganov and Petrova 2007; hydrostatic reconstruction, Audusse et al. 2004); rain and source terms | Ritter dam break; lake at rest; Thacker bowl; SWASHES cases |
| T3 | Snow and ice | layered snow with drift, melt and avalanches (Cordonnier et al. 2018); exposure after Fearing 2000; glaciers by the shallow-ice approximation | no snow above the repose angle; mass balance equals snowfall minus melt |
| T4 | Lava | Bingham cellular flow with temperature-dependent yield and viscosity, radiative cooling, solidification into bedrock (Vicari et al. 2007) | flow halts at h = τ/(ρ g sin θ) on an incline |
| T5 | Wildfire | Rothermel rate of spread with wind and slope factors on the grid (Rothermel 1972; Finney 1998) | BehavePlus rates for standard fuel models |

**Atmosphere and rendering**

| # | SREP | Recommended method | Reference tests |
|---|---|---|---|
| A1 | Sun, moon and sky | solar position by NREL SPA (Reda and Andreas 2004); atmosphere after Hillaire 2020 / Bruneton 2017 with multiple scattering; aerial perspective; height fog | SPA published example within 0.001°; transmittance against quadrature; sky radiance against Hosek–Wilkie, Prague and libRadtran data |
| A2 | Volumes | homogeneous, height and grid media from OpenVDB/NanoVDB assets and UsdVol volumes; blackbody emission; null-scattering transport for the path tracer (Miller et al. 2019); froxels and ray marching in raster | Beer–Lambert exact; white-furnace energy test; raster converges to path tracer |
| A3 | Clouds and night sky | layered procedural clouds with weather maps (Schneider and Vos 2015), Draine–HG phase (Jendersie and d'Eon 2023); stars, moon and airglow (Jensen et al. 2001) | phase functions normalise; coverage follows the weather map |
| A4 | Ocean and water surfaces | directional spectra JONSWAP, TMA, Pierson–Moskowitz, Phillips (Tessendorf 2001; Horvath 2015) as functions of time; foam from the displacement Jacobian; water medium; caustics in the path tracer; flow maps | wave-height variance equals the spectrum integral; Fresnel 0.020 at normal incidence; Snell's window 48.6° |
| A5 | Weather | one weather state for clouds, fog, rain and snow, wet and snowy surfaces (after Lagarde 2013), lightning (dielectric breakdown, Kim and Lin 2004) | wetness darkens albedo and lowers roughness monotonically; lightning is a function of its seed |

**3D simulation**

| # | SREP | Recommended method | Reference tests |
|---|---|---|---|
| S1 | Cloth and soft bodies | Vertex Block Descent (Chen et al. 2024) with stable neo-Hookean material (Smith et al. 2018) and offset contact (Chen et al. 2025); XPBD rods for rope and hair | hanging-sheet rest shape; no energy gain without forces; zero self-intersections in a twisting test |
| S2 | Smoke and fire | stable fluids with MacCormack advection and vorticity confinement, fuel–temperature combustion, on sparse grids, rendered through A2 | divergence below ε after projection; symmetric plume from a symmetric set-up |
| S3 | Liquids | APIC/FLIP (Jiang et al. 2015) with exact transfers; MLS-MPM for granular snow and sand (Hu et al. 2018); whitewater (Ihmsen et al. 2012); surface meshing | Martin and Moyce dam-break front within 10 %; volume drift below 1 % |
| S5 | Cutaways and exploded views | section planes with capped cuts, exploded assemblies, flow lines over 3D parts (MF5) | cut faces lie on the plane; exploded parts return exactly |
| S4 | Fracture and ragdolls | seeded Voronoi pre-fracture with breakable glue joints; articulated bodies with motors blending from animation; rigid bodies read from and written to UsdPhysics and glTF physics (KHR_physics_rigid_bodies, once ratified) | fragment volumes sum to the whole; no glue breaks below its threshold |

**Vegetation and growth**

| # | SREP | Recommended method | Reference tests |
|---|---|---|---|
| G1 | Scattering and vegetation | seeded Poisson-disk scattering over terrain masks (Bridson 2007), exchanged as USD PointInstancer and glTF EXT_mesh_gpu_instancing; trees by L-systems, space colonisation and Weber–Penn parameters; analytic wind sway; ecosystem growth with self-thinning (Deussen et al. 1998) | no two points closer than r; L-system string lengths (Fibonacci algae, 5ⁿ Koch) |
| G2 | Pattern systems | Gray–Scott reaction–diffusion (Pearson 1993), Lenia (Chan 2019), cellular automata, diffusion-limited aggregation, differential growth | Gray–Scott pattern classes; Life periods; DLA fractal dimension 1.71 ± 0.05; Orbium glider mass and speed |

**Maps**

| # | SREP | Recommended method | Reference tests |
|---|---|---|---|
| M1 | Relief layers | MapLibre `raster`, `hillshade` (standard, basic, combined, igor, multidirectional) and `color-relief`; contours by marching squares with tile stitching; bathymetry as signed elevation; terrain on globes | within 1 level of `gdaldem hillshade` and `color-relief`; contours within 0.5 px of `gdal_contour`; no seams across tiles, poles or the antimeridian |
| M2 | Data layers | MapLibre `heatmap`, `fill-extrusion`, symbol icons and sprites | MapLibre render-test fixtures for these layer types |
| M3 | Time-series layers | feature time and timeline-driven filters; trips (paths revealed by time) | a trip's head at time t is at its interpolated position |
| M4 | Vector-field layers | particle advection over U/V grids (after Agafonkin's webgl-wind), GRIB2 resolved into a pinned raster | particles in a solid-body field follow the analytic circle |
| M5 | 3D Tiles | OGC 3D Tiles 1.1 from open or self-hosted sets; tile choice by screen-space error from the camera alone | the CesiumGS 1.1 samples load; tile choice matches a reference list for fixed cameras |

### Order of work

Nine milestones, ordered by share of screen time times size of gap, then by dependency. Catalogue counts are
the estimated number of native shots once the milestone lands.

| Milestone | Content | Screen time | Native shots after |
|---|---|---|---|
| 0 Scoreboard | the catalogue in the evidence harness; F1 random numbers; F5 provenance and licence manifests | all | 15 of 36, measured |
| 1 Math and fields | MF1–MF5 | ≈20% | 22 |
| 2 Space | SP1–SP6; A1 sun, sky and atmosphere | ≈12% | 24 |
| 3 Light and volumes | F3 media; A2 volumes; A3 clouds; SP7 relativistic rendering; SP8 deep sky; MF6 | space and sims | 27 |
| 4 Footage | LA1–LA3 | ≈22% | 27 (existing shots without external trackers) |
| 5 Optics and waves | OW1–OW4 | ≈3%, signature shots | 29 |
| 6 Machines and matter | S5, S2, S3, S1, S4 | ≈11% | 33 |
| 7 Characters, agents and looks | CL1–CL3 | ≈6% | 36 |
| 8 Worlds | F2, F4, T1–T5, A4, A5, G1, G2, M1–M5 | ≈2%, plus maps | beyond the catalogue |

The map layers of milestone 8 (M1, M2) are small and may run in parallel with earlier milestones, since
maps are about 8% of screen time.

### Licensing constraints found

- Google Photorealistic 3D Tiles may not be cached or used offline and limit promotional videos to 30 s; Cesium
  ion content may not be stored for offline use. Neither fits rule 7, so M5 covers open and self-hosted
  tilesets only.
- Sentinel-2 cloudless mosaics after 2016 are CC BY-NC-SA 4.0; the 2016 mosaic is CC BY 4.0.
- Copernicus GLO-30, SRTM, GEBCO, NASA GIBS and NOAA GFS are usable with their stated credits.

- The Gaia DR3 archive states CC BY-NC 3.0 IGO (to confirm), so SP2 defaults to Hipparcos and the Yale Bright
  Star Catalogue.
- SpaceEngine's free licence forbids monetised video; it is a peer, not a dependency.
- REBOUND is GPL-3 (to confirm); SP4 implements the published integrators rather than linking it.

These are findings to confirm under F5, not legal advice.

## Rationale

- **One roadmap before many SREPs** lets implementers see the shared pieces (terrain grid, media, wind,
  random numbers) and the order, so no SREP defines its own version of them.
- **Two comparisons.** The format is positioned against the same peers as its earlier survey, because those
  are what authors choose between; none of them offers these capabilities natively. Quality, though, is
  measured against the specialist tools that lead each area, because the peers set no bar there. No single
  product covers all the shot families.
- **Order by screen time.** Milestones follow share of explainer screen time times size of gap. Math, fields and
  space are about a third of screen time and all open gaps; landscapes are about 2%.
- **A catalogue as the measure.** Progress is counted in reference shots made native, with seek consistency,
  so claims of coverage are evidence rather than estimates.
- **Algorithms were chosen** for being gather-form or closed-form in time (so they can be exact and seekable),
  having published reference solutions, and being current practice in production tools.

## Rejected alternatives

- **Environments first.** Terrain, water and weather were the first plan, but they fill about 2% of explainer
  screen time; they move to the last milestone.
- **One SREP for everything.** It would take years to reach Accepted and could not be reviewed in pieces.
- **Adopting an external engine's model wholesale** (for example Houdini's heightfield layers or Unreal's
  water). Their definitions are not public specifications and are not deterministic.
- **Particle droplet erosion as the main terrain method.** Its scattered deposits need exact accumulation to
  be order-independent, and it has no analytic test; it stays available as a detail pass.
- **Google and Cesium ion tiles through the resolve step.** Their terms forbid the cache the format requires.

## Backwards compatibility

None: this SREP changes nothing. Each planned SREP adds elements under a new minor version and keeps neutral
defaults.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | n/a | implements each planned SREP first | |
| C (`c-scene-render`) | n/a | per planned SREP | |
| Python (`py-render`) | n/a | per planned SREP | |
| JavaScript (`js-render-engine`) | n/a | per planned SREP | |

## Conformance

None for this SREP. Each planned SREP lists its cases.

## Open issues

- The exact counter-based generator for F1 (Philox or PCG variants) and whether it is specified in integer
  arithmetic only.
- Whether terrain processes share one grid resolution or may nest finer grids.
- How far the compatibility kit, which measures still frames geometrically, can test simulations; engine
  tests may need a shared reference-solution suite in sr-core.
- Citations marked for checking in the research notes: Houdini's slope-collapse node, Niagara's shallow-water
  status, the Tessendorf course-notes URL, BehavePlus reference numbers, the Prague model's dataset size and
  licence.

## References

Peers (as surveyed, September 2026):

- Lottie specification 1.0: https://lottie.github.io/lottie-spec/1.0/
- Rive scripting: https://rive.app/blog/scripting-is-live-in-rive
- Remotion and three.js: https://www.remotion.dev/docs/three
- HyperFrames: https://github.com/heygen-com/hyperframes
- Shotstack API: https://shotstack.io/docs/api/
- OpenUSD rigid body physics: https://openusd.org/release/wp_rigid_body_physics.html
- OpenUSD 26.03 (Gaussian splats in UsdVol): https://aousd.org/blog/openusd-v26-03/
- glTF extension registry: https://github.com/KhronosGroup/glTF/blob/main/extensions/README.md

Methods and specialist tools:

- Audusse, Bouchut, Bristeau, Klein, Perthame 2004, SIAM J. Sci. Comput. 25(6): hydrostatic reconstruction.
- Bridson 2007, "Fast Poisson Disk Sampling in Arbitrary Dimensions", SIGGRAPH sketch.
- Bruneton 2017, "A Qualitative and Quantitative Evaluation of 8 Clear Sky Models", IEEE TVCG;
  https://github.com/ebruneton/clear-sky-models
- Chan 2019, "Lenia: Biology of Artificial Life", Complex Systems 28(3).
- Chen, Liu, Yang, Yuksel 2024, "Vertex Block Descent", ACM TOG 43(4).
- Cordonnier, Braun, Cani, Benes, Galin, Peytavie, Guérin 2016, "Large Scale Terrain Generation from Tectonic
  Uplift and Fluvial Erosion", CGF 35(2).
- Cordonnier, Ecormier, Galin, Gain, Benes, Cani 2018, "Interactive Generation of Time-evolving, Snow-Covered
  Landscapes with Avalanches", CGF 37(2).
- Delestre et al. 2013, "SWASHES: a compilation of shallow water analytic solutions", IJNMF 72.
- Deussen et al. 1998, "Realistic Modeling and Rendering of Plant Ecosystems", SIGGRAPH.
- Fearing 2000, "Computer Modelling of Fallen Snow", SIGGRAPH.
- Finney 1998, FARSITE, USDA RMRS-RP-4.
- Hillaire 2020, "A Scalable and Production Ready Sky and Atmosphere Rendering Technique", CGF 39(4).
- Horvath 2015, "Empirical Directional Wave Spectra for Computer Graphics", DigiPro.
- Hu et al. 2018, "A Moving Least Squares Material Point Method", ACM TOG 37(4).
- Ihmsen et al. 2012, "Unified spray, foam and air bubbles for particle-based fluids", The Visual Computer.
- Jendersie and d'Eon 2023, "An Approximate Mie Scattering Function for Fog and Cloud Rendering".
- Jensen, Durand, Dorsey, Stark, Shirley, Premože 2001, "A Physically-Based Night Sky Model", SIGGRAPH.
- Jiang et al. 2015, "The Affine Particle-In-Cell Method", ACM TOG 34(4).
- Kim and Lin 2004, "Physically Based Animation and Rendering of Lightning", Pacific Graphics.
- Kurganov and Petrova 2007, "A second-order well-balanced positivity preserving central-upwind scheme for
  the Saint-Venant system", Commun. Math. Sci. 5(1).
- Lagarde 2012–2013, "Water drop" articles on wet surfaces.
- MapLibre style specification: https://maplibre.org/maplibre-style-spec/
- Mark 1992, multidirectional oblique-weighted hillshade, USGS Open-File Report 92-422.
- Martin and Moyce 1952, Phil. Trans. R. Soc. A 244: dam-break experiments.
- Mei, Decaudin, Hu 2007, "Fast Hydraulic Erosion Simulation and Visualization on GPU", Pacific Graphics.
- Miller, Georgiev, Jarosz 2019, "A Null-Scattering Path Integral Formulation of Light Transport", ACM TOG 38(4).
- Musgrave, Kolb, Mace 1989, "The Synthesis and Rendering of Eroded Fractal Terrains", SIGGRAPH.
- Museth 2021, "NanoVDB: A GPU-Friendly and Portable VDB Data Structure", SIGGRAPH talks.
- OGC 3D Tiles 1.1, OGC 22-025r4.
- Pearson 1993, "Complex Patterns in a Simple System", Science 261.
- Reda and Andreas 2004, "Solar Position Algorithm for Solar Radiation Applications", NREL.
- Rothermel 1972, USDA Research Paper INT-115.
- Schneider and Vos 2015, "The Real-time Volumetric Cloudscapes of Horizon Zero Dawn", SIGGRAPH courses.
- Šťava, Beneš, Brisbin, Křivánek 2008, "Interactive Terrain Modeling Using Hydraulic Erosion", SCA.
- Smith, de Goes, Kim 2018, "Stable Neo-Hookean Flesh Simulation", ACM TOG 37(2).
- Tessendorf 2001, "Simulating Ocean Water", SIGGRAPH course notes.
- Tzathas, Gailleton, Steer, Cordonnier 2024, "Physically-based analytical erosion for fast terrain
  generation", CGF 43(2).
- Vicari et al. 2007, MAGFLOW, Environmental Modelling & Software 22.
- Wilkie et al. 2021, "A fitted radiance and attenuation model for realistic atmospheres" (Prague sky model),
  ACM TOG 40(4).
- Ballesteros 2012, "New insights into black bodies", EPL 97, 34008 (B–V to temperature).
- Cabral and Leedom 1993, "Imaging Vector Fields Using Line Integral Convolution", SIGGRAPH.
- Gander and Wanner 2012, "From Euler, Ritz, and Galerkin to Modern Computing", SIAM Review 54(4).
- James, von Tunzelmann, Franklin, Thorne 2015, "Gravitational lensing by spinning black holes in astrophysics,
  and in the movie Interstellar", Class. Quantum Grav. 32, 065001.
- Jobard and Lefer 1997, "Creating Evenly-Spaced Streamlines of Arbitrary Density", Visualization in Scientific
  Computing.
- Rein and Spiegel 2015, "IAS15: a fast, adaptive, high-order integrator for gravitational dynamics", MNRAS 446.
- Wegert 2012, *Visual Complex Functions*, Birkhäuser.
- Manim: https://docs.manim.community/ ; OpenSpace: https://www.openspaceproject.com/ ;
  ray-optics: https://github.com/ricktu288/ray-optics ; ANISE: https://github.com/nyx-space/anise

## History

- 2026-09-29: first draft, as a roadmap for environments, simulation and geodata.
- 2026-09-29: broadened to science-explainer video: benchmark catalogue, math and fields, space, footage,
  optics and waves, characters and looks; milestones ordered by share of screen time.
