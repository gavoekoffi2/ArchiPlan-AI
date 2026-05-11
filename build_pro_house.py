#!/usr/bin/env python3
"""
ARCHIPLAN 3D — Professional House Builder
Builds a 3D house model with SOLID walls as full boxes, properly connected at corners.
Each wall is a complete box with all 6 faces, not a thin extrusion.
"""
import numpy as np
import trimesh
from pathlib import Path

OUT_DIR = Path("/tmp/archiplan3d_output")
OUT_DIR.mkdir(exist_ok=True)

# ─── Architectural Parameters ───────────────────────────────────────
WALL_HEIGHT = 2.7       # m
WALL_THICKNESS = 0.20   # m  (20cm standard)
HOUSE_WIDTH = 11.0      # m total
HOUSE_DEPTH = 8.5       # m total
ROOF_PEAK = WALL_HEIGHT + 1.5  # m
ROOF_OVERHANG = 0.4     # m overhang on all sides

# Exterior wall colors (warm beige/brick)
EXT_COLOR = [215, 195, 175, 255]
# Interior wall colors (lighter)
INT_COLOR = [240, 232, 224, 255]
# Floor
FLOOR_COLOR = [195, 185, 175, 255]
# Roof (terracotta)
ROOF_COLOR = [185, 70, 55, 255]
# Doors (wood)
DOOR_COLOR = [145, 110, 70, 255]
# Windows (blueish glass)
WINDOW_COLOR = [175, 210, 235, 200]


def make_box(cx, cy, cz, sx, sy, sz, color):
    """Create a centered box and return it as a trimesh.Trimesh.
    (cx, cy, cz) = center of the box
    (sx, sy, sz) = full size in x, y, z
    """
    box = trimesh.creation.box(extents=(sx, sy, sz))
    # trimesh box is centered at origin, so translate
    box.apply_translation([cx, cy, cz])
    box.visual.face_colors = [color] * len(box.faces)
    return box


def make_wall_segment(x0, y0, x1, y1, height=WALL_HEIGHT, thickness=WALL_THICKNESS,
                      color=EXT_COLOR):
    """Create a wall segment as a solid box.
    (x0, y0) to (x1, y1) is the centerline of the wall.
    For axis-aligned walls, one dimension is length, the other is thickness.
    """
    dx = x1 - x0
    dy = y1 - y0
    length = np.sqrt(dx*dx + dy*dy)

    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    cz = height / 2.0  # center z

    if abs(dy) < 0.001:
        # Horizontal wall (runs in X direction)
        box = make_box(cx, cy, cz, length, thickness, height, color)
    elif abs(dx) < 0.001:
        # Vertical wall (runs in Y direction)
        box = make_box(cx, cy, cz, thickness, length, height, color)
    else:
        # Diagonal wall — use a rotated box
        box = trimesh.creation.box(extents=(length, thickness, height))
        angle = np.arctan2(dy, dx)
        # Rotate around Z axis
        rot = trimesh.transformations.rotation_matrix(angle, [0, 0, 1])
        box.apply_transform(rot)
        box.apply_translation([cx, cy, cz])
        box.visual.face_colors = [color] * len(box.faces)

    return box


