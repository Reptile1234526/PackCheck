"""Generate a flat tray case for the RFID Backpack Checker as a STEP file."""

import cadquery as cq

# ── DIMENSIONS (mm) ──────────────────────────────────
WALL     = 2.0      # outer wall thickness
DIVIDER  = 2.0      # internal divider thickness
FLOOR    = 1.6      # bottom thickness
GAP      = 1.0      # clearance around components (per side)
CORNER_R = 3.0      # outer corner fillet
LID_T    = 1.6      # lid thickness
LID_LIP  = 3.0      # lid lip depth
LIP_WALL = 1.2      # lid lip frame wall
TOL      = 0.3      # lid tolerance

# Components: (length, width, height) in mm
BAT_L, BAT_W, BAT_H   = 153.0, 68.8, 29.5
PI_L,  PI_W,  PI_H     = 85.6, 56.5, 17.0
RFID_L, RFID_W, RFID_H = 102.0, 76.0, 25.0   # *** VERIFY ***

# Pi mounting holes (from board corner)
PI_STD_H  = 4.0     # standoff height
PI_STD_OD = 5.5     # standoff outer diameter
PI_HOLE_D = 2.2     # M2.5 self-tap pilot hole
PI_HOLES  = [(3.5, 3.5), (61.5, 3.5), (61.5, 52.5), (3.5, 52.5)]

# Charging slot
CHARGE_W = 14.0
CHARGE_H = 8.0

# Cable slot between compartments
CABLE_W  = 12.0
CABLE_H  = 10.0

# ── LAYOUT (flat, components side by side) ────────────
# Arrangement (top view):
#   +-----------------------------+
#   |          Battery            |
#   |         153 x 68.8         |
#   +-----------------------------+
#   |   RFID        |     Pi     |
#   |  102 x 76     |  85.6x56.5|
#   +-----------------------------+
#
# All pockets are the same depth = tallest component (battery)

# Pocket sizes (component + gap on each side)
bat_pocket_l = BAT_L + 2 * GAP
bat_pocket_w = BAT_W + 2 * GAP

rfid_pocket_l = RFID_L + 2 * GAP
rfid_pocket_w = RFID_W + 2 * GAP

pi_pocket_l = PI_L + 2 * GAP
pi_pocket_w = PI_W + 2 * GAP

# Bottom row width = RFID + divider + Pi
bottom_row_l = rfid_pocket_l + DIVIDER + pi_pocket_l
# Use the wider of battery row or bottom row
int_l = max(bat_pocket_l, bottom_row_l)
# Depth = battery row + divider + bottom row height
bottom_row_w = max(rfid_pocket_w, pi_pocket_w)
int_w = bat_pocket_w + DIVIDER + bottom_row_w

# Internal height = tallest component
int_h = BAT_H + GAP  # battery is tallest

# Outer dimensions
ext_l = int_l + 2 * WALL
ext_w = int_w + 2 * WALL
ext_h = int_h + FLOOR

# ── TRAY ──────────────────────────────────────────────

# Outer shell
tray = (
    cq.Workplane("XY")
    .box(ext_l, ext_w, ext_h, centered=False)
    # Fillet vertical edges
    .edges("|Z")
    .fillet(CORNER_R)
)

# Hollow out interior (cut from top)
tray = (
    tray.faces(">Z").workplane()
    .center(-ext_l / 2 + WALL, -ext_w / 2 + WALL)
    .rect(int_l, int_w, centered=False)
    .cutBlind(-int_h)
)

# ── DIVIDER: horizontal (separates battery row from bottom row) ──
div_h_z = FLOOR  # starts at floor
div_h_y = WALL + bat_pocket_w  # position along Y
tray = (
    tray.faces("<Z").workplane(offset=FLOOR)
    .center(-ext_l / 2 + WALL, -ext_w / 2 + div_h_y)
    .rect(int_l, DIVIDER, centered=False)
    .extrude(int_h)
)

# ── DIVIDER: vertical (separates RFID from Pi in bottom row) ──
div_v_x = WALL + rfid_pocket_l  # position along X
div_v_y = WALL + bat_pocket_w + DIVIDER  # start of bottom row
tray = (
    tray.faces("<Z").workplane(offset=FLOOR)
    .center(-ext_l / 2 + div_v_x, -ext_w / 2 + div_v_y)
    .rect(DIVIDER, bottom_row_w, centered=False)
    .extrude(int_h)
)

# ── RAISED FLOOR for Pi (so it sits higher, closer to top) ──
pi_raise = BAT_H - PI_H - PI_STD_H  # raise floor so Pi top ≈ case top
if pi_raise > 0:
    pi_pocket_x = WALL + rfid_pocket_l + DIVIDER
    pi_pocket_y = WALL + bat_pocket_w + DIVIDER
    tray = (
        tray.faces("<Z").workplane(offset=FLOOR)
        .center(-ext_l / 2 + pi_pocket_x, -ext_w / 2 + pi_pocket_y)
        .rect(pi_pocket_l, pi_pocket_w, centered=False)
        .extrude(pi_raise)
    )

