```
SREP:            0
Title:           Add draped map ground and globes to object3D
Author:          rs-scene-render maintainers
Status:          Draft
Type:            Standards
Created:         2026-09-29
Schema-Version:  1.2
Requires:        the tiles and basemaps SREP (srep-0000-basemaps.md)
```

# SREP 0 — Add draped map ground and globes to object3D

## Abstract

`object3D` gains two primitives. `primitive="map"` lays a map asset down as ground in 3D, draped with the map
as the 2D renderer draws it, optionally raised by elevation tiles (`@terrain`) and with the basemap's buildings
extruded (`@buildings`). `primitive="globe"` wraps a sphere in the map's content drawn over the whole world.
Authors get Google Earth-style flights, terrain and 3D cities from the same `<map>` they use in 2D.

## Motivation

A tilted 2D map layer is a flat card: it has no relief, no buildings and no horizon, and a globe drawn in an
orthographic projection cannot be lit or orbited by the 3D camera. Map scenes in documentaries and news
graphics routinely fly a camera over terrain and cities; doing it in scene-render today needs pre-rendered
video.

## Specification

### Syntax

```xml
<!-- object3D/@primitive gains two values -->
<xs:enumeration value="map"/><xs:enumeration value="globe"/>

<!-- new object3D attributes -->
<xs:attribute name="map" type="xs:IDREF">
  <xs:annotation><xs:documentation>
    primitive="map": the map asset as ground in the object's xy plane, one map pixel per scene
    unit, draped with the map as drawn; @terrain (tiles of elevation, Terrarium or Mapbox
    Terrain-RGB per @terrainEncoding) raises it toward the camera (−z) by true height times
    @exaggeration on a grid of @resolution cells, and @buildings extrudes the footprints of its
    vector basemap to their heights (in @material). Terrain and buildings need a web-mercator
    map. primitive="globe": a sphere of @radius (poles on the y axis, 0° longitude facing the
    camera) draped with the map's content drawn over the whole world. @textureSize is the
    drape's size in pixels along a map's longer side, and a globe drape's height (its width
    is twice that).
  </xs:documentation></xs:annotation>
</xs:attribute>
<xs:attribute name="terrain" type="xs:IDREF"/>
<xs:attribute name="terrainEncoding" default="terrarium">
  <xs:simpleType><xs:restriction base="xs:string">
    <xs:enumeration value="terrarium"/><xs:enumeration value="mapbox"/>
  </xs:restriction></xs:simpleType>
</xs:attribute>
<xs:attribute name="exaggeration" type="xs:double" default="1"/>
<xs:attribute name="buildings" type="xs:boolean" default="false"/>
<xs:attribute name="textureSize" default="2048">
  <xs:simpleType><xs:restriction base="xs:positiveInteger"><xs:minInclusive value="64"/><xs:maxInclusive value="8192"/></xs:restriction></xs:simpleType>
</xs:attribute>
```

The existing `@resolution` (8–256, default 64) is reused for the terrain grid.

```xml
<!-- in the object3D rule of pattern p26 -->
<sch:assert id="C47" test="not(@primitive='map' or @primitive='globe') or @map">object3D primitive="map" or "globe" requires @map.</sch:assert>
<sch:assert id="R28" test="not(@map) or /scene/assets/map[@id=current()/@map]">object3D/@map must name a map asset.</sch:assert>
<sch:assert id="R29" test="not(@terrain) or /scene/assets/tiles[@id=current()/@terrain]">object3D/@terrain must name a tiles asset.</sch:assert>
```

No new element or asset kind, so no version gate beyond the one the basemaps SREP adds: the attributes and
enumeration values are accepted in every version, as new attributes on existing elements are.

### Semantics

**Ground (`map`).** The map asset of size W × H is drawn exactly as a 2D layer would draw it at the current
time (its camera, fly-tos, layers, basemaps and animation) into a drape texture of `@textureSize` pixels along
its longer side, and mapped onto a rectangle W × H scene units, centred on the object's origin in its xy
plane, with the map's up toward −y. The object's transform (rule 2.5 of the conventions) then applies.