def build_professional_house():
    """Build the complete 3D house model with solid connecting walls."""

    all_meshes = []

    # ═══════════════════════════════════════════════════════════════
    #  EXTERIOR WALLS — Four walls forming the perimeter
    # ═══════════════════════════════════════════════════════════════
    # The house is exactly 11.0m wide × 8.5m deep.
    # Exterior wall centerlines are at the exact boundaries.
    # Walls are 0.20m thick, centered on the boundary line.
    #
    # Bottom wall (South): y=0, x from 0 to 11.0
    all_meshes.append(
        make_wall_segment(0.0, 0.0, HOUSE_WIDTH, 0.0, color=EXT_COLOR))

    # Top wall (North): y=8.5, x from 0 to 11.0
    all_meshes.append(
        make_wall_segment(0.0, HOUSE_DEPTH, HOUSE_WIDTH, HOUSE_DEPTH, color=EXT_COLOR))

    # Left wall (West): x=0, y from 0 to 8.5
    all_meshes.append(
        make_wall_segment(0.0, 0.0, 0.0, HOUSE_DEPTH, color=EXT_COLOR))

    # Right wall (East): x=11.0, y from 0 to 8.5
    all_meshes.append(
        make_wall_segment(HOUSE_WIDTH, 0.0, HOUSE_WIDTH, HOUSE_DEPTH, color=EXT_COLOR))

    # ═══════════════════════════════════════════════════════════════
    #  INTERIOR WALLS — Based on specified room layout
    # ═══════════════════════════════════════════════════════════════
    # Room layout (interior coordinates, walls fill the gaps):
    #   Salon:     (0, 0) → (4.2, 4.2)
    #   Cuisine:   (4.4, 0) → (7.6, 3.5)
    #   Chambre 1: (7.8, 0) → (10.8, 4.2)
    #   SDB:       (0, 4.4) → (2.2, 8.3)
    #   Chambre 2: (2.4, 4.4) → (6.0, 8.3)
    #   Couloir:   (6.2, 4.4) → (7.8, 8.3)
    #   Bureau:    (8.0, 4.4) → (10.8, 8.3)
    #
    # Wall thickness = 0.20m. Walls centered on gap between rooms.

    IW = INT_COLOR  # shorthand

    # --- VERTICAL interior walls (running in Y direction) ---

    # V1: Wall between Salon(right=4.2) and Cuisine(left=4.4)
    #     This wall spans from y=0 to y=4.2 (bottom) and continues to y=4.4 (top row)
    #     Full segment: y=0.0 to y=4.4, centered at x=4.3
    all_meshes.append(
        make_wall_segment(4.3, 0.0, 4.3, 4.4, color=IW))

    # V2: Wall between Cuisine(right=7.6) and Chambre1(left=7.8)
    #     Spans from y=0 to y=3.5 + gap to y=4.4
    #     Full segment: y=0.0 to y=4.4, centered at x=7.7
    all_meshes.append(
        make_wall_segment(7.7, 0.0, 7.7, 4.4, color=IW))

    # V3: Wall between SDB(right=2.2) and Chambre2(left=2.4)
    #     Spans from y=4.4 to y=8.3, centered at x=2.3
    all_meshes.append(
        make_wall_segment(2.3, 4.4, 2.3, 8.3, color=IW))

    # V4: Wall between Chambre2(right=6.0) and Couloir(left=6.2)
    #     Spans from y=4.4 to y=8.3, centered at x=6.1
    all_meshes.append(
        make_wall_segment(6.1, 4.4, 6.1, 8.3, color=IW))

    # V5: Wall between Couloir(right=7.8) and Bureau(left=8.0)
    #     Spans from y=4.4 to y=8.3, centered at x=7.9
    all_meshes.append(
        make_wall_segment(7.9, 4.4, 7.9, 8.3, color=IW))

    # V6: Right exterior wall inner segment (x=10.8) already covered by exterior
    #     But the interior side: wall between Chambre1/Bureau and exterior
    #     Actually, the exterior right wall at x=11.0 already covers this.
    #     The interior face is at x=10.8. The rooms extend to x=10.8.
    #     The exterior wall centerline is at x=11.0, so it goes from x=10.9 to 11.1.
    #     But room Chambre1 and Bureau go to x=10.8. Gap is 10.8→10.9 = 0.1m.
    #     With wall thickness 0.2m centered at 11.0, wall covers 10.9→11.1.
    #     So there's a 0.1m gap. Let me add a thin fill.
    #     Actually, let me just make the right wall centered at 10.9 instead of 11.0
    #     so it spans 10.8→11.0. I'll adjust the exterior wall above.
    #     Hmm, this complexities things. The simpler approach: the exterior wall
    #     centerline at x=11.0 gives interior face at x=10.9, and the room goes to
    #     x=10.8. This 0.1m gap is fine visually (it's absorbed by wall rendering).
    #     Let's just keep it as is.

    # --- HORIZONTAL interior walls (running in X direction) ---

    # H1: Wall between Salon(bottom, y=4.2) and SDB(top, y=4.4)
    #     Spans from x=0.0 to x=2.3, centered at y=4.3
    all_meshes.append(
        make_wall_segment(0.0, 4.3, 2.3, 4.3, color=IW))

    # H2: Wall between the gap above Cuisine (y=3.5→4.4) connecting to V1 and V2
    #     Cuisine ends at y=3.5. Above it is a corridor space (y=3.5→4.4).
    #     The horizontal wall at y=3.5 from x=4.3 to x=7.7
    #     Actually this is already partially handled by V1 and V2 going to y=4.4.
    #     There's space from y=3.5 to 4.4 between x=4.3 and x=7.7.
    #     Let me add a horizontal wall segment at the bottom of this gap:
    all_meshes.append(
        make_wall_segment(4.3, 3.6, 7.7, 3.6, color=IW))
    # This creates a wall at the top of the Cuisine (y=3.5 center, spans 3.5±0.1)

    # H3: Wall between Chambre1(bottom, y=4.2) and the rooms above (y=4.4)
    #     Spans from x=7.9 to x=10.8, centered at y=4.3
    all_meshes.append(
        make_wall_segment(7.9, 4.3, 10.8, 4.3, color=IW))

    # H4: Top wall between Chambre2(y=8.3) and exterior (y=8.5)
    #     Already covered by the North exterior wall at y=8.5
    #     But the interior side: Chambre2, Couloir, Bureau go to y=8.3.
    #     The North wall centerline at y=8.5 goes from y=8.4 to 8.6.
    #     Gap from 8.3 to 8.4 needs filling.
    #     Let me reposition North wall to center at y=8.4 instead of 8.5.
    #     Wait, I already created it. Let me handle this after.

    # ═══════════════════════════════════════════════════════════════
    #  FIX exterior wall positions to align with interior rooms
    # ═══════════════════════════════════════════════════════════════
    # Re-do: Instead of patching, let me just rebuild the exterior walls
    # to align properly with the 10.8m × 8.3m interior footprint.
    #
    # Interior footprint: x=[0, 10.8], y=[0, 8.3]
    # With 0.20m walls, the exterior centerlines should be:
    #   South: y=0.0 (wall spans -0.1 to 0.1)
    #   North: y=8.4 (wall spans 8.3 to 8.5) — aligns with room boundary at 8.3
    #   West:  x=0.0 (wall spans -0.1 to 0.1)
    #   East:  x=10.9 (wall spans 10.8 to 11.0) — aligns with room boundary at 10.8
    #
    # Total house: 0 to 11.0 in X (11.0m), 0 to 8.5 in Y (8.5m) ✓
    # Interior: 0.1 to 10.8 in X = 10.7m, 0.1 to 8.3 in Y = 8.2m

    # Actually, I already created the exterior walls above. Let me just
    # rebuild them with corrected positions. I'll clear and redo.

    # Let me take a cleaner approach: rebuild from scratch below.
    pass