# ── RAISED FLOOR for RFID ──
rfid_raise = BAT_H - RFID_H
if rfid_raise > 0:
    rfid_pocket_x = WALL
    rfid_pocket_y = WALL + bat_pocket_w + DIVIDER
    tray = (
        tray.faces("<Z").workplane(offset=FLOOR)
        .center(-ext_l / 2 + rfid_pocket_x, -ext_w / 2 + rfid_pocket_y)
        .rect(rfid_pocket_l, rfid_pocket_w, centered=False)
        .extrude(rfid_raise)
    )

# ── Pi STANDOFFS ──
pi_origin_x = WALL + rfid_pocket_l + DIVIDER + GAP
pi_origin_y = WALL + bat_pocket_w + DIVIDER + GAP
standoff_base_z = FLOOR + (pi_raise if pi_raise > 0 else 0)

for hx, hy in PI_HOLES:
    sx = pi_origin_x + hx
    sy = pi_origin_y + hy
    # Standoff post
    tray = (
        tray.faces("<Z").workplane(offset=standoff_base_z)
        .center(-ext_l / 2 + sx, -ext_w / 2 + sy)
        .circle(PI_STD_OD / 2)
        .extrude(PI_STD_H)
    )
    # Screw hole
    tray = (
        tray.faces("<Z").workplane(offset=standoff_base_z)
        .center(-ext_l / 2 + sx, -ext_w / 2 + sy)
        .circle(PI_HOLE_D / 2)
        .cutBlind(PI_STD_H + 1)
    )

# ── CABLE SLOTS in dividers (using box cuts) ──
# Slot through horizontal divider (battery ↔ bottom row)
slot_z = FLOOR + (int_h - CABLE_H) / 2
h_div_y = WALL + bat_pocket_w
cable_slot_h = (
    cq.Workplane("XY")
    .transformed(offset=((ext_l - CABLE_W) / 2, h_div_y - 0.5, slot_z))
    .box(CABLE_W, DIVIDER + 1, CABLE_H, centered=False)
)
tray = tray.cut(cable_slot_h)

# Slot through vertical divider (RFID ↔ Pi)
v_div_x = WALL + rfid_pocket_l
v_slot_y = WALL + bat_pocket_w + DIVIDER + (bottom_row_w - CABLE_W) / 2
cable_slot_v = (
    cq.Workplane("XY")
    .transformed(offset=(v_div_x - 0.5, v_slot_y, slot_z))
    .box(DIVIDER + 1, CABLE_W, CABLE_H, centered=False)
)
tray = tray.cut(cable_slot_v)

# ── CHARGING SLOT on battery end wall ──
charge_z = FLOOR + BAT_H * 0.4 - CHARGE_H / 2
bat_center_y = WALL + bat_pocket_w / 2
charge_slot = (
    cq.Workplane("XY")
    .transformed(offset=(-0.5, bat_center_y - CHARGE_W / 2, charge_z))
    .box(WALL + 1, CHARGE_W, CHARGE_H, centered=False)
)
tray = tray.cut(charge_slot)

# ── LID ──────────────────────────────────────────────
lid = (
    cq.Workplane("XY")
    .box(ext_l, ext_w, LID_T, centered=False)
    .edges("|Z")
    .fillet(CORNER_R)
)

# Lid lip (frame that fits inside case walls)
lip_inset = WALL + TOL
lip_outer_l = ext_l - 2 * lip_inset
lip_outer_w = ext_w - 2 * lip_inset
lip_inner_l = lip_outer_l - 2 * LIP_WALL
lip_inner_w = lip_outer_w - 2 * LIP_WALL

lip = (
    cq.Workplane("XY")
    .center(ext_l / 2, ext_w / 2)
    .rect(lip_outer_l, lip_outer_w)
    .rect(lip_inner_l, lip_inner_w)
    .extrude(-LID_LIP)
)

lid = lid.union(lip)

# Move lid to sit on top of tray (with small gap for visualization)
lid = lid.translate((0, 0, ext_h + 2))

# ── EXPORT ────────────────────────────────────────────
out_dir = "/Users/avibuxbaum/projects/rfid-backpack-checker/case"

# Export tray
cq.exporters.export(tray, f"{out_dir}/tray.step")

# Export lid
cq.exporters.export(lid, f"{out_dir}/lid.step")

# Also export combined for reference
combined = tray.union(lid)
cq.exporters.export(combined, f"{out_dir}/case_complete.step")

print(f"Done! Overall: {ext_l:.0f} x {ext_w:.0f} x {ext_h + LID_T:.0f} mm")
print(f"  Battery pocket: {bat_pocket_l:.0f} x {bat_pocket_w:.0f} x {BAT_H:.0f} mm")
print(f"  RFID pocket:    {rfid_pocket_l:.0f} x {rfid_pocket_w:.0f} x {RFID_H:.0f} mm")
print(f"  Pi pocket:      {pi_pocket_l:.0f} x {pi_pocket_w:.0f} x {PI_H:.0f} mm")
print(f"\nFiles:")
print(f"  {out_dir}/tray.step")
print(f"  {out_dir}/lid.step")
print(f"  {out_dir}/case_complete.step")
