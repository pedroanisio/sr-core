# Changelog — sr-core

The version is `sr_core.__version__`; each release is tagged `vX.Y.Z`. It covers the commands, their options,
exit codes and outputs, and the URL layout of the generated schema reference. It does not cover Python
modules, which are internal; `sr_core.scene` is provisional until its SREP is accepted, and then becomes part of
this contract (that SREP amends SREP 4). The package format has its own version, `formatVersion`, which changes only
through an SREP and is listed here when it does. The schema has its own changelog, [schema/CHANGELOG.md](schema/CHANGELOG.md).

Record every change under **Unreleased** when it lands. `python3 tools/release.py next tools` computes the next
version:

| Class | Bump | For |
|---|---|---|
| Breaking, Removed | MAJOR | a command, option, exit code, output file or reference URL that scripts rely on changes or goes away; a new package-format MAJOR |
| Added, Deprecated | MINOR | new commands or options, new outputs, a new package-format MINOR |
| Changed, Fixed, Security, Docs | PATCH | everything else |

## Unreleased

### Breaking

### Added

- Draft SREP "Add time-series layers to the map" (`srep/srep-0000-time-series.md`, M3 of SREP 12): every timed
  element has a data time T = `timeOrigin` (seconds, or an ISO 8601 date-time read as seconds since 1970) plus its
  animatable `time`; `geoLayer` gains `timeBy`, `timeEndBy`, `trail` and `fade` (a feature is drawn from its time
  until its end or the trail's end, fading linearly; states visible/pending/expired/ended/unreadable); `route` over a
  geo asset gains `timeBy` per-vertex timestamps with deck.gl TripsLayer's trail 120 and fade (the window from
  T − trail to the head interpolated by time, per-point alpha 1 − (T − τ)/trail, round-capped strokes, the head dot
  by `headRadius`/`headFill`; states pending/running/complete/gone); `basemap` gains `timeOrigin`/`time` so
  `["global-state", "time"]` is T in style filters; rules TS1–TS4, warnings W-TS1/W-TS2, the version gate V19.
  Reference `conformance/tools/time_series_reference.py` (numpy; prints the draft's 31-row table),
  `tests/test_time_series.py` (35 tests). Engine card SR-114.
- Draft SREP "Add data layers to the map" (`srep/srep-0000-data-layers.md`, M2 of SREP 12): basemap styles draw the
  MapLibre `heatmap` layer (every feature vertex a Gaussian kernel centre per MapLibre's heatmap shaders, the quad
  cut-off 1/4080, a ramp over `heatmap-density` interpolated in straight RGBA then premultiplied), the
  `fill-extrusion` layer (roofs lit by the style's root `light` per MapLibre's fill_extrusion vertex shader on a 2D
  map; the features become SREP 10's `@buildings` prisms on a 3D map) and `symbol` icons from sprite sheets declared
  as `sprite` children of `basemap` (`name`, `index`, `image` assets; MapLibre's shapeIcon box times `icon-size`,
  `icon-offset` in icon pixels, rotation about the anchor, `icon-text-fit`, overlap modes never/always/cooperative,
  ignore-placement, the icon-optional/text-optional pairing with SREP 9's labels, SDF icons coloured by `icon-color`
  with a halo per the symbol_sdf shader, bilinear sampling) and `basemap/@icons`; rules DL1–DL7, warning W-DL1 and
  the version gate V18. Reference `conformance/tools/data_layers_reference.py` (numpy; prints the draft's 48-row
  table), `tests/test_data_layers.py` (51 tests). Engine card SR-113.
- Draft SREP "Add relief layers to the map" (`srep/srep-0000-relief.md`, M1 of SREP 12): basemap styles draw the
  MapLibre `raster` (opacity, hue rotation, brightness, saturation, contrast, resampling per MapLibre's raster
  shader), `hillshade` (standard from MapLibre's legacy formula; basic, combined, igor and multidirectional from
  gdaldem's formulas, GDAL MIT; exaggeration scales the slope, the viewport anchor turns the light with the map)
  and `color-relief` (interpolate or step stops over `["elevation"]`, gdaldem's lookup) layers that SREP 9 skipped,
  reading heights from `basemap/@elevation` with `@encoding` terrarium or mapbox; a `contours` child of `map` draws
  level lines by marching squares at pixel centres with the cell-mean saddle rule; every frame shades one mosaic of
  the visible tile set bordered by its neighbours (x modulo 2^z across the antimeridian, rows extrapolated beyond
  the poles) with the Horn gradient in metres per metre, so no seam appears; heights are signed (bathymetry); on a
  globe the layers join the SREP 10 drape from a whole-world mosaic. RL1–RL6, W-RL1, V17. Reference
  `conformance/tools/relief_reference.py` (numpy; 36-row table), `tests/test_relief.py` (77 tests; the gdaldem and
  gdal_contour comparisons skip without GDAL). Engine card SR-112.
- Draft SREP "Add pattern systems to the scene" (`srep/srep-0000-patterns.md`, G2 of SREP 12): five 2D pattern
  nodes beside `flock` and `slime`, each a box stepped at `rate` steps per second with `prewarm` and `maxSteps`
  so every frame renders alone: `reaction` (Gray–Scott, Pearson 1993, nine-point Laplacian on a torus, a classifier
  of spots, labyrinth and extinction), `lenia` (Chan 2019, ring kernel, Gaussian growth, the Orbium glider whose
  mass and speed the tests check), `automaton` (Life-like B/S rules, Golly RLE patterns, periods of the blinker and
  the glider), `aggregation` (diffusion-limited aggregation with lattice walkers whose steps are stream draws,
  radius-of-gyration dimension 1.71 ± 0.05) and `growth` (differential growth of a closed curve by insertion,
  repulsion and splitting, frozen at `maxNodes`); PT1–PT5, V17. Reference `conformance/tools/patterns_reference.py`
  (numpy) with its numeric table; `tests/test_patterns.py`. Engine card SR-111.
- Draft SREP "Add scattering and vegetation to the terrain grid" (`srep/srep-0000-vegetation.md`, G1 of
  SREP 12): `tree` prototypes of `terrain` grown by an L-system (3D turtle, stochastic rules from the streams,
  bounded `iterations` and `maxSymbols`), by space colonisation (Runions et al. 2007, stream-drawn attractors in a
  crown ellipsoid, Murray's-law radii) or by the parametric model of Weber and Penn 1995; `scatter` elements
  placing a prototype by Bridson's Poisson-disk sampling over a terrain `mask` with every draw from the streams,
  exported and imported as a USD PointInstancer or a glTF node with EXT_mesh_gpu_instancing; sway as a cantilever
  under crown drag in the wind-field draft's `wind` at each instance; one `ecosystem` from a scatter with
  logistic growth, death by age, offspring from maturity and the self-thinning of Deussen et al. 1998, replayed per
  frame; VG1–VG5, V17. Reference `conformance/tools/vegetation_reference.py` with its numeric table;
  `tests/test_vegetation.py`. Engine card SR-110.
- Draft SREP "Add wildfire to the terrain grid" (`srep/srep-0000-wildfire.md`, T5 of SREP 12): a `wildfire` child
  of `terrain` lights a surface fire at (`ignitionX`, `ignitionY`, `ignitionTime`) and spreads it by Rothermel's
  surface fire spread model (Rothermel 1972, Albini 1976, as Andrews 2018 lays it out) on one of the forty
  standard fuel models of Scott and Burgan 2005 (`fuelModel`, dynamic `curing`, five moistures), the midflame
  wind the wind-field draft's `wind` times `windAdjustment`, wind and slope combined as vectors into an effective
  wind, Anderson's length-to-breadth ellipse, the arrival time of every cell by minimum travel time over the
  eight neighbours (Finney 2002) with the wind read at departure; the terrain's `burn` layer is the burn fraction
  (crossing plus residence time), its `fuel` layer scales the loads and is consumed (zero is a firebreak), the
  flame length Byram's; WF1–WF5, V17. Reference `conformance/tools/wildfire_reference.py` with its numeric
  table (Rothermel's table 17, BehavePlus's GR2 and SH8 curves); `tests/test_wildfire.py`. Engine card SR-109.
- Draft SREP "Add lava to the terrain grid" (`srep/srep-0000-lava.md`, T4 of SREP 12): a `lavaFlow` child of
  `terrain` erupts lava from a vent (`ventX`, `ventY`, an animatable `effusion` varied through the random streams
  at purpose 2³¹ + 2¹⁷) into the terrain's `lava` layer and moves it over the surface as a Bingham fluid in a
  cellular automaton after MAGFLOW (Vicari et al. 2007): Dragoni's steady flux between the eight neighbours by
  the surface slope, zero under the critical thickness τ / (ρ g sin θ) and never past the plug, mixing by volume,
  Stefan–Boltzmann cooling through the lava's or the `crust`'s thermal mass, solidification into `bedrock` below
  the `solidus`; log-linear `viscosity` and `yieldStrength` in the temperature; the terrain's `temperature` layer
  as the surface temperature; LV1–LV4, V17. Reference `conformance/tools/lava_reference.py` with its numeric
  table; `tests/test_lava.py`. Engine card SR-108.
- Draft SREP "Add a weather state" (`srep/srep-0000-weather.md`, A5 of SREP 12): `weather` elements of `physics`
  beside `wind`, holding one animatable state (`temperature`, `humidity`, `precipitation`, `cloudiness`,
  `visibility`, `lightning`) and a `wind`, that drives the elements naming it instead of their own attributes:
  `cloudLayer` (coverage, precipitation), `snowpack` (snowfall, temperature), `shallowWater` and hydraulic `erode`
  (rain), rain and snow `emitter`s (rate from the Marshall–Palmer and Gunn–Marshall fluxes), `medium` (the
  Koschmieder extinction of the visibility) and `material`s (wetness darkens the dielectric albedo by the water
  film's geometric series after Lekner and Dorf and lowers the roughness toward the film's; snow cover toward
  0.85 / 0.7 on upward faces); rain and snow split by the temperature (Auer); wetness and snow depth by a stepped
  recurrence (`wetTime`, `dryTime`, `snowScale`, `meltRate`, `step`, `maxSteps`); lightning as a Poisson process by
  the time-change of the integrated rate with random-stream draws, each bolt a dielectric-breakdown channel on a
  `lightningGrid` (`lightningEta`, `maxStrikes`, `flashDuration`); rules WX1–WX4 and V17 inside the draft, the
  schema files unchanged. The clouds draft's map attribute is renamed `weatherMap`. Reference
  `conformance/tools/weather_reference.py` (34-row numeric table), `tests/test_weather.py`. Engine card SR-107.
- Draft SREP "Add snow and ice to the terrain grid" (`srep/srep-0000-snow.md`, T3 of SREP 12): one `snowpack`
  child of the terrain-grid draft's `terrain` acting on a snow `layer`, the `water` layer and the `ice` layer:
  `snowfall` varied by `snowfallVariation` through the random-streams draft at pack(i, j, 0) with the purpose
  2³¹ + 2¹⁶, degree-day melt (`meltRate`, `temperature` or the `temperature` layer, `density` into `water`),
  drift by the wind-field draft's `wind` (the cubic saltation law with `driftRate` and `driftThreshold`, the
  exposure of Fearing 2000 with `exposureGain`, snow leaving the grid reported), avalanches by the erosion draft's
  thermal step at `repose` with `avalancheRate`, and glaciers by the shallow-ice approximation (`iceFlow`,
  `iceTimeScale`, adaptive explicit substeps bounded at 1000 per step, volume conserved, ice non-negative);
  `step`, `maxSteps`; rules SN1–SN5 and V17 inside the draft, the schema files unchanged. Reference
  `conformance/tools/snow_reference.py` (31-row numeric table), `tests/test_snow.py`. Engine card SR-106.
- Draft SREP "Add shallow-water flow to the terrain grid" (`srep/srep-0000-surface-water.md`, T2 of SREP 12):
  one `shallowWater` child of the terrain-grid draft's `terrain` integrating the shallow-water equations on the
  terrain's grid (the bed from the solid layers, `water` the depth, `flow` the discharge) with the central-upwind
  flux of Kurganov and Petrova on the hydrostatic reconstruction of Audusse et al., `order` 1 or 2 (minmod and
  Heun), well-balanced with dry islands and positivity preserving, semi-implicit `manning` friction, `rain` and
  `source` children (`x`, `y`, `radius`, `rate`, `start`, `end`), a fixed `step` subdivided by `cfl`,
  `dryTolerance`, `boundary` open or closed, `maxSteps`; rules SW1–SW5 and V17 inside the draft, the schema files
  unchanged. Reference `conformance/tools/surface_water_reference.py` (28-row numeric table; Ritter dam break,
  Thacker bowl and the SWASHES bump implemented from the papers), `tests/test_surface_water.py`. Engine card
  SR-105.
- Draft SREP "Add erosion processes to the terrain grid" (`srep/srep-0000-erosion.md`, T1 of SREP 12):
  `erode` children of the terrain-grid draft's `terrain` with `kind` one of `fluvial` (the linear stream power
  law with `uplift`, `erodibility`, `m` solved in closed form along the D8 flow paths by travel time, at the
  geological time `time` + `timeScale` · t, so every frame renders alone), `thermal` (Musgrave talus relaxation
  of a solid `layer` at `talus` and `rate`, mass conserved) and `hydraulic` (the virtual pipes of Mei et al. on
  the `water`, `sediment`, `flow` and `loose` layers: `rain` varied by `rainVariation` through the random-streams
  draft at pack(i, j, 0), fluxes bounded by the Torricelli discharge, `pipeArea`, `capacity` with `minTilt` and
  Šťava's `maxDepth` limiter, `erodeRate` into `loose` then `bedrock` scaled by 1 − `hardness`, `depositRate`,
  sediment carried by the fluxes, `evaporation`, `boundary` open or closed), stepped processes replayed at `step`
  under `maxSteps`; rules ER1–ER5 and V17 inside the draft, the schema files unchanged. Reference
  `conformance/tools/erosion_reference.py` (28-row numeric table), `tests/test_erosion.py`. Engine card SR-104.
- Draft SREP "Add spectral seas, caustics and flow maps to the ocean" (`srep/srep-0000-ocean.md`, A4 of
  SREP 12): one `sea` child of `ocean`, a statistical wave field over SREP 40's solver with `model` one of
  `phillips`, `piersonMoskowitz`, `jonswap`, `tma` (`windSpeed`, `windDirection`, `fetch`, `gamma`, `spread`,
  `cutoff`), the Longuet-Higgins spreading, a periodic grid (`size`, `resolution`) whose initial amplitudes are
  the random-streams draft's normal draw on channels 1 and 2 at pack(i, j, 0), the Hermitian closed form in
  time (Tessendorf), `choppiness` displacement, slopes, normal, the Jacobian and foam (`foamThreshold`,
  `foamDecay`) feeding SREP 79's albedo; the ocean's `absorption` (Pope and Fry), `scattering`, `ior`, exact
  Fresnel (0.020 at normal incidence, Snell's window 48.6°), `caustics` and `flowMap` with `flowSpeed` and
  `flowCycle` (Vlachos). The variance equals the spectrum integral and the significant wave height is 4 √m₀.
  Rules OC1–OC6 and V17; the schema files are unchanged. Reference `conformance/tools/ocean_reference.py` with
  a 43-row numeric table; `tests/test_ocean.py`. Engine card SR-103.
- Draft SREP "Add cloud layers and the night sky" (`srep/srep-0000-clouds.md`, A3 of SREP 12): `cloudLayer`
  children of a dome light with `sky="physical"`, spherical shells between `base` and `base` + `thickness`
  whose shape is the random-streams value noise dilated by Worley billows, a height gradient blended from the
  stratus, stratocumulus and cumulus presets by `type`, a coverage threshold calibrated so that the covered
  fraction equals `coverage` (or the `weatherMap`'s red channel, with precipitation in green and type in blue),
  a Worley `detail` erosion and a drift by an F4 `wind`; lighting by Beer's law with the powder term, the media
  draft's `fog` phase for `dropletDiameter` and three multiple-scattering octaves; and the night sky's moon
  (Jensen's Lommel-Seeliger irradiance with `earthshine`, the moon's tint and the Hapke-Lommel-Seeliger disc),
  `airglow` with the van Rhijn factor and `starlight` plus the galactic background, in the sun's units. Rules
  CN1–CN6 and V17; reference `conformance/tools/clouds_reference.py` with a 37-row numeric table;
  `tests/test_clouds.py`. The schema files are unchanged. Engine card SR-102.
- Draft SREP "Define the random streams derived from the D24 hash" (`srep/srep-0000-random-streams.md`, F1 of
  SREP 12), recorded here with its first amendment: the unit and normal draws, permutations, the packing of 2D
  and 3D lattice indices, value and gradient noise, the octave sum, 3D Perlin noise, the element seed as the
  CRC-32 of `project:id:seed:purpose` (the seed text is the attribute's schema default when the schema declares
  one, `particles3D/@seed` reads `0` when absent) and the stream draws S, S_signed and S_normal addressed by
  element seed, purpose, step and index, under the 1.8 gate; open issues for the legacy seeds of agents, program
  nodes and clay and for the ejecta purposes 41 and 42. Reference `conformance/tools/random_streams_reference.py`;
  `tests/test_random_streams.py`. Engine card SR-61.
- Draft SREP "Add the wind field" (`srep/srep-0000-wind.md`, F4 of SREP 12): a `wind` element under
  `physics`, a velocity field in m/s over the physics space with a mean (`speed`, `direction`, `speedZ`), a
  stochastic gust factor (`gustiness`, `gustPeriod`, `gustOctaves`: an octave sum of the random-streams
  draft's value noise over time), declared `gust` children (`at`, `duration`, `peak`, `shape` one of `cosine`,
  `iec`) and a curl-noise `turbulence` (`turbulenceScale`, `turbulenceOctaves`, `turbulenceTime`): the analytic
  curl of a vector potential of three D24 value-noise fields on pack(i, j, k), divergence-free, carried by the
  mean wind (Taylor's frozen turbulence) and sliding in time; particles and bodies listing the wind in
  `forceFields` relax toward it with a `response` time; later milestone 8 SREPs sample it directly; the 1.7
  `forceField type="wind"` is unchanged. Rules WD1–WD5 and V17; the schema files are unchanged, the diff is
  inside the draft. Reference module `conformance/tools/wind_reference.py` with a 33-row numeric table and
  `tests/test_wind.py`. Engine card SR-101.
- Draft SREP "Add the terrain grid" (`srep/srep-0000-terrain-grid.md`, F2 of SREP 12): a `terrain` element
  holding a regular grid of named layers with units over a rectangle (`cells` along the longer side,
  `metersPerCell`; `bedrock`, `loose`, `lava`, `ice`, `snow` by type solid in metres; `water`, `sediment`,
  `flow`, `temperature`, `fuel`, `burn`, `hardness`, `wetness`), the ground surface the sum of the solid
  layers; layers by a flat `value`, a `generate` child (`fbm`, `ridged` or `billow` value noise on the D24
  lattice of the random-streams draft with `octaves`, `frequency`, `lacunarity`, `gain`, a domain `warp`,
  `terraces` and `amplitude`/`offset`) or an asset (`from` with `gray`, `gray16`, `terrarium` or `mapbox`
  `encoding`); `mask` children by `slope`, `altitude`, `curvature` or D8 `flow` with `min`, `max`, `feather`,
  `invert` and `material` splatting over the altitude ramp; the 2D `picture` hill-shaded as the baseline's
  `erosion`, the 3D surface as `object3D primitive="terrain"` (SREP 70's heightfield over the physical
  extent); one grid resolution per element (the SREP 12 open issue, decided); layers pinned by a `sha256`
  digest; reference module `conformance/tools/terrain_grid_reference.py`, `tests/test_terrain_grid.py` (its
  numeric table checked row by row); the schema files are unchanged, the diff (TG1-TG6, V17) is inside the
  draft; engine card SR-100.
- Draft SREP "Add plate integration" (`srep/srep-0000-plate-integration.md`, LA3 of SREP 12): `camera` gains
  `track` (a camera `trackData` that drives it) and `trackScale` (scene units per track unit, default
  `pixelsPerMeter`), the row held at the frame written into the engine's conventions (y down, z forward,
  yaw-pitch-roll about y, x, z, horizontal `fov`); `object3D` gains `anchor` and `anchorName` (a planar
  track whose pose, carried through the tracked camera, places the object, so a `shadowCatcher` there
  darkens the plate by SREP 41's rule); the camera `solve` gains `lens="plumb"`, the plumb-line estimate of
  the engine's radial `k1` (`three_post.wgsl`) written into the track cache and taken by a tracked camera
  without `lensDistortion`; a solved camera re-projects the target onto its plate positions within 0.5 px
  (0.327 px measured; 0 px after undistortion of `k1 = 0.15`, 0.696 px without); reference module
  `conformance/tools/plate_integration_reference.py`, `tests/test_plate_integration.py` (its numeric table
  checked row by row); the schema files are unchanged, the diff (PI1-PI4, V17) is inside the draft; engine
  card SR-99.
- Draft SREP "Add computed masks and depth" (`srep/srep-0000-computed-masks.md`, LA2 of SREP 12):
  `imageSequence` gains `provider="masks"` with a `segment` child or `provider="depth"` with an `estimate`
  child, and a resolve step (SREP 9's pattern) writes one 16-bit PGM per frame under the `src` pattern plus a
  manifest of every frame's digest, pinned by the asset's `sha256`; mattes by the engine's `chroma` and
  `difference` key formulas, by `region` growing from `seeds` with a linear colour model on the boundary that
  follows the object, and by keyed `roto` polygons, with `expansion` and `feather` as on `maskType`; depth
  from the `plane` of a tracked target through a solved camera and from `stereo` block matching with
  Lucas-Kanade refinement and a left-right consistency check; synthetic mattes measured at an intersection
  over union of at least 0.95 per frame and the stereo depth within 2 %; frames read a static cache
  (SREP 14); reference module `conformance/tools/computed_masks_reference.py`, `tests/test_computed_masks.py`
  (its numeric table checked row by row); the schema files are unchanged, the diff (MD1-MD4, V17) is inside
  the draft; engine card SR-98.
- Draft SREP "Add computed tracking" (`srep/srep-0000-computed-tracking.md`, LA1 of SREP 12): `trackData`
  gains `provider="tracks"` with one `solve` child, and a resolve step (SREP 9's pattern) writes the track
  cache at `src` in the engine's JSON format, pinned by `sha256`, with sorted keys and four decimals so the
  bytes are reproducible; `point` solves by normalised cross-correlation search and Lucas-Kanade refinement
  with a confidence and a lost state; `planar` solves by a grid of tracked points and a homography from the
  normalised DLT under RANSAC on the document's stream (SREP 92); `camera` solves from a planar target of
  known size (Zhang) or survey points (DLT PnP), refined by Gauss-Newton on the re-projection error, as the
  engine's camera row; synthetic plates with known motion measured below 0.5 px; frames read a static cache
  (SREP 14); reference module `conformance/tools/computed_tracking_reference.py`,
  `tests/test_computed_tracking.py` (its numeric table checked row by row); the schema files are unchanged,
  the diff (CT1-CT4, V17) is inside the draft; engine card SR-97.
- Draft SREP "Add wave simulations" (`srep/srep-0000-wave-sim.md`, OW4 of SREP 12): a `rippleTank` 2D node
  stepping the scalar wave equation by finite differences (leapfrog) with a document-stated Courant number
  checked against the CFL bound, point and line `source`s (continuous or pulsed), `wall`s with `slit`s,
  `speedRegion`s and `absorbing` (sponge), `reflecting` or `periodic` boundaries, with the conserved discrete
  energy and `hits` drawn from the pattern with the document's stream (SREP 92, channel HITS); a `string`
  node with fixed or free ends, plucked, struck or driven, damped, with the closed-form modes n c/2L and nodes
  at n lambda/2; a `chladniPlate` node with the simply supported closed form and the free square plate by
  Ritz's method with free-free beam functions (Gander and Wanner 2012), split by symmetry, with sand walking
  to the nodal lines; frames as pure functions of the frame (SREP 14); reference module
  `conformance/tools/wave_sim_reference.py`, `tests/test_wave_sim.py` (its numeric table checked row by row);
  the schema files are unchanged, the diff (WS1-WS4, V17) is inside the draft; engine card SR-96.
- Draft SREP "Add polarisation and wave optics" (`srep/srep-0000-wave-optics.md`, OW3 of SREP 12): Jones
  vectors on the ray-optics bench's sources (`polarisation` linear, circular, elliptical or none) with
  `polariser`, `waveplate`, `rotator` (an angle or Biot's law for a sugar column) and `detector` (Stokes
  parameters) elements; a `diffraction` 2D node for `slit`, `doubleSlit`, `circular`, `grating` and `mask`
  apertures with the closed forms (sinc², cos² sinc², Airy, grating), a radix-2 FFT of the aperture function,
  Huygens-Fresnel summation for the near field and phase shown as hue; reference module
  `conformance/tools/wave_optics_reference.py`, `tests/test_wave_optics.py` (its numeric table checked row by
  row); the schema files are unchanged, the diff (WO1-WO4, V17) is inside the draft; engine card SR-95.
- Draft SREP "Add spectral rendering" (`srep/srep-0000-spectral.md`, OW2 of SREP 12): `dispersionModel`
  attributes (`cauchy`, `sellmeier`, named `glass` from a table with cited coefficients: BK7, SF10, SF11, fused
  silica, water, diamond) on materials and on the ray-optics bench's elements, with the raster `dispersion`
  derived through the Abbe number as KHR_materials_dispersion defines; a `spectral` path-tracer mode with
  hero-wavelength sampling from SREP 92's path stream, CIE 1931 matching functions (Wyman fit), D65 and the
  sRGB matrices; blackbody `temperature` and tabulated `spectrum` emitters; the Jakob-Hanika sigmoid uplift of
  RGB colours; `wavelength` on bench sources; reference module `conformance/tools/spectral_reference.py`,
  `tests/test_spectral.py` (its numeric table checked row by row); the schema files are unchanged, the diff
  (SD1-SD4, V17) is inside the draft; engine card SR-94.
- Draft SREP "Add ray-optics diagrams" (`srep/srep-0000-ray-optics.md`, OW1 of SREP 12): an `opticalBench`
  2D node with `source`s (point fans, parallel beams), thin and thick `lens`es, flat and spherical `mirror`s,
  `prism`s, refracting `block`s, parabolic `grin` slabs, `screen`s and an `object` that draws a thin lens's
  image construction; rays traced non-sequentially or sequentially by Snell's law, total internal reflection
  and an optional Fresnel split, with a bounce bound and a power floor owned by the document; reference module
  `conformance/tools/ray_optics_reference.py`, `tests/test_ray_optics.py` (its numeric table checked row by
  row); the schema files are unchanged, the diff (RO1-RO4, V17) is inside the draft; engine card SR-93.
- Draft SREP "Add relativity diagrams" (`srep/srep-0000-relativity.md`, SP6 of SREP 12): a `spacetime`
  child of the plots draft's `axes` (Minkowski diagrams in units of c with a `boost` keyed in rapidity, the
  boosted frame's grid, `event`s with light cones, inertial, accelerated and parametric `worldline`s,
  `lightRay`s, and `compact` modes for the Penrose diamond and the Kruskal–Szekeres Penrose diagram of a
  `blackHole`), an `embedding` primitive of `object3D` (Flamm's paraboloid or the potential sheet as rings and
  spokes) and a `strain` modifier (plus and cross polarisations at a frequency or along the chirp of a chirp
  mass); reference module `conformance/tools/relativity_reference.py`, `tests/test_relativity.py` (its numeric
  table checked row by row); the schema files are unchanged, the diff (RD1-RD4, V17) is inside the draft;
  engine card SR-92.
- Draft SREP "Add scale: powers of ten, depth resolution and a floating origin" (`srep/srep-0000-scale.md`,
  SP5 of SREP 12): a `depth` attribute on `camera` (`reversed`, the engine's mapping, or `logarithmic`) with a
  resolution requirement the kit can measure (one part in 10⁵ at every decade up to a `far` / `near` ratio of
  1e20, SC1), a `geometric` key interpolation for the powers of ten camera, a `scaleBar` child of `camera`
  (1-2-5 bars in m, au, ly or pc at the measured depth) and a floating origin stated as an engine error bound
  (binary64 rebasing about the eye, one space per SREP 14); reference module
  `conformance/tools/scale_reference.py`, `tests/test_scale.py` (its numeric table checked row by row); the
  schema files are unchanged, the diff (SC1-SC4, V17) is inside the draft; engine card SR-91.
- Draft SREP "Add orbits and N-body motion" (`srep/srep-0000-orbits.md`, SP4 of SREP 12): an `orbit` child of
  `object3D` (classical elements about a central object, propagated by universal variables with two-body closure
  to 1e-12), an `nbody` child of `space` (members and Plummer clusters drawn from the random streams, integrators
  `leapfrog`, `wisdomHolman` in Jacobi coordinates and `ias15` with computed Gauss-Radau nodes, a fixed step that
  divides the frame interval or an adaptive IAS15 step under `tolerance`) and a `trail` ribbon; bounded energy
  error and time reversibility as reference tests; reference module `conformance/tools/orbits_reference.py`,
  `tests/test_orbits.py` (its numeric table checked row by row); the schema files are unchanged, the diff
  (OR1-OR5, V17) is inside the draft; engine card SR-90.
- Draft SREP "Add planets and the Sun as bodies" (`srep/srep-0000-planets.md`, SP3 of SREP 12): a
  `primitive="planet"` for `object3D`, an oblate spheroid of the IAU 2009 radii of its `body` under
  `pixelsPerMeter`, with the day texture and night lights read as equirectangular maps centred on the prime
  meridian (`nightLights`, `twilight`), a cloud shell with its shadow (`cloudMap`, `cloudHeight`, `cloudRotation`,
  `cloudShadow`), rings shadowing and shadowed by the planet (`ringMap`, `ringInner`, `ringOuter`), the
  Hestroffer-Magnan limb darkening of the Sun (`limbDarkening="solar"`) and the physical-sky atmosphere as a shell
  (`atmosphere`, `atmosphereHeight`); limb, terminator, cusps and phase in closed form; reference module
  `conformance/tools/planets_reference.py`, `tests/test_planets.py` (its numeric table checked row by row); the
  schema files are unchanged, the diff (PL1-PL5, V17) is inside the draft; engine card SR-89.
- Draft SREP "Add star fields from the Bright Star Catalogue" (`srep/srep-0000-star-fields.md`, SP2 of SREP 12):
  a `catalogue` asset (a gzipped nine-column CSV pinned by sha256) and a `starField` child of the dome light
  (`limitMagnitude`, `magnitudeZero`, `pointSize`, `properMotion`, `epoch`, `constellations`); flux by the
  magnitude scale, colour by Ballesteros' temperature through the CIE 1931 observer into linear sRGB, proper
  motion from J2000 to the frame's epoch (the `space` clock when present), constellations by Roman's table with
  Herget's precession; reference module `conformance/tools/star_fields_reference.py` (it also rebuilds the
  fixture), fixture `conformance/assets/bsc5-compact.csv.gz` (9,096 stars, 198 KB), `tests/test_star_fields.py`
- Draft SREP "Add time scales, celestial frames and JPL ephemerides" (`srep/srep-0000-time-frames.md`, SP1 of
  SREP 12): a `space` element (epoch in UTC, TT or TDB with the NAIF leap-second table and TDB formula, rate,
  origin, ICRF, ecliptic J2000 or IAU 2009 body-fixed frame, pixel mapping by SREP 14 rule 4), an `ephemeris`
  asset that is a JPL SPK file read by our own DAF reader and pinned by sha256 (de440s.bsp as the reference
  file; Horizons vectors reproduced to 3.2 m), the Standish-Williams elements as the fallback, and bodies
  placed on `object3D`; reference module `conformance/tools/time_frames_reference.py`, fixtures
  `conformance/assets/de440s-excerpt.bsp` and `horizons-vectors.json`, `tests/test_time_frames.py`
  (SRC-44, engine card SR-87).
- Draft SREP "Add the physical sun, moon and sky to dome lights" (`srep/srep-0000-physical-sky.md`, A1 of
  SREP 12): `sky="physical"` on dome lights with `date`, `latitude`, `longitude`, `altitude`, `pressure`,
  `temperature` and `deltaT`; the sun by the Solar Position Algorithm of Reda and Andreas written from the
  report (its example within 0.001°), the moon by Montenbruck and Pfleger, the atmosphere of Hillaire 2020
  (Rayleigh, Mie, ozone; transmittance by quadrature, single and multiple scattering, sun disc, aerial
  perspective, height fog); reference module `conformance/tools/physical_sky_reference.py` and
  `tests/test_physical_sky.py` (SRC-43, engine card SR-86).
- Draft SREP "Add cutaways, exploded views and surface flow to 3D objects" (`srep/srep-0000-cutaways.md`, S5 of
  SREP 12): `section` planes with capped, hatched cuts (crossing points computed once per edge so a closed mesh
  stays closed, loops ear-clipped with holes bridged), `explode` views whose amount 0 is the identity exactly
  (radial, axis and dense-rank modes), and `flow` lines of a field's tangent part over the surface (Runge–Kutta
  with projected stages, Jobard–Lefer seeding at the chord); reference module
  `conformance/tools/cutaways_reference.py` and `tests/test_cutaways.py` (SRC-41, engine card SR-85).
- Draft SREP "Add ragdolls and physics interchange to 3D rigid bodies" (`srep/srep-0000-ragdolls-interchange.md`,
  S4 of SREP 12): the landed Voronoi glue of SREP 80 restated as measurable rules (pieces sum to the whole in
  cells, mass and momentum; no joint below its principal-tension threshold breaks; the glued cantilever's beam
  stresses), a `ragdoll` with `limb` children on an imported model (capsule limbs, ball or hinge joints with
  limits, a `blend` weight that is kinematic at 0, drives the joints by 1 - blend above it and slerps the
  drawn pose), `physics/@src` reading UsdPhysics and glTF KHR_physics_rigid_bodies assets and a
  `physics-export` action writing them with a normative mapping table (SREP 11's physics frame, `sr:` custom
  data for the identity round trip, typed errors for what the format cannot express); reference module
  `conformance/tools/ragdoll_reference.py` and `tests/test_ragdolls_interchange.py` (SRC-40, engine card SR-84).
- Draft SREP "Add particle liquids and granular media in 3D" (`srep/srep-0000-liquids.md`, S3 of SREP 12): a
  `liquid3D` node stepped by APIC, FLIP or MLS-MPM on a MAC grid with quadratic B-spline transfers, a
  projection over the particle cells with an interior density correction and a particle separation, `material`
  children (fixed corotated, snow, Drucker-Prager sand), a `whitewater` child from Ihmsen's potentials with
  hashed deterministic emission, the Zhu-Bridson surface, and the plan's bars (the Martin and Moyce dam-break
  front, the volume) as measured rules; reference module `conformance/tools/liquids_reference.py` and
  `tests/test_liquids.py` (SRC-39, engine card SR-83).
- Draft SREP "Add combustion and sparse tiles to pyro" (`srep/srep-0000-pyro-combustion.md`, S2 of SREP 12): a
  fuel channel with `pyroSource/@fuelRate`, `pyroImpulse/@fuel` and a `pyroCombustion` child (ignition, rate,
  heat, expansion, soot), sparse tiles (`pyro/@tile`, `@tileMargin`, `@tileThreshold`) with a masked step, a
  relative floor on the confinement direction, and the plan's bars (divergence after projection, the
  symmetric plume) as measured rules; reference module `conformance/tools/pyro_reference.py` and
  `tests/test_pyro_combustion.py` (SRC-38, engine card SR-82).
- Draft SREP "Add cloth and soft bodies in 3D" (`srep/srep-0000-softbody.md`, S1 of SREP 12): a `softBody3D`
  node of kind cloth, solid or rope; Vertex Block Descent with PSD-projected spring and stable neo-Hookean
  Hessians, offset self-contact, XPBD rods, fixed iteration and substep counts for the seek check; reference
  module `conformance/tools/softbody_reference.py` and `tests/test_softbody.py` (SRC-37, engine card SR-81).
- Draft Standards SREP "Add deep sky: procedural galaxies, N-body mergers and emission-line nebulae" (`srep/srep-0000-deepsky.md`, the SP8 block of SREP 12): a `galaxy` node whose seeded catalogue follows the exponential disk (sech² in height), a Sérsic bulge (b_n from the half-light condition), logarithmic spiral arms by inverse-CDF azimuths and dust lanes inside the ridges, with blackbody colours; a `dynamics` child putting the bodies on the rotation curve and stepping a Plummer-softened leapfrog with a fixed step count per frame, and a `merger` placement at rest; `medium/lines` with the Hα, Hβ, [O III], [S II] and [N II] lines through the natural, SHO and HOO palettes; its reference module `conformance/tools/deepsky_reference.py` (the catalogues follow their laws with a Kolmogorov statistic of 0.0071, a two-body orbit closes within 10⁻⁵, the energy drift is 3.8 × 10⁻⁶) and `tests/test_deepsky.py`. Engine work filed as SR-80.
- Draft Standards SREP "Add Kerr geodesics, ray bundles, beaming and a relativistic camera" (`srep/srep-0000-relativistic.md`, the open part of the SP7 block of SREP 12): `blackHole/@spin` with Kerr geodesics traced from the Boyer–Lindquist Hamiltonian (E, L and Carter's constant as the checks), `accretionDisk/@orbit` with the Kerr Keplerian redshift and g⁴ beaming, `camera/@motion` static, orbit or infall seen through aberration, the Doppler factor and the searchlight D⁴, and `camera/@bundle` filtering the sky over the ellipse of each pixel's ray bundle; its reference module `conformance/tools/relativistic_reference.py` (the shadow at sqrt(27) M traced and exact, the ISCO at 6M, the weak-field deflection 4M/b, the Kerr closed forms and capture boundaries) and `tests/test_relativistic.py`. Engine work filed as SR-79.
- Draft Standards SREP "Add homogeneous and height media, UsdVol volumes and null-scattering transport" (`srep/srep-0000-volumes.md`, the open part of the A2 block of SREP 12): `medium/@source` box, sphere or height with a closed-form optical depth, the `usdvol` volume asset format (a Volume prim's field relationships to OpenVDBAsset prims), `transport="tracking"` for the path tracer (a majorant per domain, delta and ratio tracking driven by the seeded streams), and `rasterTransport="froxels"` with exponential slices composed front to back; its reference module `conformance/tools/volumes_reference.py` (ratio tracking unbiased, the white furnace exact at albedo 1, froxels converging to the exact transmittance) and `tests/test_volumes.py`. Engine work filed as SR-78.
- Draft Standards SREP "Add scalar 3D: isosurfaces and transfer-function volumes" (`srep/srep-0000-scalar3d.md`, the MF6 block of SREP 12): an `isosurface` object meshing the level set of an expression or of a volume channel by marching tetrahedra (six tetrahedra per cell, crossings from the inside corner, vertices welded by point, faces toward the rising side, smooth, gradient or flat normals) and a `transfer` child of `medium` mapping one scalar channel through colour and opacity stops into SREP 40's density and emission; its reference module `conformance/tools/scalar3d_reference.py` (the sphere's area error falls with order 1.85 and 2.04 between 6, 12 and 24 cells per axis) and `tests/test_scalar3d.py`. Engine work filed as SR-77.
- Draft Standards SREP "Add agent behaviours" (`srep/srep-0000-agents.md`, the CL3 block of SREP 12): an `agents` node whose seeded population lives in days, with the day's pellets from a D24 stream, a race decided by arrival times (the first arrival eats, up to `meals`, shared by two claimants with a `payoff` table for hawk and dove), fates from food and draws, children in parent order with mutated speeds, homes on the rim, and live counts for expressions and charts; its reference module `conformance/tools/agents_reference.py` and `tests/test_agents.py`. Engine work filed as SR-76.
- Draft Standards SREP "Add stylised characters" (`srep/srep-0000-characters.md`, the CL2 block of SREP 12): the area rule of the 2D `squash` and `stretch` modifiers made normative, `deform` on `object3D` with a volume rule (`s` along the axis, `1 / sqrt(s)` across), `axis="velocity"` with a gain, an `eye` node in 2D and a clay `blob shape="eye"` in 3D with pupil travel, lids and D24-seeded blinks, and a bounce rig; its reference module `conformance/tools/characters_reference.py` and `tests/test_characters.py`. Engine work filed as SR-75.
- Draft Standards SREP "Add a style layer" (`srep/srep-0000-style-layer.md`, the CL1 block of SREP 12): a `look` asset (flat, sketch, toon, photoreal) applied by `@look` on composition, group, object3D and shape, the nearest ancestor winning; toon bands that fall at their declared thresholds, specular and rim bands, G-buffer outlines, mesh silhouette and crease edges, D24-noise sketch strokes with an endpoint taper, whole-turn wavelengths on closed paths, overdraw passes and a boil step, marker widths and band hatching; its reference module `conformance/tools/style_layer_reference.py` and `tests/test_style_layer.py` (89 tests). Engine work filed as SR-74.
- Draft Standards SREP "Add fields and flow" (`srep/srep-0000-fields.md`, the MF5 block of SREP 12): a `field` node in the data frame with expression, complex, grid, forceField, charge, current and dipole sources; arrows, evenly spaced streamlines (Jobard and Lefer 1997), line integral convolution (Cabral and Leedom 1993), phase portraits (Wegert 2012), charge lines and contours; the winding number and the dipole line constant as kit measures; reference module `conformance/tools/fields_reference.py` and `tests/test_fields.py`. Engine work filed as SR-67.
- Draft Standards SREP "Add reactive values" (`srep/srep-0000-reactive-values.md`, the MF4 block of SREP 12): a `value` asset read by `prop("id.value")`, time folds stepped from their start with hold or linear between steps, index folds for sums, gather-form reads among folds, the `draw` and `random` draws of an update, bounds, and the Fourier centre of mass and Einstein solid of shots 9 and 5; reference module `conformance/tools/reactive_values_reference.py` and `tests/test_reactive_values.py`. Engine work filed as SR-66.
- Draft SREP "Add tagged formula parts and shape morphing" (`srep/srep-0000-semantic-tex.md`, the MF3 block of SREP 12) with its reference module `conformance/tools/semantic_tex_reference.py`: the `\part{name}{...}` tag, part matching by name or TeX, moving, morphing and fading of parts, and path morphing by arc-length resampling, start alignment, sub-path matching and linear interpolation with a self-intersection count; `python3 conformance/tools/semantic_tex_reference.py` prints the SREP's numeric table. Engine work is SR-65.
- Draft SREP "Add space transforms" (`srep/srep-0000-space-transforms.md`, the MF2 block of SREP 12) with its reference module `conformance/tools/space_transforms_reference.py`: the matrix, expression and complex-function deform modifiers as point maps, adaptive midpoint subdivision bounded at ten splits, breaks at poles, the conformality check, the stereographic projection of the 3-sphere and the Penrose compactification; `python3 conformance/tools/space_transforms_reference.py` prints the SREP's numeric table. Engine work is SR-64.
- Draft SREP "Add coordinate systems and plots" (`srep/srep-0000-plots.md`, the MF1 block of SREP 12) with its reference module `conformance/tools/plots_reference.py`: the axes mapping, nice 1-2-5 tick steps and step-decided tick labels, explicit, parametric and polar sampling, clipping to the box, marching squares with the centre-resolved saddle, 3D axes and parallel-transport tubes; `python3 conformance/tools/plots_reference.py` prints the SREP's numeric table. Engine work is SR-63.
- Conformance: an entry's `"compare"` form checks its render against another case's, each at its own entry's output: `{"case": ID, "tolerance": N}` passes when every channel of every pixel is within N 8-bit code values of the other render, and `{"case": ID, "brighter": true}` when the render is brighter (by the sum of its channels) somewhere and darker nowhere. A failed render of either case is an error, and so are a missing case, a case compared with itself, both or neither of `tolerance` and `brighter`, and unknown keys. The report gives the pixels that differ, or those brighter and darker.
- Conformance: case `srep-0071-subsurface-absent`, the scene of `srep-0071-subsurface-zero-neutral` without the subsurface attributes, as its reference picture.
- Conformance: an entry's `"coverage"` form checks the fraction of a box that a colour class fills: `[{"colour": C, "box": [x0, y0, x1, y1], "min": F, "max": F}]` with `colour` one of the four colour classes or `lit` (some channel above a quarter) and `dark` (every channel below a tenth), integer box corners (x1 and y1 exclusive) and at least one of `min` and `max` as fractions in [0, 1]. A simulation or a 3D render fixes where content must appear, not its exact outline (SREP 12 milestone 0).
- Conformance: `catalogue.py` (also `run.py --catalogue [--shots N,M]`) scores the 36 probe scenes of SREP 12's benchmark catalogue (`cases/srep-0012-shot-NN-*.xml`, written by `tools/srep12_cases.py` from its table of shots) and reports the native count: a shot is native when its probe renders under `--strict` without a fallback at its check frame, meets its pixel checks there and renders its seek frame alone pixel-identical to the same frame played from 0 (SREP 14); the table's `custom` and `gap` flags, a strict fallback (`degraded`), a failed check (`wrong`) and a failed render (`error`) take precedence in that order from the right. The run is a measurement: it exits 0 whenever every selected probe was scored and writes `out/catalogue.json` and `out/catalogue.md`. Only the Rust engine is wired (`RS_RENDER_BIN`).

### Fixed

- `tools/check_hygiene.py --artifacts` (R5) names the tests that fail from the unpacked sdist, from pytest's short summary (`-rfE`), after the counts line; it quoted the counts line alone, so a failing gate could not be traced to a test. Seen when R5 reported one failure twice under a machine load near ten while the same sdist's suite passed alone twice.
- Conformance: the six SREP 34 findings cases (`srep-0034-inert-collapse`, `-inert-channel-red`, `-inert-key-param`, `-inert-effect-param`, `-inert-source-opacity-zero`, `-mask-miss`) expected the engine's pre-amendment codes `E19` and `E20`; they now expect `INERT-I9`, `INERT-I10`, `INERT-I12`, `INERT-I13`, `INERT-I11` and `MASK-MISS`, the codes SREP 34's own case table states and the Rust reference reports since 0.5.0. They had failed on every build from 0.7.2 on; they pass on scene-render main 67a661a (0.7.4, llvmpipe).
- Conformance: `srep-0036-geo-outline-p125` and `srep-0036-geo-outline-p875` are no longer pending. Their boxes are those of a trace with round caps (p125: green cx 190.89, cy 221.46, w 504, h 104; p875: cx 270.65, cy 167.8, w 604, h 208), which the draft SREP "Stroke geoLayer outlines with round caps and joins" (`srep/srep-0000-geo-outline-cap.md`) states from the reference's behaviour, as SREP 0 settles a point the schema is silent on; measured on main 67a661a.
- Conformance: `srep-0017-pdf-bad-cache` is no longer pending: it checks the render report for `ASSET-MISSING`, the code SREP 18's table gives an asset that fails its `cacheSha256` (SREP 17 erratum of 2026-10-24); the reference refuses the render and writes no picture.
- Conformance: `srep-0029-matte-choke-grow` and `srep-0032-resample-mitchell` are pending, each with the reference's measurements on main 67a661a: a negative `matte-choke` amount erodes where SREP 29 and the schema say it dilates, and `resample="mitchell"` departs from SREP 32's weights at five of 32 sampled columns (recomputed from the strip asset). Both had failed, not pending, on every build from 0.7.2 on, so the kit run was red; they are tracked on the engine board as SR-59 and SR-60.
- Conformance: a findings entry with `"via": "report"` has the engine encode the whole document with a render report (SREP 18) and checks that report's findings (`codes`, `absent`, `counts`, `messages`; a report gives no `valid`). An unknown `via` is an error; before, it silently checked `validate`. SREP 63's two cases use it: `validate` never carried the SUP findings of SREP 22, so `srep-0063-when-raster` passed whatever the engine did. SREP 18's report cases, SREP 19's four legibility cases and SREP 21's `FONT-GLYPH` case use it too.
- Conformance: 79 of the 82 pending cases are no longer pending, each passing on scene-render main (llvmpipe): 74 at e586b57 (0.7.4); at a7d7b01 `srep-0058-vertex`, where a motion path's exact vertex takes the outgoing direction, and the four render comparisons of SREPs 71 and 87 through the `compare` form (the SREP 87 seed-local pair and `srep-0071-subsurface-zero-neutral` against `srep-0071-subsurface-absent` pixel-identical; `srep-0071-subsurface-wraps-terminator` brighter than `srep-0071-subsurface-zero-neutral` at 20400 pixels and darker at none). 63 passed already: seven of SREP 16, four of SREP 17, six of SREP 26, eleven of SREP 52, nineteen of SREP 57, `srep-0058-jump`, two of SREP 59, `srep-0063-when-raster` and the twelve failed-render cases of SREPs 66, 69 and 87 (through the `failure` form). Three of SREP 16 expected the wrong numbers: `srep-0016-arrow` and `srep-0016-trim-arrow` gave the box centre for the pixel centroid (now 331.02 and 258.53, as SREP 15's identical cases derive), and `srep-0016-anchor` gave the geometric 164.24 x 164.24 box where the classifier sees 164 x 162, as the line's corners blend with the boxes at its ends (derived by supersampling the geometry). `srep-0016-trim-arrow` also checks SREP 16's "no green right of x = 322". Eight now check the render report. Three stay pending, each reason giving what the engine does: `srep-0017-pdf-bad-cache` (SREP 17 names no failure code) and the two SREP 36 outline cases (no stroke cap is specified for a traced geo outline).
- Conformance: `run.py` checks only colour keys of an entry as colours. It checked `pending`, `source`, `requires` and `native_only` as colours that were missing, so `--run-pending` could never retire a pending colour case, and an entry with `source` or `requires` could not pass.
- Conformance: `run.py` reads `validate --format json` from the `scene-render-cli/1` envelope (`result.files`), as well as the older top-level `files`. Every findings case had reported `KeyError: 'files'` against current scene-render. An envelope with another format, or with no file entry, is an error rather than a pass.
- Conformance: `srep-0055-node-shutter-frame0` is no longer pending. It checks the first frame's blur with the default `shutterPhase` (−90°) against SREP 55's sample times, with properties holding their first key before time 0 as the schema defines (blue 180°: cx 320.63; red 360°: cx 322.81; green 0°: sharp at 320.0). The pending note expected a smear on both sides, which would need linear extrapolation before the first key; the schema's default is hold.

## 1.8.0 — 2026-10-20

### Added

- Validates and packs schema 1.7.1 documents: the source release carries schema 1.7.1 and its generated reference under `docs/schema`, and `sr_core.scene` is regenerated from it, so `describe()` and the class documentation carry the attribute documentation of SREP 92 and report schema release 1.7.1. See [schema/CHANGELOG.md](schema/CHANGELOG.md).
- `sr_core.scene`, a Python scene SDK generated from the schema (SREP 91, `srep-0091.md`):
- classes for all 169 complex types, with values checked on assignment;
- reading and writing that keeps comments and lexical forms;
- version gates compiled from the Schematron, with `min_version()` and `version="auto"`;
- checks at four levels (construction, standard library, lxml, engine);
- the `sr-scene` command (`check`, `min-version`, `format`);
- the optional extra `sr-core[validate]` (lxml);
- a valid lexical `str` is accepted for every attribute whose type is not string-valued (numbers, booleans, `xs:dateTime`) and written as given, so a ported builder can write the exact text of the one it replaces;
- `layout="indent"` for `to_bytes` and `write`: libxml2's pretty-print rule (indentation only inside elements that have no text child), equal to `lxml.etree.tostring(..., pretty_print=True)`;
- a class that covers several element names takes the constructor keyword `xml_name`, typed as a `Literal` of those names and refused with `SchemaValueError` otherwise: `Still(xml_name="thumbnail", path=...)` builds a `<thumbnail>` (before, `to_bytes(Still())` could only write `<poster/>`).
- `sr_core.scene` for AI agents and their users (section 3.12, 3.13 and 8 of the SDK SREP draft):
- `UnknownNameError`, a `SchemaValueError` and an `AttributeError`, for a wrong attribute, constructor keyword, `add_<name>` factory, child or `xml_name`, with `suggestions` (another case, `from` for `from_`, close spellings) and the `allowed` names: `<layer> has no attribute 'blendMode'; did you mean 'blend'?`;
- `describe(target)`, `describe_all()` and `element_names()`: documentation, minimum version, content model, children with occurrences, and attributes with type, enumeration, facets, default, required, minimum version and documentation, as a frozen record or JSON of the versioned format `sr-scene-describe/1`;
- `sr-scene describe NAME...`, `sr-scene describe --all --format json`, `sr-scene list` and `sr-scene new`;
- `sr-scene check --format json` carries `"format": "sr-scene-findings/1"`;
- `docs/scene-sdk-guide.md`, whose Python blocks the test suite runs.
- Drift controls:
- `python3 -m sr_core.scene.generate --check`, run by `tools/release.py check`;
- `release schema` regenerates the SDK and needs an Unreleased entry for it.
- `conformance/run.py` gains `--run-pending` (runs the pending cases that have a check: one that now passes is reported as `retire` and fails the run, one that still fails stays pending) and the check form `failure` (`{"code": "PRG12"}`: a non-zero exit, the code in the output, no picture). It prints how many cases were pending.
- `tools/check_hygiene.py` rule R4 also compares `srep/index.md` with the SREP headers (Title, Type, Status, Version, a row for every SREP, ascending order); an intended difference is an `srep/srep-NNNN.md:R4:reason` entry.

### Changed

- `sr_core.scene`: the documentation of an attribute is its `xs:documentation`, or else that of its simple type; it reaches `Attr.doc`, the descriptor's `__doc__`, a docstring after each declaration and the docstrings of the checker stubs (before, the descriptors carried only the declaration's own text, and the stubs none).
- `sr_core.scene`: a refused enumeration value carries `suggestions` and says `did you mean 'multiply'?` for `layer.blend = "mutliply"` (also inside list types and unions); a mistyped class name, `sr_core.scene.Layr` or `sr_core.scene.textanimator`, raises `UnknownNameError` with `kind="class"` and `did you mean 'Layer'?` (still an `AttributeError`; `from sr_core.scene import Layr` is still an `ImportError`). `SchemaValueError` now pickles.
- `sr_core.scene`: an unknown attribute, factory or child now raises `UnknownNameError` (still an `AttributeError`, or a `SchemaValueError` for a child) instead of a bare `AttributeError`.

### Fixed

- `scenerender-vpkg run`: a render step that names an `output` and a `to` renders that output by its id on py, rs and js, then copies its file to `to`, so the output keeps the settings it declares (size, codec, quality, colour, audio, report). Before, py and rs got `-o TO`, which wrote an ad-hoc output with the engine's defaults. A scene, or the engine variant of one, that lacks the named output id now fails the step instead of rendering something else. On c, which cannot select an output, `run` prints a warning that the output's settings are not applied.
- `sr_core.scene` (second review, 2026-10-12):
- `add` and direct changes of `.nodes` refuse the element itself or one of its ancestors; before, the tree became a cycle and `iter`, `check`, `xml_path` and writing never returned;
- white space is XML white space only (space, tab, CR, LF): a no-break space or U+2003 in element-only content is `xsd:occurs` at level 1 as it is for lxml, `layout="pretty"` keeps it instead of deleting it, and `new_id`, the program `mode` test and the gate compiler no longer trim Unicode spaces;
- `new_id` keeps an index of the document's ids, so building a document with one `new_id` per element is linear (8,000 ids: quadratic before);
- the generator checks the XSD against the XML Schema vocabulary it implements (D3): `xs:unique`, `xs:key`, `xs:keyref`, `xs:any`, `xs:import`, `nillable`, `targetNamespace` and the like fail the generation instead of being ignored, which made the SDK pass documents lxml refuses;
- `read` ignores comments and processing instructions inside a DOCTYPE's internal subset; it moved them into the prolog, and the written document's C14N 2.0 form differed from the original's;
- `sr-scene check` reports a clean document as `ok (level 1)`, `ok (levels 1, 2)` ..., and its JSON output has `levels`: a bare `ok` after level 1, which runs only the Schematron's version gates, overstated the check;
- the SREP draft (4.3) no longer says NaN and the infinities are refused outright: a Python NaN or infinity is, while the `xs:double` lexical forms `NaN`, `INF`, `-INF` are accepted as a `str` unless a facet refuses them;
- the D4 test of the generated gates takes its expectation from the `.sch` through ElementTree and two regular expressions instead of `compile_gates`, which the generator itself uses, so a fault there cannot pass unseen;
- `conformance/run.py` no longer reports `pass` for a case that checks nothing: an `expected.json` entry with an unknown key, an empty check or no check at all is an `error`, and so is a form whose checks did not run.
- `conformance/make_cases.py` reads the implicit camera's field of view and the default sensor width from the constants block in `conformance/CONVENTIONS.md` (2.8) instead of restating them; a test fails when the block and the prose disagree. The generated cases are unchanged.
- The case generators of `conformance/tools/` are re-run by `tests/test_conformance_generators.py`, which fails when the committed `srep_cases/` differ from what they write; the README's SDK example is executed from the README.
- `srep/index.md` row 83 carries the header's title.
- `docs/vpkg-howto.md` names every option of `scenerender-vpkg` (`pack --date`, `--with-archive`, `unpack`/`run --no-fetch`, `verify --shallow`, `info --json` were missing) and says that only the Rust engine is active; `tests/test_docs_cli.py` fails when an option is missing and runs every `python3 -m` command of the README.
- `srep/srep-0000-generated-marker-ids.md`, the unnumbered draft of SREP 57, is removed; hygiene rule R4 now fails a `srep-0000-*.md` file whose title a numbered SREP carries.
- Docstrings for every public symbol of `vpkg/pack.py`, `review/{scene,pdf,cli}.py` and `schemadoc/html.py`; `tests/test_docstring_coverage.py` keeps the coverage from falling.
- `srep/index.md` says that engine-repository paths cited in SREPs are not files of this repository.
- The corpus differentials of the SDK (D5, D6, the gates and the name tests) run by default; `SR_SCENE_CORPUS=0` switches them off. CI no longer sets a variable to enable them.
- The tests of SREPs 76 to 85 no longer skip when the `schema-1.5.0` tag is missing: the two 1.5.0 files are kept, with their hashes checked against the inventory, in `conformance/tools/baseline-1.5.0/`.
- `tests/test_conformance.py` regenerates `conformance/cases/` and `assets/` from nothing, so a file nobody generates fails it; the three hand-kept case files moved to `tests/fixtures/kit/`.
- `tests/test_drift_p2.py` pins the capability-manifest schema to the code and the validator that read it, the counts quoted in SREP 0000 and here to the schema, the engine-gap inventory to the SREP diff blocks, and the packages `ci.yml` installs to the extras and to what the tests import (including what they skip when absent).

### Docs

- The schema documents its attributes (schema CHANGELOG, SREP 92, `srep-0092.md`): `tests/test_schema_attribute_docs.py` fails for an attribute with neither documentation nor an entry in `tests/undocumented-attributes.txt`. The bundled schema copy and generated reference carry the sentences.
- 746 attribute docs corrected after an adversarial review against the engine code.
- `docs/scene-sdk-guide.md` section 10 explains the cost of a path-traced camera, width × height × `pathSamples` × `maxBounces` per frame, and how to choose the two values. Its Python block, run by `tests/test_scene_guide.py`, reads the defaults and maxima from the schema.

## 1.7.0 — 2026-10-12

### Added

- Validates and packs schema 1.7.0 documents: the source release carries schema 1.7.0 and its generated reference under `docs/schema` (SREP 87, with the exception of SREP 90; document version 1.7). See [schema/CHANGELOG.md](schema/CHANGELOG.md).

### Tooling

- The compatibility kit has the 15 cases of SREP 87 (`conformance/srep_cases/srep-0087.json`, written by `conformance/tools/srep87_cases.py`, with the modules `srep87-*.wasm`), and SREP 66's `srep-0066-program-id-collision` is amended by SREP 87. The reference implementation of SREP 87 is on rs-scene-render main (6602b81d) and passes all 16; 10 of them run (no longer pending), and the 3 failure cases of SREP 87, the amended SREP 66 case and the 2 render-comparison cases of `seed-local` stay pending in `conformance/tools/kit_pending.py` with the result of the check by hand, because `run.py` cannot express their check. `srep-0072-precision-3d-note` is no longer pending: the reference reports PREC1 since main 285a6931. See [schema/CHANGELOG.md](schema/CHANGELOG.md).

## 1.6.0 — 2026-10-11

### Added

- Validates and packs schema 1.6.0 documents: the source release carries schema 1.6.0 and its generated reference under `docs/schema`, with pages for the new types (SREPs 66 to 85 and 89; document version 1.6). See [schema/CHANGELOG.md](schema/CHANGELOG.md).
- `conformance/run.py` gains the check form `audio`: it delivers the document's audio-only WAV output (`encode --output`) and measures the gain of each test tone at given times (SREP 82).

### Tooling

- The compatibility kit has the 377 cases of SREPs 66 to 80, 82 to 85 and 89 (`conformance/srep_cases/srep-0066.json` to `srep-0089.json`, written by the generators in `conformance/tools/`); `conformance/tools/kit_pending.py` lists the 12 that stay pending, with the reason for each: 11 whose check `run.py` cannot express yet (failed renders of SREPs 66 and 69, render comparisons of SREP 71), each checked by hand on the reference, and SREP 72's `srep-0072-precision-3d-note`, which the reference fails.
- `conformance/tools/engine_gap.py` measures the gap between sr-core's schema and a reference engine's vendored copy (SREPs 76 to 81; `conformance/tools/engine-gap-1.5.0.json`).
- CI checks out the tags, which the tests of SREPs 76 to 83 read.

## 1.5.0 — 2026-10-06

### Added

- Validates and packs schema 1.5.0 documents: the packaged schema, the generated reference under `docs/schema` and the files `pack` and the lints read are schema 1.5.0 (SREP 59: rules R53 and R54; document version 1.5), and the schema folder carries `capabilities-1.schema.json` (SREPs 22 and 63). See [schema/CHANGELOG.md](schema/CHANGELOG.md).

### Tooling

- The compatibility kit has the cases of SREPs 58 (`srep-0058-jump`, `-vertex`), 59 (`srep-0059-identity`, `-empty-idrefs`, `-audiogram-source`) and 63 (`srep-0063-when-raster`, `-pathtrace`), and `srep-0016-group-box` of the SREP 16 erratum; those the Rust reference does not pass yet are pending. `tests/test_srep_0059.py` and `tests/test_capabilities.py` check the schema side; a case invalid only by an XSD identity check that libxml2 skips is skipped by the generic case test.
- The 11 `srep-0052-caption-lines-*` cases are pending until the Rust reference has the `captions` command (gap/srep-52-captions-dump); the kit keeps their captions check form.

## 1.4.0 — 2026-10-06

### Added

- Validates and packs schema 1.4.0 documents: the packaged schema, the generated reference under `docs/schema` and the files `pack` and the lints read are schema 1.4.0 (SREP 57: a `beat.N` or `bar.N` marker id is accepted where a marker is named, when the scene has a `beatGrid`; document version 1.4). See [schema/CHANGELOG.md](schema/CHANGELOG.md).

### Tooling

- The compatibility kit has the 19 cases of SREP 57 (`conformance/srep_cases/srep-0057.json`), pending until the Rust reference implements it, and `tests/test_srep_0057.py` checks the schema side.

## 1.3.0 — 2026-10-06

### Added

- Validates and packs schema 1.3.0 documents (every accepted SREP up to 56, and SREP 40), which the 1.2.0 package rejects: the packaged schema, the generated reference under `docs/schema` and the files `pack` and the lints read are now schema 1.3.0. See [schema/CHANGELOG.md](schema/CHANGELOG.md).

### Tooling

- The compatibility kit has cases for SREPs 15 to 56 (`conformance/srep_cases/*.json`, with their assets under `srep_cases/assets/`); `make_cases.py` writes them into `cases/` and `expected.json`.
- `conformance/run.py` gains the check form `findings`: it runs `validate --format json` (or the render, with `via: render`, for a report that exists only at frame evaluation) and compares the finding codes, their count, message fragments, the codes that must be absent and the document's validity. A case with `pending` is skipped and listed with its reason, never counted as a pass. numpy and Pillow are needed only by pixel cases.
- An `output` entry of `expected.json` may select the range and frame to render (`id`, `time`, `start`, `end`, `frame`), for SREP 13's overlay case.
- `conformance/make_test_font.py` generates the pinned font of SREP 20 and 21's cases, and `make_model_assets.py` the models of the model cases (`materials.glb`, `joints.glb`, `morphs.glb`).
- A test per SREP (`tests/test_srep_00NN.py`) checks its schema rules and its case documents, `tests/test_schema_rules.py` holds the shared helpers, and a pending-case test keeps the `pending` entries honest.
- `conformance/DEFINITIONS.md` D11 states the lighting convention the engine implements (no factor π for punctual lights), with a history paragraph; SREP 25 makes the engine's behaviour the reference.

### Fixed

- `pack` lint: paths relative to the user's home (`"~/..."`, `expanduser("~")`, `$HOME/...`, `Path.home()`) are now an error, `home-path`, as `/home/...` already was. A script that read a brand kit through `expanduser("~/...")` passed the lint and packed a build step that could not run anywhere else. `docs/vpkg-howto.md` §3.4 describes vendoring shared code and kits into the project with a lock.

## 1.2.0 — 2026-09-30

### Added

- `sr-review` (also `python -m sr_core.review`) writes a PDF review sheet of a scene: a cover with its facts and outputs, one page per section (`section` markers inside `chapter` markers, else chapters, else top-level groups) with a frame, its captions and its markers, then the open to-dos, sources and credits, and metadata. `--engine` renders the frames with the engine's still command, the same commands `scenerender-vpkg run` uses; `--frames` reads and keeps them. Exit 0 written, 1 written with missing frames, 2 nothing written. Standard library only; frames are smaller (JPEG) when Pillow is installed.

### Tooling

- The compatibility kit gains cases for SREP 9 (tile zoom, raster warp, vector tiles), SREP 10 (globe orientation), SREP 11 (substeps, damping, velocity) and SREP 13 (clamping, crossfade, alignment, focus, overlay without segments); `run.py` rewrites every `../assets/` path of a case, not only `src`.
- `conformance/run.py` renders a case's named output at a given output time when its entry in `expected.json` has `output` (`{"id", "time"}`), for SREP 13's cases; an engine that cannot is reported, not crashed.
- The schema-rule tests skip conformance cases of SREPs that are not yet accepted (unnumbered drafts, Draft or Review): their cases use syntax the canonical schema gains only on acceptance.

## 1.1.0 — 2026-09-29

### Added

- Package format 1.1 (SREP 6): `packed.metaSha256` covers `README.md` and `vpkg.schema.json`, and `pack` writes 1.1 manifests. 1.0 packages still read, with a warning that their metadata is not hash-covered. The format schema is `vpkg-1.schema.json`, with `$id` `urn:scene-render:vpkg:1`.

### Security

- `verify` and `unpack` never write from a package once any check fails, and never write outside the extraction folder. Before, a hostile manifest path could write anywhere, even during a plain `verify`.
- Paths with control characters are rejected. A newline could hide a `..` from the path check.
- `fetch` validates the manifest and keeps every download inside the project.
- `pack` refuses symbolic links that leave the project. It had bundled the files they pointed at.

### Fixed

- References to files outside the project are rewritten in `<include>`d documents too. Such packages used to fail their own `verify`.
- Font files anywhere in the project (for example `assets/`) are found when resolving font families.
- Render steps are out of date when their scene or any file it references changes.
- Media types come from a fixed table, so a project packs to the same bytes on every machine.
- The README no longer states version numbers that go stale. The reference's marker file no longer embeds the tools version, which had made a tools-only release fail `release.py check`.
- The sdist includes `conformance/`.
- `scenerender-vpkg run` reports a missing engine command with the alias it expected and how to provide it (a symlink, `VPKG_ENGINE_<ID>` or `engines.json`), instead of a Python traceback.

### Docs

- SREP 4: a correction that rejects only documents whose meaning was undefined is Fixed, not Breaking.
- SREP 8: the version gate and the Schematron checks for the 1.1 additions.
- SREP 7 adopts `conformance/CONVENTIONS.md` and the new `conformance/DEFINITIONS.md` (definitions D1–D27 and preset tables P1–P2, copied in so the specification is complete). It states the precedence, the rotation handedness of layers and 3D objects, and the explicit-camera default.
- SREP 0 describes the compatibility kit as it works: geometric measurements, no reference renders.
- The vpkg how-to and SREP 1 explain why the default engine commands are aliases (`scene-render-rs`, `-c`, `-js`) and how to create them.

### Tooling

- CI covers Linux and macOS on Python 3.10, 3.12 and 3.13, runs the schema-rule and conformance-runner tests, and runs the installed commands from outside the checkout. A test runs the vpkg how-to's walkthrough with the finished `vpkg.json` taken from the how-to itself.
- `conformance/run.py` exits non-zero when any case fails, reports a missing engine, timeout or failing engine as that case's error instead of crashing or passing, and always writes its report.
- Conformance cases that can detect what they test:
- a2 has an off-centre anchor, so the rotation sign shows;
- the glTF marker in b5 is asymmetric and single-sided, with a back-facing quad that must not appear;
- new cases: b7 (combined yaw and pitch), b8 (`focalLength`), d1 (object3D rotation order), d2 (2.5D layer rotationY) and d3 (object3D rotationY).
- The conformance runner is tested: failing and missing engines, wrong pictures, and exact regeneration of the cases.
- `.github/workflows/ci.yml`: tests on Python 3.10 and 3.12, `release.py check` and `check_hygiene.py --artifacts` on every push and pull request.
- `conformance/`: the compatibility kit (normative conventions, cases, runner) now lives in this repository. The runner finds engines through environment variables or the `scene-render-*` aliases, not machine paths.

## 1.0.1 — 2026-09-29

### Fixed

- The sdist is a complete source release. It ships `schema/`, `docs/`, `srep/`, `tools/` and `tests/`, and the tests pass from it; before, they failed at collection.
- Installation instructions and examples use neutral paths and projects: the README (and so the package metadata), the vpkg how-to and the `run` module documentation.

### Tooling

- `tools/release.py archive schema` builds the schema release tarball from a tag: the XSD, the Schematron, their hashes, README, CHANGELOG, LICENSE and the HTML reference. The same tag gives the same bytes.
- `tools/check_hygiene.py` checks that tracked files and release artifacts carry only releasable material: no working material, private paths or unpublished references, SREP records complete, artifacts complete.

### Docs

- SREP 0 is Active, and states when documentation-only and process SREPs are Final or Active.
- SREP decision records state the decision and date only.
- The SREPs name the conformance suite, not a local folder.
- SREP 5: engine-neutral wording in the schema.

## 1.0.0 — 2026-09-29

### Added

- `scenerender-vpkg`, moved from py-render (`33caa35`). It writes and reads package format 1.0 ([SREP 1](srep/srep-0001.md)).
- Package-format compatibility: a 1.N reader reads later 1.M packages, reporting what it doesn't know as warnings; other
  majors get a clear refusal; `pack` never writes a version newer than its own.
- The package format's identifier is `urn:scene-render:vpkg:1.0` (JSON Schema `$id`, and `$schema` in new
  manifests), replacing a py-render URL; older manifests remain valid.
- `sr-schemadoc`: the static HTML reference of the canonical schema, reproducible byte for byte, with `--check`.
- `schema/`: the canonical scene-render XSD and Schematron (its versions are in `schema/CHANGELOG.md`).
- `tools/release.py`: computes and applies version bumps from the changelogs.
- The SREP process ([SREP 0](srep/srep-0000.md)) and SREPs 1–4.