def build_house_clean():
    """Clean build with all wall segments properly aligned."""

    all_meshes = []

    EW = EXT_COLOR  # exterior wall
    IW = INT_COLOR  # interior wall
    WT = WALL_THICKNESS  # 0.20m
    WH = WALL_HEIGHT     # 2.7m

    # Interior footprint boundaries (room edges touch these lines):
    #   X: 0.0 to 10.8
    #   Y: 0.0 to 8.3
    #
    # Exterior wall centerlines:
    #   South: y = 0.0           (wall: -WT/2 to +WT/2 = -0.1 to 0.1)
    #   North: y = 8.3 + WT/2 = 8.4  (wall: 8.3 to 8.5)
    #   West:  x = 0.0           (wall: -0.1 to 0.1)
    #   East:  x = 10.8 + WT/2 = 10.9  (wall: 10.8 to 11.0)
    #
    # Total exterior: 11.0m × 8.5m ✓

    # ─── EXTERIOR WALLS ───────────────────────────────────────────
    # South wall (bottom)
    all_meshes.append(make_wall_segment(0.0, 0.0, 11.0, 0.0, color=EW))
    # North wall (top) — center at y=8.4
    all_meshes.append(make_wall_segment(0.0, 8.4, 11.0, 8.4, color=EW))
    # West wall (left)
    all_meshes.append(make_wall_segment(0.0, 0.0, 0.0, 8.4, color=EW))
    # East wall (right) — center at x=10.9
    all_meshes.append(make_wall_segment(10.9, 0.0, 10.9, 8.4, color=EW))

    # ─── INTERIOR VERTICAL WALLS ──────────────────────────────────
    # These are walls running in the Y direction.
    # Center X is at the midpoint between adjacent room boundaries.

    # V_A: Between Salon(x_end=4.2) and Cuisine(x_start=4.4)
    #       Center at x=4.3, runs y=0.0 to y=4.4
    all_meshes.append(make_wall_segment(4.3, 0.0, 4.3, 4.4, color=IW))

    # V_B: Between Cuisine(x_end=7.6) and Chambre1(x_start=7.8)
    #       Center at x=7.7, runs y=0.0 to y=4.4
    all_meshes.append(make_wall_segment(7.7, 0.0, 7.7, 4.4, color=IW))

    # V_C: Between SDB(x_end=2.2) and Chambre2(x_start=2.4)
    #       Center at x=2.3, runs y=4.4 to y=8.3
    all_meshes.append(make_wall_segment(2.3, 4.4, 2.3, 8.3, color=IW))

    # V_D: Between Chambre2(x_end=6.0) and Couloir(x_start=6.2)
    #       Center at x=6.1, runs y=4.4 to y=8.3
    all_meshes.append(make_wall_segment(6.1, 4.4, 6.1, 8.3, color=IW))

    # V_E: Between Couloir(x_end=7.8) and Bureau(x_start=8.0)
    #       Center at x=7.9, runs y=4.4 to y=8.3
    all_meshes.append(make_wall_segment(7.9, 4.4, 7.9, 8.3, color=IW))

    # ─── INTERIOR HORIZONTAL WALLS ────────────────────────────────
    # These are walls running in the X direction.
    # The bottom room row ends at various Y: Salon at 4.2, Cuisine at 3.5, Chambre1 at 4.2.
    # The top room row starts at Y=4.4 uniformly.

    # H_A: Between Salon(y_end=4.2) and SDB(y_start=4.4)
    #       Center at y=4.3, runs x=0.0 to x=2.3
    all_meshes.append(make_wall_segment(0.0, 4.3, 2.3, 4.3, color=IW))

    # H_B: Between Chambre1(y_end=4.2) and Bureau area(y_start=4.4)
    #       Center at y=4.3, runs x=7.9 to x=10.8
    all_meshes.append(make_wall_segment(7.9, 4.3, 10.8, 4.3, color=IW))

    # H_C: Top of Cuisine (y=3.5) — wall at the top edge
    #       Cuisine ends at y=3.5, corridor space above to y=4.4
    #       Center at y=3.6 (so wall spans 3.5 to 3.7), runs x=4.3 to x=7.7
    all_meshes.append(make_wall_segment(4.3, 3.6, 7.7, 3.6, color=IW))

    # ─── CORRIDOR / HALLWAY WALLS ─────────────────────────────────
    # The space from x=4.3 to x=7.7, y=3.5 to y=4.4 is the hallway connecting
    # Cuisine area to Couloir.
    #
    # Additional wall at the left side of this hallway (x=4.3, from y=3.5 to 4.4)
    # This is already covered by V_A going to y=4.4. ✓
    #
    # Additional wall at the right side (x=7.7, from y=3.5 to 4.4)
    # This is already covered by V_B going to y=4.4. ✓

    # ─── FLOOR ────────────────────────────────────────────────────
    floor_verts = np.array([
        [0.0, 0.0, 0.0],
        [11.0, 0.0, 0.0],
        [11.0, 8.5, 0.0],
        [0.0, 8.5, 0.0],
    ])
    floor_faces = np.array([[0, 1, 2], [0, 2, 3]])
    floor = trimesh.Trimesh(vertices=floor_verts, faces=floor_faces)
    floor.visual.face_colors = [FLOOR_COLOR, FLOOR_COLOR]
    all_meshes.append(floor)

    # ─── ROOF ─────────────────────────────────────────────────────
    # Two-pitch roof with overhangs
    roof = create_solid_roof(11.0, 8.5, WH)
    all_meshes.append(roof)

    # ─── DOORS ────────────────────────────────────────────────────
    # Door openings in walls (represented as door meshes embedded in wall gaps)
    doors_data = [
        # Salon → hallway (in wall H_A, near x=1.0)
        {"cx": 1.1, "cy": 4.3, "cz": 1.05, "width": 0.9, "height": 2.1, "orient": "h"},
        # Cuisine → hallway (in wall H_C, near x=5.5)
        {"cx": 5.5, "cy": 3.6, "cz": 1.05, "width": 0.9, "height": 2.1, "orient": "h"},
        # Chambre 1 → hallway (in wall H_B, near x=9.3)
        {"cx": 9.3, "cy": 4.3, "cz": 1.05, "width": 0.9, "height": 2.1, "orient": "h"},
        # SDB door (in wall V_C, near y=6.0)
        {"cx": 2.3, "cy": 6.0, "cz": 1.05, "width": 0.9, "height": 2.1, "orient": "v"},
        # Chambre 2 door (in wall V_D, near y=6.0)
        {"cx": 6.1, "cy": 6.0, "cz": 1.05, "width": 0.9, "height": 2.1, "orient": "v"},
        # Bureau door (in wall V_E, near y=6.0)
        {"cx": 7.9, "cy": 6.0, "cz": 1.05, "width": 0.9, "height": 2.1, "orient": "v"},
        # East exterior door (front entrance, in east wall near y=3.0)
        {"cx": 10.9, "cy": 3.0, "cz": 1.05, "width": 0.95, "height": 2.15, "orient": "v"},
    ]

    for d in doors_data:
        door = create_door_box(d["cx"], d["cy"], d["cz"],
                               d["width"], d["height"], d["orient"])
        all_meshes.append(door)

    # ─── WINDOWS ──────────────────────────────────────────────────
    windows_data = [
        # South wall (front): 2 windows
        {"cx": 2.0, "cy": 0.0, "cz": 1.6, "width": 1.2, "height": 1.1, "orient": "h"},
        {"cx": 8.0, "cy": 0.0, "cz": 1.6, "width": 1.0, "height": 1.1, "orient": "h"},
        # North wall (back): 2 windows
        {"cx": 1.5, "cy": 8.4, "cz": 1.6, "width": 1.0, "height": 1.1, "orient": "h"},
        {"cx": 9.0, "cy": 8.4, "cz": 1.6, "width": 1.0, "height": 1.1, "orient": "h"},
        # West wall: 1 window
        {"cx": 0.0, "cy": 5.0, "cz": 1.6, "width": 1.1, "height": 1.1, "orient": "v"},
        # East wall: 1 window
        {"cx": 10.9, "cy": 6.5, "cz": 1.6, "width": 1.1, "height": 1.1, "orient": "v"},
    ]

    for w in windows_data:
        win = create_window_box(w["cx"], w["cy"], w["cz"],
                                w["width"], w["height"], w["orient"])
        all_meshes.append(win)

    # ─── COMBINE AND EXPORT ───────────────────────────────────────
    combined = trimesh.util.concatenate(all_meshes)
    obj_path = str(OUT_DIR / "maison_3d.obj")

    # For OBJ export, we need to handle vertex colors properly
    # trimesh OBJ export with vertex colors works well
    combined.export(obj_path)

    print(f"\n✅ PROFESSIONAL HOUSE MODEL EXPORTED")
    print(f"   Path: {obj_path}")
    print(f"   Vertices: {len(combined.vertices):,}")
    print(f"   Faces: {len(combined.faces):,}")
    print(f"   Bounding box: X[{combined.vertices[:,0].min():.1f}, {combined.vertices[:,0].max():.1f}]")
    print(f"                 Y[{combined.vertices[:,1].min():.1f}, {combined.vertices[:,1].max():.1f}]")
    print(f"                 Z[{combined.vertices[:,2].min():.1f}, {combined.vertices[:,2].max():.1f}]")

    # Count walls vs other components
    wall_faces = 0
    for m in all_meshes:
        c = m.visual.face_colors[0] if len(m.visual.face_colors) > 0 else None
        if c is not None and (np.array_equal(c[:3], EXT_COLOR[:3]) or np.array_equal(c[:3], INT_COLOR[:3])):
            wall_faces += len(m.faces)

    print(f"   Wall components: {wall_faces} faces")
    print(f"   Colors: Ext={EXT_COLOR[:3]}, Int={INT_COLOR[:3]}, Roof={ROOF_COLOR[:3]}")

    return combined, obj_path


