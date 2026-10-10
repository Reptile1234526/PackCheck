"""
RFID Backpack Checker — Case Design Script for Fusion 360

Creates a two-piece stacking enclosure for:
  - Baseus Bipow PPBD2 20000mAh battery  (bottom)
  - Raspberry Pi 3 Model B               (middle)
  - JENCE J4212U UHF RFID reader          (top — antenna faces up)

To run:
  1. Open Fusion 360 → create a new empty design
  2. UTILITIES tab → ADD-INS → Scripts tab
  3. Click green [+] next to "My Scripts" → browse to this folder
  4. Select CaseDesign → click Run

Printing (Prusa Core 1, PLA):
  - Case Bottom: print upright, 0.2 mm layers, 20-30 % infill, 3 walls.
    Shelves bridge ~78 mm — no supports needed with good cooling.
  - Lid: print UPSIDE-DOWN (flat top on bed, lip pointing up).
"""

import adsk.core, adsk.fusion, traceback


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('Create a new design first.')
            return

        root = design.rootComponent

        # ── helpers ───────────────────────────────────────

        def cm(mm_val):
            """Convert mm to cm (Fusion internal unit)."""
            return mm_val / 10.0

        def pt(x, y, z=0.0):
            return adsk.core.Point3D.create(x, y, z)

        def vi(cm_val):
            return adsk.core.ValueInput.createByReal(cm_val)

        NEW  = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        JOIN = adsk.fusion.FeatureOperations.JoinFeatureOperation
        CUT  = adsk.fusion.FeatureOperations.CutFeatureOperation

        def offset_plane(comp, z_cm):
            inp = comp.constructionPlanes.createInput()
            inp.setByOffset(comp.xYConstructionPlane, vi(z_cm))
            return comp.constructionPlanes.add(inp)

        def rect_sketch(comp, plane, x1, y1, x2, y2):
            s = comp.sketches.add(plane)
            s.sketchCurves.sketchLines.addTwoPointRectangle(pt(x1, y1), pt(x2, y2))
            return s, s.profiles.item(0)

        def circle_sketch(comp, plane, cx, cy, r):
            s = comp.sketches.add(plane)
            s.sketchCurves.sketchCircles.addByCenterRadius(pt(cx, cy), r)
            return s, s.profiles.item(0)

        # ── DIMENSIONS (all in mm) ────────────────────────
        # Adjust these to match your parts, then re-run.

        WALL      = 2.0       # shell wall thickness
        FLOOR     = 1.6       # bottom plate thickness
        GAP       = 1.0       # clearance around parts
        SHELF     = 2.0       # internal shelf thickness
        CORNER_R  = 3.0       # outer fillet radius
        TOL       = 0.3       # lid tolerance (per side)
        LID_T     = 1.6       # lid plate thickness
        LID_LIP   = 5.0       # lid lip insertion depth
        LIP_WALL  = 1.5       # lid lip frame wall thickness

        # Baseus Bipow PPBD2-1W20  (L x W x H)
        BAT_L = 153.0;  BAT_W = 68.8;  BAT_H = 29.5

        # Raspberry Pi 3 Model B
        PI_L = 85.6;   PI_W = 56.5;   PI_H = 17.0
        PI_STD_H  = 5.0       # standoff height
        PI_STD_OD = 6.0       # standoff outer diameter
        PI_HOLE_D = 2.2       # M2.5 self-tap pilot hole
        PI_HOLES  = [          # mounting holes from board corner
            (3.5,  3.5),
            (61.5, 3.5),
            (61.5, 52.5),
            (3.5,  52.5),
        ]

        # JENCE J4212U  *** MEASURE YOURS — these are approximate ***
        RFID_L = 102.0;  RFID_W = 76.0;  RFID_H = 25.0

        # Cable pass-through and charging slot
        CABLE_R   = 6.0       # cable hole radius in shelves
        CHARGE_W  = 14.0      # charging slot width (USB-C)
        CHARGE_H  = 8.0       # charging slot height

        # ── COMPUTED LAYOUT ───────────────────────────────

        int_l  = max(BAT_L, PI_L, RFID_L) + 2 * GAP
        int_w  = max(BAT_W, PI_W, RFID_W) + 2 * GAP
        ext_l  = int_l + 2 * WALL
        ext_w  = int_w + 2 * WALL

        # Z stack (mm above interior floor)
        z1    = BAT_H + GAP                   # shelf 1 bottom
        z1t   = z1 + SHELF                    # shelf 1 top
        zPi   = z1t + PI_STD_H                # Pi board bottom
        z2    = zPi + PI_H + GAP              # shelf 2 bottom
        z2t   = z2 + SHELF                    # shelf 2 top
        zI    = z2t + RFID_H + GAP            # interior top
        ext_h = zI + FLOOR                    # overall outer height

        # Component positions (centered, mm from outer origin)
        bat_x  = WALL + (int_l - BAT_L)  / 2
        bat_y  = WALL + (int_w - BAT_W)  / 2
        pi_x   = WALL + (int_l - PI_L)   / 2
        pi_y   = WALL + (int_w - PI_W)   / 2
        rfid_x = WALL + (int_l - RFID_L) / 2
        rfid_y = WALL + (int_w - RFID_W) / 2

        # ══════════════════════════════════════════════════
        #  CASE BOTTOM
        # ══════════════════════════════════════════════════

        caseOcc = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        case    = caseOcc.component
        case.name = 'Case Bottom'
        cExt    = case.features.extrudeFeatures

        # 1 — Outer solid
        _, prof = rect_sketch(case, case.xYConstructionPlane,
                              0, 0, cm(ext_l), cm(ext_w))
        body = cExt.addSimple(prof, vi(cm(ext_h)), NEW).bodies.item(0)
        body.name = 'Shell'

        # 2 — Fillet vertical corners
        vEdges = adsk.core.ObjectCollection.create()
        for e in body.edges:
            a, b = e.startVertex.geometry, e.endVertex.geometry
            if abs(a.x - b.x) < .001 and abs(a.y - b.y) < .001 and abs(a.z - b.z) > .01:
                vEdges.add(e)
        if vEdges.count:
            fi = case.features.filletFeatures.createInput()
            fi.addConstantRadiusEdgeSet(vEdges, vi(cm(CORNER_R)), True)
            case.features.filletFeatures.add(fi)

        # 3 — Hollow interior (cut from floor up through top)
        floorPl = offset_plane(case, cm(FLOOR))
        _, prof = rect_sketch(case, floorPl,
                              cm(WALL), cm(WALL),
                              cm(ext_l - WALL), cm(ext_w - WALL))
        ci = cExt.createInput(prof, CUT)
        ci.setDistanceExtent(False, vi(cm(zI)))
        cExt.add(ci)

        # 4 — Shelf 1 (separates battery from Pi)
        sh1Pl = offset_plane(case, cm(FLOOR + z1))
        _, prof = rect_sketch(case, sh1Pl,
                              cm(WALL), cm(WALL),
                              cm(ext_l - WALL), cm(ext_w - WALL))
        cExt.addSimple(prof, vi(cm(SHELF)), JOIN)

        # 5 — Cable hole through shelf 1
        _, prof = circle_sketch(case, sh1Pl,
                                cm(ext_l - WALL - 12), cm(ext_w / 2),
                                cm(CABLE_R))
        ci = cExt.createInput(prof, CUT)
        ci.setDistanceExtent(False, vi(cm(SHELF + 1)))
        cExt.add(ci)

        # 6 — Pi standoffs + screw holes on shelf 1
        stdPl = offset_plane(case, cm(FLOOR + z1t))
        for hx, hy in PI_HOLES:
            cx, cy = cm(pi_x + hx), cm(pi_y + hy)
            # Standoff post
            _, prof = circle_sketch(case, stdPl, cx, cy, cm(PI_STD_OD / 2))
            cExt.addSimple(prof, vi(cm(PI_STD_H)), JOIN)
            # Screw hole through standoff
            _, prof = circle_sketch(case, stdPl, cx, cy, cm(PI_HOLE_D / 2))
            ci = cExt.createInput(prof, CUT)
            ci.setDistanceExtent(False, vi(cm(PI_STD_H + 0.5)))
            cExt.add(ci)

        # 7 — Shelf 2 (separates Pi from RFID reader)
        sh2Pl = offset_plane(case, cm(FLOOR + z2))
        _, prof = rect_sketch(case, sh2Pl,
                              cm(WALL), cm(WALL),
                              cm(ext_l - WALL), cm(ext_w - WALL))
        cExt.addSimple(prof, vi(cm(SHELF)), JOIN)

        # 8 — Cable hole through shelf 2
        _, prof = circle_sketch(case, sh2Pl,
                                cm(ext_l - WALL - 12), cm(ext_w / 2),
                                cm(CABLE_R))
        ci = cExt.createInput(prof, CUT)
        ci.setDistanceExtent(False, vi(cm(SHELF + 1)))
        cExt.add(ci)

        # 9 — Charging-cable slot (x = 0 wall, at battery level)
        yzP = case.yZConstructionPlane
        s = case.sketches.add(yzP)
        sy = cm(ext_w / 2)
        sz = cm(FLOOR + BAT_H * 0.4)
        s.sketchCurves.sketchLines.addTwoPointRectangle(
            pt(sy - cm(CHARGE_W / 2), sz - cm(CHARGE_H / 2)),
            pt(sy + cm(CHARGE_W / 2), sz + cm(CHARGE_H / 2)))
        ci = cExt.createInput(s.profiles.item(0), CUT)
        ci.setDistanceExtent(False, vi(cm(WALL + 0.5)))
        cExt.add(ci)

        # ══════════════════════════════════════════════════
        #  LID
        # ══════════════════════════════════════════════════

        lidOcc = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        lid    = lidOcc.component
        lid.name = 'Lid'
        lExt   = lid.features.extrudeFeatures

        lidZ = cm(FLOOR + zI)

        # Lid plate
        lidPl = offset_plane(lid, lidZ)
        _, prof = rect_sketch(lid, lidPl, 0, 0, cm(ext_l), cm(ext_w))
        lidBody = lExt.addSimple(prof, vi(cm(LID_T)), NEW).bodies.item(0)
        lidBody.name = 'Lid'

        # Fillet lid corners
        vEdges = adsk.core.ObjectCollection.create()
        for e in lidBody.edges:
            a, b = e.startVertex.geometry, e.endVertex.geometry
            if abs(a.x - b.x) < .001 and abs(a.y - b.y) < .001 and abs(a.z - b.z) > .01:
                vEdges.add(e)
        if vEdges.count:
            fi = lid.features.filletFeatures.createInput()
            fi.addConstantRadiusEdgeSet(vEdges, vi(cm(CORNER_R)), True)
            lid.features.filletFeatures.add(fi)

        # Lid lip (press-fit frame extending downward into case)
        lipInset = WALL + TOL
        lipPl = offset_plane(lid, lidZ - cm(LID_LIP))
        s = lid.sketches.add(lipPl)
        # Outer lip boundary
        s.sketchCurves.sketchLines.addTwoPointRectangle(
            pt(cm(lipInset), cm(lipInset)),
            pt(cm(ext_l - lipInset), cm(ext_w - lipInset)))
        # Inner cutout (makes it a hollow frame)
        s.sketchCurves.sketchLines.addTwoPointRectangle(
            pt(cm(lipInset + LIP_WALL), cm(lipInset + LIP_WALL)),
            pt(cm(ext_l - lipInset - LIP_WALL), cm(ext_w - lipInset - LIP_WALL)))
        # Select the frame profile (has 2 boundary loops)
        frameProf = None
        for i in range(s.profiles.count):
            p = s.profiles.item(i)
            if p.profileLoops.count == 2:
                frameProf = p
                break
        if frameProf:
            # +0.1 mm ensures overlap with lid plate for solid join
            lExt.addSimple(frameProf, vi(cm(LID_LIP + 0.1)), JOIN)

        # ══════════════════════════════════════════════════
        #  REFERENCE BODIES  (toggle visibility to see fit)
        # ══════════════════════════════════════════════════

        refOcc = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        ref    = refOcc.component
        ref.name = 'References (toggle off for export)'
        rExt   = ref.features.extrudeFeatures

        # Battery
        batPl = offset_plane(ref, cm(FLOOR))
        _, prof = rect_sketch(ref, batPl,
                              cm(bat_x), cm(bat_y),
                              cm(bat_x + BAT_L), cm(bat_y + BAT_W))
        rExt.addSimple(prof, vi(cm(BAT_H)), NEW).bodies.item(0).name = 'Battery (ref)'

        # Raspberry Pi
        piPl = offset_plane(ref, cm(FLOOR + zPi))
        _, prof = rect_sketch(ref, piPl,
                              cm(pi_x), cm(pi_y),
                              cm(pi_x + PI_L), cm(pi_y + PI_W))
        rExt.addSimple(prof, vi(cm(PI_H)), NEW).bodies.item(0).name = 'Pi 3B (ref)'

        # RFID reader
        rfPl = offset_plane(ref, cm(FLOOR + z2t))
        _, prof = rect_sketch(ref, rfPl,
                              cm(rfid_x), cm(rfid_y),
                              cm(rfid_x + RFID_L), cm(rfid_y + RFID_W))
        rExt.addSimple(prof, vi(cm(RFID_H)), NEW).bodies.item(0).name = 'J4212U (ref)'

        # ══════════════════════════════════════════════════
        #  DONE
        # ══════════════════════════════════════════════════

        app.activeViewport.refresh()

        ui.messageBox(
            'Case generated!\n\n'
            f'Overall: {ext_l:.0f} x {ext_w:.0f} x {ext_h + LID_T:.0f} mm\n\n'
            'Layer stack (bottom to top):\n'
            f'  Floor ............ {FLOOR:.1f} mm\n'
            f'  Battery .......... {BAT_H:.1f} mm\n'
            f'  Shelf 1 .......... {SHELF:.1f} mm\n'
            f'  Pi standoffs ..... {PI_STD_H:.1f} mm\n'
            f'  Pi board ......... {PI_H:.1f} mm\n'
            f'  Shelf 2 .......... {SHELF:.1f} mm\n'
            f'  RFID reader ...... {RFID_H:.1f} mm\n'
            f'  Lid .............. {LID_T:.1f} mm\n\n'
            'Components in browser:\n'
            '  Case Bottom — main shell with shelves & standoffs\n'
            '  Lid — press-fit lid with alignment lip\n'
            '  References — toggle off before exporting STL\n\n'
            'IMPORTANT: Verify J4212U dimensions before printing!\n'
            f'Currently: {RFID_L:.0f} x {RFID_W:.0f} x {RFID_H:.0f} mm',
            'RFID Checker Case')

    except:
        if ui:
            ui.messageBox(f'Script error:\n{traceback.format_exc()}')