**Terrain.** With `@terrain`, the rectangle is a grid of `@resolution` × `@resolution` cells (over its longer
side; the shorter side keeps square cells). Each vertex's longitude and latitude are the inverse of the map's
Web Mercator view at that point, and its height `h` in metres is sampled bilinearly from the elevation tiles
(256-pixel tiles) at zoom

    zd = round(map_zoom + 1 − log2(cell)),   map_zoom = log2(2π·k / 512),   cell = max(W, H) / resolution,

clamped to the archive's zoom range, where `k` is the map's projection scale (pixels per radian) and
elevation is decoded from the tile's R, G, B (0–255 integers) as

    terrarium: h = R·256 + G + B/256 − 32768
    mapbox:    h = −10000 + (R·65536 + G·256 + B)·0.1

A missing tile gives h = 0. The vertex moves toward the camera by

    Δz = −(h − h₀) · exaggeration · s,   s = k / (6378137 · cos φ₀)

where h₀ and φ₀ are the height and latitude at the map's centre: the centre stays on the object's plane,
and one metre of height is as many scene units as one metre of ground there.

**Buildings.** With `@buildings`, the polygons of the source layer `buildings` (or `building`) of the map's
first basemap (which must hold vector tiles), at zoom min(floor(map_zoom + detail), 22) with that basemap's
`@detail`, are extruded between `min_height` (else
`render_min_height`, else 0) and `height` (else `render_height`, else 8) metres, scaled by `s` and
`@exaggeration` like the terrain and standing on the terrain height at the footprint's first ring's vertex
mean. Features whose top is not above their bottom are skipped. They are drawn in `@material`.

**Globe.** A sphere of `@radius`, poles on the y axis with north toward −y, longitude 0 at −z (facing the
implicit camera) and 90° east at +x. The drape is the map's content (its layers and basemaps) drawn over the
whole world in the equirectangular projection, `2 · @textureSize` pixels wide (at most 8192) and
`@textureSize` tall (at most 4096), with north at the top.

**Material.** The drape is the base colour; `@material` supplies the rest of the surface (roughness, metallic)
and the buildings' colour.

### Defaults and the neutral case

Both primitives are new; other primitives ignore the new attributes.

## Rationale

- **One map pixel per scene unit** lets a 2D map and its 3D ground line up exactly, so a scene can cut from one
  to the other.
- **Terrarium and Mapbox Terrain-RGB** are the two public elevation encodings (AWS Terrain Tiles,
  MapTiler, Mapbox).
- **True-scale height** with an exaggeration factor is the convention of MapLibre GL's terrain and Cesium.

## Rejected alternatives

- **A separate `<terrain>` element.** Terrain only has meaning under a map; attributes on the object keep it
  one element.
- **Drawing the drape per frame on the GPU as a render target.** An engine choice, not a format question; the
  specification only fixes what the drape contains.

## Backwards compatibility

Every 1.1 document is valid and renders the same.

## Engine impact

| Engine | Status | Work | Tracking |
|---|---|---|---|
| Rust (`rs-scene-render`), reference | branch `maps-physics` | done: CPU drape, terrain grid, extruded buildings, globe | |
| C (`c-scene-render`) | pending | needs the basemaps SREP first | |
| Python (`py-render`) | pending | | |
| JavaScript (`js-render-engine`) | pending | | |

## Conformance

| Case | Checks | Tolerance |
|---|---|---|
| `conformance/cases/srep-0000-map-ground.xml` | a flat `primitive="map"` ground facing the implicit camera: the raster basemap's red and blue halves land where the 2D map places them | 2 px |

## Open issues

- Terrain and buildings need a web-mercator map; a globe with terrain is not specified.
- The attribution plate is drawn into the drape; whether it should instead stay in screen space.

## References

- AWS Terrain Tiles (Terrarium): https://registry.opendata.aws/terrain-tiles/
- Mapbox Terrain-RGB: https://docs.mapbox.com/data/tilesets/reference/mapbox-terrain-rgb-v1/
- Protomaps basemap schema, `buildings` layer: https://docs.protomaps.com/basemaps/layers

## History

- 2026-09-29: first draft.