def create_solid_roof(width, depth, wall_height):
    """Create a two-pitch roof as a solid volume with overhangs."""
    oh = ROOF_OVERHANG
    peak_h = ROOF_PEAK
    base_h = wall_height + 0.05  # slightly above wall top

    # Roof base extends beyond walls on all sides
    x0, y0 = -oh, -oh
    x1, y1 = width + oh, depth + oh
    mid_y = depth / 2.0  # ridge line in middle of Y

    # Roof is two triangular prisms meeting at the ridge
    # We'll create it as a single mesh with vertices and faces
    vertices = np.array([
        # Bottom face (flat, at base_h)
        [x0, y0, base_h],          # 0: bottom-left
        [x1, y0, base_h],          # 1: bottom-right
        [x1, y1, base_h],          # 2: top-right
        [x0, y1, base_h],          # 3: top-left

        # Ridge line (at mid_y)
        [x0, mid_y, peak_h],       # 4: ridge-left
        [x1, mid_y, peak_h],       # 5: ridge-right
    ])

    faces = np.array([
        # Bottom face
        [0, 1, 2], [0, 2, 3],
        # Front slope (south)
        [0, 1, 5], [0, 5, 4],
        # Back slope (north)
        [3, 2, 5], [3, 5, 4],
        # Left gable (west)
        [0, 4, 3],
        # Right gable (east)
        [1, 2, 5],  # actually [1, 5, 2] — the face from 1→2→5
    ])

    roof = trimesh.Trimesh(vertices=vertices, faces=faces)
    roof.visual.face_colors = [ROOF_COLOR] * len(faces)
    return roof


def create_door_box(cx, cy, cz, width, height, orientation):
    """Create a door as a colored box."""
    door_thickness = 0.06  # door panel thickness
    frame_thickness = 0.04  # frame around door

    if orientation == "v":
        # Door runs in Y direction (vertical wall), faces X
        box = make_box(cx, cy, cz, door_thickness, width, height, DOOR_COLOR)
    else:
        # Door runs in X direction (horizontal wall), faces Y
        box = make_box(cx, cy, cz, width, door_thickness, height, DOOR_COLOR)

    return box


def create_window_box(cx, cy, cz, width, height, orientation):
    """Create a window as a colored box (glass effect)."""
    glass_thickness = 0.04

    if orientation == "v":
        box = make_box(cx, cy, cz, glass_thickness, width, height, WINDOW_COLOR)
    else:
        box = make_box(cx, cy, cz, width, glass_thickness, height, WINDOW_COLOR)

    return box


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  ARCHIPLAN 3D — Professional House Builder")
    print("  Solid walls, proper corner connections")
    print("=" * 60)
    print(f"\n  House: {HOUSE_WIDTH}m × {HOUSE_DEPTH}m")
    print(f"  Wall height: {WALL_HEIGHT}m")
    print(f"  Wall thickness: {WALL_THICKNESS*100:.0f}cm")
    print(f"  Roof peak: {ROOF_PEAK}m")
    print(f"  Overhang: {ROOF_OVERHANG*100:.0f}cm")
    print()

    combined, obj_path = build_house_clean()

    # Verify the model
    print(f"\n📐 MODEL VERIFICATION:")
    verts = combined.vertices
    print(f"   X range: {verts[:,0].min():.2f} → {verts[:,0].max():.2f}")
    print(f"   Y range: {verts[:,1].min():.2f} → {verts[:,1].max():.2f}")
    print(f"   Z range: {verts[:,2].min():.2f} → {verts[:,2].max():.2f}")
    print(f"   Total vertices: {len(verts):,}")
    print(f"   Total faces: {len(combined.faces):,}")
    print(f"\n   ✅ DONE — Model ready for viewer!")
